"""Getting a run's results out: download a file, a zip of all of them, open the folder (no model, no network)."""

from __future__ import annotations

import io
import os
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_control import FakeBoard  # noqa: E402
from zyven.orchestrator.adapters import RunContext, RuntimeAdapter  # noqa: E402
from zyven.orchestrator.control import Control  # noqa: E402
from zyven.orchestrator.server import create_app  # noqa: E402


class Writer(RuntimeAdapter):
    name, label = "writer", "Writer"

    def run(self, ctx: RunContext) -> int:
        (ctx.cwd / "index.html").write_text("<script>alert(1)</script>", encoding="utf-8")
        (ctx.cwd / "sub").mkdir()
        (ctx.cwd / "sub" / "notes.txt").write_text("hello", encoding="utf-8")
        return 0


def _state_of(app) -> dict:
    """The closure dict create_app keeps its Board / Control / stores in."""
    for route in app.routes:
        for cell in getattr(getattr(route, "endpoint", None), "__closure__", None) or ():
            try:
                value = cell.cell_contents
            except ValueError:
                continue
            if isinstance(value, dict) and "control" in value:
                return value
    raise AssertionError("could not find the app state")


@pytest.fixture
def served(tmp_path):
    env = tmp_path / ".env"
    env.write_text("MODEL_BASE_URL=http://127.0.0.1:9/v1\nMODEL_NAME=x\nMODEL_API_KEY=x\n", encoding="utf-8")
    app = create_app(env_path=env, data_dir=tmp_path, board_dir=tmp_path / "board")
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        ctl = Control(tmp_path / "c2.sqlite", tmp_path / "c2", FakeBoard(), {"writer": Writer()}, autostart=False)
        _state_of(app)["control"] = ctl  # a Control with a stand-in agent in place of the real one
        rid = ctl.create(title="", runtime="writer", prompt="x")["id"]
        ctl._run_worker(rid)
        yield client, ctl, rid


def test_a_changed_file_downloads_but_is_never_rendered_by_the_board(served):
    client, _, rid = served
    r = client.get(f"/api/runs/{rid}/files/index.html")
    assert r.status_code == 200 and r.text == "<script>alert(1)</script>"
    assert "attachment" in r.headers["content-disposition"] and r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-type"] == "application/octet-stream"  # an HTML page a model wrote must not run on this origin
    assert client.get(f"/api/runs/{rid}/files/sub/notes.txt").text == "hello"


def test_only_files_the_run_changed_and_nothing_outside_its_folder(served):
    client, ctl, rid = served
    (ctl.workdir(rid) / "unlisted.txt").write_text("not reported as changed", encoding="utf-8")
    assert client.get(f"/api/runs/{rid}/files/unlisted.txt").status_code == 404
    assert client.get(f"/api/runs/{rid}/files/../../c2.sqlite").status_code in (400, 404)
    assert client.get(f"/api/runs/{rid}/files/%2e%2e/%2e%2e/c2.sqlite").status_code in (400, 404)
    assert client.get("/api/runs/nope/files/index.html").status_code == 404


def test_the_zip_holds_exactly_the_changed_files(served):
    client, _, rid = served
    z = client.get(f"/api/runs/{rid}/archive")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    assert sorted(zipfile.ZipFile(io.BytesIO(z.content)).namelist()) == ["index.html", "sub/notes.txt"]


def test_open_folder_opens_only_the_runs_own_folder(served, monkeypatch):
    client, ctl, rid = served
    opened = []
    monkeypatch.setattr(os, "startfile", lambda p: opened.append(Path(p)), raising=False)
    monkeypatch.setattr("subprocess.Popen", lambda cmd, *a, **k: opened.append(Path(cmd[-1])))
    r = client.post(f"/api/runs/{rid}/reveal")
    assert r.status_code == 200 and opened == [ctl.workdir(rid)]
    assert client.post("/api/runs/nope/reveal").status_code == 404


# --- export folder -----------------------------------------------------------------------------------------------

def test_export_needs_a_chosen_folder_and_rejects_bad_ones(served, tmp_path):
    client, ctl, rid = served
    assert client.post(f"/api/runs/{rid}/export").status_code == 400  # nothing chosen yet
    assert client.get("/api/export-settings").json()["export_dir"] is None
    for bad in ("relative/folder", str(tmp_path / "does-not-exist"), tmp_path.anchor):
        r = client.post("/api/export-settings", json={"export_dir": bad})
        assert r.status_code == 400, bad
    if os.name == "nt":
        assert client.post("/api/export-settings", json={"export_dir": r"C:\Windows"}).status_code == 400
    assert client.post("/api/export-settings", json={"export_dir": str(tmp_path)}).status_code == 200


def test_export_copies_the_runs_files_into_a_new_subfolder_and_never_overwrites(served, tmp_path):
    client, ctl, rid = served
    dest = tmp_path / "Desktop"
    dest.mkdir()
    (dest / "keep.txt").write_text("mine", encoding="utf-8")
    assert client.post("/api/export-settings", json={"export_dir": str(dest)}).json()["export_dir"] == str(dest.resolve())
    first = client.post(f"/api/runs/{rid}/export").json()
    assert first["copied"] == 2 and Path(first["to"]).parent == dest.resolve()
    assert (Path(first["to"]) / "index.html").read_text(encoding="utf-8") == "<script>alert(1)</script>"
    assert (Path(first["to"]) / "sub" / "notes.txt").read_text(encoding="utf-8") == "hello"
    second = client.post(f"/api/runs/{rid}/export").json()  # again: a new folder, the first is untouched
    assert second["to"] != first["to"] and Path(second["to"]).is_dir() and Path(first["to"]).is_dir()
    assert (dest / "keep.txt").read_text(encoding="utf-8") == "mine"
    assert not any(p.name == "unlisted.txt" for p in dest.rglob("*"))  # only what the run produced


def test_the_export_setting_survives_a_restart(tmp_path):
    from zyven.orchestrator.settings import RuntimeSettings

    folder = tmp_path / "out"
    folder.mkdir()
    RuntimeSettings(tmp_path).set_export_dir(str(folder))
    assert RuntimeSettings(tmp_path).export_dir() == str(folder.resolve())
