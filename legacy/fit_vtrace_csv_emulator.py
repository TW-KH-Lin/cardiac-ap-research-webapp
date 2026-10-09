#!/usr/bin/env python3
"""Fit voltage-like CSV traces with the local ventricular AP emulator."""

from __future__ import annotations

import argparse
import csv
import importlib
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import torch


HERE = Path(__file__).resolve().parent
DEFAULT_CSV = Path("/Users/kh_lin/Desktop/CM20/CM20_Summary_third_row_backcalc_APD80.csv")
DEFAULT_OUT_PREFIX = HERE / "cm20_vtrace_emulator_fit"
DEFAULT_LINKED_DIFFERENT = ("PCa_b", "GKr_b", "GKs_b", "GK1_b")
DEFAULT_PCA_PRIOR_LOW_FRAC = 0.25
DEFAULT_PCA_PRIOR_HIGH_FRAC = 1.75
DEFAULT_PRE_UPSTROKE_MS = 80.0
DEFAULT_POST_UPSTROKE_MS = 700.0
DEFAULT_TIME_OFFSET_CLAMP_MS = 120.0
CONDUCTANCE_ALIASES = {
    "gna": "GNa",
    "gnal": "GNaL_b",
    "gto": "Gto_b",
    "gkr": "GKr_b",
    "gks": "GKs_b",
    "gk1": "GK1_b",
    "gncx": "Gncx_b",
    "gnaca": "Gncx_b",
    "pnak": "Pnak_b",
    "gnak": "Pnak_b",
    "pca": "PCa_b",
    "gcal": "PCa_b",
}
EMULATOR_TO_MECHANISTIC_KNOB = {
    "GNa": "g_Na",
    "GNaL_b": "g_NaL",
    "Gto_b": "g_to",
    "GKr_b": "g_Kr",
    "GKs_b": "g_Ks",
    "GK1_b": "g_K1",
    "Gncx_b": "g_NaCa",
    "Pnak_b": "g_NaK",
    "PCa_b": "g_CaL",
}
DEFAULT_VALIDATION_MODEL = "ToR-ORd-dynCl ventricular"
_CARDIAC_AP_NAMESPACE: Optional[Dict[str, object]] = None


def detect_time_scale_to_ms(name: str, values: np.ndarray) -> float:
    lname = name.lower()
    if lname.endswith("_s") or lname == "time_s" or "[s]" in lname:
        return 1000.0
    if lname.endswith("_ms") or lname == "time_ms" or "[ms]" in lname:
        return 1.0
    total_span = float(values[-1] - values[0]) if values.size > 1 else 0.0
    return 1000.0 if total_span <= 10.0 else 1.0


def is_voltage_trace_column(name: str, time_name: str) -> bool:
    lname = name.strip().lower()
    time_lname = time_name.strip().lower()
    if not lname or lname == time_lname or lname.startswith("time"):
        return False
    return (
        "_v_" in lname
        or lname.endswith("_v")
        or lname.startswith("v_")
        or lname == "v"
        or "[v]" in lname
    )


def load_csv_columns(path: Path) -> Tuple[np.ndarray, Dict[str, np.ndarray], str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if not rows:
        raise ValueError(f"No rows found in {path}")

    fieldnames = list(rows[0].keys())
    time_name = next((name for name in fieldnames if name and name.lower().startswith("time")), fieldnames[0])
    time_raw = np.asarray([float(row[time_name]) for row in rows], dtype=float)
    time_ms = time_raw * detect_time_scale_to_ms(time_name, time_raw)

    trace_cols = [
        name for name in fieldnames
        if name and is_voltage_trace_column(name, time_name)
    ]
    if not trace_cols:
        raise ValueError(f"No V-trace columns found in {path}")

    traces = {
        name: np.asarray([float(row[name]) for row in rows], dtype=float)
        for name in trace_cols
    }
    return time_ms, traces, time_name


def normalize_trace_shape(values: np.ndarray, target_min_mv: float = -85.0, target_max_mv: float = 35.0) -> np.ndarray:
    vmin = float(np.min(values))
    vmax = float(np.max(values))
    if math.isclose(vmax, vmin):
        raise ValueError("Trace is flat; cannot normalize waveform shape.")
    unit = (values - vmin) / (vmax - vmin)
    return unit * (target_max_mv - target_min_mv) + target_min_mv


def affine_fit(pred_mv: np.ndarray, raw_values: np.ndarray) -> Tuple[float, float, np.ndarray]:
    x = np.column_stack([pred_mv, np.ones_like(pred_mv)])
    scale, offset = np.linalg.lstsq(x, raw_values, rcond=None)[0]
    mapped = scale * pred_mv + offset
    return float(scale), float(offset), mapped


def rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((a - b) ** 2)))


def phase_loss_weights(target_mv: np.ndarray) -> np.ndarray:
    weights = np.ones_like(target_mv, dtype=float)
    if target_mv.size < 5:
        return weights

    rest_mv = float(np.percentile(target_mv, 5.0))
    peak_idx = int(np.argmax(target_mv))
    peak_mv = float(target_mv[peak_idx])
    amplitude = peak_mv - rest_mv
    if amplitude <= 1e-6:
        return weights

    norm = (target_mv - rest_mv) / amplitude
    time_idx = np.arange(target_mv.size)

    plateau_mask = (time_idx >= peak_idx) & (norm >= 0.30)
    repol_mask = (time_idx >= peak_idx) & (norm >= 0.10) & (norm <= 0.70)
    terminal_repol_mask = (time_idx >= peak_idx) & (norm >= 0.02) & (norm < 0.20)

    weights[plateau_mask] = np.maximum(weights[plateau_mask], 2.0)
    weights[repol_mask] = np.maximum(weights[repol_mask], 4.0)
    weights[terminal_repol_mask] = np.maximum(weights[terminal_repol_mask], 3.0)
    return weights / float(np.mean(weights))


def downsample_time_series(time_ms: np.ndarray, values: np.ndarray, max_points: int) -> Tuple[np.ndarray, np.ndarray]:
    if max_points <= 0 or time_ms.size <= max_points:
        return time_ms, values
    indices = np.linspace(0, time_ms.size - 1, max_points).round().astype(int)
    indices = np.unique(indices)
    return time_ms[indices], values[indices]


def downsample_indices(size: int, max_points: int) -> np.ndarray:
    if max_points <= 0 or size <= max_points:
        return np.arange(size, dtype=int)
    indices = np.linspace(0, size - 1, max_points).round().astype(int)
    return np.unique(indices)


def detect_upstroke_index(values: np.ndarray) -> int:
    if values.size < 3:
        return 0
    return int(np.argmax(np.diff(values)))


def extract_aligned_beat_window(
    time_ms: np.ndarray,
    values: np.ndarray,
    pre_upstroke_ms: float,
    post_upstroke_ms: float,
) -> Tuple[np.ndarray, np.ndarray, float]:
    upstroke_index = detect_upstroke_index(values)
    upstroke_time_ms = float(time_ms[upstroke_index])
    keep = (time_ms >= upstroke_time_ms - float(pre_upstroke_ms)) & (time_ms <= upstroke_time_ms + float(post_upstroke_ms))
    if not np.any(keep):
        return time_ms.copy(), values.copy(), upstroke_time_ms
    return time_ms[keep] - upstroke_time_ms, values[keep], upstroke_time_ms


def canonicalize_conductance_name(token: str) -> str:
    stripped = token.strip()
    if not stripped:
        return ""
    key = stripped.lower().replace("_", "").replace("-", "")
    return CONDUCTANCE_ALIASES.get(key, stripped)


def split_requested_conductances(tokens: Sequence[str]) -> List[str]:
    names: List[str] = []
    for token in tokens:
        parts = [part.strip() for part in token.split(",")]
        names.extend(part for part in parts if part)
    return names


