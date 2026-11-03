# Security boundaries

TeoBench evaluates model-generated text. Treat submitted Python, SQL and study
metadata as untrusted input, even when the repository itself is trusted.

The 2026-11-04 source audit found no malware, hidden installer, telemetry,
credential harvesting or automatic upload. This is a source-level finding,
not a guarantee about arbitrary forks, future commits, host software or images.
The repository has no pip/npm dependencies or install hooks. Docker images are
official Python images pinned by digest; grading never pulls an image. Windows
image preparation downloads that one image only when explicitly requested.

## Isolation

- Python and SQL execute in OS sandboxes, with network denied and expected
  answers kept in the parent. SQL has its own bounded worker and SQLite heap.
- Python's restricted builtins and AST checks are defense in depth. Reflective
  generator/coroutine/frame/traceback attributes are prohibited. Do not treat
  Python syntax filtering alone as a secure isolation boundary.
- Linux Bubblewrap exposes only the required system runtime directories.
  Linux Docker uses only the local socket. Windows Docker accepts only a local
  named pipe. macOS Docker accepts only a pinned local Unix socket, rejecting
  TCP/SSH contexts. Containers have no host mounts, network or elevated capabilities.
- Linux Python workers have a 256 MiB address-space limit. Docker also applies
  a 128 MiB (Linux/macOS fallback) or 256 MiB (Windows) container memory limit.
- macOS Seatbelt denies network, writes and protected user/repository reads,
  but **does not impose a hard Python memory limit or a full filesystem
  allowlist**. CPU and output limits do not prevent every large allocation.
  Run deliberately hostile submissions on a disposable Linux/container host;
  the macOS backend is not a complete resource sandbox for a personal machine.
- Host system/runtime directories, Python/SQLite and the OS/container engine
  remain trusted dependencies. There is no claim of protection against kernel
  vulnerabilities or an attacker controlling those dependencies.

## Public submissions

Inference does not upload data automatically. `study submit` previews a public
submission; `--publish` explicitly authorizes GitHub API calls through the user's
existing authenticated `gh`. The PR includes answers, synthetic tool receipts,
model labels, environment, timings and grades. Inspect it for personal data;
pattern-based secret checks cannot recognize every possible secret.

The trusted study workflow checks out base-branch code and fetches only study
JSON from a PR. It never runs contributor scripts/workflows as trusted code and
never merges automatically. Mixed source/study PRs are rejected before grading.
Ordinary PR CI runs in GitHub's disposable environment with read-only repository
permissions. Do not change these workflows to execute fork code with secrets.

Model identity, settings and tool receipts are submitter-reported. Regrading
verifies the recorded scores, not the provenance of inference. CSV metadata is
escaped against spreadsheet formulas; JSON preserves the original strings.

## Reporting a problem

Use the repository's private GitHub security reporting option if available.
Otherwise contact the maintainer through the public profile. Do not post
credentials, personal files or an actionable exploit in a public study PR.
