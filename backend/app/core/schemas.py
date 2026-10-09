from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PacingSettings(BaseModel):
    mode: Literal["external", "spontaneous", "single_beat"] | None = None
    frequency_hz: float = Field(default=1.0, ge=0, le=20)
    stimulus_duration_ms: float = Field(default=1.0, ge=0, le=20)
    stimulus_strength_nA: float = Field(default=1.1, ge=0, le=100)
    offset_ms: float = Field(default=200, ge=0, le=20000)
    cm_pf: float = Field(default=50, gt=0, le=500)


class ParameterChange(BaseModel):
    scale: float | None = Field(default=None, ge=0, le=4)
    native_value: float | None = None

    @model_validator(mode="after")
    def exactly_one_change(self):
        if (self.scale is None) == (self.native_value is None):
            raise ValueError("Specify exactly one of scale or native_value")
        return self


class SimulationRequest(BaseModel):
    model_id: str
    duration_ms: float = Field(default=1000, gt=0, le=20000)
    pacing: PacingSettings | None = None
    prepace_beats: int = Field(default=10, ge=0, le=100)
    parameters: dict[str, ParameterChange] = Field(default_factory=dict)
    model_options: dict[str, float] = Field(default_factory=dict, max_length=20)
    include_currents: list[str] = Field(default_factory=list, max_length=30)
    auto_rescue: bool = False


class CompareRequest(BaseModel):
    simulations: list[SimulationRequest] = Field(min_length=2, max_length=4)


class MetricsRequest(BaseModel):
    time_ms: list[float] = Field(min_length=3, max_length=200000)
    voltage_mv: list[float] = Field(min_length=3, max_length=200000)
    mode: Literal["paced", "spontaneous"] = "paced"
    pacing: PacingSettings | None = None


class FittingRequest(BaseModel):
    csv_text: str = Field(min_length=10, max_length=2_000_000)
    time_column: str
    time_unit: Literal["ms", "s"]
    reference_column: str
    mutant_column: str | None = None
    trace_mode: Literal["voltage_mv", "dff", "shape"] = "voltage_mv"
    df_for_100mv: float = Field(default=0.29, gt=0, le=10)
    rest_mv: float = Field(default=-85, ge=-150, le=50)
    fit_parameters: list[str] | None = None
    mutant_variable_parameters: list[str] | None = None
    directions: dict[str, Literal["up", "down", "free"]] = Field(default_factory=dict)
    mutant_change_limits_pct: dict[str, float] = Field(default_factory=dict)
    epochs: int = Field(default=150, ge=10, le=400)
    max_points: int = Field(default=500, ge=100, le=2000)
    seed: int = Field(default=7, ge=0, le=2**31 - 1)


class ValidationRequest(BaseModel):
    grandits_parameters: dict[str, float]
    duration_ms: float = Field(default=1000, gt=0, le=20000)
    prepace_beats: int = Field(default=50, ge=0, le=100)
    pacing: PacingSettings | None = None
