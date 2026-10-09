# Cardiac Action Potential Python Code — Model & Reproducibility Audit

Date: 2026-10-07

## Executive conclusion

The codebase is best understood as one legacy comparator plus one later generalized simulator and one inverse-fitting branch:

- `Two_cardiac_models.py` — legacy 2-model desktop comparator.
- `Cardiac AP.py` — current main forward-simulation architecture.
- `simone_trancuccio_backend.py` — specialized Simone/Trancuccio hiPSC backend used by `Cardiac AP.py`.
- `fit_vtrace_csv_emulator.py` — inverse fitting engine using the Grandits neural AP emulator and optional mechanistic validation.
- `fit_vtrace_csv_emulator_ui.py` — desktop UI for the fitting engine.

For a future web app, the architectural source of truth should be the model registry / simulation interface in `Cardiac AP.py`, but it should be refactored before deployment rather than ported verbatim.

## Audit status

### Completed
- Python syntax compilation for all five uploaded files: PASS.
- Static dependency and architecture audit: PASS.
- Official model-source identification for ToR-ORd, BPS2020, Grandi 2011, Fabbri 2017, Simone/Trancuccio 2025/2026, and Grandits emulator: PASS.
- Grandits emulator conductance-name and training-range audit against the official pretrained package: PASS.
- Grandits center conductances vs ToR-ORd endocardial baseline audit: PASS; values match essentially exactly.
- Fitter-to-mechanistic parameter mapping audit: FAIL/PARTIAL — current ToR validation uses 7 of 9 fitted emulator parameters.
- Simone backend MATLAB-to-Python transform smoke tests: PASS for representative syntax.
- Stimulus/current unit-conversion helper checks: PASS.
- APD90 algorithm review: needs replacement for robust scientific use.
- Model licensing/deployment audit: multiple important restrictions identified.

### Not completed in this runtime
A full numerical Myokit regression run (baseline AP, APD90, currents, and parameter perturbations) could not be executed because this runtime lacks `myokit`, `pyqtgraph`, and system CVODES/SUNDIALS; package installation/network transfer is unavailable here. This is an execution-environment limitation, not a Python syntax failure. Therefore this report does **not** claim that all Myokit models have been numerically reproduced in this session.

## 1. Version / role classification

| File | Role | Recommendation |
|---|---|---|
| `Two_cardiac_models.py` | Early ToR-ORd/BPS2020 comparison GUI | Keep only as legacy/reference; salvage overlay comparison UX |
| `Cardiac AP.py` | Generalized forward simulator and model registry | Use as conceptual backend base after refactor |
| `simone_trancuccio_backend.py` | Simone/Trancuccio hiPSC numerical backend | Keep conceptually, but replace dynamic MATLAB translation at request time |
| `fit_vtrace_csv_emulator.py` | Inverse AP fitting + mechanistic validation | Keep as separate analysis service/module |
| `fit_vtrace_csv_emulator_ui.py` | Desktop fitting GUI | Do not port directly; rebuild UI for web |

## 2. Main simulator model registry

`Cardiac AP.py` currently represents eight entries:

1. ORd 2011 ventricular — Myokit
2. ToR-ORd-dynCl ventricular — Myokit
3. BPS2020 ventricular — Myokit
4. Grandi 2011 atrial — Myokit
5. Fabbri 2017 human SAN pacemaker — Myokit / intrinsic pacing
6. Simone 2026 hiPSC ventricular — SciPy/Python backend
7. Simone 2026 hiPSC ventricular, Timothy syndrome fraction 0.22 — SciPy/Python backend
8. Grandits 2024 ventricular neural emulator — PyTorch surrogate

This multi-backend registry is the strongest part of the current architecture and is a suitable concept for a web backend.

## 3. Grandits emulator ↔ ToR-ORd consistency

The official Grandits pretrained emulator uses these nine maximum-conductance inputs:

`GNa`, `GNaL_b`, `Gto_b`, `GKr_b`, `GKs_b`, `GK1_b`, `Gncx_b`, `Pnak_b`, `PCa_b`.

The official training bounds have lower bound 0 and the following upper bounds. Their centers are therefore upper/2:

| Parameter | Emulator center | Official ToR-ORd endo baseline | Result |
|---|---:|---:|---|
| GNa | 11.7795 | 11.7802 | match |
| GNaL_b | 0.0278983 | 0.0279 | match |
| Gto_b | 0.159990 | 0.16 | match |
| GKr_b | 0.0320990 | 0.0321 | match |
| GKs_b | 0.001099935 | 0.0011 | match |
| GK1_b | 0.699155 | 0.6992 | match |
| Gncx_b | 0.00339979 | 0.0034 | match |
| Pnak_b | 15.44995 | 15.4509 | match |
| PCa_b | 0.0000837545 | 0.000083757 | match |

