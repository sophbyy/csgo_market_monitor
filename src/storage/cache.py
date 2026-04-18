from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock
from typing import Any


class FileCache:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._lock = Lock()
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                self._data = json.load(handle)
        except (json.JSONDecodeError, ValueError):
            logging.getLogger(__name__).warning(
                "Corrupt cache file %s, starting fresh.", self.path
            )
            self._data = {}

    def get(self, key: str) -> Any:
        with self._lock:
            return self._data.get(key)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as handle:
                json.dump(self._data, handle)

