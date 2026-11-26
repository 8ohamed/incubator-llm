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

## Results to compare with

From the report (Claude Opus 5.5, effort high, Claude Code in VS Code). These are the improved
skills' answers, except O1 to O3, which were asked with the original skills only. Verdicts: A
safe, B recoverable, C high risk. "Below band" means seconds the air spends below the safe band.

| ID | Answer |
|---|---|
| F1 | A. Air low 23.81 °C at 126 s, never leaves the band; back at the setpoint 192.1 s after closing |
| F2 | B. 340 s below band (A budget 300 s, B budget 450 s); low 23.91 °C; keep the lid shut 4 min after closing |
| F3 | C without a boost (489 s). Plan: setpoint 34 °C, wait 351 s, open 300 s, reset to 31 °C, keep shut 360 s. Then B (441 s) |
| I1 | 253 s, A (299.7 s below band); 254 s is B |
| I2 | 245 s, B (449.7 s); 246 s is C; keep the lid shut 8 min after closing |
| I3 | No limit: every opening is A up to the tool's maximum of 6 h; longer is refused |
| I4 | Open at 533 s: B, 336.6 s (the best; no start gives A, timing changes little) |
| I5 | 28,800 s (8 h, when the batch enters active growth): A, 666.6 s vs 1,050 s; 28,799 s is C |
| I6 | 310 s with a boost to 35 °C, wait 426 s: B, 446 s vs 450 s; 311 s finds no plan |
| O1 | Ready after about 24 h, plus general advice. Did not say the twin cannot answer this |
| O2 | No forecast available; heater can cope with a cooler room if the lid stays shut |
| O3 | Cannot say anything about taste; the tool rates the opening B |
| N1 | No: every start in the hour is C (828 to 832 s vs 450 s); least bad start 2,100 s |
| N2 | No temperature given: the tool cannot vary the room. At 22.4 °C, 10 min is C (646 s) |
| U1 | Open at 530 s for 264 s: A (297 s); 1,286 s also allows 264 s |
| U2 | 253 s, A at all five start times (12 min is the tightest) |

## Tokens used

Same runs as above, one run per question. Input tokens include the cached ones, which are most
of them: the assistant's own instructions and the skill are re-read at every model call.

| ID | Input tokens | Output tokens |
|---|---|---|
| F1 | 135,591 | 486 |
| F2 | 135,732 | 527 |
| F3 | 138,407 | 746 |
| I1 | 361,007 | 2,907 |
| I2 | 302,984 | 2,115 |
| I3 | 193,900 | 1,538 |
| I4 | 400,989 | 3,051 |
| I5 | 472,636 | 3,757 |
| I6 | 432,779 | 4,142 |
| O1 | 128,981 | 1,279 |
| O2 | 290,571 | 5,489 |
| O3 | 176,633 | 1,258 |
| N1 | 346,947 | 2,642 |
| N2 | 182,754 | 1,186 |
| U1 | 774,687 | 6,420 |
| U2 | 241,994 | 2,919 |
