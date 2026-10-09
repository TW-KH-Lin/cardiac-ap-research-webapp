from __future__ import annotations

import numpy as np


def time_to_ms_factor(unit: str) -> float:
    value = unit.strip("[] ").lower()
    factors = {"s": 1000.0, "second": 1000.0, "ms": 1.0, "millisecond": 1.0, "us": 0.001, "ns": 1e-6}
    if value not in factors:
        raise ValueError(f"Unsupported native time unit: {unit}")
    return factors[value]


def stimulus_na_to_af(strength_na: float, cm_pf: float, polarity: int = -1) -> float:
    if cm_pf <= 0:
        raise ValueError("Membrane capacitance must be positive")
    return polarity * abs(strength_na) * 1000.0 / cm_pf


def current_for_display(values: np.ndarray, native_unit: str, cm_pf: float) -> tuple[np.ndarray, str, str]:
    """Return converted values, unit, and an explicit conversion description."""
    unit = native_unit.strip("[] ")
    factors = {"A": 1e12, "mA": 1e9, "uA": 1e6, "nA": 1e3, "pA": 1.0}
    if unit == "A/F":
        return values * cm_pf, "pA", f"A/F × {cm_pf:g} pF"
    if unit in factors:
        return values * factors[unit], "pA", f"{unit} to pA"
    return values, native_unit or "unknown", "native values; no verified conversion"
