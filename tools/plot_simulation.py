"""Draw what ``tools/simulate.py`` predicts, and nothing else.

The advisory answers in numbers. This module shows the curve those numbers describe: the
predicted air temperature, the heating element behind it, and when the lid and the heater are
open and on. It plots one thing -- a simulation result -- and leaves every judgement about it
to the reader.

**No risk assessment appears here.** The verdict, the exposure budgets it is weighed against,
the phase tolerance and the advice that follows all live in ``tools/analyze.py``, and this
module neither imports it nor repeats any of its output. That is the point: a picture that
already announces the answer is no way to check the answer. Run ``python -m tools.cli`` for the
verdict and read it against this plot, which was drawn without it.

What is drawn comes from the simulation alone. The safe band and the fermentation phase are
shown because ``simulate_lid_opening`` returns them in its own ``inputs`` and measures time
outside the band in its own ``summary``; they are simulation output, not a judgement about the
batch. Nothing here says whether any of it is acceptable.

**The curve shown is the curve measured.** The trajectory is requested at full solver
resolution, which is the grid the summary figures were computed on. The lowest point drawn is
therefore exactly the ``min_t_air_c`` in the summary, and the shaded region starts and ends
where the counting did; a disagreement between picture and number is a real disagreement, not
an artefact of thinning the curve for display.

**What the temperature is.** ``t_air_c`` is the air in the box. The plant has no term for the
cake's thermal mass or for the culture's own heat, so a batch does not follow this curve: it
cools more slowly and does not reach the minimum drawn. The figure repeats this under the
plot, because it is the first thing to hold in mind while reading one.

Usage (from this folder, with the virtual environment active)::

    python -m tools.plot_simulation 5                 # a 5 minute opening, in a window
    python -m tools.plot_simulation 5 --out plot.png  # and save it
    python -m tools.plot_simulation 5 --no-show --out plot.png
    python -m tools.plot_simulation 0                 # the lid-shut baseline

Or from Python::

    from tools.plot_simulation import plot_simulation
    plot_simulation(5)
"""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np

from tools.domain_knowledge import DomainKnowledgeError
from tools.simulate import SimulationError, simulate_lid_opening
from tools.state import StateSchemaError, get_current_state

# --------------------------------------------------------------------------- appearance
#
# Two series colours (air, heater element) and three state colours, from a palette checked for
# contrast against the surface and for separation under the common forms of colour blindness.
# The dark set is stepped for the dark surface rather than being the light set inverted.
#
# Series colour marks identity; state colour marks a region of the temperature scale and is
# never used for a series. No meaning rests on colour alone: every region and threshold in the
# figure is also named, in the legend or in a label beside it.

_LIGHT = {
    "surface": "#fcfcfb",
    "ink": "#0b0b0b",
    "ink_soft": "#52514e",
    "ink_muted": "#898781",
    "grid": "#e1e0d9",
    "axis": "#c3c2b7",
    "air": "#2a78d6",
    "heater": "#eb6834",
}
_DARK = {
    "surface": "#1a1a19",
    "ink": "#ffffff",
    "ink_soft": "#c3c2b7",
    "ink_muted": "#898781",
    "grid": "#2c2c2a",
    "axis": "#383835",
    "air": "#3987e5",
    "heater": "#d95926",
}
# Fixed in both modes, so a region of the scale always reads the same.
_BAND = {
    "inside": "#0ca30c",
    "above": "#fab219",
    "below": "#d03b3b",
}

FIGSIZE = (12.0, 9.0)
DPI = 110


# --------------------------------------------------------------------------- public API

