#!/usr/bin/env python3
"""Published cardiac AP explorer using Myokit + PyQtGraph."""

from __future__ import annotations

import importlib
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
from pyqtgraph.Qt import QtCore, QtWidgets

from simone_trancuccio_backend import SIMONE_DEFAULT_CM_PF, simulate_simone_model


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

DEFAULT_PACING = {"duration": 1.0, "level": 1.1, "offset": 200.0}
DEFAULT_SIM_LENGTH_MS = 1000.0
DEFAULT_PREPACE_BEATS = 50
DEFAULT_CM_PF = 50.0
DEFAULT_MODEL_NAME = "ToR-ORd-dynCl ventricular"
STIM_POLARITY = -1

KNOB_SPECS = [
    ("g_Na", "GNa", 0.0, 10000.0, 0.01, 6),
    ("g_NaL", "GNaL", 0.0, 100.0, 0.0001, 6),
    ("g_CaL", "GCaL", 0.0, 5.0, 0.0001, 6),
    ("g_CaT", "GCaT", 0.0, 1.0, 0.0001, 6),
    ("g_f", "Gf", 0.0, 100.0, 0.0001, 6),
    ("g_to", "Gto", 0.0, 100.0, 0.0001, 6),
    ("g_Kr", "GKr", 0.0, 100.0, 0.0001, 6),
    ("g_Ks", "GKs", 0.0, 10.0, 0.0001, 6),
    ("g_K1", "GK1", 0.0, 20.0, 0.0001, 6),
    ("g_Kur", "GKur", 0.0, 1.0, 0.0001, 6),
    ("g_KACh", "GKACh", 0.0, 1.0, 0.0001, 6),
    ("g_NaCa", "GNaCa", 0.0, 20000.0, 0.01, 6),
    ("g_NaK", "GNaK", 0.0, 100.0, 0.01, 6),
]

EMULATOR_DEFAULTS = {
    "g_Na": 23.5590 / 2.0,
    "g_NaL": 0.0557966 / 2.0,
    "g_to": 0.319980 / 2.0,
    "g_Kr": 0.0641980 / 2.0,
    "g_Ks": 0.00219987 / 2.0,
    "g_K1": 1.39831 / 2.0,
    "g_NaCa": 0.00679958 / 2.0,
    "g_NaK": 30.8999 / 2.0,
    "g_CaL": 0.000167509 / 2.0,
}

SIMONE_DEFAULTS = {
    "g_Na": 1.2176 * 6447.1896,
    "g_NaL": 1.3021 * 2.3 * 7.5,
    "g_CaL": 1.0,
    "g_f": 0.62395 * 22.2763088,
    "g_to": 1.2913 * 29.9038,
    "g_Kr": 1.9913 * 29.8667,
    "g_Ks": 1.0726 * 2.041,
    "g_K1": 0.50122 * 28.1492,
    "g_NaCa": 0.66821 * 6514.47574,
    "g_NaK": 1.3055 * 2.74240,
}

