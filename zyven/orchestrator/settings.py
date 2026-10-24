"""Per-runtime settings the user can change from the Control center: switched on or off, and which model.

Stored in `runtime-settings.json` in the board directory. The environment variables still work (a runtime is on if
`ZYVEN_ENABLE_<NAME>=1` or the user switched it on here; `ZYVEN_<NAME>_MODEL` is used when no model is set here).

Letting the shell run on the host (`ZYVEN_OPENCODE_ALLOW_SHELL`) and local-command connectors
(`ZYVEN_ALLOW_STDIO_CONNECTORS`) are deliberately NOT settings: they stay environment-only, so they cannot be
switched on through the web interface.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

MODEL = re.compile(r"[\w./:#\-]{1,100}")
NAMES = ("claude", "codex", "opencode", "agy", "github")  # runtimes that start off
KEYS = {"enabled", "model"}


class RuntimeSettings:
    def __init__(self, directory: Path | None = None) -> None:
        self.path = Path(directory) / "runtime-settings.json" if directory else None
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        if self.path and self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._data = {}

    def get(self, name: str) -> dict[str, Any]:
        return dict(self._data.get(name, {}))

    def all(self) -> dict[str, dict[str, Any]]:
        return {n: self.get(n) for n in NAMES}

    def update(self, name: str, enabled: bool | None = None, model: str | None = None) -> dict[str, Any]:
        if name not in NAMES:
            raise KeyError(name)
        if model is not None:
            model = model.strip()
            if model and not MODEL.fullmatch(model):
                raise ValueError("the model should look like provider/model-name")
        with self._lock:
            cur = self._data.setdefault(name, {})
            if enabled is not None:
                cur["enabled"] = bool(enabled)
            if model is not None:
                cur["model"] = model
            if self.path:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self._data, indent=1), encoding="utf-8")
                tmp.replace(self.path)
            return dict(cur)


# The running board installs its settings here; adapters read them, and fall back to the environment.
_current = RuntimeSettings()


def install(settings: RuntimeSettings) -> None:
    global _current
    _current = settings


def current() -> RuntimeSettings:
    return _current


def is_enabled(name: str, env_flag: str) -> bool:
    return os.environ.get(env_flag) == "1" or bool(_current.get(name).get("enabled"))


def model_for(name: str) -> str:
    return (_current.get(name).get("model") or os.environ.get(f"ZYVEN_{name.upper()}_MODEL", "")).strip()
