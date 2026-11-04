"""Run trusted base-branch code; fetch PR data as JSON, never execute PR code."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from teobench.studies import MAX_BYTES, load_json, save, validate
from teobench.campaign import require_complete


def api(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request("https://api.github.com/"+path, headers={
        "Accept": "application/vnd.github+json", "Authorization": "Bearer "+os.environ["GH_TOKEN"],
        "X-GitHub-Api-Version": "2022-11-28", "Content-Type":"application/json"}, data=data)
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(12_000_001)
        if len(data) > 12_000_000:
            raise ValueError("api_response_too_large")
        return json.loads(data)


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    number = os.environ.get("PR_NUMBER", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("invalid_repository_or_pr_number")
    run_id = os.environ.get("SOURCE_RUN_ID")
    if run_id:
        if not run_id.isdigit():
            raise ValueError("invalid_source_run_id")
        run = api("repos/"+repo+"/actions/runs/"+run_id)
        if run["event"] != "pull_request" or run["name"] != "Check Easy benchmark":
            raise ValueError("unexpected_source_workflow")
        candidates = run.get("pull_requests", [])
        if not candidates:
            candidates = api("repos/"+repo+"/commits/"+run["head_sha"]+"/pulls")
        matches = []
        for item in candidates:
            pull = api("repos/"+repo+"/pulls/"+str(item["number"]))
            if pull["state"] == "open" and pull["head"]["sha"] == run["head_sha"]:
                matches.append(str(pull["number"]))
        if not matches:
            print(json.dumps({"status":"SKIP","reason":"No open PR at this workflow head; possibly superseded"}))
            return
        if len(matches) != 1:
            raise ValueError("ambiguous_source_pr")
        number = matches[0]
    if not number.isdigit():
        raise ValueError("invalid_pr_number")
    pull = api("repos/"+repo+"/pulls/"+number)
    head = pull["head"]["sha"]
    context = os.environ.get("STATUS_CONTEXT")
    def status(state, description):
        if context:
            api("repos/"+repo+"/statuses/"+head, {"state":state,"context":context,
                "description":description,"target_url":"https://github.com/"+repo+"/actions/runs/"+os.environ["GITHUB_RUN_ID"]})
    status("pending", "Trusted grader is validating study JSON")
    try:
        reports = validate_files(repo, number)
        # A late update cannot receive a verdict for the old head.
        if api("repos/"+repo+"/pulls/"+number)["head"]["sha"] != head:
            raise ValueError("pr_head_changed_during_validation")
        status("success", "Study JSON and benchmark answers verified" if reports else "No study files in this PR")
        print(json.dumps({"status":"PASS","studies":reports,"PR_code_executed":False}, indent=2))
    except Exception:
        status("failure", "Study validation failed; see trusted workflow logs")
        raise


def validate_files(repo, number):
    files = []
    for page in range(1, 32):
        batch = api("repos/"+repo+"/pulls/"+number+"/files?per_page=100&page="+str(page))
        files.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise ValueError("too_many_changed_files")
    data_files = [f for f in files if f["filename"].startswith("Easy-Bench/studies/")]
    if data_files and len(data_files) != len(files):
        raise ValueError("study_submission_must_only_add_study_json_files; submit_code_changes_separately")
    reports=[]
    for file in data_files:
        match = re.fullmatch(r"Easy-Bench/studies/([a-z0-9][a-z0-9-]{2,79})/study\.json", file["filename"])
        if not match or file["status"] not in {"added", "modified"}:
            raise ValueError("study_PR_must_add_or_update_a_study_json_file")
        if file["status"] != "added":
            raise ValueError("accepted_studies_are_immutable_submit_a_new_study_id")
        blob = api("repos/"+repo+"/git/blobs/"+file["sha"])
        if blob["size"] > MAX_BYTES or blob["encoding"] != "base64":
            raise ValueError("invalid_study_blob")
        payload = base64.b64decode(blob["content"])
        if len(payload) != blob["size"] or len(payload) > MAX_BYTES:
            raise ValueError("blob_size_mismatch")
        git_sha = hashlib.sha1(b"blob "+str(len(payload)).encode()+b"\0"+payload).hexdigest()
        if git_sha != file["sha"]:
            raise ValueError("blob_hash_mismatch")
        # Temp data never lives at a contributor-controlled path.
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"study.json"
            path.write_bytes(payload)
            value = load_json(path)
            if value["study_id"] != match[1]:
                raise ValueError("study_id_directory_mismatch")
            validate(value, regrade=False)
            # validate() permits only explicitly reviewed source/target grader pairs.
            # Full coverage and current regrading are mandatory below.
            campaign = require_complete(value)
            report = validate(value)
            report["campaign"] = campaign
            if not report["records"]:
                raise ValueError("empty_study")
            reports.append(report)
    return reports


if __name__ == "__main__":
    main()
