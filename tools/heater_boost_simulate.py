"""Simulate a lid opening that is preceded by a heater boost.

The plan: the setpoint is raised now, the lid opens later for the time asked about, and the
setpoint goes back when the lid closes. Simulated as **one run** from the current state, so the
box enters the opening exactly as the boost left it.

The model, solver settings and every figure come from `tools.simulate` unchanged, so a boosted
opening is measured exactly as a plain one. The only addition is the setpoint schedule: the
controller's state machine is subclassed (not modified) by one that reads the setpoint in force
before each step, which is what the real controller does with a setpoint changed while running.

Two figures are added to the summary for the heater limits a boost is held to: the longest
unbroken run, and the duty over the busiest hour.
"""

from __future__ import annotations

import math

import numpy as np
from oomodelling import ModelSolver

from incubator_dt.models.controller_models.controller_model_sm import ControllerModel4SM
from tools.domain_knowledge import phase_for_elapsed_hours, safe_band_c_for_phase
from tools.simulate import (
    DEFAULT_RECOVERY_BUDGET_S,
    MAX_DURATION_S,
    SOLVER_STEP_RATIO,
    SimulationError,
    _check_non_negative,
    _check_positive,
    _downsample,
    _extract,
    _first_time_at_or_above,
    _LidAwareSystem,
    _model_inputs,
    _summarise,
)
from tools.state import get_current_state

# The incubator's controller refuses a new setpoint of this value or above.
MAX_SETPOINT_C = 45.0

# Heater duty is also reported over its busiest hour, the window its duty limit is stated over.
DUTY_WINDOW_S = 3600.0


class _ScheduledStateMachine(ControllerModel4SM):
    """The incubator's bang-bang state machine, taking its setpoint from a schedule.

    Before each step it reads the setpoint in force, as the incubator's controller applies a new
    setpoint at its next step. Everything else is the original state machine.
    """

    def __init__(self, original: ControllerModel4SM, setpoint_at):
        super().__init__(original.temperature_desired, original.lower_bound,
                         original.heating_time, original.heating_gap)
        self._setpoint_at = setpoint_at

    def step(self, time, in_temperature):
        self.temperature_desired = self._setpoint_at(time)
        super().step(time, in_temperature)


#  public API

def simulate_boosted_opening(duration_s: float,
                             boost_setpoint_c: float,
                             open_at_s: float,
                             recovery_budget_s: float = DEFAULT_RECOVERY_BUDGET_S,
                             state: dict | None = None,
                             initial_from: str = "state_estimate") -> dict:
    """Predict a lid opening that is preceded by a heater boost.

    Args:
        duration_s: how long the lid stays open, in seconds.
        boost_setpoint_c: the setpoint raised to now, and held until the lid closes.
        open_at_s: when the lid opens, in seconds from now: the length of the pre-heat.
        recovery_budget_s: how long after the lid closes to keep simulating.
        state: a state dict from `tools.state.get_current_state`. Read from disk if omitted.
        initial_from: ``"state_estimate"`` (the default) or ``"sensors"``.

    Returns:
        The shape `tools.simulate.simulate_lid_opening` returns, plus ``inputs.boost_setpoint_c``
        and the two heater figures. One difference: exposure is counted from now, not from the
        opening, so heat the pre-heat puts into the box counts against the safe band too.
    """
    state = get_current_state() if state is None else state

    duration_s = _check_non_negative(duration_s, "duration_s")
    open_at_s = _check_non_negative(open_at_s, "open_at_s")
    boost_setpoint_c = _check_setpoint(boost_setpoint_c, "boost_setpoint_c")
    if duration_s > MAX_DURATION_S:
        raise SimulationError(
            f"duration_s={duration_s} exceeds the {MAX_DURATION_S:.0f} s cap; this tool "
            f"advises on short openings, not on leaving the incubator open.")
    recovery_budget_s = _check_positive(recovery_budget_s, "recovery_budget_s")

    close_at_s = open_at_s + duration_s
    horizon_s = close_at_s + recovery_budget_s
    fine, ctrl, initial = _run(state, initial_from, open_at_s=open_at_s, close_at_s=close_at_s,
                               boost_setpoint_c=boost_setpoint_c, boost_until_s=close_at_s,
                               horizon_s=horizon_s)

    setpoint = float(ctrl["temperature_desired_c"])
    control_low = setpoint - float(ctrl["lower_bound_c"])
    # The fermentation phase is derived from elapsed time, as for a plain opening.
    phase = phase_for_elapsed_hours(state["fermentation"]["elapsed_hours"])
    safe_band = safe_band_c_for_phase(phase)

    # Exposure counted from now (0.0), not from the opening.
    summary = _summarise(fine, setpoint, control_low, safe_band, 0.0, close_at_s,
                         initial["t_air_c"])
    summary["longest_heater_on_s"] = round(_longest_run_s(fine["t_s"], fine["heater_on"]), 1)
    summary["max_heater_duty_fraction_over_1h"] = round(
        _max_fraction_over_window(fine["t_s"], fine["heater_on"], DUTY_WINDOW_S), 3)

    return {
        "summary": summary,
        "trajectory": _downsample(fine),
        "inputs": {
            "duration_s": duration_s,
            "open_at_s": open_at_s,
            "close_at_s": close_at_s,
            "horizon_s": horizon_s,
            "initial_from": initial_from,
            "t_air_start_c": initial["t_air_c"],
            "t_heater_start_c": initial["t_heater_c"],
            "t_room_c": initial["t_room_c"],
            "setpoint_c": setpoint,
            "boost_setpoint_c": boost_setpoint_c,
            "control_low_c": round(control_low, 3),
            "phase": phase,
            "safe_band_c": list(safe_band),
            "g_open_lid_ratio": state["lid_disturbance"]["g_open_lid_ratio"],
            "controller_step_size_s": float(ctrl["controller_step_size_s"]),
        },
    }


