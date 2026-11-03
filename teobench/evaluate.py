"""Deterministic grading, separately constrained Python and read-only SQLite."""

import json
from functools import lru_cache
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
import os
import uuid

ROOT = Path(__file__).resolve().parent
# Official Python image, pinned to the reviewed multi-platform manifest. Never
# pull during grading: the operator must have provisioned this image already.
DOCKER_IMAGE = "python@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def strip_fence(text):
    match = re.fullmatch(r"\s*```[^\n]*\n(.*?)\n```\s*", text, flags=re.S)
    return match.group(1) if match else text.strip()


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def parse_json(text):
    decoder = json.JSONDecoder(object_pairs_hook=no_duplicates,
                               parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    clean = text.strip()
    try:
        return json.loads(clean, object_pairs_hook=no_duplicates, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x))), True
    except ValueError:
        pass
    for start in range(len(text)):
        if text[start] == "{":
            try:
                obj, _ = decoder.raw_decode(text[start:])
                return obj, False
            except ValueError:
                continue
    raise ValueError("missing_json")


def sandbox_command(script):
    if sys.platform == "win32":
        from .sandbox import windows_command
        return windows_command(script)
    if sys.platform.startswith("linux"):
        sandbox = shutil.which("bwrap")
        if sandbox is None:
            raise RuntimeError("OS_sandbox_unavailable_install_bubblewrap")
        executable = Path(sys.executable).resolve()
        if not executable.is_relative_to("/usr"):
            raise RuntimeError("OS_sandbox_unavailable_python_must_be_under_usr")
        runtime = [Path(path) for path in ["/usr", "/lib", "/lib64"] if Path(path).exists()]
        # Only system runtime directories are exposed; never mount private data.
        for protected in [Path.home().resolve(), ROOT.parent.resolve()]:
            if any(protected.is_relative_to(path.resolve()) or path.resolve().is_relative_to(protected)
                   for path in runtime):
                raise RuntimeError("OS_sandbox_unavailable_private_path_overlaps_runtime")
        command = [sandbox, "--unshare-user", "--unshare-ipc", "--unshare-pid", "--unshare-net",
                   "--unshare-uts", "--disable-userns", "--die-with-parent", "--new-session",
                   "--cap-drop", "ALL", "--clearenv", "--setenv", "LANG", "C.UTF-8"]
        for path in runtime:
            command += ["--ro-bind", str(path), str(path)]
        return command + ["--remount-ro", "/", "--chdir", "/", "--", str(executable), "-I", "-S", "-c", script]
    if sys.platform != "darwin":
        raise RuntimeError("OS_sandbox_unavailable_no_unsafe_fallback")
    sandbox = Path("/usr/bin/sandbox-exec")
    if not sandbox.exists():
        raise RuntimeError("OS_sandbox_unavailable_no_unsafe_fallback")
    # No network or writes. Hide both user data and the published acceptance
    # files. Candidate code is received via stdin, never as an executable file.
    protected = {str(Path.home()), str(ROOT.parent), "/Users", "/Volumes"}
    paths = " ".join("(subpath "+json.dumps(p, ensure_ascii=False)+")" for p in sorted(protected))
    profile = '(version 1)(allow default)(deny network*)(deny file-write*)(deny file-read* '+paths+')'
    return [str(sandbox), "-p", profile, sys.executable, "-I", "-c", script]


