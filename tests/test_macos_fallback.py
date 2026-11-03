"""macOS setup failures select another local sandbox, never retry an answer."""
import os
import contextlib
import io
import json
import subprocess
import unittest
from unittest.mock import patch

from teobench.evaluate import DOCKER_IMAGE, docker_run, sandbox_run
from teobench.sandbox import doctor, local_docker_client


class MacOSFallbackTests(unittest.TestCase):
    def setUp(self):
        platform = patch('teobench.evaluate.sys.platform', 'darwin')
        platform.start()
        self.addCleanup(platform.stop)
        env = patch.dict(os.environ, {'TEOBENCH_PYTHON_SANDBOX': 'auto'})
        env.start()
        self.addCleanup(env.stop)

    def test_seatbelt_setup_denial_selects_docker(self):
        denied = subprocess.CompletedProcess([], 71, '', 'sandbox-exec: sandbox_apply: Operation not permitted')
        ok = subprocess.CompletedProcess([], 0, 'ok', '')
        with patch('teobench.evaluate.sandbox_command', return_value=['sandbox-exec']), \
                patch('teobench.evaluate.subprocess.run', return_value=denied), \
                patch('teobench.evaluate.docker_run', return_value=ok) as docker:
            self.assertIs(sandbox_run('worker', input='answer'), ok)
            docker.assert_called_once_with('worker', input='answer', timeout=5)

    def test_candidate_failure_and_timeout_are_never_retried(self):
        with patch('teobench.evaluate.sandbox_command', return_value=['sandbox-exec']), \
                patch('teobench.evaluate.subprocess.run') as run, \
                patch('teobench.evaluate.docker_run') as docker:
            failed = subprocess.CompletedProcess([], 1, '', 'candidate failed')
            run.return_value = failed
            self.assertIs(sandbox_run('worker'), failed)
            run.side_effect = subprocess.TimeoutExpired('sandbox-exec', 5)
            with self.assertRaises(subprocess.TimeoutExpired):
                sandbox_run('worker')
            docker.assert_not_called()

    def test_missing_seatbelt_selects_docker(self):
        with patch('teobench.evaluate.sandbox_command', side_effect=RuntimeError('OS_sandbox_unavailable')), \
                patch('teobench.evaluate.docker_run') as docker:
            sandbox_run('worker')
            docker.assert_called_once()

    def test_desktop_context_local_unix_endpoint_is_pinned(self):
        with patch.dict(os.environ, {'DOCKER_CONTEXT': 'desktop-linux', 'DOCKER_HOST': 'tcp://remote:2375'}), \
                patch('teobench.sandbox.shutil.which', return_value='/usr/local/bin/docker'), \
                patch('teobench.sandbox.subprocess.run', return_value=subprocess.CompletedProcess(
                    [], 0, 'unix:///Users/example/.docker/run/docker.sock\n', '')) as run:
            client = local_docker_client()
            self.assertEqual(client[-2:], ['--host', 'unix:///Users/example/.docker/run/docker.sock'])
            self.assertIn('desktop-linux', run.call_args.args[0])

    def test_remote_and_malformed_endpoints_rejected_before_execution(self):
        for host in ['tcp://remote:2375', 'ssh://host', 'unix://remote/path', 'unix:///tmp/socket?remote=1']:
            with self.subTest(host=host), patch.dict(os.environ, {'DOCKER_CONTEXT': '', 'DOCKER_HOST': host}), \
                    patch('teobench.sandbox.shutil.which', return_value='docker'), \
                    patch('teobench.sandbox.subprocess.run') as run:
                with self.assertRaisesRegex(RuntimeError, 'local_unix_socket_required'):
                    local_docker_client()
                run.assert_not_called()

    def test_macos_container_keeps_limits_and_endpoint_for_cleanup(self):
        ok = subprocess.CompletedProcess([], 0, 'ok', '')
        client = ['docker', '--host', 'unix:///tmp/local-docker.sock']
        with patch('teobench.sandbox.local_docker_client', return_value=client), \
                patch('teobench.evaluate.subprocess.run', return_value=ok) as run:
            self.assertEqual(docker_run('worker', input='answer').sandbox_backend, 'macos-docker')
        create, start, cleanup = run.call_args_list
        for call in [create, start, cleanup]:
            self.assertEqual(call.args[0][:3], client)
            self.assertNotIn('DOCKER_CONTEXT', call.kwargs['env'])
            self.assertNotIn('DOCKER_HOST', call.kwargs['env'])
        for flag in ['--pull=never', '--network=none', '--read-only', '--memory=128m']:
            self.assertIn(flag, create.args[0])
        self.assertIn(DOCKER_IMAGE, create.args[0])

    def test_prepare_does_not_require_docker_when_native_sandbox_works(self):
        ok = subprocess.CompletedProcess([], 0, '[true,true,true,true,true]', '')
        with patch('teobench.evaluate.sandbox_run', return_value=ok), \
                patch('teobench.evaluate.python_outputs', return_value=[6]), \
                patch('teobench.evaluate.sql_outputs', return_value=[[6]]), \
                patch('teobench.sandbox.prepare_docker_image') as prepare:
            self.assertEqual(doctor(prepare=True)['status'], 'PASS')
            prepare.assert_not_called()

    def test_prepare_fetches_only_pinned_image_after_native_setup_failure(self):
        ok = subprocess.CompletedProcess([], 0, '[true,true,true,true,true]', '')
        ok.sandbox_backend = 'macos-docker'
        with patch('teobench.evaluate.sandbox_run', side_effect=[RuntimeError('OS_sandbox_unavailable'), ok]), \
                patch('teobench.evaluate.python_outputs', return_value=[6]), \
                patch('teobench.evaluate.sql_outputs', return_value=[[6]]), \
                patch('teobench.sandbox.prepare_docker_image') as prepare:
            self.assertEqual(doctor(prepare=True)['backend'], 'macos-docker')
            prepare.assert_called_once_with(DOCKER_IMAGE)

    def test_doctor_failure_explains_next_step_before_inference(self):
        from teobench.cli import main
        output = io.StringIO()
        with patch('teobench.sandbox.doctor', side_effect=RuntimeError('OS_sandbox_unavailable')), \
                contextlib.redirect_stdout(output):
            self.assertEqual(main(['doctor']), 2)
        report = json.loads(output.getvalue())
        self.assertEqual(report['status'], 'BLOCKED')
        self.assertIn('python3 -m teobench doctor --prepare', report['next_step'])

    def test_sql_runtime_probe_works_with_container_fallback(self):
        from teobench.evaluate import sql_runtime
        denied = subprocess.CompletedProcess([], 71, '', 'sandbox-exec: sandbox_apply: Operation not permitted')
        ok = subprocess.CompletedProcess([], 0, '', '')
        sql_runtime.cache_clear()
        self.addCleanup(sql_runtime.cache_clear)
        with patch('teobench.evaluate.sandbox_command', return_value=['sandbox-exec', '-p', 'profile', 'python', '-I', '-c', 'probe']), \
                patch('teobench.evaluate.subprocess.run', return_value=denied), \
                patch('teobench.evaluate.Path.is_file', return_value=True), \
                patch('teobench.evaluate.docker_run', return_value=ok) as docker:
            self.assertIsNotNone(sql_runtime())
            docker.assert_called_once()
