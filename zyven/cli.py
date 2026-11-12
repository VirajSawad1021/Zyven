"""zyven command line.

  zyven analyze <repo>                         deterministic analysis + rules-only baseline
  zyven scout   <repo>                         AI: list user-level capabilities
  zyven compile <repo> --capability <name>     AI: spec -> adapter -> sandbox verify -> repair -> package
  zyven verify -- <command...> | --url URL     check ANY MCP server: schemas, tool poisoning, rug pulls, robustness
  zyven mcp [--print-config]                   verified skills as a stdio MCP server for Claude Code / Codex / any agent
  zyven export <skill> [--to DIR]              a verified skill as a standalone MCP server (no Zyven needed)
  zyven outdated [--fetch]                     skills whose library moved on upstream since they were verified
  zyven reassemble [skill|library ...]         rebuild skills with the current harness, rerun the gates (no model)
  zyven setup | zyven doctor                   build the sandbox image / check what is missing
  zyven sync [--scout]                         clone the pinned catalog repos (and optionally scout them)
  zyven board [--port N] [--board-dir DIR]     task board, site and APIs on one port
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

from zyven import paths
from zyven.ai.provider import ModelProvider
from zyven.ai.roles import scout
from zyven.ai.schemas import ScoutResult
from zyven.analysis.analyzer import analyze
from zyven.analysis.miner import baseline_candidates
from zyven.catalog.catalog import Catalog
from zyven.compiler.pipeline import compile_capability


def _workdir(repo: Path) -> Path:
    d = paths.home() / "runs" / repo.resolve().name
    d.mkdir(parents=True, exist_ok=True)
    return d


def cmd_analyze(args) -> None:
    a = analyze(args.repo)
    out = _workdir(Path(args.repo)) / "analysis.json"
    out.write_text(json.dumps(a.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
    pub = [s for s in a.symbols if s.is_public and not s.file.startswith("tests")]
    print(f"{Path(a.repo).name} @ {str(a.commit)[:7]} · license {a.license} · {len(a.modules)} modules · "
          f"{len(pub)} public symbols · {sum(t.test_count for t in a.tests)} tests")
    print("\nRules-only baseline candidates:")
    for c in baseline_candidates(a):
        print(f"  {c.score:5.2f}  {c.module:40} {', '.join(e.rsplit('.', 1)[-1] for e in c.entry_points)}")
    print(f"\nwrote {out}")


def cmd_scout(args) -> None:
    a = analyze(args.repo)
    p = ModelProvider.from_env(args.env)
    res = scout(p, a)
    out = _workdir(Path(args.repo)) / "scout.json"
    out.write_text(res.value.model_dump_json(indent=1), encoding="utf-8")
    for c in res.value.capabilities:
        print(f"* {c.name}: {c.title}\n    {c.description}\n    entry: {', '.join(c.entry_points)}")
    if res.resolved:
        print(f"\nresolved model references: {len(res.resolved)}")
    if res.dropped:
        print(f"rejected references: {res.dropped}")
    print(f"\nwrote {out}")


def cmd_sync(args) -> None:
    catalog = Catalog(paths.catalog_file(), paths.home())
    provider = ModelProvider.from_env(args.env) if args.scout else None
    for line in catalog.sync(provider, rescout=args.rescout):
        print(line)
    print(f"{len(catalog.repos)} catalog repos at their pinned commits in {paths.home() / 'repos'}")


def _role_providers(args) -> tuple[ModelProvider, dict[str, ModelProvider]]:
    """--agent picks who does everything; --architect/--compiler/--tester/--repair override single roles."""
    from zyven.ai.agent_provider import provider_for
    cache: dict[str, ModelProvider] = {}

    def get(choice: str) -> ModelProvider:
        if choice not in cache:
            cache[choice] = provider_for(choice, args.env)
        return cache[choice]

    main = get(args.agent or "model")
    roles = {r: get(getattr(args, r)) for r in ("architect", "compiler", "tester", "repair") if getattr(args, r)}
    for role, prov in {"all roles": main, **roles}.items():
        print(f"{role}: {prov.label}")
    return main, roles


def cmd_compile(args) -> None:
    a = analyze(args.repo)
    p, roles = _role_providers(args)
    if args.spec:  # a fixed design: no Scout, no Architect; only the Compiler, Tester and Repair roles run
        from zyven.ai.schemas import CapabilitySpec
        spec = CapabilitySpec.model_validate_json(Path(args.spec).read_text(encoding="utf-8"))
        print(f"spec fixed from {args.spec}: {spec.name}, {len(spec.tools)} tools")
        r = compile_capability(p, a, spec=spec, skills_root=Path(args.out) if args.out else paths.skills_out(),
                               max_repairs=args.max_repairs, roles=roles)
        checks = f" ({', '.join(r.report.to_dict()['verified_for'])})" if r.report else ""
        print(f"\nskill: {r.skill_dir}\nverified: {r.verified}{checks}")
        sys.exit(0 if r.verified else 1)
    scout_file = _workdir(Path(args.repo)) / "scout.json"
    if scout_file.exists() and not args.rescout:
        candidates = ScoutResult.model_validate_json(scout_file.read_text(encoding="utf-8")).capabilities
    else:
        res = scout(p, a)
        scout_file.write_text(res.value.model_dump_json(indent=1), encoding="utf-8")
        candidates = res.value.capabilities
    from zyven.catalog.catalog import Catalog  # reviewer-curated entries apply to catalog repos
    cat_file = paths.catalog_file()
    if cat_file.exists():
        cat = Catalog(cat_file, paths.home())
        for r in cat.repos:
            if cat.checkout_dir(r).resolve() == Path(args.repo).resolve():
                candidates = cat.capabilities(r)
    cand = next((c for c in candidates if c.name == args.capability), None) or \
        next((c for c in candidates if args.capability in c.name), None)
    if args.entry:
        # Human-edited boundary: the reviewer names the entry points (resolved like model references).
        from zyven.ai.schemas import CandidateCapability
        from zyven.analysis.refs import RefResolver
        ok, bad = RefResolver(a).resolve_all(args.entry)
        if bad:
            sys.exit(f"unknown entry points: {bad}")
        base = cand or CandidateCapability(name=args.capability, title=args.capability.replace("_", " ").title(),
                                           description=args.description or args.capability.replace("_", " "),
                                           entry_points=[], why_agents_need_it="selected by a human reviewer")
        cand = base.model_copy(update={"name": args.capability, "entry_points": ok,
                                       "description": args.description or base.description})
        print(f"boundary set by reviewer: {', '.join(ok)}")
    if args.test and cand is not None:
        cand = cand.model_copy(update={"tests": args.test})
    if cand is None:
        sys.exit(f"capability {args.capability!r} not found; available: {', '.join(c.name for c in candidates)}")
    r = compile_capability(p, a, candidate=cand, skills_root=Path(args.out) if args.out else paths.skills_out(), max_repairs=args.max_repairs, roles=roles)
    checks = f" ({', '.join(r.report.to_dict()['verified_for'])})" if r.report else ""
    print(f"\nskill: {r.skill_dir}\nverified: {r.verified}{checks}")
    sys.exit(0 if r.verified else 1)


def cmd_verify_configs(args) -> None:
    """zyven verify --config FILE / --discover: every server a client is configured with, then one summary."""
    from zyven.mcpverify import format_markdown, verify_server
    from zyven.mcpverify.configs import known_locations, read_config
    files = [Path(p) for p in args.config or []]
    if args.discover:
        found = known_locations()
        print("config files found: " + (", ".join(str(p) for p in found) or "none"))
        files += found
    entries = []
    for f in dict.fromkeys(files):
        try:
            entries += read_config(f)
        except (OSError, ValueError) as e:
            print(f"  cannot read {f}: {e}")
    if not entries:
        sys.exit("no MCP servers found in those files")
    print(f"{len(entries)} server(s). Each runs on this machine as its client would run it"
          + (" (inside the sandbox)" if args.docker else "") + "; env values from the config are passed, never shown.\n")
    rows, reports = [], []
    for e in entries:
        if e.disabled:
            rows.append((e.name, "skipped", "disabled in its config", e.source))
            continue
        r = verify_server(e.command or None, e.url or None, e.headers or None, e.env or None, args.docker,
                          None, probe=args.probe, timeout=args.timeout, network=args.allow_network)
        reports.append({"name": e.name, "source": e.source, **r.to_dict()})
        if args.markdown:
            with open(args.markdown, "a", encoding="utf-8") as f:
                f.write(f"## {e.name}\n\n" + format_markdown(r) + "\n")
        bad = [c.name for c in r.checks if c.status == "FAIL"]
        warn = [c.name for c in r.checks if c.status == "WARN" and c.name != "isolation"]
        rows.append((e.name, r.verdict, ("failed: " + ", ".join(bad)) if bad else
                     (("warnings: " + ", ".join(warn)) if warn else f"{len(r.tools)} tools, clean"), e.source))
        print(f"  {r.verdict:4}  {e.name}  ({rows[-1][2]})", flush=True)
    width = max(len(r[0]) for r in rows)
    print("\n" + "\n".join(f"  {n:<{width}}  {v:<7}  {d}" for n, v, d, _ in rows))
    if args.json:
        Path(args.json).write_text(json.dumps(reports, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"report: {args.json}")
    sys.exit(1 if any(v == "FAIL" for _, v, _, _ in rows) else 0)


def cmd_verify(args) -> None:
    from zyven.mcpverify import format_markdown, format_report, verify_server, write_lock
    if args.config or args.discover:
        return cmd_verify_configs(args)
    command = args.server[1:] if args.server[:1] == ["--"] else args.server
    if not command and not args.url:
        sys.exit("give the server command after --, e.g.  zyven verify -- npx -y @modelcontextprotocol/server-memory\n"
                 "or a URL:  zyven verify --url https://example.com/mcp")
    headers = dict(h.split(":", 1) for h in args.header or [])
    headers = {k.strip(): v.strip() for k, v in headers.items()}
    env = {}
    for item in args.env_var or []:  # NAME=value, or NAME to pass this shell's value through
        k, _, v = item.partition("=")
        env[k] = v if _ else __import__("os").environ.get(k, "")
    if not args.docker and command:
        print("note: the server runs on this machine with your permissions; use --docker IMAGE for the sandbox\n")
    lock = Path(args.lock) if args.lock else None
    mounts = {}
    for i, m in enumerate(args.mount or []):  # HOST[:/CONTAINER]; "C:\x" stays a host path (no "/" after the colon)
        host, sep, cont = m.rpartition(":")
        if not (sep and cont.startswith("/")):
            host, cont = m, ("/work" if i == 0 else f"/work{i}")
        mounts[Path(host)] = cont
    r = verify_server(command or None, args.url, headers, env or None, args.docker, mounts or None, probe=args.probe,
                      lock_file=None if args.update_lock else lock, timeout=args.timeout, network=args.allow_network)
    print(format_report(r, verbose=args.verbose))
    if args.json:
        Path(args.json).write_text(json.dumps(r.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"report: {args.json}")
    if args.markdown:  # e.g. $GITHUB_STEP_SUMMARY: appended, so several servers can share one summary
        with open(args.markdown, "a", encoding="utf-8") as f:
            f.write(format_markdown(r) + "\n")
    if lock and (args.update_lock or not lock.exists()) and r.lock:
        write_lock(r, lock)
        print(f"lock file written: {lock} ({len(r.lock)} tools)")
    warned = any(c.status == "WARN" and c.name != "isolation" for c in r.checks)
    if args.strict and r.verdict == "PASS" and warned:
        print("strict: warnings count as failures")
        sys.exit(1)
    sys.exit(0 if r.verdict == "PASS" else 1)


def cmd_outdated(args) -> None:
    from zyven.outdated import check, skill_dirs, to_json
    targets = [Path(p) for p in args.paths] or [paths.home() / "library", paths.skills_out()]
    skills = skill_dirs(targets)
    if not skills:
        sys.exit("no compiled skills found in: " + ", ".join(str(t) for t in targets))
    rows = []
    for sk in skills:
        st = check(sk, fetch=args.fetch)
        rows.append(st)
        how = f"{st.behind} commits behind" if st.behind is not None else ""
        print(f"  {st.state:<11} {st.skill:<28} {st.commit[:10]}" + (f" -> {st.upstream[:10]}" if st.state == "behind" else "")
              + (f"  {how}" if how else "") + (f"  ({st.detail})" if st.detail else ""))
        for f in st.touched[:8]:
            print(f"                touched: {f}")
    if args.json:
        Path(args.json).write_text(to_json(rows), encoding="utf-8")
    moved = [r for r in rows if r.state == "behind"]
    if moved:
        print(f"\n{len(moved)} skill(s) behind upstream. They stay verified for their pinned commit. To move one: pin the"
              " new commit in catalog/repos.json, `zyven sync`, then `zyven compile` it again (all six gates rerun).")
    sys.exit(1 if moved and args.strict else 0)


def cmd_export(args) -> None:
    from zyven.export import export
    skill = Path(args.skill)
    to = Path(args.to) if args.to else Path("exported") / skill.name
    try:
        out = export(skill, to)
    except (FileNotFoundError, ValueError) as e:
        sys.exit(str(e))
    print(f"exported to {out}:\n  " + "\n  ".join(sorted(p.name for p in out.iterdir())))
    print(f"\nnext: cd {out} && docker build -t zyven-skill-{skill.name.replace('_', '-')} .   (see README.md)")


def cmd_reassemble(args) -> None:
    from zyven.compiler.reassemble import reassemble
    targets = [Path(p) for p in args.paths] or [paths.home() / "library", paths.skills_out()]
    results = reassemble(list(dict.fromkeys(targets)), verify_gates=not args.no_verify, dry_run=args.dry_run)
    if not results:
        print("no compiled skills found in: " + ", ".join(str(t) for t in targets))
    for r in results:
        print(f"  {r.status:<20} {r.skill}" + (f"  ({r.detail})" if r.detail else ""))
    sys.exit(1 if any(r.status.startswith("kept") for r in results) else 0)


def launch_command() -> list[str]:
    """How another program should start zyven, so the command still works next week.

    A checkout runs its own Python. A uvx run lives in uv's cache, which can be cleaned at any time, so it is told to
    run uvx again from the same source zyven came from (PyPI, git or a wheel file). A pipx/pip install has a stable
    `zyven` program on PATH."""
    if paths.checkout_root():
        return [str(Path(sys.executable).resolve()), "-m", "zyven.cli"]
    # the environment folder, not the resolved interpreter: on Linux the venv's python is a symlink into uv's shared
    # Python install, so resolving it leaves the cache path behind
    env = Path(sys.prefix).as_posix().lower() + "/"
    if any(m in env for m in ("/uv/cache/", "/.cache/uv/", "/archive-v", "uv-cache/")):  # not uv/tools: that one is stable
        source = "zyven"  # from the package index
        try:
            from importlib.metadata import distribution
            direct = distribution("zyven").read_text("direct_url.json")
            if direct:
                info = json.loads(direct)
                vcs = info.get("vcs_info")
                source = (f"git+{info['url']}" + (f"@{vcs['commit_id']}" if vcs.get("commit_id") else "")) if vcs \
                    else info["url"]
        except Exception:  # noqa: BLE001  metadata missing: the index name is the best guess
            pass
        return ["uvx", "--from", source, "zyven"] if source != "zyven" else ["uvx", "zyven"]
    found = shutil.which("zyven")
    return [found] if found else [str(Path(sys.executable).resolve()), "-m", "zyven.cli"]


def cmd_mcp(args) -> None:
    root = paths.checkout_root()
    board_dir = (args.board_dir or paths.home()).resolve()
    if args.print_config:
        custom = args.board_dir or __import__("os").environ.get("ZYVEN_HOME")  # the agent will not inherit ZYVEN_HOME
        tail = ["mcp"] + (["--board-dir", str(board_dir)] if custom else []) + \
            (["--connections"] if args.connections else [])
        run = launch_command() + tail
        quoted = " ".join(f'"{a}"' if " " in a else a for a in run)
        print("Claude Code:\n  claude mcp add --scope user zyven -- " + quoted)
        print("\nCodex:\n  codex mcp add zyven -- " + quoted)
        print("\nAny MCP client (JSON):\n  " + json.dumps({"mcpServers": {"zyven": {"command": run[0], "args": run[1:],
                                                                          **({"cwd": str(root)} if root else {})}}}))
        return
    from zyven.hub.stdio import main as serve_stdio
    serve_stdio(board_dir, connections=args.connections, only=args.skill)


def main() -> None:
    ap = argparse.ArgumentParser(prog="zyven")
    ap.add_argument("--env", default=None, help="settings file (default: ./.env, the checkout's .env, or ~/.zyven/.env)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("analyze"); s.add_argument("repo"); s.set_defaults(fn=cmd_analyze)
    s = sub.add_parser("scout"); s.add_argument("repo"); s.set_defaults(fn=cmd_scout)
    s = sub.add_parser("compile"); s.add_argument("repo"); s.add_argument("--capability", required=True)
    s.add_argument("--out", default=None, help="where to write the skill (default: skills/ in a checkout, else "
                   "~/.zyven/library, which `zyven mcp` serves)"); s.add_argument("--max-repairs", type=int, default=2)
    s.add_argument("--rescout", action="store_true")
    s.add_argument("--entry", action="append", help="override entry points (human-edited boundary); repeatable")
    s.add_argument("--description", help="capability description when defining it with --entry")
    s.add_argument("--test", action="append", help="upstream test file to run for verification (repo-relative); repeatable")
    s.add_argument("--spec", help="compile this capability.json as it is (skips the Scout and Architect); e.g. to compare "
                   "contenders on one fixed design")
    who = ("'model' (the chat model in .env) or a coding agent run headless: codex, claude, agy, opencode, qoder, "
           "optionally with a model, e.g. claude:opus or opencode:opencode/big-pickle")
    s.add_argument("--agent", help=f"who does every role (and the scout): {who}")
    for role in ("architect", "compiler", "tester", "repair"):
        s.add_argument(f"--{role}", help=f"who does the {role} role only: {who}")
    s.set_defaults(fn=cmd_compile)
    s = sub.add_parser("verify", help="check any MCP server: schemas, tool poisoning, rug pulls, robustness")
    s.add_argument("--url", help="a streamable HTTP MCP server instead of a command")
    s.add_argument("--config", action="append", help="check every server in a client config (Claude Desktop/Code, "
                   "Cursor, VS Code mcp.json, Codex config.toml); repeatable")
    s.add_argument("--discover", action="store_true", help="find the usual client config files and check them all")
    s.add_argument("--header", action="append", help="HTTP header for --url, 'Name: value'; repeatable")
    s.add_argument("--env", dest="env_var", action="append",
                   help="environment for the server, NAME=value or NAME (pass through); nothing else is passed")
    s.add_argument("--docker", metavar="IMAGE", help="run the command in Zyven's sandbox using this image "
                   "(no network, read-only, no capabilities); e.g. zyven-sandbox:py312")
    s.add_argument("--mount", action="append", help="with --docker: HOST[:CONTAINER] folder mounted read-only "
                   "(default /work); repeatable")
    s.add_argument("--allow-network", action="store_true", help="with --docker: give the container network access "
                   "(for servers that must reach their service to start; the report says so)")
    s.add_argument("--probe", action="store_true", help="also call each tool with input its schema forbids")
    s.add_argument("--lock", help="lock file of tool definitions: written if missing, compared if present")
    s.add_argument("--update-lock", action="store_true", help="rewrite the lock file from this run")
    s.add_argument("--json", help="write the full report here")
    s.add_argument("--markdown", help="append a Markdown report to this file (e.g. $GITHUB_STEP_SUMMARY)")
    s.add_argument("--strict", action="store_true", help="warnings fail too (except isolation, which is about "
                   "where the check ran)")
    s.add_argument("--timeout", type=float, default=60.0)
    s.add_argument("server", nargs=argparse.REMAINDER, help="-- command args...")
    s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("mcp", help="serve verified skills over stdio to Claude Code, Codex or any MCP client")
    s.add_argument("--board-dir", type=Path, help="board folder whose library/ holds the skills (default ~/.zyven, or workspace/ in a checkout)")
    s.add_argument("--connections", action="store_true", help="also offer the services connected on the board "
                   "(write tools are then gated only by your agent's permission prompt)")
    s.add_argument("--skill", action="append", help="serve only this skill; repeatable")
    s.add_argument("--print-config", action="store_true", help="print the commands that add Zyven to Claude Code and Codex")
    s.set_defaults(fn=cmd_mcp)
    s = sub.add_parser("outdated", help="skills whose library moved on upstream since they were verified")
    s.add_argument("paths", nargs="*", help="skill folders or libraries (default: the library and skills/)")
    s.add_argument("--fetch", action="store_true", help="also fetch, count commits behind and list changed files in "
                   "the modules each skill uses (updates remote refs in the pinned checkout only)")
    s.add_argument("--json", help="write the result here")
    s.add_argument("--strict", action="store_true", help="exit 1 when any skill is behind (for CI)")
    s.set_defaults(fn=cmd_outdated)
    s = sub.add_parser("export", help="a verified skill as a standalone MCP server (Dockerfile, pinned library, README)")
    s.add_argument("skill", help="the skill folder")
    s.add_argument("--to", help="output folder (default exported/<skill>)")
    s.set_defaults(fn=cmd_export)
    s = sub.add_parser("reassemble", help="rebuild compiled skills with the current harness and rerun the gates "
                       "(no model calls)")
    s.add_argument("paths", nargs="*", help="skill folders or libraries (default: the library and skills/)")
    s.add_argument("--dry-run", action="store_true", help="only say which skills would change")
    s.add_argument("--no-verify", action="store_true", help="skip the gates (the skill is then marked as such)")
    s.set_defaults(fn=cmd_reassemble)
    s = sub.add_parser("setup", help="build the sandbox image and create the home folder")
    s.set_defaults(fn=lambda a: sys.exit(__import__("zyven.setup", fromlist=["setup"]).setup()))
    s = sub.add_parser("doctor", help="check Docker, the sandbox image, settings and coding agents")
    s.set_defaults(fn=lambda a: sys.exit(__import__("zyven.setup", fromlist=["doctor"]).doctor()))
    s = sub.add_parser("sync"); s.add_argument("--scout", action="store_true", help="also scout capabilities (model calls)")
    s.add_argument("--rescout", action="store_true", help="re-scout repos that already have cached results")
    s.set_defaults(fn=cmd_sync)
    s = sub.add_parser("board"); s.add_argument("--port", type=int, default=8765)
    s.add_argument("--board-dir", type=Path, help="keep tasks and skills here instead of workspace/ (a clean board)")
    s.set_defaults(fn=lambda a: __import__("zyven.orchestrator.server", fromlist=["serve"]).serve(port=a.port, board_dir=a.board_dir))
    args = ap.parse_args()
    if args.env is None:
        args.env = str(paths.env_file())
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args.fn(args)


if __name__ == "__main__":
    main()