This is strong evidence that the emulator integration was intentionally tied to the ToR-ORd parameterization and that the baseline setup is conceptually sound.

## 4. Critical defect: mechanistic validation is 7/9, not 9/9

The fitter correctly defines nine translations:

- GNa → g_Na
- GNaL_b → g_NaL
- Gto_b → g_to
- GKr_b → g_Kr
- GKs_b → g_Ks
- GK1_b → g_K1
- Gncx_b → g_NaCa
- Pnak_b → g_NaK
- PCa_b → g_CaL

However, the current ToR-ORd entry in `Cardiac AP.py` exposes only seven knobs: GNa, GNaL, Ito, IKr, IKs, IK1, ICaL. Therefore the validation helper discards `Gncx_b` and `Pnak_b` as unsupported.

### Recommended exact ToR-ORd 9-parameter mapping

For the endocardial ToR-ORd CellML, use the *baseline* variables corresponding to emulator inputs:

- `g_Na` → `INa.GNa`
- `g_NaL` → `INaL.GNaL_b`
- `g_to` → `Ito.Gto_b`
- `g_Kr` → `IKr.GKr_b`
- `g_Ks` → `IKs.GKs_b`
- `g_K1` → `IK1.GK1_b`
- `g_NaCa` → `INaCa.Gncx_b`
- `g_NaK` → `INaK.Pnak_b`
- `g_CaL` → `ICaL.PCa_b`

The current code often targets derived variables (`GKr`, `GKs`, `Gto`, etc.). For endocardial celltype these happen to equal the `_b` values, but mapping directly to `_b` variables is semantically correct and exactly matches the Grandits parameter definitions. It also prevents confusion if epi/mid-cell scaling is added later.

**Priority: P0 before claiming full mechanistic validation.**

## 5. Reproducibility / source-version problem

The early `Two_cardiac_models.py` expects canonical CellML files:

- `ToRORd_dynCl_endo.cellml`
- `BPS2020.cellml`

The later `Cardiac AP.py` instead expects local converted artifacts:

- `ToRORd_dynCl_endo.mmt`
- `BPS2020.mmt`

The provenance/version of those local MMT files is not encoded in the Python source. This is a reproducibility risk.

BPS2020 is especially important: the current Physiome workspace updated the default extracellular calcium to 1.7 mM in November 2024 following author feedback. An older local converted MMT may therefore not reproduce the current public CellML baseline.

### Recommendation
For the web app:
- Vendor/pin exact source revisions rather than downloading “latest” at runtime.
- Store upstream URL/repository, commit/revision hash, file SHA256, citation, and license in a model manifest.
- If converting CellML → MMT, commit both the canonical source metadata and the generated artifact, and test the conversion output.

## 6. APD90 algorithm needs replacement

Current logic:
- global Vmin/Vmax over the whole trace;
- threshold = Vmin + 10% × (Vmax − Vmin);
- APD90 = time difference between the first two threshold crossings.

This is acceptable only for a clean isolated single action potential. It can fail or become ambiguous for:
- multiple paced beats;
- SAN spontaneous rhythm;
- EAD/DAD;
- alternans;
- failed/partial depolarization;
- long traces containing baseline drift.

### Recommended metrics engine
Detect beats/upstrokes first, then compute per beat:
- MDP/resting Vm
- peak Vm
- APA
- dV/dtmax
- APD30/50/80/90 with post-peak crossing and linear interpolation
- cycle length / spontaneous rate for SAN
- optional EAD/DAD flags
- aggregate mean/last-beat values only after explicit beat selection.

**Priority: P0 for quantitative web results.**

## 7. Auto-rescue stimulation should not be silent

If a trace spans <30 mV, the current simulator automatically retries:
- both stimulus polarities;
- amplitude ×2, ×4, ×8;
- duration at least 1 or 2 ms.

This is useful for debugging but can turn a requested protocol into a different actual protocol.

### Recommendation
- Default `auto_rescue = false` for scientific use.
- If enabled, display both requested and actual protocol.
- Mark rescued simulations visually and in exported metadata.
- Do not use rescued traces as an unlabeled baseline/reference result.

## 8. Simone/Trancuccio backend

Positive findings:
- Python defaults correspond to the parameter formulas in the official Simone/Trancuccio MATLAB source.
- `fractional_TS = 0.22` is consistent with the source comment for Timothy syndrome.
- Representative MATLAB syntax transformations in the current translator pass smoke tests.

