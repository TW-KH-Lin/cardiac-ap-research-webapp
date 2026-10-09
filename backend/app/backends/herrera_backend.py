"""Constrained Octave adapter for the pinned Herrera et al. 2025 model."""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from app.backends.base import SimulationBackend
from app.core.metrics import paced_metrics
from app.core.registry import ROOT
from app.core.schemas import PacingSettings, SimulationRequest

SCALE_NAMES = (
    "INa_Scale", "INaL_Scale", "INab_Scale", "INaK_Scale", "Itof_Scale",
    "IKur_Scale", "IK2p_Scale", "IKr_Scale", "IKs_Scale", "IK1_Scale",
    "IKp_Scale", "IKach_Scale", "ISK_Scale", "ICaL_Scale", "ICab_Scale",
    "ICap_Scale", "INCX_Scale", "IClCa_Scale", "IClb_Scale", "Jrel_Scale",
    "Jserca_Scale", "Cleft_Buffer_Scale", "Cytosol_Buffer_Scale",
    "L_type_k1o_Scale", "L_type_Scale_camkii", "PLB_kmf_Scale",
    "RyR_EC50_Scale", "Ca_SR_leak_Scale", "CSQ_B_max_Scale", "KiCa_Scale",
    "KoCa_Scale", "Kim_Scale", "Kom_Scale",
)


def parameter_metadata(entry: dict) -> dict[str, dict]:
    return {
        canonical: {"native_name": native, "native_unit": "relative scale", "native_baseline": 1.0}
        for canonical, native in entry["parameters"].items()
    }