def resolve_conductance_names(emulator, requested: Sequence[str]) -> List[str]:
    available = [str(name) for name in emulator.max_conds_names]
    requested_names = split_requested_conductances(requested)
    if not requested_names:
        return []

    resolved: List[str] = []
    unknown: List[str] = []
    for token in requested_names:
        candidate = canonicalize_conductance_name(token)
        if candidate in available:
            if candidate not in resolved:
                resolved.append(candidate)
        else:
            unknown.append(token)

    if unknown:
        raise ValueError(
            "Unknown conductance name(s): "
            + ", ".join(unknown)
            + ". Available choices: "
            + ", ".join(available_short_names(emulator))
        )
    return resolved


def resolve_direction_constraints(emulator, constraints: Dict[str, str] | None) -> Dict[str, str]:
    if not constraints:
        return {}
    available = [str(name) for name in emulator.max_conds_names]
    resolved: Dict[str, str] = {}
    for raw_name, raw_direction in constraints.items():
        candidate = canonicalize_conductance_name(str(raw_name))
        if candidate not in available:
            raise ValueError(
                f"Unknown conductance name for direction constraint: {raw_name}. "
                f"Available choices: {', '.join(available_short_names(emulator))}"
            )
        direction = str(raw_direction).strip().lower()
        if direction not in {"up", "down", "free"}:
            raise ValueError(f"Unsupported direction constraint '{raw_direction}' for {raw_name}.")
        resolved[candidate] = direction
    return resolved


def resolve_mutant_change_limits(emulator, change_limits: Dict[str, float] | None) -> Dict[str, float]:
    if not change_limits:
        return {}
    available = [str(name) for name in emulator.max_conds_names]
    resolved: Dict[str, float] = {}
    for raw_name, raw_value in change_limits.items():
        candidate = canonicalize_conductance_name(str(raw_name))
        if candidate not in available:
            raise ValueError(
                f"Unknown conductance name for mutant change limit: {raw_name}. "
                f"Available choices: {', '.join(available_short_names(emulator))}"
            )
        resolved[candidate] = float(raw_value)
    return resolved


def resolve_fit_conductances(emulator, requested: Sequence[str] | None) -> List[str]:
    if requested is None:
        return [str(name) for name in emulator.max_conds_names]
    resolved = resolve_conductance_names(emulator, requested)
    if not resolved:
        raise ValueError("No conductances selected for fitting.")
    return resolved


def available_short_names(emulator) -> List[str]:
    reverse_alias = {
        "GNa": "GNa",
        "GNaL_b": "GNaL",
        "Gto_b": "Gto",
        "GKr_b": "GKr",
        "GKs_b": "GKs",
        "GK1_b": "GK1",
        "Gncx_b": "Gncx",
        "Pnak_b": "Pnak",
        "PCa_b": "PCa",
    }
    return [reverse_alias.get(str(name), str(name)) for name in emulator.max_conds_names]


def emulator_bounds_with_pca_prior(
    emulator,
    pca_prior_low_frac: float | None,
    pca_prior_high_frac: float | None,
    allow_training_extrapolation: bool = False,
) -> Tuple[np.ndarray, np.ndarray]:
    lower = np.asarray(emulator.max_conds_ranges[0], dtype=np.float32).copy()
    upper = np.asarray(emulator.max_conds_ranges[1], dtype=np.float32).copy()
    if allow_training_extrapolation:
        upper[:] = np.inf
    names = [str(name) for name in emulator.max_conds_names]
    if "PCa_b" in names and pca_prior_low_frac is not None and pca_prior_high_frac is not None:
        pca_idx = names.index("PCa_b")
        center = float(np.asarray(emulator.max_conds_center, dtype=np.float32)[pca_idx])
        lower[pca_idx] = max(lower[pca_idx], center * float(pca_prior_low_frac))
        upper[pca_idx] = min(upper[pca_idx], center * float(pca_prior_high_frac))
    return lower, upper


def clamp_param_vector_to_bounds(
    emulator,
    params: Sequence[float],
    use_pca_prior: bool,
    pca_prior_low_frac: float,
    pca_prior_high_frac: float,
    allow_training_extrapolation: bool = False,
) -> Tuple[np.ndarray, List[str], np.ndarray, np.ndarray]:
    params_np = np.asarray(params, dtype=np.float32).reshape(-1)
    if params_np.size != len(emulator.max_conds_names):
        raise ValueError("Conductance vector size does not match emulator conductance count.")
    lower_np, upper_np = emulator_bounds_with_pca_prior(
        emulator,
        pca_prior_low_frac if use_pca_prior else None,
        pca_prior_high_frac if use_pca_prior else None,
        allow_training_extrapolation=allow_training_extrapolation,
    )
    clipped = np.clip(params_np, lower_np, upper_np)
    clamp_messages: List[str] = []
    for name, original, adjusted, lower, upper in zip(emulator.max_conds_names, params_np, clipped, lower_np, upper_np):
        if original < lower or original > upper:
            clamp_messages.append(
                f"{name}: {float(original):.6g} -> {float(adjusted):.6g} within [{float(lower):.6g}, {float(upper):.6g}]"
            )
    return clipped, clamp_messages, lower_np, upper_np


def load_cardiac_ap_namespace() -> Dict[str, object]:
    global _CARDIAC_AP_NAMESPACE
    if _CARDIAC_AP_NAMESPACE is None:
        _CARDIAC_AP_NAMESPACE = importlib.import_module("runpy").run_path(str(HERE / "Cardiac AP.py"), run_name="cardiac_ap_fit_mod")
    return _CARDIAC_AP_NAMESPACE


def load_emulator():
    card_ns = load_cardiac_ap_namespace()
    emulator = card_ns["load_emulator_model"]()

    repo = HERE / "cardiomyocyte_emulator_repo"
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    importlib.invalidate_caches()
    inverse_module = importlib.import_module("cardiomyocyte_emulator.inverse")
    return emulator, inverse_module.match_Vm


def available_validation_models() -> List[str]:
    card_ns = load_cardiac_ap_namespace()
    library = card_ns["MODEL_LIBRARY"]
    names: List[str] = []
    for model_name, config in library.items():
        if str(config.get("backend", "myokit")) == "emulator":
            continue
        if "ventricular" in str(model_name).lower():
            names.append(str(model_name))
    return names


def validation_run_defaults(model_name: str) -> Dict[str, float | int]:
    card_ns = load_cardiac_ap_namespace()
    library = card_ns["MODEL_LIBRARY"]
    if model_name not in library:
        raise ValueError(f"Unknown validation model: {model_name}")
    config = library[model_name]
    default_pacing = dict(card_ns["DEFAULT_PACING"])
    run_defaults = dict(config.get("run_defaults", {}))
    external_stim = bool(config.get("external_stim", True))
    return {
        "sim_length_ms": float(run_defaults.get("sim_length_ms", card_ns["DEFAULT_SIM_LENGTH_MS"])),
        "stim_frequency_hz": float(run_defaults.get("stim_frequency_hz", 1.0 if external_stim else 0.0)),
        "stim_duration_ms": float(run_defaults.get("stim_duration_ms", default_pacing["duration"] if external_stim else 0.0)),
        "stim_strength_nA": float(run_defaults.get("stim_strength_nA", default_pacing["level"] if external_stim else 0.0)),
        "stim_offset_ms": float(run_defaults.get("stim_offset_ms", default_pacing["offset"] if external_stim else 0.0)),
        "cm_pf": float(run_defaults.get("cm_pf", card_ns["DEFAULT_CM_PF"])),
        "prepace_beats": int(run_defaults.get("prepace_beats", card_ns["DEFAULT_PREPACE_BEATS"] if external_stim else 0)),
    }


