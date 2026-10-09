import json
from pathlib import Path

import numpy as np
import pytest

from app.backends.simone_backend import SimoneBackend
from app.backends.simone_static_rhs import INITIAL_STATE, SOURCE_SHA256

REFERENCE = Path(__file__).parent / "reference"


@pytest.mark.parametrize(("model_id", "fractional_ts"), (("simone_wt", 0.0), ("simone_ts22", 0.22)))
def test_static_port_matches_original_octave_source(model_id, fractional_ts):
    folder = REFERENCE / model_id
    metadata = json.loads((folder / "octave_reference.json").read_text())
    fixture = np.load(folder / "octave_reference.npz")
    assert SOURCE_SHA256 == metadata["source_sha256"]
    solution = SimoneBackend._solve(INITIAL_STATE.copy(), 3.0, fixture["time_s"], fractional_ts, {})
    voltage_error = solution.y[0] * 1000 - fixture["voltage_v"] * 1000
    assert np.sqrt(np.mean(voltage_error ** 2)) < metadata["voltage_rmse_tolerance_mv"]
    assert np.max(np.abs(voltage_error)) < metadata["voltage_max_abs_tolerance_mv"]
    assert np.sqrt(np.mean((solution.y[2] - fixture["calcium_mm"]) ** 2)) < 1e-8
