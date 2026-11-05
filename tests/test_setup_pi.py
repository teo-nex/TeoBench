import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from teobench import setup_pi


class SetupTests(unittest.TestCase):
    def test_missing_pi_is_not_implicitly_installed(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('teobench.setup_pi.shutil.which',return_value='/trusted/node'), \
             patch('teobench.setup_pi.subprocess.run',side_effect=AssertionError('no installer')):
            with self.assertRaisesRegex(ValueError,'explicit --install'):
                setup_pi.setup(prefix=directory)

    def test_existing_different_version_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'node_modules/@earendil-works/pi-coding-agent';p.mkdir(parents=True)
            meta=p/'package.json';meta.write_text(json.dumps({'name':setup_pi.PACKAGE,'version':'9.9.9'}))
            before=meta.read_bytes()
            with patch('teobench.setup_pi.shutil.which',return_value='/trusted/node'):
                with self.assertRaisesRegex(ValueError,'different installed Pi version'):
                    setup_pi.setup(prefix=directory,install=True)
            self.assertEqual(meta.read_bytes(),before)

    def test_setup_child_does_not_inherit_hooks_or_credentials(self):
        env=setup_pi.node_environment({'PATH':'/bin','HOME':'/home/test','NODE_OPTIONS':'--import evil',
                                      'OPENAI_API_KEY':'secret','NPM_TOKEN':'secret','CODEX_HOME':'private'})
        self.assertEqual(env,{'PATH':'/bin','HOME':'/home/test'})

    def test_native_stderr_warning_does_not_turn_exit_zero_into_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            def native(*args,**kwargs):
                kwargs['stdout'].write('0.85.1\n');kwargs['stderr'].write('npm warning\n')
                return subprocess.CompletedProcess(args[0],0)
            with patch('teobench.setup_pi.subprocess.run',side_effect=native):
                self.assertEqual(setup_pi.native(['node'],Path(directory),'version',{}),'0.85.1')

    def test_native_exit_failure_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('teobench.setup_pi.subprocess.run',return_value=subprocess.CompletedProcess([],7)):
            with self.assertRaisesRegex(ValueError,'exit 7'):
                setup_pi.native(['node'],Path(directory),'version',{})


if __name__=='__main__':unittest.main()