def mechanistic_knob_values_from_params(model_name: str, params: Sequence[float]) -> Tuple[Dict[str, float], List[str], List[str]]:
    card_ns = load_cardiac_ap_namespace()
    library = card_ns["MODEL_LIBRARY"]
    if model_name not in library:
        raise ValueError(f"Unknown validation model: {model_name}")
    config = library[model_name]
    knob_values = dict(config.get("defaults", {}))
    cond_names = [str(name) for name in load_emulator()[0].max_conds_names]
    mapped: List[str] = []
    ignored: List[str] = []
    for cond_name, value in zip(cond_names, params):
        knob_name = EMULATOR_TO_MECHANISTIC_KNOB.get(cond_name)
        if knob_name is None or knob_name not in config["knobs"]:
            ignored.append(cond_name)
            continue
        knob_values[knob_name] = float(value)
        mapped.append(f"{cond_name}->{knob_name}")
    knob_values = {name: float(value) for name, value in knob_values.items() if name in config["knobs"]}
    return knob_values, mapped, ignored


def simulate_mechanistic_validation(
    model_name: str,
    params: Sequence[float],
    overrides: Dict[str, float | int] | None = None,
):
    card_ns = load_cardiac_ap_namespace()
    simulate_selected_model = card_ns["simulate_selected_model"]
    knob_values, mapped, ignored = mechanistic_knob_values_from_params(model_name, params)
    settings = validation_run_defaults(model_name)
    if overrides:
        settings.update(overrides)
    result = simulate_selected_model(
        model_name=model_name,
        knob_values=knob_values,
        sim_length_ms=float(settings["sim_length_ms"]),
        stim_frequency_hz=float(settings["stim_frequency_hz"]),
        stim_duration_ms=float(settings["stim_duration_ms"]),
        stim_strength_nA=float(settings["stim_strength_nA"]),
        stim_offset_ms=float(settings["stim_offset_ms"]),
        cm_pf=float(settings["cm_pf"]),
        prepace_beats=int(settings["prepace_beats"]),
    )
    return {
        "result": result,
        "knob_values": knob_values,
        "mapped_params": mapped,
        "ignored_params": ignored,
        "settings": settings,
    }


def rest_candidate_grid() -> np.ndarray:
    return np.asarray([-90.0, -85.0, -80.0, -75.0, -70.0, -65.0, -60.0, -55.0, -50.0], dtype=float)


def fit_target_from_dff(
    raw_trace: np.ndarray,
    df_for_100mv: float,
    rest_df: float,
    rest_mv: float,
) -> np.ndarray:
    mv_per_df = 100.0 / float(df_for_100mv)
    return (raw_trace - rest_df) * mv_per_df + float(rest_mv)


def build_trace_target(
    raw_trace: np.ndarray,
    df_for_100mv: float | None,
    rest_mv: float,
) -> Tuple[str, np.ndarray, float, float, float]:
    if df_for_100mv is None:
        return "normalized-shape", normalize_trace_shape(raw_trace), math.nan, math.nan, math.nan
    estimated_rest_df = float(np.percentile(raw_trace, 5.0))
    return (
        "dff-calibrated",
        fit_target_from_dff(raw_trace, df_for_100mv, estimated_rest_df, rest_mv),
        estimated_rest_df,
        float(rest_mv),
        float(df_for_100mv),
    )


def fit_trace_with_emulator(
    emulator,
    time_ms: np.ndarray,
    raw_trace: np.ndarray,
    epochs: int,
    max_points: int,
    df_for_100mv: float | None,
    use_pca_prior: bool,
    pca_prior_low_frac: float,
    pca_prior_high_frac: float,
    pre_upstroke_ms: float,
    post_upstroke_ms: float,
    time_offset_clamp_ms: float,
    fit_param_names: Sequence[str] | None,
    allow_training_extrapolation: bool = False,
) -> Dict[str, object]:
    aligned_time_ms, aligned_raw, upstroke_time_ms = extract_aligned_beat_window(
        time_ms,
        raw_trace,
        pre_upstroke_ms=pre_upstroke_ms,
        post_upstroke_ms=post_upstroke_ms,
    )
    fit_time_ms, fit_raw = downsample_time_series(aligned_time_ms, aligned_raw, max_points)
    best_fit: Dict[str, object] | None = None
    lower_np, upper_np = emulator_bounds_with_pca_prior(
        emulator,
        pca_prior_low_frac if use_pca_prior else None,
        pca_prior_high_frac if use_pca_prior else None,
        allow_training_extrapolation=allow_training_extrapolation,
    )
    device = emulator.device
    lower_t = torch.from_numpy(lower_np).to(device)
    upper_t = torch.from_numpy(upper_np).to(device)
    center_t = torch.from_numpy(np.asarray(emulator.max_conds_center, dtype=np.float32)).to(device)
    resolved_fit_names = resolve_fit_conductances(emulator, fit_param_names)
    index_map = {str(name): idx for idx, name in enumerate(emulator.max_conds_names)}
    fit_indices = np.asarray([index_map[name] for name in resolved_fit_names], dtype=int)
    fixed_indices = np.asarray([idx for idx in range(len(index_map)) if idx not in set(int(i) for i in fit_indices)], dtype=int)
    fit_time_t = torch.from_numpy(fit_time_ms.astype(np.float32)).to(device)

    if df_for_100mv is None:
        candidate_targets = [("normalized-shape", normalize_trace_shape(fit_raw), math.nan, math.nan)]
    else:
        estimated_rest_df = float(np.percentile(fit_raw, 5.0))
        candidate_targets = [
            (
                "dff-calibrated",
                fit_target_from_dff(fit_raw, df_for_100mv, estimated_rest_df, rest_mv),
                estimated_rest_df,
                float(rest_mv),
            )
            for rest_mv in rest_candidate_grid()
        ]

    for mode_name, fit_target_mv, estimated_rest_df, assumed_rest_mv in candidate_targets:
        target_t = torch.from_numpy(fit_target_mv.astype(np.float32)).to(device)
        weights_t = torch.from_numpy(phase_loss_weights(fit_target_mv).astype(np.float32)).to(device)

        param_vec = center_t.clone().detach().requires_grad_(True)
        t_offset = torch.zeros(1, dtype=torch.float32, device=device, requires_grad=True)
        optimizer = torch.optim.Adam((param_vec, t_offset), lr=5e-2)

        best_loss = float("inf")
        best_params = param_vec.detach().clone()
        best_offset = t_offset.detach().clone()

        for _ in range(int(epochs)):
            optimizer.zero_grad()
            pred = emulator.forward_latent(fit_time_t + t_offset[0], param_vec[None])[0]
            loss = 0.5 * torch.mean(weights_t * (pred - target_t) ** 2)
            loss = loss + 2.5 * torch.mean((emulator.normalize_max_conds_ranges(param_vec[None]) - emulator.normalize_max_conds_ranges(center_t[None])) ** 2)
            loss = loss + 1e-4 * torch.mean(t_offset**2)
            loss.backward()
            optimizer.step()

            with torch.no_grad():
                param_vec[:] = param_vec.clamp(min=lower_t, max=upper_t)
                if fixed_indices.size:
                    param_vec[fixed_indices] = center_t[fixed_indices]
                t_offset[:] = t_offset.clamp(-float(time_offset_clamp_ms), float(time_offset_clamp_ms))

            loss_value = float(loss.detach().cpu().item())
            if loss_value < best_loss:
                best_loss = loss_value
                best_params = param_vec.detach().clone()
                best_offset = t_offset.detach().clone()

        with torch.no_grad():
            pred_mv = emulator.forward_latent(fit_time_t + best_offset[0], best_params[None])[0].detach().cpu().numpy()
        params = best_params.detach().cpu().numpy().astype(float).reshape(-1)
        pred_mv = np.asarray(pred_mv, dtype=float).reshape(-1)
        t_offset_ms = float(best_offset.detach().cpu().numpy().reshape(-1)[0])
        rmse_target = rmse(pred_mv, fit_target_mv)

        if df_for_100mv is None:
            scale_to_raw, offset_to_raw, pred_raw_units = affine_fit(pred_mv, fit_raw)
        else:
            mv_per_df = 100.0 / float(df_for_100mv)
            pred_raw_units = (pred_mv - assumed_rest_mv) / mv_per_df + estimated_rest_df
            scale_to_raw = 1.0 / mv_per_df
            offset_to_raw = estimated_rest_df - assumed_rest_mv / mv_per_df

        fit = {
            "mode": mode_name,
            "fit_time_ms": fit_time_ms,
            "fit_raw": fit_raw,
            "fit_target_mv": fit_target_mv,
            "pred_mv": pred_mv,
            "pred_raw_units": pred_raw_units,
            "t_offset_ms": t_offset_ms,
            "rmse_target_mv": rmse_target,
            "rmse_raw_units": rmse(pred_raw_units, fit_raw),
            "scale_to_raw": scale_to_raw,
            "offset_to_raw": offset_to_raw,
            "params": params,
            "estimated_rest_df": estimated_rest_df,
            "assumed_rest_mv": assumed_rest_mv,
            "df_for_100mv": df_for_100mv if df_for_100mv is not None else math.nan,
            "pca_prior_enabled": use_pca_prior,
            "pca_prior_low_frac": pca_prior_low_frac,
            "pca_prior_high_frac": pca_prior_high_frac,
            "training_extrapolation_enabled": allow_training_extrapolation,
            "upstroke_time_ms": upstroke_time_ms,
            "pre_upstroke_ms": pre_upstroke_ms,
            "post_upstroke_ms": post_upstroke_ms,
            "time_offset_clamp_ms": time_offset_clamp_ms,
            "fitted_param_names": ",".join(resolved_fit_names),
            "fixed_param_names": ",".join(
                str(name) for idx, name in enumerate(emulator.max_conds_names) if idx in set(int(i) for i in fixed_indices)
            ),
        }
        if best_fit is None or float(fit["rmse_target_mv"]) < float(best_fit["rmse_target_mv"]):
            best_fit = fit

    assert best_fit is not None
    return best_fit


