"""Strict 9/9 Grandits to ToR-ORd native base-variable mapping."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.core.registry import model_by_id
from app.core.schemas import ParameterChange

GRANDITS_TO_CANONICAL = {
    "GNa": "g_Na", "GNaL_b": "g_NaL", "Gto_b": "g_to",
    "GKr_b": "g_Kr", "GKs_b": "g_Ks", "GK1_b": "g_K1",
    "Gncx_b": "g_NaCa", "Pnak_b": "g_NaK", "PCa_b": "g_CaL",
}

GRANDITS_TO_TOR_NATIVE = {
    "GNa": "INa.GNa", "GNaL_b": "INaL.GNaL_b", "Gto_b": "Ito.Gto_b",
    "GKr_b": "IKr.GKr_b", "GKs_b": "IKs.GKs_b", "GK1_b": "IK1.GK1_b",
    "Gncx_b": "INaCa.Gncx_b", "Pnak_b": "INaK.Pnak_b", "PCa_b": "ICaL.PCa_b",
}


def to_tor_changes(values: Mapping[str, float] | Sequence[float]) -> dict[str, ParameterChange]:
    if not isinstance(values, Mapping):
        if len(values) != 9:
            raise ValueError("Grandits validation requires exactly nine values")
        values = dict(zip(GRANDITS_TO_CANONICAL, values, strict=True))
    if set(values) != set(GRANDITS_TO_CANONICAL):
        missing = sorted(set(GRANDITS_TO_CANONICAL) - set(values))
        extra = sorted(set(values) - set(GRANDITS_TO_CANONICAL))
        raise ValueError(f"Grandits validation requires 9/9 parameters; missing={missing}, unexpected={extra}")
    tor = model_by_id("torord_dyncl_endo")
    for grandits, native in GRANDITS_TO_TOR_NATIVE.items():
        canonical = GRANDITS_TO_CANONICAL[grandits]
        if tor["parameters"].get(canonical) != native:
            raise RuntimeError(f"ToR mapping mismatch: {grandits} -> {canonical} -> {native}")
    return {GRANDITS_TO_CANONICAL[name]: ParameterChange(native_value=float(value)) for name, value in values.items()}
