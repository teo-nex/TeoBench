"""Exercise infrastructure selection and timeout cleanup without a Docker daemon."""

import subprocess
import unittest
from unittest.mock import patch

from teobench.evaluate import DOCKER_IMAGE, docker_run, sandbox_run


class DockerSandboxTests(unittest.TestCase):
    def setUp(self):
        platform = patch('teobench.evaluate.sys.platform', 'linux')
        platform.start()
        self.addCleanup(platform.stop)

    def test_setup_failure_uses_isolated_docker_but_worker_failure_does_not(self):
        failure = subprocess.CompletedProcess([], 1, '', 'bwrap: namespace denied')
        success = subprocess.CompletedProcess([], 0, 'ok', '')
        with patch.dict('os.environ', {'TEOBENCH_PYTHON_SANDBOX': 'auto'}), \
                patch('teobench.evaluate.sys.platform', 'linux'), \
                patch('teobench.evaluate.sandbox_command', return_value=['bwrap']), \
                patch('teobench.evaluate.subprocess.run', return_value=failure), \
                patch('teobench.evaluate.docker_run', return_value=success) as docker:
            self.assertIs(sandbox_run('script', input='request'), success)
            docker.assert_called_once_with('script', input='request', timeout=5)
            docker.reset_mock()
            failure.stderr = 'candidate failed'
            self.assertIs(sandbox_run('script'), failure)
            docker.assert_not_called()

    def test_bubblewrap_timeout_does_not_retry_candidate(self):
        with patch.dict('os.environ', {'TEOBENCH_PYTHON_SANDBOX': 'auto'}), \
                patch('teobench.evaluate.sys.platform', 'linux'), \
                patch('teobench.evaluate.sandbox_command', return_value=['bwrap']), \
                patch('teobench.evaluate.subprocess.run', side_effect=subprocess.TimeoutExpired('bwrap', 5)), \
                patch('teobench.evaluate.docker_run') as docker:
            with self.assertRaises(subprocess.TimeoutExpired):
                sandbox_run('script')
            docker.assert_not_called()

    def test_missing_or_forbidden_backends_fail_closed(self):
        with patch('teobench.evaluate.shutil.which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'OS_sandbox_unavailable'):
                docker_run('script')
        with patch.dict('os.environ', {'TEOBENCH_PYTHON_SANDBOX': 'unconfined'}):
            with self.assertRaisesRegex(RuntimeError, 'unknown_backend'):
                sandbox_run('script')
        with patch.dict('os.environ', {'TEOBENCH_PYTHON_SANDBOX': 'bubblewrap'}), \
                patch('teobench.evaluate.sys.platform', 'linux'), \
                patch('teobench.evaluate.sandbox_command', side_effect=RuntimeError('OS_sandbox_unavailable')), \
                patch('teobench.evaluate.docker_run') as docker:
            with self.assertRaisesRegex(RuntimeError, 'OS_sandbox_unavailable'):
                sandbox_run('script')
            docker.assert_not_called()

    def test_docker_command_is_local_pinned_and_restricted(self):
        success = subprocess.CompletedProcess([], 0, 'ok', '')
        with patch('teobench.evaluate.shutil.which', return_value='/usr/bin/docker'), \
                patch('teobench.evaluate.subprocess.run', return_value=success) as run:
            self.assertIs(docker_run('print(1)', input='request'), success)
        create, start, remove = run.call_args_list
        command = create.args[0]
        self.assertEqual(command[:3], ['/usr/bin/docker', '--host=unix:///var/run/docker.sock', 'create'])
        for flag in ['--pull=never', '--network=none', '--ipc=none', '--read-only',
                     '--cap-drop=ALL', '--security-opt=no-new-privileges=true',
                     '--user=65534:65534', '--pids-limit=16', '--memory=128m']:
            self.assertIn(flag, command)
        self.assertEqual(command[-5:], [DOCKER_IMAGE, '-I', '-S', '-c', 'print(1)'])
        self.assertFalse(any(arg.startswith(('--volume', '--mount', '--privileged')) for arg in command))
        self.assertEqual(start.kwargs['input'], 'request')
        name = command[command.index('--name') + 1]
        self.assertEqual(start.args[0][-1], name)
        self.assertEqual(remove.args[0][-3:], ['rm', '--force', name])
        self.assertNotIn('HOME', create.kwargs['env'])

    def test_docker_timeout_force_removes_only_its_own_container(self):
        success = subprocess.CompletedProcess([], 0, '', '')
        with patch('teobench.evaluate.shutil.which', return_value='/usr/bin/docker'), \
                patch('teobench.evaluate.subprocess.run',
                      side_effect=[success, subprocess.TimeoutExpired('docker', 5), success]) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                docker_run('while True: pass')
        create, start, remove = run.call_args_list
        name = create.args[0][create.args[0].index('--name') + 1]
        self.assertEqual(start.args[0][-1], name)
        self.assertEqual(remove.args[0][-3:], ['rm', '--force', name])

    def test_missing_image_never_downloads_or_runs_worker(self):
        failure = subprocess.CompletedProcess([], 1, '', 'image unavailable')
        with patch('teobench.evaluate.shutil.which', return_value='/usr/bin/docker'), \
                patch('teobench.evaluate.subprocess.run', return_value=failure) as run:
            with self.assertRaisesRegex(RuntimeError, 'OS_sandbox_unavailable_docker_create_failed'):
                docker_run('script')
        self.assertEqual(run.call_count, 2)  # create, then cleanup; never start/pull
        self.assertEqual(run.call_args_list[1].args[0][-3:-1], ['rm', '--force'])


if __name__ == '__main__':
    unittest.main()
