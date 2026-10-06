"""Turn a simulated lid opening into a risk verdict for the tempeh batch.

``tools/simulate.py`` says what the *air temperature* does. This module says what that means
for the *culture*: is the opening safe, is it survivable provided the lid then stays shut for a
while, or does it put the batch at real risk?

The split is deliberate. Everything here is a rule applied to numbers the simulation already
computed; this module never re-derives a temperature. The answer given to the operator puts the
verdict and its reasons into plain language, and does not decide the verdict.

**Where the thresholds come from.** The fermentation phase, the safe temperature band, the
cold-exposure budgets and the hot-side damage ceiling all come from
``tools/domain_knowledge.py``, which reads ``domain_knowledge/tempeh_thresholds.json``: tempeh
fermentation science, cited, and cross-checked against one real batch. That is not calibration.
No batch that actually spoiled was available, so these thresholds can be informed by the
literature and cross-checked against a healthy batch, never validated against a real failure.
``thresholds_are_provisional`` stays ``True`` for exactly that reason, and every verdict returns
the thresholds it used, so the claim can be checked.

**Caveats travel with the verdict.** A verdict is only as good as the model behind it, and the
model describes air rather than tempeh. Every result therefore carries the caveats that bear on
it. The answer given to the operator says that it has limitations and explains them on request.
"""

from __future__ import annotations

import math

from tools import domain_knowledge
from tools.state import get_current_state

VERDICTS = {
    "safe": "A",
    "recoverable": "B",
    "high_risk": "C",
}

#: Limits of the model every verdict rests on. Returned with each verdict so that they are
#: always at hand when the operator asks about them.
MODEL_CAVEATS = (
    "The predicted temperature is the AIR in the box. The model has no term for the tempeh "
    "cake's thermal mass, so the cake cools far more slowly than the predicted curve and does "
    "not reach the minimum shown.",
    "The model has no term for the culture's own metabolic heat, which a real 22 hour batch "
    "shows becomes significant after about 11 hours. Predicted drops are therefore pessimistic, "
    "too deep and too fast, for a batch in active growth.",
    "Room temperature is held at its current value for the whole predicted period.",
)


class AnalysisError(ValueError):
    """An analysis was asked for on something that is not a simulation result."""


def assess_lid_opening(simulation: dict, state: dict | None = None) -> dict:
    """Classify a simulated lid opening as safe / recoverable / high-risk.

    Args:
        simulation: the dict returned by `tools.simulate.simulate_lid_opening`.
        state: a state dict from `tools.state.get_current_state`. Read from disk if omitted.

    Returns:
        A JSON-serialisable dict with:

        - ``verdict``: ``"safe"``, ``"recoverable"`` or ``"high_risk"``, plus ``option``
          (``"A"``/``"B"``/``"C"``).
        - ``keep_closed_s``: for a ``recoverable`` verdict, how long the lid must then stay shut
          for the box to be back at the setpoint. ``None`` if recovery never happened.
        - ``reasons``: short factual strings, each carrying the number that justifies it.
        - ``caveats``: the limits of the model this verdict rests on, explained to the operator
          on request; the drop predicted here is for air, not for the cake.
        - ``metrics`` / ``thresholds``: what the verdict was computed from.
    """
    state = get_current_state() if state is None else state
    summary = _summary_of(simulation)
    ferm = state["fermentation"]

    # An incubator has no sensor for the fermentation phase, so it is derived from how long the
    # batch has been running rather than read from a field someone set by hand.
    phase = domain_knowledge.phase_for_elapsed_hours(ferm["elapsed_hours"])
    band_low, band_high = domain_knowledge.safe_band_c_for_phase(phase)
    base_safe_s, base_recoverable_s = domain_knowledge.cold_exposure_budgets_s()
    tolerance = domain_knowledge.cold_exposure_multiplier_for_phase(phase)
    budget_safe = base_safe_s * tolerance
    budget_recoverable = base_recoverable_s * tolerance
    damage_ceiling = domain_knowledge.heat_damage_ceiling_c()

    cold_s = float(summary["time_below_safe_band_s"])
    hot_s = float(summary["time_above_safe_band_s"])
    recovered = bool(summary["recovered_to_setpoint"])
    recovery_s = summary["recovery_to_setpoint_s"]
    duration_s = float(simulation["inputs"]["duration_s"])

    verdict, reasons = _classify(cold_s, hot_s, recovered, budget_safe, budget_recoverable,
                                 summary, band_low, band_high, duration_s, damage_ceiling)

    # Only a B verdict comes with a condition attached; for A there is nothing to hold to,
    # and for C the advice is not to open at all.
    keep_closed_s = math.ceil(recovery_s / 60.0) * 60.0 if (
        verdict == "recoverable" and recovery_s is not None) else None

    return {
        "verdict": verdict,
        "option": VERDICTS[verdict],
        "keep_closed_s": keep_closed_s,
        "reasons": reasons,
        "caveats": _caveats(phase),
        "metrics": {
            "duration_s": duration_s,
            "min_t_air_c": summary["min_t_air_c"],
            "max_t_air_c": summary["max_t_air_c"],
            "safe_band_c": [band_low, band_high],
            "max_excursion_below_safe_band_c": summary["max_excursion_below_safe_band_c"],
            "time_below_safe_band_s": cold_s,
            "time_above_safe_band_s": hot_s,
            "recovery_to_setpoint_s": recovery_s,
            "phase": phase,
            "elapsed_hours": ferm["elapsed_hours"],
        },
        "thresholds": {
            "cold_exposure_safe_s": budget_safe,
            "cold_exposure_recoverable_s": budget_recoverable,
            "phase_tolerance_factor": tolerance,
            "heat_damage_ceiling_c": damage_ceiling,
        },
        "thresholds_are_provisional": True,
    }


