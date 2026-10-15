"""Pinned Grandits single-beat surrogate adapter."""
from __future__ import annotations

import hashlib
import sys
from functools import lru_cache

import numpy as np

from app.backends.base import SimulationBackend
from app.core.metrics import paced_metrics
from app.core.registry import ROOT, source_path
from app.core.schemas import SimulationRequest


@lru_cache(maxsize=1)
def load_emulator():
    import torch

    from app.core.registry import model_by_id

    entry = model_by_id("grandits_2024")
    path = source_path(entry)
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise ValueError("Grandits checkpoint checksum mismatch")
    repo = ROOT / "external/grandits_emulator"
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from cardiomyocyte_emulator.emulator import APEmulator

    # Upstream checkpoint contains a Pandas Index and requires pickle loading.
    # Only this fixed, SHA-verified local checkpoint is ever deserialized.
    state = torch.load(path, map_location="cpu", weights_only=False)
    names = [str(name) for name in state.pop("max_conds_names")]
    ranges = tuple(np.asarray(arr, dtype=float) for arr in state.pop("max_conds_ranges"))
    emulator = APEmulator(device="cpu")
    emulator.load_state_dict(state)
    emulator.max_conds_names = names
    emulator.max_conds_ranges = ranges
    emulator.max_conds_ranges_t = tuple(torch.from_numpy(arr.astype(np.float32))[None] for arr in ranges)
    emulator.max_conds_extent = ranges[1] - ranges[0]
    emulator.max_conds_extent_t = emulator.max_conds_ranges_t[1] - emulator.max_conds_ranges_t[0]
    emulator.eval()
    return emulator


class GranditsBackend(SimulationBackend):
    def simulate(self, entry: dict, request: SimulationRequest) -> dict:
        if request.model_options:
            raise ValueError("The Grandits surrogate does not expose model-specific options")
        if request.duration_ms > 500:
            raise ValueError("Grandits time output is limited to 500 ms, matching the documented example range")
        if request.include_currents:
            raise ValueError("The Grandits surrogate does not produce mechanistic ionic currents")
        if request.auto_rescue:
            raise ValueError("Auto rescue does not apply to the Grandits surrogate")
        if request.prepace_beats:
            raise ValueError("Grandits is a single-beat surrogate and does not support prepacing")
        emulator = load_emulator()
        names = list(emulator.max_conds_names)
        lower, upper = emulator.max_conds_ranges
        values = np.asarray(emulator.max_conds_center, dtype=float).copy()
        unsupported = set(request.parameters) - set(entry["parameters"])
        if unsupported:
            raise ValueError(f"Unsupported Grandits parameters: {', '.join(sorted(unsupported))}")
        applied = {}
        for canonical, change in request.parameters.items():
            native = entry["parameters"][canonical]
            index = names.index(native)
            baseline = float(values[index])
            value = baseline * change.scale if change.scale is not None else float(change.native_value)
            if not np.isfinite(value) or value < lower[index] or value > upper[index]:
                raise ValueError(f"{canonical} is outside the emulator training range")
            values[index] = value
            applied[canonical] = {"native_name": native, "baseline": baseline, "value": value, "scale": value / baseline}
        t = np.linspace(-10, request.duration_ms, int((request.duration_ms + 10) / 0.5) + 1)
        v = emulator.forward_latent_np(t.astype(np.float32), values.astype(np.float32))[0].astype(float)
        metrics = paced_metrics(t, v, 0, 1000)
        return {
            "model_id": entry["id"], "model_version": entry["source_revision"], "backend": "grandits",
            "settings_requested": request.model_dump(),
            "settings_actual": {"pacing": {"mode": "single_beat", "stimulus_strength_nA": None}, "prepace_beats": 0, "rescued": False, "parameter_values": applied},
            "time_ms": t.tolist(), "voltage_mv": v.tolist(), "calcium": {}, "currents": {},
            "metrics": metrics,
            "warnings": ["Neural surrogate: ionic currents and mechanistic pacing are not represented."],
            "provenance": {key: entry.get(key) for key in ("source_url", "source_revision", "sha256", "publication", "license", "default_cell_type")},
        }
