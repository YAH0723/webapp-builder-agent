"""Regressions for conflicting shared writes and malformed API design output."""
from copy import deepcopy
import importlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.agent.discovery import ContextIndex
from infrastructure.shared.agent.proposals import ProposalCallBudgetExceeded, ProposalStagnation, propose_json
from infrastructure.stages.backend.coordination import (APIDesignRecovery, APIResponseError,
    compatibility, validate_response, validate_endpoints)
from infrastructure.stages.backend.primitives import apply_decomposition, validate_design
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.shared.agent.tasks import StageIncomplete
from infrastructure.utils.files import read_artifact


def api(writes, path='/api/records', method='POST'):
    obj = {'type': 'object'}
    return {'description': 'Apply the operation supported by the requirement', 'read': [], 'write': writes,
        'signature': {'name': 'operate', 'method': method, 'path': path},
        'request': {key: deepcopy(obj) for key in ('params', 'query', 'body', 'headers')},
        'response': {'success': {'status': 200, 'body': deepcopy(obj), 'headers': deepcopy(obj)}, 'errors': []},
        'precondition': [], 'postcondition': []}


def fixture():
    tree = RequirementTree({'id': 'ROOT', 'children': [
        {'id': 'CREATE', 'name': 'Create a record', 'description': 'Initialize both stored fields'},
        {'id': 'UPDATE', 'name': 'Update a record', 'description': 'Change value while preserving metadata'}]})
    schema = {'entities': {'Record': {'description': 'Record', 'fields': {
        key: {'description': key, 'type': 'string'} for key in ('value', 'metadata')}}}}
    obligations = {'requirements': {'ROOT': {'read': [], 'write': []},
        'CREATE': {'read': [], 'write': ['Record.metadata', 'Record.value']},
        'UPDATE': {'read': [], 'write': ['Record.value']}}, 'steps': {}}
    design = {'apis': {'WRITE': api(['Record.metadata', 'Record.value'])},
        'requirements': {'ROOT': [], 'CREATE': ['WRITE']}}
    return tree, schema, obligations, design


