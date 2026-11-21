"""Does the file `zyven verify --srt-settings` writes actually hold under Anthropic's sandbox-runtime (srt)?

Runs on Linux, where srt uses bubblewrap (CI installs bwrap, socat and ripgrep). It builds the settings for a server
that was seen to reach one host, then runs small commands under `srt --settings`:

    the allowed host answers          another host is refused        a plain command still runs
    nothing can be written            a credential folder cannot be read

It also reports, without failing, whether an `npx`-launched program can run under "no writes at all": npx writes its
cache, so a server started that way may need a writable cache folder added by hand.

    uv run python scripts/check_srt.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.mcpverify.checks import run_checks  # noqa: E402
from zyven.mcpverify.srt import srt_settings  # noqa: E402

SRT = ["npx", "-y", "@anthropic-ai/sandbox-runtime@0.0.83"]
ALLOWED, OTHER = "example.com", "www.github.com"


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="zyven-srt-"))
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
        r = subprocess.run([*SRT, "--settings", str(settings), "--", *cmd], cwd=work, capture_output=True,
                           text=True, timeout=180)  # "--": the command's own options are not srt's
        print(f"$ srt {' '.join(cmd)} -> exit {r.returncode}\n  {(r.stdout + r.stderr).strip()[:300]}")
        return r

    curl = ["curl", "-sS", "-o", "/dev/null", "--max-time", "20"]
    control = srt("echo", "ok")
    if control.returncode != 0 or "ok" not in control.stdout:
        # every "refused" below would then be srt failing to start, not the settings holding: never count those
        print("FAIL  srt cannot run a plain command here, so nothing below would mean anything")
        return 1
    checks = {
        "a plain command runs": True,
        f"the allowed host ({ALLOWED}) answers": srt(*curl, f"https://{ALLOWED}").returncode == 0,
        f"another host ({OTHER}) is refused": srt(*curl, f"https://{OTHER}").returncode != 0,
        "nothing can be written": (srt("sh", "-c", "echo x > written.txt").returncode != 0
                                   and not (work / "written.txt").exists()),
        "a credential folder cannot be read": "secret" not in srt("cat", str(probe)).stdout,
    }
    npx = srt("npx", "-y", "cowsay@1.6.0", "hi")
    probe.unlink()
    print()
    for what, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {what}")
    print(f"info  an npx-launched program under no-writes: {'runs' if npx.returncode == 0 else 'does not run'}"
          " (npx writes its cache; such a server needs a writable cache folder added to allowWrite)")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
