"""Tempeh fermentation and heater limits the digital twin does not carry.

The twin models the air in the box and the heater element. It knows nothing about the culture
inside: which phase of fermentation a batch is in, how cold it may get before that matters, or
how long it may stay there. Those figures live in ``domain_knowledge/tempeh_thresholds.json``
and are read here.

Every value is marked ``"sourced"`` or ``"estimated"`` in that file. This module reads and looks
up; deciding what a particular trajectory means for a batch belongs to the risk assessment.

The fermentation phase is derived rather than read. An incubator has no sensor for it, so it is
computed from how long the batch has been running.
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

    Phases are contiguous and sorted by `elapsed_hours` in the JSON. A batch that has run
    longer than the taxonomy's `total_duration_hours` falls back to the last phase
    (maturation) -- a slow batch, not an error.
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
    """Heater safety figures: the temperature ceiling and the three duty limits.

    Keys: ``max_t_heater_c``, ``max_continuous_on_s``, ``min_off_after_max_on_s``,
    ``max_duty_fraction_over_1h``. All estimated. The duty limits bound what the heater may be
    asked to do; they are adopted figures, not measured hardware limits.
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
