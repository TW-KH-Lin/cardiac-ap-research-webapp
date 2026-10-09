#!/usr/bin/env python3
"""Desktop PyQtGraph viewer for comparing two cardiac AP models."""

from __future__ import annotations

import os
import re
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import myokit
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets


# Keep Myokit temp output away from transient macOS temp-dir churn.
PERSIST_TMP = Path("/tmp") / "myokit_qt_tmp"
PERSIST_TMP.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(PERSIST_TMP)
os.environ["TMPDIR"] = str(PERSIST_TMP)
os.environ["TEMP"] = str(PERSIST_TMP)
os.environ["TMP"] = str(PERSIST_TMP)
if hasattr(myokit, "set_temp_dir"):
    myokit.set_temp_dir(str(PERSIST_TMP))
myokit.DEBUG = True

HERE = Path(__file__).resolve().parent
SEARCH_ROOTS = [HERE, Path("/Users/kh_lin/PycharmProjects/Analysis"), Path.cwd(), Path.home()]

MODEL_A_LABEL = "ToRORd_dynCl_endo"
MODEL_B_LABEL = "BPS2020"
MODEL_A_PATH = HERE / "ToRORd_dynCl_endo.cellml"
MODEL_B_PATH = HERE / "BPS2020.cellml"

DEFAULT_PACING = {"bcl": 1000.0, "duration": 1.0, "level": 1.1, "offset": 200.0}
DEFAULT_PARAMS = {
    "g_Na": 75.0,
    "g_CaL": 0.0001,
    "g_Kr": 0.046,
    "g_Ks": 0.0034,
    "g_to": 0.02,
    "g_NaL": 0.0075,
    "g_K1": 0.1908,
}
DEFAULT_PRESET_NAME = "Custom"
DEFAULT_SIM_LENGTH_MS = 1000.0
DEFAULT_PREPACE_BEATS = 50
DEFAULT_CM_PF = 50.0
STIM_POLARITY = -1

OVERRIDE_STIM = {"A": "membrane.I_stim", "B": "stimulus.i_stim"}
OVERRIDE_KNOBS = {"A": {}, "B": {}}
OVERRIDE_CURRENTS = {"A": {}, "B": {}}

CUR_PATTERNS: Dict[str, List[re.Pattern[str]]] = {
    "INa": [re.compile(r"(?:^|[._])i[_]?na(?:$|[._])", re.I), re.compile(r"(?:^|[._])ina(?:$|[._])", re.I)],
    "INaL": [re.compile(r"(?:^|[._])i[_]?nal(?:$|[._])", re.I), re.compile(r"(?:^|[._])inal(?:$|[._])", re.I)],
    "ICaL": [re.compile(r"(?:^|[._])i[_]?ca?l(?:$|[._])", re.I), re.compile(r"(?:^|[._])ical(?:$|[._])", re.I)],
    "Ito": [re.compile(r"(?:^|[._])i[_]?to(?:$|[._])", re.I), re.compile(r"(?:^|[._])ito(?:$|[._])", re.I)],
    "IKr": [re.compile(r"(?:^|[._])i[_]?kr(?:$|[._])", re.I), re.compile(r"(?:^|[._])ikr(?:$|[._])", re.I)],
    "IKs": [re.compile(r"(?:^|[._])i[_]?ks(?:$|[._])", re.I), re.compile(r"(?:^|[._])iks(?:$|[._])", re.I)],
    "IK1": [re.compile(r"(?:^|[._])i[_]?k1(?:$|[._])", re.I), re.compile(r"(?:^|[._])ik1(?:$|[._])", re.I)],
}

