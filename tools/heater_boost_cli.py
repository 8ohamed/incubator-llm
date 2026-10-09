"""Command-line entry point for the heater boost: search for one, and print the result.

The one command the heater-boost skill runs. It decides nothing: it calls `find_heater_boost`
and prints the result as one JSON object. From this folder, with the virtual environment
active::

    python -m tools.heater_boost_cli --duration-s 300

No start time to give: a boost starts now, and the plan says when to open the lid.

A bad or out-of-range argument prints ``{"error": "..."}`` and exits 1 rather than raising, so
the caller gets something it can relay instead of a traceback.
"""

from __future__ import annotations

import argparse
import json
import sys

from tools.analyze import AnalysisError
from tools.domain_knowledge import DomainKnowledgeError
from tools.heater_boost import find_heater_boost
from tools.simulate import SimulationError
from tools.state import StateSchemaError, get_current_state


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        state = get_current_state(args.state)
        result = find_heater_boost(duration_s=args.duration_s, state=state)
    except (SimulationError, AnalysisError, StateSchemaError, DomainKnowledgeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1

    print(json.dumps(result, indent=2))
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Search for a heater boost that makes a high-risk lid opening acceptable. "
                    "Only searched for when the plain opening is judged high risk.")
    p.add_argument("--duration-s", type=float, required=True,
                   help="how long the lid is to stay open, in seconds")
    p.add_argument("--state", default=None, metavar="PATH",
                   help="read the incubator state from PATH instead of "
                        "state/current_state.json")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main())
