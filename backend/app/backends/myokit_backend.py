"""Pinned CellML/MMT adapter; no UI or dynamic user code execution."""
from __future__ import annotations

import math
import os
from functools import lru_cache

import myokit
import numpy as np
from myokit.formats import cellml

from app.backends.base import SimulationBackend
from app.core.metrics import paced_metrics, pacemaker_metrics
from app.core.registry import ROOT, source_path
from app.core.schemas import PacingSettings, SimulationRequest
from app.core.units import current_for_display, stimulus_na_to_af, time_to_ms_factor


def _configure_sundials() -> None:
    prefix = os.environ.get("SUNDIALS_PREFIX")
    if prefix is None and (ROOT / ".local/sundials/include/sundials/sundials_config.h").is_file():
        prefix = str(ROOT / ".local/sundials")
    if prefix:
        for target, suffix in ((myokit.SUNDIALS_INC, "include"), (myokit.SUNDIALS_LIB, "lib")):
            path = os.path.join(prefix, suffix)
            if path not in target:
                target.insert(0, path)


@lru_cache(maxsize=8)
def _load_model(path: str) -> myokit.Model:
    model = cellml.CellMLImporter().model(path) if path.endswith(".cellml") else myokit.load_model(path)
    model.validate()
    return model


def _native_baseline(var: myokit.Variable) -> float:
    try:
        value = float(var.rhs().eval())
    except Exception as exc:
        raise ValueError(f"{var.qname()} is not a constant native parameter") from exc
    if not math.isfinite(value):
        raise ValueError(f"Non-finite native parameter {var.qname()}")
    return value


def parameter_metadata(entry: dict) -> dict[str, dict]:
    if entry["backend"] != "myokit" or not entry.get("sha256"):
        return {}
    model = _load_model(str(source_path(entry)))
    return {
        name: {"native_name": qname, "native_unit": str(model.get(qname).unit() or "unknown"), "native_baseline": _native_baseline(model.get(qname))}
        for name, qname in entry["parameters"].items()
    }


