import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from teobench.medium_campaign import Campaign
from teobench.medium_container import ContainerError


class CampaignGateTests(unittest.TestCase):
    def test_blocked_readiness_never_opens_auth_journal_or_model(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign=Campaign.__new__(Campaign);campaign.out=Path(directory)
            expected={'status':'BLOCKED','blockers':['host_disk_reserve_reached'],'model_requests':0}
            campaign.check=lambda:expected
            with patch('teobench.medium_campaign.CodexQuotaGuard') as auth, \
                 patch('teobench.medium_campaign.Journal') as journal, \
                 patch('teobench.medium_campaign.run_agent') as model:
                self.assertEqual(campaign.run(),expected)
                auth.assert_not_called();journal.assert_not_called();model.assert_not_called()
            self.assertEqual(json.loads((campaign.out/'readiness.json').read_text()),expected)
            self.assertFalse((campaign.out/'controller.lock').exists())

    def test_reserve_guard_stops_inference_without_destroying_anything(self):
        campaign=Campaign.__new__(Campaign);campaign.out=Path('.')
        campaign.docker=SimpleNamespace(reserve_bytes=12*1024**3)
        with patch('teobench.medium_campaign.shutil.disk_usage',return_value=SimpleNamespace(free=11*1024**3)):
            with self.assertRaisesRegex(ContainerError,'no_further_inference'):campaign.enforce_disk_reserve()

    def test_existing_controller_lock_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign=Campaign.__new__(Campaign);campaign.out=Path(directory)
            lock=campaign.out/'controller.lock';lock.write_text('other-controller')
            with self.assertRaisesRegex(ValueError,'verify_owner'):
                with campaign.lock():self.fail('must not enter')
            self.assertEqual(lock.read_text(),'other-controller')
