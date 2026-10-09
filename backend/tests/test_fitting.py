import csv
import io

import numpy as np
from fastapi.testclient import TestClient

from app.backends.grandits_backend import load_emulator
from app.main import app

client = TestClient(app)


def test_numeric_csv_fit_returns_all_nine_parameters():
    emulator = load_emulator()
    time = np.linspace(-10, 500, 350)
    voltage = emulator.forward_latent_np(time.astype(np.float32), np.asarray(emulator.max_conds_center, dtype=np.float32))[0]
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["time_ms", "V_ref"])
    writer.writerows(zip(time, voltage, strict=True))
    response = client.post("/api/fitting/grandits", json={
        "csv_text": stream.getvalue(), "time_column": "time_ms", "time_unit": "ms",
        "reference_column": "V_ref", "epochs": 10, "max_points": 300,
    })
    assert response.status_code == 200, response.text
    fit = response.json()["traces"]["reference"]
    assert len(fit["parameters"]) == 9
    assert fit["rmse_mv"] < 15
    assert len(fit["parameter_table"]) == 9


def test_mechanistic_validation_applies_nine_of_nine():
    emulator = load_emulator()
    params = {str(name): float(value) for name, value in zip(emulator.max_conds_names, emulator.max_conds_center, strict=True)}
    response = client.post("/api/fitting/validate", json={"grandits_parameters": params, "duration_ms": 600, "prepace_beats": 0})
    assert response.status_code == 200, response.text
    validation = response.json()
    assert validation["mapped_count"] == 9
    assert validation["ignored_parameters"] == []
    applied = validation["mechanistic_result"]["settings_actual"]["parameter_values"]
    assert len(applied) == 9
    assert applied["g_NaCa"]["native_name"] == "INaCa.Gncx_b"
    assert applied["g_NaK"]["native_name"] == "INaK.Pnak_b"


def test_partial_mechanistic_validation_is_rejected():
    response = client.post("/api/fitting/validate", json={"grandits_parameters": {"GNa": 11.78}})
    assert response.status_code == 422
    assert "9/9" in response.json()["detail"]