def plot_simulation(minutes: float,
                    open_after_minutes: float = 0.0,
                    state: dict | None = None,
                    state_path: str | None = None,
                    out_path: str | None = None,
                    show: bool = True,
                    dark: bool = False,
                    full_horizon: bool = False) -> dict:
    """Simulate a lid opening and plot the result.

    No risk assessment is run, and none is drawn. This returns and shows what the simulation
    predicted; what it means for the batch is `tools.analyze`'s question, asked separately.

    Args:
        minutes: how long the lid stays open, in minutes. 0 plots the lid-shut baseline.
        open_after_minutes: when the lid opens, in minutes from now. 0 means "right now".
        state: a state dict from `tools.state.get_current_state`. Read from disk if omitted.
        state_path: where to read the state from, when `state` is not given.
        out_path: save the figure here. Omit to only show it.
        show: open the figure in a window. Turn off when only the file is wanted.
        dark: use the dark colour set, for a dark viewer or slide.
        full_horizon: draw the whole simulated hour. Off by default, because the opening and
            its recovery occupy the first few minutes of it and the rest is the controller
            cycling; the simulation is unchanged either way, only how much of it is shown.

    Returns:
        ``{"simulation": ..., "figure_path": ...}`` -- the dict
        `tools.simulate.simulate_lid_opening` returned, so the numbers behind the picture are
        available to the caller, plus where the figure was written (``None`` if not saved).
    """
    duration_s = _minutes_to_seconds(minutes, "minutes")
    open_at_s = _minutes_to_seconds(open_after_minutes, "open_after_minutes")

    state = get_current_state(state_path) if state is None else state
    # Every solver sample, so that the curve drawn is the one the figures were measured on.
    simulation = simulate_lid_opening(duration_s=duration_s, open_at_s=open_at_s,
                                      state=state, trajectory_points=None)

    figure_path = _draw(simulation, out_path=out_path, show=show, dark=dark,
                        full_horizon=full_horizon)
    return {"simulation": simulation, "figure_path": figure_path}


# --------------------------------------------------------------------------- internals

def _minutes_to_seconds(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SimulationError(f"{name}: expected a number of minutes, got {value!r}")
    if value < 0 or not np.isfinite(value):
        raise SimulationError(f"{name}: expected a finite value >= 0, got {value}")
    return float(value) * 60.0


def _import_pyplot(show: bool):
    """Import pyplot, choosing a file-only backend when no window is wanted.

    Selecting the backend before the first import matters: with no display available the
    interactive backends fail, and a saved figure does not need one.
    """
    try:
        import matplotlib
    except ImportError as exc:  # pragma: no cover - a missing dependency, not a logic path
        raise SimulationError(
            "plotting needs matplotlib, which is not installed in this environment; "
            "`pip install -r requirements.txt` from this folder installs it") from exc
    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _draw(simulation: dict, out_path: str | None, show: bool, dark: bool,
          full_horizon: bool) -> str | None:
    plt = _import_pyplot(show)
    c = _DARK if dark else _LIGHT

    traj = simulation["trajectory"]
    summary = simulation["summary"]
    inputs = simulation["inputs"]

    t_min = np.asarray(traj["t_s"], dtype=float) / 60.0
    air = np.asarray(traj["t_air_c"], dtype=float)
    heater_t = np.asarray(traj["t_heater_c"], dtype=float)
    heater_on = np.asarray(traj["heater_on"], dtype=bool)
    lid_open = np.asarray(traj["lid_open"], dtype=bool)

    band_low, band_high = inputs["safe_band_c"]
    setpoint = inputs["setpoint_c"]
    control_low = inputs["control_low_c"]
    open_min = inputs["open_at_s"] / 60.0
    close_min = inputs["close_at_s"] / 60.0
    event_start_min, event_end_min = (v / 60.0 for v in summary["event_window_s"])

    fig = plt.figure(figsize=FIGSIZE, dpi=DPI, facecolor=c["surface"])
    gs = fig.add_gridspec(3, 1, height_ratios=[3.0, 1.0, 0.55], hspace=0.14,
                          left=0.075, right=0.845, top=0.845, bottom=0.095)
    ax_air = fig.add_subplot(gs[0])
    ax_heat = fig.add_subplot(gs[1], sharex=ax_air)
    ax_state = fig.add_subplot(gs[2], sharex=ax_air)
    for ax in (ax_air, ax_heat, ax_state):
        _style_axes(ax, c)

    _draw_air(ax_air, c, t_min, air, band_low, band_high, setpoint, control_low,
              open_min, close_min, event_start_min, event_end_min, summary, inputs)
    _draw_heater(ax_heat, c, t_min, heater_t, open_min, close_min, summary)
    _draw_state_strip(ax_state, c, t_min, heater_on, lid_open)

    for ax in (ax_air, ax_heat):
        ax.tick_params(labelbottom=False)
    ax_state.set_xlabel("time from now (minutes)", color=c["ink_soft"], fontsize=10)

    view_end = _view_end_min(t_min, summary, inputs, full_horizon)
    ax_air.set_xlim(float(t_min[0]), view_end)
    if view_end < float(t_min[-1]):
        ax_state.annotate(
            f"view ends here; simulated to {t_min[-1]:.0f} min",
            xy=(1.0, -0.50), xycoords="axes fraction", xytext=(0, 0),
            textcoords="offset points", ha="right", va="top",
            color=c["ink_muted"], fontsize=8)

    _draw_heading(fig, c, simulation)

    figure_path = None
    if out_path is not None:
        fig.savefig(out_path, facecolor=c["surface"], dpi=DPI)
        figure_path = str(out_path)
    if show:
        plt.show()
    plt.close(fig)
    return figure_path


def _view_end_min(t_min, summary: dict, inputs: dict, full_horizon: bool) -> float:
    """How much of the simulation to draw.

    The whole horizon is an hour of controller cycling after a disturbance a few minutes long,
    which leaves the part being looked at squeezed into the first eighth of the axis. By default
    the view ends a margin past the last thing the summary reports -- the end of the measuring
    window, or the return to the setpoint, whichever is later -- and the axis says so when it
    has been cropped. The simulation itself is untouched, so every figure quoted is still the
    figure the advisory would quote.
    """
    horizon_min = float(t_min[-1])
    if full_horizon:
        return horizon_min
    last_event_s = summary["event_window_s"][1]
    recovery_s = summary["recovery_to_setpoint_s"]
    if recovery_s is not None:
        last_event_s = max(last_event_s, inputs["close_at_s"] + recovery_s)
    return min(horizon_min, max(last_event_s / 60.0 * 1.45, 10.0))


def _style_axes(ax, c: dict) -> None:
    """Recessive chrome: hairline grid and axes one shade off the surface, no heavy frame."""
    ax.set_facecolor(c["surface"])
    ax.grid(True, color=c["grid"], linewidth=0.6, linestyle="-")
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(c["axis"])
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=c["ink_muted"], labelsize=9, length=3, width=0.8)


