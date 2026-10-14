"""Run untrusted repository code inside a locked-down Docker container.

Defaults: no network, non-root user, read-only root filesystem, read-only source mount,
all Linux capabilities dropped, no privilege escalation, CPU/memory/process/time limits.
The harness (this module) decides pass/fail from exit codes and parsed output, never a model.
"""

from __future__ import annotations

import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_IMAGE = "zyven-sandbox:py312"


@dataclass
class SandboxResult:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    seconds: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class SandboxPolicy:
    image: str = DEFAULT_IMAGE
    network: bool = False
    memory: str = "1g"
    cpus: str = "2"
    pids_limit: int = 256
    timeout_s: int = 300
    extra_env: dict[str, str] = field(default_factory=dict)


def _docker_path(p: Path) -> str:
    return str(p.resolve()).replace("\\", "/")


def run(
    command: list[str],
    mounts: dict[Path, str],
    policy: SandboxPolicy | None = None,
    workdir: str = "/src",
) -> SandboxResult:
    """mounts: host path -> container path. Paths ending in ':rw' in the container side are writable."""
    policy = policy or SandboxPolicy()
    name = f"zyven-{uuid.uuid4().hex[:12]}"
    args = [
        "docker", "run", "--rm", "--name", name,
        "--user", "1000:1000",
        "--read-only", "--tmpfs", "/tmp:rw,size=256m",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--memory", policy.memory, "--cpus", policy.cpus, "--pids-limit", str(policy.pids_limit),
        "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HOME=/tmp",
        "-w", workdir,
    ]
    if not policy.network:
        args += ["--network", "none"]
    for k, v in policy.extra_env.items():
        args += ["-e", f"{k}={v}"]
    for host, target in mounts.items():
        mode = "rw" if target.endswith(":rw") else "ro"
        args += ["-v", f"{_docker_path(host)}:{target.removesuffix(':rw')}:{mode}"]
    args += [policy.image, *command]

    started = time.monotonic()
    try:
        proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=policy.timeout_s)
        return SandboxResult(command, proc.returncode, proc.stdout, proc.stderr, time.monotonic() - started)
    except subprocess.TimeoutExpired as e:
        subprocess.run(["docker", "kill", name], capture_output=True)
        return SandboxResult(command, -1, str(e.stdout or ""), str(e.stderr or ""),
                             time.monotonic() - started, timed_out=True)


@dataclass
class TestReport:
    ran: int
    failures: int
    errors: int
    skipped: int
    passed: bool
    seconds: float
    tail: str  # last lines of output, for reports and for the repair model


_RAN_RE = re.compile(r"Ran (\d+) tests? in")
_FAILED_RE = re.compile(r"FAILED \(([^)]*)\)")


def parse_unittest(result: SandboxResult) -> TestReport:
    out = result.stderr + "\n" + result.stdout  # unittest reports on stderr
    ran = int(m.group(1)) if (m := _RAN_RE.search(out)) else 0
    counts = {"failures": 0, "errors": 0, "skipped": 0}
    if m := _FAILED_RE.search(out):
        for part in m.group(1).split(","):
            k, _, v = part.strip().partition("=")
            if k in counts and v.isdigit():
                counts[k] = int(v)
    if m := re.search(r"OK \(skipped=(\d+)\)", out):
        counts["skipped"] = int(m.group(1))
    tail = "\n".join(out.strip().splitlines()[-40:])
    return TestReport(ran=ran, passed=result.ok and ran > 0, seconds=round(result.seconds, 2), tail=tail, **counts)


_PYTEST_COUNT_RE = re.compile(r"(\d+) (passed|failed|errors?|skipped)")


def parse_pytest(result: SandboxResult) -> TestReport:
    out = result.stdout + "\n" + result.stderr
    summary = [ln for ln in out.splitlines() if re.search(r"\d+ (passed|failed|error)", ln)]
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for n, kind in _PYTEST_COUNT_RE.findall(summary[-1] if summary else ""):
        counts["error" if kind.startswith("error") else kind] = int(n)
    ran = counts["passed"] + counts["failed"] + counts["error"]
    tail = "\n".join(out.strip().splitlines()[-40:])
    return TestReport(ran=ran, failures=counts["failed"], errors=counts["error"], skipped=counts["skipped"],
                      passed=result.ok and ran > 0, seconds=round(result.seconds, 2), tail=tail)


def run_upstream_tests(repo: Path, test_paths: list[str] | None = None,
                       policy: SandboxPolicy | None = None, source_root: str = ".",
                       ignore: list[str] | None = None) -> TestReport:
    """Run a repo's tests with pytest (also runs unittest TestCases and doctest files), repo mounted read-only.

    test_paths: repo-relative files (`tests/test_x.py`, `tests/test_x.doctest`, or a source module whose
    docstrings are doctests). Default: the `tests` directory. Project `addopts` (e.g. coverage plugins that are
    not installed) are overridden; doctest option flags from the project config still apply.
    """
    cmd = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=",
           "--doctest-glob=*.doctest", "--rootdir=/src"]
    paths = test_paths or ["tests"]
    cmd += [f"--ignore={p}" for p in (ignore or [])]  # e.g. tests needing packages the sandbox lacks
    if any(p.endswith(".py") and not ({"tests", "test"} & set(Path(p).parts)) and not Path(p).name.startswith("test")
           for p in paths):
        cmd.append("--doctest-modules")  # a source module was listed: run its docstring examples
    policy = policy or SandboxPolicy()
    if source_root not in ("", "."):  # src-style layouts: make the packages importable
        policy = SandboxPolicy(**{**policy.__dict__, "extra_env": {**policy.extra_env,
                                                                    "PYTHONPATH": f"/src/{source_root}"}})
    return parse_pytest(run(cmd + paths, {repo: "/src"}, policy))
