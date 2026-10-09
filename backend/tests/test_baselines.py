import json
from pathlib import Path

import numpy as np
import pytest

from app.backends.myokit_backend import MyokitBackend
from app.backends.grandits_backend import GranditsBackend
from app.backends.ni_backend import NiBackend
from app.backends.simone_backend import SimoneBackend
from app.backends.herrera_backend import HerreraBackend
from app.core.registry import model_by_id
from app.core.schemas import SimulationRequest

REFERENCE = Path(__file__).parent / "reference"
IDS = (
    "torord_dyncl_endo", "bps2020", "ord_2011", "grandi_2011", "fabbri_2017",
    "linder_fabbri_2025", "grandits_2024", "ni_2023_atrial", "simone_wt", "simone_ts22",
    "herrera_2025_male_nsr", "herrera_2025_female_nsr",
    "herrera_2025_male_caf", "herrera_2025_female_caf",
)


@pytest.mark.parametrize("model_id", IDS)
def test_pinned_baseline_regression(model_id):
    reference = json.loads((REFERENCE / model_id / "baseline.json").read_text())
    entry = model_by_id(model_id)
    assert entry["sha256"] == reference["source_sha256"]
    backend = {
        "myokit": MyokitBackend, "grandits": GranditsBackend, "external_compiled": NiBackend,
        "simone_static": SimoneBackend, "herrera_octave": HerreraBackend,
    }[entry["backend"]]()
    result = backend.simulate(entry, SimulationRequest.model_validate(reference["request"]))
    fixture = np.load(REFERENCE / model_id / "baseline_trace.npz")
    voltage = np.asarray(result["voltage_mv"])
    assert np.all(np.isfinite(voltage))
    assert len(voltage) == len(fixture["voltage_mv"])
    assert np.sqrt(np.mean((voltage - fixture["voltage_mv"]) ** 2)) < reference["tolerances"]["trace_rmse_mv"]
    assert np.ptp(voltage) > 30
    selected = result["metrics"].get("last_valid_beat") if result["metrics"]["mode"] == "paced" else result["metrics"]
    assert selected and selected["valid"]
    key = "apd90_ms" if result["metrics"]["mode"] == "paced" else "cycle_length_ms"
    actual = selected[key]
    expected = reference["selected_metrics"][key]
    assert abs(actual - expected) / expected < reference["tolerances"]["metric_relative"]
    if model_id == "ni_2023_atrial":
        assert abs(actual - reference["upstream_reference_apd90_ms"]) < reference["upstream_reference_tolerance_ms"]
    for name, expected_peak in reference["current_peak_abs"].items():
        current = result["currents"][name]
        assert current["native_name"] == entry["currents"][name]
        peak = float(np.max(np.abs(current["values"])))
        assert abs(peak - expected_peak) / max(expected_peak, 1e-9) < reference["tolerances"]["current_peak_relative"]
    assert result["settings_actual"]["rescued"] is False



def test_all_catalog_models_have_passed_the_validation_gate():
    assert all(model_by_id(model_id)["status"] == "enabled" for model_id in IDS)
