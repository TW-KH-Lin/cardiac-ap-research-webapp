import pytest

from app.backends.myokit_backend import MyokitBackend
from app.backends.ni_backend import NiBackend
from app.core.registry import model_by_id
from app.core.schemas import ParameterChange, SimulationRequest
from app.fitting.mapping import GRANDITS_TO_CANONICAL, to_tor_changes


@pytest.fixture(scope="module")
def baseline():
    entry = model_by_id("torord_dyncl_endo")
    return MyokitBackend().simulate(entry, SimulationRequest(model_id=entry["id"], prepace_beats=50))


@pytest.mark.parametrize("name,scale,expected", [
    ("g_Na", 0.5, "upstroke_down"),
    ("g_CaL", 0.5, "apd_down"),
    ("g_Kr", 0.5, "apd_up"),
    ("g_K1", 0.5, "apd_up"),
    ("g_NaL", 1.5, "apd_up"),
])
def test_tor_qualitative_perturbation_direction(baseline, name, scale, expected):
    entry = model_by_id("torord_dyncl_endo")
    request = SimulationRequest(model_id=entry["id"], prepace_beats=50, parameters={name: ParameterChange(scale=scale)})
    result = MyokitBackend().simulate(entry, request)
    first = baseline["metrics"]["last_valid_beat"]
    second = result["metrics"]["last_valid_beat"]
    assert second and second["valid"]
    if expected == "upstroke_down":
        assert second["dvdt_max_mv_per_ms"] < first["dvdt_max_mv_per_ms"] * 0.8
    elif expected == "apd_down":
        assert second["apd90_ms"] < first["apd90_ms"] - 10
    else:
        assert second["apd90_ms"] > first["apd90_ms"] + 5


def test_all_nine_grandits_values_reach_tor_native_variables():
    entry = model_by_id("torord_dyncl_endo")
    reference = {
        "GNa": 11.7802, "GNaL_b": 0.0279, "Gto_b": 0.16,
        "GKr_b": 0.0321, "GKs_b": 0.0011, "GK1_b": 0.6992,
        "Gncx_b": 0.0034, "Pnak_b": 15.4509, "PCa_b": 8.3757e-5,
    }
    assert set(reference) == set(GRANDITS_TO_CANONICAL)
    changes = to_tor_changes(reference)
    result = MyokitBackend().simulate(entry, SimulationRequest(model_id=entry["id"], prepace_beats=0, parameters=changes))
    applied = result["settings_actual"]["parameter_values"]
    assert len(applied) == 9
    assert applied["g_NaCa"]["native_name"] == "INaCa.Gncx_b"
    assert applied["g_NaK"]["native_name"] == "INaK.Pnak_b"


def test_ni_ikr_reduction_prolongs_apd90():
    entry = model_by_id("ni_2023_atrial")
    backend = NiBackend()
    baseline = backend.simulate(entry, SimulationRequest(model_id=entry["id"], prepace_beats=0))
    reduced = backend.simulate(entry, SimulationRequest(
        model_id=entry["id"], prepace_beats=0,
        parameters={"g_Kr": ParameterChange(scale=0.5)},
    ))
    assert reduced["metrics"]["last_valid_beat"]["apd90_ms"] > baseline["metrics"]["last_valid_beat"]["apd90_ms"] + 10