KNOB_PATTERNS: Dict[str, List[re.Pattern[str]]] = {
    "g_Na": [re.compile(r"(?:^|[._])g[_]?na(?:$|[._])", re.I), re.compile(r"(?:^|[._])gna(?:$|[._])", re.I)],
    "g_CaL": [
        re.compile(r"(?:^|[._])g[_]?ca?l(?:$|[._])", re.I),
        re.compile(r"(?:^|[._])p[_]?ca(?:$|[._])", re.I),
        re.compile(r"(?:^|[._])gca?l(?:$|[._])", re.I),
        re.compile(r"(?:^|[._])pc[aA](?:$|[._])", re.I),
    ],
    "g_Kr": [re.compile(r"(?:^|[._])g[_]?kr(?:$|[._])", re.I), re.compile(r"(?:^|[._])gkr(?:$|[._])", re.I)],
    "g_Ks": [re.compile(r"(?:^|[._])g[_]?ks(?:$|[._])", re.I), re.compile(r"(?:^|[._])gks(?:$|[._])", re.I)],
    "g_to": [re.compile(r"(?:^|[._])g[_]?to(?:$|[._])", re.I), re.compile(r"(?:^|[._])gto(?:$|[._])", re.I)],
    "g_NaL": [re.compile(r"(?:^|[._])g[_]?nal(?:$|[._])", re.I), re.compile(r"(?:^|[._])gnal(?:$|[._])", re.I)],
    "g_K1": [re.compile(r"(?:^|[._])g[_]?k1(?:$|[._])", re.I), re.compile(r"(?:^|[._])gk1(?:$|[._])", re.I)],
}

STIM_PATTERNS = [
    re.compile(r"(?:^|[._])i[_]?stim(?:$|[._])", re.I),
    re.compile(r"(?:^|[._])stimulus[._]i(?:$|[._])", re.I),
    re.compile(r"(?:^|[._])membrane[._]i[_]?stim(?:$|[._])", re.I),
]

CURRENT_ORDER = ["INa", "INaL", "ICaL", "Ito", "IKr", "IKs", "IK1"]
MODEL_KEYS = {"A": MODEL_A_LABEL, "B": MODEL_B_LABEL}
MODEL_COLORS = {"A": "#0072B2", "B": "#D55E00"}
PUBLISHED_PRESETS: Dict[str, Dict[str, float]] = {
    "Custom": dict(DEFAULT_PARAMS),
    "ORd 2011 ventricular": {
        "g_Na": 75.0,
        "g_CaL": 0.0001,
        "g_Kr": 0.046,
        "g_Ks": 0.0034,
        "g_to": 0.02,
        "g_NaL": 0.0075,
        "g_K1": 0.1908,
    },
    "ToR-ORd-dynCl ventricular": {
        "g_Na": 11.7802,
        "g_CaL": 8.3757e-05,
        "g_Kr": 0.0321,
        "g_Ks": 0.0011,
        "g_to": 0.16,
        "g_NaL": 0.0279,
        "g_K1": 0.6992,
    },
    "BPS2020 ventricular": {
        "g_Na": 75.0,
        "g_CaL": 9.0e-05,
        "g_Kr": 0.0552,
        "g_Ks": 0.0068,
        "g_to": 0.02,
        "g_NaL": 0.0210,
        "g_K1": 0.135468,
    },
}
PRESET_SOURCES = {
    "Custom": "Manual conductance set.",
    "ORd 2011 ventricular": "O'Hara, Virag, Varro, Rudy 2011 human ventricular model.",
    "ToR-ORd-dynCl ventricular": "Tomek, Bueno-Orovio, Rodriguez 2020 ToR-ORd-dynCl human ventricular model.",
    "BPS2020 ventricular": "Bartolucci, Passini, Hyttinen, Paci, Severi 2020 BPS2020 human ventricular model.",
}
ATRIAL_MODEL_REQUEST = (
    "Exact atrial or pacemaker support needs a real model file or supplementary "
    "equation tables. Mazhar 2024 is a full atrial electromechanics model, and "
    "Fabbri 2017 is the key human SAN pacemaker model."
)


@dataclass
class SimulationResult:
    label: str
    time_ms: np.ndarray
    voltage_mv: Optional[np.ndarray]
    currents_pa: Dict[str, Tuple[np.ndarray, str]]
    apd90_ms: Optional[float]
    current_map: Dict[str, str]
    knob_map: Dict[str, str]
    stim_info: str
    warning: Optional[str]


def _ensure_std_streams() -> None:
    if getattr(sys, "stdout", None) is None or getattr(sys.stdout, "closed", False):
        sys.stdout = sys.__stdout__
    if getattr(sys, "stderr", None) is None or getattr(sys.stderr, "closed", False):
        sys.stderr = sys.__stderr__


