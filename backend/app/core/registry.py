from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = ROOT / "backend/app/models/manifest.json"


@lru_cache(maxsize=1)
def models() -> list[dict]:
    entries = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["models"]
    ids = [entry["id"] for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate model ID in manifest")
    for entry in entries:
        path = ROOT / entry["source_file"]
        if entry.get("sha256") and path.is_file():
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != entry["sha256"]:
                raise ValueError(f"Source checksum mismatch for {entry['id']}")
        runtime_file = entry.get("runtime_file")
        runtime_sha = entry.get("runtime_sha256")
        if runtime_file and runtime_sha:
            runtime_path = (ROOT / runtime_file).resolve()
            if not runtime_path.is_relative_to(ROOT) or not runtime_path.is_file():
                raise ValueError(f"Pinned runtime model missing for {entry['id']}")
            if hashlib.sha256(runtime_path.read_bytes()).hexdigest() != runtime_sha:
                raise ValueError(f"Runtime model checksum mismatch for {entry['id']}")
        initial_file = entry.get("initial_conditions_file")
        initial_sha = entry.get("initial_conditions_sha256")
        if initial_file and initial_sha:
            initial_path = (ROOT / initial_file).resolve()
            if not initial_path.is_relative_to(ROOT) or not initial_path.is_file():
                raise ValueError(f"Pinned initial conditions missing for {entry['id']}")
            if hashlib.sha256(initial_path.read_bytes()).hexdigest() != initial_sha:
                raise ValueError(f"Initial-condition checksum mismatch for {entry['id']}")
    return entries


def model_by_id(model_id: str) -> dict:
    for entry in models():
        if entry["id"] == model_id:
            return entry
    raise KeyError(f"Unknown model: {model_id}")


def source_path(entry: dict) -> Path:
    path = (ROOT / entry.get("runtime_file", entry["source_file"])).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Model path escapes project root")
    return path