def fit_trace_from_reference_params(
    emulator,
    time_ms: np.ndarray,
    raw_trace: np.ndarray,
    epochs: int,
    max_points: int,
    df_for_100mv: float | None,
    rest_mv: float,
    use_pca_prior: bool,
    pca_prior_low_frac: float,
    pca_prior_high_frac: float,
    pre_upstroke_ms: float,
    post_upstroke_ms: float,
    time_offset_clamp_ms: float,
    free_param_names: Sequence[str],
    initial_params: np.ndarray,
    prior_params: np.ndarray,
    fixed_param_values: np.ndarray,
    mode_prefix: str,
    extra_metadata: Dict[str, object] | None = None,
    lower_override: np.ndarray | None = None,
    upper_override: np.ndarray | None = None,
    allow_training_extrapolation: bool = False,
) -> Dict[str, object]:
    aligned_time_ms, aligned_raw, upstroke_time_ms = extract_aligned_beat_window(
        time_ms,
        raw_trace,
        pre_upstroke_ms=pre_upstroke_ms,
        post_upstroke_ms=post_upstroke_ms,
    )
    fit_time_ms, fit_raw = downsample_time_series(aligned_time_ms, aligned_raw, max_points)
    mode_name, fit_target_mv, estimated_rest_df, assumed_rest_mv, df_scale = build_trace_target(fit_raw, df_for_100mv, rest_mv)
    weights = phase_loss_weights(fit_target_mv).astype(np.float32)

    lower_np, upper_np = emulator_bounds_with_pca_prior(
        emulator,
        pca_prior_low_frac if use_pca_prior else None,
        pca_prior_high_frac if use_pca_prior else None,
        allow_training_extrapolation=allow_training_extrapolation,
    )
    if lower_override is not None:
        lower_np = np.maximum(lower_np, np.asarray(lower_override, dtype=np.float32))
    if upper_override is not None:
        upper_np = np.minimum(upper_np, np.asarray(upper_override, dtype=np.float32))

    resolved_free_names = resolve_conductance_names(emulator, free_param_names)
    index_map = {str(name): idx for idx, name in enumerate(emulator.max_conds_names)}
    free_indices = np.asarray([index_map[name] for name in resolved_free_names], dtype=int)
    free_index_set = set(int(idx) for idx in free_indices)
    fixed_indices = np.asarray([idx for idx in range(len(index_map)) if idx not in free_index_set], dtype=int)

    device = emulator.device
    fit_time_t = torch.from_numpy(fit_time_ms.astype(np.float32)).to(device)
    target_t = torch.from_numpy(fit_target_mv.astype(np.float32)).to(device)
    weights_t = torch.from_numpy(weights).to(device)
    lower_t = torch.from_numpy(lower_np).to(device)
    upper_t = torch.from_numpy(upper_np).to(device)
    initial_t = torch.from_numpy(np.asarray(initial_params, dtype=np.float32)).to(device)
    prior_t = torch.from_numpy(np.asarray(prior_params, dtype=np.float32)).to(device)
    fixed_t = torch.from_numpy(np.asarray(fixed_param_values, dtype=np.float32)).to(device)

    param_vec = initial_t.clone().detach().requires_grad_(True)
    t_offset = torch.zeros(1, dtype=torch.float32, device=device, requires_grad=True)
    optimizer = torch.optim.Adam((param_vec, t_offset), lr=5e-2)

    best_loss = float("inf")
    best_params = param_vec.detach().clone()
    best_offset = t_offset.detach().clone()

    for _ in range(int(epochs)):
        optimizer.zero_grad()
        pred = emulator.forward_latent(fit_time_t + t_offset[0], param_vec[None])[0]
        loss = 0.5 * torch.mean(weights_t * (pred - target_t) ** 2)
        loss = loss + 2.5 * torch.mean(
            (emulator.normalize_max_conds_ranges(param_vec[None]) - emulator.normalize_max_conds_ranges(prior_t[None])) ** 2
        )
        loss = loss + 1e-4 * torch.mean(t_offset**2)
        loss.backward()
        optimizer.step()

        with torch.no_grad():
            param_vec[:] = param_vec.clamp(min=lower_t, max=upper_t)
            if fixed_indices.size:
                param_vec[fixed_indices] = fixed_t[fixed_indices]
            t_offset[:] = t_offset.clamp(-float(time_offset_clamp_ms), float(time_offset_clamp_ms))

        loss_value = float(loss.detach().cpu().item())
        if loss_value < best_loss:
            best_loss = loss_value
            best_params = param_vec.detach().clone()
            best_offset = t_offset.detach().clone()

    with torch.no_grad():
        pred_mv = emulator.forward_latent(fit_time_t + best_offset[0], best_params[None])[0].detach().cpu().numpy()
    params = best_params.detach().cpu().numpy().astype(float).reshape(-1)
    pred_mv = np.asarray(pred_mv, dtype=float).reshape(-1)
    t_offset_ms = float(best_offset.detach().cpu().numpy().reshape(-1)[0])

    if df_for_100mv is None:
        scale_to_raw, offset_to_raw, pred_raw_units = affine_fit(pred_mv, fit_raw)
    else:
        mv_per_df = 100.0 / float(df_scale)
        pred_raw_units = (pred_mv - assumed_rest_mv) / mv_per_df + estimated_rest_df
        scale_to_raw = 1.0 / mv_per_df
        offset_to_raw = estimated_rest_df - assumed_rest_mv / mv_per_df

    fit = {
        "mode": f"{mode_prefix}-{mode_name}",
        "fit_time_ms": fit_time_ms,
        "fit_raw": fit_raw,
        "fit_target_mv": fit_target_mv,
        "pred_mv": pred_mv,
        "pred_raw_units": pred_raw_units,
        "t_offset_ms": t_offset_ms,
        "rmse_target_mv": rmse(pred_mv, fit_target_mv),
        "rmse_raw_units": rmse(pred_raw_units, fit_raw),
        "scale_to_raw": scale_to_raw,
        "offset_to_raw": offset_to_raw,
        "params": params,
        "estimated_rest_df": estimated_rest_df,
        "assumed_rest_mv": assumed_rest_mv,
        "df_for_100mv": df_scale,
        "pca_prior_enabled": use_pca_prior,
        "pca_prior_low_frac": pca_prior_low_frac,
        "pca_prior_high_frac": pca_prior_high_frac,
        "training_extrapolation_enabled": allow_training_extrapolation,
        "upstroke_time_ms": upstroke_time_ms,
        "pre_upstroke_ms": pre_upstroke_ms,
        "post_upstroke_ms": post_upstroke_ms,
        "time_offset_clamp_ms": time_offset_clamp_ms,
        "fitted_param_names": ",".join(resolved_free_names),
        "fixed_param_names": ",".join(
            str(name) for idx, name in enumerate(emulator.max_conds_names) if idx in set(int(i) for i in fixed_indices)
        ),
    }
    if extra_metadata:
        fit.update(extra_metadata)
    return fit


