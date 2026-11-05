"""Trusted subprocess bridge to the unmodified, pinned SWE-bench 4.1.0 API."""
import dataclasses
import importlib.machinery
import importlib.metadata
import json
from pathlib import Path
import sys
import types


def load_pinned_api():
    distribution=importlib.metadata.distribution('swebench')
    if distribution.version!='4.1.0':raise RuntimeError('pinned_swebench_4_1_0_required')
    # Upstream's package aggregators eagerly import Unix-only image-building
    # commands (resource) even when only generating a test script on Windows.
    # Load the original API modules through namespaces, without executing those
    # unrelated command aggregators. No evaluator or parser source is patched,
    # and no fake resource module or platform emulation is installed.
    for name in ('swebench','swebench.harness'):
        module=types.ModuleType(name)
        module.__path__=[str(distribution.locate_file(name.replace('.','/')))]
        module.__package__=name
        module.__spec__=importlib.machinery.ModuleSpec(name,loader=None,is_package=True)
        module.__spec__.submodule_search_locations=module.__path__
        sys.modules[name]=module


def main():
    load_pinned_api()
    from swebench.harness.test_spec.test_spec import make_test_spec, TestSpec
    from swebench.harness.grading import get_eval_report
    request=json.load(sys.stdin)
    if request['action']=='spec':
        spec=make_test_spec(request['row'],namespace='swebench',arch='x86_64')
        result={'spec':dataclasses.asdict(spec),'image':spec.instance_image_key,'eval_script':spec.eval_script}
    elif request['action']=='grade':
        spec=TestSpec(**request['spec'])
        result=get_eval_report(spec,request['prediction'],Path(request['log_path']),include_tests_status=True)
    else:raise ValueError('unknown_trusted_swe_action')
    print(json.dumps(result))


if __name__=='__main__':main()
