# Cardiac AP Web App — Codex Master Handoff

**Status date:** 2026-10-07  
**Purpose:** Authoritative implementation brief for rebuilding the legacy cardiac action-potential desktop tools as a reproducible research-oriented Web App.

---

## 0. Instructions to Codex

You are rebuilding an existing cardiac electrophysiology simulator, not starting from a blank scientific concept.

Work autonomously and proceed in phases. Do not ask the user to manually locate public model files that are listed below. Download them from the specified repositories, pin the exact revision/commit used, and record checksums in a model manifest.

The primary goals are:

1. Preserve and validate the existing forward-simulation behavior.
2. Correct known parameter-mapping and metric problems.
3. Separate scientific model code from UI code.
4. Support ventricular, atrial, and pacemaker/SAN models behind one stable simulation API.
5. Preserve the Grandits inverse-fitting workflow, but do not let fitting delay completion of a validated forward simulator.
6. Make all scientific assumptions, stimulation protocols, model versions, units, and auto-corrections visible to the user.
7. Produce a reproducible deployable web application, not another desktop Qt application.

The finished application should be suitable for research exploration and model comparison. It must not imply clinical diagnostic use.

---

# 1. Files the user MUST provide to Codex

The following are the user's legacy/local files. These are the only files that must come from the user because they contain the user's own integration logic and historical implementation decisions.

## REQUIRED legacy Python files

### 1. `Cardiac AP.py`
**Role:** Main/current forward simulator and model registry.  
**Priority:** Critical — use as the main behavioral reference.

Contains:
- `MODEL_LIBRARY`
- canonical control/knob names
- Myokit model loading
- current detection
- stimulation logic
- unit conversion
- APD90 helper
- Simone backend routing
- Grandits emulator routing
- current plotting/result schema concepts

This file should **not** remain monolithic in the Web App. Refactor its scientific logic into backend modules.

### 2. `simone_trancuccio_backend.py`
**Role:** Adapter for the Simone–Trancuccio hiPSC ventricular model.  
**Priority:** Critical if Simone/Timothy syndrome support is retained.

Current implementation dynamically converts MATLAB syntax to Python and uses `exec()`. Preserve it only as a validation/reference implementation. For production, convert the equations once to a static reviewed Python module and regression-test it against the original MATLAB implementation.

### 3. `fit_vtrace_csv_emulator.py`
**Role:** Grandits neural-emulator inverse-fitting engine and mechanistic-validation bridge.  
**Priority:** Critical for the fitting module.

Contains:
- CSV parsing
- experimental V-trace handling
- dF/F calibration
- trace alignment
- weighted fitting loss
- control/reference → mutant fitting
- parameter constraints
- Grandits inverse fit
- mapping to mechanistic models
- mechanistic validation

This file also contains a known validation mapping issue described later in this handoff.

## STRONGLY RECOMMENDED reference files

### 4. `fit_vtrace_csv_emulator_ui.py`
**Role:** Desktop UI reference for the fitting workflow.  
**Priority:** Recommended, not scientifically required.

Use it to understand:
- which options the previous UI exposed
- reference/mutant workflow
- conductance fit table
- calibration controls
- result presentation
- mechanistic validation UX

Do **not** port Qt widgets directly. Recreate the concepts in the Web UI.

### 5. `Two_cardiac_models.py`
**Role:** Older comparison-oriented simulator.  
**Priority:** Recommended as a UX/functionality reference.

Its main feature worth restoring is simultaneous overlay comparison of multiple models. Do not treat it as the scientific core.

## ALSO PROVIDE

### 6. `cardiac_ap_model_audit.md`
This is the prior audit of the legacy code and should be treated as background/reference.

### 7. This file: `CARDIAC_WEBAPP_CODEX_MASTER_HANDOFF.md`
Treat this document as the implementation specification.

---

# 2. Recommended project structure

Create a clean repository such as:

```text
cardiac-webapp/
├── README.md
├── LICENSE_NOTES.md
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── models.py
│   │   │   ├── simulation.py
│   │   │   ├── fitting.py
│   │   │   └── health.py
│   │   ├── core/
│   │   │   ├── schemas.py
│   │   │   ├── units.py
│   │   │   ├── metrics.py
│   │   │   ├── pacing.py
│   │   │   └── registry.py
│   │   ├── backends/
│   │   │   ├── base.py
│   │   │   ├── myokit_backend.py
│   │   │   ├── grandits_backend.py
│   │   │   ├── simone_backend.py
│   │   │   ├── native_python_backend.py
│   │   │   └── external_compiled_backend.py
│   │   ├── fitting/
│   │   │   ├── grandits_fit.py
│   │   │   ├── preprocessing.py
│   │   │   └── mechanistic_validation.py
│   │   └── models/
│   │       ├── manifest.json
│   │       └── registry_data.py
│   └── tests/
│       ├── test_registry.py
│       ├── test_metrics.py
│       ├── test_units.py
│       ├── test_baselines.py
│       ├── test_perturbations.py
│       └── test_fitting_mapping.py
├── frontend/
│   ├── package.json
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   ├── api/
│   │   └── types/
│   └── ...
├── external/
│   ├── torord/
│   ├── myokit-models/
│   ├── grandits_emulator/
│   ├── ni_2023_atrial/
│   ├── herrera_2025_atrial/
│   ├── heijman_sk_trafficking/
│   ├── fullerton_rrc/
│   └── ...
├── model_assets/
│   ├── ventricular/
│   ├── atrial/
│   └── pacemaker/
├── legacy/
│   ├── Cardiac AP.py
│   ├── simone_trancuccio_backend.py
│   ├── fit_vtrace_csv_emulator.py
│   ├── fit_vtrace_csv_emulator_ui.py
│   └── Two_cardiac_models.py
└── docs/
    ├── cardiac_ap_model_audit.md
    └── CARDIAC_WEBAPP_CODEX_MASTER_HANDOFF.md
```

