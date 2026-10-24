"""Task board backend: cards, a sequential worker, live events (SSE), and human approval.

Run:  uv run zyven board        (http://127.0.0.1:8765)

One task runs at a time (the model host is the bottleneck). Every card event is persisted to SQLite
and streamed to the UI. A card that needs outside code compiled waits in NEEDS_APPROVAL until a
human clicks Approve or Reject; nothing is compiled without that click.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from zyven.agent.self_extend import ApprovalRequest, run_self_extending
from zyven.ai.provider import ModelProvider
from zyven.analysis.analyzer import analyze
from zyven.analysis.explorer import explore
from zyven.catalog.catalog import Catalog
from zyven.connections.probe import probe as probe_connection
from zyven.connections.runtime import load_enabled
from zyven.connections.store import ConnectionError_, ConnectionStore, stdio_allowed
from zyven.connections.templates import TEMPLATES
from zyven.orchestrator.control import DEFAULT_IMAGE, PLANNED, Control, runtime_info
from zyven.memory.skills import SkillLibrary

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "web" / "out"  # the Next.js static export (`cd web && npm run build`)
LEGACY = Path(__file__).with_name("legacy.html")
ART = ROOT / "web" / "public" / "art"

AGENT_SYSTEM = (
    "You are a helpful assistant that completes the user's task using your tools when they apply. "
    "Report tool results faithfully; do not recompute what a tool already returned. Be concise."
)


class NewCard(BaseModel):
    task: str


class Decision(BaseModel):
    approved: bool


class NewConnection(BaseModel):
    name: str
    kind: str
    url: str = ""
    command: str = ""
    args: list[str] = []
    secrets: dict[str, str] = {}


class Toggle(BaseModel):
    enabled: bool


class NewRun(BaseModel):
    title: str = ""
    runtime: str
    prompt: str
    image: str = DEFAULT_IMAGE
    network: bool = False
    memory: str = "1g"
    cpus: str = "1"
    repo_url: str = ""
    run_at: float | None = None
    repeat_secs: float | None = None


class Board:
    def __init__(self, db_path: Path, library: SkillLibrary, catalog: Catalog, provider: ModelProvider) -> None:
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS cards (id TEXT PRIMARY KEY, task TEXT, status TEXT, created REAL,"
            " updated REAL, answer TEXT, learned TEXT, reused TEXT);"
            "CREATE TABLE IF NOT EXISTS events (card TEXT, seq INTEGER, ts REAL, kind TEXT, data TEXT);")
        self.library, self.catalog, self.provider = library, catalog, provider
        self.connections: ConnectionStore | None = None  # services the user connected (set when the app starts)
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.listeners: set[asyncio.Queue] = set()
        self.approvals: dict[str, asyncio.Future] = {}
        self.loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()  # compile events arrive from worker threads
        # Cards interrupted by a restart are marked failed rather than silently lost.
        self.db.execute("UPDATE cards SET status='FAILED', answer='interrupted by restart' "
                        "WHERE status NOT IN ('DONE','FAILED','UNVERIFIED')")
        self.db.commit()

    # --- persistence + fan-out ---------------------------------------------------------------
    def _publish(self, payload: dict) -> None:
        def push() -> None:
            for q in list(self.listeners):
                q.put_nowait(payload)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if self.loop and running is not self.loop:
            self.loop.call_soon_threadsafe(push)  # called from a worker thread
        else:
            push()

    def emit(self, card_id: str, kind: str, data: dict) -> None:
        clean = json.loads(json.dumps(data, default=str))
        status = kind if kind.isupper() else None
        with self._lock:
            seq = self.db.execute("SELECT COUNT(*) FROM events WHERE card=?", (card_id,)).fetchone()[0]
            self.db.execute("INSERT INTO events VALUES (?,?,?,?,?)",
                            (card_id, seq, time.time(), kind, json.dumps(clean)))
            if status:
                self.db.execute("UPDATE cards SET status=?, updated=? WHERE id=?", (status, time.time(), card_id))
            self.db.commit()
        self._publish({"type": "event", "card": card_id, "kind": kind, "data": clean, "status": status})

    def card(self, card_id: str) -> dict | None:
        row = self.db.execute("SELECT id, task, status, created, updated, answer, learned, reused FROM cards "
                              "WHERE id=?", (card_id,)).fetchone()
        if not row:
            return None
        keys = ["id", "task", "status", "created", "updated", "answer", "learned", "reused"]
        c = dict(zip(keys, row))
        c["learned"] = json.loads(c["learned"] or "[]")
        c["reused"] = json.loads(c["reused"] or "[]")
        c["events"] = [{"seq": s, "ts": ts, "kind": k, "data": json.loads(d)} for s, ts, k, d in self.db.execute(
            "SELECT seq, ts, kind, data FROM events WHERE card=? ORDER BY seq", (card_id,))]
        return c

    def cards(self) -> list[dict]:
        ids = [r[0] for r in self.db.execute("SELECT id FROM cards ORDER BY created DESC LIMIT 50")]
        return [self.card(i) for i in ids]

    # --- lifecycle ----------------------------------------------------------------------------
    def create(self, task: str) -> dict:
        cid = uuid.uuid4().hex[:8]
        now = time.time()
        self.db.execute("INSERT INTO cards VALUES (?,?,?,?,?,?,?,?)", (cid, task, "QUEUED", now, now, None, "[]", "[]"))
        self.db.commit()
        self.queue.put_nowait(cid)
        self._publish({"type": "card", "card": self.card(cid)})
        return self.card(cid)

    async def worker(self) -> None:
        self.loop = asyncio.get_running_loop()
        while True:
            cid = await self.queue.get()
            task = self.db.execute("SELECT task FROM cards WHERE id=?", (cid,)).fetchone()[0]

            async def approve(req: ApprovalRequest, cid=cid) -> bool:
                fut = asyncio.get_running_loop().create_future()
                self.approvals[cid] = fut
                try:
                    return await fut
                finally:
                    self.approvals.pop(cid, None)

            try:
                connect = None
                if self.connections is not None:
                    store = self.connections

                    async def connect(tb, emit, ask, store=store):
                        return await load_enabled(tb, store, emit, ask)

                res = await run_self_extending(self.provider, task, self.library, self.catalog, approve,
                                               on_event=lambda k, d, cid=cid: self.emit(cid, k, d),
                                               system=AGENT_SYSTEM, connect=connect)
                answer = res.answer.final_text if res.answer else ""
                with self._lock:
                    self.db.execute("UPDATE cards SET answer=?, learned=?, reused=?, status=? WHERE id=?",
                                    (answer, json.dumps(res.learned), json.dumps(res.reused), res.status, cid))
                    self.db.commit()
            except Exception as e:  # noqa: BLE001 - a crashing task must not kill the worker
                self.emit(cid, "FAILED", {"detail": f"{type(e).__name__}: {e}"[:500]})
                with self._lock:
                    self.db.execute("UPDATE cards SET answer=? WHERE id=?", (f"error: {e}"[:500], cid))
                    self.db.commit()
            self._publish({"type": "card", "card": self.card(cid)})

    def decide(self, card_id: str, approved: bool) -> None:
        fut = self.approvals.get(card_id)
        if not fut or fut.done():
            raise KeyError(card_id)
        self.emit(card_id, "approval.decision", {"detail": "approved by user" if approved else "rejected by user"})
        fut.set_result(approved)

    def stats(self) -> dict:
        """Aggregates for the Insights view, computed from persisted cards and events."""
        cards = self.cards()
        per_card = []
        for c in cards:
            evs = c["events"]
            gates = [e for e in evs if e["kind"].startswith("compile.gate.")]
            compiles = sum(1 for e in evs if e["kind"] == "COMPILING")
            per_card.append({
                "id": c["id"], "task": c["task"][:110], "status": c["status"],
                "created": c["created"],
                "duration": round(c["updated"] - c["created"], 1) if c["updated"] and c["created"] else None,
                "learned": c["learned"], "reused": c["reused"],
                "compiled": compiles > 0, "compiles": compiles,
                "gates": [{"name": e["kind"].removeprefix("compile.gate."), "passed": bool(e["data"].get("passed"))}
                          for e in gates],
            })
        compile_cards = [p for p in per_card if p["compiled"]]
        reuse_cards = [p for p in per_card if not p["compiled"] and p["duration"] is not None]
        gate_out: dict[str, dict] = {}
        for p in per_card:
            for g in p["gates"]:
                d = gate_out.setdefault(g["name"], {"pass": 0, "fail": 0})
                d["pass" if g["passed"] else "fail"] += 1
        # Cumulative skill growth over time (learned events in card order).
        growth, seen = [], set()
        for p in sorted(per_card, key=lambda x: x["created"]):
            for s in p["learned"]:
                if s not in seen:
                    seen.add(s)
                    growth.append({"skill": s, "ts": p["created"]})
        return {
            "cards": sorted(per_card, key=lambda x: x["created"]),
            "totals": {
                "tasks": len(per_card),
                "done": sum(1 for p in per_card if p["status"] == "DONE"),
                "unverified": sum(1 for p in per_card if p["status"] == "UNVERIFIED"),
                "failed": sum(1 for p in per_card if p["status"] == "FAILED"),
                "skills": len(growth),
                "reuses": sum(len(p["reused"]) for p in per_card),
            },
            "averages": {
                "compile_s": round(sum(p["duration"] for p in compile_cards if p["duration"]) / len(compile_cards), 1)
                if compile_cards else None,
                "reuse_s": round(sum(p["duration"] for p in reuse_cards) / len(reuse_cards), 1)
                if reuse_cards else None,
            },
            "gates": gate_out,
            "growth": growth,
        }


def create_app(env_path: Path = ROOT / ".env", data_dir: Path = ROOT / "workspace",
               board_dir: Path | None = None) -> FastAPI:
    """data_dir holds catalog checkouts and analysis caches; board_dir (default: data_dir) holds the board's own
    state, its tasks and skill library, so a separate board can start clean without re-cloning the catalog."""
    state: dict = {}
    board_dir = board_dir or data_dir

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        data_dir.mkdir(parents=True, exist_ok=True)
        board_dir.mkdir(parents=True, exist_ok=True)
        board = Board(board_dir / "board.sqlite", SkillLibrary(board_dir / "library"),
                      Catalog(ROOT / "catalog" / "repos.json", data_dir), ModelProvider.from_env(env_path))
        state["board"] = board
        state["control"] = Control(board_dir / "board.sqlite", board_dir, board)
        state["connections"] = board.connections = ConnectionStore(board_dir)
        worker = asyncio.create_task(board.worker())
        yield
        worker.cancel()

    app = FastAPI(title="Zyven board", lifespan=lifespan)

    # The Next.js site (web/out) is mounted last, after every API route. The single-file page is a
    # no-build fallback: it is served at / when the site is not built, and always at /legacy.
    @app.get("/legacy")
    def legacy():
        return FileResponse(LEGACY)

    @app.get("/art/{name}")
    def art(name: str):
        if "/" in name or "\\" in name or ".." in name:
            raise HTTPException(400, "bad path")
        f = ART / name
        if not f.exists():
            raise HTTPException(404, "not found")
        return FileResponse(f, media_type="image/webp")

    @app.get("/api/cards")
    def list_cards():
        return state["board"].cards()

    @app.post("/api/cards")
    def new_card(body: NewCard):
        if not body.task.strip():
            raise HTTPException(400, "task is empty")
        return state["board"].create(body.task.strip())

    @app.post("/api/cards/{card_id}/decision")
    def decide(card_id: str, body: Decision):
        try:
            state["board"].decide(card_id, body.approved)
        except KeyError:
            raise HTTPException(409, "card is not waiting for approval") from None
        return {"ok": True}

    @app.get("/api/skills")
    def skills():
        b: Board = state["board"]
        health = b.library.health()
        return [{"name": s.name, "title": s.spec.title, "summary": s.spec.summary, "source": s.source,
                 "verified_for": s.verified_for, "tools": [t.name for t in s.spec.tools],
                 "health": health.get(s.name, {"ok": 0, "calls": 0})} for s in b.library.list()]

    @app.get("/api/catalog")
    def catalog():
        b: Board = state["board"]
        return [{"repo": r.name, "url": r.url, "commit": r.commit, "license": r.license, "note": r.note}
                for r in b.catalog.repos]

    @app.get("/api/stats")
    def stats():
        return state["board"].stats()

    # --- agent control center: runtimes, runs, environments ---

    @app.get("/api/runtimes")
    def runtimes():
        return {"runtimes": runtime_info(state["control"].adapters), "planned": PLANNED, "default_image": DEFAULT_IMAGE}

    @app.get("/api/runs")
    def runs():
        return state["control"].list()

    @app.post("/api/runs")
    def new_run(body: NewRun):
        try:
            return state["control"].create(**body.model_dump())
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str):
        try:
            return state["control"].get(run_id)
        except KeyError:
            raise HTTPException(404, "unknown run") from None

    @app.post("/api/runs/{run_id}/cancel")
    def run_cancel(run_id: str):
        state["control"].cancel(run_id)
        return {"ok": True}

    # --- connections: MCP servers the user connects (secrets stay on this machine) ---
    @app.get("/api/connections")
    def connections():
        return {"connections": state["connections"].list(), "templates": TEMPLATES, "stdio_allowed": stdio_allowed()}

    @app.post("/api/connections")
    def connection_add(body: NewConnection):
        try:
            return state["connections"].add(**body.model_dump())
        except ConnectionError_ as e:
            raise HTTPException(400, str(e)) from None

    @app.post("/api/connections/{cid}/test")
    async def connection_test(cid: str):
        try:
            return await probe_connection(state["connections"], cid)
        except KeyError:
            raise HTTPException(404, "unknown connection") from None

    @app.post("/api/connections/{cid}/enabled")
    def connection_enable(cid: str, body: Toggle):
        try:
            return state["connections"].set_enabled(cid, body.enabled)
        except KeyError:
            raise HTTPException(404, "unknown connection") from None
        except ConnectionError_ as e:
            raise HTTPException(400, str(e)) from None

    @app.delete("/api/connections/{cid}")
    def connection_remove(cid: str):
        try:
            state["connections"].remove(cid)
        except KeyError:
            raise HTTPException(404, "unknown connection") from None
        return {"ok": True}

    @app.get("/api/approvals")
    def approvals(pending: bool = True):
        return state["control"].approvals_for(pending_only=pending)

    @app.post("/api/approvals/{approval_id}")
    def approval_decide(approval_id: str, body: Decision):
        try:
            return state["control"].decide(approval_id, body.approved)
        except KeyError:
            raise HTTPException(404, "unknown approval") from None
        except ValueError as e:
            raise HTTPException(409, str(e)) from None

    # --- repo explorer: static analysis -> funnel + module graph (cached per repo, computed in a thread) ---
    jobs: dict[str, dict] = {}

    def _explore_file(name: str) -> Path:
        return data_dir / "explore" / f"{name}.json"

    def _repo(name: str):
        b: Board = state["board"]
        r = next((x for x in b.catalog.repos if x.name == name), None)
        if r is None:
            raise HTTPException(404, "unknown repo")
        return b, r

    def _run_explore(name: str) -> None:
        try:
            b, r = _repo(name)
            d = b.catalog.checkout_dir(r)
            if not (d / ".git").exists():
                raise RuntimeError("repo is not cloned yet; run catalog sync first")
            t0 = time.time()
            caps = [{"name": c.name, "title": c.title, "entry_points": list(c.entry_points)}
                    for c in b.catalog.capabilities(r)]
            out = explore(analyze(d), caps)
            out["analyzed_in_s"] = round(time.time() - t0, 1)
            out["analyzed_at"] = time.time()
            _explore_file(name).parent.mkdir(parents=True, exist_ok=True)
            _explore_file(name).write_text(json.dumps(out), encoding="utf-8")
            jobs[name] = {"state": "done"}
        except Exception as e:  # surfaced in the UI instead of a silent hang
            jobs[name] = {"state": "error", "error": f"{type(e).__name__}: {e}"}

    @app.get("/api/explore")
    def explore_list():
        b: Board = state["board"]
        out = []
        for r in b.catalog.repos:
            f = _explore_file(r.name)
            cached = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
            funnel = cached["funnel"] if cached else []
            out.append({"repo": r.name, "note": r.note, "license": r.license,
                        "cloned": (b.catalog.checkout_dir(r) / ".git").exists(),
                        "job": jobs.get(r.name, {"state": "idle"}),
                        "analyzed": cached is not None,
                        "symbols": funnel[0]["count"] if funnel else None,
                        "mcp_able": funnel[4]["count"] if funnel else None})
        return out

    @app.get("/api/explore/{name}")
    def explore_get(name: str):
        _repo(name)
        f = _explore_file(name)
        if not f.exists():
            raise HTTPException(404, "not analyzed yet")
        return json.loads(f.read_text(encoding="utf-8"))

    @app.post("/api/explore/{name}/analyze")
    def explore_start(name: str):
        _repo(name)
        if jobs.get(name, {}).get("state") == "running":
            return jobs[name]
        jobs[name] = {"state": "running", "started": time.time()}
        threading.Thread(target=_run_explore, args=(name,), daemon=True).start()
        return jobs[name]

    @app.get("/api/stream")
    async def stream():
        b: Board = state["board"]
        q: asyncio.Queue = asyncio.Queue()
        b.listeners.add(q)

        async def gen():
            try:
                yield "retry: 2000\n\n"
                while True:
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=15)
                        yield f"data: {json.dumps(msg)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                b.listeners.discard(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    if (SITE / "index.html").exists():
        app.mount("/", StaticFiles(directory=SITE, html=True), name="site")
    else:
        @app.get("/")
        def index():
            return FileResponse(LEGACY)

    return app


def serve(host: str = "127.0.0.1", port: int = 8765, board_dir: Path | None = None) -> None:
    import uvicorn

    uvicorn.run(create_app(board_dir=board_dir), host=host, port=port, log_level="warning")
