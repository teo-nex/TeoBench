"""Offline grading commands plus an explicit, optional isolated Pi inference command."""

import argparse
import collections
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from .evaluate import grade

ROOT = Path(__file__).resolve().parent.parent
EASY = ROOT / "Easy-Bench" / "tasks"


def load():
    manifest = json.loads((EASY / "manifest.json").read_text(encoding="utf-8-sig"))
    for name, key in [("tasks.jsonl", "public_sha256"), ("answers.json", "sealed_sha256")]:
        if hashlib.sha256((EASY / name).read_bytes()).hexdigest() != manifest[key]:
            raise ValueError("dataset_hash_mismatch: " + name)
    tasks = [json.loads(line) for line in (EASY / "tasks.jsonl").read_text(encoding="utf-8-sig").splitlines()]
    return tasks, json.loads((EASY / "answers.json").read_text(encoding="utf-8-sig")), manifest


def verify():
    tasks, answers, manifest = load()
    spec = importlib.util.spec_from_file_location("original_generator", EASY / "source" / "dataset.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    generated_tasks, generated_answers = module.build()
    if generated_tasks != tasks or generated_answers != answers:
        raise ValueError("generator_does_not_reproduce_frozen_dataset")
    receipt = json.loads((EASY / "PROVENANCE.json").read_text(encoding="utf-8-sig"))
    for relative, expected in receipt["published_files_sha256"].items():
        if hashlib.sha256((EASY / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("provenance_hash_mismatch: " + relative)
    return {
        "status": "PASS", "level": "easy", "tasks": len(tasks),
        "families": dict(collections.Counter(t["family"] for t in tasks)),
        "code_cases": sum(len(answers[t["id"]]["cases"]) for t in tasks if t["family"] == "code"),
        "sql_databases": sum(len(answers[t["id"]]["cases"]) for t in tasks if t["family"] == "sql"),
        "public_sha256": manifest["public_sha256"],
        "acceptance_sha256": manifest["sealed_sha256"],
    }


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def main(argv=None):
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="TeoBench Easy — offline benchmark inspection and grading")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="check Python/SQL sandbox before model requests")
    doctor.add_argument("--prepare", action="store_true", help="prepare pinned local Docker image on Windows or when needed on macOS")
    sub.add_parser("verify", help="check hashes and regenerate all 30 original tasks in memory")
    listing = sub.add_parser("list", help="list original task IDs and titles")
    listing.add_argument("--family", choices=["reasoning", "code", "sql", "data", "tools"])
    show = sub.add_parser("show", help="print a model-facing task, without acceptance data")
    show.add_argument("task")
    lookup = sub.add_parser("lookup", help="execute the synthetic lookup tool for a T task")
    lookup.add_argument("task")
    lookup.add_argument("id")
    grading = sub.add_parser("grade", help="grade one answer; see docs/PROTOCOL.md for trace schema")
    grading.add_argument("task")
    grading.add_argument("--answer", type=Path, required=True)
    grading.add_argument("--history", type=Path, help="JSON array of trusted executor lookup receipts")
    study = sub.add_parser("study", help="create, record, validate or submit a community study")
    actions = study.add_subparsers(dest="action", required=True)
    create = actions.add_parser("create")
    create.add_argument("--id", required=True)
    create.add_argument("--file", type=Path, required=True)
    create.add_argument("--access-route", required=True, help="provider/gateway route, without credentials")
    create.add_argument("--environment", required=True, help="OS/runtime and relevant tool settings; no host/user names")
    create.add_argument("--campaign-profile", help="explicit trusted campaign profile; creates schema 1.1")
    create.add_argument("--execution-profile", choices=["pi-clean-v1"], help="separate standardized inference cohort")
    record = actions.add_parser("record")
    record.add_argument("--file", type=Path, required=True)
    record.add_argument("--task", required=True)
    record.add_argument("--model", required=True, help="exact model ID used")
    record.add_argument("--effort", required=True)
    record.add_argument("--replicate", type=int, default=0)
    record.add_argument("--answer", type=Path, required=True)
    record.add_argument("--history", type=Path)
    record.add_argument("--seconds", type=float)
    record.add_argument("--transport-error")
    record.add_argument("--attempt", type=int, default=0, help="schema 1.1 non-scoring retry number; 0 records the controlled observation")
    record.add_argument("--started-at", help="timezone-aware actual retry start time; required with --attempt")
    for action in ["validate", "submit"]:
        command = actions.add_parser(action)
        command.add_argument("--file", type=Path, required=True)
        if action == "submit":
            command.add_argument("--publish", action="store_true", help="explicit consent to create a public PR")
            command.add_argument("--gh", help="path to an authenticated GitHub CLI")
    campaign = sub.add_parser("campaign", help="plan and check the FULL 7-model x 5-effort study")
    campaign_actions = campaign.add_subparsers(dest="action", required=True)
    campaign_plan = campaign_actions.add_parser("plan")
    campaign_plan.add_argument("--profile", help="trusted campaign profile (default: original seven-model study)")
    for action in ["status", "next"]:
        command = campaign_actions.add_parser(action)
        command.add_argument("--file", type=Path, required=True)
    stats = sub.add_parser("stats", help="regrade accepted studies and aggregate complete runs")
    stats.add_argument("--directory", type=Path, default=ROOT / "Easy-Bench" / "studies")
    stats.add_argument("--output", type=Path)
    pi = sub.add_parser("pi-trial", help="optional clean Pi trial; --preflight performs no model inference")
    pi.add_argument("--task", required=True)
    pi.add_argument("--model", required=True)
    pi.add_argument("--effort", required=True)
    pi.add_argument("--provider", required=True)
    pi.add_argument("--pi-package", type=Path)
    pi.add_argument("--auth-file", type=Path)
    pi.add_argument("--transport", type=Path, help="explicit routing-only JSON; never personal models.json")
    pi.add_argument("--output", type=Path, required=True, help="new private output directory")
    pi.add_argument("--study", type=Path, help="record next missing campaign slot; locks checkpoint for the whole trial")
    pi.add_argument("--replicate", type=int, default=0)
    pi.add_argument("--preflight", action="store_true", help="check isolation and exact selection without a model request")
    args = parser.parse_args(argv)
    try:
        if args.command == "pi-trial":
            from . import pi_runner
            if args.output.exists():
                raise ValueError("trial_output_already_exists")
            args.output.mkdir(parents=True, mode=0o700)
            with ExitStack() as stack:
                value = None
                route_hash = None
                if args.study:
                    from . import studies, campaign
                    stack.enter_context(studies.study_lock(args.study))
                    value = studies.load_json(args.study)
                    studies.validate(value, regrade=False)
                    pi_runner.require_profile(value)
                    job = campaign.coverage(value)['next_trial']
                    requested = (args.model, args.effort, args.replicate, args.task)
                    if job is None or campaign.identity(job) != requested:
                        raise ValueError("BLOCKED: execute the exact next missing campaign slot")
                    route_hash = pi_runner.bind_route(value, args.provider, args.transport)
                    studies.validate(value, regrade=False)
                    studies.save(args.study, value)
                result = pi_runner.run(args.task, args.model, args.effort, args.provider,
                    pi_package=args.pi_package, auth_file=args.auth_file, transport=args.transport, preflight=args.preflight, expected_transport_hash=route_hash, result_file=args.output/"receipt.json")
                # Persist the original result before grading; a grader outage must not cause reinference.
                (args.output/"receipt.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                (args.output/"receipt.json").chmod(0o600)
                if value is not None and not args.preflight and result['status'] in ('COMPLETED','TRANSPORT_ERROR'):
                    studies.add_record(value, args.task, args.model, args.effort,
                        result['answer'], result['tool_history'], args.replicate,
                        result['elapsed_seconds'], result['transport_error'])
                    studies.save(args.study, value)
            for name, value in [("answer.txt", result["answer"]),
                                ("history.json", json.dumps(result["tool_history"], ensure_ascii=False)),
                                ("receipt.json", json.dumps(result, ensure_ascii=False, indent=2))]:
                path = args.output/name
                path.write_text(value, encoding="utf-8"); path.chmod(0o600)
            emit({"status":result["status"], "profile":result["profile"], "profile_sha256":result["profile_sha256"],
                  "output":str(args.output), "blocker":result.get("blocker"),
                  "transport_error":result.get("transport_error"), "inference_started":result["inference_started"]})
            return 0 if result["status"] in ("COMPLETED","PREFLIGHT_PASS") else 1
        if args.command == "doctor":
            from .sandbox import doctor
            emit(doctor(args.prepare))
            return 0
        if args.command == "campaign":
            from . import campaign, studies
            if args.action == "plan":
                config, jobs = campaign.plan(args.profile)
                emit({"configuration": config, "planned_trials": len(jobs),
                      "primary_trials": sum(j['phase'] == 'primary' for j in jobs),
                      "pilot_trials": sum(j['phase'] == 'pilot' for j in jobs),
                      "control_trials": sum(j['phase'] == 'controls' for j in jobs),
                      "next": "Execute all configured models/efforts through your model interfaces; CLI inspection does not run inference."})
                return 0
            value = studies.load_json(args.file)
            studies.validate(value, regrade=False)
            result = campaign.coverage(value)
            if args.action == "next":
                job = result["next_trial"]
                if job:
                    tasks, _, _ = load()
                    emit({"trial": job, "task": next(task for task in tasks if task["id"] == job["task_id"]),
                          "note": "Invoke the exact requested model and effort; do not answer using the orchestrator model."})
                else:
                    emit(result)
                return 0
            emit(result)
            return 0 if result["full_protocol_complete"] else 1
        if args.command == "study":
            from . import studies
            if args.action == "create":
                with studies.study_lock(args.file):
                    if args.file.exists():
                        raise ValueError("study_file_already_exists")
                    value = studies.create(args.id, args.access_route, args.environment, args.campaign_profile)
                    if args.execution_profile:
                        from .pi_runner import mark_study
                        mark_study(value)
                    studies.validate(value, regrade=False)
                    studies.save(args.file, value)
                emit({"created": str(args.file), "records": 0})
            elif args.action == "record":
                history = studies.load_json(args.history) if args.history else []
                answer = args.answer.read_text(encoding="utf-8-sig")
                with studies.study_lock(args.file):
                    value = studies.load_json(args.file)
                    studies.validate(value, regrade=False)
                    studies.add_record(value, args.task, args.model, args.effort, answer, history,
                        args.replicate, args.seconds, args.transport_error, args.attempt, args.started_at)
                    studies.save(args.file, value)
                emit(studies.validate(value, regrade=False))
            elif args.action == "validate":
                emit(studies.validate(studies.load_json(args.file)))
            else:
                emit(studies.publish(args.file, args.publish, args.gh))
            return 0
        if args.command == "stats":
            import csv
            from . import studies
            report = studies.statistics_report(args.directory.glob("*/study.json"))
            if args.output:
                studies.save(args.output, report)
                fields = ["model", "effort", "access_route", "environment", "grader_sha256", "regraded_with_sha256",
                          "studies", "runs", "task_results", "median_pass_rate", "mean_pass_rate",
                          "min_pass_rate", "max_pass_rate", "transport_errors"]
                with args.output.with_suffix(".csv").open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
                    writer.writeheader()
                    def csv_value(value):
                        # Preserve raw metadata in JSON, but prevent spreadsheet
                        # applications from executing contributor text as formulas.
                        if isinstance(value, str) and (value.startswith(('\t', '\r', '\n'))
                                or value.lstrip().startswith(('=', '+', '-', '@'))):
                            return "'"+value
                        return value
                    writer.writerows({key: csv_value(value) for key, value in group.items()}
                                     for group in report["groups"])
            emit(report)
            return 0
        if args.command == "verify":
            emit(verify())
            return 0
        tasks, answers, _ = load()
        if args.command == "list":
            for task in tasks:
                if not args.family or task["family"] == args.family:
                    print("{id}\t{family}\t{difficulty}\t{title}".format(**task))
            return 0
        task = next((task for task in tasks if task["id"] == args.task), None)
        if task is None:
            raise ValueError("unknown_task: " + args.task)
        if args.command == "show":
            emit(task)
            return 0
        if args.command == "lookup":
            if task["family"] != "tools":
                raise ValueError("lookup_only_available_for_tools_tasks")
            emit(answers[task["id"]]["catalog"][args.id])
            return 0
        history = json.loads(args.history.read_text(encoding="utf-8-sig")) if args.history else []
        if not isinstance(history, list):
            raise ValueError("history_must_be_an_array")
        result = grade(task, args.answer.read_text(encoding="utf-8-sig"), answers[task["id"]], history)
        emit(result)
        return 0 if result["semantic_pass"] else 1
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        report = {"error": str(error)}
        if args.command == 'doctor':
            report['status'] = 'BLOCKED'
            if sys.platform == 'darwin':
                report['next_step'] = (
                    'Do not start model requests. If permitted, run this command in ordinary Terminal: '
                    'python3 -m teobench doctor --prepare. It uses native Seatbelt first; '
                    'if denied, it prepares the pinned image in an already running local Docker Linux engine. '
                    'If both are unavailable, retain answers and use another authorized grading host. '
                    'See docs/SETUP.md. No host security changes are needed.')
        emit(report)
        return 2
