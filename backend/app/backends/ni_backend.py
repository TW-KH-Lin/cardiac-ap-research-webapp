"""Strict subprocess adapter for the pinned Ni 2023 single-cell C++ model."""
from __future__ import annotations

import io
import math
import subprocess

import numpy as np

from app.backends.base import SimulationBackend
from app.core.metrics import paced_metrics
from app.core.registry import ROOT, source_path
from app.core.schemas import PacingSettings, SimulationRequest
from app.core.units import current_for_display


SCALE_ORDER = (
    "g_Na", "g_NaL", "g_to", "g_Kur", "g_K2P", "g_Kr",
    "g_Ks", "g_K1", "g_SK", "g_CaL", "g_NaK", "g_NaCa",
)


def parameter_metadata(entry: dict) -> dict[str, dict]:
    return {
        name: {"native_name": native, "native_unit": "relative scale", "native_baseline": 1.0}
        for name, native in entry["parameters"].items()
    }


class NiBackend(SimulationBackend):
    def simulate(self, entry: dict, request: SimulationRequest) -> dict:
        pacing = request.pacing or PacingSettings(**entry["default_pacing"])
        if (pacing.mode or "external") != "external" or pacing.frequency_hz <= 0:
            raise ValueError("Ni 2023 supports external periodic pacing only")
        fixed = entry["default_pacing"]
        for key in ("stimulus_duration_ms", "stimulus_strength_nA", "offset_ms", "cm_pf"):
            if not math.isclose(float(getattr(pacing, key)), float(fixed[key]), rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError(f"Ni 2023 uses a fixed model-native {key} of {fixed[key]}")
        if request.auto_rescue:
            raise ValueError("Auto rescue is unavailable for the Ni 2023 native backend")

        unsupported = set(request.parameters) - set(entry["parameters"])
        if unsupported:
            raise ValueError(f"Unsupported Ni 2023 parameters: {', '.join(sorted(unsupported))}")
        unsupported_options = set(request.model_options) - set(entry["model_options"])
        if unsupported_options:
            raise ValueError(f"Unsupported Ni 2023 options: {', '.join(sorted(unsupported_options))}")
        requested_currents = request.include_currents or list(entry["currents"])[:3]
        unsupported_currents = set(requested_currents) - set(entry["currents"])
        if unsupported_currents:
            raise ValueError(f"Unsupported Ni 2023 currents: {', '.join(sorted(unsupported_currents))}")

        options = dict(entry["default_options"])
        options.update({name: float(value) for name, value in request.model_options.items()})
        if options["af_state"] not in (0, 1):
            raise ValueError("af_state must be 0 (nSR) or 1 (AF)")
        if not 0 <= options["iso_nm"] <= 1000:
            raise ValueError("iso_nm must be in the range 0–1000 nM")
        for name in ("camkii_inhibition", "camkii_double"):
            if options[name] not in (0, 1):
                raise ValueError(f"{name} must be 0 or 1")

        scales = {name: 1.0 for name in SCALE_ORDER}
        applied = {}
        for name, change in request.parameters.items():
            value = float(change.scale if change.scale is not None else change.native_value)
            if not math.isfinite(value) or not 0 <= value <= 4:
                raise ValueError(f"{name} scale must be between 0 and 4")
            scales[name] = value
            applied[name] = {
                "native_name": entry["parameters"][name], "native_unit": "relative scale",
                "baseline": 1.0, "value": value, "scale": value,
            }

        bcl_ms = 1000.0 / pacing.frequency_hz
        simulated_ms = request.prepace_beats * bcl_ms + request.duration_ms
        if simulated_ms > 120_000:
            raise ValueError("Ni 2023 native simulation is limited to 120 seconds including prepacing")
        binary = (ROOT / entry["runtime_file"]).resolve()
        if not binary.is_file() or not binary.is_relative_to(ROOT):
            raise ValueError("Ni 2023 native executable is missing; run scripts/build_ni_2023.sh")
        initial_conditions = (ROOT / entry["initial_conditions_file"]).resolve()
        if not initial_conditions.is_file() or not initial_conditions.is_relative_to(ROOT):
            raise ValueError("Ni 2023 pinned initial conditions are missing")

        command = [
            str(binary), f"{bcl_ms:.12g}", str(request.prepace_beats),
            f"{request.duration_ms:.12g}", str(int(options["af_state"])),
            f"{options['iso_nm'] / 1000.0:.12g}", str(int(options["camkii_inhibition"])),
            str(int(options["camkii_double"])), str(initial_conditions),
            *(f"{scales[name]:.12g}" for name in SCALE_ORDER),
        ]
        try:
            completed = subprocess.run(
                command, cwd=binary.parent, check=True, capture_output=True, text=True,
                timeout=min(120.0, 15.0 + simulated_ms / 500.0),
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Ni 2023 native simulation exceeded its server timeout") from exc
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() or "native process failed"
            raise ValueError(f"Ni 2023 simulation failed: {message[:500]}") from exc

        data = np.genfromtxt(io.StringIO(completed.stdout), delimiter=",", names=True)
        if data.size < 3:
            raise ValueError("Ni 2023 returned an incomplete trace")
        t = np.atleast_1d(data["time_ms"]).astype(float)
        v = np.atleast_1d(data["voltage_mv"]).astype(float)
        cai = np.atleast_1d(data["calcium_mm"]).astype(float)
        if not (np.all(np.isfinite(t)) and np.all(np.isfinite(v)) and np.all(np.isfinite(cai))):
            raise ValueError("Ni 2023 returned non-finite output")

        currents = {}
        for name in requested_currents:
            column = entry["currents"][name]
            values, unit, method = current_for_display(np.atleast_1d(data[column]).astype(float), "A/F", pacing.cm_pf)
            currents[name] = {
                "values": values.tolist(), "unit": unit, "native_name": column,
                "native_unit": "uA/uF (numerically A/F)", "conversion": method,
            }
        metrics = paced_metrics(t, v, 0.0, bcl_ms)
        warnings = [
            "The upstream repository has no explicit LICENSE file; redistribution requires review.",
            "The model-native stimulus is fixed at 12.5 uA/uF for 5 ms.",
        ]
        if float(np.ptp(v)) < 30:
            warnings.append("No full action potential was detected; the pacing protocol was not changed.")
        return {
            "model_id": entry["id"], "model_version": entry["source_revision"], "backend": "external_compiled",
            "settings_requested": request.model_dump(),
            "settings_actual": {
                "pacing": pacing.model_dump(), "prepace_beats": request.prepace_beats,
                "native_stimulus_level": 12.5, "native_stimulus_unit": "uA/uF",
                "model_options": options, "rescued": False, "parameter_values": applied,
            },
            "time_ms": t.tolist(), "voltage_mv": v.tolist(),
            "calcium": {"values": cai.tolist(), "native_name": "Cai", "unit": "mM"},
            "currents": currents, "metrics": metrics, "warnings": warnings,
            "provenance": {key: entry.get(key) for key in ("source_url", "source_revision", "sha256", "publication", "license", "default_cell_type")},
        }