def _draw_air(ax, c, t_min, air, band_low, band_high, setpoint, control_low,
              open_min, close_min, event_start_min, event_end_min, summary, inputs) -> None:
    """The predicted air temperature, with the bands and times the summary reports on it."""
    # Regions first, so the curve sits on top of them.
    ax.axhspan(band_low, band_high, color=_BAND["inside"], alpha=0.10, linewidth=0,
               label=f"safe band for the {inputs['phase'].replace('_', ' ')} phase "
                     f"({band_low:.1f}-{band_high:.1f} C)")
    if close_min > open_min:
        ax.axvspan(open_min, close_min, color=c["ink_muted"], alpha=0.10, linewidth=0,
                   label=f"lid open ({(close_min - open_min) * 60:.0f} s)")

    # The shaded excursions span exactly the samples the summary measured into
    # time_below_safe_band_s and time_above_safe_band_s, which is why they are bounded at
    # event_end_min rather than running to the end of the horizon: past that point the
    # controller's ordinary cycling would be measured as though the lid had caused it.
    in_event = (t_min >= event_start_min) & (t_min <= event_end_min)
    cold_s = float(summary["time_below_safe_band_s"])
    if cold_s > 0:
        ax.fill_between(t_min, air, band_low, where=in_event & (air < band_low),
                        interpolate=True, color=_BAND["below"], alpha=0.30, linewidth=0,
                        label=f"below the safe band: {cold_s:.0f} s")
    hot_s = float(summary["time_above_safe_band_s"])
    if hot_s > 0:
        ax.fill_between(t_min, air, band_high, where=in_event & (air > band_high),
                        interpolate=True, color=_BAND["above"], alpha=0.35, linewidth=0,
                        label=f"above the safe band: {hot_s:.0f} s")

    # Thresholds, dashed to read as limits rather than as grid.
    ax.axhline(setpoint, color=c["ink_soft"], linewidth=1.2, linestyle=(0, (6, 4)))
    ax.axhline(control_low, color=c["ink_muted"], linewidth=1.0, linestyle=(0, (2, 3)))
    _edge_label(ax, setpoint, f"setpoint {setpoint:.1f} C", c["ink_soft"])
    _edge_label(ax, control_low,
                f"heating starts {control_low:.1f} C", c["ink_muted"])

    ax.plot(t_min, air, color=c["air"], linewidth=2.0, solid_joinstyle="round",
            label="air temperature in the box", zorder=4)

    # The end of the measuring window, which is where the box is back inside the controller's
    # band. Worth seeing, because it explains where the shaded region stops.
    if close_min < event_end_min < float(t_min[-1]):
        ax.axvline(event_end_min, color=c["ink_muted"], linewidth=1.0, linestyle=(0, (1, 3)))
        ax.annotate("back in the controller's band;\ntime outside measured up to here",
                    xy=(event_end_min, 1.0), xycoords=("data", "axes fraction"),
                    xytext=(5, -4), textcoords="offset points",
                    color=c["ink_muted"], fontsize=8, ha="left", va="top")

    # Selective direct labels: the two points the summary singles out, and nothing else.
    _point(ax, summary["min_t_air_at_s"] / 60.0, summary["min_t_air_c"], c,
           f"lowest air {summary['min_t_air_c']:.2f} C\n"
           f"({summary['drop_c']:.2f} C below the start)",
           offset=(0, -12), ha="center", va="top")
    recovery_s = summary["recovery_to_setpoint_s"]
    if recovery_s is not None:
        from_when = "after the lid shuts" if close_min > open_min else "from now"
        _point(ax, (inputs["close_at_s"] + recovery_s) / 60.0, setpoint, c,
               f"back at the setpoint\n{recovery_s:.0f} s {from_when}",
               offset=(-14, 10), ha="right", va="bottom")

    # Headroom under the lowest point, so its label has somewhere to sit that the curve
    # cannot reach.
    low, high = ax.get_ylim()
    ax.set_ylim(low - 0.15 * (high - low), high)

    ax.set_ylabel("air temperature (C)", color=c["ink_soft"], fontsize=10)
    leg = ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.015), ncol=2, frameon=False,
                    fontsize=9, handlelength=1.6, columnspacing=2.4, labelspacing=0.5)
    for text in leg.get_texts():
        text.set_color(c["ink_soft"])


