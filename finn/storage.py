"""Tiny file-based cache. Everything is saved under data/ so the demo never
depends on a live scrape working at the moment someone opens the app."""
import json
from pathlib import Path

import config


def data_path(*parts: str) -> Path:
    path = config.DATA_DIR.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
    tmp.replace(path)  # atomic: a crash never leaves a half-written file
