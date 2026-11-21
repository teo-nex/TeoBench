# Objective Workbench v3 (extension)

A small, separately scored companion to Easy-Bench, contributed from an external
router-evaluation campaign. It is **not** part of the frozen Easy-Bench dataset,
campaign profile, statistics or study submission path; nothing in `teobench/`
imports it.

10 templates × 3 fixed seed variants (11, 29, 47) = 30 instances. Seed variants
of one template are correlated and are not independent tasks (S01 is identical
across seeds). Grading is deterministic, standard-library Python, no LLM judge.

| ID | Track | What is checked |
|---|---|---|
| Q01 | answer | failed events, ordered unique request IDs, types |
| Q02 | answer | invoice lines with HALF_EVEN rounding, total, currency |
| Q03 | answer | new confirmed quotes: ID, source, literal text, no duplicates/fakes |
| Q04 | answer | applicable revision of a long document; explicit `null` for unknown |
| Q05 | answer | supported part of a form with sources; explicit gaps |
| Q06 | answer | events joined by ID, aware timestamps in UTC, order, codes |
| S01 | artifact | change exactly one INI line; all other bytes and file set unchanged |
| S02 | artifact | run a provided SQLite importer; rows, relations, schema, unchanged inputs |
| S03 | artifact | tar exactly the manifest files, delete only them; no extra/unsafe members |
| S04 | artifact | CSV→JSON regional report: exact sums, unmatched IDs, unchanged inputs |

Answer tasks require one strict JSON object (duplicate keys, NaN/Infinity,
extra/missing fields and wrong types fail; key order and whitespace do not).
Artifact tasks are graded on the final workspace state only. A grader cannot
prove process claims such as "ran the importer twice" or "archived before
deleting"; the prompts say so explicitly.

## Usage

```sh
cd Extensions/objective-workbench-v3
python3 -m unittest discover -s tests -v
python3 cli.py export --seed 11 --out /absolute/unused/package
python3 cli.py reference Q02 --seed 11 --out /absolute/unused/answer.json
python3 cli.py grade Q02 --seed 11 --submission /absolute/answer.json
python3 validate.py   # tests + export + reference + grade for all 30 instances
```

`export` writes `public/<ID>` (prompt, contract, inputs or initial workspace)
and `private/` (full cards with expected results). Give a candidate only its
own `public/<ID>`. These are development materials, not a sealed holdout.
`grade` exits 0 = pass, 1 = fail, 2 = CLI usage error.

## Security boundary

The graders never execute submitted code, open SQLite read-only, do not extract
tar members to disk, and reject symlinks, special nodes and inputs over 2 MB.
This is **not** a security sandbox: in the original campaign both the model's
`python` tool and artifact grading of model-produced files ran inside a
separate no-network bubblewrap executor with CPU/memory/file limits. Do the
same before grading untrusted workspaces.

## Limits

One author wrote generators, references and graders; independent references
and 50 unit/mutant tests reduce but do not remove shared-author error. The
templates are deliberately formal (sources/IDs/values) and do not measure
free-form writing quality. Results from one campaign are in
`Easy-Bench/external-runs/private-gateway-20261115/` (separate PR).

## Русский

Отдельное дополнение к Easy-Bench: 10 шаблонов × 3 связанных seed-варианта,
детерминированная проверка без LLM-судьи. Не входит в замороженный набор,
профиль кампании и статистику. Для артефактных задач проверяется только
конечное состояние; проверка не является sandbox — непроверенные рабочие
папки оценивайте в изолированном исполнителе.