Do not keep hard-coded personal paths such as `/Users/...`.

---

# 3. Recommended technical stack

## Backend
Use Python.

Recommended:
- FastAPI
- Pydantic
- NumPy
- SciPy
- Pandas
- Myokit
- Torch CPU for Grandits emulator
- Uvicorn/Gunicorn as appropriate
- pytest

Myokit server deployment requires a C/C++ compiler and CVODES/SUNDIALS support. Build this into Docker. Do not assume the deployment machine has the same scientific libraries as a developer laptop.

A practical Linux container should install the compiler/build chain and SUNDIALS/CVODES dependencies before `pip install myokit`.

## Frontend
Recommended:
- React
- TypeScript
- Vite or the existing project framework if one already exists
- Plotly.js or another scientific plotting library capable of:
  - multiple synchronized traces
  - hover values
  - legends
  - zoom
  - current overlays
  - downloadable PNG/SVG if desired

## Important architectural rule
**Do not port mechanistic cardiac ODE models into JavaScript for the first release.**

Run scientific simulation server-side in Python/native compiled code. Keep the browser responsible for controls, rendering, export, and presentation.

---

# 4. Public model assets: Codex should download these itself

Do not ask the user to upload the following public model files.

For every downloaded source:
1. record source URL;
2. record download date;
3. record Git commit / PMR revision;
4. compute SHA-256;
5. record license/status;
6. store these in `backend/app/models/manifest.json`.

Never silently replace a pinned model with a newer upstream revision.

---

# 5. CORE ventricular models

## 5.1 ToR-ORd-dynCl — PRIMARY adult ventricular model

**Use:** Main adult human ventricular baseline.

Official/source repository:
```text
https://github.com/jtmff/torord
```

Clone:
```bash
git clone https://github.com/jtmff/torord.git external/torord
```

Primary files:
```text
external/torord/cellml/ToRORd_dynCl_endo.cellml
external/torord/cellml/ToRORd_dynCl_epi.cellml
external/torord/cellml/ToRORd_dynCl_mid.cellml
```

The legacy app used endocardial by default. Add epi/mid only after endocardial baseline passes regression.

### IMPORTANT: correct 9-parameter base-variable mapping

For the official ToR-ORd-dynCl CellML, use the baseline/native parameters, not derived cell-type-scaled variables:

```text
canonical g_Na   -> INa.GNa
canonical g_NaL  -> INaL.GNaL_b
canonical g_to   -> Ito.Gto_b
canonical g_Kr   -> IKr.GKr_b
canonical g_Ks   -> IKs.GKs_b
canonical g_K1   -> IK1.GK1_b
canonical g_NaCa -> INaCa.Gncx_b
canonical g_NaK  -> INaK.Pnak_b
canonical g_CaL  -> ICaL.PCa_b
```

Expected endocardial baseline values from the official model:

```text
GNa     = 11.7802
GNaL_b  = 0.0279
Gto_b   = 0.16
GKr_b   = 0.0321
GKs_b   = 0.0011
GK1_b   = 0.6992
Gncx_b  = 0.0034
Pnak_b  = 15.4509
PCa_b   = 8.3757e-05
```

### Known legacy bug to fix
The old mechanistic validation accepted 9 Grandits parameters but the ToR registry exposed only 7 knobs, so:
- `Gncx_b -> g_NaCa`
- `Pnak_b -> g_NaK`

were ignored during ToR validation.

This must become a true **9/9 mapping**.

---

## 5.2 BPS2020 ventricular

Official Physiome Model Repository workspace:
```text
https://models.cellml.org/workspace/711
```

Known pinned CellML revision:
```text
https://models.cellml.org/workspace/711/rawfile/c8dc3b237a23e43c99a5d4a768313d5c6bc3ce18/BPS2020.cellml
```

Download as:
```text
model_assets/ventricular/BPS2020.cellml
```

Important version note:
The repository updated the default extracellular Ca concentration to **1.7 mM** on 2024-11-22 after author feedback. Record this in the manifest and do not mix baseline output from an older BPS2020 revision with this file.

Do not rely on the user's old local `BPS2020.mmt` without identifying its origin/revision.

---

## 5.3 O'Hara-Rudy / ORd 2011

For a curated Myokit implementation, use:
```text
https://github.com/myokit/models
```

Clone:
```bash
git clone https://github.com/myokit/models.git external/myokit-models
```

File:
```text
external/myokit-models/c/ohara-2011.mmt
```

Use this as a stable Myokit-compatible ORd implementation after verifying its metadata/version.

The legacy file `Cardiac AP.py` references `ord-2011-apd.txt`; do not preserve that odd filename dependency as the canonical source.

---

## 5.4 Grandits ventricular neural emulator

Official repository:
```text
https://github.com/thomgrand/cardiomyocyte_emulator
```

Clone:
```bash
git clone https://github.com/thomgrand/cardiomyocyte_emulator.git external/grandits_emulator
```

Important files:
```text
cardiomyocyte_emulator/emulator.py
cardiomyocyte_emulator/inverse.py
cardiomyocyte_emulator/emulator_state.pt
cardiomyocyte_emulator/emulator_hyperparams.npz
```

This is used for:
- fast AP emulation
- inverse fitting
- conductance estimation

The pretrained emulator's parameter-space center closely matches ToR-ORd baseline, which is why it is suitable for the existing inverse-fit → ToR validation workflow.