def docker_run(script, input=None, timeout=5):
    if sys.platform == 'darwin':
        from .sandbox import local_docker_client, docker_environment
        client = local_docker_client()
        environment = docker_environment()
    else:
        docker = shutil.which("docker")
        if docker is None:
            raise RuntimeError("OS_sandbox_unavailable_bubblewrap_or_local_docker_required")
        # Linux ignores remote contexts; macOS resolves its local Desktop socket.
        client = [docker, "--host=unix:///var/run/docker.sock"]
        environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    name = "teobench-worker-" + uuid.uuid4().hex
    options = dict(capture_output=True, text=True, cwd="/",
                   env=environment)
    # No host mounts, Docker socket, network, writable filesystem or elevated
    # privileges. IPC=none also removes the writable /dev/shm shared memory.
    command = client + ["create", "--name", name, "--pull=never", "--interactive",
               "--network=none", "--ipc=none", "--read-only", "--cap-drop=ALL",
               "--security-opt=no-new-privileges=true", "--user=65534:65534",
               "--pids-limit=16", "--memory=128m", "--memory-swap=128m", "--cpus=1",
               "--ulimit", "core=0", "--workdir=/", "--env", "LANG=C.UTF-8",
               "--entrypoint", "/usr/local/bin/python3", DOCKER_IMAGE,
               "-I", "-S", "-c", script]
    # Create separately so a worker timeout cannot orphan a running container
    # after the attached Docker client is killed by subprocess.run.
    created = False
    try:
        result = subprocess.run(command, timeout=10, **options)
        if result.returncode:
            raise RuntimeError("OS_sandbox_unavailable_docker_create_failed_local_image_required")
        created = True
        result = subprocess.run(client + ["start", "--attach", "--interactive", name],
                                input=input, timeout=timeout, **options)
        if result.returncode in {125, 126, 127} or (result.returncode and
                result.stderr.startswith(("Error response from daemon:", "Error: failed to start"))):
            raise RuntimeError("OS_sandbox_unavailable_docker_start_failed")
        result.sandbox_backend = "macos-docker" if sys.platform == 'darwin' else "linux-docker"
        return result
    finally:
        # Also attempt cleanup after a create timeout; never remove containers
        # selected by a model, an image, or another concurrent TeoBench worker.
        removed = subprocess.run(client + ["rm", "--force", name], timeout=10, **options)
        if created and removed.returncode:
            raise RuntimeError("OS_sandbox_unavailable_docker_cleanup_failed")


