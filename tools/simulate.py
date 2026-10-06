"""Forward-simulate the incubator, with or without a lid opening.

Answers "what happens to the box if the lid is open for N seconds?" with a trajectory and a set
of derived figures. It computes; it does not interpret. Turning a trajectory into a judgement
about the batch is the risk assessment's job.

**The model.** The digital twin's four-parameter plant together with its bang-bang controller,
wired the way the twin wires them. An open lid is represented by driving the plant's ``G_box``
input to ``g_open_lid_ratio * G_box`` while the lid is open, which is the same disturbance the
twin's seven-parameter plant applies, kept here on the four-parameter set so that the heater
power stays consistent. The twin's own code is not modified: ``G_box`` is declared as an input,
so supplying a time-varying value is ordinary use of it.

**What the temperature means.** ``t_air_c`` is the air temperature inside the box, the quantity
the incubator's sensors and controller see. The plant has no term for the batch's thermal mass
or for any heat the culture produces, so a batch does not follow this curve.
"""

from __future__ import annotations

import numpy as np
from oomodelling import Model, ModelSolver

from incubator_dt.models.controller_models.controller_model4 import ControllerModel4
from incubator_dt.models.plant_models.four_parameters_model.four_parameter_model import (
    FourParameterIncubatorPlant,
)
from tools.domain_knowledge import phase_for_elapsed_hours, safe_band_c_for_phase
from tools.state import get_current_state

# The incubator controller's own execution interval, and the solver step ratio the twin's
# code uses throughout.
CTRL_STEP_S = 3.0
SOLVER_STEP_RATIO = 10.0

# Default seconds of simulated time after the lid closes, in which to look for recovery.
DEFAULT_RECOVERY_BUDGET_S = 3600.0

# Target number of samples in the returned trajectory. Every figure is computed on the full
# solver grid; this only controls how much of the curve is returned alongside them.
TARGET_TRAJECTORY_POINTS = 100

MAX_DURATION_S = 6 * 3600.0

class SimulationError(ValueError):
    """A simulation was asked for with arguments that do not make sense."""


# --------------------------------------------------------------------------- the model

class _LidAwareSystem(Model):
    """Four-parameter plant + bang-bang controller, with a square lid-open pulse.

    Mirrors `SystemModel4Parameters`, adding one thing: ``G_box`` is switched to
    ``g_open_lid_ratio * G_box`` for ``[open_at_s, close_at_s)``. A zero-length pulse gives
    the undisturbed baseline.
    """

    def __init__(self, *, C_air, G_box, C_heater, G_heater, V_heater, I_heater,
                 g_open_lid_ratio, lower_bound, heating_time, heating_gap,
                 max_temperature_desired, initial_box_temperature, initial_heat_temperature,
                 initial_room_temperature, open_at_s, close_at_s):
        super().__init__()

        self.ctrl = ControllerModel4(temperature_desired=max_temperature_desired,
                                     heating_time=heating_time, heating_gap=heating_gap,
                                     lower_bound=lower_bound)
        self.plant = FourParameterIncubatorPlant(V_heater, I_heater,
                                                 initial_room_temperature,
                                                 initial_box_temperature,
                                                 initial_heat_temperature,
                                                 C_air, G_box, C_heater, G_heater)

        self.ctrl.in_temperature = self.plant.T
        self.plant.in_heater_on = self.ctrl.heater_on

        # Recorded so the returned trajectory can show when the lid was open, rather than the
        # caller having to reconstruct it from the arguments.
        self.lid_open = self.var(
            lambda: 1.0 if open_at_s <= self.plant.time() < close_at_s else 0.0)
        self.plant.G_box = lambda: G_box * (g_open_lid_ratio if self.lid_open() > 0.5 else 1.0)

        self.save()


# --------------------------------------------------------------------------- public API

