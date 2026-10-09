#!/usr/bin/env python3
"""Refresh checksums of already-pinned local model files, without changing revisions."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "backend/app/models/manifest.json"


def main() -> None:
    data = json.loads(MANIFEST.read_text())
    for model in data["models"]:
        source = ROOT / model["source_file"]
        if source.is_file():
            model["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
            model["download_date"] = model.get("download_date") or date.today().isoformat()
        else:
            model["sha256"] = None
            model["download_date"] = None
            model["status"] = "unavailable"
            model.setdefault("status_reason", "Pinned source file is not present locally.")
    MANIFEST.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
