# Legacy migration map

The original files are reference artifacts and have not been edited.

| Legacy file | SHA-256 | New location of responsibility |
|---|---|---|
| `Cardiac AP.py` | `826f12b72f5b0a473bc76acd7a78fbcea597dbd1ca77f75c25239e27c4579cf2` | Registry, schemas, Myokit/Grandits/native backends, metrics, API |
| `Two_cardiac_models.py` | `10d6475b81a351b7dc363cd47c42f229b7bbfb712717f6ad2bba79ba36e63597` | `/api/compare` and React comparison page |
| `fit_vtrace_csv_emulator.py` | `0dd7aa5461cb69f6f8dfa53b6aa5d77c250b33481d37571f1a0134705a964086` | `backend/app/fitting/` and fitting endpoints |
| `fit_vtrace_csv_emulator_ui.py` | `760ec6c0323ed6bc98db4423ebc526050802e38342c0b4acb7a71c948fcc3516` | React fitting workflow |
| `simone_trancuccio_backend.py` | `f634661bff200da7d09a6bee74c03e238c3e08bca7eda001803715831b3d9ba4` | Reference only; production dynamic execution is disabled |

## Deliberate behavior changes

- The scientific backend is independent from the UI.
- Model assets are pinned and hashed; simulations never download code at runtime.
- Parameter controls resolve to explicit native variables.
- Grandits mechanistic validation maps 9/9 values, including Na/Ca exchange and Na/K pump parameters that were previously omitted.
- AP metrics operate on full resolution beat windows. SAN metrics use spontaneous peak cycles.
- Automatic stimulus rescue is disabled. Requested and actual settings are returned together.
- Uploaded CSV content is parsed as bounded numeric data; no uploaded code or filesystem path is executed.
- Simone's MATLAB text conversion and `exec()` path remains only in `legacy/`.

## API correspondence

| Desktop concept | Web implementation |
|---|---|
| Model selector | `GET /api/models`, grouped React selector, Models catalog |
| Run action potential | `POST /api/simulate` |
| Overlay models | `POST /api/compare` |
| Calculate APD | `POST /api/metrics` and simulation result metrics |
| Grandits fit | `POST /api/fitting/grandits` |
| ToR validation | `POST /api/fitting/validate` |
| Save trace | Browser CSV/JSON exports |

Server responses omit local model paths. Model IDs, revisions, settings, unit conversions, and warnings remain in exported results.