class MyokitBackend(SimulationBackend):
    def simulate(self, entry: dict, request: SimulationRequest) -> dict:
        _configure_sundials()
        model = _load_model(str(source_path(entry))).clone()
        factor = time_to_ms_factor(str(model.time().unit()))
        pacing = request.pacing or PacingSettings(**entry["default_pacing"])
        expected_mode = entry["default_pacing"]["mode"]
        mode = pacing.mode or expected_mode
        if mode != expected_mode:
            raise ValueError(f"{entry['id']} supports {expected_mode} pacing only")
        if mode == "external" and pacing.frequency_hz <= 0:
            raise ValueError("Externally paced models require frequency_hz > 0")
        option_metadata = entry.get("model_options", {})
        unsupported_options = set(request.model_options) - set(option_metadata)
        if unsupported_options:
            raise ValueError(f"Unsupported model options for {entry['id']}: {', '.join(sorted(unsupported_options))}")
        selected_options = {**entry.get("default_options", {}), **request.model_options}
        option_variables = entry.get("model_option_variables", {})
        applied_options = {}
        for name, value in selected_options.items():
            if name not in option_variables:
                raise ValueError(f"No native variable mapping for model option {name}")
            metadata = option_metadata.get(name, {})
            numeric = float(value)
            if not math.isfinite(numeric) or numeric < metadata.get("min", numeric) or numeric > metadata.get("max", numeric):
                raise ValueError(f"Invalid value for model option {name}")
            var = model.get(option_variables[name])
            var.set_rhs(myokit.Number(numeric, var.unit()))
            applied_options[name] = {"native_name": var.qname(), "native_unit": str(var.unit() or "unknown"), "value": numeric}
            activation_variable = entry.get("model_option_activation_variables", {}).get(name)
            if activation_variable:
                activation = model.get(activation_variable)
                activation_value = 1.0 if numeric > 0 else 0.0
                activation.set_rhs(myokit.Number(activation_value, activation.unit()))
                applied_options[name]["activation_native_name"] = activation.qname()
                applied_options[name]["activation_value"] = activation_value
        unsupported = set(request.parameters) - set(entry["parameters"])
        if unsupported:
            raise ValueError(f"Unsupported parameters for {entry['id']}: {', '.join(sorted(unsupported))}")
        unsupported_currents = set(request.include_currents) - set(entry["currents"])
        if unsupported_currents:
            raise ValueError(f"Unsupported currents for {entry['id']}: {', '.join(sorted(unsupported_currents))}")

        applied = {}
        for name, change in request.parameters.items():
            var = model.get(entry["parameters"][name])
            baseline = _native_baseline(var)
            value = baseline * change.scale if change.scale is not None else float(change.native_value)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"Invalid native parameter value for {name}")
            var.set_rhs(myokit.Number(value, var.unit()))
            applied[name] = {"native_name": var.qname(), "native_unit": str(var.unit() or "unknown"), "baseline": baseline, "value": value, "scale": value / baseline if baseline else None}

        native_level = None
        protocol = None
        if mode == "external":
            native_level = stimulus_na_to_af(pacing.stimulus_strength_nA, pacing.cm_pf)
            stimulus_variable = entry.get("stimulus_variable")
            if entry["id"] == "torord_dyncl_endo" or stimulus_variable:
                # CellML's internal time predicate has a discontinuity that CVODES
                # can step over. Bind the physical stimulus current to Myokit's
                # event-aware pacing engine, as the legacy viewer intended.
                model.get(stimulus_variable or "membrane.Istim").set_binding("pace")
                protocol = myokit.pacing.blocktrain(
                    period=1000 / pacing.frequency_hz / factor,
                    duration=pacing.stimulus_duration_ms / factor,
                    level=native_level,
                    offset=pacing.offset_ms / factor,
                )
            else:
                var = model.get("stimulus.amplitude")
                var.set_rhs(myokit.Number(native_level, var.unit()))
                protocol = myokit.pacing.blocktrain(
                    period=1000 / pacing.frequency_hz / factor,
                    duration=pacing.stimulus_duration_ms / factor,
                    level=1,
                    offset=pacing.offset_ms / factor,
                )

        sim = myokit.Simulation(model, protocol)
        bcl_ms = 1000 / pacing.frequency_hz if mode == "external" else None
        pre_ms = request.prepace_beats * bcl_ms if bcl_ms is not None else max(request.prepace_beats, 0) * 1000
        if pre_ms:
            sim.pre(pre_ms / factor)
        names = [model.time().qname(), entry["voltage"]]
        if entry.get("calcium") and model.has_variable(entry["calcium"]):
            names.append(entry["calcium"])
        requested_currents = request.include_currents or list(entry["currents"])[:3]
        names.extend(entry["currents"][key] for key in requested_currents)
        names = list(dict.fromkeys(names))
        interval_ms = 0.2 if mode == "external" else 0.5
        log = sim.run(request.duration_ms / factor, log=names, log_interval=interval_ms / factor)
        t = np.asarray(log[model.time().qname()], dtype=float) * factor
        v = np.asarray(log[entry["voltage"]], dtype=float)
        if not np.all(np.isfinite(v)):
            raise ValueError("Simulation returned non-finite voltage")
        warnings = []
        if mode == "external" and float(np.ptp(v)) < 30:
            warnings.append("No full action potential was detected at the requested stimulus; protocol was not changed.")
        if request.auto_rescue:
            warnings.append("Auto rescue was requested but is not implemented for this backend; protocol was not changed.")
        calcium = {}
        if entry.get("calcium") and entry["calcium"] in log:
            var = model.get(entry["calcium"])
            calcium = {"values": np.asarray(log[entry["calcium"]], dtype=float).tolist(), "native_name": var.qname(), "unit": str(var.unit() or "unknown")}
        currents = {}
        for name in requested_currents:
            qname = entry["currents"][name]
            var = model.get(qname)
            native_unit = str(var.unit() or "unknown")
            values, unit, method = current_for_display(np.asarray(log[qname], dtype=float), native_unit, pacing.cm_pf)
            currents[name] = {"values": values.tolist(), "unit": unit, "native_name": qname, "native_unit": native_unit, "conversion": method}
        metrics = paced_metrics(t, v, pacing.offset_ms, bcl_ms) if mode == "external" else pacemaker_metrics(t, v)
        actual = {"pacing": pacing.model_dump(), "prepace_beats": request.prepace_beats, "native_stimulus_level": native_level, "native_stimulus_unit": "A/F" if native_level is not None else None, "rescued": False, "parameter_values": applied, "model_options": applied_options}
        return {
            "model_id": entry["id"], "model_version": entry["source_revision"], "backend": "myokit",
            "settings_requested": request.model_dump(), "settings_actual": actual,
            "time_ms": t.tolist(), "voltage_mv": v.tolist(), "calcium": calcium,
            "currents": currents, "metrics": metrics, "warnings": warnings,
            "provenance": {key: entry.get(key) for key in ("source_url", "source_revision", "sha256", "publication", "license", "default_cell_type")},
        }
