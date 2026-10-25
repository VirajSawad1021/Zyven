"""The board shares one sqlite connection between request threads and task workers; every use must take the lock.

Found live: polling the cards while a task wrote events raised 'sqlite3.InterfaceError: bad parameter or other API misuse'
and the page got a 500.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.orchestrator.server import Board  # noqa: E402


class _Nothing:
    repos: list = []


def test_reading_cards_while_events_are_written_from_other_threads_never_fails(tmp_path):
    board = Board(tmp_path / "b.sqlite", library=None, catalog=_Nothing(), provider=None)  # type: ignore[arg-type]
    board.queue = None  # type: ignore[assignment]  # create() would queue work; this test only needs the rows
    cid = "abc12345"
    board.db.execute("INSERT INTO cards VALUES (?,?,?,?,?,?,?,?)", (cid, "t", "RUNNING", 0, 0, None, "[]", "[]"))
    board.db.commit()
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            for i in range(300):
                board.emit(cid, "NOTE", {"i": i})
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    def reader() -> None:
        try:
            for _ in range(300):
                assert board.card(cid) is not None
                board.cards()
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=writer) for _ in range(2)] + [threading.Thread(target=reader) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, errors[:1]
    assert len(board.card(cid)["events"]) == 600
