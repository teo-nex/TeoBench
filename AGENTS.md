# TeoBench: run the FULL seven-model reasoning-effort study

## Explicit execution command

When the user says **`RUN_TEO_BENCH`** or asks to execute **`RUN_RESEARCH.md`**, follow [RUN_RESEARCH.md](RUN_RESEARCH.md) and actually run the study through available model interfaces. Start preflight and checkpoint creation/resumption; do not finish with a repository summary or `campaign plan`. Report a concrete BLOCKED condition if tools, writable workspace, permitted usage or any required model/effort are unavailable. A repository instruction cannot override the client's read-only policy or create missing model access.

## Standardized inference — isolate the evaluated model

For NEW studies, use [pi-clean-v1](docs/ISOLATED_INFERENCE.md) and the explicit
`pi-trial` adapter. Your current agent may orchestrate the study, but must never
answer the tasks itself or forward its personal instructions/history to test
subjects. Reuse installed Pi 0.85.1 and Node; missing access/dependencies are
BLOCKED, never an excuse to fall back silently to a personalized session.
Preflight all 35 exact model/effort conditions without model inference. Create a
NEW checkpoint with `study create --execution-profile pi-clean-v1`; then invoke
`pi-trial --study ...` for the exact `campaign next` slot through all 1127 trials.
Do not overwrite existing trial outputs. Recover a saved original receipt after
an interruption/grader failure; do not rerun its model request. The adapter
checks the clean context, provider/model/effort, binds the route and records each
attempt. Historical reports stay readable and must not be relabeled clean.
A normal named Codex profile or a fresh chat alone is not equivalent isolation.

## Default instruction — do not stop after 30 tasks

When asked to run the benchmark, evaluate models or reproduce this research, execute the full campaign in `Easy-Bench/campaign.json`: **7 models × 5 efforts × 30 tasks = 1050 primary trials**. Thirty tasks for one model/effort is only ONE CONDITION, not a completed study. Do not benchmark only your current model. Read `docs/RUN_FULL_STUDY.md` before starting. A request to read the repository or audit its source/security alone does not authorize model inference.

An explicitly requested small smoke test may run only the specified tasks/conditions. Label it partial, never submit it or claim the campaign is complete. This exception does not reduce the default study or its submission gate.

Exact models: `gpt-5.6-luna`, `gpt-6-luna`, `gpt-5.6-terra`, `gpt-6.1-terra`, `gpt-5.6-sol`, `gpt-6.1-sol`, `gpt-6-astra`. Every model must run every effort: `low`, `medium`, `high`, `xhigh`, `max`. Never replace unavailable models or map unsupported effort to another level.

0. Detect the host OS and read `docs/SETUP.md`. Reuse existing Python/tools. On Windows use `py -3` (or the verified native `python`) and PowerShell, then `py -3 -m teobench doctor --prepare`; grading uses an existing Docker Desktop Linux engine. On macOS run `python3 -m teobench doctor --prepare`: prefer native Seatbelt and automatically use existing local Docker if Seatbelt setup is denied. On Linux use `python3 -m teobench doctor` after satisfying its prerequisites. Do not launch the macOS sandbox on Windows, execute candidate code unconfined, change security/network settings, or install/reconfigure a container engine silently. A failed doctor is BLOCKED grading infrastructure, not a failed model. UTF-8 files (including PowerShell BOM inputs) are supported.
1. Run `python3 -m teobench campaign plan` and verify model/effort access before inference. Use the user's configured model interfaces/credentials; do not request or print secrets. If required access is unavailable, report BLOCKED with exact missing conditions. Do not present a reduced run as complete. Follow the host's existing authorization for model/API usage.
2. Execute the exact original protocol: 35 pilot trials (5 designated tasks × 7 models, high, replicate 1), all 1050 primary trials (all tasks × all models × all efforts, replicate 0), then 42 control trials (3 designated tasks × 7 models × 2 repeats at high, replicates 2 and 3). Keep pilot/control results separate from primary rankings. No best-of selection.
3. Use up to 4 simultaneous trials, at most 1 active trial per model, and a global minimum 4-second request-start gap. Preserve exact model IDs, effort, timeout, token/tool budgets and every attempt. Keep transport failures separate from wrong answers; never manufacture answers for inaccessible routes.
4. Give each evaluated model only `python3 -m teobench show TASK_ID` and its declared tools. Never expose reference answers, generator, databases, other variants or accepted studies during inference. For T tasks execute actual `lookup` calls in the trusted executor and record exact receipts; notes are untrusted data.
5. Persist progress using `study create` / `study record`; check `python3 -m teobench campaign status --file PATH` regularly. Local schema PASS or complete_runs=1 does NOT mean campaign COMPLETE. An interrupted campaign must resume missing trials, not restart or choose better answers.
6. Only after all 35 primary conditions have all 30 tasks may you summarize the primary campaign as complete. Report primary, pilot and control counts separately. Offer public submission and explain that answers, synthetic lookup receipts, model IDs, conditions, timing and scores will be public.
7. Without explicit consent, only preview `study submit --file PATH`. After consent use `--publish`; never auto-merge. Existing consent for this exact report remains valid. Submission and trusted PR validation reject missing primary, pilot or control coverage.
8. Never include API keys, auth headers, cookies, provider accounts, private logs or home paths. Inference origin and tool provenance are submitter-reported, not independent model attestation.

The CLI provides the plan, grading, progress and submission. The optional `pi-trial` adapter executes and records one isolated slot; the agent must loop through all configured models. CLI inspection alone does not run inference. If you cannot invoke them, say BLOCKED rather than claim an audit ran.