def _draw_heater(ax, c, t_min, heater_t, open_min, close_min, summary) -> None:
    """The heating element, on its own axis -- a second temperature scale, not a second y-axis.

    It is here because the air recovering only means something alongside what the element had
    to do to achieve it.
    """
    if close_min > open_min:
        ax.axvspan(open_min, close_min, color=c["ink_muted"], alpha=0.10, linewidth=0)
    ax.plot(t_min, heater_t, color=c["heater"], linewidth=2.0, solid_joinstyle="round")
    ax.set_ylabel("heating element (C)", color=c["ink_soft"], fontsize=10)
    ax.annotate(f"peak {summary['max_t_heater_c']:.1f} C", xy=(0.995, 0.08),
                xycoords="axes fraction", ha="right", va="bottom",
                color=c["ink_soft"], fontsize=9)


def _draw_state_strip(ax, c, t_min, heater_on, lid_open) -> None:
    """Two on/off bands: when the lid is open, and when the controller runs the heater."""
    ax.fill_between(t_min, 0.55, 0.95, where=lid_open, step="post",
                    color=c["ink_muted"], alpha=0.55, linewidth=0)
    ax.fill_between(t_min, 0.05, 0.45, where=heater_on, step="post",
                    color=c["heater"], alpha=0.80, linewidth=0)
    ax.set_ylim(0.0, 1.0)
    ax.set_yticks([0.75, 0.25])
    ax.set_yticklabels(["lid open", "heater on"], fontsize=9)
    ax.tick_params(axis="y", length=0)
    ax.grid(False)
    ax.spines["left"].set_visible(False)


def _edge_label(ax, y: float, text: str, color: str) -> None:
    """Name a threshold line out in the margin, where the curve cannot run into the words."""
    ax.annotate(text, xy=(1.005, y), xycoords=("axes fraction", "data"),
                xytext=(0, 0), textcoords="offset points",
                ha="left", va="center", color=color, fontsize=8.5,
                annotation_clip=False)


def _point(ax, x: float, y: float, c: dict, text: str,
           offset: tuple[int, int], ha: str, va: str) -> None:
    """A marked, directly labelled point. The surface-coloured ring keeps it legible on the band."""
    ax.plot([x], [y], marker="o", markersize=8, color=c["air"],
            markeredgecolor=c["surface"], markeredgewidth=2.0, zorder=5)
    ax.annotate(text, xy=(x, y), xytext=offset, textcoords="offset points",
                ha=ha, va=va, color=c["ink"], fontsize=9, zorder=6)


