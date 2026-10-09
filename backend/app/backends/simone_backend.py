"""Production adapter for the statically generated Simone–Trancuccio model."""
from __future__ import annotations

import math

import numpy as np
from scipy.integrate import solve_ivp

from app.backends.base import SimulationBackend
from app.backends.simone_static_rhs import INITIAL_STATE, SOURCE_SHA256, simone_rhs
from app.core.metrics import pacemaker_metrics
from app.core.schemas import PacingSettings, SimulationRequest
from app.core.units import current_for_display

OUTPUT_NAMES = (
    "INa", "If", "ICaL", "Ito", "IKs", "IKr", "IK1", "INaCa", "INaK",
    "IpCa", "IbNa", "IbCa", "Irel", "Istim", "E_K", "E_Na", "INaL", "Iup",
)


def parameter_metadata(entry: dict) -> dict[str, dict]:
    return {
        canonical: {
            "native_name": native,
            "native_unit": "model native conductance/permeability",
            "native_baseline": float(entry["parameter_baselines"][canonical]),
        }
        for canonical, native in entry["parameters"].items()
    }


class SimoneBackend(SimulationBackend):
    def simulate(self, entry: dict, request: SimulationRequest) -> dict:
        if entry.get("sha256") != SOURCE_SHA256:
            raise ValueError("Static Simone solver does not match the pinned source checksum")
        pacing = request.pacing or PacingSettings(**entry["default_pacing"])
        if (pacing.mode or "spontaneous") != "spontaneous" or pacing.frequency_hz != 0:
            raise ValueError("Simone WT and TS22 use spontaneous pacing only")
        if request.auto_rescue:
            raise ValueError("Auto rescue is unavailable for the Simone static backend")
        unsupported = set(request.parameters) - set(entry["parameters"])
        if unsupported:
            raise ValueError(f"Unsupported Simone parameters: {', '.join(sorted(unsupported))}")
        if request.model_options:
            raise ValueError("Simone variants expose no additional model options")
        requested_currents = request.include_currents or list(entry["currents"])[:3]
        unsupported_currents = set(requested_currents) - set(entry["currents"])
        if unsupported_currents:
            raise ValueError(f"Unsupported Simone currents: {', '.join(sorted(unsupported_currents))}")

        params: dict[str, float] = {}
        applied: dict[str, dict] = {}
        for canonical, change in request.parameters.items():
            baseline = float(entry["parameter_baselines"][canonical])
            value = float(change.native_value if change.native_value is not None else baseline * change.scale)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{canonical} must be finite and nonnegative")
            native = entry["parameters"][canonical]
            params[native] = value
            applied[canonical] = {
                "native_name": native, "native_unit": "model native", "baseline": baseline,
                "value": value, "scale": value / baseline,
            }

        fractional_ts = float(entry["fractional_ts"])
        y0 = INITIAL_STATE.copy()
        warmup_s = float(request.prepace_beats)
        if warmup_s:
            warmup = self._solve(y0, warmup_s, None, fractional_ts, params)
            if not warmup.success:
                raise ValueError(f"Simone warm-up failed: {warmup.message}")
            y0 = warmup.y[:, -1]

        duration_s = request.duration_ms / 1000.0
        points = int(min(20_001, max(400, round(request.duration_ms / 0.2) + 1)))
        times = np.linspace(0.0, duration_s, points)
        solution = self._solve(y0, duration_s, times, fractional_ts, params)
        if not solution.success:
            raise ValueError(f"Simone simulation failed: {solution.message}")
        voltage_mv = solution.y[0] * 1000.0
        if not np.all(np.isfinite(voltage_mv)):
            raise ValueError("Simone simulation returned non-finite voltage")

        output = np.asarray([
            simone_rhs(float(t), solution.y[:, index], 0, 0, 1.0, fractional_ts, params=params)
            for index, t in enumerate(solution.t)
        ])
        currents = {}
        for name in requested_currents:
            values, unit, conversion = current_for_display(output[:, OUTPUT_NAMES.index(name)], "A/F", pacing.cm_pf)
            currents[name] = {
                "values": values.tolist(), "unit": unit, "native_name": entry["currents"][name],
                "native_unit": "A/F", "conversion": conversion,
            }

        metrics = pacemaker_metrics(solution.t * 1000.0, voltage_mv)
        warnings = [
            "Source terms permit noncommercial use only.",
            "This static port is for research exploration and is not a clinical model.",
        ]
        if float(np.ptp(voltage_mv)) < 30:
            warnings.append("No full spontaneous action potential was detected in the requested window.")
        return {
            "model_id": entry["id"], "model_version": entry["source_revision"], "backend": "simone_static",
            "settings_requested": request.model_dump(),
            "settings_actual": {
                "pacing": pacing.model_dump(), "prepace_beats": request.prepace_beats,
                "warmup_seconds": warmup_s, "fractional_ts": fractional_ts,
                "model_options": {}, "rescued": False, "parameter_values": applied,
            },
            "time_ms": (solution.t * 1000.0).tolist(), "voltage_mv": voltage_mv.tolist(),
            "calcium": {"values": solution.y[2].tolist(), "native_name": "Cai", "unit": "mM"},
            "currents": currents, "metrics": metrics, "warnings": warnings,
            "provenance": {key: entry.get(key) for key in ("source_url", "source_revision", "sha256", "publication", "license", "default_cell_type")},
        }

    @staticmethod
    def _solve(y0: np.ndarray, duration_s: float, t_eval: np.ndarray | None, fractional_ts: float, params: dict[str, float]):
        return solve_ivp(
            lambda t, y: simone_rhs(t, y, 0, 1, 1.0, fractional_ts, params=params),
            (0.0, duration_s), y0, method="BDF", t_eval=t_eval,
            rtol=1e-8, atol=1e-10, max_step=0.005,
        )
