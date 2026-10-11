# Scientific validation report

**Validation date:** 2026-10-09  
**Scope:** 14 enabled catalog entries, metric engine, perturbations, fitting, native/source adapters, API, and frontend build.

## Reproducibility controls

- Source revisions and SHA-256 hashes are recorded in `backend/app/models/manifest.json`.
- Runtime simulations use local pinned assets only.
- The Grandits Torch checkpoint is hash checked before deserialization.
- The Ni C++ checkout and all legacy files remain unchanged; compatibility and adapters are separate. The native build uses a temporary source copy with explicit returns for four state-update functions whose return values are discarded upstream, eliminating GCC undefined behavior without changing model state.
- Baseline voltage traces, metrics, current peaks, protocols, and provenance are stored under `backend/tests/reference/`.
- Auto rescue is off. A failed capture never changes the requested stimulus.

## Accepted baselines

| Model | Primary accepted metric | Voltage range (mV) | Source gate |
|---|---:|---:|---|
| ToR-ORd-dynCl endocardial | APD90 272.51 ms | -89.75 to 33.12 | Pinned official CellML |
| BPS2020 | APD90 227.43 ms | -87.96 to 40.32 | Pinned official CellML |
| O'Hara-Rudy 2011 | APD90 236.77 ms | -87.94 to 39.47 | Pinned curated MMT |
| Grandi 2011 atrial | APD90 326.51 ms | -73.55 to 8.81 | Pinned curated MMT |
| Ni 2023 atrial signaling | APD90 290.54 ms | -79.91 to 36.54 | Repository sample 288.77 ms; error 1.77 ms |
| Fabbri 2017 SAN | Cycle length 813.0 ms | -58.89 to 26.42 | Spontaneous limit cycle |
| Linder–Fabbri 2025 | Cycle length 813.0 ms | -58.88 to 26.42 | Official source; ISO response verified |
| Grandits 2024 emulator | APD90 273.00 ms | -89.22 to 34.26 | SHA-verified checkpoint |
| Simone WT | Cycle length 834.6 ms | -71.59 to 32.97 | Static port vs original Octave source |
| Simone TS22 | Cycle length 1017.4 ms | -74.99 to 35.05 | Static port vs original Octave source |
| Herrera male nSR | APD90 298.90 ms | -78.46 to 36.28 | Original MATLAB equations under Octave |
| Herrera female nSR | APD90 291.17 ms | -77.22 to 36.62 | Original MATLAB equations under Octave |
| Herrera male cAF | APD90 229.78 ms | -82.52 to 43.04 | Original MATLAB equations under Octave |
| Herrera female cAF | APD90 219.09 ms | -82.33 to 41.11 | Original MATLAB equations under Octave |

Trace RMSE tolerance is 3 mV, key-metric relative tolerance is 10%, and current-peak relative tolerance is 20% unless a stricter gate is listed.

## Independent Simone equivalence

The committed static RHS was compared to the pinned original MATLAB equations using GNU Octave 10.3.0, `ode15s`, 3 seconds, `RelTol=1e-8`, `AbsTol=1e-10`, and `MaxStep=0.005 s`.

| Variant | Voltage RMSE | Maximum absolute voltage error | Calcium RMSE |
|---|---:|---:|---:|
| WT | 0.0000573 mV | 0.00186 mV | 3.60e-11 mM |
| TS22 | 0.0000997 mV | 0.00361 mV | 1.03e-10 mM |

The generated RHS also matches the reviewed legacy translator exactly at representative WT/TS22, paced/spontaneous derivative and output evaluations. Production does not use dynamic `exec`.

## Perturbation and fitting gates

- ToR qualitative perturbations cover `g_Na`, `g_CaL`, `g_Kr`, `g_K1`, and `g_NaL`.
- Grandits fitting returns all nine conductance/permeability values.
- Mechanistic validation rejects partial mappings.
- All nine values reach distinct ToR variables: `GNa→INa.GNa`, `GNaL_b→INaL.GNaL_b`, `Gto_b→Ito.Gto_b`, `GKr_b→IKr.GKr_b`, `GKs_b→IKs.GKs_b`, `GK1_b→IK1.GK1_b`, `Gncx_b→INaCa.Gncx_b`, `Pnak_b→INaK.Pnak_b`, and `PCa_b→ICaL.PCa_b`.

## Model adapter notes

- BPS2020 and Linder–Fabbri were recovered from their pinned official PMR revisions and checksum locked.
- Linder’s runtime copy repairs importer-level CellML unit/interface defects without changing equations or constants.
- Herrera uses the four supplied 184-state steady-state files and executes the original `NH_ODE.m` equations. Its sex-specific scaling and cAF remodeling therefore remain authoritative. The missing upstream license is reported as `review_required`.
