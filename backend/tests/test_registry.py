import hashlib

from app.backends.myokit_backend import parameter_metadata
from app.core.registry import ROOT, model_by_id, models


def test_enabled_models_have_pinned_sources_and_native_parameters():
    enabled = [entry for entry in models() if entry["status"] == "enabled"]
    assert len(enabled) == 14
    for entry in enabled:
        assert hashlib.sha256((ROOT / entry["source_file"]).read_bytes()).hexdigest() == entry["sha256"]
        if entry.get("runtime_file") and entry.get("runtime_sha256"):
            assert hashlib.sha256((ROOT / entry["runtime_file"]).read_bytes()).hexdigest() == entry["runtime_sha256"]
        if entry["backend"] == "myokit":
            assert set(parameter_metadata(entry)) == set(entry["parameters"])


def test_tor_contains_all_nine_native_base_variables():
    metadata = parameter_metadata(model_by_id("torord_dyncl_endo"))
    assert len(metadata) == 9
    assert metadata["g_NaCa"]["native_name"] == "INaCa.Gncx_b"
    assert metadata["g_NaK"]["native_name"] == "INaK.Pnak_b"