Expected approximate centers:

```text
GNa      ~ 11.7795
GNaL_b   ~ 0.0278983
Gto_b    ~ 0.159990
GKr_b    ~ 0.032099
GKs_b    ~ 0.00109994
GK1_b    ~ 0.699155
Gncx_b   ~ 0.00339979
Pnak_b   ~ 15.44995
PCa_b    ~ 8.37545e-05
```

**License warning:** repository states AGPL. Record and review implications before public deployment.

---

## 5.5 Simone–Trancuccio human iPSC ventricular / Timothy syndrome

Official PMR workspace:
```text
https://models.cellml.org/workspace/d92
```

Pinned known source revision:

Main:
```text
https://models.cellml.org/workspace/d92/rawfile/83903a0ad0a326782c7f35c4d51e9cea5dc6e90a/Main_Simone_Trancuccio_2025.m
```

Model:
```text
https://models.cellml.org/workspace/d92/rawfile/83903a0ad0a326782c7f35c4d51e9cea5dc6e90a/Simone_Trancuccio2025.m
```

Download into:
```text
model_assets/ventricular/simone/
```

Keep:
- WT
- Timothy syndrome / fractional_TS = 0.22

### Production rule
The current `simone_trancuccio_backend.py` dynamically translates MATLAB and calls `exec()`.
Do not use dynamic translation + `exec()` as the final production backend.

Instead:
1. preserve the old backend for regression;
2. create a static Python translation;
3. compare static Python output against original MATLAB model under identical conditions;
4. freeze it only after the trace and key metrics agree within defined tolerance.

**License warning:** the source explicitly states **NON-COMMERCIAL USE ONLY**.  
The app must display/track this restriction, and public/commercial deployment must not assume permission.

---

## 5.6 OPTIONAL latest ventricular: Avezzu human fetal ventricular model (2026)

This is not a replacement for adult ToR-ORd. It is a fetal ventricular model and should be clearly labeled.

Official PMR workspace:
```text
https://models.cellml.org/workspace/d90
```

Current final published-model file listed by PMR:
```text
HFVM_model_Avezzu2025.cellml
```

Use only as an optional developmental/fetal model. Do not show it under "adult ventricular baseline."

---

# 6. CORE atrial models

## 6.1 Grandi 2011 human atrial

Keep as the classic/legacy human atrial baseline.

Official PMR exposure:
```text
https://models.cellml.org/e/596
```

File:
```text
grandi_2011_atrial_with_meta.cellml
```

Alternative curated Myokit implementation:
```text
external/myokit-models/c/grandi-2011.mmt
```

For first-release reliability, the curated Myokit MMT may be easier to integrate. Preserve the original PMR/Grandi citation in the model metadata.

---

## 6.2 Ni–Morotti–Grandi 2023 human atrial signaling model — HIGH PRIORITY ADVANCED ATRIAL

This is an important modern atrial model because it integrates:
- electrophysiology
- Ca handling
- PKA signaling
- CaMKII signaling
- beta-adrenergic signaling
- atrial-specific currents including IKur, IK2P, and SK-related mechanisms

Official/source repository:
```text
https://github.com/drgrandilab/Ni-et-al-2023-Human-Atrial-Signaling-Model
```

Clone:
```bash
git clone https://github.com/drgrandilab/Ni-et-al-2023-Human-Atrial-Signaling-Model.git external/ni_2023_atrial
```

Do **not** initially integrate the entire 2-D tissue framework.

Focus on:
```text
Single_Cells/
```

Important entry/reference files include:
```text
Single_Cells/main_HAM_Signalling_cvode_new.cpp
Single_Cells/lib/
Single_Cells/lib/LTCC_Markov.cpp
Single_Cells/lib/SingleCellParameter.cpp
Single_Cells/lib/betaAR_update.hpp
Single_Cells/lib/cvode_function.cpp
Single_Cells/lib/cvode_solver.hpp
Single_Cells/lib/signalling_para.cpp
Single_Cells/lib/stimulus.cpp
Single_Cells/readme.md
```

The repository's single-cell README reports a reference invocation:

```bash
./main_HAM_Signalling_cvode_new 1000 0 0 0 0
```

and sample 1-Hz steady-state output with APD90 approximately:
```text
288.77 ms
```

Use the repository's sample outputs as a regression reference.

### Integration recommendation
Do not translate the whole C++ code to JavaScript.

Preferred options:
1. compile the single-cell C++ backend in the server container and wrap it with a strict Python adapter; or
2. port to static Python/Cython only after baseline numerical equivalence is established.

The web API should expose higher-level physiological inputs, not arbitrary internal C++ state variables.

---

## 6.3 Herrera et al. 2025 sex-specific human atrial model — HIGH PRIORITY

Official/source repository:
```text
https://github.com/drgrandilab/Herrera-et-al-2025-Sex-Specific-Human-Atrial-Model
```

Clone:
```bash
git clone https://github.com/drgrandilab/Herrera-et-al-2025-Sex-Specific-Human-Atrial-Model.git external/herrera_2025_atrial
```

Focus first on:
```text
Single Cell/
```

Important files:
```text
Single Cell/Main_platform.m
Single Cell/NH_single_cell.m
Single Cell/NH_ODE.m
Single Cell/NH_ECC.m
Single Cell/NH_BetaAR.m
Single Cell/NH_cam.m
Single Cell/NH_camkii.m
Single Cell/IKr_ODE.m
Single Cell/LTCC_mode_1.m
Single Cell/LTCC_mode_2.m
Single Cell/sex_diff.m
```

Important provided steady-state initial-condition files:

```text
Single Cell/yfin_nSR_1Hz_0_ISO_male.mat
Single Cell/yfin_nSR_1Hz_0_ISO_female.mat
Single Cell/yfin_cAF_1Hz_0_ISO_male.mat
Single Cell/yfin_cAF_1Hz_0_ISO_female.mat
```

The UI should ultimately expose four clear variants:

```text
Male / normal sinus rhythm
Female / normal sinus rhythm
Male / chronic AF
Female / chronic AF
```

### Integration recommendation
Do not make MATLAB a production runtime dependency.

Use the original MATLAB files as authoritative reference. Port the single-cell equations to a static Python/native backend and establish regression tests against the original model before enabling it in production.

---

## 6.4 Meier/Heijman atrial SK trafficking model — OPTIONAL ADVANCED

Repository:
```text
https://github.com/HeijmanLab/SK-trafficking
```

Clone:
```bash
git clone https://github.com/HeijmanLab/SK-trafficking.git external/heijman_sk_trafficking
```

Use only after the core atrial models are stable.

This model is useful for:
- high-rate dependent SK trafficking
- AF-related remodeling
- time-dependent membrane trafficking

It is not required for the MVP.

---

## 6.5 MBS2023 / Mazhar-Bartolucci-Severi atrial electromechanics — OPTIONAL

Use only if the app expands from pure electrophysiology into:
- Ca transient
- contractility
- force
- mechano-electric feedback
- mechano-calcium feedback

Do not block the initial AP Web App on this model.

---

# 7. CORE pacemaker / SAN models

## 7.1 Fabbri 2017 human SAN — CLASSIC BASELINE

Prefer one of these two sources:

### A. Official PMR
Workspace:
```text
https://models.cellml.org/workspace/486
```

File:
```text
HumanSAN_Fabbri_Fantini_Wilders_Severi_2017.cellml
```

### B. Curated Myokit version
From:
```text
https://github.com/myokit/models
```

File:
```text
external/myokit-models/c/fabbri-2017.mmt
```

For the Web App, use the Myokit version if it passes baseline validation and makes the backend simpler, but retain official publication/source metadata.

Fabbri is an intrinsic pacemaker model:
- no forced external stimulus by default;
- report spontaneous cycle length / beating rate;
- APD metrics need pacemaker-specific handling.

---

## 7.2 Linder–Fabbri 2025 human SAN + beta-adrenergic signaling — HIGH PRIORITY

Official PMR workspace:
```text
https://models.cellml.org/workspace/c65
```

The workspace contains an extended Fabbri human SAN model with AC–cAMP–PKA / beta-adrenergic signaling. Keep it separate from the classic Fabbri asset even if filenames overlap.

Download/store separately:

```text
model_assets/pacemaker/fabbri_2017_classic/
model_assets/pacemaker/linder_fabbri_2025_betaAR/
```

The PMR workspace description reports study of:
```text
extracellular Ca2+: 0.6–1.8 mM
isoprenaline / ISO: 0–1000 nM
```

### UI controls to expose for Linder-Fabbri
At minimum:
```text
extracellular Ca2+ concentration
isoprenaline / ISO concentration
```

The primary output should include:
```text
cycle length
beating rate
maximum diastolic potential
maximum upstroke velocity
AP amplitude
APD-like metrics if appropriate
```

---

# 8. Additional optional models — do NOT block MVP

## Ventricular: Fullerton repolarization-reserve model
Repository:
```text
https://github.com/Christini-Lab/rrc-conductance-profile
```

Useful for repolarization reserve / INaL studies.

## Ventricular: Meier 2023 Kv11.1/hERG trafficking
HeijmanLab code:
```text
https://github.com/HeijmanLab
```
Search/use the repository associated with the Kv11.1 ion-channel trafficking publication.  
This is a specialist long-timescale trafficking model, not a replacement for ToR-ORd.

## Ventricular electromechanics: Margara / ToR-ORd + Land
A modern maintained implementation exists at:
```text
https://github.com/GSK-Biostatistics/CellContraction.jl
```
It is Julia and should remain a later electromechanics module.

## 2026 fetal ventricular: Avezzu
PMR:
```text
https://models.cellml.org/workspace/d90
```

Keep clearly separated from adult ventricular.

---

# 9. Model priority for implementation

## Phase A — MUST work before UI is considered scientifically complete

### Adult ventricular
1. ToR-ORd-dynCl endocardial
2. BPS2020
3. ORd 2011

### Atrial
4. Grandi 2011

### Pacemaker
5. Fabbri 2017

### Existing advanced backends
6. Grandits emulator
7. Simone hiPSC / Timothy syndrome, subject to license restriction

These models should establish the common API, plotting, parameter controls, currents, pacing behavior, metrics, and comparison framework.

## Phase B — modern additions

8. Linder-Fabbri 2025 SAN beta-AR
9. Ni 2023 atrial signaling
10. Herrera 2025 sex-specific atrial

## Phase C — specialist models

11. Meier atrial SK trafficking
12. Fullerton repolarization reserve
13. Meier ventricular Kv11.1 trafficking
14. MBS2023 atrial electromechanics
15. Margara/ToR-ORd-Land electromechanics
16. Avezzu fetal ventricular

Do not delay completion of Phase A for Phase C.

---

# 10. Unified model registry specification

Create a machine-readable registry. Every model should have fields similar to:

```json
{
  "id": "torord_dyncl_endo",
  "display_name": "ToR-ORd-dynCl Endocardial",
  "category": "ventricular",
  "species": "human",
  "developmental_stage": "adult",
  "backend": "myokit",
  "source_file": "model_assets/ventricular/ToRORd_dynCl_endo.cellml",
  "source_url": "...",
  "source_revision": "...",
  "sha256": "...",
  "publication": {
    "authors": "...",
    "year": 2020,
    "doi": "..."
  },
  "license": {
    "status": "...",
    "notes": "..."
  },
  "pacing": {
    "mode": "external",
    "default_frequency_hz": 1.0,
    "default_duration_ms": 1.0
  },
  "parameters": {},
  "currents": {},
  "outputs": ["Vm", "currents", "Ca"]
}
```

Never infer model identity from filenames alone.

---

# 11. Parameter-control design

Do **not** present every model with a misleading set of identical absolute parameter values.

For each parameter display:

```text
Canonical concept
Native model variable
Native unit
Native baseline value
Current value
Relative scale vs baseline (%)
```

Example:

```text
Rapid delayed rectifier K+ current strength
Canonical: g_Kr
ToR native: IKr.GKr_b
Baseline: 0.0321 mS/uF
Scale: 100%
```

The safest primary UI control is a relative multiplier:

```text
0% ... 50% ... 100% ... 200% ...
```

with an optional advanced native-value editor.

This avoids falsely implying that `g_CaL` in one model has the same physical definition/unit as `g_CaL` in another model.

---

# 12. Common canonical parameter vocabulary

Support at least:

```text
g_Na
g_NaL
g_CaL
g_CaT
g_f
g_to
g_Kr
g_Ks
g_K1
g_Kur
g_KACh
g_NaCa
g_NaK
```

But each model registry entry must declare which are actually supported.

Unsupported controls must be disabled, not silently ignored.

---

# 13. Standard current vocabulary

Normalize display names without destroying native provenance:

```text
INa
INaL
ICaL
ICaT
If
Ito
IKr
IKs
IK1
IKur
IKACh
INaCa
INaK
IpCa
IbNa
IbCa
Istim
```

Every returned current must include:
- display current name;
- native variable name;
- original unit;
- converted/display unit;
- conversion method.

Do not convert currents to pA unless conversion is physically well-defined from the source unit and capacitance.

---

# 14. Simulation result API

Use a backend-neutral schema such as:

```json
{
  "model_id": "...",
  "model_version": "...",
  "backend": "...",
  "settings_requested": {},
  "settings_actual": {},
  "time_ms": [],
  "voltage_mv": [],
  "calcium": {},
  "currents": {
    "IKr": {
      "values": [],
      "unit": "pA",
      "native_name": "IKr.IKr",
      "native_unit": "uA/uF"
    }
  },
  "metrics": {},
  "warnings": [],
  "provenance": {}
}
```

Critical rule: `settings_requested` and `settings_actual` must both exist.

This prevents hidden stimulus changes from being invisible.

---

# 15. Fix the legacy auto-rescue behavior

The legacy forward simulator automatically retries a flat AP with:
- opposite stimulus polarity;
- 2×, 4×, 8× stimulus strength;
- altered duration.

This is acceptable only as an explicit troubleshooting feature.

Production behavior:

```text
Auto rescue = OFF by default
```

If enabled:
- clearly label result as rescued;
- show original requested stimulus;
- show actual stimulus used;
- never mix rescued and non-rescued traces in scientific comparison without warning.

---

# 16. Rewrite the AP metric engine

Do not reuse the legacy `vmin + 10% amplitude` / first-two-crossings APD90 algorithm as the sole metric method.

Implement beat-aware analysis.

## Ventricular/atrial paced-cell metrics

For each selected beat:
- stimulus/upstroke time
- resting potential before upstroke
- peak voltage
- action-potential amplitude
- maximum dV/dt
- APD30
- APD50
- APD80
- APD90
- triangulation (for example APD90 - APD30)
- EAD detection
- DAD/triggered event flag where feasible

Algorithm must:
1. identify a valid upstroke;
2. identify the corresponding peak;
3. find post-peak repolarization crossings;
4. avoid using a prior/following beat crossing;
5. return "not measurable" instead of a misleading number when the beat is abnormal.

## Pacemaker/SAN metrics

Add:
- cycle length
- beating rate
- maximum diastolic potential
- peak voltage
- AP amplitude
- maximum upstroke velocity
- diastolic depolarization slope
- optional APD metrics when meaningful

Pacemaker models must not be treated as forced ventricular beats.

---

# 17. Baseline and numerical validation requirements

No model becomes "enabled" in the public UI until it passes a baseline test.

For each model store a regression artifact:

```text
tests/reference/<model_id>/
    baseline.json
    baseline_trace.csv or compressed npz
    provenance.json
```

At minimum test:
- simulation completes;
- trace contains finite values;
- voltage range is plausible;
- expected beat/spontaneous activity exists;
- AP metrics are within stored tolerance;
- key current traces are present;
- stimulus behavior is correct.

Whenever upstream model source changes, baseline regression should fail until reviewed.

---

# 18. Perturbation-direction tests

For core models, test at least:
- g_Na down
- g_CaL down
- g_Kr down
- g_K1 down
- g_NaL up

Do not assert simplistic exact physiological behavior for every model; instead record expected qualitative effects only where validated.

Examples that can be used as sanity checks:
- strong g_Na reduction should reduce excitability/upstroke in externally paced ventricular models;
- IKr reduction generally tends to prolong repolarization in normal adult ventricular models;
- extreme parameter changes may cause failed AP/EADs and should be reported rather than auto-corrected.

---

# 19. Grandits inverse fitting module

Keep fitting separate from forward simulation.

Recommended Web App flow:

```text
Upload CSV
   ↓
Choose trace / time column
   ↓
Calibrate voltage or dF/F
   ↓
Choose Reference / Mutant mode
   ↓
Fit with Grandits emulator
   ↓
Show fitted 9 conductances + confidence/limits
   ↓
Mechanistic validation in ToR-ORd
   ↓
Overlay experimental / emulator / mechanistic traces
```

