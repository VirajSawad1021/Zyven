"""Installed (pipx/uvx) versus checkout paths, the board without a model key, and the sandbox image stamp."""

from __future__ import annotations

from pathlib import Path

import pytest

from zyven import paths, setup


def test_checkout_keeps_its_old_layout(monkeypatch):
    monkeypatch.delenv("ZYVEN_HOME", raising=False)
    root = paths.checkout_root()
    assert root is not None and (root / "pyproject.toml").exists()
    assert paths.home() == root / "workspace"
    assert paths.catalog_file() == root / "catalog" / "repos.json"
    assert paths.skills_out() == Path("skills")


def test_installed_copy_uses_a_home_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "checkout_root", lambda: None)
    monkeypatch.delenv("ZYVEN_HOME", raising=False)
    monkeypatch.delenv("ZYVEN_ENV", raising=False)
    monkeypatch.chdir(tmp_path)  # no ./.env here
    assert paths.home() == Path.home() / ".zyven"
    assert paths.env_file() == Path.home() / ".zyven" / ".env"
    assert paths.skills_out() == Path.home() / ".zyven" / "library"  # what `zyven mcp` serves
    assert paths.catalog_file() == paths.PACKAGE / "data" / "catalog" / "repos.json"
    monkeypatch.setenv("ZYVEN_HOME", str(tmp_path / "h"))
    assert paths.home() == (tmp_path / "h").resolve()


def test_a_local_env_file_wins(monkeypatch, tmp_path):
    monkeypatch.delenv("ZYVEN_ENV", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("MODEL_NAME=x\n", encoding="utf-8")
    assert paths.env_file() == Path(".env")
    monkeypatch.setenv("ZYVEN_ENV", str(tmp_path / "other.env"))
    assert paths.env_file() == tmp_path / "other.env"


def test_launch_command_for_uvx_uses_the_environment_not_the_symlinked_python(monkeypatch):
    from zyven import cli
    monkeypatch.setattr(paths, "checkout_root", lambda: None)
    # Linux CI: the environment is in uv's cache, while its python resolves into the shared Python install
    monkeypatch.setattr(cli.sys, "prefix", "/home/runner/work/_temp/setup-uv-cache/archive-v0/AbC123")
    monkeypatch.setattr(cli.sys, "executable", "/home/runner/.local/share/uv/python/cpython-3.12/bin/python3.12")
    assert cli.launch_command()[0] == "uvx"
    monkeypatch.setattr(cli.sys, "prefix", "/home/me/.local/share/uv/tools/zyven")  # uv tool install: stable
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/home/me/.local/bin/zyven")
    assert cli.launch_command() == ["/home/me/.local/bin/zyven"]


def test_build_hash_tracks_every_file_baked_into_the_image(monkeypatch, tmp_path):
    for name in setup.BUILD_FILES:
        (tmp_path / name).write_text(name, encoding="utf-8")
    monkeypatch.setattr(setup, "SANDBOX_DIR", tmp_path)
    before = setup.build_hash()
    (tmp_path / "diff_check.py").write_text("changed", encoding="utf-8")
    assert setup.build_hash() != before  # a changed in-container script makes the old image stale


def test_board_starts_without_a_model_key(tmp_path):
    from fastapi.testclient import TestClient

    from zyven.orchestrator.server import create_app
    env = tmp_path / ".env"
    env.write_text("MODEL_NAME=x\n", encoding="utf-8")  # no key
    with TestClient(create_app(env_path=env, data_dir=tmp_path, board_dir=tmp_path / "board"),
                    base_url="http://127.0.0.1") as c:  # the board answers only local host names
        assert c.get("/api/skills").status_code == 200


def test_no_model_explains_what_to_do():
    from zyven.ai.provider import ProviderError
    from zyven.orchestrator.server import NoModel
    with pytest.raises(ProviderError, match="--agent codex"):
        NoModel("MODEL_API_KEY is empty").chat([{"role": "user", "content": "hi"}])
