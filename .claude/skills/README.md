# Skills: two versions, use one at a time

This folder holds both versions of the two skills:

| Folder | Version |
|---|---|
| `lid-opening/`, `heater-boost/` | the original skills |
| `lid-opening-improved/`, `heater-boost-improved/` | the improved skills |

Each pair declares the same skill names (`lid-opening`, `heater-boost`), so **only one version may
be in this folder when Claude Code starts**. Before a session, move the two folders of the
version you are not using out of `.claude/skills/` (anywhere outside `.claude/`), start Claude
Code, and move them back afterwards.

- **Original skills:** move out `lid-opening-improved/` and `heater-boost-improved/`.
- **Improved skills:** move out `lid-opening/` and `heater-boost/`. To match the recorded runs
  exactly, also rename `lid-opening-improved/` to `lid-opening/` and `heater-boost-improved/` to
  `heater-boost/` while they are in use, since the folder path is shown to the model when a skill
  loads.
- **No skills (baseline):** move out all four.

Start a new Claude Code session after every change, so the session sees only the version in place.
