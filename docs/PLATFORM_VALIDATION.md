# Platform validation — 2026-11-04

This is a harness compatibility check and an explicitly requested two-task model smoke test, **not a new full campaign**. The frozen task/reference bytes and scoring rules are unchanged.

| Environment | Validation | Result |
|---|---|---|
| macOS, system Python 3.9.6, sandbox-exec | complete unittest suite | 41 tests, PASS; 1 Linux-only test skipped |
| Windows 10 x64, native Python 3.13.7, Docker 29.2.1 Linux engine | `doctor --prepare`, complete unittest suite, UTF-8 with `PYTHONUTF8=0` | PASS; 41 tests, 2 POSIX-specific tests skipped |
| Ubuntu under WSL, system Python 3.14.4, Bubblewrap | `doctor`, complete unittest suite | PASS; 41 tests, no skips |
| Historical published study | regrade/aggregate using the current macOS backend | PASS; all 1050 recorded results, 35 statistical groups retained |

The complete suite includes all 30 reference solutions (300 Python cases and 72 SQLite fixtures), wrong/empty answers, filesystem/network boundaries, code restrictions/timeouts, tool receipts, report validation and the full-campaign submission gate. Tests use synthetic fixtures where indicated; they do not call models.

## Two real smoke trials

The Windows job requested only the public R01 and C04 tasks in independent trials. Requests went through the existing **OmniRoute on the Mac** via the existing SSH job's stdin/stdout; no listener, forwarding, tunnel or credential copy was introduced. The Windows job received answers, graded them with its native CLI/Docker backend, saved a local two-record checkpoint, and revalidated it.

Requested route: `codex/gpt-5.6-terra-high` (recorded condition `gpt-5.6-terra`, effort `high`). HTTP responses identified the model as `gpt-5.6-terra-high`; provider identity remains self-reported rather than independently attested.

| Task | HTTP | Semantic/strict | Cases passed |
|---|---:|---|---:|
| R01 | 200 | PASS / PASS | 1/1 |
| C04 | 200 | PASS / PASS | 50/50 |

Exactly **two** model requests, no transport failures. The checkpoint has 2 records, zero complete 30-task conditions and `campaign_complete=false`. It was not submitted to community statistics. A standalone Windows inference route was not exercised: the configured Windows Codex catalog exposed the seven required models/efforts, but model inference for this smoke used the Mac gateway.

## Defects reproduced and addressed

- Windows previously failed all six Python tasks because it attempted to use the macOS-only sandbox. It now selects an isolated Linux Docker worker while the CLI stays native Windows.
- Windows SSH could not unlock Docker's credential helper when pulling the public image. Preparation now uses an ephemeral anonymous registry entry against the same local named-pipe engine when that exact credential failure occurs. User configuration and credentials stay intact.
- Report/answer/CLI encoding is explicit UTF-8, including BOM input compatibility; generated report bytes use LF.
- Platform path mocks were adjusted for Windows; actual Linux confinement was tested separately in WSL.
- Updating OS execution changes the grader digest. Historical report metadata remains intact and readable, revalidation identifies the current grader, unknown hashes are rejected, and appending current trials to an old grader checkpoint is blocked.

Linux support incorporates contributor [PR #3](https://github.com/teo-nex/TeoBench/pull/3). Host SSH, NetBird, firewall and security policy were not changed. The hosted Windows CI job checks the native control plane and container command/cleanup policy; full Linux-container integration was verified on the Windows development host, rather than claimed for a Windows-only hosted Docker engine.
