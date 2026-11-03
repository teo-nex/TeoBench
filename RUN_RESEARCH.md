# RUN_TEO_BENCH — execute the research

This is an execution task for an agent with tools and the participant's existing
model access. It is not a repository summary, code review or dry run.

When the user sends **`RUN_TEO_BENCH`** or asks you to execute this file:

1. Read [AGENTS.md](AGENTS.md), [OS setup](docs/SETUP.md),
   [security boundaries](SECURITY.md) and the
   [full protocol](docs/RUN_FULL_STUDY.md). Use a writable checkout. If the client
   permits only reading, report `BLOCKED: read-only workspace/tool policy` and
   the exact permission needed; do not bypass the client's restrictions.
2. Run the OS-specific `doctor` and verify the frozen dataset. Discover the
   participant's configured model interfaces without displaying credentials.
   Confirm all 35 exact model/effort combinations in
   [campaign.json](Easy-Bench/campaign.json). Missing sandbox, model access,
   allowed usage or write permission is a concrete blocker, not success.
3. Create or resume a current-grader checkpoint under `local-runs/`. Follow the
   execution order: **35 pilot + 1050 primary + 42 control = 1127 attempts**.
   Invoke each requested model/effort through its actual interface. Do not
   answer as the orchestrator, import old answers as fresh observations, invent
   tool receipts, substitute routes or reduce the matrix.
4. Persist every answer or transport failure immediately with `study record`.
   Use up to four concurrent trials, at most one per model, a global four-second
   start gap and 240-second trial timeouts. Resume missing trials after
   interruption; do not select better attempts. Keep references out of inference.
5. Continue beyond inspection commands. `verify`, `doctor`, `show`, `list`,
   `campaign plan` and reading documentation execute **zero model trials**.
   A successful preflight is the start of the research, not its completion.
6. Finish only when campaign coverage is `COMPLETE` with all 1127 slots and
   answer validation passes, or when a concrete blocker prevents progress.
   Report the checkpoint, model/effort coverage, actual recorded counts and any
   missing conditions. Never label a 30-task condition a full study.
7. Show results and the public submission preview. Offer to contribute them;
   call `study submit --publish` only with the user's consent for this report.

The CLI supplies grading, progress and submission; it is not a universal model
API runner. An agent must perform the model calls through available interfaces.
This file does not install model access or override account/host permissions.