def _draw_heading(fig, c, simulation: dict) -> None:
    """What was simulated, and the conditions it was simulated under.

    It names the run, not its merit: no verdict is computed by this module and none is shown.
    """
    inputs = simulation["inputs"]
    duration_min = inputs["duration_s"] / 60.0

    headline = (f"Lid open {duration_min:.1f} min"
                if inputs["duration_s"] > 0 else "Lid kept shut (baseline)")
    if inputs["open_at_s"] > 0:
        headline += f", starting {inputs['open_at_s'] / 60.0:.1f} min from now"
    headline += "   -   predicted air temperature"

    fig.text(0.075, 0.9595, headline, color=c["ink"], fontsize=15, fontweight="bold",
             ha="left", va="center")
    fig.text(0.075, 0.9245,
             f"{inputs['phase'].replace('_', ' ')} phase   |   "
             f"room {inputs['t_room_c']:.1f} C   |   "
             f"starting from {inputs['t_air_start_c']:.2f} C air "
             f"({inputs['initial_from'].replace('_', ' ')})   |   "
             f"open lid modelled as {inputs['g_open_lid_ratio']:.1f}x the heat loss",
             color=c["ink_soft"], fontsize=10, ha="left", va="center")


def _print_table(result: dict) -> None:
    """The figure's numbers as text, so no value in it is reachable only by looking at a picture."""
    simulation = result["simulation"]
    s, i = simulation["summary"], simulation["inputs"]
    rows = [
        ("lid open", f"{i['duration_s']:.0f} s, from {i['open_at_s']:.0f} s"),
        ("phase", i["phase"]),
        ("safe band", f"{i['safe_band_c'][0]:.1f} - {i['safe_band_c'][1]:.1f} C"),
        ("air at start", f"{s['t_air_start_c']:.2f} C"),
        ("air at lid close", f"{s['t_air_at_close_c']:.2f} C"),
        ("lowest air", f"{s['min_t_air_c']:.2f} C at {s['min_t_air_at_s']:.0f} s "
                       f"(drop {s['drop_c']:.2f} C)"),
        ("measuring window", f"{s['event_window_s'][0]:.0f} - {s['event_window_s'][1]:.0f} s"),
        ("below safe band", f"{s['time_below_safe_band_s']:.0f} s "
                            f"(deepest {s['max_excursion_below_safe_band_c']:.2f} C)"),
        ("above safe band", f"{s['time_above_safe_band_s']:.0f} s"),
        ("recovery to band", "not inside the horizon"
                             if s["recovery_to_control_band_s"] is None
                             else f"{s['recovery_to_control_band_s']:.0f} s after lid close"),
        ("recovery to setpoint", "not inside the horizon"
                                 if s["recovery_to_setpoint_s"] is None
                                 else f"{s['recovery_to_setpoint_s']:.0f} s after lid close"),
        ("peak element temp", f"{s['max_t_heater_c']:.1f} C"),
        ("heater duty", f"{s['heater_duty_fraction'] * 100:.1f} % of the horizon"),
        ("solver samples drawn", f"{simulation['trajectory']['n_solver_samples']}"),
    ]
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"  {label.ljust(width)}  {value}")
    if result["figure_path"]:
        print(f"\n  figure written to {result['figure_path']}")


# --------------------------------------------------------------------------- command line

def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = plot_simulation(minutes=args.minutes,
                                 open_after_minutes=args.open_after_min,
                                 state_path=args.state,
                                 out_path=args.out,
                                 show=not args.no_show,
                                 dark=args.dark,
                                 full_horizon=args.full_horizon)
    except (SimulationError, StateSchemaError, DomainKnowledgeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1

    _print_table(result)
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Plot what a lid opening is predicted to do to the box. This shows the "
                    "simulation only; for whether it is acceptable for the batch, run "
                    "tools.cli.")
    p.add_argument("minutes", type=float,
                   help="how long the lid stays open, in minutes (0 = lid kept shut)")
    p.add_argument("--open-after-min", type=float, default=0.0,
                   help="when the lid opens, in minutes from now (default: 0, i.e. now)")
    p.add_argument("--out", default=None, metavar="PATH",
                   help="also save the figure to PATH (.png, .pdf, .svg)")
    p.add_argument("--no-show", action="store_true",
                   help="do not open a window; use with --out to only write the file")
    p.add_argument("--dark", action="store_true",
                   help="use the dark colour set")
    p.add_argument("--full-horizon", action="store_true",
                   help="draw the whole simulated hour instead of ending the view shortly "
                        "after the box is back at the setpoint")
    p.add_argument("--state", default=None, metavar="PATH",
                   help="read the incubator state from PATH instead of "
                        "state/current_state.json")
    args = p.parse_args(argv)
    if args.no_show and args.out is None:
        args.out = f"lid_opening_{args.minutes:g}min.png"
    return args


if __name__ == "__main__":
    sys.exit(main())