def time_to_reach_setpoint(setpoint_c: float,
                           horizon_s: float,
                           state: dict | None = None,
                           initial_from: str = "state_estimate") -> float | None:
    """Lid shut, setpoint raised to ``setpoint_c`` now: when does the air first reach it?

    Seconds from now, or ``None`` if not within ``horizon_s``. The controller only starts
    heating once the air is ``lower_bound_c`` below the setpoint, so a small boost lets the box
    cool first; that wait is included.
    """
    state = get_current_state() if state is None else state
    setpoint_c = _check_setpoint(setpoint_c, "setpoint_c")
    horizon_s = _check_positive(horizon_s, "horizon_s")

    fine, _, _ = _run(state, initial_from, open_at_s=0.0, close_at_s=0.0,
                      boost_setpoint_c=setpoint_c, boost_until_s=math.inf, horizon_s=horizon_s)
    return _first_time_at_or_above(fine["t_s"], fine["t_air_c"], setpoint_c, 0.0)


# --------------------------------------------------------------------------- internals

def _check_setpoint(value, name: str) -> float:
    v = _check_positive(value, name)
    if v >= MAX_SETPOINT_C:
        raise SimulationError(
            f"{name}={v}: the incubator's controller only accepts setpoints below "
            f"{MAX_SETPOINT_C:.0f} C")
    return v


def _run(state: dict, initial_from: str, *, open_at_s: float, close_at_s: float,
         boost_setpoint_c: float, boost_until_s: float, horizon_s: float):
    """Run the lid-opening model with the setpoint held at the boost until `boost_until_s`."""
    ctrl, params, initial = _model_inputs(state, initial_from)
    setpoint = float(ctrl["temperature_desired_c"])

    model = _LidAwareSystem(
        C_air=params["C_air"], G_box=params["G_box"],
        C_heater=params["C_heater"], G_heater=params["G_heater"],
        V_heater=params["V_heater"], I_heater=params["I_heater"],
        g_open_lid_ratio=state["lid_disturbance"]["g_open_lid_ratio"],
        lower_bound=ctrl["lower_bound_c"],
        heating_time=ctrl["heating_time_s"],
        heating_gap=ctrl["heating_gap_s"],
        max_temperature_desired=setpoint,
        initial_box_temperature=initial["t_air_c"],
        initial_heat_temperature=initial["t_heater_c"],
        initial_room_temperature=initial["t_room_c"],
        open_at_s=open_at_s, close_at_s=close_at_s)
    model.ctrl.state_machine = _ScheduledStateMachine(
        model.ctrl.state_machine,
        lambda t: boost_setpoint_c if t < boost_until_s else setpoint)

    step = float(ctrl["controller_step_size_s"])
    ModelSolver().simulate(model, 0.0, horizon_s, step, step / SOLVER_STEP_RATIO)
    return _extract(model), ctrl, initial


def _longest_run_s(t: np.ndarray, mask: np.ndarray) -> float:
    """Longest unbroken stretch of time over which `mask` holds."""
    longest = current = 0.0
    for dt, on in zip(np.diff(t), mask[:-1]):
        current = current + dt if on else 0.0
        longest = max(longest, current)
    return float(longest)


def _max_fraction_over_window(t: np.ndarray, mask: np.ndarray, window_s: float) -> float:
    """Largest fraction of any `window_s`-long window over which `mask` holds.

    A run shorter than the window is treated as one window.
    """
    if t.size < 2:
        return 0.0
    window_s = min(window_s, float(t[-1] - t[0]))
    held = np.concatenate(([0.0], np.cumsum(np.diff(t) * mask[:-1])))
    starts = np.flatnonzero(t + window_s <= t[-1] + 1e-9)
    ends = np.searchsorted(t, t[starts] + window_s, side="right") - 1
    return float(np.max((held[ends] - held[starts]) / window_s))
