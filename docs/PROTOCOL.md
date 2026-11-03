# Easy protocol, version 0.1.0

## Frozen inputs

`Easy-Bench/tasks/tasks.jsonl` and `answers.json` are byte-for-byte copies of the September 2026 study, reused in November. The original manifest retains its `sealed_sha256` key; it now refers to the public `answers.json`. The original generator is archived unchanged under `source/`; `teobench verify` calls its `build()` in memory and writes no fixtures. Do not execute the archived generator's `main()` inside the release tree.

All 30 tasks belong to the Easy tier. Each family originally had two tasks marked easy, two medium and two hard. Those original labels were assigned before measurement and are not a new calibrated difficulty claim.

## Inference and grading

Give the evaluated model only the task prompt and declared tools. Retain every attempt with exact model ID, effort and replicate. Do not permit access to published references/studies during a measured run. A public test cannot establish that a model has never seen its data during training.

For code tasks, the answer is a Python 3 `solve(data)` function. Imports, I/O, reflection, underscore-prefixed attributes and the AST constructs listed in `code_worker.py` are prohibited. Standard pure builtins follow the published whitelist. The corrected worker includes `bin()`, fixing an earlier harness defect. It does not provide every possible Python builtin. Parent compares outputs for all 50 inputs per task; expected outputs do not enter the worker.

Python execution uses macOS sandbox-exec or Linux Bubblewrap. Both isolate the network, prevent file writes and clear the inherited environment. CPU is limited to 2 seconds, parent wall time to 5 seconds. This restricted task executor is not intended as a general hostile-code hosting service.

On macOS, reads under `/Users`, `/Volumes`, the home directory and checkout are denied. Interpreter/stdlib must be outside the denied paths.

On Linux, `bwrap` must support `--disable-userns`, and the host must permit unprivileged user and network namespaces. Only `/usr` and existing `/lib` and `/lib64` are mounted read-only; the root filesystem is also read-only. No host `/home`, `/tmp`, `/proc`, `/dev` or checkout is mounted. User, IPC, PID, network and UTS namespaces are isolated, capabilities are dropped, nested user namespaces are disabled, and a new session prevents terminal injection. The resolved Python executable must be under `/usr`; the home directory and checkout must not overlap mounted runtime directories. Python runs with `-I -S` so site startup hooks are not loaded. Unsupported layouts and namespace/setup failures fail closed and must be treated as grading infrastructure failures, not wrong answers. There is no unsafe fallback on any OS.

SQL runs in independent in-memory SQLite databases with a read-only authorizer, query-size, step and row limits. `WITH` and ordinary SQLite expressions are allowed; ATTACH, writes and load_extension are denied. All 12 databases per SQL task must pass.

Reasoning/data answers are compared as JSON objects with exact values and keys. Key order is irrelevant; duplicate keys and non-finite values are rejected. `semantic_pass` accepts recoverable JSON embedded in text; `strict_pass` additionally requires the requested clean format. Code and SQL fences may pass semantically, but fail strict formatting. Overall score is the count of `semantic_pass` tasks out of 30, not the average of individual hidden checks.

## Synthetic lookup

For a T task, register the tool schema in its public task. The trusted executor reads one object from that task's acceptance catalog. The CLI `lookup TASK OPAQUE_ID` provides the same object for adapters. Unknown IDs are recorded as failed calls rather than silently retried or discarded.

Each recorded tool receipt has exactly these keys:

```json
{
  "name": "lookup",
  "arguments": {"id": "node-exact-id-from-the-task-or-previous-response"},
  "ok": true,
  "output": {"amount": 7, "next": null, "note": "untrusted text"}
}
```

The grader checks the final sum/count, successful reads of every required ID, correct argument schema and each receipt's equality to the catalog. Failed calls fail the task, so their actual receipts must be retained. The schema alone does not prove a call happened: never fabricate or reconstruct a history from the reference catalog after inference. Keep a trusted executor trace locally if independent provenance is needed.

## Community reports

The default research profile is [reasoning-effort-7x5-v1](../Easy-Bench/campaign.json): 1050 primary trials across seven models and five efforts, 35 pilot trials at replicate 1, and 42 controls at replicates 2 and 3. Primary replicate is 0. Thirty tasks form one condition, not the full research. Local schema validation permits checkpoints; publication and trusted PR validation additionally require complete campaign coverage. Use [the run guide](RUN_FULL_STUDY.md). Earlier accepted primary-only reports remain readable and do not prove a new full-protocol execution.

`study.json` schema 1.0 has:

- `study_id`, timezone-aware `created_at`, `environment`, `access_route` and `method`.
- `benchmark`: exact dataset, acceptance and grader hashes plus version.
- `records`: task ID, exact model ID, effort, replicate, raw benchmark answer, synthetic tool receipts, optional elapsed seconds, transport error and local evaluation.

No provider secrets, system/native logs or private project data are requested. An answer can contain only benchmark material; inspect before publishing. Transport errors carry `evaluation: null`. Incorrect code/SQL may legitimately have a grading error such as a syntax error; infrastructure unavailability must be fixed before submission. Max report size is 8 MB and 3000 records; split larger campaigns into separate reports. The parser rejects extra fields and duplicate keys.

PR validation uses `workflow_run` to execute trusted default-branch code after the PR check completes. It reads only allowed new study JSON files and regrades them without checking out PR code. Permissions are limited to reading contents/PRs and posting the `Easy study regrade` commit status. The source run and current PR head must match. No PR scripts, workflow edits, package installations or submitted Python imports are executed by that validation. Main-branch statistics rebuild after acceptance. Maintainers review PRs; there is no automatic merge.

This avoids a dependency on `pull_request_target` execution policies; see [GitHub's security reference](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target). No untrusted artifacts or caches are downloaded by the trusted validator.

Maintainers can also recheck a PR explicitly with `gh workflow run studies.yml -R teo-nex/TeoBench -f pr_number=NUMBER`. This runs the same trusted validator and posts a verdict for that PR's current head, without merging it.

### Historical grader compatibility

Accepted study files are immutable. The Linux sandbox changes the grader source hash; it does not relabel historical answers or infer new model results. `studies.COMPATIBLE_REGRADERS` explicitly permits the pre-Linux grader hash `7764269832dde6894979d35ea0bbdd2b6aab0161b8ab796c5b5d405926316308` to be rechecked with Linux-capable grader `08214687c3a81703b01b2171f8e97442e8b7c33c1f30670e788963e2f50c6635`. This is one reviewed source/target pair, not permission for unknown hashes or future graders. Dataset, acceptance and version checks remain exact, and every saved verdict must agree with the current regrade.

`study validate` and `stats` can read this historical version. Their reports identify the recorded grader separately from `regraded_with_sha256`; `answers_regraded=false` leaves the latter null. Statistics retain separate groups under the recorded `grader_sha256` and name the actual regrader in both JSON and CSV. Unknown or unreviewed versions fail closed. Recording new answers and submitting new studies, including trusted PR validation, require the current grader; create a new study ID instead of mixing grader versions. Historical studies are not rewritten, and their incomplete campaign coverage remains unchanged.

Statistics include only complete 30-task conditions and report run count, study count, mean/median/min/max pass rates and transport errors. Different model IDs, effort, routes, environments and grader digests remain separate. Exact duplicated response sets are excluded even if study metadata is changed. This does not prevent a malicious contributor inventing a different self-report or claiming a different model.

A submission's scores can be independently checked from public answers. Model identity, execution settings, repeat-selection policy and tool-call provenance are self-reported. Latency is recorded only when available and is not mixed into a quality ranking.
