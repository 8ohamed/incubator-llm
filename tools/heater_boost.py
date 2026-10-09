"""Search for a heater boost that makes a high-risk lid opening acceptable.

Only the controller's setpoint can be changed on a running incubator, so a boost is a setpoint
and a wait: raise the setpoint to X now, open the lid when the air reaches X, set the setpoint
back when the lid closes.

**Tried:** whole-degree setpoints above the current one, up to the top of the phase's safe band.
Each is simulated as one run (`heater_boost_simulate.simulate_boosted_opening`) and judged by
the same rules as a plain opening (`analyze.assess_lid_opening`).

**Accepted:** verdict B or A, inside every hard limit, and clearing the phase's exposure budget
by more than the simulation can resolve. The guard matters because the search prefers the lowest
qualifying setpoint, which is by definition the one that only just crosses, and a margin inside
the solver grid flips with a fraction of a second more or less pre-heat.

**Order:** highest setpoint first. A lower one drives the element to a lower temperature and so
stores less heat, so if the highest is inside the limits and still not enough, none is.
Otherwise try from the lowest up and take the first that qualifies. The argument is about the
element's target temperature, not the length of the pre-heat -- the wait is not monotonic in the
setpoint.

**What a boost can do:** little. The air loses its heat within seconds of the lid opening; the
gain is heat stored in the element, which shortens recovery after the lid shuts.
"""

from __future__ import annotations

import math

from tools import domain_knowledge
from tools.analyze import assess_lid_opening
from tools.heater_boost_simulate import (
    MAX_SETPOINT_C,
    simulate_boosted_opening,
    time_to_reach_setpoint,
)
from tools.simulate import simulate_lid_opening
from tools.state import get_current_state

# The reach time is rounded down to this, so the lid never opens after the air gets there.
# Well below the controller's step: anything coarser throws away margin the plan needs.
WAIT_UNIT_S = 0.1


def find_heater_boost(duration_s: float, state: dict | None = None) -> dict:
    """Find the lowest boost setpoint that lifts a high-risk opening to B or A.

    Args:
        duration_s: how long the operator wants the lid open, in seconds.
        state: a state dict from `tools.state.get_current_state`. Read from disk if omitted.

    Returns:
        A JSON-serialisable dict with:

        - ``without_boost``: the risk assessment of the plain opening.
        - ``boost_needed``: ``False`` unless that verdict is high risk (C). Nothing further is
          returned otherwise -- a boost is only searched for after a C.
        - ``found``: whether one qualifies. If so, ``plan`` (setpoint, wait, opening, setpoint
          to return to, how long to keep the lid shut, and how far it clears the budget) plus
          its ``simulation`` and ``risk``. If not, ``why_not``: factual strings, each carrying
          its number.
        - ``candidates``: only the setpoints actually tried, lowest first -- the search prunes,
          so this is not the range that was considered. ``why_not`` says what was covered.
        - ``limits``: the hard limits each plan was held to.
    """
    state = get_current_state() if state is None else state

    plain = simulate_lid_opening(duration_s=duration_s, state=state)
    plain_risk = assess_lid_opening(plain, state=state)
    result: dict = {"duration_s": plain["inputs"]["duration_s"], "without_boost": plain_risk}
    if plain_risk["verdict"] != "high_risk":
        result["boost_needed"] = False
        return result
    result["boost_needed"] = True

    setpoint = plain["inputs"]["setpoint_c"]
    limits = _limits(plain["inputs"]["safe_band_c"])
    boosts = _candidate_setpoints(setpoint, limits["safe_band_c"][1])

    tried: dict[float, dict] = {}

    def attempt(boost_c: float) -> dict:
        if boost_c not in tried:
            tried[boost_c] = _try_boost(boost_c, duration_s, state, limits)
        return tried[boost_c]

    chosen = None
    if boosts:
        highest = attempt(boosts[-1])
        # Only if the highest qualifies, or is ruled out by a limit rather than by its
        # verdict, can a lower setpoint be the answer.
        if highest["accepted"] or highest["candidate"]["limits_broken"]:
            chosen = next((a for a in map(attempt, boosts) if a["accepted"]), None)

    if chosen is not None:
        result.update({
            "found": True,
            "plan": {
                "boost_setpoint_c": chosen["candidate"]["boost_setpoint_c"],
                "open_after_s": chosen["candidate"]["open_after_s"],
                "open_for_s": result["duration_s"],
                "reset_setpoint_c": setpoint,
                "keep_closed_s": chosen["risk"]["keep_closed_s"],
                # How far the plan clears the phase's exposure budget, and the resolution that
                # margin has to beat. Reported so the answer can say how close the plan is
                # without working it out from two other figures.
                "exposure_budget_s": chosen["candidate"]["exposure_budget_s"],
                "exposure_margin_s": chosen["candidate"]["margin_s"],
            },
            "simulation": chosen["simulation"],
            "risk": chosen["risk"],
        })
    else:
        result.update({"found": False,
                       "why_not": _why_not(tried, boosts, setpoint, plain["inputs"]["phase"],
                                           limits)})

    result["candidates"] = [tried[b]["candidate"] for b in sorted(tried)]
    result["limits"] = limits
    return result