class APICoordination(unittest.TestCase):
    def setUp(self):
        self.stage = importlib.import_module('06_design_backend_apis')
        self.profile = patch.dict('os.environ', {'ARC_AGENT_PROFILE': 'b2'}, clear=True)
        self.profile.start()
        self.addCleanup(self.profile.stop)

    def run_stage(self, generate, directory, max_attempts=10):
        tree, schema, obligations, _ = fixture()
        with patch.object(self.stage, 'load_context', return_value=(tree, schema, obligations)), \
                patch.object(self.stage, 'TextModel', return_value=Mock(generate_json=generate)), \
                patch.object(self.stage, 'DemoConsole', return_value=Mock()):
            return self.stage.design_backend_apis(Path(directory), max_attempts=max_attempts)

    def test_conflict_recovery_preserves_shared_contract_and_designs_compatible_operation(self):
        requests = []
        tree, _, obligations, original = fixture()

        def generate(instructions, payload):
            requests.append(deepcopy(payload))
            if payload['requirement']['id'] == 'CREATE':
                return {'apis': deepcopy(original['apis']), 'requirement_apis': ['WRITE']}
            self.assertFalse(payload['api_compatibility']['WRITE']['fits_current_write_boundary'])
            if 'correction' not in payload:
                return {'apis': {'WRITE': api(['Record.value'])}, 'requirement_apis': ['WRITE']}
            context = payload['correction']['repair_context']
            self.assertEqual(set(context['affected_requirements']), {'CREATE', 'UPDATE'})
            self.assertEqual(context['affected_requirements']['CREATE']['obligations']['write'], ['Record.metadata', 'Record.value'])
            self.assertIn('preserving metadata', context['affected_requirements']['UPDATE']['source']['description'])
            return {'apis': {'UPDATE-VALUE': api(['Record.value'], '/api/records/:id', 'PATCH')},
                'requirement_apis': ['UPDATE-VALUE']}

        with TemporaryDirectory() as directory:
            result = self.run_stage(generate, directory)
            self.assertEqual(result, read_artifact(Path(directory), 'backend_apis.json'))
        validate_design(result, obligations, tree=tree)
        self.assertEqual(len(requests), 3)
        self.assertEqual(result['apis']['WRITE'], original['apis']['WRITE'])
        self.assertEqual(result['requirements']['UPDATE'], ['UPDATE-VALUE'])

    def test_missing_root_keys_receive_contract_and_repair_without_guessed_associations(self):
        requests = []
        def generate(instructions, payload):
            requests.append(deepcopy(payload))
            rid = payload['requirement']['id']
            writes = ['Record.metadata', 'Record.value'] if rid == 'CREATE' else ['Record.value']
            aid = 'WRITE' if rid == 'CREATE' else 'UPDATE-VALUE'
            result = {'apis': {aid: api(writes, '/api/' + aid.lower())}, 'requirement_apis': [aid]}
            if len(requests) == 1:
                return {'apis': result['apis']}
            if rid == 'CREATE':
                self.assertIn('requirement_apis', payload['correction']['error'])
                self.assertIn('requirement_apis', payload['correction']['repair_context']['result_contract']['required_top_level'])
            return result
        with TemporaryDirectory() as directory:
            self.run_stage(generate, directory)
        self.assertEqual(len(requests), 3)

    def test_repeated_malformed_output_replans_then_stops_and_preserves_neighbor(self):
        requests = []
        def generate(instructions, payload):
            requests.append(deepcopy(payload))
            if payload['requirement']['id'] == 'CREATE':
                return {'apis': {}, 'conventions': {'rejected-only': 'Must not be persisted'}}
            return {'apis': {'UPDATE-VALUE': api(['Record.value'], '/api/records/:id', 'PATCH')},
                'requirement_apis': ['UPDATE-VALUE']}
        with TemporaryDirectory() as directory:
            with self.assertRaises(StageIncomplete) as failure:
                self.run_stage(generate, directory)
            saved = read_artifact(Path(directory), 'backend_apis.json')
            conventions = read_artifact(Path(directory), 'shared_conventions.json')
        self.assertEqual(len(requests), 4)  # Three failed proposals, then the neighboring task.
        self.assertEqual(requests[2]['correction']['recovery_mode'], 'replan_from_accepted_contracts')
        self.assertNotIn('previous_response', requests[2]['correction'])
        self.assertNotIn('CREATE', saved['requirements'])
        self.assertNotIn('rejected-only', conventions)
        self.assertIn('UPDATE', saved['requirements'])
        self.assertEqual(failure.exception.failures[0]['error_type'], 'ProposalStagnation')

    def test_alternating_coverage_failures_are_bounded_without_relaxing_writes(self):
        tree, _, obligations, design = fixture()
        responses = [
            {'apis': {'WRITE': api(['Record.value'])}, 'requirement_apis': ['WRITE']},
            {'apis': {}, 'requirement_apis': ['WRITE']}]
        requests = []
        def generate(instructions, payload):
            requests.append(deepcopy(payload))
            return deepcopy(responses[(len(requests) - 1) % 2])
        before = deepcopy(design)
        with self.assertRaises(ProposalStagnation):
            propose_json(Mock(generate_json=generate), '', {},
                lambda response: apply_decomposition(design, response, 'UPDATE', obligations, tree),
                Mock(), 'Alternating', 6, repair_policy=APIDesignRecovery(design, obligations, tree, 'UPDATE'), call_limit=8)
        self.assertEqual(len(requests), 5)
        self.assertEqual(design, before)
        self.assertEqual(requests[3]['correction']['recovery_mode'], 'replan_from_accepted_contracts')

    def test_targeted_replan_can_recover_on_third_proposal(self):
        tree, _, obligations, design = fixture()
        responses = [{'apis': {}}, {'apis': {}}, {'apis': {}, 'requirement_apis': ['WRITE']}]
        requests = []
        def generate(instructions, payload):
            requests.append(deepcopy(payload))
            return responses[len(requests) - 1]
        def accept(response):
            validate_response(response, design)
            return apply_decomposition(design, response, 'CREATE', obligations, tree)
        result, _ = propose_json(Mock(generate_json=generate), '', {}, accept, Mock(), 'Recover', 6,
            repair_policy=APIDesignRecovery(design, obligations, tree, 'CREATE'), call_limit=8)
        self.assertEqual(len(requests), 3)
        self.assertEqual(result, design)
        self.assertNotIn('previous_response', requests[2]['correction'])

    def test_unknown_api_reference_lists_actual_accepted_ids(self):
        *_, design = fixture()
        with self.assertRaises(APIResponseError) as failure:
            validate_response({'apis': {}, 'requirement_apis': ['TYPO']}, design)
        self.assertEqual(failure.exception.feedback['unknown_api_ids'], ['TYPO'])
        self.assertEqual(failure.exception.feedback['accepted_api_ids'], ['WRITE'])

    def test_incomplete_or_invalid_new_api_is_rejected_before_artifact_merge(self):
        *_, design = fixture()
        before = deepcopy(design)
        for bad in ({'description': 'partial'}, {**api([]), 'write': 'Record.value'},
                {**api([]), 'response': {'success': {}, 'errors': []}}):
            with self.subTest(bad=bad), self.assertRaises((KeyError, APIResponseError)):
                validate_response({'apis': {'NEW': bad}, 'requirement_apis': ['NEW']}, design)
        self.assertEqual(design, before)

    def test_new_api_id_cannot_disguise_same_endpoint_with_different_effects(self):
        *_, design = fixture()
        design['apis']['ALIAS'] = api(['Record.value'])
        with self.assertRaisesRegex(APIResponseError, 'share one method/path'):
            validate_endpoints(design)

    def test_compatible_shared_updates_are_still_allowed(self):
        tree, _, obligations, design = fixture()
        changed = deepcopy(design['apis']['WRITE'])
        changed['description'] = 'Clarified shared behavior'
        validate_response({'apis': {'WRITE': changed}, 'requirement_apis': ['WRITE']}, design)
        updated = apply_decomposition(design, {'apis': {'WRITE': changed}, 'requirement_apis': ['WRITE']}, 'CREATE', obligations, tree)
        validate_endpoints(updated)
        self.assertEqual(updated['apis']['WRITE']['description'], changed['description'])

    def test_compatibility_does_not_mutate_canonical_design(self):
        _, _, obligations, design = fixture()
        info = compatibility(design, obligations, 'UPDATE', ['WRITE'])
        info['WRITE']['accepted_write_fields'].clear()
        self.assertEqual(len(design['apis']['WRITE']['write']), 2)

    def test_api_specific_call_budget_includes_discovery(self):
        model = Mock(generate_json=Mock(side_effect=[{'context_request': {'kind': 'api', 'ids': [str(i)]}} for i in range(9)]))
        with self.assertRaises(ProposalCallBudgetExceeded):
            propose_json(model, '', {}, Mock(), Mock(), 'Budget', 6,
                context_index=ContextIndex({'api': {str(i): {} for i in range(9)}}), call_limit=8)
        self.assertEqual(model.generate_json.call_count, 8)

    def test_old_profile_does_not_apply_api_recovery(self):
        calls = []
        def generate(instructions, payload):
            calls.append(deepcopy(payload))
            self.assertNotIn('result_contract', payload)
            return {}
        with TemporaryDirectory() as directory, patch.dict('os.environ', {'ARC_AGENT_PROFILE': 'b1'}, clear=True):
            with self.assertRaises(StageIncomplete):
                self.run_stage(generate, directory, max_attempts=4)
        self.assertEqual(len(calls), 8)  # Two tasks use their explicit old four-attempt budget.


if __name__ == '__main__':
    unittest.main()