def find_file(path: Path, name_hint: str) -> Path:
    if path.is_file():
        return path
    for root in SEARCH_ROOTS:
        try:
            matches = list(Path(root).rglob(name_hint))
        except Exception:
            continue
        if matches:
            return matches[0]
    raise FileNotFoundError(f"Could not find {name_hint}")


def load_model_any(path: Path) -> myokit.Model:
    suffix = path.suffix.lower()
    if suffix in {".mmt", ".txt"}:
        return myokit.load_model(str(path))
    if suffix == ".cellml":
        importer = myokit.formats.cellml.CellMLImporter()
        return importer.model(str(path))
    raise ValueError(f"Unsupported model file: {path}")


def ensure_time_binding(model: myokit.Model) -> None:
    if model.time() is not None:
        return
    for name in ("engine.time", "environment.time", "membrane.time", "time.time", "time"):
        try:
            var = model.get(name)
        except KeyError:
            continue
        if isinstance(var, myokit.Variable):
            var.set_binding("time")
            var.set_unit("ms")
            return
    try:
        engine = model.get("engine")
    except KeyError:
        engine = model.add_component("engine")
    time_var = engine.add_variable("time")
    time_var.set_binding("time")
    time_var.set_unit("ms")


def unit_text(var: myokit.Variable) -> str:
    try:
        unit = var.unit()
        return str(unit) if unit is not None else "-"
    except Exception:
        return "-"


def unit_tag(var: myokit.Variable) -> str:
    text = unit_text(var)
    if "A/F" in text or "/F" in text:
        return "A/F"
    if "A" in text:
        return "A"
    return "?"


def autodetect_currents(model: myokit.Model, overrides: Optional[Dict[str, str]] = None) -> Dict[str, myokit.Variable]:
    found: Dict[str, myokit.Variable] = {}
    if overrides:
        for label, qname in overrides.items():
            try:
                obj = model.get(qname)
            except KeyError:
                continue
            if isinstance(obj, myokit.Variable):
                found[label] = obj
    variables = {var.qname(): var for var in model.variables()}
    for label, patterns in CUR_PATTERNS.items():
        if label in found:
            continue
        best: Optional[myokit.Variable] = None
        best_score = -1
        for qname, var in variables.items():
            score = 2 * sum(pattern.search(qname) is not None for pattern in patterns)
            text = unit_text(var)
            if "A/F" in text or "/F" in text or "A" in text:
                score += 1
            if score > best_score:
                best = var
                best_score = score
        if best is not None and best_score > 0:
            found[label] = best
    return found


def autodetect_knobs(model: myokit.Model, overrides: Optional[Dict[str, str]] = None) -> Dict[str, myokit.Variable]:
    found: Dict[str, myokit.Variable] = {}
    if overrides:
        for label, qname in overrides.items():
            try:
                obj = model.get(qname)
            except KeyError:
                continue
            if isinstance(obj, myokit.Variable):
                found[label] = obj
    variables = list(model.variables())
    for label, patterns in KNOB_PATTERNS.items():
        if label in found:
            continue
        best: Optional[myokit.Variable] = None
        best_score = -1
        for var in variables:
            score = 2 * sum(pattern.search(var.qname()) is not None for pattern in patterns)
            try:
                if var.is_literal():
                    score += 2
            except Exception:
                pass
            if score > best_score:
                best = var
                best_score = score
        if best is not None and best_score > 0:
            found[label] = best
    return found


def choose_stim_var(model: myokit.Model, override_name: Optional[str]) -> Tuple[Optional[myokit.Variable], str]:
    if override_name:
        try:
            stim_var = model.get(override_name)
        except KeyError:
            stim_var = None
        if isinstance(stim_var, myokit.Variable):
            if stim_var.binding() != "pace":
                stim_var.set_binding("pace")
            return stim_var, unit_tag(stim_var)
    for var in model.variables():
        try:
            if var.binding() == "pace":
                return var, unit_tag(var)
        except Exception:
            continue
    best: Optional[myokit.Variable] = None
    best_score = -1
    for var in model.variables():
        score = 2 * sum(pattern.search(var.qname()) is not None for pattern in STIM_PATTERNS)
        if score <= 0:
            continue
        tag = unit_tag(var)
        if tag == "A/F":
            score += 3
        elif tag == "A":
            score += 2
        if score > best_score:
            best = var
            best_score = score
    if best is not None:
        if best.binding() != "pace":
            best.set_binding("pace")
        return best, unit_tag(best)
    return None, "?"


