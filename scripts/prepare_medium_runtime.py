"""Materialize pinned evaluator assets; never expose this directory to a model.

Downloads selected Terminal/Pro tasks, official BIRD evaluator and spreadsheet
recalculation/comparison code. Does not execute upstream code or run inference.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from teobench.medium import verify, digest

HARNESS_PINS = {
    'swe-pro': ('scaleapi/SWE-bench_Pro-os', '66f92766bba642462d4bbe5479e83f91f9211862'),
    'bird': ('harbor-framework/harbor', '981a4b246aef3c68b3d1b5aa27cecb703692b1f9'),
}


def safe_relative(value):
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or any(p in ('..', '.') for p in path.parts)
            or '\\' in value or ':' in value):
        raise ValueError('unsafe_upstream_path')
    return path


def download(url, path, *, limit=32_000_000, blob=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        data = path.read_bytes()
    else:
        with urllib.request.urlopen(url, timeout=90) as response:
            data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('upstream_asset_size_limit')
        part = path.with_suffix(path.suffix + '.part')
        part.write_bytes(data)
        part.replace(path)
    if blob and hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != blob:
        raise ValueError('upstream_git_blob_mismatch')
    return data


def prepare(output):
    manifest = verify()
    output = Path(output)
    selected = {}
    for source in ('terminal', 'swe-pro'):
        if source == 'terminal':
            pin = manifest['source_pins'][source]
            repo = pin['repository'].removeprefix('https://github.com/')
            revision = pin['revision']
        else:
            repo, revision = HARNESS_PINS[source]
        tree = json.loads(download(f'https://api.github.com/repos/{repo}/git/trees/{revision}?recursive=1',
                                   output/'metadata'/(source+'-tree.json'), limit=12_000_000))
        if tree.get('truncated') or tree.get('sha') != revision:
            raise ValueError('incomplete_or_unpinned_upstream_tree')
        wanted = {t['id'] for t in manifest['tasks'] if t['source'] == source}
        prefix = 'tasks/' if source == 'terminal' else 'v2/tasks/'
        entries = []
        for entry in tree['tree']:
            if entry['type'] != 'blob' or not entry['path'].startswith(prefix):
                continue
            relative = entry['path'][len(prefix):]
            task_id, separator, member = relative.partition('/')
            if not separator or task_id not in wanted:
                continue
            safe_relative(member)
            if entry.get('mode') not in ('100644', '100755'):
                raise ValueError('upstream_symlink_or_special_file')
            entries.append((entry, task_id, member))
        def fetch_task(item):
            entry, task_id, member = item
            path = output/source/task_id/member
            data = download(f'https://raw.githubusercontent.com/{repo}/{revision}/{entry["path"]}',
                            path, blob=entry['sha'])
            if data.startswith(b'version https://git-lfs.github.com/spec/v1'):
                raise ValueError('git_lfs_asset_requires_verified_materialization')
            return {'source': source, 'task_id': task_id, 'member': member,
                    'git_blob': entry['sha'], 'sha256': hashlib.sha256(data).hexdigest()}
        with ThreadPoolExecutor(6) as pool:
            selected[source] = list(pool.map(fetch_task, entries))
        for task_id in wanted:
            base = output/source/task_id
            for member in ('instruction.md', 'task.toml', 'environment/Dockerfile', 'tests/test.sh', 'solution/solve.sh'):
                if not (base/member).is_file():
                    raise ValueError('required_task_asset_missing: '+source+'/'+task_id+'/'+member)
            if source == 'terminal':
                task = next(t for t in manifest['tasks'] if t['source'] == source and t['id'] == task_id)
                if hashlib.sha256((base/'task.toml').read_bytes()).hexdigest() != task['task_config_sha256']:
                    raise ValueError('frozen_terminal_config_mismatch')
                if digest({'instruction': (base/'instruction.md').read_text()}) != task['public_input_sha256']:
                    raise ValueError('frozen_terminal_instruction_mismatch')
    evaluators = {
        'bird/evaluate.py': (*HARNESS_PINS['bird'], 'adapters/bird_bench/src/bird_bench/task-template/tests/evaluate.py'),
        'spreadsheet/evaluation.py': ('RUCKBReasoning/SpreadsheetBench-2', manifest['source_pins']['spreadsheet']['grader_revision'], 'evaluation/evaluation.py'),
        'spreadsheet/open_spreadsheet.py': ('RUCKBReasoning/SpreadsheetBench-2', manifest['source_pins']['spreadsheet']['grader_revision'], 'evaluation/open_spreadsheet.py'),
    }
    hashes = {}
    for name, (repo, revision, path) in evaluators.items():
        data = download(f'https://raw.githubusercontent.com/{repo}/{revision}/{path}', output/'evaluators'/name)
        hashes[name] = hashlib.sha256(data).hexdigest()
    record = {'schema_version': 'medium-evaluator-assets-1', 'status': 'ASSETS_DOWNLOADED_NOT_RUNTIME_ACCEPTED',
              'manifest_sha256': manifest['sha256'], 'harness_pins': HARNESS_PINS,
              'task_files': selected, 'evaluator_sha256': hashes, 'model_requests': 0}
    record['sha256'] = digest(record)
    (output/'assets.json').write_text(json.dumps(record, indent=2)+'\n')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.output)
    print(json.dumps({'status': result['status'], 'files': sum(map(len, result['task_files'].values())),
                      'sha256': result['sha256'], 'model_requests': 0}))
