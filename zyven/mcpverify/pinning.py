"""Is the server's launch pinned, and is it still the server the lock file recorded?

Tool definitions are not the whole server. postmark-mcp (September 2025) kept every tool description the same and
only changed its code in a new version, so a definitions-only lock would not have noticed. A launch command such as
`npx -y some-server` runs whatever was published last, every time. These checks look at what can be seen from
outside: whether the command names an exact version, and whether the server's identity, version, image or network
destinations differ from the lock.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import PurePath
from typing import Any

_EXACT_NPM = re.compile(r"^(@[^/@\s]+/)?[^@\s]+@v?\d+\.\d+\.\d+(?:[-+][\w.\-+]*)?$")
_EXACT_PY = re.compile(r"^[A-Za-z0-9_.\-\[\],]+==[\w.!+\-]+$")


def _first_package(args: list[str], takes_value: set[str]) -> str | None:
    """The first argument that is not an option (or an option's value)."""
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a == "--":
            continue
        if a.startswith("-"):
            skip = a in takes_value
            continue
        return a
    return None


def unpinned(command: list[str] | None) -> list[str]:
    """Why this launch command may run different code next time (empty if it names exact versions)."""
    if not command:
        return []
    exe = PurePath(command[0]).name.lower().removesuffix(".exe").removesuffix(".cmd")
    args = command[1:]
    out: list[str] = []
    if exe in ("npx", "bunx", "pnpx"):
        pkg = None
        for i, a in enumerate(args):  # -p/--package names the package; otherwise the first positional argument
            if a in ("-p", "--package") and i + 1 < len(args):
                pkg = args[i + 1]
            elif a.startswith("--package="):
                pkg = a.split("=", 1)[1]
        pkg = pkg or _first_package(args, {"-p", "--package", "-c", "--call"})
        if pkg and not _EXACT_NPM.match(pkg):
            name = re.sub(r"(?<=.)@[^/@]*$", "", pkg)  # drop a tag such as @latest, keep a leading @scope
            out.append(f"{exe} {pkg}: no exact version, so every start runs the newest release "
                       f"(pin it, e.g. {name}@1.2.3)")
    elif exe in ("uvx", "pipx") or (exe == "uv" and args[:2] == ["tool", "run"]):
        rest = args[1:] if exe == "pipx" and args[:1] == ["run"] else (args[2:] if exe == "uv" else args)
        frm = next((rest[i + 1] for i, a in enumerate(rest[:-1]) if a in ("--from", "--spec")), None)
        frm = frm or next((a.split("=", 1)[1] for a in rest if a.startswith(("--from=", "--spec="))), None)
        pkg = frm or _first_package(rest, {"--from", "--spec", "--with", "-w", "--python", "-p", "--index-url",
                                           "--index", "--extra-index-url"})
        local = pkg and (pkg.startswith((".", "/", "\\", "git+", "file:")) or re.match(r"^[A-Za-z]:[\\/]", pkg))
        if pkg and not local and not _EXACT_PY.match(pkg):
            out.append(f"{exe} {pkg}: no exact version, so every start runs the newest release "
                       f"(pin it, e.g. --from {pkg.split('[')[0]}==1.2.3)")
    elif exe in ("docker", "podman") and args[:1] == ["run"]:
        image = _first_package(args[1:], {"-e", "--env", "-v", "--volume", "--name", "-p", "--publish", "--network",
                                          "--net", "-w", "--workdir", "-u", "--user", "--env-file", "--mount",
                                          "--entrypoint", "--platform", "-m", "--memory", "--cpus", "--pull"})
        if image and "@sha256:" not in image:
            out.append(f"{exe} image {image}: not pinned by digest, so the tag can be moved to a different image "
                       f"(use {image.split(':')[0]}@sha256:...)")
    return out


def image_id(image: str) -> str | None:
    """The local image ID Docker resolved this name to (it changes whenever the tag points at a new build)."""
    try:
        r = subprocess.run(["docker", "image", "inspect", "-f", "{{.Id}}", image], capture_output=True, text=True,
                           timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def reached_hosts(obs: dict[str, Any]) -> list[str]:
    eg = obs.get("egress") or {}
    return sorted({d.get("host") for d in eg.get("decisions", []) if d.get("allowed") and d.get("host")})


def launch_of(obs: dict[str, Any]) -> dict[str, Any]:
    launch = dict(obs.get("launch") or {})
    if obs.get("image"):
        launch["image"] = obs["image"]
    return launch


def lock_differences(obs: dict[str, Any], locked: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(failures, warnings) from comparing this run with everything but the tool hashes in a lock file."""
    bad: list[str] = []
    warn: list[str] = []
    srv, was = obs.get("server") or {}, locked.get("server") or {}
    if was.get("name") and srv.get("name") and was["name"] != srv["name"]:
        bad.append(f"server name changed: {was['name']!r} in the lock file, now {srv['name']!r}")
    if was.get("version") and srv.get("version") != was["version"]:
        warn.append(f"server version changed from {was['version']} to {srv.get('version') or '(none)'}: the code can "
                    f"change while every tool definition stays the same (re-review, then --update-lock)")
    old, new = locked.get("launch") or {}, launch_of(obs)
    if old.get("command") and new.get("command") and old["command"] != new["command"]:
        warn.append(f"launch command changed: {' '.join(old['command'])}  ->  {' '.join(new['command'])}")
    if old.get("url") and new.get("url") and old["url"] != new["url"]:
        warn.append(f"server URL changed: {old['url']} -> {new['url']}")
    oi, ni = (old.get("image") or {}).get("id"), (new.get("image") or {}).get("id")
    if oi and ni and oi != ni:
        warn.append(f"the image {new['image'].get('name')} now resolves to a different build "
                    f"({oi[:19]} -> {ni[:19]})")
    if "reached_hosts" in locked and obs.get("egress"):
        extra = sorted(set(reached_hosts(obs)) - set(locked.get("reached_hosts") or []))
        if extra:
            warn.append(f"now contacts hosts it did not when locked: {extra}")
    return bad, warn
