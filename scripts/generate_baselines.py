#!/usr/bin/env python3
"""Generate reviewed numerical regression artifacts for enabled models."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.backends.myokit_backend import MyokitBackend  # noqa: E402
from app.backends.ni_backend import NiBackend  # noqa: E402
from app.backends.simone_backend import SimoneBackend  # noqa: E402
from app.backends.herrera_backend import HerreraBackend  # noqa: E402
from app.core.registry import model_by_id  # noqa: E402
from app.core.schemas import SimulationRequest  # noqa: E402

SETTINGS = {
    "torord_dyncl_endo": (1000, 50, ["INa", "IKr", "ICaL"]),
    "bps2020": (1000, 50, ["INa", "IKr", "ICaL"]),
    "ord_2011": (1000, 50, ["INa", "IKr", "ICaL"]),
    "grandi_2011": (1000, 50, ["INa", "IKr", "ICaL"]),
    "fabbri_2017": (3000, 5, ["If", "IKr", "ICaL"]),
    "linder_fabbri_2025": (3000, 5, ["If", "IKr", "ICaL"]),
    "ni_2023_atrial": (1000, 0, ["INa", "IKr", "ICaL", "IKur"]),
    "simone_wt": (3000, 0, ["INa", "IKr", "ICaL"]),
    "simone_ts22": (3000, 0, ["INa", "IKr", "ICaL"]),
    "herrera_2025_male_nsr": (1000, 0, []),
    "herrera_2025_female_nsr": (1000, 0, []),
    "herrera_2025_male_caf": (1000, 0, []),
    "herrera_2025_female_caf": (1000, 0, []),
}


def main() -> None:
    manifest_path = ROOT / "backend/app/models/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    selected_ids = sys.argv[1:] or list(SETTINGS)
    unknown = set(selected_ids) - set(SETTINGS)
    if unknown:
        raise SystemExit(f"Unknown baseline target(s): {', '.join(sorted(unknown))}")
    for model_id in selected_ids:
        duration, prepace, currents = SETTINGS[model_id]
        entry = model_by_id(model_id)
        request = SimulationRequest(model_id=model_id, duration_ms=duration, prepace_beats=prepace, include_currents=currents)
        backends = {
            "myokit": MyokitBackend, "external_compiled": NiBackend,
            "simone_static": SimoneBackend, "herrera_octave": HerreraBackend,
        }
        result = backends[entry["backend"]]().simulate(entry, request)
        v = np.asarray(result["voltage_mv"])
        metrics = result["metrics"]
        selected = metrics.get("last_valid_beat") if metrics["mode"] == "paced" else metrics
        if not selected or not selected.get("valid") or not np.all(np.isfinite(v)) or np.ptp(v) < 30:
            raise RuntimeError(f"Baseline gate failed for {model_id}")
        if metrics["mode"] == "paced" and selected.get("apd90_ms") is None:
            raise RuntimeError(f"APD90 not measurable for {model_id}")
        if any(name not in result["currents"] for name in currents):
            raise RuntimeError(f"Missing current for {model_id}")
        folder = ROOT / "backend/tests/reference" / model_id
        folder.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(folder / "baseline_trace.npz", time_ms=result["time_ms"], voltage_mv=result["voltage_mv"])
        summary = {
            "model_id": model_id, "source_sha256": entry["sha256"],
            "request": request.model_dump(), "settings_actual": result["settings_actual"],
            "voltage_min_mv": float(v.min()), "voltage_max_mv": float(v.max()),
            "selected_metrics": selected,
            "current_peak_abs": {name: float(np.max(np.abs(result["currents"][name]["values"]))) for name in currents},
            "tolerances": {"trace_rmse_mv": 3.0, "metric_relative": 0.1, "current_peak_relative": 0.2},
        }
        if model_id == "ni_2023_atrial":
            summary["upstream_reference_apd90_ms"] = 288.77
            summary["upstream_reference_tolerance_ms"] = 5.0
        (folder / "baseline.json").write_text(json.dumps(summary, indent=2) + "\n")
        (folder / "provenance.json").write_text(json.dumps(result["provenance"], indent=2) + "\n")
        print(model_id, selected)
        for item in manifest["models"]:
            if item["id"] == model_id:
                item["status"] = "enabled"
                item.pop("status_reason", None)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
