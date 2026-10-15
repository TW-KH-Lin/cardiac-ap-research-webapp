"""CPU inverse fitting with the pinned Grandits emulator."""
from __future__ import annotations

import numpy as np

from app.backends.grandits_backend import load_emulator
from app.core.schemas import FittingRequest
from app.fitting.preprocessing import aligned_window, calibrate, parse_csv


def _weights(target: np.ndarray) -> np.ndarray:
    rest = float(np.percentile(target, 5))
    amplitude = max(float(np.max(target) - rest), 1e-6)
    norm = (target - rest) / amplitude
    peak = int(np.argmax(target))
    weight = np.ones(len(target), dtype=np.float32)
    index = np.arange(len(target))
    weight[(index >= peak) & (norm >= 0.3)] = 2
    weight[(index >= peak) & (norm >= 0.1) & (norm <= 0.7)] = 4
    weight[(index >= peak) & (norm >= 0.02) & (norm < 0.2)] = 3
    return weight / np.mean(weight)


def _fit_one(
    emulator, t: np.ndarray, target: np.ndarray, epochs: int,
    names_to_fit: list[str], initial: np.ndarray,
    directions: dict[str, str] | None = None,
    reference: np.ndarray | None = None,
    change_limits: dict[str, float] | None = None,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    import torch

    names = list(emulator.max_conds_names)
    lower = np.asarray(emulator.max_conds_ranges[0], dtype=np.float32)
    upper = np.asarray(emulator.max_conds_ranges[1], dtype=np.float32)
    center = np.asarray(emulator.max_conds_center, dtype=np.float32)
    # Match the legacy PCa prior while staying inside the training domain.
    if "PCa_b" in names:
        i = names.index("PCa_b")
        lower[i] = max(lower[i], center[i] * 0.25)
        upper[i] = min(upper[i], center[i] * 1.75)
    active = {names.index(name) for name in names_to_fit}
    start = np.asarray(initial, dtype=np.float32).copy()
    parameters = torch.tensor(start, requires_grad=True)
    offset = torch.tensor(0.0, requires_grad=True)
    times = torch.from_numpy(t.astype(np.float32))
    target_t = torch.from_numpy(target.astype(np.float32))
    weight_t = torch.from_numpy(_weights(target))
    optimizer = torch.optim.Adam([parameters, offset], lr=0.025)
    best_loss = float("inf")
    best_params, best_offset = start.copy(), 0.0
    for _ in range(epochs):
        optimizer.zero_grad()
        prediction = emulator.forward_latent(times + offset, parameters)[0]
        normalized_delta = (parameters - torch.from_numpy(center)) / torch.from_numpy(upper - lower)
        loss = torch.mean(weight_t * (prediction - target_t) ** 2) + 25 * torch.mean(normalized_delta**2) + 0.001 * offset**2
        loss.backward()
        optimizer.step()
        with torch.no_grad():
            parameters.clamp_(min=torch.from_numpy(lower), max=torch.from_numpy(upper))
            for index, name in enumerate(names):
                if index not in active:
                    parameters[index] = float(start[index])
                if reference is not None and index in active:
                    direction = (directions or {}).get(name, "free")
                    if direction == "up":
                        parameters[index] = torch.maximum(parameters[index], torch.tensor(reference[index]))
                    elif direction == "down":
                        parameters[index] = torch.minimum(parameters[index], torch.tensor(reference[index]))
                    limit = (change_limits or {}).get(name)
                    if limit is not None:
                        lo = max(lower[index], reference[index] * (1 - limit / 100))
                        hi = min(upper[index], reference[index] * (1 + limit / 100))
                        parameters[index].clamp_(min=float(lo), max=float(hi))
            offset.clamp_(-20, 20)
            selected = emulator.forward_latent(times + offset, parameters)[0]
            selected_loss = float(torch.mean(weight_t * (selected - target_t) ** 2).item())
            if selected_loss < best_loss:
                best_loss = selected_loss
                best_params = parameters.detach().numpy().copy()
                best_offset = float(offset.item())
    predicted = emulator.forward_latent_np((t + best_offset).astype(np.float32), best_params)[0]
    return best_params, predicted, best_offset, float(np.sqrt(np.mean((predicted - target) ** 2)))


def fit_csv(request: FittingRequest) -> dict:
    import torch

    torch.manual_seed(request.seed)
    emulator = load_emulator()
    names = [str(name) for name in emulator.max_conds_names]
    t, traces = parse_csv(request)
    selected = request.fit_parameters or names
    if not selected or set(selected) - set(names):
        raise ValueError("Fit parameters must be names from the nine Grandits conductances")
    variable = request.mutant_variable_parameters or names
    if set(variable) - set(names) or set(request.directions) - set(names) or set(request.mutant_change_limits_pct) - set(names):
        raise ValueError("Unknown mutant conductance name")
    if any(value < 0 or value > 200 for value in request.mutant_change_limits_pct.values()):
        raise ValueError("Mutant change limits must be between 0% and 200%")
    if request.mutant_column and request.mutant_column == request.reference_column:
        raise ValueError("Reference and mutant columns must differ")

    output = {}
    reference_params = None
    for role, name in [("reference", request.reference_column), ("mutant", request.mutant_column)]:
        if name is None:
            continue
        calibrated, calibration = calibrate(traces[name], request.trace_mode, request.rest_mv, request.df_for_100mv)
        fit_t, fit_v, upstroke = aligned_window(t, calibrated, request.max_points)
        if float(fit_t.min()) < -11 or float(fit_t.max()) > 501:
            raise ValueError("Aligned time is outside the validated -10 to 500 ms emulator window")
        initial = np.asarray(reference_params if role == "mutant" else emulator.max_conds_center, dtype=np.float32)
        active = variable if role == "mutant" else selected
        params, predicted, offset, rmse = _fit_one(
            emulator, fit_t, fit_v, request.epochs, active, initial,
            request.directions if role == "mutant" else None,
            reference_params if role == "mutant" else None,
            request.mutant_change_limits_pct if role == "mutant" else None,
        )
        if role == "reference":
            reference_params = params.copy()
        output[role] = {
            "column": name, "time_ms": fit_t.tolist(), "target_mv": fit_v.tolist(), "emulator_mv": predicted.tolist(),
            "upstroke_time_ms": upstroke, "time_offset_ms": offset, "rmse_mv": rmse,
            "calibration": calibration,
            "parameters": {native: float(value) for native, value in zip(names, params, strict=True)},
            "parameter_table": [
                {"name": native, "baseline": float(emulator.max_conds_center[i]), "fitted": float(params[i]),
                 "percent_change_from_baseline": float((params[i] / emulator.max_conds_center[i] - 1) * 100),
                 "training_min": float(emulator.max_conds_ranges[0][i]), "training_max": float(emulator.max_conds_ranges[1][i]),
                 "at_training_bound": bool(np.isclose(params[i], emulator.max_conds_ranges[0][i], rtol=1e-4) or np.isclose(params[i], emulator.max_conds_ranges[1][i], rtol=1e-4))}
                for i, native in enumerate(names)
            ],
        }
    return {"mode": "reference_mutant" if request.mutant_column else "reference", "traces": output,
            "settings": request.model_dump(exclude={"csv_text"}),
            "provenance": {"model_id": "grandits_2024", "source_revision": "26ba43c619c0acf2fc853326aa4cd0578b786d6a", "seed": request.seed},
            "warnings": ["Emulator fit quality and ToR mechanistic validation are separate results.", "No confidence interval is estimated; training bounds are shown for each parameter."]}
