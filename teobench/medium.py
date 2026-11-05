"""Frozen public-source Medium selection, separate from the Easy study schema.

Selection is not runtime acceptance. This module deliberately cannot report a
campaign COMPLETE without task adapters and independent verifier acceptance.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / 'Medium-Bench' / 'manifest.json'
SEED = 'teobench-medium-v1-20261105'
QUOTAS = {'terminal': 25, 'swe-pro': 25, 'swe-verified': 20, 'bird': 15, 'spreadsheet': 15}
MODELS = ['gpt-5.6-luna', 'gpt-6-luna', 'gpt-5.6-terra', 'gpt-6.1-terra',
          'gpt-5.6-sol', 'gpt-6.1-sol', 'gpt-6-astra']
EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max']


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def select(rows, count, source):
    """Round-robin strata, then fixed hash rank. Never inspect model scores.

    A family key prevents selecting near-duplicate spreadsheet variants that
    share a golden workbook. No runtime failure may silently replace a task.
    """
    rank = lambda value: hashlib.sha256((SEED+'\0'+source+'\0'+value).encode()).hexdigest()
    groups = defaultdict(list)
    seen = set()
    for row in rows:
        if row['id'] in seen:
            raise ValueError('duplicate_source_id')
        seen.add(row['id'])
        groups[row['stratum']].append(row)
    for group in groups.values():
        group.sort(key=lambda row: rank(row['id']))
    strata = sorted(groups, key=rank)
    chosen, families = [], set()
    while len(chosen) < count:
        progress = False
        for stratum in strata:
            group = groups[stratum]
            while group:
                row = group.pop(0)
                family = row.get('family_key', row['id'])
                if family in families:
                    continue
                chosen.append(row)
                families.add(family)
                progress = True
                break
            if len(chosen) == count:
                break
        if not progress:
            raise ValueError('insufficient_distinct_tasks')
    return chosen


def verify(path=MANIFEST):
    manifest = json.loads(Path(path).read_text(encoding='utf-8'))
    payload = {k:v for k,v in manifest.items() if k != 'sha256'}
    if digest(payload) != manifest.get('sha256'):
        raise ValueError('medium_manifest_hash_mismatch')
    tasks = manifest['tasks']
    if dict(Counter(t['source'] for t in tasks)) != QUOTAS:
        raise ValueError('medium_quota_mismatch')
    identities = [(t['source'],t['id']) for t in tasks]
    if len(set(identities)) != 100:
        raise ValueError('medium_duplicate_task')
    if manifest['models'] != MODELS or manifest['efforts'] != EFFORTS:
        raise ValueError('medium_matrix_mismatch')
    commits = [(t['repo'].casefold(), t['base_commit']) for t in tasks
               if t['source'] in ('swe-pro','swe-verified')]
    if len(set(commits)) != len(commits):
        raise ValueError('medium_duplicate_swe_commit')
    for task in tasks:
        if any(k in task for k in ('patch','test_patch','SQL','golden_response','answer','instruction')):
            raise ValueError('medium_manifest_contains_task_content')
        for field in ['public_input_sha256','source_record_sha256']:
            value = task[field]
            if len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('invalid_input_digest')
    return manifest


def plan(path=MANIFEST):
    m = verify(path)
    return {'status':'SELECTION_FROZEN_NOT_RUNTIME_ACCEPTED',
            'manifest_sha256':m['sha256'], 'tasks':100, 'quotas':QUOTAS,
            'models':MODELS, 'efforts':EFFORTS, 'primary_attempts':3500,
            'execution_supported':False,
            'execution_profile':'pi-medium-sandbox-v1 (task adapters pending acceptance)',
            'blockers':['medium_task_adapters_not_accepted',
                        'oracle_and_negative_verifier_checks_not_run',
                        'container_capacity_not_accepted'],
            'transport_probes_are_benchmark_results':False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['verify','plan'])
    parser.add_argument('--manifest',type=Path,default=MANIFEST)
    args = parser.parse_args(argv)
    result = plan(args.manifest) if args.action == 'plan' else {
        'status':'MANIFEST_INTEGRITY_PASS','tasks':len(verify(args.manifest)['tasks']),
        'runtime_accepted':False}
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
