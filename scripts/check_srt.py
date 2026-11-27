"""Does the file `zyven verify --srt-settings` writes actually hold under Anthropic's sandbox-runtime (srt)?

Runs on Linux, where srt uses bubblewrap (CI installs bwrap, socat and ripgrep), on macOS, and on Windows after srt's
one-time `npx @anthropic-ai/sandbox-runtime windows-install` (administrator; see LIMITATIONS.md). It builds the settings
for a server that was seen to reach one host, then runs small commands under `srt --settings`:

    the allowed host answers          another host is refused        a plain command still runs
    nothing can be written            a credential folder cannot be read

The allowed host is fetched with Python, the way an MCP server would, since Python (like Node) brings its own
certificate roots. curl is also tried and only reported: on macOS, programs that use Apple's TLS stack cannot reach
the system's certificate service inside srt's sandbox, so their HTTPS fails to verify even for an allowed host.

On Windows the command runs as srt's own `srt-sandbox` account. That account cannot read the caller's profile (unless
the install's profile grant was made), which changes four things here:
  * srt is installed into workspace/srt, not run through npx. srt starts its bundled srt-win.exe as `srt-sandbox`, so
    from npx's cache (in the profile) that fails with "CreateProcessWithLogonW(srt-sandbox): Access is denied".
  * The work folder is under workspace/, not in the profile's temp folder.
  * The fetch uses Node (from Program Files, with its own TLS stack), since a Python installed in the profile cannot
    start. curl is Git for Windows' (OpenSSL), because srt documents that `System32\\curl.exe`, which uses Windows'
    own TLS stack, cannot work under its restricted token.
  * Each command goes to srt as one cmd.exe line (`srt -c`): given as separate arguments, srt 0.0.83 dropped cmd's
    `/c` and started an interactive cmd.
So the repository itself must be outside the profile (as C:\\src\\Zyven is, and C:\\Users\\<you>\\Zyven is not).

    uv run python scripts/check_srt.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.mcpverify.checks import run_checks  # noqa: E402
from zyven.mcpverify.srt import srt_settings  # noqa: E402

SRT_PACKAGE = "@anthropic-ai/sandbox-runtime@0.0.83"
ALLOWED, OTHER = "example.com", "www.github.com"
WINDOWS = os.name == "nt"
WINDOWS_SRT_DIR = ROOT / "workspace" / "srt"  # outside the profile, as long as the repository is (see above)
GIT_CURL_DIRS = os.pathsep.join(rf"C:\Program Files\Git\{d}\bin" for d in ("mingw64", "ucrt64", "usr"))


def srt_command() -> list[str]:
    if not WINDOWS:
        return ["npx", "-y", SRT_PACKAGE]
    cli = WINDOWS_SRT_DIR / "node_modules" / "@anthropic-ai" / "sandbox-runtime" / "dist" / "cli.js"
    if not cli.exists():
        subprocess.run([shutil.which("npm") or "npm.cmd", "install", "--prefix", str(WINDOWS_SRT_DIR), "--no-save",
                        "--no-audit", "--no-fund", SRT_PACKAGE], check=True)
    return [shutil.which("node") or "node", str(cli)]


def main() -> int:
    if WINDOWS and Path.home() in ROOT.parents:
        print(f"FAIL  {ROOT} is inside your profile, which srt's sandbox account cannot read: clone it elsewhere")
        return 1
    if WINDOWS:
        (ROOT / "workspace").mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="zyven-srt-", dir=ROOT / "workspace" if WINDOWS else None))
    srt_cmd = srt_command()
    probe = Path.home() / ".ssh" / "zyven_srt_probe"
    probe.parent.mkdir(exist_ok=True)
    probe.write_text("secret\n", encoding="utf-8")
    report = run_checks({"target": "t", "started": True, "server": {"name": "s"}, "tools": [], "seconds": 1,
                         "sandboxed": True, "egress": {"hosts": [ALLOWED],
                                                      "decisions": [{"host": ALLOWED, "port": 443, "allowed": True}]}})
    data = srt_settings(report)
    if os.environ.get("ZYVEN_SRT_NO_SECCOMP"):  # CI on GitHub's Linux runners only (see the workflow)
        # srt's seccomp helper nests a second user namespace, which these runners refuse; without it bubblewrap uses
        # --disable-userns instead. This lifts only unix-socket filtering, which nothing below checks: the network and
        # filesystem rules under test are exactly the ones Zyven wrote.
        data["network"]["allowAllUnixSockets"] = True
        print("note: CI-only addition network.allowAllUnixSockets=true (no seccomp helper on this runner)")
    settings = work / "srt.json"
    settings.write_text(json.dumps(data), encoding="utf-8")
    print("settings:", settings.read_text(encoding="utf-8"))

    def srt(*cmd: str) -> subprocess.CompletedProcess:
        # "--": the command's own options are not srt's. On Windows, one cmd.exe line (see the module note).
        run = ["-c", subprocess.list2cmdline(cmd)] if WINDOWS else ["--", *cmd]
        r = subprocess.run([*srt_cmd, "--settings", str(settings), *run], cwd=work, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=180)
        print(f"$ srt {' '.join(cmd)} -> exit {r.returncode}\n  {(r.stdout + r.stderr).strip()[:300]}")
        return r

    windows = WINDOWS
    if windows:
        curl = [shutil.which("curl", path=GIT_CURL_DIRS) or "curl", "-sS", "-o", "NUL", "--max-time", "20"]
        fetch = [shutil.which("node") or "node", "-e",
                 ("fetch(process.argv[1], {signal: AbortSignal.timeout(20000)})"
                  ".then(() => process.exit(0), e => { console.error(String(e.cause || e)); process.exit(1) })")]
        echo, write, read = (["cmd", "/c", "echo ok"], ["cmd", "/c", "echo x> written.txt"],
                             ["cmd", "/c", "type", str(probe)])
    else:
        curl = ["curl", "-sS", "-o", "/dev/null", "--max-time", "20"]
        fetch = [sys.executable, "-c", "import certifi, ssl, sys, urllib.request; urllib.request.urlopen(sys.argv[1], "
                 "context=ssl.create_default_context(cafile=certifi.where()), timeout=20)"]
        echo, write, read = ["echo", "ok"], ["sh", "-c", "echo x > written.txt"], ["cat", str(probe)]
    how = "Node" if windows else "Python"
    control = srt(*echo)
    if control.returncode != 0 or "ok" not in control.stdout:
        # every "refused" below would then be srt failing to start, not the settings holding: never count those
        print("FAIL  srt cannot run a plain command here, so nothing below would mean anything")
        return 1
    checks = {
        "a plain command runs": True,
        f"the allowed host ({ALLOWED}) answers ({how})": srt(*fetch, f"https://{ALLOWED}").returncode == 0,
        f"another host ({OTHER}) is refused ({how})": srt(*fetch, f"https://{OTHER}").returncode != 0,
        f"another host ({OTHER}) is refused (curl)": srt(*curl, f"https://{OTHER}").returncode != 0,
        "nothing can be written": srt(*write).returncode != 0 and not (work / "written.txt").exists(),
        "a credential folder cannot be read": "secret" not in srt(*read).stdout,
    }
    curl_allowed = srt(*curl, f"https://{ALLOWED}").returncode == 0
    probe.unlink()
    shutil.rmtree(work, ignore_errors=True)
    print()
    for what, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {what}")
    print(f"info  curl to the allowed host: {'works' if curl_allowed else 'fails'}"
          + ("" if curl_allowed else " (on macOS, Apple's TLS stack cannot verify certificates inside the sandbox; "
                                      "on Windows, a curl built on Schannel gets no TLS credentials under srt's token)"))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
