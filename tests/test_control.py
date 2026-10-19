"""Control center scheduling (no Docker, no network)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.orchestrator.control import Control  # noqa: E402


class FakeBoard:
    def __init__(self) -> None:
        self.tasks: list[str] = []

    def create(self, task: str) -> dict:
        self.tasks.append(task)
        return {"id": f"card{len(self.tasks)}"}

    def cards(self) -> list[dict]:
        return [{"id": f"card{i + 1}", "status": "RUNNING"} for i in range(len(self.tasks))]


def _control(tmp_path, board) -> Control:
    c = Control(tmp_path / "control.sqlite", tmp_path, board)
    c._loop = lambda: None  # not used: the tests call the scheduler directly
    return c


def test_agent_task_starts_immediately_without_a_start_time(tmp_path):
    board = FakeBoard()
    run = _control(tmp_path, board).create(title="", runtime="zyven", prompt="convert a date")
    assert board.tasks == ["convert a date"] and run["status"] == "RUNNING" and run["card_id"]


def test_scheduled_agent_task_waits_until_it_is_due(tmp_path):
    board = FakeBoard()
    c = _control(tmp_path, board)
    run = c.create(title="", runtime="zyven", prompt="later", run_at=time.time() + 3600)
    assert run["status"] == "SCHEDULED" and run["card_id"] is None and board.tasks == []
    c._start_due_agent_runs()
    assert board.tasks == [] and c.get(run["id"])["status"] == "SCHEDULED"  # not due yet

    c._set(run["id"], run_at=time.time() - 1)
    c._start_due_agent_runs()
    started = c.get(run["id"])
    assert board.tasks == ["later"] and started["status"] == "RUNNING" and started["card_id"] == "card1"
    c._start_due_agent_runs()
    assert board.tasks == ["later"]  # started exactly once


def test_repeating_task_queues_its_successor_when_it_starts(tmp_path):
    board = FakeBoard()
    c = _control(tmp_path, board)
    first = c.create(title="", runtime="zyven", prompt="daily", run_at=time.time() + 3600, repeat_secs=86400)
    assert [r["status"] for r in c.list()] == ["SCHEDULED"]  # nothing queued behind it yet

    c._set(first["id"], run_at=time.time() - 1)
    c._start_due_agent_runs()
    runs = {r["id"]: r for r in c.list()}
    nxt = next(r for i, r in runs.items() if i != first["id"])
    assert runs[first["id"]]["status"] == "RUNNING" and nxt["status"] == "SCHEDULED"
    assert 86300 < nxt["run_at"] - time.time() <= 86400  # one interval from now

    c.cancel(nxt["id"])  # cancelling the waiting run ends the series
    c._start_due_agent_runs()
    assert len(c.list()) == 2 and board.tasks == ["daily"]


def test_repeat_interval_is_bounded(tmp_path):
    import pytest

    c = _control(tmp_path, FakeBoard())
    for bad in (5, 10 * 86400 * 4):
        with pytest.raises(ValueError):
            c.create(title="", runtime="zyven", prompt="x", repeat_secs=bad)