MODEL_LIBRARY = {
    "ORd 2011 ventricular": {
        "path": HERE / "ord-2011-apd.txt",
        "source": "O'Hara, Virag, Varro, Rudy 2011 human ventricular model.",
        "stim": None,
        "external_stim": True,
        "knobs": {
            "g_Na": "ina.GNa",
            "g_CaL": "ical.PCa",
            "g_Kr": "ikr.GKr",
            "g_Ks": "iks.GKs",
            "g_to": "ito.Gto",
            "g_NaL": "inal.GNaL",
            "g_K1": "ik1.GK1",
        },
        "currents": {
            "INa": "ina.INa",
            "INaL": "inal.INaL",
            "ICaL": "ical.ICaL",
            "Ito": "ito.Ito",
            "IKr": "ikr.IKr",
            "IKs": "iks.IKs",
            "IK1": "ik1.IK1",
        },
        "defaults": {
            "g_Na": 75.0,
            "g_CaL": 0.0001,
            "g_Kr": 0.046,
            "g_Ks": 0.0034,
            "g_to": 0.02,
            "g_NaL": 0.0075,
            "g_K1": 0.1908,
        },
    },
    "ToR-ORd-dynCl ventricular": {
        "path": HERE / "ToRORd_dynCl_endo.mmt",
        "source": "Tomek, Bueno-Orovio, Rodriguez 2020 ToR-ORd-dynCl human ventricular model.",
        "stim": "membrane.I_stim",
        "external_stim": True,
        "knobs": {
            "g_Na": "INa.GNa",
            "g_CaL": "ICaL.PCa",
            "g_Kr": "IKr.GKr",
            "g_Ks": "IKs.GKs",
            "g_to": "Ito.Gto",
            "g_NaL": "INaL.GNaL",
            "g_K1": "IK1.GK1",
        },
        "currents": {
            "INa": "INa.INa",
            "INaL": "INaL.INaL",
            "ICaL": "ICaL.ICaL",
            "Ito": "Ito.Ito",
            "IKr": "IKr.IKr",
            "IKs": "IKs.IKs",
            "IK1": "IK1.IK1",
        },
        "defaults": {
            "g_Na": 11.7802,
            "g_CaL": 8.3757e-05,
            "g_Kr": 0.0321,
            "g_Ks": 0.0011,
            "g_to": 0.16,
            "g_NaL": 0.0279,
            "g_K1": 0.6992,
        },
    },
    "BPS2020 ventricular": {
        "path": HERE / "BPS2020.mmt",
        "source": "Bartolucci, Passini, Hyttinen, Paci, Severi 2020 BPS2020 human ventricular model.",
        "stim": "stimulus.i_stim",
        "external_stim": True,
        "knobs": {
            "g_Na": "INa.GNa",
            "g_CaL": "ICaL.PCa",
            "g_Kr": "IKr.GKr",
            "g_Ks": "IKs.GKs",
            "g_to": "Ito.Gto",
            "g_NaL": "INaL.GNaL",
            "g_K1": "IK1.GK1",
        },
        "currents": {
            "INa": "INa.INa",
            "INaL": "INaL.INaL",
            "ICaL": "ICaL.ICaL",
            "Ito": "Ito.Ito",
            "IKr": "IKr.IKr",
            "IKs": "IKs.IKs",
            "IK1": "IK1.IK1",
        },
        "defaults": {
            "g_Na": 75.0,
            "g_CaL": 9.0e-05,
            "g_Kr": 0.0552,
            "g_Ks": 0.0068,
            "g_to": 0.02,
            "g_NaL": 0.0210,
            "g_K1": 0.135468,
        },
    },
    "Grandi 2011 atrial": {
        "path": HERE / "grandi_2011_atrial_with_meta.cellml",
        "source": "Grandi, Pandit, Voigt et al. 2011 human atrial electrophysiology model.",
        "stim": "stimulus.I_stim",
        "external_stim": True,
        "knobs": {
            "g_Na": "ina.gNa",
            "g_NaL": "inal.gNaL",
            "g_CaL": "ical.pCa",
            "g_to": "ito.gto",
            "g_Kr": "ikr.gKr",
            "g_Ks": "iks.gKs_max",
            "g_K1": "ik1.gK1",
            "g_Kur": "ikur.gKur",
        },
        "currents": {
            "INa": "ina.INa",
            "INaL": "inal.INaL",
            "ICaL": "ical.ICaL",
            "Ito": "ito.Ito",
            "IKr": "ikr.IKr",
            "IKs": "iks.IKs",
            "IK1": "ik1.IK1",
            "IKur": "ikur.IKur",
        },
        "defaults": {
            "g_Na": 23.0,
            "g_NaL": 0.0,
            "g_CaL": 0.00027,
            "g_to": 0.165,
            "g_Kr": 0.035,
            "g_Ks": 0.0035,
            "g_K1": 0.0525,
            "g_Kur": 0.045,
        },
    },
    "Fabbri 2017 pacemaker": {
        "path": HERE / "HumanSAN_Fabbri_Fantini_Wilders_Severi_2017.cellml",
        "source": "Fabbri, Fantini, Wilders, Severi 2017 human sinoatrial node model.",
        "stim": None,
        "external_stim": False,
        "pre_ms": 5000.0,
        "log_interval_ms": 0.2,
        "knobs": {
            "g_f": "i_f.g_f",
            "g_Na": "i_Na.g_Na",
            "g_NaL": "i_Na.g_Na_L",
            "g_CaL": "i_CaL.P_CaL",
            "g_CaT": "i_CaT.P_CaT",
            "g_to": "i_to.g_to",
            "g_Kr": "i_Kr.g_Kr",
            "g_Ks": "i_Ks.g_Ks_",
            "g_Kur": "i_Kur.g_Kur",
            "g_KACh": "i_KACh.g_KACh",
        },
        "currents": {
            "If": "i_f.i_f",
            "INa": "i_Na.i_Na",
            "ICaL": "i_CaL.i_CaL",
            "ICaT": "i_CaT.i_CaT",
            "IKr": "i_Kr.i_Kr",
            "IKs": "i_Ks.i_Ks",
            "Ito": "i_to.i_to",
            "IKur": "i_Kur.i_Kur",
            "IKACh": "i_KACh.i_KACh",
            "INaK": "i_NaK.i_NaK",
            "INaCa": "i_NaCa.i_NaCa",
        },
        "defaults": {
            "g_f": 0.00427,
            "g_Na": 0.0223,
            "g_NaL": 0.0,
            "g_CaL": 0.4578,
            "g_CaT": 0.04132,
            "g_to": 0.0035,
            "g_Kr": 0.00424,
            "g_Ks": 0.00065,
            "g_Kur": 0.0001539,
            "g_KACh": 0.00345,
        },
        "run_defaults": {
            "sim_length_ms": 2000.0,
            "stim_frequency_hz": 0.0,
            "stim_duration_ms": 0.0,
            "stim_strength_nA": 0.0,
            "stim_offset_ms": 0.0,
            "cm_pf": DEFAULT_CM_PF,
            "prepace_beats": 0,
        },
    },
    "Simone 2026 hiPSC ventricular": {
        "backend": "simone",
        "source": "Simone, Trancuccio et al. 2026 hiPSC-derived ventricular myocyte model.",
        "external_stim": True,
        "fractional_ts": 0.0,
        "knobs": {
            "g_Na": "g_Na",
            "g_NaL": "GNaLmax",
            "g_CaL": "bGCaL",
            "g_f": "g_f",
            "g_to": "g_to",
            "g_Kr": "g_Kr",
            "g_Ks": "g_Ks",
            "g_K1": "g_K1",
            "g_NaCa": "kNaCa",
            "g_NaK": "PNaK",
        },
        "currents": {
            "INa": "INa",
            "INaL": "INaL",
            "ICaL": "ICaL",
            "Ito": "Ito",
            "IKr": "IKr",
            "IKs": "IKs",
            "IK1": "IK1",
            "If": "If",
            "INaCa": "INaCa",
            "INaK": "INaK",
            "Istim": "Istim",
        },
        "defaults": dict(SIMONE_DEFAULTS),
        "run_defaults": {
            "sim_length_ms": 1000.0,
            "stim_frequency_hz": 0.0,
            "stim_duration_ms": 5.0,
            "stim_strength_nA": 0.0,
            "stim_offset_ms": 0.0,
            "cm_pf": SIMONE_DEFAULT_CM_PF,
            "prepace_beats": 0,
        },
    },
    "Simone 2026 hiPSC ventricular (TS 22%)": {
        "backend": "simone",
        "source": "Simone, Trancuccio et al. 2026 hiPSC-derived ventricular myocyte model with Timothy syndrome fraction 0.22.",
        "external_stim": True,
        "fractional_ts": 0.22,
        "knobs": {
            "g_Na": "g_Na",
            "g_NaL": "GNaLmax",
            "g_CaL": "bGCaL",
            "g_f": "g_f",
            "g_to": "g_to",
            "g_Kr": "g_Kr",
            "g_Ks": "g_Ks",
            "g_K1": "g_K1",
            "g_NaCa": "kNaCa",
            "g_NaK": "PNaK",
        },
        "currents": {
            "INa": "INa",
            "INaL": "INaL",
            "ICaL": "ICaL",
            "Ito": "Ito",
            "IKr": "IKr",
            "IKs": "IKs",
            "IK1": "IK1",
            "If": "If",
            "INaCa": "INaCa",
            "INaK": "INaK",
            "Istim": "Istim",
        },
        "defaults": dict(SIMONE_DEFAULTS),
        "run_defaults": {
            "sim_length_ms": 1000.0,
            "stim_frequency_hz": 0.0,
            "stim_duration_ms": 5.0,
            "stim_strength_nA": 0.0,
            "stim_offset_ms": 0.0,
            "cm_pf": SIMONE_DEFAULT_CM_PF,
            "prepace_beats": 0,
        },
    },
    "Grandits 2024 ventricular emulator": {
        "backend": "emulator",
        "source": "Grandits et al. 2024 eLife neural ventricular AP emulator trained on ventricular conductance space.",
        "external_stim": False,
        "knobs": {
            "g_Na": "GNa",
            "g_NaL": "GNaL_b",
            "g_to": "Gto_b",
            "g_Kr": "GKr_b",
            "g_Ks": "GKs_b",
            "g_K1": "GK1_b",
            "g_NaCa": "Gncx_b",
            "g_NaK": "Pnak_b",
            "g_CaL": "PCa_b",
        },
        "currents": {},
        "defaults": dict(EMULATOR_DEFAULTS),
        "run_defaults": {
            "sim_length_ms": 600.0,
            "stim_frequency_hz": 0.0,
            "stim_duration_ms": 0.0,
            "stim_strength_nA": 0.0,
            "stim_offset_ms": 0.0,
            "cm_pf": DEFAULT_CM_PF,
            "prepace_beats": 0,
        },
    },
}

