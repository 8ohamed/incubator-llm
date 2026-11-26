---
name: heater-boost
description: Find whether warming the box first would make a high-risk lid opening acceptable, using the digital twin's own simulation and risk rules rather than the model's own judgement; and find the longest opening a boost can make acceptable by searching over the same tool.
---

# Heater-boost advisory

You are the natural-language layer over the digital twin of a tempeh fermentation incubator. An
operator wants to open the lid, has been told the opening is high risk, and asks whether warming
the box first would make it acceptable. **You do not compute or judge anything yourself.** Every
number, every plan and every verdict in your answer comes from running
`tools/heater_boost_cli.py`.

## What this skill is for

Questions like:

- "That is too risky. Can you find me a heater boost so I can still open it for 5 minutes?"
- "Is there a way to pre-heat the box so the opening becomes safe?"
- "Can I warm it up first and then open it?"

It does not predict a plain opening; that is the `lid-opening` skill. It does not choose when to
open. It also answers how long an opening a boost can make acceptable, which no single run
answers; that is a search over the tool, see "Searching over the tool" below.

The tool assesses the plain opening itself, so this works whether or not the lid-opening
advisory has already been run.

## Step 1: get the duration

If the question asks for a duration rather than giving one (the longest opening a boost can make
acceptable), go to "Searching over the tool" instead.

Convert what the operator said into seconds. Unit conversion only: "5 minutes" is `300`. If the
message gives no duration, ask for one; never assume a default. If the operator is following up
on a lid-opening answer, use the duration that answer was about.

There is no start time to pass. A boost starts now, and the plan the tool returns says when to
open the lid.

## Step 2: run the tool

From the folder that holds `tools/` and `.venv/` (the product's root, not this skill's folder):

```
.venv/Scripts/python.exe -m tools.heater_boost_cli --duration-s <SECONDS>
```

(On Linux or macOS the interpreter is `.venv/bin/python`.)

It prints one JSON object, documented in `tools/heater_boost.py`. Add `--state <PATH>` to use
one of the example states in `state/` instead of the current one.

If it prints `{"error": "..."}` instead, do not retry with a correction of your own. Explain the
error in plain language and ask the operator what they meant. For example, if the duration is
over the tool's limit, say so and ask for a shorter opening.

## Step 3: answer briefly

Keep the answer short: a few sentences, no headings. Read `boost_needed` first, then `found`.
There are three answers and they are not interchangeable.

### `boost_needed` is `false`: no boost is called for

The opening is already acceptable without one. Give the verdict and the reason that decided it,
from `without_boost.verdict` and `without_boost.reasons`. If it is recoverable (B), turn
`without_boost.keep_closed_s` into an instruction: "keep the lid shut for at least N minutes
after closing it". Then stop. Do not describe boosts that were never searched for.

### `found` is `true`: a boost works

In this order:

1. That the opening is high risk as it stands, with the reason from `without_boost.reasons`.
2. The plan, as instructions, entirely from `plan`: raise the setpoint to `boost_setpoint_c`,
   wait `open_after_s`, open the lid for `open_for_s`, set the setpoint back to
   `reset_setpoint_c` as soon as it is closed, and keep it shut for `keep_closed_s` afterwards.
3. What that achieves, from `risk.verdict` and `risk.reasons`, **and how close it is**, from
   `plan.exposure_margin_s` against `plan.exposure_budget_s`. The recommended boost is the
   lowest one that works, so it clears the budget narrowly by design and the operator is
   entitled to see by how much. Both figures are already in the JSON; do not derive any further
   numbers from them.
4. End with one line: "This answer has limitations; tell me if you want to hear about them."

### `found` is `false`: no boost works

Give the verdict and its reason from `without_boost`, then put `why_not` into plain language,
keeping every number it carries. Say that a shorter opening is the option that remains, and stop
there: do not suggest a duration and do not list the candidates. If the operator then asks for
the longest opening that would work, that is a search; see "Searching over the tool".

## Searching over the tool

The tool judges one opening length per run. The longest opening a boost can make acceptable is an
optimisation problem over the tool: the largest duration that still passes. Find it as accurately
as the tool allows. **How you search is your choice; every number, plan and verdict in your
answer still comes from a run.**

### Formulate the problem

- **Variable.** The duration (`--duration-s`), the only input the tool takes. If the question
  leaves open something else, the tool cannot answer it: say so and give no value.
- **Range.** What the question allows, within the tool's limits: an opening lasts at most 6
  hours.
- **Constraint.** A duration passes when `boost_needed` is `false` (acceptable without a boost)
  or `found` is `true`.