# --------------------------------------------------------------------------- internals

def _summary_of(simulation: dict) -> dict:
    if not isinstance(simulation, dict) or "summary" not in simulation or "inputs" not in simulation:
        raise AnalysisError(
            "assess_lid_opening expects the dict returned by simulate_lid_opening "
            "(with 'summary' and 'inputs' keys)")
    return simulation["summary"]


def _classify(cold_s, hot_s, recovered, budget_safe, budget_recoverable,
              summary, band_low, band_high, duration_s, damage_ceiling) -> tuple[str, list[str]]:
    """Apply the verdict rules, collecting the reason for each one that fires."""
    reasons: list[str] = []

    max_t_air_c = float(summary["max_t_air_c"])
    if max_t_air_c > damage_ceiling:
        # A lid opening only ever cools the box, so this cannot fire on one. The rule exists
        # because any advisory that deliberately raises the temperature needs it. It is checked
        # first: heat above this line risks killing the culture outright, not merely slowing
        # its growth, so it overrides everything else.
        reasons.append(
            f"the air peaks at {max_t_air_c:.1f} C, above the {damage_ceiling:.1f} C ceiling "
            f"above which the culture itself risks dying, not just its growth slowing")
        return "high_risk", reasons

    if hot_s > 0:
        reasons.append(
            f"the air spends {hot_s:.0f} s above the safe band's upper edge "
            f"({band_high:.1f} C), peaking at {summary['max_t_air_c']:.1f} C")

    if not recovered:
        reasons.append(
            "the box does not get back to the setpoint within the simulated horizon, so "
            "recovery cannot be confirmed")
        return "high_risk", reasons

    if cold_s <= 0:
        reasons.append(
            f"the air never leaves the safe band (minimum {summary['min_t_air_c']:.1f} C "
            f"against a lower edge of {band_low:.1f} C)")
        verdict = "safe"
    elif cold_s <= budget_safe:
        reasons.append(
            f"the air drops to {summary['min_t_air_c']:.1f} C, "
            f"{summary['max_excursion_below_safe_band_c']:.1f} C below the safe band, but "
            f"only for {cold_s:.0f} s -- within the {budget_safe:.0f} s treated as "
            f"negligible exposure for this phase")
        verdict = "safe"
    elif cold_s <= budget_recoverable:
        reasons.append(
            f"the air spends {cold_s:.0f} s below the safe band, past the {budget_safe:.0f} s "
            f"negligible-exposure budget but within the {budget_recoverable:.0f} s treated as "
            f"recoverable for this phase")
        verdict = "recoverable"
    else:
        reasons.append(
            f"the air spends {cold_s:.0f} s below the safe band, beyond the "
            f"{budget_recoverable:.0f} s treated as recoverable for this phase")
        verdict = "high_risk"

    if verdict != "high_risk" and hot_s > 0:
        # A hot excursion below the damage ceiling is never the reason a cold-exposure
        # verdict improves, but it must not be silently outranked by a passing cold verdict
        # either.
        verdict = "recoverable" if verdict == "safe" else verdict

    if verdict == "recoverable":
        reasons.append(
            f"once the lid is shut the box returns to the setpoint in "
            f"{summary['recovery_to_setpoint_s']:.0f} s")
    if duration_s == 0:
        reasons.append("no opening was simulated; this is the undisturbed baseline")

    return verdict, reasons


def _caveats(phase: str) -> list[str]:
    """The model limits that change how this verdict should be read.

    `MODEL_CAVEATS` applies to every verdict. The phase adds one more, because how much the
    omitted metabolic heat matters depends on how far along the batch is.
    """
    caveats: list[str] = list(MODEL_CAVEATS)
    if phase == "active_growth":
        caveats.append(
            "The batch is in active growth, so its own metabolic heat, which the model omits, "
            "makes the real drop shallower and the real recovery faster than shown. This "
            "verdict is pessimistic.")
    elif phase == "lag":
        caveats.append(
            "The batch is in lag phase, with no metabolic heat of its own yet, so the modelled "
            "drop is closer to what would really happen.")
    return caveats
