"""Portable CLI, UTF-8, sandbox policy and daemon-side timeout cleanup."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from teobench import studies
from teobench.cli import ROOT
from teobench.sandbox import WINDOWS_IMAGE, run_command, windows_command, doctor


class PortabilityTests(unittest.TestCase):
    def test_windows_container_has_no_host_mounts_and_bounded_resources(self):
        with patch('teobench.sandbox.shutil.which', return_value='docker.exe'):
            command = windows_command('print(42)')
        for option in ['--pull=never', '--network=none', '--read-only', '--user=65534:65534',
                       '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=16',
                       '--memory=256m', '--memory-swap=256m', '--ulimit=cpu=2:2']:
            self.assertIn(option, command)
        self.assertIn(WINDOWS_IMAGE, command)
        self.assertFalse(any(x in command for x in ['-v', '--volume', '--mount', '--privileged', '--env']))
        self.assertEqual(command[-5:], ['python', '-I', '-S', '-c', 'print(42)'])

    def test_public_image_prepare_preserves_user_docker_credentials(self):
        calls = []
        temporary_config = []
        def fake(command, **kwargs):
            calls.append(command)
            if 'info' in command:
                return subprocess.CompletedProcess(command, 0, 'linux\n', '')
            if 'context' in command:
                return subprocess.CompletedProcess(command, 0, 'npipe:////./pipe/dockerDesktopLinuxEngine\n', '')
            if '--config' in command:
                directory = Path(command[command.index('--config')+1])
                temporary_config.append(directory)
                config = json.loads((directory/'config.json').read_text(encoding='utf-8'))
                self.assertEqual(config, {'auths': {'https://index.docker.io/v1/': {}}})
                self.assertIn('npipe:////./pipe/dockerDesktopLinuxEngine', command)
                return subprocess.CompletedProcess(command, 0, '', '')
            return subprocess.CompletedProcess(command, 1, '', 'error getting credentials: logon session unavailable')
        with patch('teobench.sandbox.sys.platform', 'win32'), patch('teobench.sandbox.shutil.which', return_value='docker.exe'), patch('teobench.sandbox.subprocess.run', side_effect=fake), patch('teobench.sandbox.run_command', return_value=subprocess.CompletedProcess([], 0, '[true,true,true,true,true]', '')), patch('teobench.evaluate.python_outputs', return_value=[6]):
            self.assertEqual(doctor(prepare=True)['status'], 'PASS')
        self.assertEqual(len(calls), 4)
        self.assertFalse(temporary_config[0].exists())

    def test_missing_docker_never_executes_candidate(self):
        with patch('teobench.sandbox.shutil.which', return_value=None), self.assertRaisesRegex(RuntimeError, 'OS_sandbox_unavailable'):
            windows_command('print(42)')

    def test_daemon_container_removed_when_client_times_out(self):
        with patch('teobench.sandbox.shutil.which', return_value='docker.exe'):
            command = windows_command('while True: pass')
        failure = subprocess.TimeoutExpired(command, 30)
        with patch('teobench.sandbox.subprocess.run', side_effect=[failure, subprocess.CompletedProcess([], 0)]) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                run_command(command)
        self.assertEqual(run.call_args_list[1].args[0], ['docker.exe', 'rm', '-f', command[command.index('--name')+1]])

    def test_docker_engine_or_missing_image_is_infrastructure_failure(self):
        with patch('teobench.sandbox.shutil.which', return_value='docker.exe'):
            command = windows_command('print(42)')
        with patch('teobench.sandbox.subprocess.run', return_value=subprocess.CompletedProcess([], 125, '', '')):
            with self.assertRaisesRegex(RuntimeError, 'OS_sandbox_unavailable'):
                run_command(command)

    def test_utf8_report_roundtrip_and_portable_cli(self):
        value = studies.create('portable-utf8', 'test-route', 'Windows; UTF-8 тест 日本語')
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'study.json'
            studies.save(target, value)
            self.assertEqual(json.loads(target.read_bytes().decode('utf-8')), value)
            self.assertNotIn(b'\r\n', target.read_bytes())
            self.assertEqual(studies.load_json(target), value)
        result = subprocess.run([sys.executable, '-m', 'teobench', 'campaign', 'plan'],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['planned_trials'], 1127)

    def test_historical_grader_is_preserved_but_unknown_hash_rejected(self):
        path = ROOT/'Easy-Bench/studies/2026-11-03-reasoning-effort/study.json'
        value = studies.load_json(path)
        original = value['benchmark']['grader_sha256']
        self.assertEqual(studies.validate(value, regrade=False)['records'], 1050)
        self.assertEqual(value['benchmark']['grader_sha256'], original)
        with self.assertRaisesRegex(ValueError, 'historical_study_is_read_only'):
            studies.add_record(value, 'R01', 'test-model', 'high', '{}', [])
        value['benchmark']['grader_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'version_mismatch'):
            studies.validate(value, regrade=False)

    def test_windows_private_home_paths_rejected(self):
        for path in ['C:\\Users\\private-person\\study.json', 'D:\\Users\\private-person\\secret.txt']:
            with self.assertRaisesRegex(ValueError, 'private_home_path'):
                studies.reject_secrets({'environment': path})


if __name__ == '__main__':
    unittest.main()
