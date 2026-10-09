#!/usr/bin/env python3
"""Helpers for the Simone-Trancuccio hiPSC ventricular model."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

import numpy as np
from scipy.integrate import solve_ivp


HERE = Path(__file__).resolve().parent
PMR_MODEL = HERE / "pmr_d92_workspace" / "Simone_Trancuccio2025.m"
PMR_MAIN = HERE / "pmr_d92_workspace" / "Main_Simone_Trancuccio_2025.m"

SIMONE_DEFAULT_CM_PF = 98.7109
SIMONE_OUTPUT_NAMES = [
    "INa",
    "If",
    "ICaL",
    "Ito",
    "IKs",
    "IKr",
    "IK1",
    "INaCa",
    "INaK",
    "IpCa",
    "IbNa",
    "IbCa",
    "Irel",
    "Istim",
    "E_K",
    "E_Na",
    "INaL",
    "Iup",
]


@dataclass
class SimoneSimulation:
    time_ms: np.ndarray
    voltage_mv: np.ndarray
    currents_af: Dict[str, np.ndarray]
    current_order: List[str]
    warning: str | None = None


def _strip_inline_comment(line: str) -> str:
    if "%" not in line:
        return line.rstrip()
    return line.split("%", 1)[0].rstrip()


def _transform_statement(line: str) -> str:
    line = _strip_inline_comment(line).strip()
    if not line:
        return ""
    line = re.sub(r"\bexp\(", "np.exp(", line)
    line = re.sub(r"\blog\(", "np.log(", line)
    line = re.sub(r"\bsqrt\(", "np.sqrt(", line)
    line = re.sub(r"\bfloor\(", "np.floor(", line)
    line = line.replace("^", "**")
    line = line.replace(".*", "*")
    line = line.replace("./", "/")
    line = line.replace("~=", "!=")
    line = line.replace("&&", " and ")
    line = line.replace("||", " or ")
    line = re.sub(r"Y\((\d+)\)", lambda m: f"y[{int(m.group(1)) - 1}]", line)
    line = re.sub(r"dY\((\d+),\s*1\)", lambda m: f"dy[{int(m.group(1)) - 1}]", line)
    line = re.sub(r"\bdY\b", "dy", line)
    line = line.rstrip(";")
    if line.startswith("error("):
        return "raise ValueError" + line[len("error") :]
    if line.startswith("disp("):
        return "print" + line[len("disp") :]
    return line


def _transform_condition(line: str) -> str:
    line = line.strip()
    if line.startswith("if "):
        line = line[3:]
    return _transform_statement(line)


@lru_cache(maxsize=1)
def load_initial_state() -> np.ndarray:
    if not PMR_MAIN.is_file():
        raise FileNotFoundError(f"Missing Simone main file: {PMR_MAIN}")
    text = PMR_MAIN.read_text(encoding="utf-8")
    text = re.sub(r"\.\.\.\s*\n\s*", " ", text)
    match = re.search(r"X0=\[(.*?)\];", text, re.S)
    if match is None:
        raise ValueError("Could not parse Simone initial conditions from PMR main file.")
    values = [float(token) for token in match.group(1).split()]
    return np.asarray(values, dtype=float)


@lru_cache(maxsize=1)
def load_rhs():
    if not PMR_MODEL.is_file():
        raise FileNotFoundError(f"Missing Simone model file: {PMR_MODEL}")
    text = PMR_MODEL.read_text(encoding="utf-8")
    text = re.sub(r"\.\.\.\s*\n\s*", " ", text)
    body_lines: List[str] = []
    indent = 1
    for raw in text.splitlines():
        line = _strip_inline_comment(raw).strip()
        if not line or line.startswith("function "):
            continue
        if line == "else":
            indent -= 1
            body_lines.append("    " * indent + "else:")
            indent += 1
            continue
        if line == "end":
            indent -= 1
            continue
        if line.startswith("if "):
            body_lines.append("    " * indent + f"if {_transform_condition(line)}:")
            indent += 1
            continue
        py_line = _transform_statement(line)
        if py_line:
            body_lines.append("    " * indent + py_line)

    func_src = [
        "def simone_rhs(time, y, stimFlag, odeflag, i_stim_frequency, fractional_TS,",
        "               stim_amplitude_A=5.5e-10, stim_duration_s=0.005,",
        "               stim_offset_s=0.0, stim_end_s=1000.0, params=None):",
        "    import numpy as np",
        "    dy = np.zeros_like(y)",
        "    params = {} if params is None else params",
    ]
    for idx, line in enumerate(body_lines):
        stripped = line.strip()
        if stripped.startswith("i_stim_Amplitude"):
            body_lines[idx] = "    i_stim_Amplitude = stim_amplitude_A"
        elif stripped.startswith("i_stim_End"):
            body_lines[idx] = "    i_stim_End = stim_end_s"
        elif stripped.startswith("i_stim_PulseDuration"):
            body_lines[idx] = "    i_stim_PulseDuration = stim_duration_s"
        elif stripped.startswith("i_stim_Start"):
            body_lines[idx] = "    i_stim_Start = stim_offset_s"
        elif stripped.startswith("g_Na"):
            body_lines[idx] = "    g_Na = params.get('g_Na', 1.2176 * 6447.1896)"
        elif stripped.startswith("GNaLmax"):
            body_lines[idx] = "    GNaLmax = params.get('GNaLmax', 1.3021 * 2.3 * 7.5)"
        elif re.match(r"^bGCaL\s*=", stripped):
            body_lines[idx] = "    bGCaL = params.get('bGCaL', 1.0)"
        elif re.match(r"^g_f\s*=", stripped):
            body_lines[idx] = "    g_f = params.get('g_f', 0.62395 * 22.2763088)"
        elif re.match(r"^g_to\s*=", stripped):
            body_lines[idx] = "    g_to = params.get('g_to', 1.2913 * 29.9038)"
        elif re.match(r"^g_Ks\s*=", stripped):
            body_lines[idx] = "    g_Ks = params.get('g_Ks', 1.0726 * 2.041)"
        elif re.match(r"^g_Kr\s*=", stripped):
            body_lines[idx] = "    g_Kr = params.get('g_Kr', 1.9913 * 29.8667)"
        elif re.match(r"^g_K1\s*=", stripped):
            body_lines[idx] = "    g_K1 = params.get('g_K1', 0.50122 * 28.1492)"
        elif re.match(r"^kNaCa\s*=", stripped):
            body_lines[idx] = "    kNaCa = params.get('kNaCa', 0.66821 * 6514.47574)"
        elif re.match(r"^PNaK\s*=", stripped):
            body_lines[idx] = "    PNaK = params.get('PNaK', 1.3055 * 2.74240)"
    func_src.extend(body_lines)
    func_src.append("    return output")

    namespace = {"np": np}
    exec("\n".join(func_src), namespace)
    return namespace["simone_rhs"]


def _solve_segment(
    y0: np.ndarray,
    duration_s: float,
    t_eval: np.ndarray | None,
    stim_flag: int,
    frequency_hz: float,
    fractional_ts: float,
    stim_amplitude_A: float,
    stim_duration_s: float,
    stim_offset_s: float,
    params: Dict[str, float] | None,
) -> solve_ivp:
    rhs = load_rhs()
    frequency_hz = max(float(frequency_hz), 1.0)
    return solve_ivp(
        fun=lambda t, y: rhs(
            t,
            y,
            stim_flag,
            1,
            frequency_hz,
            fractional_ts,
            stim_amplitude_A,
            stim_duration_s,
            stim_offset_s,
            1.0e9,
            params,
        ),
        t_span=(0.0, float(duration_s)),
        y0=np.asarray(y0, dtype=float),
        method="BDF",
        t_eval=t_eval,
        rtol=1.0e-8,
        atol=1.0e-10,
        max_step=0.005,
    )


def simulate_simone_model(
    sim_length_ms: float,
    stim_frequency_hz: float,
    stim_duration_ms: float,
    stim_strength_nA: float,
    stim_offset_ms: float,
    prepace_beats: int,
    fractional_ts: float,
    params: Dict[str, float] | None = None,
) -> SimoneSimulation:
    y0 = load_initial_state().copy()
    stim_enabled = float(stim_frequency_hz) > 0 and float(stim_strength_nA) > 0 and float(stim_duration_ms) > 0
    stim_flag = 1 if stim_enabled else 0
    frequency_hz = max(float(stim_frequency_hz), 1.0)
    stim_amplitude_A = max(float(stim_strength_nA), 0.0) * 1.0e-9
    stim_duration_s = max(float(stim_duration_ms), 0.0) / 1000.0
    stim_offset_s = max(float(stim_offset_ms), 0.0) / 1000.0
    sim_length_s = max(float(sim_length_ms), 1.0) / 1000.0
    bcl_s = 1.0 / frequency_hz
    prepace_s = max(int(prepace_beats), 0) * bcl_s if stim_enabled else 0.0

    warning = None
    if prepace_s > 0:
        pre_sol = _solve_segment(
            y0,
            prepace_s,
            None,
            stim_flag,
            frequency_hz,
            fractional_ts,
            stim_amplitude_A,
            stim_duration_s,
            stim_offset_s,
            params,
        )
        if not pre_sol.success:
            raise RuntimeError(f"Simone hiPSC prepace failed: {pre_sol.message}")
        y0 = pre_sol.y[:, -1]

    nr_points = int(min(5000, max(400, round(float(sim_length_ms) / 0.2))))
    t_eval = np.linspace(0.0, sim_length_s, nr_points)
    sol = _solve_segment(
        y0,
        sim_length_s,
        t_eval,
        stim_flag,
        frequency_hz,
        fractional_ts,
        stim_amplitude_A,
        stim_duration_s,
        stim_offset_s,
        params,
    )
    if not sol.success:
        raise RuntimeError(f"Simone hiPSC simulation failed: {sol.message}")

    rhs = load_rhs()
    outputs = np.asarray(
        [
            rhs(
                float(t),
                sol.y[:, idx],
                stim_flag,
                0,
                frequency_hz,
                fractional_ts,
                stim_amplitude_A,
                stim_duration_s,
                stim_offset_s,
                1.0e9,
                params,
            )
            for idx, t in enumerate(sol.t)
        ],
        dtype=float,
    )
    output_map = {name: outputs[:, idx] for idx, name in enumerate(SIMONE_OUTPUT_NAMES)}
    currents_af = {
        "INa": output_map["INa"],
        "INaL": output_map["INaL"],
        "ICaL": output_map["ICaL"],
        "Ito": output_map["Ito"],
        "IKr": output_map["IKr"],
        "IKs": output_map["IKs"],
        "IK1": output_map["IK1"],
        "If": output_map["If"],
        "INaCa": output_map["INaCa"],
        "INaK": output_map["INaK"],
        "Istim": output_map["Istim"],
    }

    if np.max(sol.y[0]) - np.min(sol.y[0]) < 0.03:
        warning = "Simone hiPSC trace is nearly flat; try longer duration or spontaneous mode."

    return SimoneSimulation(
        time_ms=sol.t * 1000.0,
        voltage_mv=sol.y[0] * 1000.0,
        currents_af=currents_af,
        current_order=["INa", "INaL", "ICaL", "Ito", "IKr", "IKs", "IK1", "If", "INaCa", "INaK", "Istim"],
        warning=warning,
    )
