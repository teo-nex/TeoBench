# Setup by operating system

The agent first detects the OS, reuses installed Python 3.9+ and reads this page. There is no pip dependency or platform-specific model installation. All inference still requires the participant's configured model interfaces and access to the full campaign. Do not install another model, replace model IDs, or change the host's network/security settings to make a grading probe pass.

| Host | CLI | Python-answer sandbox | Preflight |
|---|---|---|---|
| macOS | `python3` outside `/Users` and `/Volumes` | built-in `/usr/bin/sandbox-exec` | `python3 -m teobench doctor` |
| Linux | system `/usr/bin/python3`, checkout/home outside runtime directories | Bubblewrap with `--disable-userns`; permitted user/network namespaces | `python3 -m teobench doctor` |
| Windows 10/11 | native `py -3` or verified `python` | existing Docker Desktop, Linux engine | `py -3 -m teobench doctor --prepare` once, then `py -3 -m teobench doctor` |

Clone the repository and run commands from its root. Do not select the Microsoft Store `python3` placeholder when an installed Python/launcher is available. On macOS `/usr/bin/python3` is a suitable candidate if present; an interpreter under the protected home or external volume cannot run inside the sandbox. On Linux use the system interpreter rather than a tool-cache/virtualenv runtime outside `/usr`.

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

On Debian/Ubuntu, Bubblewrap is normally installed with `sudo apt-get install bubblewrap`. Reuse it when present. An agent must respect the host's package-install authorization. If user namespaces or Bubblewrap flags are prohibited/unavailable, report BLOCKED. Do not disable AppArmor, change sysctl/security settings, use a privileged container, or run Python answers without the sandbox. The CI workflow's disposable GitHub-hosted Ubuntu policy is not an instruction for participant machines.

## Run the actual study

A passing doctor or 30 passing reference solutions only validates the harness. It is **not** model research. Follow [RUN_FULL_STUDY.md](RUN_FULL_STUDY.md): prove all 35 model/effort access conditions, then execute 35 pilot + 1050 primary + 42 control trials. The agent uses the participant's existing credentials without logging or copying them. Localhost URLs refer to the machine where the agent runs; a Mac-only gateway does not become available on Windows automatically. Report a missing route as BLOCKED; do not open tunnels or silently call a different provider.

Keep partial studies locally and resume them. Submission and trusted GitHub checks require the full 1127-trial protocol. Historical reports remain readable and retain their original grader identity. All published data is self-reported rather than independently attested model provenance.

## Validation coverage

macOS/Linux CI runs the complete grader/CLI suite. Hosted Windows CI checks the native CLI, UTF-8, campaign contract and Docker command/cleanup logic without claiming that its Windows-container engine can run the Linux grader. Full Windows integration tests must run on a Windows host with a working Linux Docker engine, as on the development PC. `python -m unittest discover -s tests -v` never silently skips those grading tests when that engine is missing.

The isolation flags follow the [Docker run reference](https://docs.docker.com/reference/cli/docker/container/run/); the anonymous registry entry also prevents [automatic credential-store detection](https://github.com/docker/cli/blob/master/cli/config/config.go).