MODEL_NOTE = (
    "This viewer now includes published ventricular, atrial, SAN, hiPSC, and emulator entries. "
    "Mazhar 2024 remains a separate atrial electromechanics model, and the Grandits 2024 "
    "emulator provides AP morphology only, not mechanistic ionic current traces."
)

CUR_PATTERNS: Dict[str, List[re.Pattern[str]]] = {
    "INa": [re.compile(r"(?:^|[._])i[_]?na(?:$|[._])", re.I), re.compile(r"(?:^|[._])ina(?:$|[._])", re.I)],
    "INaL": [re.compile(r"(?:^|[._])i[_]?nal(?:$|[._])", re.I), re.compile(r"(?:^|[._])inal(?:$|[._])", re.I)],
    "ICaL": [re.compile(r"(?:^|[._])i[_]?ca?l(?:$|[._])", re.I), re.compile(r"(?:^|[._])ical(?:$|[._])", re.I)],
    "ICaT": [re.compile(r"(?:^|[._])i[_]?ca?t(?:$|[._])", re.I), re.compile(r"(?:^|[._])icat(?:$|[._])", re.I)],
    "If": [re.compile(r"(?:^|[._])i[_]?f(?:$|[._])", re.I)],
    "Ito": [re.compile(r"(?:^|[._])i[_]?to(?:$|[._])", re.I), re.compile(r"(?:^|[._])ito(?:$|[._])", re.I)],
    "IKr": [re.compile(r"(?:^|[._])i[_]?kr(?:$|[._])", re.I), re.compile(r"(?:^|[._])ikr(?:$|[._])", re.I)],
    "IKs": [re.compile(r"(?:^|[._])i[_]?ks(?:$|[._])", re.I), re.compile(r"(?:^|[._])iks(?:$|[._])", re.I)],
    "IK1": [re.compile(r"(?:^|[._])i[_]?k1(?:$|[._])", re.I), re.compile(r"(?:^|[._])ik1(?:$|[._])", re.I)],
    "IKur": [re.compile(r"(?:^|[._])i[_]?kur(?:$|[._])", re.I), re.compile(r"(?:^|[._])ikur(?:$|[._])", re.I)],
    "IKACh": [re.compile(r"(?:^|[._])i[_]?kach(?:$|[._])", re.I), re.compile(r"(?:^|[._])i[_]?ach(?:$|[._])", re.I)],
    "INaK": [re.compile(r"(?:^|[._])i[_]?nak(?:$|[._])", re.I)],
    "INaCa": [re.compile(r"(?:^|[._])i[_]?naca(?:$|[._])", re.I)],
}

STIM_PATTERNS = [
    re.compile(r"(?:^|[._])i[_]?stim(?:$|[._])", re.I),
    re.compile(r"(?:^|[._])stimulus[._]i(?:$|[._])", re.I),
    re.compile(r"(?:^|[._])membrane[._]i[_]?stim(?:$|[._])", re.I),
]