def stim_level_nA_to_target(level_nA: float, target_unit: str, cm_pf: float, polarity: int = STIM_POLARITY) -> float:
    if target_unit == "A":
        value = float(level_nA) * 1e-9
    else:
        value = (float(level_nA) / float(cm_pf)) * 1e3
    return float(polarity) * abs(value)


def build_simulation(model: myokit.Model, protocol: myokit.Protocol) -> myokit.Simulation:
    last_error: Optional[Exception] = None
    for _ in range(3):
        try:
            _ensure_std_streams()
            return myokit.Simulation(model, protocol)
        except FileNotFoundError as exc:
            last_error = exc
            time.sleep(0.1)
    if last_error is not None:
        raise last_error
    raise RuntimeError("Failed to build Myokit simulation")


def find_voltage_var(model: myokit.Model) -> Optional[myokit.Variable]:
    for name in ("membrane.V", "cell.V", "voltage.V", "V", "membrane.v"):
        try:
            var = model.get(name)
        except KeyError:
            continue
        if isinstance(var, myokit.Variable):
            return var
    return None


def apd90_ms(time_ms: np.ndarray, voltage_mv: Optional[np.ndarray]) -> Optional[float]:
    if voltage_mv is None or time_ms.size < 3:
        return None
    v_min = float(np.min(voltage_mv))
    v_max = float(np.max(voltage_mv))
    threshold = v_min + 0.1 * (v_max - v_min)
    above = voltage_mv > threshold
    crossings = np.where(np.diff(above.astype(int)) != 0)[0]
    if crossings.size >= 2:
        return float(time_ms[crossings[1]] - time_ms[crossings[0]])
    return None


def clone_and_configure(
    base_model: myokit.Model,
    model_key: str,
    knob_values: Dict[str, float],
) -> Tuple[myokit.Model, Dict[str, myokit.Variable], Dict[str, myokit.Variable]]:
    model = base_model.clone()
    ensure_time_binding(model)
    current_vars = autodetect_currents(model, OVERRIDE_CURRENTS.get(model_key))
    knob_vars = autodetect_knobs(model, OVERRIDE_KNOBS.get(model_key))
    for name, value in knob_values.items():
        knob_var = knob_vars.get(name)
        if knob_var is None:
            continue
        try:
            knob_var.set_rhs(float(value))
        except Exception:
            pass
    return model, current_vars, knob_vars