### Mandatory 9/9 validation fix

Grandits names:
```text
GNa
GNaL_b
Gto_b
GKr_b
GKs_b
GK1_b
Gncx_b
Pnak_b
PCa_b
```

Map to:
```text
g_Na
g_NaL
g_to
g_Kr
g_Ks
g_K1
g_NaCa
g_NaK
g_CaL
```

Then map those to the ToR native base variables listed in section 5.1.

If any parameter cannot be applied, the validation request must fail loudly or show a high-visibility "ignored parameter" warning. Never silently validate 7/9 and display it as full validation.

---

# 20. Web UI: required pages/modules

## A. Simulator

Controls:
- model family/category
- model
- model variant/cell type
- pacing/spontaneous mode
- frequency/BCL
- stimulus strength
- stimulus duration
- stimulus offset
- prepace beats
- parameter multipliers
- advanced native values

Outputs:
- AP trace
- Ca trace when available
- ionic currents
- biomarkers/metrics
- provenance/model version
- warnings

## B. Compare

Restore the useful idea from `Two_cardiac_models.py`.

Allow 2–4 simulations to be overlaid:
- same model with different parameters, or
- different models

Comparison must explicitly show:
- model name/version
- pacing differences
- cell type
- parameter changes
- requested/actual stimulus

Do not imply that absolute conductance values are comparable across different model formulations.

## C. Fitting

Recreate the workflow from `fit_vtrace_csv_emulator_ui.py`:
- upload CSV
- choose voltage-like traces
- Reference → Mutant fit
- choose fitted conductances
- set percentage constraints/directions
- display result table
- Grandits fitted trace
- mechanistic validation trace
- export result

## D. Model information

For every model show:
- citation
- DOI
- source URL
- source revision
- SHA-256
- cell type
- backend
- supported currents
- supported controls
- known limitations
- license/reuse note

---

# 21. Initial model selector design

Recommended user-facing hierarchy:

```text
Ventricular
  Adult
    ToR-ORd-dynCl
      Endocardial
      Epicardial
      Midmyocardial
    BPS2020
    ORd 2011

  hiPSC
    Simone–Trancuccio
      WT
      Timothy syndrome 22%

  Emulator
    Grandits ventricular emulator

  Developmental
    Avezzu fetal ventricular [optional]

Atrial
  Grandi 2011
  Ni 2023 signaling [advanced]
  Herrera 2025 sex-specific
    Male nSR
    Female nSR
    Male cAF
    Female cAF
  Meier SK trafficking [advanced/optional]

Pacemaker / SAN
  Fabbri 2017
  Linder-Fabbri 2025 beta-AR
```

Do not mix fetal, hiPSC, adult ventricular, atrial, and SAN entries in a flat list.

---

# 22. Scientific provenance and model versioning

Create `manifest.json`.

For every model include:

```text
model_id
model_name
publication_year
publication DOI
source repository
source file
source commit/revision
download date
SHA256
license/status
backend
default cell type
default extracellular ions
default temperature if model-specific
default pacing
default capacitance
notes
```

The Web UI should expose this provenance in an "About this model" panel.

---

# 23. Licensing / deployment blockers

Do not treat "publicly downloadable" as identical to "unrestricted commercial redistribution."

At minimum flag:

### Grandits emulator
Repository declares AGPL.

### Simone–Trancuccio
Source explicitly says:
```text
NON-COMMERCIAL USE ONLY
```

### ToR-ORd repository
Review the repository license and redistribution obligations before bundling/deploying.

### PMR / CellML models
Record each exposure/workspace license/citation information. Fabbri's published PMR exposure states CC BY 3.0. Other models may have repository-level/public-access terms or unspecified model-specific fields.

### Ni/Herrera/Heijman GitHub models
Inspect repository LICENSE files. If no explicit license exists, mark:
```text
license_status = review_required
```
and do not invent a permissive license.

Create a visible `LICENSE_NOTES.md`.

This is not a substitute for legal review if the app becomes commercial.

---

# 24. Runtime/download policy

Do **not** download model code from the internet every time the user runs a simulation.

Correct workflow:
1. developer/Codex downloads model source;
2. revision is pinned;
3. checksum is recorded;
4. validated model asset is vendored or built into deployment;
5. runtime uses only the pinned local asset.

This guarantees reproducibility.

---

# 25. Myokit deployment checklist

Codex must verify all of the following inside the production container:

```text
python --version
myokit version
C/C++ compiler available
SUNDIALS/CVODES available
Myokit single-cell simulation compiles
CellML import works
MMT load works
headless server requires no Qt/PyQtGraph
```

PyQtGraph and Qt must not be required for the backend.

The legacy desktop GUI imports should be removed from scientific modules.

---

# 26. Security / stability constraints

- Never execute arbitrary uploaded Python/MATLAB code.
- CSV uploads are data only.
- Put file-size limits on uploads.
- Validate numeric arrays.
- Apply simulation-duration and prepace limits.
- Apply server timeout limits.
- Avoid unrestricted `exec()` in production.
- Do not allow arbitrary filesystem paths from API input.
- Do not return server filesystem paths to the browser.
- Log model/version/settings for every simulation.

---

# 27. Performance

First optimize correctness.

Then:
- cache parsed/compiled models;
- reuse precompiled Myokit model artifacts when safe;
- cache steady-state initial conditions by model/BCL when scientifically valid;
- batch emulator evaluations;
- use CPU Torch unless GPU is explicitly needed;
- keep large current arrays optional;
- downsample only for browser display, not scientific metric calculation.