@dataclass
class SimulationResult:
    model_name: str
    time_ms: np.ndarray
    voltage_mv: Optional[np.ndarray]
    currents_pa: Dict[str, Tuple[np.ndarray, str]]
    current_order: List[str]
    apd90_ms: Optional[float]
    current_map: Dict[str, str]
    knob_map: Dict[str, str]
    stim_info: str
    source: str
    warning: Optional[str]


def _ensure_std_streams() -> None:
    if getattr(sys, "stdout", None) is None or getattr(sys.stdout, "closed", False):
        sys.stdout = sys.__stdout__
    if getattr(sys, "stderr", None) is None or getattr(sys.stderr, "closed", False):
        sys.stderr = sys.__stderr__


def fix_grandi_cellml_if_needed(path: Path) -> None:
    if path.name != "grandi_2011_atrial_with_meta.cellml" or not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    new_text = text.replace('units name="1_times_1000000000000000"', 'units name="u_scale_1_times_1000000000000000"')
    new_text = new_text.replace('cellml:units="1_times_1000000000000000"', 'cellml:units="u_scale_1_times_1000000000000000"')
    new_text = re.sub(r'initial_value="\s+([^"]+)"', r'initial_value="\1"', new_text)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")


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
        fix_grandi_cellml_if_needed(path)
        from myokit.formats import cellml

        return cellml.CellMLImporter().model(str(path))
    raise ValueError(f"Unsupported model file: {path}")


def ensure_time_binding(model: myokit.Model) -> None:
    if model.time() is not None:
        return
    for name in ("engine.time", "environment.time", "membrane.time", "Membrane.time", "time.time", "time"):
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
    for tag in ("[pA]", "pA", "[nA]", "nA", "[uA]", "uA", "[mA]", "mA", "[A]", " A", "ampere"):
        if tag in text:
            if "pA" in tag:
                return "pA"
            if "nA" in tag:
                return "nA"
            if "uA" in tag:
                return "uA"
            if "mA" in tag:
                return "mA"
            return "A"
    if "A" in text:
        return "A"
    return "?"


def time_unit_to_ms_factor(model: myokit.Model) -> float:
    time_var = model.time()
    if time_var is None:
        return 1.0
    text = unit_text(time_var).strip().lower()
    if text in {"[s]", "s", "second", "[second]"}:
        return 1000.0
    if text in {"[ms]", "ms", "millisecond", "[millisecond]"}:
        return 1.0
    if text in {"[us]", "us", "microsecond", "[microsecond]"}:
        return 1e-3
    if text in {"[ns]", "ns", "nanosecond", "[nanosecond]"}:
        return 1e-6
    return 1.0


def autodetect_currents(model: myokit.Model, overrides: Optional[Dict[str, str]] = None) -> Dict[str, myokit.Variable]:
    found: Dict[str, myokit.Variable] = {}
    if overrides:
        for name, qname in overrides.items():
            try:
                var = model.get(qname)
            except KeyError:
                continue
            if isinstance(var, myokit.Variable):
                found[name] = var
    qname_map = {var.qname(): var for var in model.variables()}
    for current_name, patterns in CUR_PATTERNS.items():
        if current_name in found:
            continue
        best: Optional[myokit.Variable] = None
        best_score = -1
        for qname, var in qname_map.items():
            score = 2 * sum(pattern.search(qname) is not None for pattern in patterns)
            if "A" in unit_text(var):
                score += 1
            if score > best_score:
                best = var
                best_score = score
        if best is not None and best_score > 0:
            found[current_name] = best
    return found


def load_knobs(model: myokit.Model, knob_map: Dict[str, str]) -> Dict[str, myokit.Variable]:
    found: Dict[str, myokit.Variable] = {}
    for name, qname in knob_map.items():
        try:
            var = model.get(qname)
        except KeyError:
            continue
        if isinstance(var, myokit.Variable):
            found[name] = var
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
        elif tag in {"A", "mA", "uA", "nA", "pA"}:
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
    amp_nA = float(level_nA)
    if target_unit == "A":
        value = amp_nA * 1e-9
    elif target_unit == "mA":
        value = amp_nA * 1e-6
    elif target_unit == "uA":
        value = amp_nA * 1e-3
    elif target_unit == "nA":
        value = amp_nA
    elif target_unit == "pA":
        value = amp_nA * 1e3
    else:
        value = (amp_nA / float(cm_pf)) * 1e3
    return float(polarity) * abs(value)


def current_to_pa(values: np.ndarray, tag: str, cm_pf: float) -> Tuple[np.ndarray, str]:
    if tag == "A/F":
        return values * float(cm_pf), "A/F -> pA"
    if tag == "A":
        return values * 1e12, "A -> pA"
    if tag == "mA":
        return values * 1e9, "mA -> pA"
    if tag == "uA":
        return values * 1e6, "uA -> pA"
    if tag == "nA":
        return values * 1e3, "nA -> pA"
    if tag == "pA":
        return values, "pA"
    return values, "raw"


def emulator_repo_root() -> Path:
    path = HERE / "cardiomyocyte_emulator_repo"
    if not path.is_dir():
        raise FileNotFoundError(f"Missing emulator repository: {path}")
    return path


_EMULATOR_CACHE: Optional[object] = None