def fit_reference_then_mutant_with_emulator(
    emulator,
    time_ms: np.ndarray,
    raw_traces: Dict[str, np.ndarray],
    epochs: int,
    max_points: int,
    df_for_100mv: float | None,
    fit_param_names: Sequence[str] | None,
    different_param_names: Sequence[str],
    rest_mv: float,
    use_pca_prior: bool,
    pca_prior_low_frac: float,
    pca_prior_high_frac: float,
    pre_upstroke_ms: float,
    post_upstroke_ms: float,
    time_offset_clamp_ms: float,
    direction_constraints: Dict[str, str] | None = None,
    mutant_change_limits_pct: Dict[str, float] | None = None,
    reference_locked_params: Sequence[float] | None = None,
    allow_training_extrapolation: bool = False,
) -> Dict[str, Dict[str, object]]:
    trace_names = list(raw_traces.keys())
    if len(trace_names) != 2:
        raise ValueError("Reference -> mutant fitting requires exactly two selected traces.")

    reference_name, mutant_name = trace_names
    resolved_fit_names = resolve_fit_conductances(emulator, fit_param_names)
    resolved_change_limits = resolve_mutant_change_limits(emulator, mutant_change_limits_pct)
    if resolved_change_limits:
        resolved_different = list(resolved_change_limits.keys())
        resolved_directions = {
            name: ("up" if value > 0 else "down" if value < 0 else "free")
            for name, value in resolved_change_limits.items()
            if abs(value) > 1e-9
        }
    else:
        resolved_different = resolve_conductance_names(emulator, different_param_names)
        resolved_directions = resolve_direction_constraints(emulator, direction_constraints)
    if not set(resolved_different).issubset(set(resolved_fit_names)):
        raise ValueError("Conductances allowed to change in mutant must also be selected for fitting in the reference trace.")

    center = np.asarray(emulator.max_conds_center, dtype=np.float32).copy()
    shared_names = [name for name in resolved_fit_names if name not in set(resolved_different)]
    direction_text = ",".join(f"{name}:{resolved_directions.get(name, 'free')}" for name in resolved_different)
    linked_name_text = ",".join(resolved_different)
    change_limit_text = ",".join(f"{name}:{value:+.1f}%" for name, value in resolved_change_limits.items())
    common_meta = {
        "fit_strategy": "reference_then_mutant",
        "reference_trace_name": reference_name,
        "mutant_trace_name": mutant_name,
        "linked_different_params": linked_name_text,
        "mut_direction_constraints": direction_text,
        "mutant_change_limits_pct": change_limit_text,
        "shared_param_names": ",".join(shared_names),
        "reference_lock_active": bool(reference_locked_params is not None),
        "training_extrapolation_enabled": bool(allow_training_extrapolation),
    }

    clamp_messages: List[str] = []
    if reference_locked_params is not None:
        locked_params, clamp_messages, _, _ = clamp_param_vector_to_bounds(
            emulator,
            reference_locked_params,
            use_pca_prior=use_pca_prior,
            pca_prior_low_frac=pca_prior_low_frac,
            pca_prior_high_frac=pca_prior_high_frac,
            allow_training_extrapolation=allow_training_extrapolation,
        )
        common_meta["reference_lock_clamped"] = bool(clamp_messages)
        common_meta["reference_lock_clamp_summary"] = " | ".join(clamp_messages)
        reference_fit = fit_trace_from_reference_params(
            emulator=emulator,
            time_ms=time_ms,
            raw_trace=raw_traces[reference_name],
            epochs=epochs,
            max_points=max_points,
            df_for_100mv=df_for_100mv,
            rest_mv=rest_mv,
            use_pca_prior=use_pca_prior,
            pca_prior_low_frac=pca_prior_low_frac,
            pca_prior_high_frac=pca_prior_high_frac,
            pre_upstroke_ms=pre_upstroke_ms,
            post_upstroke_ms=post_upstroke_ms,
            time_offset_clamp_ms=time_offset_clamp_ms,
            free_param_names=(),
            initial_params=locked_params,
            prior_params=locked_params,
            fixed_param_values=locked_params,
            mode_prefix="locked-reference",
            extra_metadata=common_meta,
            allow_training_extrapolation=allow_training_extrapolation,
        )
    else:
        reference_fit = fit_trace_from_reference_params(
            emulator=emulator,
            time_ms=time_ms,
            raw_trace=raw_traces[reference_name],
            epochs=epochs,
            max_points=max_points,
            df_for_100mv=df_for_100mv,
            rest_mv=rest_mv,
            use_pca_prior=use_pca_prior,
            pca_prior_low_frac=pca_prior_low_frac,
            pca_prior_high_frac=pca_prior_high_frac,
            pre_upstroke_ms=pre_upstroke_ms,
            post_upstroke_ms=post_upstroke_ms,
            time_offset_clamp_ms=time_offset_clamp_ms,
            free_param_names=resolved_fit_names,
            initial_params=center,
            prior_params=center,
            fixed_param_values=center,
            mode_prefix="reference",
            extra_metadata=common_meta,
            allow_training_extrapolation=allow_training_extrapolation,
        )
        common_meta["reference_lock_clamped"] = False
        common_meta["reference_lock_clamp_summary"] = ""
    reference_params = np.asarray(reference_fit["params"], dtype=np.float32).copy()

    lower_override = np.full_like(reference_params, -np.inf, dtype=np.float32)
    upper_override = np.full_like(reference_params, np.inf, dtype=np.float32)
    index_map = {str(name): idx for idx, name in enumerate(emulator.max_conds_names)}
    for name in resolved_different:
        idx = index_map[name]
        if name in resolved_change_limits:
            target_value = reference_params[idx] * (1.0 + resolved_change_limits[name] / 100.0)
            lower_override[idx] = min(reference_params[idx], target_value)
            upper_override[idx] = max(reference_params[idx], target_value)
            continue
        direction = resolved_directions.get(name, "free")
        if direction == "up":
            lower_override[idx] = reference_params[idx]
        elif direction == "down":
            upper_override[idx] = reference_params[idx]

    mutant_meta = dict(common_meta)
    mutant_meta["reference_fitted_param_names"] = ",".join(resolved_fit_names)
    mutant_fit = fit_trace_from_reference_params(
        emulator=emulator,
        time_ms=time_ms,
        raw_trace=raw_traces[mutant_name],
        epochs=epochs,
        max_points=max_points,
        df_for_100mv=df_for_100mv,
        rest_mv=rest_mv,
        use_pca_prior=use_pca_prior,
        pca_prior_low_frac=pca_prior_low_frac,
        pca_prior_high_frac=pca_prior_high_frac,
        pre_upstroke_ms=pre_upstroke_ms,
        post_upstroke_ms=post_upstroke_ms,
        time_offset_clamp_ms=time_offset_clamp_ms,
        free_param_names=resolved_different,
        initial_params=reference_params,
        prior_params=reference_params,
        fixed_param_values=reference_params,
        mode_prefix="mutant-from-reference",
        extra_metadata=mutant_meta,
        lower_override=lower_override,
        upper_override=upper_override,
        allow_training_extrapolation=allow_training_extrapolation,
    )
    if clamp_messages:
        mutant_fit["reference_lock_clamped"] = True
        mutant_fit["reference_lock_clamp_summary"] = " | ".join(clamp_messages)

    return {
        reference_name: reference_fit,
        mutant_name: mutant_fit,
    }


