import copy
import json
from pathlib import Path
import tempfile
import unittest

from teobench import medium
from teobench.medium_pi_smoke import transport


class SelectionTests(unittest.TestCase):
    def rows(self):
        return [dict(id=f'{group}-{n}',stratum=group) for group in 'abc' for n in range(8)]

    def test_selection_is_independent_of_input_order(self):
        rows=self.rows()
        self.assertEqual(medium.select(rows,11,'fixture'),
                         medium.select(list(reversed(rows)),11,'fixture'))

    def test_strata_balanced_before_repeating(self):
        chosen=medium.select(self.rows(),8,'fixture')
        counts=medium.Counter(row['stratum'] for row in chosen)
        self.assertLessEqual(max(counts.values())-min(counts.values()),1)
        self.assertEqual(len({r['id'] for r in chosen}),8)

    def test_shared_workbook_variants_are_not_independent_tasks(self):
        rows=self.rows()
        for row in rows:row['family_key']=row['id'].split('-')[0]
        chosen=medium.select(rows,3,'fixture')
        self.assertEqual(len({r['family_key'] for r in chosen}),3)
        with self.assertRaisesRegex(ValueError,'insufficient_distinct_tasks'):
            medium.select(rows,4,'fixture')

    def test_duplicate_source_ids_are_rejected(self):
        rows=self.rows()
        with self.assertRaisesRegex(ValueError,'duplicate_source_id'):
            medium.select(rows+[rows[0]],3,'fixture')


class ManifestTests(unittest.TestCase):
    def manifest(self):
        return medium.verify()

    def check_mutation(self,mutate,expected,rehash=True):
        m=copy.deepcopy(self.manifest());mutate(m)
        if rehash:m['sha256']=medium.digest({k:v for k,v in m.items() if k!='sha256'})
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'manifest.json';path.write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError,expected):medium.verify(path)

    def test_frozen_matrix_and_selection_do_not_imply_runtime_acceptance(self):
        plan=medium.plan()
        self.assertEqual(plan['primary_attempts'],3500)
        self.assertEqual(plan['status'],'SELECTION_FROZEN_NOT_RUNTIME_ACCEPTED')
        self.assertFalse(plan['transport_probes_are_benchmark_results'])
        self.assertTrue(plan['blockers'])

    def test_corrupt_manifest_is_rejected(self):
        self.check_mutation(lambda m:m['tasks'][0].update(id='tampered'),
                            'medium_manifest_hash_mismatch',rehash=False)

    def test_answers_cannot_be_added_to_selection_metadata(self):
        self.check_mutation(lambda m:m['tasks'][0].update(patch='reference'),
                            'medium_manifest_contains_task_content')

    def test_dropping_a_model_cannot_make_a_reduced_campaign_complete(self):
        self.check_mutation(lambda m:m['models'].pop(),'medium_matrix_mismatch')

    def test_same_swe_repo_and_commit_cannot_be_double_counted(self):
        def mutate(m):
            rows=[r for r in m['tasks'] if r['source'].startswith('swe-')]
            rows[1].update(repo=rows[0]['repo'],base_commit=rows[0]['base_commit'])
        self.check_mutation(mutate,'medium_duplicate_swe_commit')


class TransportTests(unittest.TestCase):
    def value(self):
        return {'base_url':'http://localhost:20128/v1','api':'openai-responses',
                'model_routes':{m:'codex/'+m for m in medium.MODELS}}

    def load(self,value,key_env='TEOBENCH_GATEWAY_KEY'):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'routing.json';path.write_text(json.dumps(value))
            return transport(path,key_env)

    def test_explicit_prefix_routes_preserve_exact_models(self):
        self.assertEqual(self.load(self.value()),self.value())

    def test_url_credentials_cannot_enter_routing(self):
        value=self.value();value['base_url']='http://secret:password@localhost/v1'
        with self.assertRaisesRegex(ValueError,'invalid_transport_url'):self.load(value)

    def test_route_must_not_substitute_model(self):
        value=self.value();value['model_routes'][medium.MODELS[0]]='codex/another-model'
        with self.assertRaisesRegex(ValueError,'model_route_substitution_forbidden'):self.load(value)

    def test_command_credential_resolver_is_not_supported(self):
        with self.assertRaisesRegex(ValueError,'invalid_credential_variable_name'):
            self.load(self.value(),'!read-secret')

    def test_no_literal_secret_field_in_routing(self):
        value=self.value();value['api_key']='do-not-store-keys'
        with self.assertRaisesRegex(ValueError,'transport_requires'):self.load(value)

    def test_malformed_nested_route_is_rejected(self):
        value=self.value();value['model_routes'][medium.MODELS[0]]={}
        with self.assertRaisesRegex(ValueError,'all_seven'):self.load(value)


if __name__=='__main__':unittest.main()
