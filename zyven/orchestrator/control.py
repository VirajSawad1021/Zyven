"""Agent Control Center backend: assign a task to a runtime, run it in an isolated environment, observe it.

Runtimes declare what they actually expose; the UI shows "not exposed" for the rest and never invents
numbers. The built-in Zyven agent runs as a board card; every other runtime is an adapter
(zyven/orchestrator/adapters.py): docker (a command in a locked-down container) and claude (Claude Code,
headless, off by default). The Control center owns queueing, scheduling, repeats, repo checkout and the
before/after file diff, so an adapter only implements `run` and `cancel`.

Host paths are never taken from the client: every run gets a directory under `<data>/control/`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path

from zyven.orchestrator.adapters import RunContext, RuntimeAdapter, default_adapters

DEFAULT_IMAGE = "python:3.12-slim"
MAX_LOG_LINES = 4000

ZYVEN_RUNTIME = {
    "label": "Zyven agent", "open_weight": True, "available": True,
    "exposes": {"live_output": True, "tool_calls": True, "approvals": True, "file_changes": False, "tokens": False},
    "note": "Built-in self-extending agent. Grows its own MCP tools; asks before compiling.",
}
# Detected on the host but without an adapter yet: listed so the UI is honest about it.
PLANNED = {
    "hermes": "Headless mode verified (-z, --usage-file); needs a working provider via `hermes model`; adapter not built.",
}


def runtime_info(adapters: dict[str, RuntimeAdapter]) -> dict[str, dict]:
    """Every runtime's description. Command-line agents also report installed / signed in, which runs each program,
    so the checks go in parallel (and each adapter caches its answer for a minute)."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=max(1, len(adapters))) as pool:
        infos = dict(zip(adapters, pool.map(lambda a: a.info(), adapters.values())))
    from zyven.orchestrator import settings as rs

    for name, info in infos.items():
        if name in rs.NAMES:  # the user can switch these on and pick a model from the page
            info["settings"] = {**{"enabled": False, "model": ""}, **rs.current().get(name)}
            info["env_enabled"] = os.environ.get(f"ZYVEN_ENABLE_{name.upper()}") == "1"
    return {"zyven": ZYVEN_RUNTIME, **infos}


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    out = {}
    for p in root.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            st = p.stat()
            out[p.relative_to(root).as_posix()] = (int(st.st_mtime_ns // 1000), st.st_size)
    return out


MIN_REPEAT_SECS, MAX_REPEAT_SECS = 60, 30 * 86400
APPROVAL_TTL_S = 3600  # an unanswered request is denied after this long


class Control:
    def __init__(self, db_path: Path, data_dir: Path, board, adapters: dict[str, RuntimeAdapter] | None = None,
                 autostart: bool = True) -> None:
        self.adapters = adapters if adapters is not None else default_adapters()
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, title TEXT, runtime TEXT, prompt TEXT, image TEXT,"
            " network INTEGER, memory TEXT, cpus TEXT, repo_url TEXT, run_at REAL, status TEXT, created REAL,"
            " updated REAL, card_id TEXT, exit_code INTEGER, files TEXT, workdir TEXT);"
            "CREATE TABLE IF NOT EXISTS run_events (run TEXT, seq INTEGER, ts REAL, kind TEXT, text TEXT);"
            "CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, run TEXT, kind TEXT, summary TEXT, detail TEXT,"
            " status TEXT, created REAL, decided REAL);")
        if "repeat_secs" not in {r[1] for r in self.db.execute("PRAGMA table_info(runs)")}:  # older databases
            self.db.execute("ALTER TABLE runs ADD COLUMN repeat_secs REAL")
        self.root = Path(data_dir).resolve() / "control"  # absolute: programs started in a task folder resolve paths from inside it
        self.root.mkdir(parents=True, exist_ok=True)
        self.board = board
        self._lock = threading.Lock()
        self._cancel: set[str] = set()
        self.db.execute("UPDATE runs SET status='FAILED' WHERE status IN ('RUNNING','NEEDS_APPROVAL') "
                        "AND runtime != 'zyven'")  # interrupted by a restart
        self.db.execute("UPDATE approvals SET status='EXPIRED' WHERE status='PENDING'")
        self.db.commit()
        if autostart:  # tests drive the worker by hand
            threading.Thread(target=self._loop, daemon=True).start()

    # --- data ---------------------------------------------------------------------------------------
    def _emit(self, run: str, kind: str, text: str) -> None:
        with self._lock:
            seq = self.db.execute("SELECT COALESCE(MAX(seq),-1)+1 FROM run_events WHERE run=?", (run,)).fetchone()[0]
            if seq < MAX_LOG_LINES:
                self.db.execute("INSERT INTO run_events VALUES (?,?,?,?,?)", (run, seq, time.time(), kind, text[:2000]))
                self.db.commit()

    def _set(self, run: str, **kw) -> None:
        with self._lock:
            sets = ", ".join(f"{k}=?" for k in kw)
            self.db.execute(f"UPDATE runs SET {sets}, updated=? WHERE id=?", (*kw.values(), time.time(), run))
            self.db.commit()

    def _row(self, r) -> dict:
        keys = ["id", "title", "runtime", "prompt", "image", "network", "memory", "cpus", "repo_url", "run_at", "status",
                "created", "updated", "card_id", "exit_code", "files"]
        d = dict(zip(keys, r))
        d["network"] = bool(d["network"])
        d["files"] = json.loads(d["files"]) if d["files"] else None
        if d["runtime"] == "zyven" and d["card_id"]:  # status mirrors the board card
            card = next((c for c in self.board.cards() if c["id"] == d["card_id"]), None)
            if card:
                d["status"] = {"DONE": "COMPLETED", "FAILED": "FAILED", "REJECTED": "FAILED",
                               "NEEDS_APPROVAL": "NEEDS_APPROVAL"}.get(card["status"], "RUNNING")
                d["answer"] = card.get("answer")
        return d

    def list(self) -> list[dict]:
        rows = self.db.execute("SELECT id,title,runtime,prompt,image,network,memory,cpus,repo_url,run_at,status,created,"
                               "updated,card_id,exit_code,files FROM runs ORDER BY created DESC").fetchall()
        return [self._row(r) for r in rows]

    def get(self, run_id: str) -> dict:
        r = self.db.execute("SELECT id,title,runtime,prompt,image,network,memory,cpus,repo_url,run_at,status,created,"
                            "updated,card_id,exit_code,files FROM runs WHERE id=?", (run_id,)).fetchone()
        if not r:
            raise KeyError(run_id)
        d = self._row(r)
        d["log"] = [{"ts": ts, "kind": k, "text": t} for ts, k, t in self.db.execute(
            "SELECT ts,kind,text FROM run_events WHERE run=? ORDER BY seq", (run_id,))]
        return d

    # --- approvals ----------------------------------------------------------------------------------
    def request_approval(self, rid: str, kind: str, summary: str, detail: str = "", ttl: float = APPROVAL_TTL_S,
                         poll: float = 0.5) -> bool:
        """Ask the user before an outward action. Blocks the run's worker until they decide.

        Nothing is approved by default: a timeout, a restart or a cancel all mean "no".
        """
        aid = uuid.uuid4().hex[:8]
        with self._lock:
            self.db.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?)",
                            (aid, rid, kind[:40], summary[:300], detail[:4000], "PENDING", time.time(), None))
            self.db.commit()
        self._set(rid, status="NEEDS_APPROVAL")
        self._emit(rid, "info", f"waiting for approval: {summary[:200]}")
        deadline = time.monotonic() + ttl
        status = "PENDING"
        while status == "PENDING":
            if rid in self._cancel or time.monotonic() > deadline:
                with self._lock:
                    self.db.execute("UPDATE approvals SET status='EXPIRED', decided=? WHERE id=? AND status='PENDING'",
                                    (time.time(), aid))
                    self.db.commit()
            status = self.db.execute("SELECT status FROM approvals WHERE id=?", (aid,)).fetchone()[0]
            if status == "PENDING":
                time.sleep(poll)
        if rid not in self._cancel:
            self._set(rid, status="RUNNING")
        self._emit(rid, "info", f"approval {status.lower()}: {summary[:120]}")
        return status == "APPROVED"

    def decide(self, approval_id: str, approve: bool) -> dict:
        with self._lock:
            row = self.db.execute("SELECT status FROM approvals WHERE id=?", (approval_id,)).fetchone()
            if not row:
                raise KeyError(approval_id)
            if row[0] != "PENDING":
                raise ValueError(f"already {row[0].lower()}")
            self.db.execute("UPDATE approvals SET status=?, decided=? WHERE id=?",
                            ("APPROVED" if approve else "DENIED", time.time(), approval_id))
            self.db.commit()
        return self.approvals_for(approval_id=approval_id)[0]

    def approvals_for(self, run: str | None = None, pending_only: bool = False, approval_id: str | None = None) -> list[dict]:
        q, args = "SELECT id,run,kind,summary,detail,status,created,decided FROM approvals WHERE 1=1", []
        for col, val in (("run", run), ("id", approval_id)):
            if val:
                q += f" AND {col}=?"
                args.append(val)
        if pending_only:
            q += " AND status='PENDING'"
        keys = ["id", "run", "kind", "summary", "detail", "status", "created", "decided"]
        return [dict(zip(keys, r)) for r in self.db.execute(q + " ORDER BY created DESC", args).fetchall()]

    # --- lifecycle ----------------------------------------------------------------------------------
    def create(self, *, title: str, runtime: str, prompt: str, image: str = DEFAULT_IMAGE, network: bool = False,
               memory: str = "1g", cpus: str = "1", repo_url: str = "", run_at: float | None = None,
               repeat_secs: float | None = None) -> dict:
        if runtime != "zyven":
            if runtime not in self.adapters:
                raise ValueError(f"unknown runtime {runtime!r}")
            ok, why = self.adapters[runtime].available()
            if not ok:
                raise ValueError(f"runtime {runtime!r} is not available: {why}")
        if not prompt.strip():
            raise ValueError("task is empty")
        if not re.fullmatch(r"\d+(\.\d+)?[mg]", memory) or not re.fullmatch(r"\d+(\.\d+)?", cpus):
            raise ValueError("bad resource limits")
        if repo_url and not re.fullmatch(r"https://[\w.\-]+/[\w.\-/]+?(\.git)?", repo_url):
            raise ValueError("repo_url must be an https URL")
        if not re.fullmatch(r"[\w./:\-]+", image):
            raise ValueError("bad image name")
        if repeat_secs is not None and not MIN_REPEAT_SECS <= repeat_secs <= MAX_REPEAT_SECS:
            raise ValueError("repeat interval must be between 1 minute and 30 days")
        rid = uuid.uuid4().hex[:8]
        now = time.time()
        status = "SCHEDULED" if run_at and run_at > now else "QUEUED"
        card_id = None
        if runtime == "zyven" and status == "QUEUED":  # a scheduled agent task gets its card when it is due
            card_id = self.board.create(prompt.strip())["id"]
            status = "RUNNING"
        self.db.execute("INSERT INTO runs (id,title,runtime,prompt,image,network,memory,cpus,repo_url,run_at,status,"
                        "created,updated,card_id,exit_code,files,workdir) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (rid, title.strip() or prompt.strip()[:60], runtime, prompt.strip(), image, int(network), memory,
                         cpus, repo_url, run_at, status, now, now, card_id, None, None, str(self.root / rid)))
        self.db.execute("UPDATE runs SET repeat_secs=? WHERE id=?", (repeat_secs, rid))
        self.db.commit()
        if repeat_secs and status == "RUNNING":
            self._schedule_next(rid)
        return self.get(rid)

    def cancel(self, run_id: str) -> None:
        self._cancel.add(run_id)
        row = self.db.execute("SELECT status, runtime FROM runs WHERE id=?", (run_id,)).fetchone()
        if row and row[1] in self.adapters:
            self.adapters[row[1]].cancel(run_id)
        if row and row[0] in ("QUEUED", "SCHEDULED"):
            self._set(run_id, status="CANCELLED")

    def _schedule_next(self, rid: str) -> None:
        """A repeating run queues its successor when it starts, so cancelling a waiting run ends the series."""
        r = self.get(rid)
        every = self.db.execute("SELECT repeat_secs FROM runs WHERE id=?", (rid,)).fetchone()[0]
        if not every:
            return
        self.create(title=r["title"], runtime=r["runtime"], prompt=r["prompt"], image=r["image"], network=r["network"],
                    memory=r["memory"], cpus=r["cpus"], repo_url=r["repo_url"],
                    run_at=max(r["run_at"] or 0, time.time()) + every, repeat_secs=every)

    def _start_due_agent_runs(self) -> None:
        for (rid, prompt) in self.db.execute(
                "SELECT id, prompt FROM runs WHERE runtime='zyven' AND status='SCHEDULED' AND run_at<=?",
                (time.time(),)).fetchall():
            self._set(rid, status="RUNNING", card_id=self.board.create(prompt)["id"])
            self._schedule_next(rid)

    def _loop(self) -> None:
        while True:
            try:
                self._start_due_agent_runs()
                marks = ",".join("?" * len(self.adapters))
                due = self.db.execute(
                    f"SELECT id FROM runs WHERE runtime IN ({marks}) AND status IN ('QUEUED','SCHEDULED') "
                    "AND (run_at IS NULL OR run_at<=?) ORDER BY created LIMIT 1",
                    (*self.adapters, time.time())).fetchone() if self.adapters else None
                if due:
                    self._run_worker(due[0])
                    continue
            except Exception as e:  # keep the worker alive
                print("control loop error:", e)
            time.sleep(1.0)

    def _run_worker(self, rid: str) -> None:
        r = self.get(rid)
        adapter = self.adapters[r["runtime"]]
        work = self.root / rid
        work.mkdir(parents=True, exist_ok=True)
        self._set(rid, status="RUNNING")
        self._schedule_next(rid)
        try:
            if r["repo_url"]:
                self._emit(rid, "info", f"cloning {r['repo_url']}")
                c = subprocess.run(["git", "clone", "--depth", "1", "--quiet", r["repo_url"], str(work / "repo")],
                                   capture_output=True, text=True, timeout=300)
                if c.returncode:
                    raise RuntimeError("git clone failed: " + c.stderr.strip()[-300:])
            before = _snapshot(work)
            ctx = RunContext(run=r, workdir=work, cwd=work / "repo" if r["repo_url"] else work,
                             emit=lambda kind, text: self._emit(rid, kind, text),
                             cancelled=lambda: rid in self._cancel,
                             approve=lambda kind, summary, detail="": self.request_approval(rid, kind, summary, detail))
            code = adapter.run(ctx)
            after = _snapshot(work)
            files = {"added": sorted(set(after) - set(before)),
                     "modified": sorted(k for k in after if k in before and after[k] != before[k])}
            status = "CANCELLED" if rid in self._cancel else "COMPLETED" if code == 0 else "FAILED"
            self._emit(rid, "info", f"exited with code {code}")
            self._set(rid, status=status, exit_code=code, files=json.dumps(files))
        except Exception as e:
            self._emit(rid, "error", f"{type(e).__name__}: {e}")
            self._set(rid, status="FAILED")

    def workdir(self, rid: str) -> Path:
        return self.root / rid

    def purge(self, rid: str) -> None:
        shutil.rmtree(self.root / rid, ignore_errors=True)
