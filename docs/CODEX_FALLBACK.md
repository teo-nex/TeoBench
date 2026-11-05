# Disposable Codex fallback

If compatible Pi/Node is unavailable, reuse **native Codex CLI 0.166.0** already
installed by the participant. Do not install another client or reuse the
orchestrator's conversation. `study create --execution-profile auto` selects
Pi first, then Codex, and returns the selected `trial_command`. Explicit
`--execution-profile codex-clean-v1` is also supported. Keep one adapter and
authentication/transport route throughout a checkpoint; switching requires a
separate study.

On Windows replace `python3` with `py -3` and use PowerShell line syntax. The
adapter resolves standard installed npm Windows shims to native `codex.exe`
without running a shell. For other layouts pass `--codex-bin PATH` with the
existing native executable. Unsupported versions are `BLOCKED`, never silently
treated as this pinned profile.

## Temporary profile and cleanup

Every task gets a new private temporary `HOME`, `USERPROFILE`, `CODEX_HOME`, XDG
and Windows application-data directories, an empty workspace, fixed configuration
and client model catalog, and an ephemeral app-server thread. No personal config,
AGENTS.md, skills, plugins, hooks, MCP servers, memories, prior sessions or extra
tools are imported. The fixed prompt and unchanged public task are the model's
input. Only T tasks receive the trusted `lookup` tool; references remain in the
executor. Exact model and effort selection and the effective configuration are
checked before a turn starts. A client catalog declaration is not proof of
backend access, provider weights or honored effort.

Temporary profile/workspace files are removed after success, model failure,
timeout or handled Ctrl+C, before the command returns. Answers, tool receipts,
trial receipts and the study checkpoint remain in the requested output paths.
The participant's original settings and credential file are not modified.
An OS crash, power loss or uncatchable process kill can leave an orphaned
`teobench-codex-*` temporary directory; cleanup cannot be guaranteed in those cases.
This isolates model context, not untrusted native software. Python/SQL answer
grading still requires the existing OS sandbox and a passing `doctor`.

The [profile](../Easy-Bench/profiles/codex-clean-v1.json) and adapter source are
fingerprinted in the report. Codex uses its **native output limit**, whereas Pi
uses a fixed 16,384-token cap; these are separate experimental cohorts and must
not be pooled. Neither a score difference between adapters nor clean-versus-old
reports alone establishes account A/B testing. The total trial deadline is 240
seconds, automatic request/stream retries are disabled, and request starts are
separated by at least four seconds. With `--study`, the checkpoint lock serializes
trials and the initial wait also separates successive trials. Use one checkpoint
for one campaign.

## Existing sign-in, no implicit API billing

The default is `--auth-mode chatgpt`, using the participant's existing file-based
Codex ChatGPT sign-in (`CODEX_HOME/auth.json`, normally `~/.codex/auth.json`).
`--auth-file PATH` selects an existing file explicitly. Only selected access,
ID and account fields enter the temporary private credential file. The original
refresh token is never copied and no automated refresh is attempted. Credentials
do not enter the task, CLI arguments, receipts or public report.

The existing access token must remain valid for at least the trial deadline plus
60 seconds. If expired, near expiry, opaque, absent or available only in an OS
keyring, report `BLOCKED` and ask the participant to refresh/sign in through their
normal Codex installation or select an existing supported auth file. Never ask
for a password or token in chat. A long campaign can pause at token expiry;
resume missing slots after normal sign-in refresh. TeoBench does not rotate the
participant's original credentials. Account quota and all seven exact models
must still be available; a subscription does not guarantee either.

API-key usage requires explicitly selecting `--auth-mode api-key` and the user's
authorization for that usage. It reads an existing `OPENAI_API_KEY` from the
environment or selected auth file. An API key in the environment never causes
automatic fallback from ChatGPT to API billing.

## Preflight and full campaign

Run the OS-specific `doctor` and `verify` first. Check all 35 exact model/effort
conditions using a fresh output directory per check. Example, with zero model
inference:

```bash
python3 -m teobench codex-trial --preflight \
  --task R01 --model gpt-6-luna --effort high \
  --output local-runs/preflight-codex-luna6-high
```

`PREFLIGHT_PASS` verifies local isolation and selection, not a successful model
completion, remaining quota or backend support. Actual model failures are
recorded separately from wrong answers. Never substitute unavailable models or
translate `xhigh`/`max` into another effort.

```bash
python3 -m teobench study create --id my-clean-codex-study \
  --file local-runs/study.json --execution-profile auto \
  --access-route 'existing participant sign-in' --environment 'OS and architecture'
python3 -m teobench campaign next --file local-runs/study.json
```

If creation returned `codex-clean-v1` / `codex-trial`, execute each exact next
slot with that command. The first slot is:

```bash
python3 -m teobench codex-trial --study local-runs/study.json \
  --task R01 --model gpt-5.6-luna --effort high --replicate 1 \
  --output local-runs/trial-0001
```

Repeat `campaign next` and the selected adapter through **1127 original
attempts**: 35 pilot, 1050 primary and 42 control. Existing output paths and recorded slots
cannot be overwritten. The adapter saves the original receipt before grading;
recover it with `study record` after a grader/persistence interruption instead of
requesting a replacement answer. Follow [RUN_FULL_STUDY.md](RUN_FULL_STUDY.md)
for coverage, validation and consent before publication. A standalone trial or
preflight is not a completed study.

## Explicit Responses gateways

In explicitly authorized API-key mode only, `--transport PATH` accepts a routing
file containing exactly `{"base_url":"https://gateway.example/v1"}`. Headers,
commands, credentials, query parameters, personal configuration and generation
overrides are rejected. ChatGPT tokens are never forwarded to an arbitrary
gateway. The route fingerprint is fixed for the checkpoint; the endpoint/key
is not published. A declared gateway does not independently attest model identity.

## Offline verification and upstream references

`python3 -m unittest discover -s tests -p test_codex_runner.py -v` runs policy
checks without installing anything. If the pinned native Codex is installed, it
also checks real app-server request construction against a synthetic localhost
Responses server: all 35 preflights, exact effort, no personal context, trusted
lookup calls, failure/interruption cleanup and preserved output. No real model
or paid API is called. Otherwise the installed-client checks explicitly skip.

The implementation uses the supported [Codex app-server protocol](https://learn.chatgpt.com/docs/app-server#start-or-resume-a-thread)
and [configuration schema](https://developers.openai.com/codex/config-schema.json).
A normal [named CLI profile](https://learn.chatgpt.com/docs/developer-commands#codex-exec)
layers onto user settings; it is insufficient isolation on its own. Windows
native executable locations follow the [official launcher](https://github.com/openai/codex/blob/main/codex-cli/bin/codex.js).
