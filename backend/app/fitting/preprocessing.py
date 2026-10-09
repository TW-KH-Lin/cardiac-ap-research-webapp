"""Bounded, numeric-only CSV parsing and explicit trace calibration."""
from __future__ import annotations

import csv
import io

import numpy as np

from app.core.schemas import FittingRequest


def parse_csv(request: FittingRequest) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    sample = request.csv_text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(request.csv_text.lstrip("\ufeff")), dialect=dialect)
    fields = reader.fieldnames or []
    columns = [request.time_column, request.reference_column]
    if request.mutant_column:
        columns.append(request.mutant_column)
    if len(fields) > 50 or len(set(fields)) != len(fields):
        raise ValueError("CSV must have 50 or fewer uniquely named columns")
    if any(name not in fields for name in columns):
        raise ValueError(f"CSV is missing a selected column; available: {fields}")
    arrays = {name: [] for name in columns}
    for index, row in enumerate(reader):
        if index >= 20000:
            raise ValueError("CSV exceeds the 20,000-row limit")
        for name in columns:
            try:
                arrays[name].append(float(row[name]))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Non-numeric value in {name}, row {index + 2}") from exc
    if len(arrays[request.time_column]) < 30:
        raise ValueError("At least 30 data rows are required")
    t = np.asarray(arrays.pop(request.time_column), dtype=float)
    if request.time_unit == "s":
        t *= 1000
    if not np.all(np.isfinite(t)) or not np.all(np.diff(t) > 0):
        raise ValueError("Time must be finite and strictly increasing")
    traces = {name: np.asarray(values, dtype=float) for name, values in arrays.items()}
    if any(not np.all(np.isfinite(trace)) for trace in traces.values()):
        raise ValueError("Traces must contain finite numeric values")
    return t, traces


def calibrate(raw: np.ndarray, mode: str, rest_mv: float, df_for_100mv: float) -> tuple[np.ndarray, dict]:
    if mode == "voltage_mv":
        return raw.copy(), {"mode": mode, "unit": "mV"}
    if mode == "dff":
        rest_df = float(np.percentile(raw, 5))
        return (raw - rest_df) * 100 / df_for_100mv + rest_mv, {"mode": mode, "rest_df": rest_df, "rest_mv": rest_mv, "df_for_100mv": df_for_100mv, "unit": "mV"}
    low, high = float(raw.min()), float(raw.max())
    if high - low <= 1e-12:
        raise ValueError("Flat trace cannot be shape-normalized")
    return (raw - low) / (high - low) * 120 - 85, {"mode": "shape", "source_min": low, "source_max": high, "mapped_min_mv": -85, "mapped_max_mv": 35, "unit": "mV"}


def aligned_window(t: np.ndarray, v: np.ndarray, max_points: int) -> tuple[np.ndarray, np.ndarray, float]:
    dvdt = np.diff(v) / np.diff(t)
    upstroke = float(t[int(np.argmax(dvdt))])
    keep = np.flatnonzero((t >= upstroke - 10) & (t <= upstroke + 500))
    if len(keep) < 30:
        raise ValueError("Insufficient samples around the detected upstroke")
    if len(keep) > max_points:
        keep = keep[np.unique(np.linspace(0, len(keep) - 1, max_points).round().astype(int))]
    return t[keep] - upstroke, v[keep], upstroke