def simulate_lid_opening(duration_s: float,
                         open_at_s: float = 0.0,
                         horizon_s: float | None = None,
                         recovery_budget_s: float = DEFAULT_RECOVERY_BUDGET_S,
                         state: dict | None = None,
                         initial_from: str = "state_estimate",
                         trajectory_points: int | None = TARGET_TRAJECTORY_POINTS) -> dict:
    """Predict what a lid opening does to the incubator, starting from the current DT state.

    Args:
        duration_s: how long the lid stays open, in seconds. 0 gives the undisturbed baseline.
        open_at_s: when the lid opens, in seconds from now. 0 means "right now".
        horizon_s: total simulated time. Defaults to
            ``open_at_s + duration_s + recovery_budget_s``, i.e. enough time to watch the
            box recover after the lid is closed.
        recovery_budget_s: how long after the lid closes to keep simulating, when
            ``horizon_s`` is not given.
        state: a state dict from `tools.state.get_current_state`. Read from disk if omitted.
        initial_from: ``"state_estimate"`` (the DT's Kalman output, the default) or
            ``"sensors"`` (the raw readings) for the initial temperatures.
        trajectory_points: how many samples the returned ``trajectory`` is thinned to.
            ``None`` returns every solver sample, which is the grid the summary figures were
            computed on -- what to ask for when the curve is to be inspected against them.

    Returns:
        A JSON-serialisable dict with:

        - ``summary``: the numbers an answer is built from -- minimum air temperature and
          when it occurs, temperature at the moment the lid closes, total drop, peak heater
          temperature, recovery times after closing, heater duty.
        - ``trajectory``: down-sampled series (``t_s``, ``t_air_c``, ``t_heater_c``,
          ``heater_on``, ``lid_open``) for context or plotting.
        - ``inputs``: the arguments and initial conditions actually used.

        ``recovery_*`` entries are ``None`` when recovery did not happen inside the horizon;
        that is a real answer ("not within N minutes"), not a failure.
    """
    state = get_current_state() if state is None else state

    duration_s = _check_non_negative(duration_s, "duration_s")
    open_at_s = _check_non_negative(open_at_s, "open_at_s")
    if duration_s > MAX_DURATION_S:
        raise SimulationError(
            f"duration_s={duration_s} exceeds the {MAX_DURATION_S:.0f} s cap; this tool "
            f"advises on short openings, not on leaving the incubator open.")

    recovery_budget_s = _check_positive(recovery_budget_s, "recovery_budget_s")
    close_at_s = open_at_s + duration_s
    if horizon_s is None:
        horizon_s = close_at_s + recovery_budget_s
    horizon_s = _check_positive(horizon_s, "horizon_s")
    if horizon_s <= close_at_s:
        raise SimulationError(
            f"horizon_s={horizon_s} does not reach the moment the lid closes "
            f"({close_at_s} s); nothing could be said about recovery.")

    ctrl, params, initial = _model_inputs(state, initial_from)

    model = _LidAwareSystem(
        C_air=params["C_air"], G_box=params["G_box"],
        C_heater=params["C_heater"], G_heater=params["G_heater"],
        V_heater=params["V_heater"], I_heater=params["I_heater"],
        g_open_lid_ratio=state["lid_disturbance"]["g_open_lid_ratio"],
        lower_bound=ctrl["lower_bound_c"],
        heating_time=ctrl["heating_time_s"],
        heating_gap=ctrl["heating_gap_s"],
        max_temperature_desired=ctrl["temperature_desired_c"],
        initial_box_temperature=initial["t_air_c"],
        initial_heat_temperature=initial["t_heater_c"],
        initial_room_temperature=initial["t_room_c"],
        open_at_s=open_at_s, close_at_s=close_at_s)

    step = float(ctrl["controller_step_size_s"])
    ModelSolver().simulate(model, 0.0, horizon_s, step, step / SOLVER_STEP_RATIO)

    fine = _extract(model)
    setpoint = float(ctrl["temperature_desired_c"])
    control_low = setpoint - float(ctrl["lower_bound_c"])
    # The fermentation phase is derived from elapsed time rather than read from the state,
    # because an incubator has no sensor for it.
    phase = phase_for_elapsed_hours(state["fermentation"]["elapsed_hours"])
    safe_band = safe_band_c_for_phase(phase)

    return {
        "summary": _summarise(fine, setpoint, control_low, safe_band,
                              open_at_s, close_at_s, initial["t_air_c"]),
        "trajectory": _downsample(fine, trajectory_points),
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
            "control_low_c": round(control_low, 3),
            "phase": phase,
            "safe_band_c": list(safe_band),
            "g_open_lid_ratio": state["lid_disturbance"]["g_open_lid_ratio"],
            "controller_step_size_s": step,
        },
    }


