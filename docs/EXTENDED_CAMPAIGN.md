# Opt-in Codex eight-model campaign (schema 1.1)

The default seven-model profile and schema 1.0 remain unchanged. Use the explicit
`codex-available-8x-v1` profile only for a study of the fixed November 4, 2026 Codex
snapshot: the original seven models plus `gpt-6-sol`, with `ultra` on all except
`gpt-6-luna` and `gpt-5.6-luna`. This is not a claim that an account has access to
these routes. Check actual model/effort access and the OS sandbox before inference.

```sh
python3 -m teobench campaign plan --profile codex-available-8x-v1
python3 -m teobench study create --id my-eight-model-study --file local-runs/study.json \
  --campaign-profile codex-available-8x-v1 \
  --access-route 'configured model interface, no credentials' \
  --environment 'OS/runtime and sandbox, no private paths'
```

The profile requires **1380 primary + 40 pilot + 48 control = 1468 slots**.
There are 46 primary model/effort conditions, each containing all 30 tasks.
Completion, preview, publication and trusted PR regrading use the same fixed
profile. Missing slots, substituted models and unexpected results still fail.
Profile names are allowlisted; a report cannot point at a custom configuration.
Changing the declared profile does not generate observations or make missing
model access available.

Schema 1.1 adds `campaign_profile` and `additional_attempts` to the study object:

- `records` contains the controlled observations, including the **first** failed
  response or timeout. Its identities and scores define coverage and statistics.
- `additional_attempts` retains non-scoring retries without replacing a first
  failure. Each entry has the ordinary record fields plus a positive `attempt`
  number and a timezone-aware `started_at`. It must reference an existing
  controlled identity. Retries are validated and regraded but never count toward
  campaign coverage, complete runs or primary scores. The existing 3000-record
  limit applies to controlled and additional observations together.

Record a retry with the same controlled identity and `--attempt 1 --started-at
2026-11-04T00:00:00+00:00` (using its actual start time). Keep `--replicate`
unchanged: attempt numbers do not replace the pilot/control replicate numbers.
The controlled observation must already exist; retry numbers must be contiguous.

Failed `lookup` receipts (`ok: false`) may preserve an original argument object
with missing, extra or mistyped fields. They still fail the unmodified grader.
Successful receipts retain the strict single-string-`id` schema. A schema 1.1
trace can retain up to 256 actual calls, with at most 100 successful receipts,
so a failing model's long trace is not silently truncated. The 8 MB report limit,
secret checks, frozen inputs, grader hashes and trusted sandbox are unchanged.
These storage bounds do not increase an evaluated model's tool budget.

Retain every actual attempt; never invent an ID, drop a failed call, replace a
timeout with a later answer, or import an old response as fresh inference.
Model identity and tool provenance remain submitter-reported. Keep study data
and source/schema changes in separate pull requests; publication needs the
participant's consent and does not merge a PR automatically.
