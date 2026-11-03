"""Community study format, offline validation and explicit GitHub submission."""

import base64
import collections
import datetime
import hashlib
import json
import math
import re
import shutil
import statistics
import subprocess
import time
from pathlib import Path

from . import __version__
from .evaluate import grade

UPSTREAM = "teo-nex/TeoBench"
MAX_BYTES = 8_000_000
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{2,79}\Z")
EFFORTS = {"low", "medium", "high", "xhigh", "max", "default", "none"}
# Explicit, non-transitive regrading compatibility: the pre-Linux grader at
# aacfaa7 and the Bubblewrap grader from PR #3 may be checked with the
# reviewed portable grader. Every saved
# verdict must still match. Future grader changes require a new reviewed edge.
COMPATIBLE_REGRADERS = {
    "7764269832dde6894979d35ea0bbdd2b6aab0161b8ab796c5b5d405926316308":
        "99074aa5b4f52574c3da336f43ce6abf29e97ec86faaedfaeba9d5d49f322282",
    "08214687c3a81703b01b2171f8e97442e8b7c33c1f30670e788963e2f50c6635":
        "99074aa5b4f52574c3da336f43ce6abf29e97ec86faaedfaeba9d5d49f322282",
    "351c9710e3baf53251f4052cb8191035d7c2a99ab61b0537f34007cbf9229b8b":
        "99074aa5b4f52574c3da336f43ce6abf29e97ec86faaedfaeba9d5d49f322282",
}
SECRET = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})|Bearer\s+[A-Za-z0-9._-]{20,}|https?://[^\s/]+:[^\s/@]+@|/(?:Users|home)/[^/\s]+/", re.I)


def grader_digest():
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in ["evaluate.py", "code_worker.py", "sandbox.py"]:
        digest.update(name.encode()+b"\0"+(root/name).read_bytes())
    return digest.hexdigest()


def require_current_grader(study):
    if study["benchmark"]["grader_sha256"] != grader_digest():
        raise ValueError("historical_study_is_read_only_create_a_new_study")


def reject_secrets(value):
    encoded = json.dumps(value, ensure_ascii=False)
    windows_home = re.search(r"[A-Za-z]:\\\\(?:Users|Documents and Settings)\\\\[^\\]+\\\\", encoded, re.I)
    if SECRET.search(encoded) or windows_home:
        raise ValueError("possible_secret_or_private_home_path: inspect and remove before publishing")


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode("utf-8"))


def strict_object(value, keys, context):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError("invalid_fields: " + context)


def text(value, limit, context):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("invalid_text: " + context)


