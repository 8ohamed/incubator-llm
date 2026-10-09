# Incubator advisory

Ask the incubator's digital twin, in plain language, what opening the lid will do to a tempeh
batch.

## Setup

Python 3 (tested on 3.13). From this folder:

```
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

## Use

Open Claude Code in this folder and ask, for example:

> I want to open the lid for 5 minutes. Is that safe?

The `lid-opening` skill runs the simulation and risk assessment and explains the result.

If the answer comes back high risk, ask whether warming the box first would rescue it:

> Can you find me a heater boost so I can still open it for 5 minutes?

The `heater-boost` skill searches for the lowest setpoint that makes the opening acceptable and
returns it as a plan — what to set, how long to wait, and how long to keep the lid shut
afterwards — or reports that no boost is enough.

The advisory reads `state/current_state.json`. Four example states are included; copy one over
it to switch. Asked about a 5 minute opening:

| File | Batch | Room | Verdict | Heater boost |
|---|---|---|---|---|
| `state/state_a_safe.json` | 18 h, active growth | 22.4 °C | A, safe | not needed |
| `state/state_b_recoverable.json` | 3 h, lag phase | 22.4 °C | B, recoverable (keep shut 4 min) | not needed |
| `state/state_c_high_risk.json` | 3 h, lag phase | 17.0 °C | C, high risk | none makes it acceptable |
| `state/state_d_boost_helps.json` | 3 h, lag phase | 17.6 °C | C, high risk | 34 °C makes it B |

To run the tools directly:

```
python -m tools.cli --duration-s 300               # lid opening
python -m tools.heater_boost_cli --duration-s 300  # heater boost
```

## Seeing the prediction

Both commands above answer in numbers. To see the curve those numbers describe:

```
python -m tools.plot_simulation 5              # a 5 minute opening, in a window
python -m tools.plot_simulation 5 --out p.png  # and save it
```

The plot shows the simulation and nothing else: the predicted air temperature, the heating
element behind it, when the lid is open and the heater runs, the safe band for the batch's
phase, the controller's own band, and how long the air spends outside the safe band. The
simulation's figures are printed beside it.

**No verdict appears on the plot.** Whether an opening is acceptable is decided in
`tools/analyze.py`, and the plot neither runs it nor repeats it — a picture that already
announces the answer is no way to check the answer. Run `python -m tools.cli` for the verdict
and read it against a plot drawn without it. The advisory's answers are the same whether or not
anyone draws one.
