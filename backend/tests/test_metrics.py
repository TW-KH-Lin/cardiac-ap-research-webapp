import numpy as np

from app.core.metrics import paced_metrics, pacemaker_metrics


def test_paced_metrics_keep_crossings_within_their_beat():
    t = np.arange(0, 2000, 0.2)
    v = np.full_like(t, -85.0)
    for onset in (200, 1200):
        rise = (t >= onset) & (t < onset + 2)
        plateau = (t >= onset + 2) & (t < onset + 100)
        decay = (t >= onset + 100) & (t < onset + 300)
        v[rise] = -85 + 120 * (t[rise] - onset) / 2
        v[plateau] = 35
        v[decay] = 35 - 120 * (t[decay] - onset - 100) / 200
    result = paced_metrics(t, v, 200, 1000)
    assert result["valid_beat_count"] == 2
    assert 250 < result["last_valid_beat"]["apd90_ms"] < 300


def test_flat_trace_has_no_misleading_apd():
    t = np.arange(0, 1000, 0.2)
    result = paced_metrics(t, np.full_like(t, -80), 200, 1000)
    assert result["last_valid_beat"] is None
    assert result["beats"][0]["valid"] is False


def test_ead_detection_ignores_phase_one_notch_but_flags_late_redepolarization():
    t = np.arange(0, 800, 0.2)
    base = np.full_like(t, -85.0)
    points_t = np.array([200, 202, 210, 240, 300, 420, 520, 700])
    normal_points = np.array([-85, 35, 10, 25, 15, -30, -75, -85])
    normal = base.copy()
    active = t >= 200
    normal[active] = np.interp(t[active], points_t, normal_points)
    normal_result = paced_metrics(t, normal, 200, 600)["last_valid_beat"]
    assert normal_result and normal_result["ead_flag"] is False
    ead = normal.copy()
    ead += 18 * np.exp(-((t - 470) / 18) ** 2)
    ead_result = paced_metrics(t, ead, 200, 600)["last_valid_beat"]
    assert ead_result and ead_result["ead_flag"] is True


def test_pacemaker_metrics_detect_cycle_length():
    t = np.arange(0, 3000, 1.0)
    phase = (t % 800) / 800
    v = -60 + 90 * np.exp(-((phase - 0.5) / 0.08) ** 2)
    result = pacemaker_metrics(t, v)
    assert result["valid"] is True
    assert 795 < result["cycle_length_ms"] < 805
