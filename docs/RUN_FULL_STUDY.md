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

> RUN_TEO_BENCH: execute RUN_RESEARCH.md now. Run all 1127 trials through my configured model interfaces, preserve exact IDs and efforts, persist every attempt and resume missing trials. Do not stop at reading the repository, printing a plan, running 30 tasks or evaluating only your current model. Continue to COMPLETE or report a concrete BLOCKED condition. Show results and ask before publishing.

The [root execution task](../RUN_RESEARCH.md) distinguishes actual model trials from read-only CLI commands. `RUN_TEO_BENCH` is a message to the agent, not a shell executable. Client read-only restrictions and missing model access cannot be changed by Markdown instructions; report those exact blockers instead of claiming the research ran.

A user may explicitly request a narrow smoke test (for example, two real tasks) to check OS setup. Keep it local and label it partial; it does not satisfy campaign completion or submission.

## Execution order

0. Detect the OS and follow [SETUP.md](SETUP.md). Require a passing `doctor` before inference. Replace `python3` below with `py -3` on Windows; use PowerShell syntax instead of Bash continuation.
1. Inspect `python3 -m teobench campaign plan`. Use `python3 -m teobench campaign next --file local-runs/study.json` to obtain each missing trial with its exact model/effort and model-facing task; execute it and record the answer, then repeat. Confirm access to all 35 model/effort combinations using the user's configured interfaces. These are exact model identifiers from the source study; they are not a promise that every provider/account exposes them. Never silently substitute models/efforts or label unavailable routes completed.
2. Create a local report as shown in the root README. Complete **35 pilot trials**, high effort, task IDs R01/C04/S03/D06/T01, all seven models, `--replicate 1`.
3. Complete **1050 primary trials**, every task, every model and all five efforts, `--replicate 0`. Each task must be a fresh independent trial; tool calls within a trial remain sequential. Retain every answer and transport failure.
4. Complete **42 control trials**, high effort, task IDs R04/D03/T03, all seven models, `--replicate 2` and `--replicate 3`. These reserved replicate numbers distinguish phases in the shared report; they do not change the source protocol's two control repeats.
5. Run `python3 -m teobench campaign status --file local-runs/study.json`. Primary coverage must show 1050/1050 and 35 complete conditions; the full original protocol is 1127/1127 including pilot/control trials. An unfinished checkpoint is not a completed campaign.
6. Validate answers, summarize all 35 primary conditions, show the public-data preview and ask whether to contribute. After consent `study submit --file ... --publish` creates a PR. Trusted GitHub validation rejects incomplete primary, pilot or control coverage. Earlier accepted primary-only studies remain readable; they are not evidence of a new full-protocol run.

Use up to 4 concurrent trials, at most one per model, at least 4 seconds between request starts globally, and 240-second trial timeouts. For Responses-style streams, follow the [terminal-event transport contract and opt-in collector](STREAMING_TRANSPORT.md): completion is not HTTP EOF, and partial output must survive failures without becoming a successful answer. Do not provide references to the evaluated model. Preserve model/tool/token settings in `method`. API/model access is supplied by the participant, not by TeoBench. The optional `pi-trial` and `codex-trial` adapters execute one isolated trial; the agent still coordinates the full plan. Other transports are not automatically standardized. If it cannot, the result is BLOCKED, not successful research.

## Clean evaluated-model context

New studies use [clean inference](ISOLATED_INFERENCE.md). Your current Codex/Pi/other
agent is the orchestrator; evaluated models must not inherit its instructions,
skills, extensions or conversation. Create a separate checkpoint using
`study create --execution-profile auto`: installed Pi is preferred; otherwise use
[disposable Codex](CODEX_FALLBACK.md). Preflight every condition, and execute the
returned `trial_command` (`pi-trial` or `codex-trial`) with `--study ...` for each
exact next slot. Keep the selected adapter throughout the checkpoint. The profile/route
fingerprints separate these results from historical personalized runs. Never
silently fall back when clean execution is unavailable.

## Existing clones

Run `git pull --ff-only`, then tell the agent to reread AGENTS.md and resume the full matrix. Previously collected 30-task results can be retained for their exact model/effort/replicate; collect the missing 1020 primary trials instead of discarding or duplicating them. Keep all original attempts; do not replace lower-scoring answers.