def simulate_baseline(horizon_s: float,
                      state: dict | None = None,
                      initial_from: str = "state_estimate",
                      trajectory_points: int | None = TARGET_TRAJECTORY_POINTS) -> dict:
    """Simulate the incubator with the lid kept shut -- the "do nothing" comparison.

    Same return shape as `simulate_lid_opening`; it *is* that function with a zero-length
    opening, so the two curves are directly comparable.
    """
    return simulate_lid_opening(duration_s=0.0, open_at_s=0.0, horizon_s=horizon_s,
                                state=state, initial_from=initial_from,
                                trajectory_points=trajectory_points)


# --------------------------------------------------------------------------- internals

def _check_non_negative(value, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise SimulationError(f"{name}: expected a number, got {value!r}")
    if value < 0 or not np.isfinite(value):
        raise SimulationError(f"{name}: expected a finite value >= 0, got {value}")
    return float(value)


def _check_positive(value, name: str) -> float:
    v = _check_non_negative(value, name)
    if v == 0:
        raise SimulationError(f"{name}: expected > 0, got {v}")
    return v


def _model_inputs(state: dict, initial_from: str) -> tuple[dict, dict, dict]:
    """Split the validated state into (controller config, plant parameters, initial conditions).

    `tools.state` has already checked types and ranges, so this only has to choose which
    temperatures to start from.
    """
    if initial_from not in ("state_estimate", "sensors"):
        raise SimulationError(
            f"initial_from={initial_from!r}: expected 'state_estimate' or 'sensors'")

    sensors = state["sensors"]
    source = state["state_estimate"] if initial_from == "state_estimate" else sensors
    initial = {
        "t_air_c": float(source["t_air_c"]),
        "t_heater_c": float(source["t_heater_c"]),
        # The Kalman filter does not estimate room temperature; it is always measured.
        "t_room_c": float(sensors["t_room_c"]),
    }
    return state["controller"], state["model_parameters"], initial


def _extract(model: _LidAwareSystem) -> dict:
    """Pull the recorded signals off the model as arrays on the solver's own time grid.

    The grid is slightly irregular (~`CTRL_STEP_S`): `oomodelling` commits a sample on the
    first solver step that crosses each communication interval.
    """
    return {
        "t_s": np.asarray(model.signals["time"], dtype=float),
        "t_air_c": np.asarray(model.plant.signals["T"], dtype=float),
        "t_heater_c": np.asarray(model.plant.signals["T_heater"], dtype=float),
        "heater_on": np.asarray(model.ctrl.signals["heater_on"], dtype=bool),
        "lid_open": np.asarray(model.signals["lid_open"], dtype=float) > 0.5,
    }


def _first_time_at_or_above(t: np.ndarray, y: np.ndarray, threshold: float,
                            not_before: float) -> float | None:
    """First time at or after `not_before` where `y >= threshold`, else None."""
    hits = np.flatnonzero((t >= not_before) & (y >= threshold))
    return float(t[hits[0]]) if hits.size else None


def _seconds_where(t: np.ndarray, mask: np.ndarray) -> float:
    """Time covered by `mask`, integrating the sample intervals it is true over."""
    if t.size < 2:
        return 0.0
    dt = np.diff(t)
    # Attribute each interval to the sample that opens it.
    return float(np.sum(dt[mask[:-1]]))


def _summarise(fine: dict, setpoint: float, control_low: float, safe_band: tuple[float, float],
               open_at_s: float, close_at_s: float, t_air_start_c: float) -> dict:
    t, air, heat = fine["t_s"], fine["t_air_c"], fine["t_heater_c"]

    after_close = t >= close_at_s
    min_idx = int(np.argmin(air))
    # Temperature at the moment the lid closes -- the worst the air gets for an opening that
    # is still cooling when it ends, and the point the recovery is measured from.
    close_idx = int(np.flatnonzero(after_close)[0]) if after_close.any() else int(t.size - 1)

    to_control_band = _first_time_at_or_above(t, air, control_low, close_at_s)
    to_setpoint = _first_time_at_or_above(t, air, setpoint, close_at_s)

    # The disturbance window: from the lid opening until the box is back inside the
    # controller's normal band (or the end of the horizon, if it never gets there). Exposure
    # is measured over this window only -- across the whole horizon it would be swamped by
    # the controller's ordinary cycling between control_low and setpoint, which happens lid
    # or no lid and says nothing about the opening.
    event_end_s = to_control_band if to_control_band is not None else float(t[-1])
    in_event = (t >= open_at_s) & (t <= event_end_s)
    band_low, band_high = safe_band

    return {
        "t_air_start_c": round(t_air_start_c, 2),
        "t_air_at_close_c": round(float(air[close_idx]), 2),
        "min_t_air_c": round(float(air[min_idx]), 2),
        "min_t_air_at_s": round(float(t[min_idx]), 1),
        "max_t_air_c": round(float(air.max()), 2),
        "drop_c": round(t_air_start_c - float(air[min_idx]), 2),
        "max_t_heater_c": round(float(heat.max()), 2),
        "final_t_air_c": round(float(air[-1]), 2),
        # Measured from the moment the lid closes, which is what a user can act on.
        "recovery_to_control_band_s": _relative(to_control_band, close_at_s),
        "recovery_to_setpoint_s": _relative(to_setpoint, close_at_s),
        "recovered_to_setpoint": to_setpoint is not None,
        # Exposure, over the disturbance window only.
        "event_window_s": [round(open_at_s, 1), round(event_end_s, 1)],
        "time_below_control_band_s": round(_seconds_where(t, in_event & (air < control_low)), 1),
        "time_below_safe_band_s": round(_seconds_where(t, in_event & (air < band_low)), 1),
        "time_above_safe_band_s": round(_seconds_where(t, in_event & (air > band_high)), 1),
        "max_excursion_below_safe_band_c": round(max(band_low - float(air.min()), 0.0), 2),
        # Heater use, over the whole horizon.
        "heater_on_s": round(_seconds_where(t, fine["heater_on"]), 1),
        "heater_duty_fraction": round(
            _seconds_where(t, fine["heater_on"]) / max(float(t[-1] - t[0]), 1e-9), 3),
    }


def _relative(absolute_s: float | None, origin_s: float) -> float | None:
    return None if absolute_s is None else round(max(absolute_s - origin_s, 0.0), 1)


def _downsample(fine: dict, target: int | None = TARGET_TRAJECTORY_POINTS) -> dict:
    """Thin the solver grid to about `target` samples for reporting.

    Every sample is a real solver sample -- this selects, it does not interpolate, so no
    value in the trajectory is invented. The summary metrics are computed on the full grid,
    so `target=None`, which keeps every sample, is what makes the trajectory and the summary
    describe exactly the same curve.
    """
    n = fine["t_s"].size
    if target is None:
        keep = np.arange(n)
    else:
        if not isinstance(target, int) or isinstance(target, bool) or target < 2:
            raise SimulationError(
                f"trajectory_points: expected an integer >= 2, or None for every solver "
                f"sample, got {target!r}")
        keep = np.arange(n) if n <= target else np.unique(
            np.linspace(0, n - 1, target).round().astype(int))
    return {
        "t_s": [round(v, 1) for v in fine["t_s"][keep]],
        "t_air_c": [round(v, 2) for v in fine["t_air_c"][keep]],
        "t_heater_c": [round(v, 2) for v in fine["t_heater_c"][keep]],
        "heater_on": [bool(v) for v in fine["heater_on"][keep]],
        "lid_open": [bool(v) for v in fine["lid_open"][keep]],
        "n_solver_samples": int(n),
    }