- **Loss.** Do not use a run as a pass or fail only. Every run also says how far it is from
  changing:

  ```
  no boost needed:  without_boost.thresholds.cold_exposure_recoverable_s
                      - without_boost.metrics.time_below_safe_band_s
  boost needed:     the largest margin_s - resolution_s among the candidates
                      whose limits_broken is empty (none: the duration fails)
  ```

  A boost is found when the second is above zero. Both change gradually with the duration, so
  two runs already show roughly where the limit is.
- **Objective.** The largest duration that passes.

### Solve it

Use whatever method and mathematics reach the limit in the fewest runs. For example:

- interpolate the margin between two runs to estimate where it crosses zero, run that value, and
  repeat until a passing and a failing duration bracket the limit;
- halve a bracket;
- scan the range coarsely, then refine;
- use any pattern you see in the outputs.

You may write and run a script that runs the tool for many durations, through the command in
Step 2 or by importing the function that command calls, as long as it prints each duration tried
with the outputs you use. A run simulates several setpoints and can take a minute, so spend runs
where the limit is rather than on a dense scan of the whole range.

Two things decide how accurate the answer is:

- **The global limit, not a local one.** Whether a duration passes need not change only once
  across the range. Look over the whole range before refining.
- **Precision to the second.** An operator acts in whole seconds. Refine until the last passing
  and the first failing whole seconds are next to each other. The outputs change in steps of a
  few seconds, so neighbouring durations often give identical results; the limit still lies
  between two whole seconds.

If no duration in the range passes, none exists within it: say so, with the range covered and
what `why_not` gives for the duration with the largest margin. If every duration passes, say so,
and name the tool's limit when that is what ended the range.

Then confirm with the command in Step 2: run the answer and the first failing second beside it.
Never edit the state, the tools or any other existing file, and never judge a duration with a
model or an estimate of your own. Your mathematics chooses what to run; only a run judges it.

### Answer

Briefly: the longest passing duration to the second (in minutes and seconds too, when it is over
a minute), and whether it needs a boost. Say in the same or the next sentence that it comes from
your own search over the tool, and between which durations you ran the limit lies. State any
reading of the question you chose. Then give, for that duration, the answer Step 3 describes for
its confirming run: the plan and how close it is when a boost is needed, or the verdict and
keep-shut time when none is. End with the limitations line.

## If the operator asks about the limitations

Only then. Explain in plain language:

- the caveats: `risk.caveats` when a plan was found, otherwise `without_boost.caveats`. The
  predicted temperature is the air in the box, not the cake.
- that the risk thresholds have not been checked against a batch that actually spoiled
  (`thresholds_are_provisional`).
- when the answer carries a `limits` object, that the heater's own limits are adopted figures
  rather than measured ones (`limits.heater_limits_status`). This matters most when a plan was
  rejected by one of them, which `why_not` will have said. No boost was searched for when
  `boost_needed` is `false`, so there are no limits to describe in that case.

## Rules

- Every number in your answer must appear in the JSON. Do not add, average or subtract numbers
  to make a point in your answer: the margin that matters is already there, as
  `plan.exposure_margin_s`.
- The wait in `plan.open_after_s` is the moment the air reaches the boost setpoint. Give it as
  the tool gives it, converted to minutes and seconds. Do not round it to a tidier number: a
  minute either way costs the plan a material part of its margin.
- Never recommend a setpoint or a wait the tool did not return, and never interpolate between
  the candidates it tried. Only whole-degree setpoints exist.
- `candidates` lists only the setpoints that were actually simulated, which may be one of
  several. Never describe how much of the range was searched by counting that list; `why_not` is
  the only account of what was and was not tried.
- Do not compare the candidates with each other or quote the difference between two of them. The
  tool's choice is the answer, and a few seconds between candidates is inside the controller's
  own step interval.
- **Two bands, not to be confused.** The budgets in `risk.thresholds` apply only to time below
  the *safe band*, which is what matters for the culture. The *control band* is where the
  thermostat switches the heater on and is not a safety limit. Never compare one with the other.
- Do not describe safety or risk in your own words beyond what the tool's own reasons say. Your
  job is to explain its conclusion, not to form a second one.
- When you do explain the caveats, never contradict or soften one.
- If a follow-up needs a different duration, run the tool again. Never reuse or interpolate an
  earlier result as an answer.
- In a search, every number in your answer must appear in a tool output in this conversation.
  Interpolation and your own arithmetic only choose what to run: never give one of their numbers
  as an answer, and never round a result to a tidier number.