Never calculate APD from the display-downsampled trace if a higher-resolution trace exists.

---

# 28. API endpoints

Recommended minimum:

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

Do not make frontend components call model-specific scripts directly.

---

# 29. Example `/api/simulate` request

```json
{
  "model_id": "torord_dyncl_endo",
  "duration_ms": 1000,
  "pacing": {
    "frequency_hz": 1.0,
    "stimulus_duration_ms": 1.0,
    "stimulus_strength_nA": 1.1,
    "offset_ms": 200
  },
  "prepace_beats": 50,
  "parameters": {
    "g_Kr": {"scale": 0.5},
    "g_CaL": {"scale": 1.0}
  },
  "include_currents": ["IKr", "ICaL", "INa"],
  "auto_rescue": false
}
```

---

# 30. Required tests before calling the Web App complete

## Unit tests
- unit conversions
- time conversions
- parameter scaling
- model registry validation
- stimulus conversion
- metric engine
- abnormal AP handling
- pacemaker cycle detection
- 9/9 Grandits mapping

## Integration tests
- each Phase A model baseline runs
- compare endpoint runs two models
- current output is present
- CSV fitting loads
- Grandits fit returns 9 parameters
- mechanistic validation applies 9/9 to ToR
- model provenance is returned
- no Qt dependency in backend

## Regression tests
For every enabled model:
- baseline voltage trace
- key metrics
- selected current peaks
- protocol settings
- source hash

Use tolerances; do not use exact floating-point equality.

---

# 31. Scientific acceptance criteria for Phase A

Phase A is successful when:

```text
[ ] ToR-ORd endocardial runs from pinned official source
[ ] BPS2020 runs from pinned official source
[ ] ORd 2011 runs
[ ] Grandi 2011 runs
[ ] Fabbri 2017 runs spontaneously
[ ] Grandits emulator runs
[ ] Simone WT and TS run OR are intentionally disabled with license/status explanation
[ ] no Qt/PyQtGraph is required server-side
[ ] all enabled models expose provenance
[ ] AP metrics are beat-aware
[ ] pacemaker metrics are separate
[ ] auto-rescue is OFF by default
[ ] requested vs actual stimulus is reported
[ ] parameter controls use native metadata + relative scaling
[ ] model comparison works
[ ] results export to CSV/JSON
```

---

# 32. Scientific acceptance criteria for Phase B

```text
[ ] Linder-Fabbri 2025 runs and exposes [Ca2+]o + ISO
[ ] Ni 2023 single-cell model runs from pinned source
[ ] Ni 2023 regression matches repository sample output within tolerance
[ ] Herrera 2025 model runs
[ ] four Herrera states/variants are available:
    male nSR
    female nSR
    male cAF
    female cAF
[ ] original MATLAB/C++ source remains in external/reference folder
[ ] translated/wrapped implementations have regression tests
```

---

# 33. Fitting acceptance criteria

```text
[ ] CSV import is robust
[ ] time units are explicit after import
[ ] voltage calibration is visible
[ ] reference/mutant mode works
[ ] fit parameters can be selected/locked/constrained
[ ] all 9 Grandits parameters are returned
[ ] all 9 can map to ToR-ORd validation
[ ] ignored parameters are never silent
[ ] emulator and mechanistic validation traces are shown separately
[ ] parameter table reports baseline, fitted value, and percent change
[ ] fitting settings are exportable with result
```

---

# 34. Download bootstrap commands

Codex should create a script such as `scripts/fetch_models.sh`.

Suggested initial commands:

```bash
set -euo pipefail

mkdir -p external model_assets/ventricular model_assets/atrial model_assets/pacemaker

git clone https://github.com/jtmff/torord.git external/torord
git clone https://github.com/myokit/models.git external/myokit-models
git clone https://github.com/thomgrand/cardiomyocyte_emulator.git external/grandits_emulator

git clone https://github.com/drgrandilab/Ni-et-al-2023-Human-Atrial-Signaling-Model.git external/ni_2023_atrial
git clone https://github.com/drgrandilab/Herrera-et-al-2025-Sex-Specific-Human-Atrial-Model.git external/herrera_2025_atrial

git clone https://github.com/HeijmanLab/SK-trafficking.git external/heijman_sk_trafficking || true
git clone https://github.com/Christini-Lab/rrc-conductance-profile.git external/fullerton_rrc || true

curl -L \
  "https://models.cellml.org/workspace/711/rawfile/c8dc3b237a23e43c99a5d4a768313d5c6bc3ce18/BPS2020.cellml" \
  -o model_assets/ventricular/BPS2020.cellml

mkdir -p model_assets/ventricular/simone

curl -L \
  "https://models.cellml.org/workspace/d92/rawfile/83903a0ad0a326782c7f35c4d51e9cea5dc6e90a/Simone_Trancuccio2025.m" \
  -o model_assets/ventricular/simone/Simone_Trancuccio2025.m

curl -L \
  "https://models.cellml.org/workspace/d92/rawfile/83903a0ad0a326782c7f35c4d51e9cea5dc6e90a/Main_Simone_Trancuccio_2025.m" \
  -o model_assets/ventricular/simone/Main_Simone_Trancuccio_2025.m
```

For Fabbri/Linder and Avezzu, fetch from the PMR workspaces:

```text
Classic Fabbri:
https://models.cellml.org/workspace/486

Linder-Fabbri 2025:
https://models.cellml.org/workspace/c65

Avezzu fetal ventricular:
https://models.cellml.org/workspace/d90
```

Codex should pin the exact workspace revision it downloads and save the revision/checksum to `manifest.json`.

---

# 35. What NOT to do