class HerreraBackend(SimulationBackend):
    def simulate(self, entry: dict, request: SimulationRequest) -> dict:
        pacing = request.pacing or PacingSettings(**entry["default_pacing"])
        if (pacing.mode or "external") != "external" or pacing.frequency_hz <= 0:
            raise ValueError("Herrera 2025 supports external periodic pacing only")
        fixed = entry["default_pacing"]
        for key in ("stimulus_duration_ms", "stimulus_strength_nA", "offset_ms", "cm_pf"):
            if not math.isclose(float(getattr(pacing, key)), float(fixed[key]), rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError(f"Herrera 2025 uses a fixed model-native {key} of {fixed[key]}")
        if request.auto_rescue:
            raise ValueError("Auto rescue is unavailable for the Herrera source backend")
        if request.include_currents:
            raise ValueError("Herrera ionic-current export is not enabled in the source-faithful adapter")
        unsupported = set(request.parameters) - set(entry["parameters"])
        if unsupported:
            raise ValueError(f"Unsupported Herrera parameters: {', '.join(sorted(unsupported))}")
        unsupported_options = set(request.model_options) - set(entry["model_options"])
        if unsupported_options:
            raise ValueError(f"Unsupported Herrera options: {', '.join(sorted(unsupported_options))}")

        options = {**entry["default_options"], **request.model_options}
        iso_nm = float(options["iso_nm"])
        if not 0 <= iso_nm <= 1000:
            raise ValueError("iso_nm must be in the range 0–1000 nM")
        bcl_ms = 1000.0 / pacing.frequency_hz
        total_ms = request.prepace_beats * bcl_ms + request.duration_ms
        if total_ms > 5000:
            raise ValueError("Herrera source simulations are limited to 5 seconds including prepacing")

        scales = {name: 1.0 for name in SCALE_NAMES}
        applied = {}
        for canonical, change in request.parameters.items():
            value = float(change.native_value if change.native_value is not None else change.scale)
            if not math.isfinite(value) or not 0 <= value <= 4:
                raise ValueError(f"{canonical} scale must be between 0 and 4")
            native = entry["parameters"][canonical]
            scales[native] = value
            applied[canonical] = {
                "native_name": native, "native_unit": "relative scale", "baseline": 1.0,
                "value": value, "scale": value,
            }

        micromamba = ROOT / ".runtime/bin/micromamba"
        octave_root = ROOT / ".runtime/mamba"
        runner = ROOT / "backend/native/herrera_2025/run_herrera.m"
        source_dir = ROOT / "external/herrera_2025_atrial/Single Cell"
        initial = (ROOT / entry["initial_conditions_file"]).resolve()
        if not all(path.is_file() for path in (runner, initial)):
            raise ValueError("The pinned Herrera source runtime is incomplete")

        with tempfile.NamedTemporaryFile(prefix="herrera-", suffix=".csv", delete=False) as handle:
            output_path = Path(handle.name)
        octave_executable = os.environ.get("OCTAVE_EXECUTABLE") or shutil.which("octave-cli") or shutil.which("octave")
        octave_args = ["octave-cli", "--quiet"]
        if micromamba.is_file() and (octave_root / "envs/octave").is_dir():
            command = [str(micromamba), "run", "-r", str(octave_root), "-n", "octave", *octave_args]
        elif octave_executable:
            command = [octave_executable, "--quiet"]
        else:
            raise ValueError("GNU Octave 10.3 is required for Herrera simulations")
        command.extend([
            str(runner), str(source_dir), str(initial), f"{total_ms:.12g}", f"{pacing.frequency_hz:.12g}",
            str(int(entry["af_state"])), str(int(entry["female"])), f"{iso_nm / 1000.0:.12g}", str(output_path),
            *(f"{scales[name]:.12g}" for name in SCALE_NAMES),
        ])
        environment = os.environ.copy()
        environment["XDG_CACHE_HOME"] = str(ROOT / ".runtime/cache")
        try:
            completed = subprocess.run(
                command, cwd=ROOT, env=environment, check=True, capture_output=True, text=True,
                timeout=min(330.0, 30.0 + total_ms * 0.08),
            )
            data = np.loadtxt(output_path, delimiter=",")
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Herrera source simulation exceeded its server timeout") from exc
        except (subprocess.CalledProcessError, OSError, ValueError) as exc:
            message = getattr(exc, "stderr", "") or str(exc)
            raise ValueError(f"Herrera source simulation failed: {message[-500:]}") from exc
        finally:
            output_path.unlink(missing_ok=True)

        if data.ndim != 2 or data.shape[1] != 3 or data.shape[0] < 3 or not np.all(np.isfinite(data)):
            raise ValueError("Herrera source simulation returned an invalid trace")
        keep = data[:, 0] >= request.prepace_beats * bcl_ms - 1e-9
        t = data[keep, 0] - request.prepace_beats * bcl_ms
        v = data[keep, 1]
        cai = data[keep, 2]
        if t[0] >= 0:
            t = np.insert(t, 0, -0.1)
            v = np.insert(v, 0, v[0])
            cai = np.insert(cai, 0, cai[0])
        metrics = paced_metrics(t, v, 0.0, bcl_ms)
        warnings = [
            "The upstream repository has no explicit license; reuse and redistribution require review.",
            "This adapter executes the pinned original MATLAB equations under Octave.",
            "Ionic-current export is not yet exposed for this source-faithful adapter.",
        ]
        return {
            "model_id": entry["id"], "model_version": entry["source_revision"], "backend": "herrera_octave",
            "settings_requested": request.model_dump(),
            "settings_actual": {
                "pacing": pacing.model_dump(), "prepace_beats": request.prepace_beats,
                "model_options": options, "af_state": entry["af_state"], "female": entry["female"],
                "rescued": False, "parameter_values": applied,
            },
            "time_ms": t.tolist(), "voltage_mv": v.tolist(),
            "calcium": {"values": cai.tolist(), "native_name": "Cai", "unit": "mM"},
            "currents": {}, "metrics": metrics, "warnings": warnings,
            "provenance": {key: entry.get(key) for key in ("source_url", "source_revision", "sha256", "publication", "license", "default_cell_type")},
        }