# --------------------------------------------------------------------------- internals

def _limits(safe_band_c: list[float]) -> dict:
    heater = domain_knowledge.heater_safety()
    return {
        "safe_band_c": list(safe_band_c),
        "max_t_heater_c": float(heater["max_t_heater_c"]),
        "max_continuous_on_s": float(heater["max_continuous_on_s"]),
        "max_duty_fraction_over_1h": float(heater["max_duty_fraction_over_1h"]),
        # The heater limits are adopted figures, not measured ones; the label travels with them.
        "heater_limits_status": heater["status"],
    }


def _candidate_setpoints(setpoint_c: float, band_high_c: float) -> list[float]:
    """Whole degrees above the current setpoint, up to the top of the safe band, lowest first."""
    top = min(band_high_c, MAX_SETPOINT_C - 1.0)
    return [float(c) for c in range(math.floor(setpoint_c) + 1, math.floor(top) + 1)]


def _try_boost(boost_c: float, duration_s: float, state: dict, limits: dict) -> dict:
    """Simulate and judge one boost setpoint."""
    # The heater runs without a break from the start of the boost until the box has recovered,
    # so a pre-heat still short of the setpoint after the continuous limit cannot qualify.
    reached_s = time_to_reach_setpoint(boost_c, limits["max_continuous_on_s"], state=state)
    if reached_s is None:
        return {"accepted": False, "candidate": {
            "boost_setpoint_c": boost_c, "open_after_s": None, "option": None,
            "time_below_safe_band_s": None, "exposure_budget_s": None,
            "margin_s": None, "resolution_s": None,
            "limits_broken": [
                f"the air does not reach {boost_c:.1f} C within "
                f"{limits['max_continuous_on_s']:.0f} s, the longest the heater may run "
                f"without a break"]}}

    # Open the moment the air reaches the setpoint, rounded down so never after it.
    # Open the moment the air reaches the setpoint, rounded down so never after it.
    wait_s = round(math.floor(reached_s / WAIT_UNIT_S) * WAIT_UNIT_S, 1)
    simulation = simulate_boosted_opening(duration_s=duration_s, boost_setpoint_c=boost_c,
                                          open_at_s=wait_s, state=state)
    risk = assess_lid_opening(simulation, state=state)
    broken = _limits_broken(simulation["summary"], limits)

    budget_s = float(risk["thresholds"]["cold_exposure_recoverable_s"])
    resolution_s = _resolution_s(simulation)
    margin_s = round(budget_s - float(simulation["summary"]["time_below_safe_band_s"]), 1)
    return {
        "accepted": (risk["verdict"] != "high_risk" and not broken
                     and margin_s > resolution_s),
        "simulation": simulation,
        "risk": risk,
        "candidate": {
            "boost_setpoint_c": boost_c,
            "open_after_s": wait_s,
            "option": risk["option"],
            "time_below_safe_band_s": simulation["summary"]["time_below_safe_band_s"],
            "exposure_budget_s": budget_s,
            "margin_s": margin_s,
            "resolution_s": resolution_s,
            "limits_broken": broken,
        },
    }


