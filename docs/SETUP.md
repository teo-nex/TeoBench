# Setup by operating system

The agent first detects the OS, reuses installed Python 3.9+ and reads this page. There is no pip dependency or platform-specific model installation. All inference still requires the participant's configured model interfaces and access to the full campaign. Do not install another model, replace model IDs, or change the host's network/security settings to make a grading probe pass.

| Host | CLI | Python-answer sandbox | Preflight |
|---|---|---|---|
| macOS | `python3` outside `/Users` and `/Volumes` for Seatbelt | built-in Seatbelt; automatic fallback to an existing local Docker Linux engine | `python3 -m teobench doctor --prepare` |
| Linux | system `/usr/bin/python3`, checkout/home outside runtime directories | Bubblewrap with `--disable-userns`; permitted user/network namespaces | `python3 -m teobench doctor` |
| Windows 10/11 | native `py -3` or verified `python` | existing Docker Desktop, Linux engine | `py -3 -m teobench doctor --prepare` once, then `py -3 -m teobench doctor` |

Clone the repository and run commands from its root. Do not select the Microsoft Store `python3` placeholder when an installed Python/launcher is available. On macOS `/usr/bin/python3` is a suitable candidate if present; an interpreter under the protected home or external volume cannot run inside the sandbox. On Linux use the system interpreter rather than a tool-cache/virtualenv runtime outside `/usr`.

SQL grading requires SQLite with a working hard heap limit. Apple's system Python may link a SQLite build whose heap limit remains zero. On macOS the grader probes the current interpreter, the existing `python3` on PATH and the standard Homebrew Python locations, all inside Seatbelt, and reuses a passing installed runtime for SQL only. It installs nothing. If none passes, doctor reports `OS_sandbox_unavailable_SQLite_heap_limit_use_supported_installed_Python` before inference. Doctor checks both the Python and SQL workers.

## Windows (PowerShell)

```powershell
git clone https://github.com/teo-nex/TeoBench.git
Set-Location TeoBench
py -3 -m teobench doctor --prepare
if ($LASTEXITCODE -ne 0) { throw 'Grading environment is BLOCKED; follow doctor error' }
py -3 -m teobench verify
py -3 -m teobench campaign plan
py -3 -m unittest discover -s tests -v
```

`--prepare` downloads only the digest-pinned official Python image. It does not install Docker, enable WSL/Hyper-V, switch engines, change execution policy, request administrator credentials, or alter firewall/VPN settings. If Docker is absent/stopped/in Windows-container mode, report that concrete prerequisite and stop inference until it is resolved through the user's normal setup process. Do not fall back to executing code in the host interpreter.

Windows SSH sessions sometimes cannot unlock Docker Desktop's credential helper. For this public image only, preparation can retry anonymously with a temporary anonymous Docker config against the exact same local named-pipe daemon. It does not edit the user's Docker config, copy credentials, change context or persist that temporary config. Remote/non-pipe contexts receive a concrete BLOCKED error instead.

Use `py -3 -m teobench ...` for **all** record/grade/validate/stats/submit/campaign commands. Use single-line commands or PowerShell continuation, not Bash `\`. Python subprocess pipes and report files use UTF-8 explicitly. PowerShell 5 UTF-8 BOM input files are accepted. Generated reports keep LF endings. `--environment` should describe Windows/Python/Docker and model/tool settings, without usernames, computer names or private paths.

## macOS / Linux

```sh
python3 -m teobench doctor
python3 -m teobench verify
python3 -m unittest discover -s tests -v
python3 -m teobench campaign plan
```

### macOS: Seatbelt denied

`sandbox-exec: sandbox_apply: Operation not permitted` (often exit 71) means
the host/client refused to apply the grading sandbox. An already sandboxed
agent session can cause this; the message alone does not prove the exact host
policy. In default `auto` mode, TeoBench then tries an existing local Docker
Linux engine. It resolves and pins the current Docker context's local Unix
socket, including Docker Desktop's socket under `~/.docker/run`; TCP/SSH and
remote contexts are rejected before sending answers. No engine is installed,
started or reconfigured. Worker errors/timeouts do not trigger a second trial.

Use **one preflight command before model requests**:

```sh
python3 -m teobench doctor --prepare
```

When Seatbelt works, this command does not require Docker or download anything.
When Seatbelt setup is denied, it prepares only the digest-pinned official
Python image in the already running local Docker engine, then checks isolation,
Python and SQL. Grading itself never downloads images. The selected backend is
shown as `macos-seatbelt` or `macos-docker`. `TEOBENCH_PYTHON_SANDBOX=seatbelt`
disables fallback; `docker` explicitly selects the container. Containers use
the Linux fallback's isolation and 128 MiB memory ceiling.

If both backends are unavailable, doctor returns `status: BLOCKED` and a
`next_step`. Stop inference and retain existing answers for later grading.
This is an infrastructure blocker, not a wrong model answer. Static Python
checks do not replace the 300 execution tests.

If the participant's normal permissions allow it, run the same `doctor` and
grading commands from an ordinary Terminal or another already available grading
host. A client approval mechanism must be used when required; do not bypass its
policy. Do not disable SIP, sandboxing, host security or execute candidates
unconfined. This error alone is not a reason to change Full Disk Access.

### Linux namespaces

On Debian/Ubuntu, Bubblewrap is normally installed with `sudo apt-get install bubblewrap`. Reuse it when present. An agent must respect the host's package-install authorization. If user namespaces or Bubblewrap flags are prohibited/unavailable, the grader tries the already configured local Docker socket and pinned local Python image described in [PROTOCOL.md](PROTOCOL.md). It never pulls that image on Linux. If neither sandbox is ready, report BLOCKED. Do not disable AppArmor, change sysctl/security settings, use a privileged container, or run Python answers without the sandbox. The CI workflow's disposable GitHub-hosted Ubuntu policy is not an instruction for participant machines.

## Run the actual study

A passing doctor or 30 passing reference solutions only validates the harness. It is **not** model research. Follow [RUN_FULL_STUDY.md](RUN_FULL_STUDY.md): prove all 35 model/effort access conditions, then execute 35 pilot + 1050 primary + 42 control trials. The agent uses the participant's existing credentials without logging or copying them. Localhost URLs refer to the machine where the agent runs; a Mac-only gateway does not become available on Windows automatically. Report a missing route as BLOCKED; do not open tunnels or silently call a different provider.

Keep partial studies locally and resume them. Submission and trusted GitHub checks require the full 1127-trial protocol. Historical reports remain readable and retain their original grader identity. All published data is self-reported rather than independently attested model provenance.

## Validation coverage

macOS/Linux CI runs the complete grader/CLI suite. Hosted Windows CI checks the native CLI, UTF-8, campaign contract and Docker command/cleanup logic without claiming that its Windows-container engine can run the Linux grader. Full Windows integration tests must run on a Windows host with a working Linux Docker engine, as on the development PC. `python -m unittest discover -s tests -v` never silently skips those grading tests when that engine is missing.

The isolation flags follow the [Docker run reference](https://docs.docker.com/reference/cli/docker/container/run/); macOS endpoint resolution follows [Docker contexts](https://docs.docker.com/engine/manage-resources/contexts/) and [Mac socket configuration](https://docs.docker.com/desktop/setup/install/mac-permission-requirements/). The anonymous registry entry also prevents [automatic credential-store detection](https://github.com/docker/cli/blob/master/cli/config/config.go).
