# TeoBench Medium — public 100-task selection (preparation)

**The full Medium campaign is not yet runnable or runtime-accepted. No Medium
model results exist in this branch.** The clean Pi/container client has passed
Windows acceptance. Four evaluator adapters have passed representative oracle /
no-op / corrupt-artifact checks; SWE-bench Verified is blocked on disk capacity.
Easy's `RUN_TEO_BENCH`
command still runs Easy; it does not run this set.

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
Python 3, a POSIX shell and `timeout`. The scaffold was exercised on Windows
with Docker's Linux engine and Pi 0.85.1: 38 automated tests, all 35 model/effort
selections without inference, and a real tool/file-write smoke using a scripted
localhost provider. The latter is **not a model response or benchmark score**.
See the [sanitized Windows acceptance record](validation/windows-client-4525d14.json).
All seven exact models also passed a separate live Windows Pi/container smoke
at `high` through a local OmniRoute gateway. See the
[gateway acceptance record](validation/windows-gateway-20261105.json).
This does not establish live access at the other four effort levels or provide
any scores for the selected tasks. These are historical v1 client checks; the
current v2 checks and remaining gates are listed below. Linux execution of
this new scaffold is not established by these Windows checks.

Transport failures retain fixed diagnostic categories, including session-limit,
quota, authentication and model-access errors, without saving raw provider error
messages. An OmniRoute API key's `maxSessions` counts registered conversations;
it is not the scheduler's concurrent-request limit. A cap of four blocked the
fifth fresh Pi session during acceptance. Use a separate admission limit for
parallel requests; do not weaken model or connection restrictions to fix it.
All initial infrastructure failures remain separate from benchmark observations.

This branch now includes experimental adapters for all five sources and a durable
3500-slot controller. **Adapter code is not full runtime acceptance.** See
[the runtime acceptance record](validation/windows-runtime-20261105.json).

## Experimental v2 runtime and campaign

`pi-medium-sandbox-v2` adds a container-only `inspect_image` tool. Personal Pi
configuration, skills, extensions, context files and model credentials are not
mounted in task containers. Every model/effort is selected explicitly. A
scripted localhost provider has exercised terminal and image tools on Windows;
all 35 selections have passed preflight without model inference. This is not
live acceptance of all 35 provider routes.

The new controller is separate from Easy and the historical v1 smoke:

```sh
python scripts/prepare_medium_runtime.py --output local-runs/medium/runtime-assets
python scripts/prepare_medium_databases.py --output local-runs/medium/databases --docker docker
python -m teobench.medium_campaign check --config local-runs/medium/config.json
python -m teobench.medium_campaign prepare-metadata --config local-runs/medium/config.json
python -m teobench.medium_campaign accept --config local-runs/medium/config.json --source bird --task 18
python -m teobench.medium_campaign run --config local-runs/medium/config.json
```

These commands require the preparation cache, installed Pi 0.85.1, Node,
`pyarrow==26.0.1`, `swebench==4.1.0` and an existing Linux amd64 Docker engine.
The database command downloads a pinned public data image, creates a stopped
container and extracts only exact selected database paths. It never runs that
image. Mini-Dev's toxicology override must take precedence over the same-named
dev database; selection by basename is invalid.

Copy [runtime.example.json](runtime.example.json) to a private `local-runs`
directory and fill its paths and immutable local image IDs. Build the
[spreadsheet environment](environments/spreadsheet/Dockerfile) only within the
user's authorized setup. Record the actual resulting image ID. LibreOffice
preparation uses the upstream UNO functions and verifies that both workbooks
were replaced; a zero exit code or valid XLSX alone is insufficient. Historical
spreadsheet preparation without these write receipts must use a new directory.

`check` and `run` fail closed on missing source acceptance, spreadsheet
recalculation, BIRD gold/database compatibility, current Pi fixture/preflight,
unpinned task images or insufficient host space. All source acceptance records
must show oracle=1, no-op=0, corrupt=0 and zero model requests. The full run has
**not yet passed end-to-end acceptance**; do not advertise it as ready.

The controller currently runs one trial at a time with a minimum four-second
request gap. It records first attempts in SQLite/WAL, freezes source/profile/
image/input hashes and resumes saved artifacts without rerunning inference.
Interrupted dispatched attempts block for receipt review. A transport failure
stops the controller and stays separate from a wrong answer. No automatic
submission, retries for score improvement or model substitution is enabled.

A trusted launcher supplies `TEOBENCH_GATEWAY_KEY` in process memory. The
subscription quota guard reads existing native authentication without changing
it, checks every request and pauses at 70% usage. Unknown quota or identity
changes block requests; credits never override the gate. This local reserve
policy is not a provider-side billing lock. Restrict the gateway to the seven
exact subscription routes and one authorized connection, with fallback disabled.

Image pulls and active Pi execution check a 12 GiB host-space reserve. This is a
best-effort stop, not a hard filesystem quota or a guarantee that compressed
images fit after unpacking. Docker Desktop's guest-space reclamation may not
immediately return space to Windows. The current PC1 run is blocked on host
capacity and Verified runtime acceptance; **zero of 3500 primary attempts have
started**. Linux and macOS acceptance of this v2 controller remains pending.

## Explicit Pi installation on Windows

When the user has authorized installing Pi, run the Python helper from an
ordinary terminal. It does not depend on PowerShell `.ps1` execution permission:

```powershell
py -3 -m teobench.setup_pi --install
py -3 -c "from teobench.pi_runner import package_path; print(package_path())"
```

Without `--install`, the command only checks an existing installation. The
helper reuses Node.js 22.19+ and npm, installs Pi 0.85.1 into the current
user's npm prefix, skips lifecycle scripts and verifies that Pi starts. It does
not sign in, copy credentials, alter a personal Pi profile or change execution
policy, Docker, firewall or networking. A different existing Pi version is
preserved unless replacement is explicitly requested. Native npm warnings are
logged separately instead of being treated as failed installation by
PowerShell 5. It invokes npm's JavaScript entry point directly using native
Node, without invoking `.cmd`/`.ps1` wrappers or disabling script policy.

With an existing image that provides Python 3, `sh` and `timeout`, validate the
client without model access or quota usage:

```powershell
py -3 scripts/check_medium_pi_container.py --engine docker --image YOUR_EXISTING_IMAGE --output local-runs/pi-preflight --preflight-all
py -3 scripts/check_medium_pi_container.py --engine docker --image YOUR_EXISTING_IMAGE --output local-runs/pi-scripted-smoke
```

Use a new output directory each time to preserve earlier receipts. These
commands do not pull images, install an engine, run any of the 100 tasks or
establish subscription quota. Model routing must be explicitly configured for
the authorized gateway; do not fall back to another account, model or paid API
when it is unreachable. A host loopback URL refers to the machine running Pi,
so copying a routing file from another computer does not make its gateway
reachable.
