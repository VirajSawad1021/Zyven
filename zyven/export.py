"""`zyven export`: a verified skill as a standalone MCP server that runs without Zyven.

    zyven export <skill folder> [--to DIR]

The folder written contains:
  server.py           the verified server, unchanged
  pyproject.toml      `mcp` plus the source library pinned to the exact commit the gates ran against
  Dockerfile          the same kind of runtime Zyven uses (non-root; run it with --network none --read-only)
  README.md           what it does, where it came from, which gates it passed, and client config to paste
  provenance.json, validation-report.json, capability.json   the evidence, copied as-is

Nothing is re-verified here; the gates' report is copied, not repeated. Export a skill only after it passed.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

EVIDENCE = ("provenance.json", "validation-report.json", "capability.json", "diff_tests.json")


def _pip_source(prov: dict) -> tuple[str, str]:
    """(pip requirement, distribution name guess) for the pinned library."""
    url, commit = prov.get("repository", ""), prov.get("commit", "")
    sub = ""
    checkout = Path(prov.get("source_checkout") or "")
    root = prov.get("source_root") or "."
    repo = checkout if root in ("", ".") else Path(*checkout.parts[:len(checkout.parts) - len(Path(root).parts)])
    has_build = lambda d: any((d / f).exists() for f in ("pyproject.toml", "setup.py", "setup.cfg"))  # noqa: E731
    if root not in ("", ".") and repo.exists() and not has_build(repo) and has_build(repo / root):
        sub = f"#subdirectory={root}"  # e.g. python-phonenumbers keeps its package in python/
    name = url.rstrip("/").split("/")[-1].removesuffix(".git") or "library"
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"provenance has no repository URL to pin ({url!r})")
    return f"{name} @ git+{url}@{commit}{sub}", name


def export(skill_dir: Path, to: Path) -> Path:
    for f in ("server.py", "provenance.json", "validation-report.json", "capability.json"):
        if not (skill_dir / f).exists():
            raise FileNotFoundError(f"{skill_dir} has no {f}; is it a compiled skill?")
    report = json.loads((skill_dir / "validation-report.json").read_text(encoding="utf-8"))
    if not report.get("passed"):
        raise ValueError(f"{skill_dir.name} did not pass its gates; only verified skills can be exported")
    prov = json.loads((skill_dir / "provenance.json").read_text(encoding="utf-8"))
    spec = json.loads((skill_dir / "capability.json").read_text(encoding="utf-8"))
    name = spec["name"]
    req, lib = _pip_source(prov)
    to.mkdir(parents=True, exist_ok=True)
    shutil.copy(skill_dir / "server.py", to / "server.py")
    for f in EVIDENCE:
        if (skill_dir / f).exists():
            shutil.copy(skill_dir / f, to / f)
    dist = f"zyven-skill-{name.replace('_', '-')}"
    (to / "pyproject.toml").write_text(f'''[project]
name = "{dist}"
version = "0.1.0"
description = {json.dumps(spec.get("summary") or spec.get("title") or name)}
requires-python = ">=3.11"
dependencies = [
    "mcp>=2.3,<3",
    "pydantic>=2.7",
    "{req}",  # the exact commit the gates verified against
]

[project.scripts]
{dist} = "server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
only-include = ["server.py"]
''', encoding="utf-8")
    # server.py ends with `if __name__ == "__main__": server.run("stdio")`; give it a callable entry point too
    text = (to / "server.py").read_text(encoding="utf-8")
    if "def main()" not in text:
        text += '\n\ndef main() -> None:  # entry point for the packaged command (added by zyven export)\n    server.run("stdio")\n'
        (to / "server.py").write_text(text, encoding="utf-8")
    (to / "Dockerfile").write_text(f'''# {name}: a Zyven-verified MCP server. Run it the way Zyven did:
#   docker build -t {dist} .
#   docker run -i --rm --network none --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges {dist}
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* \\
 && pip install --no-cache-dir "mcp>=2.3,<3" "pydantic>=2.7" "{req.split(" @ ", 1)[1]}" \\
 && useradd -u 1000 -m skill
COPY server.py /skill/server.py
USER 1000
ENV PYTHONDONTWRITEBYTECODE=1 HOME=/tmp
ENTRYPOINT ["python", "/skill/server.py"]
''', encoding="utf-8")
    tools = [t["name"] for t in spec.get("tools", [])]
    gates = report.get("verified_for") or [g["name"] for g in report.get("gates", []) if g.get("passed")]
    docker_cmd = ["run", "-i", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp", "--cap-drop", "ALL", dist]
    (to / "README.md").write_text(f"""# {spec.get("title") or name}

{spec.get("summary", "")}

A verified MCP server, compiled by [Zyven](https://github.com/VirajSawad1021/Zyven) from
[{lib}]({prov.get("repository")}) at commit `{str(prov.get("commit", ""))[:12]}` ({prov.get("license", "see the repository")}).

**Tools:** {", ".join(f"`{t}`" for t in tools)}

**Gates passed:** {", ".join(gates)}. The full report is in `validation-report.json`, and where it came from (models,
attempts, dropped tools) is in `provenance.json`. Those files were copied from the skill as verified, not rerun.

## Run it

With Docker (recommended: no network, read-only, the way the gates ran it):

```bash
docker build -t {dist} .
docker run -i --rm --network none --read-only --tmpfs /tmp --cap-drop ALL {dist}
```

Or with Python: `uvx --from . {dist}`, or `pip install . && {dist}`.

## Add it to an agent

```bash
claude mcp add {name} -- docker {" ".join(docker_cmd)}
codex mcp add {name} -- docker {" ".join(docker_cmd)}
```

```json
{json.dumps({"mcpServers": {name: {"command": "docker", "args": docker_cmd}}}, indent=2)}
```

Check it any time with `zyven verify -- docker {" ".join(docker_cmd)}`.
""", encoding="utf-8")
    return to