def fit_linked_traces_with_emulator(
    emulator,
    time_ms: np.ndarray,
    raw_traces: Dict[str, np.ndarray],
    epochs: int,
    max_points: int,
    df_for_100mv: float | None,
    fit_param_names: Sequence[str] | None,
    different_param_names: Sequence[str],
    rest_mv: float,
    use_pca_prior: bool,
    pca_prior_low_frac: float,
    pca_prior_high_frac: float,
    pre_upstroke_ms: float,
    post_upstroke_ms: float,
    time_offset_clamp_ms: float,
    direction_constraints: Dict[str, str] | None = None,
) -> Dict[str, Dict[str, object]]:
    trace_names = list(raw_traces.keys())
    if len(trace_names) < 2:
        raise ValueError("Linked fitting requires at least two traces.")

    resolved_fit_names = resolve_fit_conductances(emulator, fit_param_names)
    resolved_names = resolve_conductance_names(emulator, different_param_names)
    if not resolved_names and len(trace_names) >= 2:
        resolved_names = []
    resolved_directions = resolve_direction_constraints(emulator, direction_constraints)
    if resolved_directions and len(trace_names) != 2:
        raise ValueError("Mut up/down constraints currently require exactly two selected traces.")
    if not set(resolved_names).issubset(set(resolved_fit_names)):
        raise ValueError("Conductances allowed to differ in mutant must also be selected for fitting.")

    index_map = {str(name): idx for idx, name in enumerate(emulator.max_conds_names)}
    fit_indices = np.asarray([index_map[name] for name in resolved_fit_names], dtype=int)
    different_indices = np.asarray([index_map[name] for name in resolved_names], dtype=int)
    different_index_set = set(int(idx) for idx in different_indices)
    fit_index_set = set(int(idx) for idx in fit_indices)
    fixed_indices = np.asarray([idx for idx in range(len(index_map)) if idx not in fit_index_set], dtype=int)
    different_name_to_pos = {name: pos for pos, name in enumerate(resolved_names)}
    up_positions = [different_name_to_pos[name] for name, direction in resolved_directions.items() if direction == "up" and name in different_name_to_pos]
    down_positions = [different_name_to_pos[name] for name, direction in resolved_directions.items() if direction == "down" and name in different_name_to_pos]

    aligned_times: List[np.ndarray] = []
    aligned_raws: List[np.ndarray] = []
    upstroke_times: List[float] = []
    min_len: Optional[int] = None
    for name in trace_names:
        aligned_time, aligned_raw, upstroke_time_ms = extract_aligned_beat_window(
            time_ms,
            raw_traces[name],
            pre_upstroke_ms=pre_upstroke_ms,
            post_upstroke_ms=post_upstroke_ms,
        )
        aligned_times.append(aligned_time)
        aligned_raws.append(aligned_raw)
        upstroke_times.append(upstroke_time_ms)
        min_len = len(aligned_time) if min_len is None else min(min_len, len(aligned_time))

    assert min_len is not None
    aligned_times = [arr[:min_len] for arr in aligned_times]
    aligned_raws = [arr[:min_len] for arr in aligned_raws]

    indices = downsample_indices(min_len, max_points)
    fit_time_ms = aligned_times[0][indices]
    fit_raw_list = [arr[indices] for arr in aligned_raws]

    target_info = [build_trace_target(raw, df_for_100mv, rest_mv) for raw in fit_raw_list]
    fit_targets = np.stack([info[1] for info in target_info]).astype(np.float32)
    fit_weights = np.stack([phase_loss_weights(info[1]) for info in target_info]).astype(np.float32)

    device = emulator.device
    t_t = torch.from_numpy(fit_time_ms.astype(np.float32)).to(device)
    target_t = torch.from_numpy(fit_targets).to(device)
    weight_t = torch.from_numpy(fit_weights).to(device)
    center = torch.from_numpy(np.asarray(emulator.max_conds_center, dtype=np.float32)).to(device)
    lower_np, upper_np = emulator_bounds_with_pca_prior(
        emulator,
        pca_prior_low_frac if use_pca_prior else None,
        pca_prior_high_frac if use_pca_prior else None,
    )
    lower = torch.from_numpy(lower_np).to(device)
    upper = torch.from_numpy(upper_np).to(device)

    shared = center.clone().detach().requires_grad_(True)
    varying = torch.tile(center[different_indices][None], (len(trace_names), 1)).detach().clone().requires_grad_(True)
    t_offsets = torch.zeros(len(trace_names), dtype=torch.float32, device=device, requires_grad=True)

    optimizer = torch.optim.Adam((shared, varying, t_offsets), lr=5e-2)
    prior_full = torch.tile(center[None], (len(trace_names), 1))

    best_loss = float("inf")
    best_shared = shared.detach().clone()
    best_varying = varying.detach().clone()
    best_offsets = t_offsets.detach().clone()

    for _ in range(int(epochs)):
        optimizer.zero_grad()

        full = torch.tile(shared[None], (len(trace_names), 1))
        full[:, different_indices] = varying

        preds = []
        for trace_index in range(len(trace_names)):
            preds.append(emulator.forward_latent(t_t + t_offsets[trace_index], full[trace_index : trace_index + 1])[0])
        pred_t = torch.stack(preds, dim=0)

        loss = 0.5 * torch.mean(weight_t * (pred_t - target_t) ** 2)
        loss = loss + 2.5 * torch.mean((emulator.normalize_max_conds_ranges(full) - emulator.normalize_max_conds_ranges(prior_full)) ** 2)
        loss = loss + 1e-4 * torch.mean(t_offsets**2)

        loss.backward()
        optimizer.step()

        with torch.no_grad():
            shared[:] = shared.clamp(min=lower, max=upper)
            if fixed_indices.size:
                shared[fixed_indices] = center[fixed_indices]
            if different_indices.size:
                shared[different_indices] = center[different_indices]
            varying[:] = varying.clamp(min=lower[different_indices], max=upper[different_indices])
            if len(trace_names) == 2:
                for pos in up_positions:
                    varying[1, pos] = torch.maximum(varying[1, pos], varying[0, pos])
                for pos in down_positions:
                    varying[1, pos] = torch.minimum(varying[1, pos], varying[0, pos])
            t_offsets[:] = t_offsets.clamp(-float(time_offset_clamp_ms), float(time_offset_clamp_ms))

        loss_value = float(loss.detach().cpu().item())
        if loss_value < best_loss:
            best_loss = loss_value
            best_shared = shared.detach().clone()
            best_varying = varying.detach().clone()
            best_offsets = t_offsets.detach().clone()

    with torch.no_grad():
        full = torch.tile(best_shared[None], (len(trace_names), 1))
        full[:, different_indices] = best_varying
        preds = []
        for trace_index in range(len(trace_names)):
            preds.append(emulator.forward_latent(t_t + best_offsets[trace_index], full[trace_index : trace_index + 1])[0])
        pred_matrix = torch.stack(preds, dim=0).detach().cpu().numpy()
        full_params = full.detach().cpu().numpy()
        t_offset_vals = best_offsets.detach().cpu().numpy()

    linked_name_text = ",".join(resolved_names)
    direction_text = ",".join(f"{name}:{resolved_directions.get(name, 'free')}" for name in resolved_names)
    results: Dict[str, Dict[str, object]] = {}
    for trace_index, trace_name in enumerate(trace_names):
        mode_name, fit_target_mv, estimated_rest_df, assumed_rest_mv, df_scale = target_info[trace_index]
        pred_mv = pred_matrix[trace_index]
        fit_raw = fit_raw_list[trace_index]
        if df_for_100mv is None:
            scale_to_raw, offset_to_raw, pred_raw_units = affine_fit(pred_mv, fit_raw)
        else:
            mv_per_df = 100.0 / float(df_scale)
            pred_raw_units = (pred_mv - assumed_rest_mv) / mv_per_df + estimated_rest_df
            scale_to_raw = 1.0 / mv_per_df
            offset_to_raw = estimated_rest_df - assumed_rest_mv / mv_per_df

        results[trace_name] = {
            "mode": f"linked-{mode_name}",
            "fit_time_ms": fit_time_ms,
            "fit_raw": fit_raw,
            "fit_target_mv": fit_target_mv,
            "pred_mv": pred_mv,
            "pred_raw_units": pred_raw_units,
            "t_offset_ms": float(t_offset_vals[trace_index]),
            "rmse_target_mv": rmse(pred_mv, fit_target_mv),
            "rmse_raw_units": rmse(pred_raw_units, fit_raw),
            "scale_to_raw": scale_to_raw,
            "offset_to_raw": offset_to_raw,
            "params": full_params[trace_index],
            "estimated_rest_df": estimated_rest_df,
            "assumed_rest_mv": assumed_rest_mv,
            "df_for_100mv": df_scale,
            "pca_prior_enabled": use_pca_prior,
            "pca_prior_low_frac": pca_prior_low_frac,
            "pca_prior_high_frac": pca_prior_high_frac,
            "upstroke_time_ms": upstroke_times[trace_index],
            "pre_upstroke_ms": pre_upstroke_ms,
            "post_upstroke_ms": post_upstroke_ms,
            "time_offset_clamp_ms": time_offset_clamp_ms,
            "fitted_param_names": ",".join(resolved_fit_names),
            "fixed_param_names": ",".join(
                str(name) for idx, name in enumerate(emulator.max_conds_names) if idx in set(int(i) for i in fixed_indices)
            ),
            "linked_different_params": linked_name_text,
            "mut_direction_constraints": direction_text,
            "shared_param_names": ",".join(
                str(name) for idx, name in enumerate(emulator.max_conds_names) if idx in fit_index_set and idx not in different_index_set
            ),
        }
    return results