def load_emulator_model():
    global _EMULATOR_CACHE
    if _EMULATOR_CACHE is not None:
        return _EMULATOR_CACHE

    import torch

    repo = emulator_repo_root()
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    importlib.invalidate_caches()
    emulator_module = importlib.import_module("cardiomyocyte_emulator.emulator")
    emulator_class = getattr(emulator_module, "APEmulator")

    state_path = repo / "cardiomyocyte_emulator" / "emulator_state.pt"
    if not state_path.is_file():
        raise FileNotFoundError(f"Missing emulator state file: {state_path}")
    try:
        state_dict = torch.load(state_path, map_location="cpu", weights_only=False)
    except TypeError:
        state_dict = torch.load(state_path, map_location="cpu")
    max_conds_names = state_dict["max_conds_names"]
    max_conds_ranges = state_dict["max_conds_ranges"]
    del state_dict["max_conds_names"]
    del state_dict["max_conds_ranges"]

    emulator = emulator_class(device="cpu")
    emulator.load_state_dict(state_dict)
    emulator.max_conds_names = max_conds_names
    emulator.max_conds_ranges = max_conds_ranges
    for layer in emulator.latent_encoder + emulator.vm_emu:
        layer.requires_grad_(False)
    emulator.eval()
    _EMULATOR_CACHE = emulator
    return emulator


def simulate_emulator_model(
    model_name: str,
    config: Dict[str, object],
    knob_values: Dict[str, float],
    sim_length_ms: float,
) -> SimulationResult:
    emulator = load_emulator_model()
    cond_names = [str(name) for name in emulator.max_conds_names]
    cond_index = {name: idx for idx, name in enumerate(cond_names)}
    cond_values = np.asarray(emulator.max_conds_center, dtype=float).copy()
    for knob_name, cond_name in config["knobs"].items():
        if knob_name not in knob_values or cond_name not in cond_index:
            continue
        cond_values[cond_index[cond_name]] = float(knob_values[knob_name])

    capped_length_ms = min(max(float(sim_length_ms), 50.0), 1000.0)
    nr_points = int(min(4000, max(400, round(capped_length_ms / 0.2))))
    time_ms = np.linspace(-10.0, capped_length_ms, nr_points)
    voltage_mv = np.asarray(emulator.forward_latent_np(time_ms, cond_values), dtype=float).reshape(-1)

    warning = None
    if sim_length_ms > 1000.0:
        warning = "Emulator time window capped at 1000 ms because the published surrogate is trained on a single-beat range."

    return SimulationResult(
        model_name=model_name,
        time_ms=time_ms,
        voltage_mv=voltage_mv,
        currents_pa={},
        current_order=[],
        apd90_ms=apd90_ms(time_ms, voltage_mv),
        current_map={},
        knob_map={key: value for key, value in config["knobs"].items()},
        stim_info="No explicit pacing protocol in the emulator backend.",
        source=config["source"],
        warning=warning,
    )


def build_simulation(model: myokit.Model, protocol: Optional[myokit.Protocol]) -> myokit.Simulation:
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
    for name in ("membrane.V", "Membrane.V", "cell.V", "voltage.V", "V", "membrane.v"):
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