def sandbox_run(script, input=None, timeout=5, executable=None, backend=None):
    if executable is not None and sys.platform != 'darwin':
        raise RuntimeError('OS_sandbox_unavailable_runtime_override_requires_macos')
    backend = backend or os.environ.get("TEOBENCH_PYTHON_SANDBOX", "auto")
    if backend not in {"auto", "bubblewrap", "docker", "seatbelt"}:
        raise RuntimeError("OS_sandbox_unavailable_unknown_backend")
    if sys.platform == "win32" and backend in {"auto", "docker"}:
        from .sandbox import run_command
        return run_command(sandbox_command(script), input, timeout=timeout)
    linux = sys.platform.startswith("linux")
    macos = sys.platform == 'darwin'
    if (backend == 'seatbelt' and not macos) or (backend == 'bubblewrap' and not linux):
        raise RuntimeError('OS_sandbox_unavailable_backend_platform_mismatch')
    if backend == "docker":
        if not (linux or macos):
            raise RuntimeError("OS_sandbox_unavailable_docker_unsupported_platform")
        return docker_run(script, input=input, timeout=timeout)
    try:
        command = sandbox_command(script)
        if executable is not None:
            command[-4] = executable
        result = subprocess.run(command, input=input, capture_output=True,
                                text=True, timeout=timeout, cwd="/",
                                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
        if macos and result.returncode and result.stderr.startswith('sandbox-exec:'):
            raise RuntimeError('OS_sandbox_unavailable_macos_seatbelt_setup_failed')
    except RuntimeError as error:
        if (not (linux or macos) or backend != "auto"
                or not str(error).startswith('OS_sandbox_unavailable')):
            raise
    else:
        if not (linux and result.returncode and result.stderr.startswith("bwrap:")):
            result.sandbox_backend = "linux-bubblewrap" if linux else "macos-seatbelt"
            return result
        if backend == "bubblewrap":
            raise RuntimeError("OS_sandbox_unavailable_bubblewrap_setup_failed")
    # Retry only an infrastructure/setup failure, never a candidate-code error
    # or timeout. Docker is another OS sandbox, not an unconfined fallback.
    return docker_run(script, input=input, timeout=timeout)


def python_outputs(source, inputs):
    worker = (ROOT / "code_worker.py").read_text(encoding="utf-8-sig")
    completed = sandbox_run(worker, input=json.dumps({"source": source, "inputs": inputs}))
    if completed.returncode != 0:
        if sys.platform.startswith("linux") and completed.stderr.startswith("bwrap:"):
            raise RuntimeError("OS_sandbox_unavailable_bubblewrap_setup_failed")
        raise RuntimeError("sandbox_worker_exit_" + str(completed.returncode))
    if len(completed.stdout) > 2_000_000:
        raise RuntimeError("worker_output_limit")
    result = json.loads(completed.stdout)
    if "error" in result:
        raise ValueError("worker_" + result["error"])
    return result["outputs"]


@lru_cache(maxsize=1)
def sql_runtime():
    if sys.platform != 'darwin':
        return None
    # Apple CLT Python may link SQLite built without working heap accounting.
    # Probe only installed interpreters, in the same OS sandbox. No downloads
    # or changes to either Python or the parent's SQLite global heap settings.
    probe = ('import sqlite3,sys; c=sqlite3.connect(":memory:"); '
             'r=c.execute("PRAGMA hard_heap_limit=67108864").fetchone(); '
             'sys.exit(0 if r and 0 < r[0] <= 67108864 else 1)')
    candidates = [sys.executable, shutil.which('python3'),
                  '/opt/homebrew/bin/python3', '/usr/local/bin/python3']
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen or not Path(candidate).is_file():
            continue
        seen.add(candidate)
        try:
            result = sandbox_run(probe, executable=candidate)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return candidate
    raise RuntimeError('OS_sandbox_unavailable_SQLite_heap_limit_use_supported_installed_Python')


def sql_batch(query, fixtures):
    if len(query.encode('utf-8')) > 100_000:
        raise ValueError('sql_length_limit')
    worker = (ROOT / 'sql_worker.py').read_text(encoding='utf-8-sig')
    request = {'query': query, 'fixtures': [{'tables': fixture['tables']} for fixture in fixtures]}
    completed = sandbox_run(worker, input=json.dumps(request), executable=sql_runtime())
    if completed.returncode:
        raise RuntimeError('sandbox_worker_exit_'+str(completed.returncode))
    if len(completed.stdout) > 2_000_000:
        raise RuntimeError('worker_output_limit')
    result = json.loads(completed.stdout)
    if 'error' in result:
        errors = {name: getattr(sqlite3, name) for name in
                  ['Error', 'DatabaseError', 'OperationalError', 'DataError',
                   'IntegrityError', 'ProgrammingError', 'InterfaceError', 'NotSupportedError']}
        errors.update(ValueError=ValueError, RuntimeError=RuntimeError, MemoryError=MemoryError,
                      TypeError=TypeError, OverflowError=OverflowError)
        raise errors.get(result['error'], ValueError)(result.get('message', 'sql_worker_failed'))
    return result['outputs']


def sql_outputs(query, fixture):
    return sql_batch(query, [fixture])[0]

def grade(task, answer, acceptance, tool_history=None):
    result = {"semantic_pass": False, "strict_pass": False, "passed_cases": 0, "total_cases": 1, "error": None}
    try:
        if task["family"] in {"code", "sql"}:
            clean = strip_fence(answer)
            cases = acceptance["cases"]
            result["total_cases"] = len(cases)
            if task["family"] == "code":
                outputs = python_outputs(clean, [c["input"] for c in cases])
            else:
                outputs = sql_batch(clean, cases)
            result["passed_cases"] = sum(canonical(out) == canonical(case["expected"]) for out, case in zip(outputs, cases))
            result["semantic_pass"] = len(outputs) == len(cases) and result["passed_cases"] == len(cases)
            result["strict_pass"] = result["semantic_pass"] and clean == answer.strip()
        else:
            parsed, strict = parse_json(answer)
            passed = canonical(parsed) == canonical(acceptance["expected"])
            if task["family"] == "tools":
                history = tool_history or []
                read_ids = set()
                valid_trace = True
                for receipt in history:
                    args = receipt.get("arguments", {})
                    key = args.get("id") if isinstance(args, dict) else None
                    valid = (receipt.get("name") == "lookup" and receipt.get("ok") is True
                             and isinstance(args, dict) and set(args) == {"id"}
                             and isinstance(key, str) and key in acceptance["catalog"])
                    if valid:
                        valid = canonical(receipt.get("output")) == canonical(acceptance["catalog"][key])
                    valid_trace = valid_trace and valid
                    if valid:
                        read_ids.add(key)
                passed = passed and valid_trace and set(acceptance["required_ids"]) <= read_ids
            result.update(semantic_pass=passed, strict_pass=passed and strict, passed_cases=int(passed))
    except Exception as error:
        result["error"] = type(error).__name__ + ": " + str(error)[:150]
    return result
