# Reproducibility overview

How to rerun the questions so the answers can be compared with the report.

## Setup (once per question)

1. **Pick the skills.** Claude Code reads `.claude/skills/`, Codex reads `.agents/skills/`. Both
   folders hold both versions. **Before you type the first prompt, erase the folders of the
   version you are not using** from the folder your assistant reads:
   - improved: erase `lid-opening/` and `heater-boost/`
   - original: erase `lid-opening-improved/` and `heater-boost-improved/`
   - no skills: erase all four

   The other folder still has a copy, so you can restore them from there afterwards. To match
   the recorded improved runs, also rename `lid-opening-improved/` to `lid-opening/` and
   `heater-boost-improved/` to `heater-boost/`. With Codex, also turn its memories off
   (`~/.codex/memories`), so no earlier notes are read.
2. **Set the scenario.** Copy the question's state file over the current state:
   `state/state_X_....json` → `state/current_state.json`
3. **Start a fresh session** in this folder, with memory off. Use one session per question.
4. **Type the prompt exactly as written below**, and nothing else. If the assistant asks
   something back, reply once with:
   > I have no more details. Please answer as best you can.
5. **Save** the transcript. Note the model, its effort setting and the date.

## Scenarios

| Scenario | File | Batch | Room |
|---|---|---|---|
| A | `state/state_a_safe.json` | 18 h, active growth | 22.4 °C |
| B | `state/state_b_recoverable.json` | 3 h, lag | 22.4 °C |
| C | `state/state_c_high_risk.json` | 3 h, lag | 17.0 °C |
| D | `state/state_d_boost_helps.json` | 3 h, lag | 17.6 °C |

## Questions

| ID | Scenario | Prompt |
|---|---|---|
| F1 | A | I want to open the lid for 5 minutes now. What happens to the batch? |
| F2 | B | What happens if I open the lid for 5 minutes, starting in 10 minutes? |
| F3 | D | Opening the lid for 5 minutes is too risky. Can I heat the box first so it becomes acceptable? |
| I1 | B | What is the longest I can open the lid and still keep the batch safe? |
| I2 | C | How long can I keep the lid open without putting the batch at high risk? |
| I3 | A | How long can the lid stay open before the batch is at risk? |
| I4 | B | I need the lid open for 5 minutes sometime in the next 10 minutes. When is the best moment? |
| I5 | C | When is the earliest I could open the lid for 10 minutes without putting the batch at high risk? |
| I6 | D | What is the longest opening that heating the box first can make acceptable? |
| O1 | A | When is the best time to eat tempeh? |
| O2 | A | Will the room get colder tonight, and should I be worried about the batch? |
| O3 | B | If I open the lid for 5 minutes, will the tempeh taste worse? |
| N1 | C | Can I open the lid for 10 minutes at some point in the next hour without putting the batch at high risk? |
| N2 | B | What room temperature would let me open the lid for 10 minutes safely right now? |
| U1 | B | I need to open the incubator sometime within the next 30 minutes. When should I open it, and for how long, to maximize the opening duration while keeping the batch safe? |
| U2 | B | I plan to open the incubator in 10 minutes, but I might be up to 2 minutes early or late. What is the longest duration I can keep the lid open while ensuring the batch remains safe if I start at 8, 9, 10, 11, or 12 minutes from now? |

The report asked U1 and U2 with the improved skills only, and O1 to O3 with the original skills
only.
