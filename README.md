# Cardiac AP Web App

A research oriented web application for running, comparing, and fitting human cardiac action potential models. The scientific runtime is server side; the browser handles configuration, plotting, provenance, and export.

This repository is intended for **noncommercial research, education, and institutional scientific work**. It is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). Model implementations and dependencies retain their own upstream terms; read [LICENSE_NOTES.md](LICENSE_NOTES.md) before use or redistribution.

The authoritative implementation brief is [docs/CARDIAC_WEBAPP_CODEX_MASTER_HANDOFF.md](docs/CARDIAC_WEBAPP_CODEX_MASTER_HANDOFF.md). The original desktop scripts remain unchanged in `legacy/`.

## Current model status

All 14 catalog entries are enabled on the development host.

| Model | Domain | Runtime status |
|---|---|---|
| ToR-ORd-dynCl / BPS2020 / O'Hara-Rudy 2011 | Adult ventricular | Pinned CellML/MMT through Myokit |
| Grandi 2011 | Adult atrial | Pinned curated MMT |
| Ni–Morotti–Grandi 2023 | Adult atrial signaling | Pinned C++ native adapter |
| Fabbri 2017 / Linder–Fabbri 2025 | Human SAN | Spontaneous Myokit models; Linder exposes Ca²⁺ and ISO |
| Grandits 2024 | Ventricular surrogate | SHA-verified Torch checkpoint |
| Simone–Trancuccio WT / TS22 | hiPSC ventricular | Static Python port validated against original source; noncommercial only |
| Herrera 2025 male/female nSR/cAF | Adult atrial | Pinned original MATLAB equations under Octave; license review required |

The Models page exposes the revision, license status, and provenance for every entry.

## Published access

- [ChatGPT Site](https://cardiac-ap-simulator.tw-kh-lin.chatgpt.site/) — phone-friendly interface and complete bundled model catalog. Scientific controls activate when a compatible backend is connected.
- [GitHub repository](https://github.com/TW-KH-Lin/cardiac-ap-research-webapp) — validated source, tests, and the Docker deployment that runs all 14 model entries.

ChatGPT Sites cannot host the native scientific stack used by this project. The Docker deployment is the complete runnable research application; the Site reports server availability explicitly instead of hiding the catalog when compute is unavailable.

## Features

- Unified simulation and comparison API for ventricular, atrial, and SAN models
- Beat aware paced metrics and separate spontaneous pacemaker metrics
- Requested and actual pacing protocols in every result
- Explicit native parameter metadata and relative scaling
- Current and calcium output with unit provenance
- Grandits CSV inverse fitting with reference/mutant constraints
- Complete 9/9 Grandits → ToR-ORd mechanistic mapping, including `Gncx_b` and `Pnak_b`
- CSV and JSON export
- Pinned source hashes and numerical regression fixtures
- No Qt dependency and no runtime model downloads

## Bootstrap pinned model sources

Third-party model source, checkpoints, generated translations, native binaries, and local runtimes are intentionally excluded from this repository. The bootstrap script checks out fixed Git revisions, downloads fixed PMR revisions, prepares the reviewed Linder importer repair and Simone static port, refreshes hashes, and builds the Ni native adapter when `SUNDIALS_PREFIX` is available.

Run it only after reviewing each upstream model's terms:

```bash
bash scripts/fetch_models.sh
```

To bootstrap only sources from GitHub:

```bash
FETCH_PMR=0 SUNDIALS_PREFIX=/usr bash scripts/fetch_models.sh
```

The Ni build targets SUNDIALS 6 while preserving the upstream SUNDIALS 5.7 source unchanged. It compiles a temporary copy with explicit return values for four state-update functions whose upstream callers discard the return value; this removes compiler-dependent undefined behavior without changing the equations or state updates:

```bash
SUNDIALS_PREFIX=/usr bash scripts/build_ni_2023.sh
```

## Run locally

Requirements: Python 3.12, a C/C++ compiler, SUNDIALS/CVODES, Node.js, pnpm, and GNU Octave for Herrera runs. The committed Herrera reference fixtures were generated with Octave 10.3; CI also exercises the distribution-provided Octave runtime.

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-test.txt
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

## Docker

Fetch every pinned model source first, then build:

```bash
SUNDIALS_PREFIX=/usr bash scripts/fetch_models.sh
docker compose up --build
```

The image compiles the Ni adapter inside Linux, avoiding reuse of a host binary, and installs Octave for the four Herrera variants.

## Tests

```bash
PYTHONPATH=backend .venv/bin/pytest backend/tests -q
cd frontend && pnpm build
```

Regression artifacts live in `backend/tests/reference/`. See [the validation report](docs/VALIDATION_REPORT.md) for accepted metrics and scientific gates.

## API

The main endpoints are:

```text
GET  /api/models
GET  /api/models/{model_id}
POST /api/simulate
POST /api/compare
POST /api/metrics
POST /api/fitting/grandits
POST /api/fitting/validate
GET  /api/health
GET  /api/version
```

Example:

```json
{
  "model_id": "torord_dyncl_endo",
  "duration_ms": 1000,
  "prepace_beats": 50,
  "parameters": {"g_Kr": {"scale": 0.5}},
  "include_currents": ["IKr", "ICaL"],
  "auto_rescue": false
}
```

## Intended use

This software supports research exploration and model comparison. It is not a clinical diagnostic device. Model specific licensing and deployment notes are in [LICENSE_NOTES.md](LICENSE_NOTES.md).

Commercial use is outside the repository license, and Simone–Trancuccio additionally carries its own upstream noncommercial restriction. Herrera and Ni have no explicit upstream repository license at their pinned revisions; the bootstrap process downloads them directly from their official repositories without relicensing or bundling them here.
