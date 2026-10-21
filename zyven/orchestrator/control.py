"""Agent Control Center backend: assign a task to a runtime, run it in an isolated environment, observe it.

Runtimes declare what they actually expose; the UI shows "not exposed" for the rest and never invents
numbers. Two runtimes exist today:

  zyven   the built-in self-extending agent (open-weight model); runs as a normal board card
  docker  any command in a locked-down container: live stdout, resource limits, network off by default,
          before/after file diff, optional repo checkout and scheduling

Host paths are never taken from the client: every run gets a directory under `<data>/control/`.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path

DEFAULT_IMAGE = "python:3.12-slim"
MAX_LOG_LINES = 4000
RUN_TIMEOUT_S = 900

RUNTIMES = {
    "zyven": {
        "label": "Zyven agent", "open_weight": True, "available": True,
        "exposes": {"live_output": True, "tool_calls": True, "approvals": True, "file_changes": False, "tokens": False},
        "note": "Built-in self-extending agent. Grows its own MCP tools; asks before compiling.",
    },
    "docker": {
        "label": "Docker command", "open_weight": True, "available": True,
        "exposes": {"live_output": True, "tool_calls": False, "approvals": False, "file_changes": True, "tokens": False},
        "note": "Runs any shell command in a container with limits and a before/after file diff.",
    },
}
# Detected on the host but without an adapter yet: listed so the UI is honest about it.
PLANNED = {
    "hermes": "Headless mode verified (-z, --usage-file); needs a working provider via `hermes model`; adapter not built.",
    "claude": "Headless stream-json verified; login expired, needs `claude` then /login; proprietary, off by default.",
}


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    out = {}
    for p in root.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            st = p.stat()
            out[p.relative_to(root).as_posix()] = (int(st.st_mtime_ns // 1000), st.st_size)
    return out


MIN_REPEAT_SECS, MAX_REPEAT_SECS = 60, 30 * 86400


class Control:
    def __init__(self, db_path: Path, data_dir: Path, board) -> None:
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, title TEXT, runtime TEXT, prompt TEXT, image TEXT,"
            " network INTEGER, memory TEXT, cpus TEXT, repo_url TEXT, run_at REAL, status TEXT, created REAL,"
            " updated REAL, card_id TEXT, exit_code INTEGER, files TEXT, workdir TEXT);"
            "CREATE TABLE IF NOT EXISTS run_events (run TEXT, seq INTEGER, ts REAL, kind TEXT, text TEXT);")
        if "repeat_secs" not in {r[1] for r in self.db.execute("PRAGMA table_info(runs)")}:  # older databases
            self.db.execute("ALTER TABLE runs ADD COLUMN repeat_secs REAL")
        self.root = Path(data_dir) / "control"
        self.root.mkdir(parents=True, exist_ok=True)
        self.board = board
        self._lock = threading.Lock()
        self._procs: dict[str, subprocess.Popen] = {}
        self._cancel: set[str] = set()
        self.db.execute("UPDATE runs SET status='FAILED' WHERE status='RUNNING'")  # interrupted by a restart
        self.db.commit()
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

    # --- lifecycle ----------------------------------------------------------------------------------
    def create(self, *, title: str, runtime: str, prompt: str, image: str = DEFAULT_IMAGE, network: bool = False,
               memory: str = "1g", cpus: str = "1", repo_url: str = "", run_at: float | None = None,
               repeat_secs: float | None = None) -> dict:
        if runtime not in RUNTIMES:
            raise ValueError(f"unknown runtime {runtime!r}")
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
        subprocess.run(["docker", "kill", f"zyven-run-{run_id}"], capture_output=True)
        row = self.db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
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
                due = self.db.execute(
                    "SELECT id FROM runs WHERE runtime='docker' AND status IN ('QUEUED','SCHEDULED') "
                    "AND (run_at IS NULL OR run_at<=?) ORDER BY created LIMIT 1", (time.time(),)).fetchone()
                if due:
                    self._run_docker(due[0])
                    continue
            except Exception as e:  # keep the worker alive
                print("control loop error:", e)
            time.sleep(1.0)

    def _run_docker(self, rid: str) -> None:
        r = self.get(rid)
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
            cmd = ["docker", "run", "--rm", "--name", f"zyven-run-{rid}", "--memory", r["memory"], "--cpus", r["cpus"],
                   "--pids-limit", "256", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                   "-v", f"{work}:/work", "-w", "/work/repo" if r["repo_url"] else "/work"]
            if not r["network"]:
                cmd += ["--network", "none"]
            cmd += [r["image"], "sh", "-c", r["prompt"]]
            self._emit(rid, "info", f"docker run {r['image']} (network {'on' if r['network'] else 'off'}, "
                                    f"{r['memory']} / {r['cpus']} cpu)")
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 encoding="utf-8", errors="replace")
            self._procs[rid] = p
            killer = threading.Timer(RUN_TIMEOUT_S, lambda: subprocess.run(["docker", "kill", f"zyven-run-{rid}"], capture_output=True))
            killer.start()
            for line in p.stdout:  # type: ignore[union-attr]
                self._emit(rid, "out", line.rstrip("\n"))
            code = p.wait()
            killer.cancel()
            after = _snapshot(work)
            files = {"added": sorted(set(after) - set(before)),
                     "modified": sorted(k for k in after if k in before and after[k] != before[k])}
            status = "CANCELLED" if rid in self._cancel else "COMPLETED" if code == 0 else "FAILED"
            self._emit(rid, "info", f"exited with code {code}")
            self._set(rid, status=status, exit_code=code, files=json.dumps(files))
        except Exception as e:
            self._emit(rid, "error", f"{type(e).__name__}: {e}")
            self._set(rid, status="FAILED")
        finally:
            self._procs.pop(rid, None)

    def workdir(self, rid: str) -> Path:
        return self.root / rid

    def purge(self, rid: str) -> None:
        shutil.rmtree(self.root / rid, ignore_errors=True)
