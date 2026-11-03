"""OS-specific, fail-closed execution. Windows uses existing Linux Docker."""
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

# Official multi-architecture Python image, resolved from Docker Hub on 2026-11-04.
# Never mount the checkout, home, Docker socket, or any host directory into it.
WINDOWS_IMAGE = 'python@sha256:94a8fee35252d06ab75856f15f12c7bae67b10e8a6da93c7fded82b2610926cd'


def local_docker_client():
    docker = shutil.which('docker')
    if not docker:
        raise RuntimeError('OS_sandbox_unavailable_start_Docker_Desktop_Linux_containers_then_doctor_prepare')
    context = os.environ.get('DOCKER_CONTEXT')
    host = os.environ.get('DOCKER_HOST') if not context else None
    if not host:
        command = [docker, 'context', 'inspect'] + ([context] if context else [])
        endpoint = subprocess.run(command+['--format', '{{.Endpoints.docker.Host}}'],
                                  capture_output=True, text=True, encoding='utf-8', timeout=15)
        if endpoint.returncode:
            raise RuntimeError('OS_sandbox_unavailable_Docker_local_endpoint_required')
        host = endpoint.stdout.strip()
    if sys.platform == 'darwin':
        # Desktop's socket can live under ~/.docker/run rather than /var/run.
        # Never send candidate data to TCP/SSH or a unix URI with an authority.
        if not re.fullmatch(r'unix:///[^\x00-\x20?#]+', host):
            raise RuntimeError('OS_sandbox_unavailable_Docker_local_unix_socket_required')
    elif not re.fullmatch(r'npipe:////\./pipe/[A-Za-z0-9_.-]+', host):
        raise RuntimeError('OS_sandbox_unavailable_Docker_local_named_pipe_required')
    return [docker, '--host', host]


def docker_environment():
    environment = dict(os.environ)
    environment.pop('DOCKER_CONTEXT', None)
    environment.pop('DOCKER_HOST', None)
    return environment


def windows_command(script):
    return local_docker_client()+['run', '--rm', '-i', '--pull=never', '--name', 'teobench-'+uuid.uuid4().hex,
            '--network=none', '--read-only', '--user=65534:65534', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--pids-limit=16', '--memory=256m',
            '--memory-swap=256m', '--cpus=1', '--ulimit=cpu=2:2', '--ulimit=nofile=32:32',
            '--ulimit=fsize=0:0', '--ipc=none', '--workdir=/', WINDOWS_IMAGE,
            'python', '-I', '-S', '-c', script]


def run_command(command, payload=None, timeout=5):
    docker = '--pull=never' in command and WINDOWS_IMAGE in command
    # Docker CLI needs its normal Windows environment to reach the existing engine.
    # It does NOT forward that environment to the container (no --env flags).
    environment = docker_environment() if docker else {'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}
    try:
        result = subprocess.run(command, input=payload, capture_output=True, text=True,
                                encoding='utf-8', timeout=timeout if not docker else max(timeout, 30),
                                cwd=Path.home().anchor if docker else '/', env=environment)
    except subprocess.TimeoutExpired:
        if docker:
            # Killing docker.exe alone does not terminate its daemon-side container.
            name = command[command.index('--name')+1]
            subprocess.run(command[:command.index('run')]+['rm', '-f', name],
                           capture_output=True, timeout=15, env=environment)
        raise
    if docker and result.returncode in {125, 126, 127}:
        raise RuntimeError('OS_sandbox_unavailable_Docker_run_failed_run_doctor_prepare')
    return result


def prepare_docker_image(image):
    """Explicit preparation only; neither grading nor auto fallback pulls."""
    client = local_docker_client()
    environment = docker_environment()
    info = subprocess.run(client+['info', '--format', '{{.OSType}}'], capture_output=True,
                          text=True, encoding='utf-8', timeout=30, env=environment)
    if info.returncode or info.stdout.strip() != 'linux':
        raise RuntimeError('OS_sandbox_unavailable_Docker_Linux_engine_required')
    pulled = subprocess.run(client+['pull', image], capture_output=True,
                            text=True, encoding='utf-8', timeout=300, env=environment)
    if pulled.returncode and 'error getting credentials' in pulled.stderr.lower():
        # Public image only: use the same pinned daemon without editing the
        # user's config or extracting credentials from a locked keychain.
        with tempfile.TemporaryDirectory(prefix='teobench-public-image-') as directory:
            Path(directory, 'config.json').write_text('{"auths":{"https://index.docker.io/v1/":{}}}', encoding='utf-8')
            pulled = subprocess.run(client+['--config', directory, 'pull', image],
                                    capture_output=True, text=True, encoding='utf-8', timeout=300, env=environment)
    if pulled.returncode:
        raise RuntimeError('OS_sandbox_unavailable_pinned_Docker_image_pull_failed')


def doctor(prepare=False):
    from .evaluate import ROOT, DOCKER_IMAGE, sandbox_run
    backend = ('macos-seatbelt' if sys.platform == 'darwin' else
               'linux-bubblewrap' if sys.platform.startswith('linux') else
               'windows-docker-linux' if sys.platform == 'win32' else 'unsupported')
    if prepare and sys.platform == 'win32':
        prepare_docker_image(WINDOWS_IMAGE)
    elif prepare and sys.platform == 'darwin':
        requested = os.environ.get('TEOBENCH_PYTHON_SANDBOX', 'auto')
        if requested == 'docker':
            prepare_docker_image(DOCKER_IMAGE)
        elif requested == 'auto':
            try:
                sandbox_run('pass', backend='seatbelt')
            except RuntimeError as error:
                if not str(error).startswith('OS_sandbox_unavailable'):
                    raise
                prepare_docker_image(DOCKER_IMAGE)
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
        result = sandbox_run(script)
        backend = getattr(result, "sandbox_backend", backend)
    finally:
        if old is None:
            os.environ.pop('TEOBENCH_PRIVATE_PROBE', None)
        else:
            os.environ['TEOBENCH_PRIVATE_PROBE'] = old
    if result.returncode or json.loads(result.stdout) != [True]*5:
        raise RuntimeError('OS_sandbox_unavailable_boundary_probe_failed')
    from .evaluate import python_outputs, sql_outputs
    if python_outputs('def solve(x): return sum(x)', [[1, 2, 3]]) != [6]:
        raise RuntimeError('OS_sandbox_unavailable_worker_probe_failed')
    if sql_outputs('SELECT 6', {'tables': {}}) != [[6]]:
        raise RuntimeError('OS_sandbox_unavailable_sql_worker_probe_failed')
    return {'status': 'PASS', 'platform': sys.platform, 'backend': backend,
            'python': '.'.join(map(str, sys.version_info[:3])),
            'sandbox_probe': 'PASS', 'sql_probe': 'PASS', 'model_access': 'NOT_CHECKED',
            'windows_image': WINDOWS_IMAGE if sys.platform == 'win32' else None}
