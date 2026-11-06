"""`zyven setup` and `zyven doctor`: one command to get ready, one to see what is missing.

setup   builds the sandbox image from the files shipped in the package (labelled with their hash, so a stale image is
        noticed), creates the home folder, and writes a settings template if there is none. It never writes keys.
doctor  checks Python, Docker, the sandbox image (present and current), the settings file (key present, never shown),
        the coding agents on PATH, and where skills live. Each line says how to fix what is missing.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

from zyven import paths
from zyven.sandbox.runner import DEFAULT_IMAGE

SANDBOX_DIR = paths.PACKAGE / "sandbox"
BUILD_FILES = ("Dockerfile", "mcp_smoke.py", "diff_check.py")  # everything the image bakes in
LABEL = "zyven.build-hash"
AGENTS = {"codex": "Codex", "claude": "Claude Code", "agy": "Antigravity", "opencode": "OpenCode", "qodercli": "Qoder CLI"}
ENV_TEMPLATE = """# Zyven settings. Only needed for the chat-model roles; coding agents (zyven compile --agent codex),
# zyven verify and zyven mcp work without it. Any OpenAI-compatible host works.
MODEL_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
MODEL_NAME=gemma-4-26b-a4b-it
MODEL_API_KEY=
"""


def build_hash() -> str:
    h = hashlib.sha256()
    for name in BUILD_FILES:
        h.update(name.encode() + b"\0" + (SANDBOX_DIR / name).read_bytes())
    return h.hexdigest()[:16]


def _run(cmd: list[str], timeout: float = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def docker_state() -> tuple[bool, str]:
    if not shutil.which("docker"):
        return False, "Docker is not installed. Install Docker Desktop (or Docker Engine) and start it."
    code, out = _run(["docker", "info", "--format", "{{.ServerVersion}}"], 20)
    if code != 0:
        return False, "Docker is installed but not running. Start Docker Desktop, then run this again."
    return True, f"Docker {out.splitlines()[-1] if out else ''}".strip()


def image_state(image: str = DEFAULT_IMAGE) -> tuple[str, str]:
    """('ok' | 'stale' | 'missing', detail)."""
    code, out = _run(["docker", "image", "inspect", image, "--format", "{{index .Config.Labels \"" + LABEL + "\"}}"])
    if code != 0:
        return "missing", f"{image} is not built. Run: zyven setup"
    if out.strip() != build_hash():
        return "stale", (f"{image} was built from other sandbox files than this version of Zyven ships. "
                         "Gates could give wrong results. Run: zyven setup")
    return "ok", f"{image} is current"


def build_image(image: str = DEFAULT_IMAGE) -> int:
    print(f"building {image} from {SANDBOX_DIR} (needs network once, takes a minute)...", flush=True)
    return subprocess.call(["docker", "build", "-t", image, "--label", f"{LABEL}={build_hash()}", str(SANDBOX_DIR)])


def setup() -> int:
    home = paths.home()
    (home / "library").mkdir(parents=True, exist_ok=True)
    print(f"home: {home}")
    env = paths.env_file()
    if not env.exists() and paths.checkout_root() is None:
        env.parent.mkdir(parents=True, exist_ok=True)
        env.write_text(ENV_TEMPLATE, encoding="utf-8")
        print(f"settings template written: {env} (add a key only if you want the chat-model roles)")
    ok, detail = docker_state()
    if not ok:
        print(detail)
        return 1
    state, detail = image_state()
    if state == "ok":
        print(detail)
    elif build_image() != 0:
        print("the image build failed; see the Docker output above")
        return 1
    print("\nready. Try:\n  zyven doctor\n  zyven verify -- <any MCP server command>\n  zyven mcp --print-config")
    return 0


def _settings_state(env: Path) -> tuple[bool | None, str]:
    if not env.exists():
        return None, f"no settings file ({env}); only the chat-model roles need one. zyven setup writes a template."
    from zyven.ai.provider import load_env
    values = load_env(env)
    key = values.get("MODEL_API_KEY", "")
    if not values.get("MODEL_NAME") or not key or key.upper().startswith("PASTE"):
        return None, f"{env}: no chat model key; use a coding agent (--agent codex) or add MODEL_API_KEY"
    return True, f"{env}: chat model {values['MODEL_NAME']} (key set, not shown)"


def doctor() -> int:
    rows: list[tuple[bool | None, str]] = []
    v = sys.version_info
    rows.append((v >= (3, 11), f"Python {v.major}.{v.minor}.{v.micro}" + ("" if v >= (3, 11) else " (need 3.11+)")))
    ok, detail = docker_state()
    rows.append((ok, detail))
    if ok:
        state, detail = image_state()
        rows.append((state == "ok", detail))
    rows.append(_settings_state(paths.env_file()))
    found = [label for b, label in AGENTS.items() if shutil.which(b)]
    rows.append((bool(found) or None, "coding agents on PATH: " + (", ".join(found) if found else
                                                                    "none (optional: codex, claude, agy, opencode, qodercli)")))
    lib = paths.home() / "library"
    n = sum(1 for d in lib.iterdir() if d.is_dir()) if lib.exists() else 0
    rows.append((True, f"home {paths.home()}; {n} skill(s) in the library"
                       + ("" if paths.checkout_root() is None else f" (git checkout: {paths.checkout_root()})")))
    for good, text in rows:
        print(f"  {'ok  ' if good else ('--  ' if good is None else 'FAIL')}  {text}")
    hard = [t for g, t in rows if g is False]
    print("\n" + ("ready" if not hard else f"{len(hard)} problem(s) to fix"))
    return 1 if hard else 0
