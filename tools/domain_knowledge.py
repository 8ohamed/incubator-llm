"""Tempeh fermentation and heater limits the digital twin does not carry.

The twin models air and heating element; it knows nothing about the culture inside. Those
figures live in ``domain_knowledge/tempeh_thresholds.json``, each marked ``"sourced"`` or
``"estimated"``, and are read here. This module looks up; what a trajectory *means* for a batch
is the risk assessment's call.

The fermentation phase is derived, not read: an incubator has no sensor for it, so it comes from
how long the batch has been running.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_THRESHOLDS = REPO_ROOT / "domain_knowledge" / "tempeh_thresholds.json"


class DomainKnowledgeError(ValueError):
    """The domain-knowledge file is missing, malformed, or asked for something it doesn't have."""


# --------------------------------------------------------------------------- public API

def load_thresholds(path: str | Path | None = None) -> dict:
    """Return the raw parsed contents of `tempeh_thresholds.json`."""
    return _load(str(path) if path is not None else str(DEFAULT_THRESHOLDS))


def phase_for_elapsed_hours(elapsed_hours: float, path: str | Path | None = None) -> str:
    """Which fermentation phase a batch is in, from how long it has been running.

    A batch past the taxonomy's `total_duration_hours` falls back to the last phase: a slow
    batch, not an error.
    """
    phases = load_thresholds(path)["fermentation_phases"]["phases"]
    for p in phases:
        _, hi = p["elapsed_hours"]
        if elapsed_hours < hi:
            return p["id"]
    return phases[-1]["id"]


def safe_band_c_for_phase(phase: str, path: str | Path | None = None) -> tuple[float, float]:
    """The (min, max) air temperature this phase is considered safe within."""
    band = load_thresholds(path)["safe_band_c_by_phase"]
    if phase not in band:
        raise DomainKnowledgeError(f"safe_band_c_by_phase has no entry for phase {phase!r}")
    lo, hi = band[phase]
    return (float(lo), float(hi))


def cold_exposure_budgets_s(path: str | Path | None = None) -> tuple[float, float]:
    """(safe_s, recoverable_s) -- the base cold-exposure budgets, before the phase multiplier."""
    b = load_thresholds(path)["cold_exposure_budgets_s"]
    return (float(b["safe_s"]), float(b["recoverable_s"]))


def cold_exposure_multiplier_for_phase(phase: str, path: str | Path | None = None) -> float:
    """How much more (>1) or less (<1) cold exposure this phase tolerates than the base budget."""
    for p in load_thresholds(path)["fermentation_phases"]["phases"]:
        if p["id"] == phase:
            return float(p["cold_exposure_multiplier"])
    raise DomainKnowledgeError(f"fermentation_phases has no entry for phase {phase!r}")


def heat_damage_ceiling_c(path: str | Path | None = None) -> float:
    """Air temperature above which the culture itself risks dying, not just growth slowing."""
    return float(load_thresholds(path)["temperature_bounds_c"]["damage_ceiling"])


def heater_safety(path: str | Path | None = None) -> dict:
    """``max_t_heater_c``, ``max_continuous_on_s``, ``min_off_after_max_on_s``,
    ``max_duty_fraction_over_1h``.

    All estimated: adopted figures bounding what the heater may be asked to do, not measured
    hardware limits.
    """
    return dict(load_thresholds(path)["heater_safety"])


# --------------------------------------------------------------------------- internals

@lru_cache(maxsize=None)
def _load(path: str) -> dict:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DomainKnowledgeError(f"domain-knowledge file not found: {p}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise DomainKnowledgeError(f"{p.name}: not valid JSON ({exc})") from exc