def simulate_selected_model(
    model_name: str,
    knob_values: Dict[str, float],
    sim_length_ms: float,
    stim_frequency_hz: float,
    stim_duration_ms: float,
    stim_strength_nA: float,
    stim_offset_ms: float,
    cm_pf: float,
    prepace_beats: int,
) -> SimulationResult:
    config = MODEL_LIBRARY[model_name]
    backend = str(config.get("backend", "myokit"))

    if backend == "emulator":
        return simulate_emulator_model(
            model_name=model_name,
            config=config,
            knob_values=knob_values,
            sim_length_ms=sim_length_ms,
        )

    if backend == "simone":
        simone_params = {
            "g_Na": float(knob_values["g_Na"]),
            "GNaLmax": float(knob_values["g_NaL"]),
            "bGCaL": float(knob_values["g_CaL"]),
            "g_f": float(knob_values["g_f"]),
            "g_to": float(knob_values["g_to"]),
            "g_Kr": float(knob_values["g_Kr"]),
            "g_Ks": float(knob_values["g_Ks"]),
            "g_K1": float(knob_values["g_K1"]),
            "kNaCa": float(knob_values["g_NaCa"]),
            "PNaK": float(knob_values["g_NaK"]),
        }
        simone_result = simulate_simone_model(
            sim_length_ms=sim_length_ms,
            stim_frequency_hz=stim_frequency_hz,
            stim_duration_ms=stim_duration_ms,
            stim_strength_nA=stim_strength_nA,
            stim_offset_ms=stim_offset_ms,
            prepace_beats=prepace_beats,
            fractional_ts=float(config.get("fractional_ts", 0.0)),
            params=simone_params,
        )
        currents_pa: Dict[str, Tuple[np.ndarray, str]] = {}
        for current_name in simone_result.current_order:
            values = simone_result.currents_af.get(current_name)
            if values is None:
                continue
            scaled, note = current_to_pa(np.asarray(values, dtype=float), "A/F", cm_pf)
            currents_pa[current_name] = (scaled, note)
        if stim_strength_nA > 0 and stim_frequency_hz > 0 and stim_duration_ms > 0:
            stim_info = (
                f"Simone hiPSC pacing: {stim_strength_nA:g} nA, {stim_duration_ms:g} ms, "
                f"{stim_frequency_hz:g} Hz, offset {stim_offset_ms:g} ms"
            )
        else:
            stim_info = "Simone hiPSC spontaneous mode (no external stimulus)."
        return SimulationResult(
            model_name=model_name,
            time_ms=simone_result.time_ms,
            voltage_mv=simone_result.voltage_mv,
            currents_pa=currents_pa,
            current_order=simone_result.current_order,
            apd90_ms=apd90_ms(simone_result.time_ms, simone_result.voltage_mv),
            current_map={name: f"{qname} [A/F]" for name, qname in config["currents"].items()},
            knob_map={key: value for key, value in config["knobs"].items()},
            stim_info=stim_info,
            source=config["source"],
            warning=simone_result.warning,
        )

    model_path = find_file(config["path"], Path(config["path"]).name)
    model = load_model_any(model_path)
    ensure_time_binding(model)
    model_to_ms = time_unit_to_ms_factor(model)
    ms_to_model = 1.0 / model_to_ms

    current_vars = autodetect_currents(model, config["currents"])
    knob_vars = load_knobs(model, config["knobs"])
    for name, value in knob_values.items():
        knob_var = knob_vars.get(name)
        if knob_var is None:
            continue
        try:
            knob_var.set_rhs(float(value))
        except Exception:
            pass

    freq = max(float(stim_frequency_hz), 1e-6)
    bcl_ms = 1000.0 / freq
    bcl = bcl_ms * ms_to_model
    protocol: Optional[myokit.Protocol]
    stim_info: str
    stim_var: Optional[myokit.Variable] = None
    stim_unit = "?"

    if config.get("external_stim", True) and stim_frequency_hz > 0 and stim_strength_nA > 0 and stim_duration_ms > 0:
        stim_var, stim_unit = choose_stim_var(model, config.get("stim"))
        stim_level = stim_level_nA_to_target(stim_strength_nA, stim_unit, cm_pf, STIM_POLARITY)
        protocol = myokit.pacing.blocktrain(
            period=bcl,
            duration=float(stim_duration_ms) * ms_to_model,
            level=stim_level,
            offset=float(stim_offset_ms) * ms_to_model,
        )
        stim_name = stim_var.qname() if stim_var is not None else "not found"
        stim_info = f"{stim_name} [{stim_unit}], protocol level={stim_level:g}, BCL={bcl_ms:g} ms"
    elif config.get("external_stim", True):
        protocol = None
        stim_info = "No external stimulus protocol."
    else:
        protocol = None
        stim_info = "Intrinsic pacemaker rhythm (no external stimulus protocol)."

    sim = build_simulation(model, protocol)
    pre_default_ms = float(prepace_beats) * bcl_ms if protocol is not None else 0.0
    pre_ms = float(config.get("pre_ms", pre_default_ms))
    if pre_ms > 0:
        sim.pre(pre_ms * ms_to_model)

    to_log: List[myokit.Variable] = [model.time()]
    voltage_var = find_voltage_var(model)
    if voltage_var is not None:
        to_log.append(voltage_var)
    for var in current_vars.values():
        to_log.append(var)
    if stim_var is not None:
        to_log.append(stim_var)

    run_kwargs = {}
    log_interval_ms = config.get("log_interval_ms")
    if log_interval_ms is not None:
        run_kwargs["log_interval"] = float(log_interval_ms) * ms_to_model
    log = sim.run(float(sim_length_ms) * ms_to_model, log=to_log, **run_kwargs)
    time_ms = np.asarray(log.time(), dtype=float) * model_to_ms
    voltage_mv = np.asarray(log[voltage_var], dtype=float) if voltage_var is not None else None

    def is_flat(trace: Optional[np.ndarray]) -> bool:
        if trace is None or trace.size == 0:
            return True
        return float(np.max(trace) - np.min(trace)) < 30.0

    warning: Optional[str] = None
    if config.get("external_stim", True) and is_flat(voltage_mv):
        warning = "auto-rescue failed"
        for polarity in (STIM_POLARITY, -STIM_POLARITY):
            for amp_factor in (2.0, 4.0, 8.0):
                for duration_ms in (max(stim_duration_ms, 1.0), max(stim_duration_ms, 2.0)):
                    alt_level = stim_level_nA_to_target(stim_strength_nA * amp_factor, stim_unit, cm_pf, polarity)
                    alt_protocol = myokit.pacing.blocktrain(
                        period=bcl,
                        duration=float(duration_ms) * ms_to_model,
                        level=alt_level,
                        offset=float(stim_offset_ms) * ms_to_model,
                    )
                    alt_sim = build_simulation(model, alt_protocol)
                    if pre_ms > 0:
                        alt_sim.pre(pre_ms * ms_to_model)
                    alt_log = alt_sim.run(float(sim_length_ms) * ms_to_model, log=to_log, **run_kwargs)
                    alt_voltage = np.asarray(alt_log[voltage_var], dtype=float) if voltage_var is not None else None
                    if not is_flat(alt_voltage):
                        log = alt_log
                        time_ms = np.asarray(log.time(), dtype=float) * model_to_ms
                        voltage_mv = alt_voltage
                        warning = f"auto-rescue amp x{amp_factor:g}, duration {duration_ms:g} ms, polarity {polarity:+d}"
                        break
                if warning and warning.startswith("auto-rescue amp"):
                    break
            if warning and warning.startswith("auto-rescue amp"):
                break

    currents_pa: Dict[str, Tuple[np.ndarray, str]] = {}
    for current_name in config["currents"]:
        var = current_vars.get(current_name)
        if var is None:
            continue
        values = np.asarray(log[var], dtype=float)
        scaled, note = current_to_pa(values, unit_tag(var), cm_pf)
        currents_pa[current_name] = (scaled, note)

    current_map = {name: f"{var.qname()} [{unit_text(var)}]" for name, var in current_vars.items()}
    knob_map = {name: var.qname() for name, var in knob_vars.items()}

    return SimulationResult(
        model_name=model_name,
        time_ms=time_ms,
        voltage_mv=voltage_mv,
        currents_pa=currents_pa,
        current_order=list(config["currents"].keys()),
        apd90_ms=apd90_ms(time_ms, voltage_mv),
        current_map=current_map,
        knob_map=knob_map,
        stim_info=stim_info,
        source=config["source"],
        warning=warning,
    )