def write_summary(path: Path, emulator, results: Dict[str, Dict[str, object]]) -> None:
    fieldnames = [
        "trace_name",
        "mode",
        "rmse_target_mv",
        "rmse_raw_units",
        "t_offset_ms",
        "scale_to_raw",
        "offset_to_raw",
        "estimated_rest_df",
        "assumed_rest_mv",
        "df_for_100mv",
        "pca_prior_enabled",
        "pca_prior_low_frac",
        "pca_prior_high_frac",
        "training_extrapolation_enabled",
        "upstroke_time_ms",
        "pre_upstroke_ms",
        "post_upstroke_ms",
        "time_offset_clamp_ms",
        "fitted_param_names",
        "fixed_param_names",
        "linked_different_params",
        "mut_direction_constraints",
        "mutant_change_limits_pct",
        "shared_param_names",
        "fit_strategy",
        "reference_trace_name",
        "mutant_trace_name",
        "reference_fitted_param_names",
        "reference_lock_active",
    ] + [str(name) for name in emulator.max_conds_names]

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for trace_name, fit in results.items():
            row = {
                "trace_name": trace_name,
                "mode": fit["mode"],
                "rmse_target_mv": fit["rmse_target_mv"],
                "rmse_raw_units": fit["rmse_raw_units"],
                "t_offset_ms": fit["t_offset_ms"],
                "scale_to_raw": fit["scale_to_raw"],
                "offset_to_raw": fit["offset_to_raw"],
                "estimated_rest_df": fit["estimated_rest_df"],
                "assumed_rest_mv": fit["assumed_rest_mv"],
                "df_for_100mv": fit["df_for_100mv"],
                "pca_prior_enabled": fit.get("pca_prior_enabled", ""),
                "pca_prior_low_frac": fit.get("pca_prior_low_frac", ""),
                "pca_prior_high_frac": fit.get("pca_prior_high_frac", ""),
                "training_extrapolation_enabled": fit.get("training_extrapolation_enabled", ""),
                "upstroke_time_ms": fit.get("upstroke_time_ms", ""),
                "pre_upstroke_ms": fit.get("pre_upstroke_ms", ""),
                "post_upstroke_ms": fit.get("post_upstroke_ms", ""),
                "time_offset_clamp_ms": fit.get("time_offset_clamp_ms", ""),
                "fitted_param_names": fit.get("fitted_param_names", ""),
                "fixed_param_names": fit.get("fixed_param_names", ""),
                "linked_different_params": fit.get("linked_different_params", ""),
                "mut_direction_constraints": fit.get("mut_direction_constraints", ""),
                "mutant_change_limits_pct": fit.get("mutant_change_limits_pct", ""),
                "shared_param_names": fit.get("shared_param_names", ""),
                "fit_strategy": fit.get("fit_strategy", ""),
                "reference_trace_name": fit.get("reference_trace_name", ""),
                "mutant_trace_name": fit.get("mutant_trace_name", ""),
                "reference_fitted_param_names": fit.get("reference_fitted_param_names", ""),
                "reference_lock_active": fit.get("reference_lock_active", ""),
            }
            for name, value in zip(emulator.max_conds_names, fit["params"]):
                row[str(name)] = value
            writer.writerow(row)


def write_traces(path: Path, results: Dict[str, Dict[str, object]]) -> None:
    trace_names = list(results.keys())
    max_len = max(len(fit["fit_time_ms"]) for fit in results.values())

    fieldnames: List[str] = ["sample_index"]
    for trace_name in trace_names:
        fieldnames.extend([
            f"{trace_name}__time_ms",
            f"{trace_name}__raw",
            f"{trace_name}__normalized_target_mv",
            f"{trace_name}__emulator_fit_mv",
            f"{trace_name}__emulator_fit_raw_units",
        ])

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for i in range(max_len):
            row = {"sample_index": i}
            for trace_name, fit in results.items():
                if i >= len(fit["fit_time_ms"]):
                    continue
                row[f"{trace_name}__time_ms"] = fit["fit_time_ms"][i]
                row[f"{trace_name}__raw"] = fit["fit_raw"][i]
                row[f"{trace_name}__normalized_target_mv"] = fit["fit_target_mv"][i]
                row[f"{trace_name}__emulator_fit_mv"] = fit["pred_mv"][i]
                row[f"{trace_name}__emulator_fit_raw_units"] = fit["pred_raw_units"][i]
            writer.writerow(row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="Input CSV with time and V-trace columns.")
    parser.add_argument("--epochs", type=int, default=150, help="Optimizer epochs per trace.")
    parser.add_argument("--max-points", type=int, default=500, help="Maximum points per trace after downsampling.")
    parser.add_argument("--out-prefix", type=Path, default=DEFAULT_OUT_PREFIX, help="Output file prefix.")
    parser.add_argument(
        "--df-for-100mv",
        type=float,
        default=0.29,
        help="Calibration for dF/F0 traces. Use 0 or a negative value to disable and fall back to shape normalization.",
    )
    parser.add_argument(
        "--rest-mv",
        type=float,
        default=-85.0,
        help="Assumed resting membrane voltage for dF/F0 calibration.",
    )
    parser.add_argument(
        "--linked-different",
        nargs="*",
        default=[],
        help="For reference -> mutant fitting, these are the conductances allowed to change in the mutant. Accepts friendly names like GKr GKs GK1 PCa.",
    )
    parser.add_argument(
        "--list-conductances",
        action="store_true",
        help="Print the available conductance names for --linked-different and exit.",
    )
    parser.add_argument(
        "--pca-prior-low-frac",
        type=float,
        default=DEFAULT_PCA_PRIOR_LOW_FRAC,
        help="Lower PCa_b prior clamp as a fraction of the emulator center value.",
    )
    parser.add_argument(
        "--pca-prior-high-frac",
        type=float,
        default=DEFAULT_PCA_PRIOR_HIGH_FRAC,
        help="Upper PCa_b prior clamp as a fraction of the emulator center value.",
    )
    parser.add_argument(
        "--no-pca-prior",
        action="store_true",
        help="Disable the extra PCa_b range clamp and use the emulator default bounds.",
    )
    parser.add_argument(
        "--allow-training-extrapolation",
        action="store_true",
        help="Allow conductances to rise above the emulator training maximum. Lower bounds remain at zero, and any active PCa prior still applies.",
    )
    parser.add_argument("--pre-upstroke-ms", type=float, default=DEFAULT_PRE_UPSTROKE_MS, help="Pre-upstroke window kept for fitting.")
    parser.add_argument("--post-upstroke-ms", type=float, default=DEFAULT_POST_UPSTROKE_MS, help="Post-upstroke window kept for fitting.")
    parser.add_argument("--time-offset-clamp-ms", type=float, default=DEFAULT_TIME_OFFSET_CLAMP_MS, help="Clamp for residual fit time offset after beat alignment.")
    return parser.parse_args()


