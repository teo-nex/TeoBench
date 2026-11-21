# External run: six models absent from Easy-Bench statistics (2026-11-15)

**Not a `studies/*/study.json` submission and not included in the regraded
community statistics.** The run used a custom direct-API agent loop, not
`responses-clean-v1`, Pi or Codex, and a different model matrix than any
allowlisted campaign profile. It is published as raw evidence alongside the
benchmark, in the same spirit as an archived report, but with every answer
retained.

The TeoBench block contains only models that have no rows in
`Easy-Bench/statistics/summary.csv` at `a62d4eb`: Claude Haiku/Opus/Sonnet 5.5,
GLM 5.3 Flash and two Nemotron models. GPT conditions from the same run are
omitted because they are already covered by accepted studies.

## TeoBench Easy — first attempt per slot

30 frozen tasks × 3 repeats per model/effort. Each cell is **passes / 90
slots**; the denominator includes requests that did not complete.

| Model | low | medium | high | xhigh | max | Semantic total | Strict total | Not completed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| claude-opus-5-5 | 88 | 90 | 88 | 90 | 85 | 441/450 | 320/450 | 0 |
| claude-sonnet-5-5 | 83 | 85 | 85 | 90 | 86 | 429/450 | 356/450 | 1 |
| claude-haiku-5-5 | 79 | 81 | 90 | 90 | 78 | 418/450 | 391/450 | 2 |
| glm-5.3-flash | 74 | 84 | 83 | — | 81 | 322/360 | 296/360 | 18 |
| nemotron-3.5-super-vl | | | full thinking: 80 | | | 80/90 | 80/90 | 0 |
| nemotron-ultra-free | | | full thinking: 74 | | | 74/90 | 74/90 | 11 |

Semantic = TeoBench `semantic_pass`; strict = `strict_pass` (for Claude the gap
is mostly Markdown fences or prose around otherwise correct answers). GLM
exposes no `xhigh`. Nemotron was run only in its maximum full-thinking mode
(`enable_thinking=true`, no reduced-effort flag); it is not comparable to an
effort scale.

All 1879 completed first-attempt and resend answers were **regraded with this
repository's grader at `a62d4eb`** (`teobench/evaluate.py` sha256
`39e47321…0c5fb3`): 0 mismatches with the stored grades. Python/SQL answers ran
in a no-network bubblewrap executor with CPU/memory/file limits.

`not completed` = HTTP 502, read timeout at 240 s, or an orchestrator
interruption before a response. These are not wrong answers. 21 such slots
were later re-sent once without changing the request; those results are kept
as `attempt: 1` records and in `technical_resend*` columns of `summary.csv`,
but **never replace** the first attempt in the table above.

## Objective Workbench v3 — supplementary block

Same run, all nine models, scored separately with the extension proposed in a
companion PR (`Extensions/objective-workbench-v3`). 10 templates × 3 correlated
seed variants × 3 repeats = 90 slots per model/effort; not independent tasks.
First-attempt passes per model (all efforts pooled):

| Model | Passes |
|---|---:|
| gpt-6.1-terra | 449/450 |
| gpt-6.1-sol | 447/450 |
| gpt-6-luna | 447/450 |
| claude-haiku-5-5 | 421/450 |
| claude-opus-5-5 | 414/450 |
| claude-sonnet-5-5 | 393/450 |
| glm-5.3-flash | 355/360 |
| nemotron-ultra-free | 90/90 |
| nemotron-3.5-super-vl | 89/90 |

All 3240 graded answers/final workspaces were regraded with the frozen source
(hashes in `PROVENANCE.json`): 0 mismatches.

## Files

- `teobench-records.jsonl.gz`, `objective-workbench-records.jsonl.gz` — one
  JSON object per attempt: task, model, effort, replicate (and seed), attempt,
  error, grade, elapsed seconds, final answer text, tool history (lookup
  receipts / python tool stdout), model-call count and summed token usage.
- `objective-workbench-final-files.jsonl.gz` — base64 final workspace files for
  artifact tasks, keyed `model/effort/objective-ID-sSEED-rREP#attempt`.
- `summary.csv` — per block/model/effort counts above.
- `PROVENANCE.json` — commits, dataset/grader hashes, limits, file hashes.

## Conditions and limits

Exact model IDs as requested from a private multi-provider subscription gateway
(OpenAI Chat Completions wire format for GPT/GLM/Nemotron, Anthropic Messages
for Claude; returned model ID checked on every call). Prompt = the public task
text only, no system prompt. Declared `lookup` tool for T tasks, executed
against the frozen catalog. 240 s per request, 18 000 max output tokens per
call, at most 10 model calls per trial, ≥4 s global gap between request
starts, no automatic retries. Requested effort is a wire setting, not an
attestation of provider compute. Model identity is self-reported by the
gateway/provider. Three repeats of the same task are dependent. No credentials,
gateway hostnames or private paths are included; a trusted-executor host path
in tool stdout was replaced with `<sandbox-host>/` (flagged as `redacted`).

## Русский

Сырые результаты внешнего прогона для шести моделей, которых нет в статистике
Easy-Bench: Claude Haiku/Opus/Sonnet 5.5, GLM 5.3 Flash и два Nemotron. В
таблице — только первая попытка; незавершённые запросы входят в знаменатель.
Повторные отправки после технических сбоев сохранены отдельно. Все ответы
перепроверены текущим оценщиком репозитория: расхождений нет. Это не
`study.json` и не входит в общую статистику: адаптер и матрица моделей
отличаются от официального протокола.
