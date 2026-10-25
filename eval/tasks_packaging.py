"""Python packaging task set: PEP 440 versions and specifiers, environment markers, name normalisation.

Ground truth is computed by the `packaging` library itself (pinned in catalog/repos.json), never by a model.
"""

from __future__ import annotations

import random
import re

from packaging.markers import Marker
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

from eval.tasks import Task

SYSTEM_HINT = ("Follow PEP 440. For yes/no questions the value is 'yes' or 'no'. For versions give the normalised "
               "version string (e.g. 1.0rc1). For lists give the versions separated by single spaces.")

_PRE = ["", "", "a1", "b2", "rc1", "rc2", ".dev1", ".post1", ".post2", "+local.1"]
_OPS = [">=", "<=", ">", "<", "==", "!=", "~=", "==1.*"]


def _version(rng: random.Random) -> str:
    base = ".".join(str(rng.randrange(0, 6)) for _ in range(rng.choice([2, 3])))
    return base + rng.choice(_PRE)


def _specifier(rng: random.Random) -> str:
    parts = []
    for _ in range(rng.choice([1, 2])):
        op = rng.choice(_OPS)
        if op == "==1.*":
            parts.append(f"=={rng.randrange(0, 6)}.*")
        elif op == "~=":
            parts.append(f"~={rng.randrange(0, 5)}.{rng.randrange(0, 5)}")
        else:
            parts.append(f"{op}{_version(rng) if rng.random() < 0.3 else '.'.join(str(rng.randrange(0, 6)) for _ in range(rng.choice([2, 3])))}")
    return ",".join(parts)


def _messy_name(rng: random.Random) -> str:
    words = rng.sample(["Friendly", "bard", "Zope", "Interface", "py", "yaml", "Typing", "Extensions", "dateutil"], 3)
    return "".join(w + rng.choice(["-", "_", ".", "__", "-."]) for w in words[:-1]) + words[-1]


def generate(per_category: int = 6, seed: int = 2026) -> list[Task]:
    rng = random.Random(seed)
    tasks: list[Task] = []

    for i in range(per_category):
        while True:
            version, spec = _version(rng), _specifier(rng)
            try:
                SpecifierSet(spec)
                answer = Version(version) in SpecifierSet(spec)
                break
            except Exception:  # noqa: BLE001 - skip combinations the library itself rejects
                continue
        tasks.append(Task(f"spec-{i}", "specifier_match",
                          f"Does version {version} satisfy the requirement specifier '{spec}'?",
                          "yes" if answer else "no"))

    for i in range(per_category):
        vs = list({_version(rng) for _ in range(5)})
        tasks.append(Task(f"max-{i}", "version_max", f"Which of these versions is the highest: {' '.join(vs)}?",
                          str(max(Version(v) for v in vs))))

    for i in range(per_category):
        vs = list({_version(rng) for _ in range(5)})
        tasks.append(Task(f"sort-{i}", "version_sort",
                          f"Sort these versions from lowest to highest: {' '.join(vs)}",
                          " ".join(str(v) for v in sorted(Version(v) for v in vs))))

    for i in range(per_category):
        raw = rng.choice(["1.0.RC1", "2.0-alpha.3", "1.0.0-post4", "v1.2", "1.0_beta_2", "3.1.dev0", "2!1.0.A5"])
        tasks.append(Task(f"norm-{i}", "version_normalize", f"What is the normalised PEP 440 form of the version '{raw}'?",
                          str(Version(raw))))

    for i in range(per_category):
        py = rng.choice(["3.8", "3.9", "3.10", "3.11", "3.12", "3.13"])
        plat = rng.choice(["linux", "win32", "darwin"])
        marker = rng.choice([f"python_version >= '{rng.choice(['3.8', '3.10', '3.12'])}' and sys_platform == '{rng.choice(['linux', 'win32', 'darwin'])}'",
                             f"python_version < '{rng.choice(['3.9', '3.11', '3.13'])}' or sys_platform != '{rng.choice(['linux', 'win32'])}'",
                             f"python_full_version >= '3.{rng.randrange(8, 13)}.{rng.randrange(0, 10)}'"])
        env = {"python_version": py, "python_full_version": f"{py}.{rng.randrange(0, 10)}", "sys_platform": plat}
        tasks.append(Task(f"marker-{i}", "marker_eval",
                          f"With python_version = {env['python_version']}, python_full_version = {env['python_full_version']} "
                          f"and sys_platform = {plat}, does the environment marker \"{marker}\" evaluate to true?",
                          "yes" if Marker(marker).evaluate(env) else "no"))

    for i in range(per_category):
        raw = _messy_name(rng)
        tasks.append(Task(f"name-{i}", "name_normalize", f"What is the canonical (normalised) PyPI project name of '{raw}'?",
                          str(canonicalize_name(raw))))
    return tasks


def score(task: Task, answer: str) -> bool:
    a = answer.strip().lower()
    if task.category in ("specifier_match", "marker_eval"):
        neg = re.search(r"\b(no|not|false|fails?)\b", a)
        pos = re.search(r"\b(yes|true|satisf\w+)\b", a)
        return ("no" if neg else ("yes" if pos else None)) == task.expected
    if task.category == "version_sort":
        return a.replace(",", " ").split() == task.expected.split()
    if task.category in ("version_max", "version_normalize", "name_normalize"):
        return a.strip("`'\". ") == task.expected.lower()
    raise ValueError(task.category)