def load_json(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("study_exceeds_8MB")
    def pairs(items):
        result = {}
        for key, val in items:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = val
        return result
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non_finite_json")))


def create(study_id, access_route, environment):
    from .cli import load
    if not SLUG.fullmatch(study_id):
        raise ValueError("study_id_must_be_3_to_80_lowercase_letters_digits_hyphens")
    _, _, manifest = load()
    value = {
        "schema_version": "1.0", "study_id": study_id,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "benchmark": {"name": "TeoBench", "level": "easy", "version": __version__,
                      "tasks_sha256": manifest["public_sha256"],
                      "acceptance_sha256": manifest["sealed_sha256"],
                      "grader_sha256": grader_digest()},
        "environment": environment, "access_route": access_route,
        "method": "All attempts retained; one replicate is a complete set of 30 tasks. No best-of selection.",
        "records": [],
    }
    reject_secrets(value)
    return value


def add_record(study, task_id, model, effort, answer, history, replicate=0,
               elapsed_seconds=None, transport_error=None):
    from .cli import load
    require_current_grader(study)
    tasks, answers, _ = load()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if task is None:
        raise ValueError("unknown_task")
    result = grade(task, answer, answers[task_id], history) if transport_error is None else None
    study["records"].append({"task_id": task_id, "model": model, "effort": effort,
        "replicate": replicate, "answer": answer, "tool_history": history,
        "elapsed_seconds": elapsed_seconds, "transport_error": transport_error,
        "evaluation": result})
    validate(study, regrade=False)
    return study


def validate(study, regrade=True):
    from .cli import load
    tasks, answers, manifest = load()
    task_map = {t["id"]: t for t in tasks}
    strict_object(study, ["schema_version", "study_id", "created_at", "benchmark", "environment",
                          "access_route", "method", "records"], "study")
    if study["schema_version"] != "1.0" or not isinstance(study["study_id"], str) or not SLUG.fullmatch(study["study_id"]):
        raise ValueError("unsupported_schema_or_study_id")
    text(study["created_at"], 80, "created_at")
    parsed = datetime.datetime.fromisoformat(study["created_at"].replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("created_at_requires_timezone")
    text(study["environment"], 300, "environment")
    text(study["access_route"], 300, "access_route")
    text(study["method"], 2000, "method")
    current_grader = grader_digest()
    benchmark = study["benchmark"]
    recorded_grader = benchmark.get("grader_sha256") if isinstance(benchmark, dict) else None
    if (not isinstance(recorded_grader, str)
            or (recorded_grader != current_grader
                and COMPATIBLE_REGRADERS.get(recorded_grader) != current_grader)):
        raise ValueError("benchmark_or_grader_version_mismatch")
    expected_benchmark = {"name": "TeoBench", "level": "easy", "version": __version__,
        "tasks_sha256": manifest["public_sha256"], "acceptance_sha256": manifest["sealed_sha256"],
        "grader_sha256": recorded_grader}
    if benchmark != expected_benchmark:
        raise ValueError("benchmark_or_grader_version_mismatch")
    rows = study["records"]
    if not isinstance(rows, list) or len(rows) > 3000:
        raise ValueError("records_must_be_array_up_to_3000")
    reject_secrets(study)
    if len(json.dumps(study, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError("study_exceeds_8MB")
    seen = set()
    groups = collections.defaultdict(list)
    for row in rows:
        strict_object(row, ["task_id", "model", "effort", "replicate", "answer", "tool_history",
                            "elapsed_seconds", "transport_error", "evaluation"], "record")
        if not isinstance(row["task_id"], str) or row["task_id"] not in task_map:
            raise ValueError("unknown_task")
        text(row["model"], 200, "model")
        if not isinstance(row["effort"], str) or row["effort"] not in EFFORTS:
            raise ValueError("unknown_effort")
        if type(row["replicate"]) is not int or not 0 <= row["replicate"] <= 100:
            raise ValueError("invalid_replicate")
        identity = row["model"], row["effort"], row["replicate"], row["task_id"]
        if identity in seen:
            raise ValueError("duplicate_task_in_condition")
        seen.add(identity)
        if not isinstance(row["answer"], str) or len(row["answer"]) > 50_000:
            raise ValueError("answer_must_be_text_up_to_50000_chars")
        secs = row["elapsed_seconds"]
        if secs is not None and (type(secs) not in (float, int) or not math.isfinite(secs) or not 0 <= secs <= 86400):
            raise ValueError("invalid_elapsed_seconds")
        error = row["transport_error"]
        if error is not None:
            text(error, 300, "transport_error")
        history = row["tool_history"]
        if not isinstance(history, list) or len(history) > 100:
            raise ValueError("invalid_tool_history")
        if history and task_map[row["task_id"]]["family"] != "tools":
            raise ValueError("tool_history_only_valid_for_tools_tasks")
        for receipt in history:
            strict_object(receipt, ["name", "arguments", "ok", "output"], "tool_receipt")
            if receipt["name"] != "lookup" or type(receipt["ok"]) is not bool:
                raise ValueError("invalid_tool_receipt")
            strict_object(receipt["arguments"], ["id"], "tool_arguments")
            text(receipt["arguments"]["id"], 100, "lookup_id")
        if error is None:
            evaluation = row["evaluation"]
            strict_object(evaluation, ["semantic_pass", "strict_pass", "passed_cases", "total_cases", "error"], "evaluation")
            if any(type(evaluation[k]) is not bool for k in ["semantic_pass", "strict_pass"]):
                raise ValueError("invalid_grade_flags")
            if (type(evaluation["passed_cases"]) is not int or type(evaluation["total_cases"]) is not int
                    or not 0 <= evaluation["passed_cases"] <= evaluation["total_cases"]):
                raise ValueError("invalid_grade_counts")
            if evaluation["error"] is not None:
                text(evaluation["error"], 300, "grade_error")
                if "OS_sandbox_unavailable" in evaluation["error"] or evaluation["error"].startswith("FileNotFoundError"):
                    raise ValueError("grader_environment_unavailable")
            if regrade:
                actual = grade(task_map[row["task_id"]], row["answer"], answers[row["task_id"]], history)
                fields = ["semantic_pass", "strict_pass", "passed_cases", "total_cases"]
                # Exception wording can vary between supported Python/SQLite
                # versions; the verdict and failure class must still agree.
                error_class = lambda x: x.split(":", 1)[0] if x else None
                if (any(actual[k] != evaluation[k] for k in fields)
                        or error_class(actual["error"]) != error_class(evaluation["error"])):
                    raise ValueError("regrade_mismatch: " + row["task_id"])
        elif row["evaluation"] is not None:
            raise ValueError("transport_failure_must_not_claim_grade")
        groups[identity[:3]].append(row)
    complete = [rows for rows in groups.values() if {r["task_id"] for r in rows} == set(task_map)]
    return {"status": "PASS", "study_id": study["study_id"], "records": len(rows),
        "conditions": len(groups), "complete_runs": len(complete),
        "incomplete_runs": len(groups)-len(complete),
        "semantic_pass": sum(bool(r["evaluation"] and r["evaluation"]["semantic_pass"]) for r in study["records"]),
        "transport_errors": sum(r["transport_error"] is not None for r in study["records"]),
        "answers_regraded": regrade,
        "recorded_grader_sha256": recorded_grader,
        "regraded_with_sha256": current_grader if regrade else None,
        "model_identity_and_execution_trace": "submitter-reported; not independently attested"}


def statistics_report(paths, regrade=True):
    groups = collections.defaultdict(list)
    seen = set()
    accepted = []
    incomplete = 0
    duplicates = 0
    regraded_with = grader_digest() if regrade else None
    for path in sorted(map(Path, paths)):
        study = load_json(path)
        report = validate(study, regrade=regrade)
        if not report["records"]:
            continue
        # Dedupe exact response sets even when metadata/study ID is changed.
        fingerprint = hashlib.sha256(json.dumps(sorted([
            {k:r[k] for k in ["task_id","model","effort","replicate","answer","tool_history","transport_error"]}
            for r in study["records"]], key=lambda r:(r["model"],r["effort"],r["replicate"],r["task_id"])),
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if fingerprint in seen:
            duplicates += 1
            continue
        seen.add(fingerprint)
        accepted.append(study["study_id"])
        conditions = collections.defaultdict(list)
        for row in study["records"]:
            conditions[row["model"],row["effort"],row["replicate"]].append(row)
        for (model, effort, replicate), rows in conditions.items():
            if len(rows) != 30:
                incomplete += 1
                continue
            key = model, effort, study["access_route"], study["environment"], study["benchmark"]["grader_sha256"]
            passed = sum(bool(r["evaluation"] and r["evaluation"]["semantic_pass"]) for r in rows)
            groups[key].append({"study_id": study["study_id"], "replicate": replicate,
                "passed": passed, "transport_errors": sum(r["transport_error"] is not None for r in rows)})
    entries=[]
    for (model, effort, route, environment, grader), runs in sorted(groups.items()):
        scores = [r["passed"] / 30 for r in runs]
        entries.append({"model": model, "effort": effort, "access_route": route,
            "environment": environment, "grader_sha256": grader,
            "regraded_with_sha256": regraded_with,
            "studies": len({r["study_id"] for r in runs}), "runs": len(runs), "task_results": 30*len(runs),
            "median_pass_rate": statistics.median(scores), "mean_pass_rate": statistics.mean(scores),
            "min_pass_rate": min(scores), "max_pass_rate": max(scores),
            "transport_errors": sum(r["transport_errors"] for r in runs)})
    return {"schema_version": "1.0", "level": "easy", "studies": accepted,
        "incomplete_runs_excluded": incomplete, "duplicate_studies_excluded": duplicates,
        "answers_regraded": regrade, "regraded_with_sha256": regraded_with,
        "identity_status": "submitter-reported model IDs; inference not attested; see answers_regraded for score checks",
        "aggregation": "Complete 30-task runs only; grouped by model, effort, access route, environment and grader. Not a representative population sample.",
        "groups": entries}


def publish(path, publish=False, gh=None):
    study = load_json(path)
    report = validate(study, regrade=False)
    require_current_grader(study)
    if not report["records"]:
        raise ValueError("cannot_submit_empty_study")
    from .campaign import require_complete
    campaign = require_complete(study)
    report = validate(study)
    report["campaign"] = campaign
    if not publish:
        return {"preview": report, "destination": UPSTREAM,
            "publishes": "answers, synthetic lookup receipts, model IDs, environment, timing and scores",
            "next": "Obtain the user's confirmation, then repeat with --publish. No network action performed."}
    executable = gh or shutil.which("gh")
    if not executable:
        raise ValueError("GitHub_CLI_not_found_install_gh_and_run_gh_auth_login")

    def api(endpoint, method="GET", data=None):
        command = [executable, "api", endpoint, "--method", method]
        payload = None
        if data is not None:
            command += ["--input", "-"]
            payload = json.dumps(data)
        result = subprocess.run(command, input=payload, text=True, capture_output=True, timeout=60)
        if result.returncode:
            raise ValueError("github_api_failed: " + result.stderr.strip()[:400])
        return json.loads(result.stdout) if result.stdout.strip() else {}

    owner = api("user")["login"]
    upstream = api("repos/"+UPSTREAM)
    base = upstream["default_branch"]
    head = api("repos/"+UPSTREAM+"/git/ref/heads/"+base)["object"]["sha"]
    if owner == UPSTREAM.split("/")[0]:
        target = UPSTREAM
    else:
        # Fork API returns an existing fork on repeated submission.
        fork = api("repos/"+UPSTREAM+"/forks", "POST", {})
        target = fork["full_name"]
        if target.split("/")[0] != owner:
            raise ValueError("fork_owner_mismatch")
        for attempt in range(5):
            try:
                api("repos/"+target+"/git/ref/heads/"+fork["default_branch"])
                break
            except ValueError:
                if attempt == 4:
                    raise
                time.sleep(1)
    content = json.dumps(study, ensure_ascii=False, indent=2, allow_nan=False)+"\n"
    # A unique branch avoids overwriting a contributor's existing work.
    branch = "study/"+study["study_id"]+"-"+datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S%f")
    api("repos/"+target+"/git/refs", "POST", {"ref":"refs/heads/"+branch,"sha":head})
    relative = "Easy-Bench/studies/"+study["study_id"]+"/study.json"
    api("repos/"+target+"/contents/"+relative, "PUT", {
        "message":"Add Easy study "+study["study_id"], "branch":branch,
        "content":base64.b64encode(content.encode()).decode()})
    result = api("repos/"+UPSTREAM+"/pulls", "POST", {
        "title":"Easy-Bench study: "+study["study_id"], "head":owner+":"+branch, "base":base,
        "body":"Community study submitted with TeoBench CLI.\n\n"
               +"Records: "+str(report["records"])+"; complete runs: "+str(report["complete_runs"])+".\n"
               +"The contributor confirmed public submission. Model identity and execution remain self-reported.\n"
               +"Please validate the study and regrade its answers before merging."})
    return {"pull_request":result["html_url"],"study_id":study["study_id"],"auto_merged":False}
