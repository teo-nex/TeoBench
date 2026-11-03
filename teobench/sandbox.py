"""OS-specific, fail-closed execution. Windows uses existing Linux Docker."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

# Official multi-architecture Python image, resolved from Docker Hub on 2026-11-04.
# Never mount the checkout, home, Docker socket, or any host directory into it.
WINDOWS_IMAGE = 'python@sha256:94a8fee35252d06ab75856f15f12c7bae67b10e8a6da93c7fded82b2610926cd'


def windows_command(script):
    docker = shutil.which('docker')
    if not docker:
        raise RuntimeError('OS_sandbox_unavailable_start_Docker_Desktop_Linux_containers_then_doctor_prepare')
    return [docker, 'run', '--rm', '-i', '--pull=never', '--name', 'teobench-'+uuid.uuid4().hex,
            '--network=none', '--read-only', '--user=65534:65534', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--pids-limit=16', '--memory=256m',
            '--memory-swap=256m', '--cpus=1', '--ulimit=cpu=2:2', '--ulimit=nofile=32:32',
            '--ulimit=fsize=0:0', '--ipc=none', '--workdir=/', WINDOWS_IMAGE,
            'python', '-I', '-S', '-c', script]


def run_command(command, payload=None, timeout=5):
    docker = '--pull=never' in command and WINDOWS_IMAGE in command
    # Docker CLI needs its normal Windows environment to reach the existing engine.
    # It does NOT forward that environment to the container (no --env flags).
    environment = None if docker else {'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}
    try:
        result = subprocess.run(command, input=payload, capture_output=True, text=True,
                                encoding='utf-8', timeout=timeout if not docker else max(timeout, 30),
                                cwd=Path.home().anchor if docker else '/', env=environment)
    except subprocess.TimeoutExpired:
        if docker:
            # Killing docker.exe alone does not terminate its daemon-side container.
            name = command[command.index('--name')+1]
            subprocess.run([command[0], 'rm', '-f', name], capture_output=True, timeout=15)
        raise
    if docker and result.returncode == 125:
        raise RuntimeError('OS_sandbox_unavailable_Docker_run_failed_run_doctor_prepare')
    return result


def doctor(prepare=False):
    from .evaluate import ROOT, sandbox_command
    backend = ('macos-seatbelt' if sys.platform == 'darwin' else
               'linux-bubblewrap' if sys.platform.startswith('linux') else
               'windows-docker-linux' if sys.platform == 'win32' else 'unsupported')
    if prepare and sys.platform == 'win32':
        docker = shutil.which('docker')
        if not docker:
            raise RuntimeError('OS_sandbox_unavailable_install_and_start_Docker_Desktop_Linux_containers')
        info = subprocess.run([docker, 'info', '--format', '{{.OSType}}'], capture_output=True,
                              text=True, encoding='utf-8', timeout=30)
        if info.returncode or info.stdout.strip() != 'linux':
            raise RuntimeError('OS_sandbox_unavailable_Docker_Linux_engine_required')
        pulled = subprocess.run([docker, 'pull', WINDOWS_IMAGE], capture_output=True,
                                text=True, encoding='utf-8', timeout=300)
        if pulled.returncode and 'error getting credentials' in pulled.stderr.lower():
            # Windows SSH sessions may not unlock Docker Desktop's credential
            # helper. This image is public: use an ephemeral anonymous config
            # against the EXACT same local named-pipe daemon. Never edit the
            # user's config, extract credentials, or change contexts/engines.
            endpoint = subprocess.run([docker, 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}'],
                                      capture_output=True, text=True, encoding='utf-8', timeout=15)
            host = endpoint.stdout.strip()
            if endpoint.returncode or not host.startswith('npipe://'):
                raise RuntimeError('OS_sandbox_unavailable_Docker_credentials_require_interactive_session')
            with tempfile.TemporaryDirectory(prefix='teobench-public-image-') as directory:
                # A registry entry prevents Docker auto-detecting wincred again.
                Path(directory, 'config.json').write_text('{"auths":{"https://index.docker.io/v1/":{}}}', encoding='utf-8')
                environment = dict(os.environ)
                environment.pop('DOCKER_CONTEXT', None)
                pulled = subprocess.run([docker, '--config', directory, '--host', host, 'pull', WINDOWS_IMAGE],
                                        capture_output=True, text=True, encoding='utf-8', timeout=300, env=environment)
        if pulled.returncode:
            raise RuntimeError('OS_sandbox_unavailable_pinned_Docker_image_pull_failed')
    # Execute arbitrary trusted probe code, bypassing the candidate AST filter:
    # test the actual OS boundary, not just Python's restricted builtins.
    paths = [str(Path.home()/'.teobench-private-probe'), str(ROOT.parent/'Easy-Bench/tasks/answers.json')]
    script = '''import json, os, socket
checks = []
for path in PATHS:
    try:
        open(path).read()
        checks.append(False)
    except (PermissionError, FileNotFoundError):
        checks.append(True)
try:
    open('/teobench-write-probe', 'w').close()
    checks.append(False)
except OSError:
    checks.append(True)
try:
    socket.create_connection(('192.0.2.1', 9), timeout=0.3)
    checks.append(False)
except OSError:
    checks.append(True)
checks.append('TEOBENCH_PRIVATE_PROBE' not in os.environ)
print(json.dumps(checks))
'''.replace('PATHS', repr(paths))
    import json
    old = os.environ.get('TEOBENCH_PRIVATE_PROBE')
    try:
        os.environ['TEOBENCH_PRIVATE_PROBE'] = 'local-doctor-marker'
        result = run_command(sandbox_command(script))
    finally:
        if old is None:
            os.environ.pop('TEOBENCH_PRIVATE_PROBE', None)
        else:
            os.environ['TEOBENCH_PRIVATE_PROBE'] = old
    if result.returncode or json.loads(result.stdout) != [True]*5:
        raise RuntimeError('OS_sandbox_unavailable_boundary_probe_failed')
    from .evaluate import python_outputs
    if python_outputs('def solve(x): return sum(x)', [[1, 2, 3]]) != [6]:
        raise RuntimeError('OS_sandbox_unavailable_worker_probe_failed')
    return {'status': 'PASS', 'platform': sys.platform, 'backend': backend,
            'python': '.'.join(map(str, sys.version_info[:3])),
            'sandbox_probe': 'PASS', 'model_access': 'NOT_CHECKED',
            'windows_image': WINDOWS_IMAGE if sys.platform == 'win32' else None}
