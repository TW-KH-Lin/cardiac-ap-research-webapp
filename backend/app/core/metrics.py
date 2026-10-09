"""Beat-aware AP and pacemaker biomarkers on full-resolution traces."""
from __future__ import annotations

import math

import numpy as np
from scipy.signal import find_peaks


def _crossing(t: np.ndarray, v: np.ndarray, threshold: float, start: int, stop: int) -> float | None:
    for i in range(start, stop - 1):
        if v[i] >= threshold > v[i + 1]:
            frac = (v[i] - threshold) / (v[i] - v[i + 1])
            return float(t[i] + frac * (t[i + 1] - t[i]))
    return None


def _one_beat(t: np.ndarray, v: np.ndarray, start_ms: float, end_ms: float, pre_ms: float = 20) -> dict:
    pre = (t >= max(float(t[0]), start_ms - pre_ms)) & (t < start_ms)
    window = np.flatnonzero((t >= start_ms) & (t < end_ms))
    if len(window) < 6 or not np.any(pre):
        return {"valid": False, "reason": "insufficient beat window"}
    rest = float(np.median(v[pre]))
    dt = np.diff(t[window])
    dvdt = np.diff(v[window]) / dt
    search = np.flatnonzero(t[window[:-1]] <= start_ms + min(120.0, (end_ms - start_ms) * 0.4))
    if not len(search):
        return {"valid": False, "reason": "no upstroke search interval"}
    up_local = int(search[np.argmax(dvdt[search])])
    up = int(window[up_local])
    max_slope = float(dvdt[up_local])
    peak_candidates = window[(window >= up) & (t[window] <= min(end_ms, float(t[up]) + 200))]
    peak = int(peak_candidates[np.argmax(v[peak_candidates])])
    amplitude = float(v[peak] - rest)
    if amplitude < 30 or max_slope < 1:
        return {"valid": False, "reason": "no valid action potential", "resting_mv": rest, "amplitude_mv": amplitude}
    result = {
        "valid": True, "upstroke_time_ms": float(t[up]), "resting_mv": rest,
        "peak_mv": float(v[peak]), "amplitude_mv": amplitude,
        "dvdt_max_mv_per_ms": max_slope,
    }
    for percent in (30, 50, 80, 90):
        threshold = rest + amplitude * (1 - percent / 100)
        crossing = _crossing(t, v, threshold, peak, int(window[-1]) + 1)
        result[f"apd{percent}_ms"] = None if crossing is None else crossing - float(t[up])
    a30, a90 = result["apd30_ms"], result["apd90_ms"]
    result["triangulation_ms"] = a90 - a30 if a30 is not None and a90 is not None else None
    # EAD flag: renewed depolarization after at least 50% repolarization. This
    # deliberately excludes a normal phase-1 notch followed by the plateau.
    post_indices = np.arange(peak, int(window[-1]) + 1)
    half_repolarized = post_indices[v[post_indices] <= rest + 0.5 * amplitude]
    if len(half_repolarized):
        late = v[int(half_repolarized[0]) : int(window[-1]) + 1]
        result["ead_flag"] = bool(len(late) > 3 and np.max(late - np.minimum.accumulate(late)) > 5)
    else:
        result["ead_flag"] = False
    return result


def paced_metrics(time_ms: list[float] | np.ndarray, voltage_mv: list[float] | np.ndarray, offset_ms: float, bcl_ms: float) -> dict:
    t, v = np.asarray(time_ms, dtype=float), np.asarray(voltage_mv, dtype=float)
    if t.size != v.size or t.size < 3 or not (np.all(np.isfinite(t)) and np.all(np.isfinite(v)) and np.all(np.diff(t) > 0)):
        raise ValueError("Time and voltage must be finite, equal-length, and strictly increasing")
    if bcl_ms <= 0:
        raise ValueError("BCL must be positive")
    beats = []
    onset = offset_ms
    while onset < t[-1] and len(beats) < 100:
        end = min(onset + bcl_ms, float(t[-1]))
        beats.append(_one_beat(t, v, onset, end))
        onset += bcl_ms
    selected = next((b for b in reversed(beats) if b.get("valid")), None)
    return {"mode": "paced", "beat_count": len(beats), "valid_beat_count": sum(b.get("valid", False) for b in beats), "last_valid_beat": selected, "beats": beats}


def pacemaker_metrics(time_ms: list[float] | np.ndarray, voltage_mv: list[float] | np.ndarray) -> dict:
    t, v = np.asarray(time_ms, dtype=float), np.asarray(voltage_mv, dtype=float)
    if t.size != v.size or t.size < 3 or not (np.all(np.isfinite(t)) and np.all(np.isfinite(v)) and np.all(np.diff(t) > 0)):
        raise ValueError("Time and voltage must be finite, equal-length, and strictly increasing")
    dt = float(np.median(np.diff(t)))
    peaks, _ = find_peaks(v, height=-20, prominence=20, distance=max(1, int(250 / dt)))
    if len(peaks) < 2:
        return {"mode": "spontaneous", "valid": False, "reason": "fewer than two spontaneous beats"}
    last_cycle = (t >= t[peaks[-2]]) & (t <= t[peaks[-1]])
    segment = np.flatnonzero(last_cycle)
    mdp = float(np.min(v[segment]))
    cycle = float(t[peaks[-1]] - t[peaks[-2]])
    slope = np.diff(v[segment]) / np.diff(t[segment])
    diastole = segment[(v[segment] >= mdp + 5) & (v[segment] <= mdp + 20)]
    dd_slope = float(np.polyfit(t[diastole], v[diastole], 1)[0]) if len(diastole) >= 3 else None
    return {
        "mode": "spontaneous", "valid": True, "beat_count": int(len(peaks)),
        "cycle_length_ms": cycle, "rate_bpm": 60000 / cycle,
        "maximum_diastolic_potential_mv": mdp, "peak_mv": float(v[peaks[-1]]),
        "amplitude_mv": float(v[peaks[-1]] - mdp),
        "dvdt_max_mv_per_ms": float(np.max(slope)),
        "diastolic_depolarization_mv_per_ms": dd_slope,
    }