class CurrentGrid(QtWidgets.QWidget):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.layout = QtWidgets.QGridLayout(self)
        self.layout.setContentsMargins(6, 6, 6, 6)
        self.layout.setHorizontalSpacing(8)
        self.layout.setVerticalSpacing(8)
        self.plots: List[pg.PlotWidget] = []

    def clear(self) -> None:
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.plots.clear()

    def update_from_result(self, result: Optional[SimulationResult]) -> None:
        self.clear()
        if result is None:
            return
        columns = 3
        visible_currents = [name for name in result.current_order if name in result.currents_pa]
        for index, current_name in enumerate(visible_currents):
            row = index // columns
            col = index % columns
            plot = pg.PlotWidget()
            plot.setBackground("w")
            plot.showGrid(x=True, y=True, alpha=0.25)
            plot.setLabel("bottom", "Time", units="ms")
            plot.setLabel("left", "Current", units="pA")
            values, note = result.currents_pa[current_name]
            plot.plot(result.time_ms, values, pen=pg.mkPen("#0072B2", width=2), name=current_name)
            plot.setTitle(f"{current_name} ({note})")
            plot.addLegend(offset=(10, 10))
            self.layout.addWidget(plot, row, col)
            self.plots.append(plot)


class ControlPanel(QtWidgets.QScrollArea):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        container = QtWidgets.QWidget()
        self.setWidget(container)
        self.form = QtWidgets.QFormLayout(container)
        self.form.setContentsMargins(10, 10, 10, 10)
        self.inputs: Dict[str, QtWidgets.QWidget] = {}

        self.model_choice = QtWidgets.QComboBox()
        self.model_choice.addItems(list(MODEL_LIBRARY))
        self.model_choice.setCurrentText(DEFAULT_MODEL_NAME)
        self.form.addRow("Published model", self.model_choice)
        self.inputs["model_name"] = self.model_choice

        for key, label, minimum, maximum, step, decimals in KNOB_SPECS:
            spin = self.make_spin(minimum, maximum, step, decimals, 0.0)
            self.form.addRow(label, spin)
            self.inputs[key] = spin

        self.sim_spin = self.make_spin(100.0, 20000.0, 100.0, 1, DEFAULT_SIM_LENGTH_MS)
        self.form.addRow("Sim length (ms)", self.sim_spin)
        self.inputs["sim_length_ms"] = self.sim_spin

        self.freq_spin = self.make_spin(0.0, 20.0, 0.1, 2, 1.0)
        self.form.addRow("Stim frequency (Hz)", self.freq_spin)
        self.inputs["stim_frequency_hz"] = self.freq_spin

        self.duration_spin = self.make_spin(0.0, 20.0, 0.1, 2, DEFAULT_PACING["duration"])
        self.form.addRow("Stim duration (ms)", self.duration_spin)
        self.inputs["stim_duration_ms"] = self.duration_spin

        self.strength_spin = self.make_spin(0.0, 100.0, 0.1, 2, DEFAULT_PACING["level"])
        self.form.addRow("Stim strength (nA)", self.strength_spin)
        self.inputs["stim_strength_nA"] = self.strength_spin

        self.offset_spin = self.make_spin(0.0, 2000.0, 10.0, 1, DEFAULT_PACING["offset"])
        self.form.addRow("Stim offset (ms)", self.offset_spin)
        self.inputs["stim_offset_ms"] = self.offset_spin

        self.cm_spin = self.make_spin(5.0, 500.0, 5.0, 1, DEFAULT_CM_PF)
        self.form.addRow("Cm (pF)", self.cm_spin)
        self.inputs["cm_pf"] = self.cm_spin

        self.prepace_spin = self.make_int_spin(0, 500, 1, DEFAULT_PREPACE_BEATS)
        self.form.addRow("Prepace beats", self.prepace_spin)
        self.inputs["prepace_beats"] = self.prepace_spin

        self.load_model_defaults(DEFAULT_MODEL_NAME)

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

    def load_model_defaults(self, model_name: str) -> None:
        config = MODEL_LIBRARY[model_name]
        defaults = config["defaults"]
        run_defaults = config.get("run_defaults", {})
        available = set(config["knobs"])
        for key, _, _, _, _, _ in KNOB_SPECS:
            widget = self.inputs[key]
            assert isinstance(widget, QtWidgets.QDoubleSpinBox)
            if key in available:
                widget.setEnabled(True)
                widget.setValue(float(defaults.get(key, 0.0)))
            else:
                widget.setEnabled(False)
                widget.setValue(0.0)

        uses_stim = bool(config.get("external_stim", True))
        for widget in (self.freq_spin, self.duration_spin, self.strength_spin, self.offset_spin):
            widget.setEnabled(uses_stim)

        self.sim_spin.setValue(float(run_defaults.get("sim_length_ms", DEFAULT_SIM_LENGTH_MS)))
        self.freq_spin.setValue(float(run_defaults.get("stim_frequency_hz", 1.0)))
        self.duration_spin.setValue(float(run_defaults.get("stim_duration_ms", DEFAULT_PACING["duration"])))
        self.strength_spin.setValue(float(run_defaults.get("stim_strength_nA", DEFAULT_PACING["level"])))
        self.offset_spin.setValue(float(run_defaults.get("stim_offset_ms", DEFAULT_PACING["offset"])))
        self.cm_spin.setValue(float(run_defaults.get("cm_pf", DEFAULT_CM_PF)))
        self.prepace_spin.setValue(int(run_defaults.get("prepace_beats", DEFAULT_PREPACE_BEATS)))

    def reset(self) -> None:
        self.model_choice.setCurrentText(DEFAULT_MODEL_NAME)
        self.load_model_defaults(DEFAULT_MODEL_NAME)
        self.sim_spin.setValue(DEFAULT_SIM_LENGTH_MS)
        self.freq_spin.setValue(1.0)
        self.duration_spin.setValue(DEFAULT_PACING["duration"])
        self.strength_spin.setValue(DEFAULT_PACING["level"])
        self.offset_spin.setValue(DEFAULT_PACING["offset"])
        self.cm_spin.setValue(DEFAULT_CM_PF)
        self.prepace_spin.setValue(DEFAULT_PREPACE_BEATS)

    def values(self) -> Dict[str, float | int | str]:
        out: Dict[str, float | int | str] = {"model_name": self.model_choice.currentText()}
        for key, widget in self.inputs.items():
            if key == "model_name":
                continue
            if isinstance(widget, QtWidgets.QDoubleSpinBox):
                out[key] = float(widget.value())
            elif isinstance(widget, QtWidgets.QSpinBox):
                out[key] = int(widget.value())
        return out


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Cardiac AP - Published Model Viewer")
        self.resize(1700, 980)
        pg.setConfigOptions(antialias=True, foreground="k", background="w")

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)

        toolbar = QtWidgets.QHBoxLayout()
        self.run_button = QtWidgets.QPushButton("Run Simulation")
        self.reset_button = QtWidgets.QPushButton("Reset")
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setWordWrap(True)
        toolbar.addWidget(self.run_button)
        toolbar.addWidget(self.reset_button)
        toolbar.addWidget(self.status_label, stretch=1)
        layout.addLayout(toolbar)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        layout.addWidget(splitter, stretch=1)

        self.controls = ControlPanel()
        self.controls.setMinimumWidth(340)
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
        self.tabs.addTab(self.ap_plot, "Action Potential")

        self.current_grid = CurrentGrid()
        self.tabs.addTab(self.current_grid, "Ion Currents")

        self.diagnostics = QtWidgets.QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.tabs.addTab(self.diagnostics, "Diagnostics")

        self.run_button.clicked.connect(self.run_simulation)
        self.reset_button.clicked.connect(self.handle_reset)
        self.controls.model_choice.currentTextChanged.connect(self.handle_model_change)
        QtCore.QTimer.singleShot(0, self.run_simulation)

    def handle_model_change(self, model_name: str) -> None:
        self.controls.load_model_defaults(model_name)
        self.run_simulation()

    def handle_reset(self) -> None:
        self.controls.reset()
        self.run_simulation()

    def run_simulation(self) -> None:
        values = self.controls.values()
        model_name = str(values["model_name"])
        knob_values = {
            key: float(values[key])
            for key in MODEL_LIBRARY[model_name]["knobs"]
        }
        sim_length_ms = float(values["sim_length_ms"])
        stim_frequency_hz = float(values["stim_frequency_hz"])
        stim_duration_ms = float(values["stim_duration_ms"])
        stim_strength_nA = float(values["stim_strength_nA"])
        stim_offset_ms = float(values["stim_offset_ms"])
        cm_pf = float(values["cm_pf"])
        prepace_beats = int(values["prepace_beats"])

        self.status_label.setText("Running published model...")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        QtWidgets.QApplication.processEvents()
        try:
            result = simulate_selected_model(
                model_name=model_name,
                knob_values=knob_values,
                sim_length_ms=sim_length_ms,
                stim_frequency_hz=stim_frequency_hz,
                stim_duration_ms=stim_duration_ms,
                stim_strength_nA=stim_strength_nA,
                stim_offset_ms=stim_offset_ms,
                cm_pf=cm_pf,
                prepace_beats=prepace_beats,
            )
        except Exception as exc:
            self.status_label.setText(f"Simulation failed: {exc}")
            details = traceback.format_exc()
            self.diagnostics.setPlainText(details)
            QtWidgets.QMessageBox.critical(self, "Simulation error", details)
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        self.update_ap_plot(result)
        self.current_grid.update_from_result(result)
        self.update_diagnostics(result, knob_values)

        apd_text = f"{result.apd90_ms:.1f} ms" if result.apd90_ms is not None else "n/a"
        status_parts = [f"{result.model_name} APD90: {apd_text}"]
        if result.warning:
            status_parts.append(f"warning: {result.warning}")
        self.status_label.setText(" | ".join(status_parts))

    def update_ap_plot(self, result: SimulationResult) -> None:
        self.ap_plot.clear()
        self.ap_plot.addLegend(offset=(10, 10))
        if result.voltage_mv is not None:
            self.ap_plot.plot(
                result.time_ms,
                result.voltage_mv,
                pen=pg.mkPen("#0072B2", width=2),
                name=result.model_name,
            )
        self.ap_plot.setTitle(result.model_name)

    def update_diagnostics(self, result: SimulationResult, knob_values: Dict[str, float]) -> None:
        lines = [
            "PyQtGraph desktop AP viewer for published ventricular, atrial, and SAN models.",
            "",
            f"Published model: {result.model_name}",
            f"Source: {result.source}",
            MODEL_NOTE,
            "",
            "Applied parameter values:",
        ]
        for key, value in knob_values.items():
            lines.append(f"  {key}: {value}")
        lines.extend(["", f"Stimulus: {result.stim_info}", "Currents:"])
        if result.current_order:
            for name in result.current_order:
                if name in result.current_map:
                    lines.append(f"  {name:<5} -> {result.current_map[name]}")
        else:
            lines.append("  No ionic current traces are available for this backend.")
        lines.append("Knobs:")
        for key, qname in result.knob_map.items():
            lines.append(f"  {key:<6} -> {qname}")
        if result.warning:
            lines.extend(["", f"Warning: {result.warning}"])
        self.diagnostics.setPlainText("\n".join(lines))


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
