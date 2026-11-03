"""Deterministic grading, separately constrained Python and read-only SQLite."""

import json
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent


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


def python_outputs(source, inputs):
    worker = (ROOT / "code_worker.py").read_text()
    completed = subprocess.run(sandbox_command(worker),
                               input=json.dumps({"source": source, "inputs": inputs}), capture_output=True,
                               text=True, timeout=5, cwd="/", env={"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"})
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


def sql_outputs(query, fixture):
    if len(query.encode("utf-8")) > 100_000:
        raise ValueError("sql_length_limit")
    connection = sqlite3.connect(":memory:")
    try:
        for table, info in fixture["tables"].items():
            columns = ",".join('"'+c+'"' for c in info["columns"])
            connection.execute('CREATE TABLE "'+table+'" ('+columns+')')
            connection.executemany('INSERT INTO "'+table+'" VALUES ('+','.join('?' for _ in info["columns"])+')', info["rows"])
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}

        def authorize(action, arg1, arg2, database, trigger):
            if action not in allowed or (action == sqlite3.SQLITE_FUNCTION and str(arg2).lower() == "load_extension"):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        steps = 0

        def progress():
            nonlocal steps
            steps += 1
            return steps > 500

        connection.set_progress_handler(progress, 1000)
        if hasattr(connection, "setlimit"):
            connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 100_000)
        cursor = connection.execute(query)
        rows = cursor.fetchmany(10_001)
        if len(rows) > 10_000:
            raise ValueError("row_limit")
        return [list(row) for row in rows]
    finally:
        connection.close()


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
                outputs = [sql_outputs(clean, case) for case in cases]
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