def simulate_model(
    base_model: myokit.Model,
    model_key: str,
    label: str,
    knob_values: Dict[str, float],
    sim_length_ms: float,
    freq_hz: float,
    stim_duration_ms: float,
    stim_strength_nA: float,
    stim_offset_ms: float,
    cm_pf: float,
    prepace_beats: int,
) -> SimulationResult:
    model, current_vars, knob_vars = clone_and_configure(base_model, model_key, knob_values)
    freq = max(float(freq_hz), 1e-6)
    bcl = 1000.0 / freq
    stim_var, stim_unit = choose_stim_var(model, OVERRIDE_STIM.get(model_key))
    stim_level = stim_level_nA_to_target(stim_strength_nA, stim_unit, cm_pf, STIM_POLARITY)
    protocol = myokit.pacing.blocktrain(
        period=bcl,
        duration=float(stim_duration_ms),
        level=stim_level,
        offset=float(stim_offset_ms),
    )
    sim = build_simulation(model, protocol)
    sim.pre(float(prepace_beats) * bcl)

    to_log: List[myokit.Variable] = [model.time()]
    voltage_var = find_voltage_var(model)
    if voltage_var is not None:
        to_log.append(voltage_var)
    for var in current_vars.values():
        to_log.append(var)
    if stim_var is not None:
        to_log.append(stim_var)

    log = sim.run(float(sim_length_ms), log=to_log)
    time_ms = np.asarray(log.time(), dtype=float)
    voltage_mv = np.asarray(log[voltage_var], dtype=float) if voltage_var is not None else None
    warning: Optional[str] = None

    def is_flat(trace: Optional[np.ndarray]) -> bool:
        if trace is None or trace.size == 0:
            return True
        return float(np.max(trace) - np.min(trace)) < 30.0

    if is_flat(voltage_mv):
        rescue_note = "auto-rescue failed"
        for polarity in (STIM_POLARITY, -STIM_POLARITY):
            for amp_factor in (2.0, 4.0, 8.0):
                for duration_ms in (max(stim_duration_ms, 1.0), max(stim_duration_ms, 2.0)):
                    alt_protocol = myokit.pacing.blocktrain(
                        period=bcl,
                        duration=float(duration_ms),
                        level=stim_level_nA_to_target(stim_strength_nA * amp_factor, stim_unit, cm_pf, polarity),
                        offset=float(stim_offset_ms),
                    )
                    alt_sim = build_simulation(model, alt_protocol)
                    alt_sim.pre(float(prepace_beats) * bcl)
                    alt_log = alt_sim.run(float(sim_length_ms), log=to_log)
                    alt_voltage = np.asarray(alt_log[voltage_var], dtype=float) if voltage_var is not None else None
                    if not is_flat(alt_voltage):
                        log = alt_log
                        time_ms = np.asarray(log.time(), dtype=float)
                        voltage_mv = alt_voltage
                        rescue_note = f"auto-rescue amp x{amp_factor:g}, duration {duration_ms:g} ms, polarity {polarity:+d}"
                        break
                if rescue_note.startswith("auto-rescue amp"):
                    break
            if rescue_note.startswith("auto-rescue amp"):
                break
        warning = rescue_note

    currents_pa: Dict[str, Tuple[np.ndarray, str]] = {}
    for current_name, var in current_vars.items():
        values = np.asarray(log[var], dtype=float)
        tag = unit_tag(var)
        if tag == "A/F":
            values = values * float(cm_pf)
            note = "A/F -> pA"
        elif tag == "A":
            values = values * 1e12
            note = "A -> pA"
        else:
            note = "raw"
        currents_pa[current_name] = (values, note)

    current_map = {name: f"{var.qname()} [{unit_text(var)}]" for name, var in current_vars.items()}
    knob_map = {name: var.qname() for name, var in knob_vars.items()}
    stim_name = stim_var.qname() if stim_var is not None else "not found"
    stim_info = f"{label}: {stim_name} [{stim_unit}], protocol level={stim_level:g}, BCL={bcl:g} ms"

    return SimulationResult(
        label=label,
        time_ms=time_ms,
        voltage_mv=voltage_mv,
        currents_pa=currents_pa,
        apd90_ms=apd90_ms(time_ms, voltage_mv),
        current_map=current_map,
        knob_map=knob_map,
        stim_info=stim_info,
        warning=warning,
    )


class CurrentGrid(QtWidgets.QWidget):
    def __init__(self, title: str, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)
        self.plots: Dict[str, pg.PlotWidget] = {}
        for index, current_name in enumerate(CURRENT_ORDER):
            row = index // 2
            col = index % 2
            plot = pg.PlotWidget()
            plot.setBackground("w")
            plot.showGrid(x=True, y=True, alpha=0.25)
            plot.setLabel("bottom", "Time", units="ms")
            plot.setLabel("left", "Current", units="pA")
            plot.setTitle(f"{title}: {current_name}")
            plot.addLegend(offset=(10, 10))
            layout.addWidget(plot, row, col)
            self.plots[current_name] = plot

    def clear_all(self, title_prefix: str) -> None:
        for current_name, plot in self.plots.items():
            plot.clear()
            plot.setTitle(f"{title_prefix}: {current_name}")

    def update_from_result(self, result: Optional[SimulationResult], color: str) -> None:
        prefix = result.label if result is not None else "No data"
        self.clear_all(prefix)
        if result is None:
            return
        for current_name, plot in self.plots.items():
            if current_name not in result.currents_pa:
                plot.setTitle(f"{result.label}: {current_name} (not detected)")
                continue
            values, note = result.currents_pa[current_name]
            plot.plot(result.time_ms, values, pen=pg.mkPen(color=color, width=2), name=current_name)
            plot.setTitle(f"{result.label}: {current_name} ({note})")


