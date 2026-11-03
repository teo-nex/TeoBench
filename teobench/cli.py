"""Offline commands. No provider, credentials, model calls or network required."""

import argparse
import collections
import hashlib
import importlib.util
import json
from pathlib import Path

from .evaluate import grade

ROOT = Path(__file__).resolve().parent.parent
EASY = ROOT / "Easy-Bench" / "tasks"


def load():
    manifest = json.loads((EASY / "manifest.json").read_text())
    for name, key in [("tasks.jsonl", "public_sha256"), ("answers.json", "sealed_sha256")]:
        if hashlib.sha256((EASY / name).read_bytes()).hexdigest() != manifest[key]:
            raise ValueError("dataset_hash_mismatch: " + name)
    tasks = [json.loads(line) for line in (EASY / "tasks.jsonl").read_text().splitlines()]
    return tasks, json.loads((EASY / "answers.json").read_text()), manifest


def verify():
    tasks, answers, manifest = load()
    spec = importlib.util.spec_from_file_location("original_generator", EASY / "source" / "dataset.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    generated_tasks, generated_answers = module.build()
    if generated_tasks != tasks or generated_answers != answers:
        raise ValueError("generator_does_not_reproduce_frozen_dataset")
    receipt = json.loads((EASY / "PROVENANCE.json").read_text())
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
    parser = argparse.ArgumentParser(description="TeoBench Easy — offline benchmark inspection and grading")
    sub = parser.add_subparsers(dest="command", required=True)
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
    for action in ["validate", "submit"]:
        command = actions.add_parser(action)
        command.add_argument("--file", type=Path, required=True)
        if action == "submit":
            command.add_argument("--publish", action="store_true", help="explicit consent to create a public PR")
            command.add_argument("--gh", help="path to an authenticated GitHub CLI")
    campaign = sub.add_parser("campaign", help="plan and check the FULL 7-model x 5-effort study")
    campaign_actions = campaign.add_subparsers(dest="action", required=True)
    campaign_actions.add_parser("plan")
    for action in ["status", "next"]:
        command = campaign_actions.add_parser(action)
        command.add_argument("--file", type=Path, required=True)
    stats = sub.add_parser("stats", help="regrade accepted studies and aggregate complete runs")
    stats.add_argument("--directory", type=Path, default=ROOT / "Easy-Bench" / "studies")
    stats.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "campaign":
            from . import campaign, studies
            if args.action == "plan":
                config, jobs = campaign.plan()
                emit({"configuration": config, "planned_trials": len(jobs),
                      "primary_trials": 1050, "pilot_trials": 35, "control_trials": 42,
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
                if args.file.exists():
                    raise ValueError("study_file_already_exists")
                value = studies.create(args.id, args.access_route, args.environment)
                studies.save(args.file, value)
                emit({"created": str(args.file), "records": 0})
            elif args.action == "record":
                value = studies.load_json(args.file)
                studies.validate(value, regrade=False)
                history = studies.load_json(args.history) if args.history else []
                studies.add_record(value, args.task, args.model, args.effort, args.answer.read_text(), history,
                    args.replicate, args.seconds, args.transport_error)
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
                with args.output.with_suffix(".csv").open("w", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(report["groups"])
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
        history = json.loads(args.history.read_text()) if args.history else []
        if not isinstance(history, list):
            raise ValueError("history_must_be_an_array")
        result = grade(task, args.answer.read_text(), answers[task["id"]], history)
        emit(result)
        return 0 if result["semantic_pass"] else 1
    except (ValueError, KeyError, OSError) as error:
        emit({"error": str(error)})
        return 2