def _resolution_s(simulation: dict) -> float:
    """Mean interval between solver samples: the grid every summary figure was measured on.

    A margin smaller than one interval is not a result -- a fraction of a second more or less
    pre-heat moves the figure across a whole cell.
    """
    n = int(simulation["trajectory"]["n_solver_samples"])
    return round(float(simulation["inputs"]["horizon_s"]) / max(n - 1, 1), 1)


def _rejection_reason(attempt: dict) -> str:
    """Why a candidate was not accepted, in the terms that actually decided it."""
    candidate = attempt["candidate"]
    if candidate["limits_broken"]:
        return candidate["limits_broken"][0]
    if attempt["risk"]["verdict"] == "high_risk":
        # The risk assessment's own words, so the explanation is the one that decided it.
        return attempt["risk"]["reasons"][0]
    return (f"it stays within the {candidate['exposure_budget_s']:.0f} s exposure budget for "
            f"this phase by only {candidate['margin_s']:.1f} s, less than the "
            f"{candidate['resolution_s']:.1f} s the simulation can resolve, so the verdict "
            f"would change with a fraction of a second more or less pre-heat")


def _limits_broken(summary: dict, limits: dict) -> list[str]:
    broken = []
    band_high = limits["safe_band_c"][1]
    if summary["max_t_air_c"] > band_high:
        broken.append(f"the air reaches {summary['max_t_air_c']:.1f} C, above the top of the "
                      f"safe band ({band_high:.1f} C)")
    if summary["max_t_heater_c"] > limits["max_t_heater_c"]:
        broken.append(f"the heating element reaches {summary['max_t_heater_c']:.1f} C, above "
                      f"its {limits['max_t_heater_c']:.0f} C limit")
    # Reaching the continuous limit would also oblige the heater to rest afterwards, which the
    # controller does not do, so a plan must stay below it.
    if summary["longest_heater_on_s"] >= limits["max_continuous_on_s"]:
        broken.append(f"the heater runs {summary['longest_heater_on_s']:.0f} s without a break, "
                      f"against a {limits['max_continuous_on_s']:.0f} s limit")
    if summary["max_heater_duty_fraction_over_1h"] > limits["max_duty_fraction_over_1h"]:
        broken.append(f"the heater is on for {summary['max_heater_duty_fraction_over_1h']:.0%} "
                      f"of its busiest hour, against a "
                      f"{limits['max_duty_fraction_over_1h']:.0%} limit")
    return broken


def _why_not(tried: dict[float, dict], boosts: list[float], setpoint_c: float, phase: str,
             limits: dict) -> list[str]:
    band_high = limits["safe_band_c"][1]
    phase_name = phase.replace("_", " ")
    if not boosts:
        return [f"the safe band for the {phase_name} phase tops out at {band_high:.1f} C, "
                f"leaving no room for a boost above the {setpoint_c:.1f} C setpoint"]

    highest = tried[boosts[-1]]
    if "risk" in highest and not highest["candidate"]["limits_broken"]:
        return [f"the highest boost the safe band for the {phase_name} phase allows, "
                f"{boosts[-1]:.1f} C, is not enough: {_rejection_reason(highest)}",
                "a lower setpoint stores less heat, so it cannot do better"]

    reasons = [f"every whole-degree boost from {boosts[0]:.1f} C to {boosts[-1]:.1f} C, the "
               f"top of the safe band for the {phase_name} phase, was tried"]
    for boost_c in boosts:
        reasons.append(f"{boost_c:.1f} C: {_rejection_reason(tried[boost_c])}")
    return reasons
