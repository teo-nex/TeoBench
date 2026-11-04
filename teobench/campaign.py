"""One authoritative full-study plan; no inference, credentials or network."""
import collections
import json
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / 'Easy-Bench' / 'campaign.json'
EXTENDED_PROFILE = 'codex-available-8x-v1'
EXTENDED_PATH = PATH.with_name('campaign-codex-available-8x-v1.json')


def plan(profile=None):
    if profile is None or profile == 'reasoning-effort-7x5-v1':
        path = PATH
    elif profile == EXTENDED_PROFILE:
        path = EXTENDED_PATH
    else:
        raise ValueError('unknown_campaign_profile')
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    jobs = []
    for phase in ['pilot', 'primary', 'controls']:
        stage = config[phase]
        for task in stage['task_ids']:
            for effort in stage.get('efforts', config['efforts']):
                for model in config['models']:
                    if effort not in config.get('efforts_by_model', {}).get(model, config['efforts']):
                        continue
                    for replicate in stage['replicates']:
                        jobs.append(dict(phase=phase, task_id=task, model=model, effort=effort, replicate=replicate))
    return config, jobs


def identity(row):
    return tuple(row[key] for key in ['model', 'effort', 'replicate', 'task_id'])


def coverage(study):
    config, jobs = plan(study.get('campaign_profile'))
    rows = study.get('records', [])
    observed = {identity(row) for row in rows}
    expected = {identity(job) for job in jobs}
    stages = {}
    for phase in ['pilot', 'primary', 'controls']:
        wanted = [job for job in jobs if job['phase'] == phase]
        missing = [job for job in wanted if identity(job) not in observed]
        stages[phase] = dict(expected=len(wanted), recorded=len(wanted)-len(missing), missing=len(missing))
    primary_complete = stages['primary']['missing'] == 0
    full_complete = all(stage['missing'] == 0 for stage in stages.values())
    conditions = {(j['model'], j['effort']) for j in jobs if j['phase'] == 'primary'}
    complete_conditions = sum(all((model, effort, 0, task) in observed for task in config['primary']['task_ids'])
                              for model, effort in conditions)
    return dict(profile=config['profile'], status='COMPLETE' if full_complete else 'PRIMARY_COMPLETE' if primary_complete else 'INCOMPLETE',
                primary_complete=primary_complete, full_protocol_complete=full_complete,
                expected_models=config['models'], expected_efforts=config['efforts'],
                complete_primary_conditions=complete_conditions, expected_primary_conditions=len(conditions),
                phases=stages, unexpected_results=len(observed-expected),
                next_trial=next((job for job in jobs if identity(job) not in observed), None),
                inference_executed_by_this_command=False)


def require_complete(study):
    result = coverage(study)
    if not result['full_protocol_complete'] or result['unexpected_results']:
        raise ValueError('incomplete_full_campaign: primary {}/{}, conditions {}/{}, pilot {}/{}, controls {}/{}; '
                         '30 tasks on one model/effort is NOT a full study. Run campaign status and resume missing trials.'.format(
                             result['phases']['primary']['recorded'], result['phases']['primary']['expected'],
                             result['complete_primary_conditions'], result['expected_primary_conditions'],
                             result['phases']['pilot']['recorded'], result['phases']['pilot']['expected'],
                             result['phases']['controls']['recorded'], result['phases']['controls']['expected']))
    return result
