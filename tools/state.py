"""Read the incubator's current state, as published by the digital twin.

This is the only place the state document is read. It is validated on the way in, so a
malformed or out-of-date state fails here with a clear message rather than reaching a
simulation and producing a plausible wrong answer. Every other tool works from the dictionary
returned by :func:`get_current_state`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CURRENT_STATE = REPO_ROOT / "state" / "current_state.json"

# The state schema this reader accepts. A state document announcing any other version is
# rejected rather than guessed at.
CURRENT_STATE_SCHEMA = "0.3.0"

REQUIRED_PARAMS = ("C_air", "G_box", "C_heater", "G_heater", "V_heater", "I_heater")
KNOWN_CONTROLLER_TYPES = ("on_off",)


class StateSchemaError(ValueError):
    """The state document is missing, malformed, or of an unsupported schema version."""


# --------------------------------------------------------------------------- public API

def get_current_state(path: str | Path | None = None) -> dict:
    """Load, validate and return `current_state.json` as a plain dict.

    Pass `path` to read a different snapshot (any file matching schema
    ``CURRENT_STATE_SCHEMA``). Raises `StateSchemaError` on anything malformed.
    """
    path = Path(path) if path is not None else DEFAULT_CURRENT_STATE
    raw = _load_json(path)
    _validate_current_state(raw, path)
    return raw


# ------------------------------------------------------------------------ validation

def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise StateSchemaError(msg)


def _require_keys(d: dict, keys, where: str) -> None:
    _require(isinstance(d, dict), f"{where}: expected an object")
    missing = [k for k in keys if k not in d]
    _require(not missing, f"{where}: missing keys {missing}")


def _number(d: dict, key: str, where: str) -> float:
    v = d.get(key)
    _require(isinstance(v, (int, float)) and not isinstance(v, bool),
             f"{where}.{key}: expected a number, got {v!r}")
    return float(v)


def _positive(d: dict, key: str, where: str) -> float:
    v = _number(d, key, where)
    _require(v > 0, f"{where}.{key}: expected > 0, got {v}")
    return v


def _parse_iso(value, where: str) -> datetime:
    _require(isinstance(value, str), f"{where}: expected an ISO-8601 string, got {value!r}")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StateSchemaError(f"{where}: cannot parse {value!r} as ISO-8601 ({exc})") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _load_json(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise StateSchemaError(f"state file not found: {path}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise StateSchemaError(f"{path.name}: not valid JSON ({exc})") from exc


def _validate_current_state(raw: dict, path: Path) -> None:
    name = path.name
    _require(isinstance(raw, dict), f"{name}: top level must be an object")
    got = raw.get("schema_version")
    _require(got == CURRENT_STATE_SCHEMA,
             f"{name}: schema_version {got!r}, this reader expects {CURRENT_STATE_SCHEMA!r}")
    _require_keys(raw, ("timestamp", "sensors", "actuators", "state_estimate", "controller",
                        "model_parameters", "lid_disturbance", "fermentation", "anomalies"), name)

    ts = _parse_iso(raw["timestamp"], f"{name}.timestamp")

    _require_keys(raw["sensors"], ("t_air_c", "t_heater_c", "t_room_c"), "sensors")
    for k in ("t_air_c", "t_heater_c", "t_room_c"):
        _number(raw["sensors"], k, "sensors")

    _require_keys(raw["state_estimate"], ("t_air_c", "t_heater_c"), "state_estimate")
    for k in ("t_air_c", "t_heater_c"):
        _number(raw["state_estimate"], k, "state_estimate")

    ctrl = raw["controller"]
    _require_keys(ctrl, ("type", "temperature_desired_c", "lower_bound_c",
                         "heating_time_s", "heating_gap_s", "controller_step_size_s"), "controller")
    _require(ctrl["type"] in KNOWN_CONTROLLER_TYPES,
             f"controller.type {ctrl['type']!r} not supported (known: {KNOWN_CONTROLLER_TYPES})")
    setpoint = _positive(ctrl, "temperature_desired_c", "controller")
    offset = _positive(ctrl, "lower_bound_c", "controller")
    for k in ("heating_time_s", "heating_gap_s", "controller_step_size_s"):
        _positive(ctrl, k, "controller")
    _require(setpoint - offset > 0,
             f"controller: temperature_desired_c - lower_bound_c = {setpoint - offset:.2f} <= 0 "
             f"(lower_bound_c is an offset BELOW the setpoint, not an absolute temperature)")

    mp = raw["model_parameters"]
    _require_keys(mp, REQUIRED_PARAMS, "model_parameters")
    for k in REQUIRED_PARAMS:
        _positive(mp, k, "model_parameters")  # also rejects the negative-C_heater 7-parameter set

    ld = raw["lid_disturbance"]
    _require_keys(ld, ("G_open_lid", "g_open_lid_ratio"), "lid_disturbance")
    _positive(ld, "G_open_lid", "lid_disturbance")
    ratio = _positive(ld, "g_open_lid_ratio", "lid_disturbance")
    _require(ratio > 1, f"lid_disturbance.g_open_lid_ratio = {ratio}, expected > 1 "
                        f"(an open lid loses heat faster, not slower)")

    frm = raw["fermentation"]
    _require_keys(frm, ("started_at", "elapsed_hours", "target_temp_c"), "fermentation")
    started = _parse_iso(frm["started_at"], "fermentation.started_at")
    _positive(frm, "target_temp_c", "fermentation")
    # The fermentation phase is deliberately not a field here: an incubator has no sensor for
    # it. It is derived from elapsed_hours in domain_knowledge.py, together with the safe
    # temperature band that applies to it.

    elapsed_calc = (ts - started).total_seconds() / 3600.0
    _require(abs(_number(frm, "elapsed_hours", "fermentation") - elapsed_calc) <= 0.1,
             f"fermentation.elapsed_hours = {frm['elapsed_hours']} but "
             f"timestamp - started_at = {elapsed_calc:.2f} h (fix elapsed_hours or started_at)")

    _require(isinstance(raw["anomalies"], list), "anomalies: expected a list")
