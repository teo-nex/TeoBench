# TeoBench Medium — public 100-task selection (preparation)

**Not yet runnable or runtime-accepted. No Medium model results exist in this
branch.** Easy's `RUN_TEO_BENCH` command still runs Easy; it does not run this set.

This freezes the proposed public-source composite before any scored inference:

| Source | Selected | Stratum |
|---|---:|---|
| Terminal-Bench 2.1 | 25 | Task category |
| SWE-bench Pro V2, default | 25 | Repository |
| SWE-bench Verified | 20 | Repository |
| BIRD Mini-Dev, SQLite | 15 | Database |
| SpreadsheetBench 2 | 15 | Debugging / Financial Model / Template |

Seven original models × five original effort levels × 100 tasks = **3500
primary attempts**. These are additional to transport and verifier checks.
Report each source separately. Any composite uses equal source weights (20%
each), not raw pooling by source task count. Do not compare it directly with
official full-dataset leaderboard scores or the Easy cohort.

## Reproduce and inspect the selection

Use Python 3.11+ and an isolated preparation environment with
`pyarrow==26.0.1`. Preparation downloads public files into the explicitly chosen
cache. It does not execute upstream code, start engines or make model requests.

```sh
python scripts/prepare_medium.py --cache /path/to/private/cache --output Medium-Bench/manifest.json
python -m teobench.medium verify
python -m teobench.medium plan
```

The selection uses a fixed seed, SHA-256 rank and round-robin strata. Terminal
tasks are filtered before selection to zero GPUs, at most 4 CPUs, 8192 MiB RAM
and 40960 MiB storage. Spreadsheet variants sharing a golden workbook count as
one family; Visualization is excluded. Task selection never uses model scores.
SWE repository/base-commit duplicates are rejected across the two sources.
Changing tasks, versions, input files or selection rules requires a new cohort.

Source revisions, archive hashes, record hashes, public-input hashes and task
IDs are in `manifest.json`. The preparation cache includes gold answers and
test patches: **never expose or mount that cache in the candidate sandbox**.
The selection metadata itself is not the model prompt. Source licenses still
apply; this manifest does not relicense upstream tasks or repositories.

## Execution acceptance still required

Medium must use a new clean Pi profile, separate from `pi-clean-v1` for Easy.
Its terminal/file tools must act only in a disposable container. No personal
skills, AGENTS.md, extensions, session history, host filesystem or credentials
may reach the candidate. Preserve each first attempt and actual route/effort;
never substitute unavailable models, remap effort, retry for a better score,
or label transport failures wrong answers.

Before the 3500 primary attempts, pin and validate all five official evaluator
adapters, resolve container image digests, run oracle/no-op/corrupt-output
checks, and verify clean Pi tool execution. Recalculate spreadsheet inputs and
gold workbooks with the upstream LibreOffice protocol before inference. Use
unique SWE run IDs for each observation to avoid stale evaluator caches.
Resource and quota checks must stop safely rather than switch billing routes.

The experimental `pi-medium-sandbox-v1` scaffold uses installed Pi 0.85.1 with
only a `terminal` tool. Its tool acts inside a private container, never on the
host. `medium_pi_smoke` uses an existing image without pulling or reconfiguring
an engine. Its 35-condition preflight makes no model requests; the live smoke
is a small file-read / compute / file-write exercise, not one of the 100 tasks.
The local gateway key is supplied through a dedicated environment variable,
referenced by name in temporary routing configuration; it is never persisted
in model configuration, included in the prompt or forwarded into the container.

To exercise it, create a routing-only JSON file with `base_url`, `api`
(`openai-responses` or `openai-completions`) and `model_routes` (an explicit map
for all seven exact model IDs; a provider prefix is allowed). Have your trusted
launcher load the existing gateway credential into `TEOBENCH_GATEWAY_KEY` in
memory. Never paste credentials into commands, prompts or result files.

```sh
python -m teobench.medium_pi_smoke --transport routing.json --output local-runs/medium-preflight --preflight-all
python -m teobench.medium_pi_smoke --transport routing.json --output local-runs/medium-smoke --model gpt-6-luna --effort high
```

The default engine is Podman; `--engine docker` supports an existing Docker
engine. `--connection NAME` explicitly selects a Podman connection without
changing the default. `--image IMAGE` must already exist locally; the smoke
resolves and uses its immutable local image ID. The smoke image must provide
Python 3, a POSIX shell and `timeout`. Windows/Linux execution of this new
scaffold still requires live acceptance; it is not established by CLI support.

This branch provides the frozen selection, integrity checks and an experimental
clean Pi/container smoke; **it does not yet provide the five complete task
execution adapters or their acceptance**.

## Explicit Pi installation on Windows

When the user has authorized installing Pi, run the helper from an ordinary
PowerShell terminal using the machine's normal script policy:

```powershell
.\scripts\setup_pi_windows.ps1
py -3 -c "from teobench.pi_runner import package_path; print(package_path())"
```

The helper reuses Node.js 22.19+ and npm, installs Pi 0.85.1 into the current
user's npm prefix, skips lifecycle scripts and verifies that Pi starts. It does
not sign in, copy credentials, alter a personal Pi profile or change execution
policy, Docker, firewall or networking. A different existing Pi version is
preserved unless replacement is explicitly requested. Native npm warnings are
logged separately instead of being treated as failed installation by
PowerShell 5. If local policy blocks scripts, follow the host's normal approval
process; the helper does not disable that policy.