class ControlPanel(QtWidgets.QScrollArea):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        container = QtWidgets.QWidget()
        self.setWidget(container)
        self.form = QtWidgets.QFormLayout(container)
        self.form.setContentsMargins(10, 10, 10, 10)
        self.form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        self.inputs: Dict[str, QtWidgets.QWidget] = {}

        self.model_choice = QtWidgets.QComboBox()
        self.model_choice.addItems(["Both", MODEL_A_LABEL, MODEL_B_LABEL])
        self.form.addRow("Model(s)", self.model_choice)
        self.inputs["which_model"] = self.model_choice

        self.preset_choice = QtWidgets.QComboBox()
        self.preset_choice.addItems(list(PUBLISHED_PRESETS))
        self.preset_choice.setCurrentText(DEFAULT_PRESET_NAME)
        self.form.addRow("Published preset", self.preset_choice)
        self.inputs["preset_name"] = self.preset_choice

        param_specs = [
            ("g_Na", "GNa", 25.0, 250.0, 1.0, 3),
            ("g_NaL", "GNaL", 0.0001, 0.025, 0.0001, 6),
            ("g_CaL", "GCaL", 0.00001, 0.001, 0.00001, 6),
            ("g_to", "Gto", 0.002, 0.2, 0.001, 4),
            ("g_Kr", "GKr", 0.02, 0.2, 0.001, 4),
            ("g_Ks", "GKs", 0.002, 0.02, 0.0001, 5),
            ("g_K1", "GK1", 0.1, 1.0, 0.01, 4),
        ]
        for key, label, minimum, maximum, step, decimals in param_specs:
            spin = self.make_spin(minimum, maximum, step, decimals, DEFAULT_PARAMS[key])
            self.form.addRow(f"{label}", spin)
            self.inputs[key] = spin

        sim_spin = self.make_spin(100.0, 20000.0, 100.0, 1, DEFAULT_SIM_LENGTH_MS)
        self.form.addRow("Sim length (ms)", sim_spin)
        self.inputs["sim_length_ms"] = sim_spin

        freq_spin = self.make_spin(0.1, 20.0, 0.1, 2, 1.0)
        self.form.addRow("Stim frequency (Hz)", freq_spin)
        self.inputs["stim_frequency_hz"] = freq_spin

        duration_spin = self.make_spin(0.1, 20.0, 0.1, 2, DEFAULT_PACING["duration"])
        self.form.addRow("Stim duration (ms)", duration_spin)
        self.inputs["stim_duration_ms"] = duration_spin

        strength_spin = self.make_spin(0.1, 100.0, 0.1, 2, DEFAULT_PACING["level"])
        self.form.addRow("Stim strength (nA)", strength_spin)
        self.inputs["stim_strength_nA"] = strength_spin

        offset_spin = self.make_spin(0.0, 2000.0, 10.0, 1, DEFAULT_PACING["offset"])
        self.form.addRow("Stim offset (ms)", offset_spin)
        self.inputs["stim_offset_ms"] = offset_spin

        cm_spin = self.make_spin(5.0, 500.0, 5.0, 1, DEFAULT_CM_PF)
        self.form.addRow("Cm (pF)", cm_spin)
        self.inputs["cm_pf"] = cm_spin

        prepace_spin = self.make_int_spin(0, 500, 1, DEFAULT_PREPACE_BEATS)
        self.form.addRow("Prepace beats", prepace_spin)
        self.inputs["prepace_beats"] = prepace_spin

    @staticmethod
    def make_spin(minimum: float, maximum: float, step: float, decimals: int, value: float) -> QtWidgets.QDoubleSpinBox:
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        spin.setValue(value)
        spin.setAccelerated(True)
        return spin

    @staticmethod
    def make_int_spin(minimum: int, maximum: int, step: int, value: int) -> QtWidgets.QSpinBox:
        spin = QtWidgets.QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setValue(value)
        spin.setAccelerated(True)
        return spin

    def values(self) -> Dict[str, float | int | str]:
        output: Dict[str, float | int | str] = {
            "which_model": self.model_choice.currentText(),
            "preset_name": self.preset_choice.currentText(),
        }
        for key, widget in self.inputs.items():
            if key in {"which_model", "preset_name"}:
                continue
            if isinstance(widget, QtWidgets.QDoubleSpinBox):
                output[key] = float(widget.value())
            elif isinstance(widget, QtWidgets.QSpinBox):
                output[key] = int(widget.value())
        return output

    def apply_preset(self, preset_name: str) -> None:
        preset = PUBLISHED_PRESETS.get(preset_name)
        if preset is None:
            return
        for key, value in preset.items():
            widget = self.inputs[key]
            assert isinstance(widget, QtWidgets.QDoubleSpinBox)
            widget.setValue(value)

    def reset(self) -> None:
        self.model_choice.setCurrentText("Both")
        self.preset_choice.setCurrentText(DEFAULT_PRESET_NAME)
        self.apply_preset(DEFAULT_PRESET_NAME)
        cast_map = {
            "sim_length_ms": DEFAULT_SIM_LENGTH_MS,
            "stim_frequency_hz": 1.0,
            "stim_duration_ms": DEFAULT_PACING["duration"],
            "stim_strength_nA": DEFAULT_PACING["level"],
            "stim_offset_ms": DEFAULT_PACING["offset"],
            "cm_pf": DEFAULT_CM_PF,
            "prepace_beats": DEFAULT_PREPACE_BEATS,
        }
        for key, value in cast_map.items():
            widget = self.inputs[key]
            widget.setValue(value)  # type: ignore[arg-type]


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, model_a: myokit.Model, model_b: myokit.Model) -> None:
        super().__init__()
        self.base_model_a = model_a
        self.base_model_b = model_b
        self.setWindowTitle("Two Cardiac Models - PyQtGraph")
        self.resize(1700, 980)

        pg.setConfigOptions(antialias=True, foreground="k", background="w")

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)

        toolbar = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setWordWrap(True)
        self.run_button = QtWidgets.QPushButton("Run Simulation")
        self.reset_button = QtWidgets.QPushButton("Reset Defaults")
        toolbar.addWidget(self.run_button)
        toolbar.addWidget(self.reset_button)
        toolbar.addWidget(self.status_label, stretch=1)
        layout.addLayout(toolbar)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        layout.addWidget(splitter, stretch=1)

        self.controls = ControlPanel()
        self.controls.setMinimumWidth(320)
        splitter.addWidget(self.controls)

        self.tabs = QtWidgets.QTabWidget()
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 1)

        self.ap_plot = pg.PlotWidget()
        self.ap_plot.setBackground("w")
        self.ap_plot.showGrid(x=True, y=True, alpha=0.25)
        self.ap_plot.addLegend(offset=(10, 10))
        self.ap_plot.setLabel("bottom", "Time", units="ms")
        self.ap_plot.setLabel("left", "Membrane Potential", units="mV")
        self.ap_plot.setYRange(-100, 60)
        self.tabs.addTab(self.ap_plot, "Action Potentials")

        self.currents_a = CurrentGrid(MODEL_A_LABEL)
        self.currents_b = CurrentGrid(MODEL_B_LABEL)
        self.tabs.addTab(self.currents_a, MODEL_A_LABEL)
        self.tabs.addTab(self.currents_b, MODEL_B_LABEL)

        self.mapping_text = QtWidgets.QPlainTextEdit()
        self.mapping_text.setReadOnly(True)
        self.tabs.addTab(self.mapping_text, "Diagnostics")

        self.run_button.clicked.connect(self.run_simulation)
        self.reset_button.clicked.connect(self.handle_reset)
        self.controls.preset_choice.currentTextChanged.connect(self.controls.apply_preset)
        QtCore.QTimer.singleShot(0, self.run_simulation)

    def handle_reset(self) -> None:
        self.controls.reset()
        self.run_simulation()

    def selected_keys(self, label: str) -> List[str]:
        if label == MODEL_A_LABEL:
            return ["A"]
        if label == MODEL_B_LABEL:
            return ["B"]
        return ["A", "B"]

    def run_simulation(self) -> None:
        values = self.controls.values()
        knob_values = {key: float(values[key]) for key in DEFAULT_PARAMS}
        sim_length_ms = float(values["sim_length_ms"])
        stim_frequency_hz = float(values["stim_frequency_hz"])
        stim_duration_ms = float(values["stim_duration_ms"])
        stim_strength_nA = float(values["stim_strength_nA"])
        stim_offset_ms = float(values["stim_offset_ms"])
        cm_pf = float(values["cm_pf"])
        prepace_beats = int(values["prepace_beats"])
        which_model = str(values["which_model"])
        preset_name = str(values["preset_name"])

        self.status_label.setText("Running Myokit simulations...")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        QtWidgets.QApplication.processEvents()
        try:
            results: Dict[str, SimulationResult] = {}
            for model_key in self.selected_keys(which_model):
                base_model = self.base_model_a if model_key == "A" else self.base_model_b
                results[model_key] = simulate_model(
                    base_model=base_model,
                    model_key=model_key,
                    label=MODEL_KEYS[model_key],
                    knob_values=knob_values,
                    sim_length_ms=sim_length_ms,
                    freq_hz=stim_frequency_hz,
                    stim_duration_ms=stim_duration_ms,
                    stim_strength_nA=stim_strength_nA,
                    stim_offset_ms=stim_offset_ms,
                    cm_pf=cm_pf,
                    prepace_beats=prepace_beats,
                )
        except Exception as exc:
            self.status_label.setText(f"Simulation failed: {exc}")
            details = traceback.format_exc()
            self.mapping_text.setPlainText(details)
            QtWidgets.QMessageBox.critical(self, "Simulation error", details)
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        self.update_ap_plot(results)
        self.currents_a.update_from_result(results.get("A"), MODEL_COLORS["A"])
        self.currents_b.update_from_result(results.get("B"), MODEL_COLORS["B"])
        self.update_diagnostics(results, knob_values, preset_name)

        status_parts = []
        for key in self.selected_keys(which_model):
            result = results[key]
            apd_text = f"{result.apd90_ms:.1f} ms" if result.apd90_ms is not None else "n/a"
            status_parts.append(f"{result.label} APD90: {apd_text}")
            if result.warning:
                status_parts.append(f"{result.label} warning: {result.warning}")
        self.status_label.setText(" | ".join(status_parts) if status_parts else "No result")

    def update_ap_plot(self, results: Dict[str, SimulationResult]) -> None:
        self.ap_plot.clear()
        self.ap_plot.addLegend(offset=(10, 10))
        for model_key in ("A", "B"):
            result = results.get(model_key)
            if result is None or result.voltage_mv is None:
                continue
            self.ap_plot.plot(
                result.time_ms,
                result.voltage_mv,
                pen=pg.mkPen(MODEL_COLORS[model_key], width=2),
                name=result.label,
            )
        self.ap_plot.setTitle("Action Potentials")

    def update_diagnostics(
        self,
        results: Dict[str, SimulationResult],
        knob_values: Dict[str, float],
        preset_name: str,
    ) -> None:
        lines = ["PyQtGraph desktop replacement for the old Dash app.", ""]
        lines.append(f"Selected preset: {preset_name}")
        lines.append(f"Preset source: {PRESET_SOURCES[preset_name]}")
        lines.append(ATRIAL_MODEL_REQUEST)
        lines.append("")
        lines.append("Applied conductance values:")
        for key, value in knob_values.items():
            lines.append(f"  {key}: {value}")
        lines.append("")
        for model_key in ("A", "B"):
            result = results.get(model_key)
            if result is None:
                continue
            lines.append(f"== {result.label} ==")
            lines.append(result.stim_info)
            lines.append("Currents:")
            if result.current_map:
                for name in CURRENT_ORDER:
                    if name in result.current_map:
                        lines.append(f"  {name:<4} -> {result.current_map[name]}")
            else:
                lines.append("  (none detected)")
            lines.append("Knobs:")
            if result.knob_map:
                for name in DEFAULT_PARAMS:
                    if name in result.knob_map:
                        lines.append(f"  {name:<5} -> {result.knob_map[name]}")
            else:
                lines.append("  (none detected)")
            if result.warning:
                lines.append(f"Warning: {result.warning}")
            lines.append("")
        self.mapping_text.setPlainText("\n".join(lines).strip())


def main() -> int:
    path_a = find_file(MODEL_A_PATH, MODEL_A_PATH.name)
    path_b = find_file(MODEL_B_PATH, MODEL_B_PATH.name)
    model_a = load_model_any(path_a)
    model_b = load_model_any(path_b)
    ensure_time_binding(model_a)
    ensure_time_binding(model_b)

    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow(model_a, model_b)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
