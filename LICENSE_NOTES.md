# Model and dependency license notes

Status reviewed on 2026-10-09. This inventory records upstream statements and missing terms; it is not legal advice.

| Asset | Pinned source | Recorded status | Deployment note |
|---|---|---|---|
| ToR-ORd | `jtmff/torord` at `11e463d…` | GPL-3.0-or-later | Review source distribution and network deployment obligations before release. |
| Grandits emulator | `thomgrand/cardiomyocyte_emulator` at `26ba43c…` | AGPL-3.0 | A network service may trigger corresponding-source obligations. |
| Simone–Trancuccio | PMR workspace `d92` at `83903a0…` | NON-COMMERCIAL USE ONLY | Enabled for noncommercial research with a clearly visible warning. Do not describe or deploy it as unrestricted. |
| Fabbri 2017 PMR exposure | PMR workspace `486` | CC BY 3.0 | Enabled through a pinned curated Myokit transcription; repository terms still require review. |
| Linder–Fabbri 2025 | PMR exposure `d14`, workspace `c65` at `95db8d6…` | CC BY 3.0 | Enabled from the official source plus a separately hashed structural-import repair. |
| Ni 2023 | `drgrandilab/Ni-et-al-2023-Human-Atrial-Signaling-Model` at `683d1da…` | `review_required` | No explicit `LICENSE` file at the pinned revision. Local research execution is enabled; redistribution needs review. |
| Herrera 2025 | `drgrandilab/Herrera-et-al-2025-Sex-Specific-Human-Atrial-Model` at `77c8e39…` | `review_required` | No explicit `LICENSE` file. Four variants execute the original source for research; redistribution needs review. |
| Myokit curated model repository | `myokit/models` at `e8ef6db…` | `review_required` | The checkout has no repository license file. Review model-specific provenance before redistribution. |
| BPS2020 PMR asset | workspace `711` at `c8dc3b2…` | `review_required` | Enabled from the pinned official CellML; model-specific reuse terms were not explicit in the downloaded file. |
| SUNDIALS | v6.7.0 source used locally | BSD-3-Clause style upstream terms | See `external/sundials/LICENSE` and `NOTICE`. |
| GNU Octave runtime | conda-forge Octave 10.3.0 | GPL-3.0-or-later | Installed as an external runtime for direct Herrera and validation runs. |

Every API model record includes its license status and notes. Public API responses omit local source, binary, and initial-condition paths.
