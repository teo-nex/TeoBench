# Clean inference profiles

The user's current agent is the **orchestrator**, not the test subject. Its personal
instructions must never be passed to the evaluated model. A fresh conversation
alone does not remove global configuration, skills, extensions or context files.

New standardized studies use **`pi-clean-v1`**, an optional Pi SDK adapter. Offline
grading, accepted studies and the frozen tasks remain unchanged. Historical
studies retain their original methods; they are not retroactively certified clean.

## Requirements and boundary

Reuse Node.js and **Pi 0.85.1** already installed by the participant. The adapter
never installs packages, changes networking/security settings, or creates model
access. If unavailable, report `BLOCKED`; do not silently use the current agent.
Pi is a separately installed, trusted dependency, not bundled with TeoBench.
On Windows pass `--pi-package` with the installed package directory if automatic
resolution cannot locate it. Use `py -3` instead of `python3` for the commands below.
The launcher uses Python/Node subprocess APIs, not a Unix shell.

Each trial has:

- a new private temporary working directory and Pi resource directory;
- in-memory settings and session, with no previous conversation;
- no discovery of extensions, skills, prompt templates, themes, AGENTS.md,
  CLAUDE.md, SYSTEM.md, APPEND_SYSTEM.md or personal package settings;
- a fixed [profile](../Easy-Bench/profiles/pi-clean-v1.json), system prompt,
  16,384 output-token cap, no automatic retry or compaction;
- only the unchanged public task and, for T tasks, the declared `lookup` tool;
- exact provider/model selection and an effort check before inference;
- checks immediately before dispatch for prompt, tools, model and effort;
- removal of Pi's generated local working-directory suffix before dispatch;
- a 240-second total subprocess deadline, including all tool rounds;
- a four-second request-start gap within the trial. With `--study`, a checkpoint
  lock serializes trials; the initial four-second wait also separates successive
  trial requests. Run one study, not independent checkpoints, for one campaign.

This controls the evaluated model's context, not the operating system or an
untrusted Pi installation. Pi code remains trusted host software. Python-answer
execution still uses the separate existing grader sandbox. Library labels and
requested settings do not attest the provider's actual weights or experiment.

Only selected provider authentication is reused. API keys are held in a private
temporary credential file; unrelated environment secrets and Node startup hooks
are not inherited. For OAuth, Pi uses the existing auth store directly so normal
token refresh does not leave the user's original store with a rotated, stale
refresh token. Normal credential refresh may update that auth file; personal
settings/resources are not copied or changed. No credentials go into the task,
command line, public receipt or study. Private receipts still contain task
answers and lookup data; review them before sharing.

## Preflight: no model inference

First run the normal OS-specific `doctor` and `verify`. Then check **all 35 exact
model/effort conditions**, using a new output directory for each check:

```bash
python3 -m teobench pi-trial --preflight \
  --provider openai-codex --model gpt-6-luna --effort high --task R01 \
  --output local-runs/preflight-luna6-high
```

`PREFLIGHT_PASS` confirms local profile construction and exact client selection,
not a successful model response, remaining quota, provider effort support or
server-side model identity. Never count it as research. Do not rename aliases or
map unsupported efforts. Missing conditions mean `BLOCKED`.

Credentials normally come from the selected provider in Pi's existing auth file.
`--auth-file PATH` can select an existing auth store explicitly. It is never
printed or uploaded. A supported environment API key can be reused for a built-in
provider without passing the key on the command line.

## One campaign, persisted original attempts

Create a **new** checkpoint for this profile; do not resume a historical or
personalized report as a clean study:

```bash
python3 -m teobench study create --id my-clean-pi-study \
  --file local-runs/study.json --execution-profile pi-clean-v1 \
  --access-route 'Pi openai-codex' --environment 'OS and architecture; Node version'
python3 -m teobench campaign next --file local-runs/study.json
```

For **the exact next slot** returned above (the initial slot is R01, Luna 5.6,
high, pilot replicate 1), execute:

```bash
python3 -m teobench pi-trial --study local-runs/study.json \
  --provider openai-codex --task R01 --model gpt-5.6-luna \
  --effort high --replicate 1 --output local-runs/trial-0001
```

Repeat `campaign next` and `pi-trial` through all **1127 slots**. The orchestrator
must actually invoke these commands, not solve the tasks itself. `--study` checks
phase/order and duplicates, locks the checkpoint for the whole trial, saves the
original receipt before grading, and records completed answers or transport
failures. Preflight blockers do not become wrong answers. A completed wrong answer
still counts as the original attempt. No retries/best-of replacement are added.

An existing output directory is never overwritten. If grading/persistence fails
after a response, recover that saved `receipt.json` using `study record`; never
make another model request for that slot. User interruption leaves any already
written receipt for recovery. Inspect existing trial outputs before resuming.

Without `--study`, the command produces a standalone trial artifact only. The
caller then owns campaign ordering and inter-trial scheduling. It is not a full
campaign and is not automatically submitted.

The study's route and method contain the execution-profile fingerprint. The first
trial also binds the provider and explicit transport fingerprint; changes are
rejected before another request. Existing statistics group these cohorts
separately. The new output cap/prompt/client are experimental conditions, so a
historical-versus-clean difference alone cannot establish account A/B testing.
After completion, use normal validation, preview and consent before publication.
No schema, old report or old score is rewritten by this feature.

## Explicit compatible gateways

Personal `models.json` is intentionally not imported. If exact model IDs are
exposed through a compatible gateway, provide a **routing-only** JSON file with
`--transport PATH` on every preflight/trial:

```json
{
  "base_url": "https://gateway.example/v1",
  "api": "openai-completions",
  "models": ["gpt-5.6-luna", "gpt-6-luna", "gpt-5.6-terra", "gpt-6.1-terra", "gpt-5.6-sol", "gpt-6.1-sol", "gpt-6-astra"]
}
```

Only `base_url`, `api` (`openai-completions` or `openai-responses`) and exact
campaign model IDs are accepted. Credentials, headers, commands, compatibility
settings, prompt and generation overrides are rejected. Use a matching existing
Pi auth-store provider entry. The transport hash is in private receipts and the
study's route binding; publishing a hash does not publish the endpoint or key.
A gateway remains an explicit research condition, not independent attestation.

## Codex and other adapters

A normal Codex `--profile` layers onto user settings; it does not create a clean
user home. `--ignore-user-config` skips its config file while authentication still
uses `CODEX_HOME`. Neither switch by itself demonstrates a fixed evaluated-model
context. See [official Codex CLI documentation](https://learn.chatgpt.com/docs/developer-commands#codex-exec).

A future Codex adapter must verify equivalent isolation, tools, model/effort and
request context, record its own fingerprint, and form a separate cohort. Do not
label a normal Codex/OpenCode session `pi-clean-v1`. The supported standardized
adapter in this change is Pi; other existing reports remain readable as declared.

## Offline verification

`python3 -m unittest discover -s tests -p test_pi_runner.py -v` tests profile,
credential selection, route binding, checkpoint recording and replay rejection.
If the pinned Pi SDK is already installed, it also runs against a **local synthetic
HTTP server**: no real model or paid API is called. Otherwise those optional
integration checks are explicitly skipped; policy tests still run on every OS.