Risks:
- The backend translates MATLAB text with regex and executes generated Python via `exec()`.
- SciPy BDF settings differ from the official MATLAB setup, so numerical equivalence must be regression-tested.
- Current Python solver: BDF, rtol 1e-8, atol 1e-10, max step 0.005 s.
- Official MATLAB main uses ode15s with tighter tolerances (RelTol 1e-10, AbsTol 1e-11) and different max-step settings.

### Recommendation
Translate the official MATLAB equations once into reviewed Python source, commit that source, then create regression fixtures against official MATLAB output. Do not translate external MATLAB source dynamically in production requests.

## 9. Grandits emulator limitations

Positive:
- Official package and fitted parameter naming are consistent with ToR-ORd baseline.
- It is well suited for fast single-beat morphology exploration and inverse fitting.

Important caveats:
- It is a surrogate model, not a mechanistic ionic-current simulator.
- Official example usage evaluates approximately -10 to 500 ms; the current app allows longer evaluation. Extrapolation in time should be documented/limited unless validated.
- Conductance extrapolation beyond the emulator training range should remain disabled by default and be flagged as out-of-distribution if enabled.
- The published software repository is a reimplementation of the research code and the paper notes that performance/runtime may differ.

## 10. Fitting branch

The reference→mutant workflow is a strong design:

Experimental control trace → estimate baseline conductances → fit mutant with directional/fixed constraints → mechanistic validation.

Recommended improvements:
- Fix the 9/9 ToR mechanistic mapping first.
- Separate “emulator fit quality” from “mechanistic validation quality” in the result object/UI.
- Add explicit out-of-training-range diagnostics.
- Store optimizer seed/settings and input preprocessing in exported result metadata.
- Review best-loss checkpointing so saved parameter state corresponds exactly to the loss used for selection.

## 11. Portability issues

Remove hardcoded local paths such as `/Users/kh_lin/PycharmProjects/Analysis` and desktop CSV paths. The web backend should use:
- package-relative model resources;
- environment/config paths only where necessary;
- immutable model manifest IDs;
- no recursive search through user home directories.

## 12. Licensing / deployment gates

Before public/commercial deployment, perform a license review:
- Grandits emulator repository: AGPL.
- ToR-ORd public repository: GPLv3-or-later headers/repository license.
- Simone/Trancuccio MATLAB source explicitly states **NON-COMMERCIAL USE ONLY**.
- Fabbri CellML exposure: CC BY 3.0.
- BPS2020 Physiome exposure currently lists model-specific terms as unspecified.
- Grandi should also be checked at the exact pinned exposure/revision.

This is not legal advice, but it affects whether models can be bundled server-side and what source-sharing/usage obligations apply.

## 13. Web-app architecture recommendation

Do not translate the PyQt desktop app directly to JavaScript. Recommended architecture:

```
Model Manifest / Registry
        |
        +-- Mechanistic Myokit adapter
        +-- Simone fixed-Python adapter
        +-- Grandits emulator adapter
        |
Unified SimulationResult
        |
Beat-aware Metrics Engine
        |
REST/API layer
        |
Web UI
```

Keep inverse fitting separately:

```
Experimental Trace
      |
Preprocessing / alignment
      |
Grandits inverse fitting
      |
Parameter estimate + uncertainty/OOD diagnostics
      |
9-parameter ToR mechanistic validation
```

## 14. Priority list before a web app

### P0 — scientific correctness
1. Fix ToR-ORd 9/9 Grandits parameter mapping (`Gncx_b`, `Pnak_b` included; use `_b` variables).
2. Pin exact model source revisions and stop relying on untracked local `.mmt` files.
3. Replace APD90 with beat-aware metrics.
4. Make auto-rescue explicit/off by default.
5. Regression-test Simone Python vs official MATLAB.

### P1 — reproducibility and API design
6. Split simulation engine from PyQt UI.
7. Define canonical parameter metadata: physiological meaning, model variable, unit, baseline, allowed range, scaling type.
8. Export full simulation metadata (model version/hash, parameters, protocol, solver, warnings).
9. Add automated baseline and perturbation regression tests.

### P2 — web UX
10. Rebuild model/parameter controls in web UI.
11. Restore useful overlay comparison from the legacy two-model viewer.
12. Add download/export of traces, currents, metrics, parameters, and provenance.

## Bottom line

`Cardiac AP.py` is the correct conceptual starting point for a future web app, but the current code should **not** be presented yet as a fully validated multi-model research simulator. The strongest part is the model-registry/multi-backend architecture and the Grandits↔ToR baseline alignment. The most important correctness fix is the incomplete 7/9 mechanistic validation mapping. After that, source pinning, beat-aware metrics, transparent pacing, and numerical regression fixtures should be completed before deployment.
