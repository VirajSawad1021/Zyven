"""Where Zyven keeps things, for a git checkout and for an installed copy (pipx, uvx, pip).

From a checkout nothing changes: data in `<repo>/workspace`, settings in `<repo>/.env`, compiled skills in `skills/`,
the catalog in `<repo>/catalog/repos.json`. Installed, the package lives in site-packages, which is no place for data,
so everything goes under one home folder instead: `ZYVEN_HOME`, else `~/.zyven`.

  home()          data: board, library (verified skills), runs, catalog checkouts
  env_file()      settings: ZYVEN_ENV, else ./.env if present, else the checkout's .env or <home>/.env
  catalog_file()  pinned catalog: the checkout's catalog/repos.json, else the copy shipped in the package
  skills_out()    default output of `zyven compile`: checkout skills/, else <home>/library (served by `zyven mcp`)
"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent


def checkout_root() -> Path | None:
    """The repository root when running from a git checkout (or an editable install of one)."""
    root = PACKAGE.parent
    if (root / "pyproject.toml").exists() and (root / "catalog" / "repos.json").exists():
        return root
    return None


def home() -> Path:
    if os.environ.get("ZYVEN_HOME"):
        return Path(os.environ["ZYVEN_HOME"]).expanduser().resolve()
    root = checkout_root()
    return (root / "workspace") if root else Path.home() / ".zyven"


def env_file() -> Path:
    if os.environ.get("ZYVEN_ENV"):
        return Path(os.environ["ZYVEN_ENV"]).expanduser()
    if Path(".env").exists():
        return Path(".env")
    root = checkout_root()
    return (root / ".env") if root else home() / ".env"


def catalog_file() -> Path:
    root = checkout_root()
    if root:
        return root / "catalog" / "repos.json"
    return PACKAGE / "data" / "catalog" / "repos.json"


def skills_out() -> Path:
    root = checkout_root()
    return Path("skills") if root else home() / "library"


def site_dir() -> Path:
    """The built dashboard (Next.js static export): the checkout's web/out, else the copy shipped in the package."""
    root = checkout_root()
    if root and (root / "web" / "out").exists():
        return root / "web" / "out"
    return PACKAGE / "data" / "site"