Do **not**:
- directly convert the old Qt GUI into a browser UI line-by-line;
- preserve personal filesystem paths;
- hide model versions;
- silently use "latest" upstream model revisions;
- silently ignore unsupported fitted parameters;
- silently rescue failed stimulation;
- treat `g_CaL`, `g_Kr`, etc. as identical physical variables across all models;
- compare raw absolute conductances across model families without context;
- run MATLAB `exec()`-style translation in production;
- require Qt on the web server;
- calculate scientific metrics only on downsampled display data;
- label hiPSC/fetal models as adult ventricular models;
- call a fitting result "mechanistically validated" unless every intended mapped parameter is actually applied;
- expose a non-commercial model as unrestricted.

---

# 36. Recommended development order

### Stage 1 — preserve legacy reference
Copy all five Python files into `legacy/`.  
Do not edit them destructively.

### Stage 2 — model/source bootstrap
Fetch and pin:
- ToR
- BPS
- Myokit curated models
- Grandits
- Simone
- classic Fabbri
- Linder-Fabbri

Create `manifest.json`.

### Stage 3 — scientific core
Implement:
- unified schemas
- units
- pacing
- metrics
- model registry
- backend interface

### Stage 4 — core adapters
Implement:
- Myokit
- Grandits
- Simone static backend

### Stage 5 — validation
Run baseline and perturbation regression before Web UI polish.

### Stage 6 — frontend
Implement Simulator and Compare.

### Stage 7 — fitting
Port the Grandits fitting workflow.

### Stage 8 — latest model expansion
Add:
- Linder-Fabbri
- Ni 2023
- Herrera 2025

### Stage 9 — optional specialists
Add trafficking/electromechanics/fetal models only after core scientific regression is stable.

---

# 37. Definition of "done"

The Web App is not done merely because it draws an AP curve.

It is done when:

1. Every enabled model has pinned provenance.
2. Baseline regressions pass.
3. Current/parameter mappings are explicit.
4. Units are traceable.
5. Requested and actual protocols are traceable.
6. AP/SAN biomarkers are robust.
7. Multi-model comparison works.
8. Results are exportable.
9. Grandits fitting performs full 9/9 ToR validation.
10. Modern atrial/SAN model additions have regression evidence.
11. Licensing/status is documented.
12. The app builds reproducibly in Docker/CI.
13. The backend runs headless without Qt.
14. Tests pass from a clean checkout.

---

# 38. Immediate first actions for Codex

Start now in this order:

```text
1. Read all files in legacy/.
2. Read docs/cardiac_ap_model_audit.md.
3. Create repo structure.
4. Create scripts/fetch_models.sh.
5. Download/pin model sources.
6. Create model manifest.
7. Extract scientific logic from Cardiac AP.py into backend modules.
8. Implement/fix ToR 9-parameter mapping.
9. Implement robust metrics.
10. Get ToR/BPS/ORd/Grandi/Fabbri baselines passing tests.
11. Integrate Grandits emulator.
12. Rebuild Simone as static backend and regression-test it.
13. Build FastAPI endpoints.
14. Build Simulator + Compare UI.
15. Port fitting workflow.
16. Add Linder-Fabbri.
17. Add Ni 2023.
18. Add Herrera 2025.
19. Run full CI and generate a model-validation report.
```

Do not pause after scaffolding. Continue until blocked by a real scientific/license ambiguity or an unrecoverable dependency issue. When blocked, document the exact blocker, keep unaffected models working, and proceed with the rest.

---

# 39. Deliverables Codex should leave in the repository

At the end, provide:

```text
working Web App
Docker build
model manifest
fetch script
baseline regression data
test suite
scientific validation report
license/provenance notes
README with setup/deployment instructions
migration notes mapping legacy files/functions to new modules
known limitations
```

The legacy Python files should remain archived under `legacy/` for traceability.

---

# 40. Key external references

Myokit model list:
```text
https://github.com/myokit/model-list
```

Myokit curated models:
```text
https://github.com/myokit/models
```

ToR-ORd:
```text
https://github.com/jtmff/torord
```

BPS2020:
```text
https://models.cellml.org/workspace/711
```

Grandits emulator:
```text
https://github.com/thomgrand/cardiomyocyte_emulator
```

Classic Fabbri SAN:
```text
https://models.cellml.org/workspace/486
```

Linder-Fabbri 2025:
```text
https://models.cellml.org/workspace/c65
```

Ni 2023 atrial signaling:
```text
https://github.com/drgrandilab/Ni-et-al-2023-Human-Atrial-Signaling-Model
```

Herrera 2025 sex-specific atrial:
```text
https://github.com/drgrandilab/Herrera-et-al-2025-Sex-Specific-Human-Atrial-Model
```

Heijman SK trafficking:
```text
https://github.com/HeijmanLab/SK-trafficking
```

Fullerton repolarization-reserve code:
```text
https://github.com/Christini-Lab/rrc-conductance-profile
```

Simone–Trancuccio:
```text
https://models.cellml.org/workspace/d92
```

Avezzu fetal ventricular:
```text
https://models.cellml.org/workspace/d90
```

---

## Final priority statement

For the first scientifically trustworthy release, prioritize:

```text
ToR-ORd + BPS2020 + ORd
Grandi 2011
Fabbri 2017
Grandits emulator
Simone hiPSC (only with clear license handling)
```

Then add the most useful modern upgrades:

```text
Linder-Fabbri 2025
Ni 2023
Herrera 2025
```

The most important scientific correction to the legacy code is the **Grandits → ToR full 9/9 parameter mapping**, followed by model version pinning, robust beat-aware biomarkers, and transparent stimulus handling.
