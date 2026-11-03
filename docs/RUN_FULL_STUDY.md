# Run the full Easy-Bench study

The default research is **7 models × 5 reasoning efforts × 30 unchanged tasks = 1050 primary trials**, not a single 30-task run. The authoritative machine-readable configuration is [campaign.json](../Easy-Bench/campaign.json).

| Model | Required effort settings | Primary trials |
|---|---|---:|
| gpt-5.6-luna | low, medium, high, xhigh, max | 150 |
| gpt-6-luna | low, medium, high, xhigh, max | 150 |
| gpt-5.6-terra | low, medium, high, xhigh, max | 150 |
| gpt-6.1-terra | low, medium, high, xhigh, max | 150 |
| gpt-5.6-sol | low, medium, high, xhigh, max | 150 |
| gpt-6.1-sol | low, medium, high, xhigh, max | 150 |
| gpt-6-astra | low, medium, high, xhigh, max | 150 |

## Give this to your agent

> Read AGENTS.md and Easy-Bench/campaign.json. Reproduce the full seven-model reasoning-effort study: 1050 primary trials across all 35 model/effort conditions, plus the defined 35 pilot and 42 control trials. Use my configured model interfaces, preserve exact IDs and efforts, persist progress, and resume missing trials. Do not stop at 30 tasks or evaluate only your current model. If any required route or effort is unavailable, report BLOCKED without substitution. After completion, show the results and offer to submit the study to TeoBench; publish only with my consent.

A user may explicitly request a narrow smoke test (for example, two real tasks) to check OS setup. Keep it local and label it partial; it does not satisfy campaign completion or submission.

## Execution order

0. Detect the OS and follow [SETUP.md](SETUP.md). Require a passing `doctor` before inference. Replace `python3` below with `py -3` on Windows; use PowerShell syntax instead of Bash continuation.
1. Inspect `python3 -m teobench campaign plan`. Use `python3 -m teobench campaign next --file local-runs/study.json` to obtain each missing trial with its exact model/effort and model-facing task; execute it and record the answer, then repeat. Confirm access to all 35 model/effort combinations using the user's configured interfaces. These are exact model identifiers from the source study; they are not a promise that every provider/account exposes them. Never silently substitute models/efforts or label unavailable routes completed.
2. Create a local report as shown in the root README. Complete **35 pilot trials**, high effort, task IDs R01/C04/S03/D06/T01, all seven models, `--replicate 1`.
3. Complete **1050 primary trials**, every task, every model and all five efforts, `--replicate 0`. Each task must be a fresh independent trial; tool calls within a trial remain sequential. Retain every answer and transport failure.
4. Complete **42 control trials**, high effort, task IDs R04/D03/T03, all seven models, `--replicate 2` and `--replicate 3`. These reserved replicate numbers distinguish phases in the shared report; they do not change the source protocol's two control repeats.
5. Run `python3 -m teobench campaign status --file local-runs/study.json`. Primary coverage must show 1050/1050 and 35 complete conditions; the full original protocol is 1127/1127 including pilot/control trials. An unfinished checkpoint is not a completed campaign.
6. Validate answers, summarize all 35 primary conditions, show the public-data preview and ask whether to contribute. After consent `study submit --file ... --publish` creates a PR. Trusted GitHub validation rejects incomplete primary, pilot or control coverage. Earlier accepted primary-only studies remain readable; they are not evidence of a new full-protocol run.

Use up to 4 concurrent trials, at most one per model, at least 4 seconds between request starts globally, and 240-second trial timeouts. Do not provide references to the evaluated model. Preserve model/tool/token settings in `method`. API/model access is supplied by the participant, not by TeoBench. There is no universal provider runner bundled in this release: the agent executes the plan through its configured interfaces. If it cannot, the result is BLOCKED, not successful research.

## Existing clones

Run `git pull --ff-only`, then tell the agent to reread AGENTS.md and resume the full matrix. Previously collected 30-task results can be retained for their exact model/effort/replicate; collect the missing 1020 primary trials instead of discarding or duplicating them. Keep all original attempts; do not replace lower-scoring answers.
