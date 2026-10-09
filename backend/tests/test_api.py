from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_models_and_health_expose_status_without_server_paths():
    assert client.get("/api/health").json()["enabled_models"] == 14
    models = client.get("/api/models").json()
    assert len(models) >= 7
    assert all(not ({"source_file", "runtime_file", "initial_conditions_file"} & set(entry)) for entry in models)
    assert client.get("/api/models/torord_dyncl_endo").json()["parameter_metadata"]["g_NaCa"]["native_name"] == "INaCa.Gncx_b"
    ni = client.get("/api/models/ni_2023_atrial").json()
    assert ni["model_options"]["iso_nm"]["max"] == 1000


def test_ni_native_baseline_and_fixed_protocol():
    request = {"model_id": "ni_2023_atrial", "duration_ms": 1000, "prepace_beats": 0, "include_currents": ["IKur"]}
    response = client.post("/api/simulate", json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    assert abs(result["metrics"]["last_valid_beat"]["apd90_ms"] - 288.77) < 5
    assert result["currents"]["IKur"]["native_name"] == "IKur"
    request["pacing"] = {"frequency_hz": 1, "stimulus_duration_ms": 4, "stimulus_strength_nA": 1.375, "offset_ms": 0, "cm_pf": 110}
    assert client.post("/api/simulate", json=request).status_code == 422


def test_simulate_and_compare():
    a = {"model_id": "torord_dyncl_endo", "duration_ms": 600, "prepace_beats": 0, "include_currents": ["IKr"]}
    b = {"model_id": "ord_2011", "duration_ms": 600, "prepace_beats": 0}
    response = client.post("/api/simulate", json=a)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["settings_requested"]["auto_rescue"] is False
    assert result["settings_actual"]["rescued"] is False
    assert result["currents"]["IKr"]["native_name"] == "IKr.IKr"
    compare = client.post("/api/compare", json={"simulations": [a, b]})
    assert compare.status_code == 200, compare.text
    assert len(compare.json()["simulations"]) == 2
    assert compare.json()["warnings"]


def test_unavailable_model_and_unsupported_parameter_fail():
    unavailable = client.post("/api/simulate", json={"model_id": "does_not_exist", "prepace_beats": 0})
    assert unavailable.status_code == 404
    unsupported = client.post("/api/simulate", json={"model_id": "torord_dyncl_endo", "prepace_beats": 0, "parameters": {"g_f": {"scale": 1.1}}})
    assert unsupported.status_code == 422
