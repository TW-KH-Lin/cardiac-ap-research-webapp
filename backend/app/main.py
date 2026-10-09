from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.backends.grandits_backend import GranditsBackend, load_emulator
from app.backends.myokit_backend import MyokitBackend, parameter_metadata
from app.backends.ni_backend import NiBackend, parameter_metadata as ni_parameter_metadata
from app.backends.simone_backend import SimoneBackend, parameter_metadata as simone_parameter_metadata
from app.backends.herrera_backend import HerreraBackend, parameter_metadata as herrera_parameter_metadata
from app.core.metrics import paced_metrics, pacemaker_metrics
from app.core.registry import ROOT, model_by_id, models
from app.core.schemas import CompareRequest, FittingRequest, MetricsRequest, SimulationRequest, ValidationRequest
from app.fitting.grandits_fit import fit_csv
from app.fitting.mapping import to_tor_changes

log = logging.getLogger("cardiac_ap")
app = FastAPI(title="Cardiac AP research simulator", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://cardiac-ap-simulator.tw-kh-lin.chatgpt.site",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def public_entry(entry: dict, detailed: bool = False) -> dict:
    safe = {k: v for k, v in entry.items() if k not in {"source_file", "auxiliary_files", "runtime_file", "initial_conditions_file"}}
    if detailed and entry["status"] == "enabled":
        if entry["backend"] == "myokit":
            safe["parameter_metadata"] = parameter_metadata(entry)
        elif entry["backend"] == "grandits":
            emulator = load_emulator()
            names = list(emulator.max_conds_names)
            safe["parameter_metadata"] = {
                canonical: {
                    "native_name": native, "native_unit": "training parameter",
                    "native_baseline": float(emulator.max_conds_center[names.index(native)]),
                    "training_min": float(emulator.max_conds_ranges[0][names.index(native)]),
                    "training_max": float(emulator.max_conds_ranges[1][names.index(native)]),
                }
                for canonical, native in entry["parameters"].items()
            }
        elif entry["backend"] == "external_compiled":
            safe["parameter_metadata"] = ni_parameter_metadata(entry)
        elif entry["backend"] == "simone_static":
            safe["parameter_metadata"] = simone_parameter_metadata(entry)
        elif entry["backend"] == "herrera_octave":
            safe["parameter_metadata"] = herrera_parameter_metadata(entry)
    return safe


@app.get("/api/health")
def health():
    return {"status": "ok", "enabled_models": sum(entry["status"] == "enabled" for entry in models())}


@app.get("/api/version")
def version():
    return {"app_version": app.version, "manifest_schema_version": 1}


@app.get("/api/models")
def list_models():
    return [public_entry(entry) for entry in models()]


@app.get("/api/models/{model_id}")
def get_model(model_id: str):
    try:
        return public_entry(model_by_id(model_id), detailed=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def run_simulation(request: SimulationRequest) -> dict:
    try:
        entry = model_by_id(request.model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if entry["status"] != "enabled":
        raise HTTPException(status_code=409, detail=entry.get("status_reason", "Model has not passed numerical validation"))
    log.info("simulation model=%s revision=%s settings=%s", entry["id"], entry["source_revision"], request.model_dump_json())
    try:
        backends = {"myokit": MyokitBackend, "grandits": GranditsBackend, "external_compiled": NiBackend, "simone_static": SimoneBackend, "herrera_octave": HerreraBackend}
        if entry["backend"] not in backends:
            raise ValueError(f"No production adapter for backend {entry['backend']}")
        backend = backends[entry["backend"]]()
        return backend.simulate(entry, request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/simulate")
def simulate(request: SimulationRequest):
    return run_simulation(request)


@app.post("/api/compare")
def compare(request: CompareRequest):
    results = [run_simulation(item) for item in request.simulations]
    warnings = []
    if len({result["model_id"] for result in results}) > 1:
        warnings.append("Absolute conductance values are not directly comparable across model formulations.")
    return {"simulations": results, "warnings": warnings}


@app.post("/api/metrics")
def metrics(request: MetricsRequest):
    try:
        if request.mode == "spontaneous":
            return pacemaker_metrics(request.time_ms, request.voltage_mv)
        if request.pacing is None or request.pacing.frequency_hz <= 0:
            raise ValueError("Paced metrics require a positive frequency and pacing settings")
        return paced_metrics(request.time_ms, request.voltage_mv, request.pacing.offset_ms, 1000 / request.pacing.frequency_hz)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/fitting/grandits")
def grandits_fit(request: FittingRequest):
    try:
        return fit_csv(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/fitting/validate")
def validate_fit(request: ValidationRequest):
    try:
        changes = to_tor_changes(request.grandits_parameters)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    simulation = SimulationRequest(
        model_id="torord_dyncl_endo", duration_ms=request.duration_ms,
        prepace_beats=request.prepace_beats, pacing=request.pacing,
        parameters=changes, include_currents=["INa", "IKr", "ICaL", "INaK", "INaCa_i", "INaCa_ss"],
    )
    result = run_simulation(simulation)
    return {"mapped_count": len(changes), "ignored_parameters": [], "mechanistic_result": result,
            "warning": "Mechanistic validation is a separate ToR simulation, not proof that the fitted parameters are unique."}


DIST = ROOT / "frontend/dist"
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def frontend(path: str):
        target = (DIST / path).resolve()
        if target.is_file() and target.is_relative_to(DIST.resolve()):
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
