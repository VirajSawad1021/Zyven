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
