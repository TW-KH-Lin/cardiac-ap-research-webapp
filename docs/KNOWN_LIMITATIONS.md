# Known limitations

## Scientific scope

- This is a research exploration tool, not a clinical diagnostic system.
- Conductance values are model specific. Relative scales can be compared as interventions; raw native conductances across model families should not be treated as equivalent.
- The EAD flag is a screening heuristic and should be inspected with the trace.
- Metrics require a complete captured beat. Truncated or noncaptured beats are returned as invalid.
- Grandits is a single-beat neural surrogate without mechanistic currents or prepacing. A ToR validation run does not establish fitted-parameter uniqueness.

## Model-specific limits

- **Simone–Trancuccio WT and TS22:** enabled only for noncommercial research use, matching the source terms. The production adapter is a static Python port validated against the original equations under Octave. It supports spontaneous activity and selected conductance/permeability scales.
- **Herrera 2025:** all four male/female nSR/cAF variants execute the pinned original MATLAB equations under Octave. The upstream repository has no explicit license, so reuse and redistribution require review. Ionic-current export is not exposed; voltage, calcium, metrics, ISO, frequency, and supported parameter scales are available. Source runs are slow and limited to five simulated seconds including prepacing.
- **Linder–Fabbri 2025:** the published CellML has structural defects that prevent strict import. `scripts/prepare_linder_cellml.py` makes only the documented interface/unit repairs and writes a separately hashed runtime copy; equations and numerical constants are unchanged.
- **Ni 2023:** uses a compiled subprocess and is limited to 120 simulated seconds including prepacing. The pinned baseline matches the repository APD90 sample within 1%.
- **BPS2020:** the app default is 1.7 mM extracellular calcium as specified in the handoff; the pinned source constant is 1.8 mM and is overridden explicitly in every default result.

## Runtime and performance

- First Myokit use compiles native simulation code and may be slower than later runs.
- Herrera requires GNU Octave with SUNDIALS `ode15s` support. The production image installs the pinned Octave 10.3.0 conda-forge runtime under `.runtime/mamba` and checks the stiff solver during the build; its original-source simulations take roughly 45 seconds per one-second trace on the development host.
- Browser plots use returned arrays directly. Scientific metrics are computed before presentation.

## Deployment

- The published ChatGPT Site is a static, phone-friendly catalog and interface. ChatGPT Sites cannot execute the Python, native C++, SUNDIALS, Torch, Myokit, and Octave runtimes used by the scientific backend. When no external scientific server is connected, it keeps the complete catalog visible and disables simulation controls with an explicit status message.
- The Docker image installs the verified Octave runtime and includes the four pinned Herrera source variants.
- License review is required before public or commercial deployment, especially for GPL/AGPL, noncommercial, and unspecified source terms.
