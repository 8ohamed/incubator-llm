"""Command-line entry point: simulate a lid opening, then assess its risk to the batch.

The one command the lid-opening skill runs. It decides nothing: it calls `simulate_lid_opening`
and `assess_lid_opening` and prints the combined result as one JSON object. Putting that into
words is the skill's job. From this folder, with the virtual environment active::

    python -m tools.cli --duration-s 300 [--open-at-s 600]

A bad or out-of-range argument prints ``{"error": "..."}`` and exits 1 rather than raising, so
the caller gets something it can relay instead of a traceback.
"""

from __future__ import annotations

import argparse
import json
import sys

from tools.analyze import AnalysisError, assess_lid_opening
from tools.domain_knowledge import DomainKnowledgeError
from tools.simulate import SimulationError, simulate_lid_opening
from tools.state import StateSchemaError, get_current_state


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        state = get_current_state(args.state)
        simulation = simulate_lid_opening(
            duration_s=args.duration_s,
            open_at_s=args.open_at_s,
            state=state,
        )
        risk = assess_lid_opening(simulation, state=state)
    except (SimulationError, AnalysisError, StateSchemaError, DomainKnowledgeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1

    print(json.dumps({"simulation": simulation, "risk": risk}, indent=2))
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Simulate a lid opening from the current incubator state and assess its "
                    "risk to the fermentation batch.")
    p.add_argument("--duration-s", type=float, required=True,
                   help="how long the lid stays open, in seconds (0 = lid kept shut)")
    p.add_argument("--open-at-s", type=float, default=0.0,
                   help="when the lid opens, in seconds from now (default: 0, i.e. now)")
    p.add_argument("--state", default=None, metavar="PATH",
                   help="read the incubator state from PATH instead of "
                        "state/current_state.json")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main())