def run_fit_from_csv(
    csv_path: Path,
    trace_names: Sequence[str] | None = None,
    epochs: int = 150,
    max_points: int = 500,
    df_for_100mv: float | None = 0.29,
    rest_mv: float = -85.0,
    fit_param_names: Sequence[str] | None = None,
    linked_different: Sequence[str] | None = None,
    use_pca_prior: bool = True,
    pca_prior_low_frac: float = DEFAULT_PCA_PRIOR_LOW_FRAC,
    pca_prior_high_frac: float = DEFAULT_PCA_PRIOR_HIGH_FRAC,
    pre_upstroke_ms: float = DEFAULT_PRE_UPSTROKE_MS,
    post_upstroke_ms: float = DEFAULT_POST_UPSTROKE_MS,
    time_offset_clamp_ms: float = DEFAULT_TIME_OFFSET_CLAMP_MS,
    direction_constraints: Dict[str, str] | None = None,
    mutant_change_limits_pct: Dict[str, float] | None = None,
    reference_locked_params: Sequence[float] | None = None,
    allow_training_extrapolation: bool = False,
    force_linked: bool = False,
    out_prefix: Path | None = None,
):
    emulator, _ = load_emulator()
    time_ms, traces, time_name = load_csv_columns(Path(csv_path))

    if trace_names:
        chosen = [name for name in trace_names if name in traces]
        if not chosen:
            raise ValueError("No selected trace names were found in the CSV.")
        traces = {name: traces[name] for name in chosen}

    linked_different = tuple(linked_different or ())
    results: Dict[str, Dict[str, object]] = {}

    if force_linked or linked_different or direction_constraints or mutant_change_limits_pct:
        selected_different = resolve_conductance_names(emulator, linked_different)
        results = fit_reference_then_mutant_with_emulator(
            emulator=emulator,
            time_ms=time_ms,
            raw_traces=traces,
            epochs=int(epochs),
            max_points=int(max_points),
            df_for_100mv=float(df_for_100mv) if df_for_100mv is not None and df_for_100mv > 0 else None,
            fit_param_names=fit_param_names,
            different_param_names=tuple(selected_different),
            rest_mv=float(rest_mv),
            use_pca_prior=bool(use_pca_prior),
            pca_prior_low_frac=float(pca_prior_low_frac),
            pca_prior_high_frac=float(pca_prior_high_frac),
            pre_upstroke_ms=float(pre_upstroke_ms),
            post_upstroke_ms=float(post_upstroke_ms),
            time_offset_clamp_ms=float(time_offset_clamp_ms),
            direction_constraints=direction_constraints,
            mutant_change_limits_pct=mutant_change_limits_pct,
            reference_locked_params=reference_locked_params,
            allow_training_extrapolation=bool(allow_training_extrapolation),
        )
    else:
        for trace_name, raw_trace in traces.items():
            fit = fit_trace_with_emulator(
                emulator=emulator,
                time_ms=time_ms,
                raw_trace=raw_trace,
                epochs=int(epochs),
                max_points=int(max_points),
                df_for_100mv=float(df_for_100mv) if df_for_100mv is not None and df_for_100mv > 0 else None,
                use_pca_prior=bool(use_pca_prior),
                pca_prior_low_frac=float(pca_prior_low_frac),
                pca_prior_high_frac=float(pca_prior_high_frac),
                pre_upstroke_ms=float(pre_upstroke_ms),
                post_upstroke_ms=float(post_upstroke_ms),
                time_offset_clamp_ms=float(time_offset_clamp_ms),
                fit_param_names=fit_param_names,
                allow_training_extrapolation=bool(allow_training_extrapolation),
            )
            results[trace_name] = fit

    summary_path = None
    traces_path = None
    if out_prefix is not None:
        out_prefix = Path(out_prefix)
        summary_path = Path(f"{out_prefix}_summary.csv")
        traces_path = Path(f"{out_prefix}_traces.csv")
        write_summary(summary_path, emulator, results)
        write_traces(traces_path, results)

    return {
        "time_name": time_name,
        "trace_names": list(traces.keys()),
        "raw_traces": traces,
        "results": results,
        "summary_path": summary_path,
        "traces_path": traces_path,
    }


def main() -> int:
    args = parse_args()
    emulator, _ = load_emulator()
    if args.list_conductances:
        print("Available conductance names:")
        for name in available_short_names(emulator):
            print(f"  {name}")
        return 0
    run = run_fit_from_csv(
        csv_path=args.csv,
        trace_names=None,
        epochs=int(args.epochs),
        max_points=int(args.max_points),
        df_for_100mv=float(args.df_for_100mv) if args.df_for_100mv > 0 else None,
        rest_mv=float(args.rest_mv),
        linked_different=tuple(args.linked_different),
        use_pca_prior=not args.no_pca_prior,
        pca_prior_low_frac=float(args.pca_prior_low_frac),
        pca_prior_high_frac=float(args.pca_prior_high_frac),
        allow_training_extrapolation=bool(args.allow_training_extrapolation),
        pre_upstroke_ms=float(args.pre_upstroke_ms),
        post_upstroke_ms=float(args.post_upstroke_ms),
        time_offset_clamp_ms=float(args.time_offset_clamp_ms),
        out_prefix=Path(args.out_prefix),
    )
    results = run["results"]
    time_name = run["time_name"]

    print(f"Input: {args.csv}")
    print(f"Time column: {time_name}")
    if args.df_for_100mv > 0:
        print(f"Calibration: {args.df_for_100mv} dF/F0 = 100 mV")
    else:
        print("Calibration: disabled, using normalized shape only")
    print("Selected V traces:")
    for name in run["trace_names"]:
        print(f"  {name}")

    if args.linked_different:
        selected_different = resolve_conductance_names(emulator, tuple(args.linked_different))
        print("Reference -> mutant fitting:")
        print(f"  Mutant-changing parameters: {', '.join(selected_different)}")

    for trace_name, fit in results.items():
        print(f"\nTrace: {trace_name}")
        print(f"  Mode: {fit['mode']}")
        print(f"  RMSE normalized target (mV-like): {fit['rmse_target_mv']:.3f}")
        print(f"  RMSE raw units: {fit['rmse_raw_units']:.6f}")
        print(f"  Time offset (ms): {fit['t_offset_ms']:.3f}")
        if not math.isnan(float(fit["estimated_rest_df"])):
            print(f"  Estimated rest dF/F0: {fit['estimated_rest_df']:.6f}")
            print(f"  Assumed rest Vm: {fit['assumed_rest_mv']:.1f} mV")
        if fit.get("pca_prior_enabled", True):
            print(f"  PCa allowed range: {fit['pca_prior_low_frac']:.2f}x to {fit['pca_prior_high_frac']:.2f}x baseline")
        else:
            print("  PCa allowed range: disabled, using emulator default bounds")
        print(f"  Beat alignment: upstroke at {fit['upstroke_time_ms']:.1f} ms, window {fit['pre_upstroke_ms']:.1f}/{fit['post_upstroke_ms']:.1f} ms, residual shift clamp {fit['time_offset_clamp_ms']:.1f} ms")
        for name, value in zip(emulator.max_conds_names, fit["params"]):
            print(f"  {name}: {float(value):.6g}")

    summary_path = run["summary_path"]
    traces_path = run["traces_path"]
    print(f"\nWrote {summary_path}")
    print(f"Wrote {traces_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
