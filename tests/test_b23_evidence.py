"""Failure observations remain evidence, never replacements for acceptance."""
import base64
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.agent.diagnostics import diagnostic_attachment, repair_evidence, feedback_without_diagnostic_duplicates
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.tools import FileTools
from infrastructure.stages.frontend.ui.testing import parse_playwright_result
from infrastructure.stages.frontend.triggers.e2e_runtime import prepare_e2e, FIXTURE, DIAGNOSTICS
from infrastructure.utils.files import save_json, save_text


def attachment(events):
    return {'name': 'arc-diagnostics', 'contentType': 'application/json',
        'body': base64.b64encode(json.dumps({'events': events}).encode()).decode()}


class DiagnosticEvidence(unittest.TestCase):
    def setUp(self):
        context = patch.dict('os.environ', {'ARC_AGENT_PROFILE': 'b2'}, clear=True)
        context.start()
        self.addCleanup(context.stop)

    def test_only_failed_cases_supply_observations_and_accepted_rejections_stay_green(self):
        report = {'suites': [{'file': 'failed.spec.ts', 'specs': [{'file': 'failed.spec.ts', 'tests': [
            {'results': [{'status': 'failed', 'errors': [{'message': 'Error: expected saved value'}],
                'attachments': [attachment([{'kind': 'http', 'method': 'POST', 'path': '/api/records', 'status': 500}])]}]}]}]},
            {'file': 'passed.spec.ts', 'specs': [{'file': 'passed.spec.ts', 'tests': [
                {'results': [{'status': 'passed', 'attachments': [attachment([{'kind': 'http', 'status': 400, 'path': '/api/reject'}])]}]}]}]}],
            'stats': {'expected': 1, 'unexpected': 1}}
        result = parse_playwright_result({'stdout': json.dumps(report), 'output': '', 'returncode': 1}, True)
        self.assertEqual(result['passed'], 1)
        self.assertEqual(result['failed'], 1)
        self.assertEqual(len(result['diagnostics']), 1)
        self.assertEqual(result['diagnostics'][0]['test_file'], 'failed.spec.ts')
        report['suites'] = report['suites'][1:]
        report['stats'] = {'expected': 1, 'unexpected': 0}
        green = parse_playwright_result({'stdout': json.dumps(report), 'output': '', 'returncode': 0})
        self.assertNotIn('diagnostics', green)
        self.assertEqual(green['returncode'], 0)

    def test_headers_payloads_queries_and_url_credentials_are_not_carried(self):
        result = diagnostic_attachment([attachment([{'kind': 'http', 'method': 'POST',
            'path': 'https://user:secret@example.com/api/records?token=private#secret', 'status': 500,
            'headers': {'Authorization': 'private'}, 'body': {'password': 'private'}},
            {'kind': 'runtime', 'message': 'Bearer private token=private at https://example.com/page?password=private'}])])
        encoded = json.dumps(result)
        self.assertNotIn('private', encoded)
        self.assertNotIn('headers', encoded)
        self.assertEqual(result[0]['path'], '/api/records')

    def test_attachment_files_cannot_read_outside_owned_test_results(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save_json(root / 'outside.json', {'events': [{'kind': 'runtime', 'message': 'outside'}]})
            item = {'name': 'arc-diagnostics', 'contentType': 'application/json', 'path': str(root / 'outside.json')}
            self.assertEqual(diagnostic_attachment([item], root), [])
            save_json(root / 'frontend/test-results/e2e/data.json', {'events': [{'kind': 'runtime', 'message': 'inside'}]})
            item['path'] = 'frontend/test-results/e2e/data.json'
            self.assertEqual(diagnostic_attachment([item], root)[0]['message'], 'inside')

    def test_oversized_invalid_and_unrelated_attachments_are_ignored(self):
        for item in ({'name': 'other', 'contentType': 'application/json', 'body': '{}'},
                {'name': 'arc-diagnostics', 'contentType': 'application/json', 'body': '!invalid!'},
                {'name': 'arc-diagnostics', 'contentType': 'application/json', 'body': 'a' * 90001}):
            self.assertEqual(diagnostic_attachment([item]), [])

    def test_contract_mapping_follows_observed_method_and_route_and_keeps_failure_status(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save_json(root / '.arc/backend_apis.json', {'apis': {'UPDATE': {'signature': {'method': 'PATCH', 'path': '/api/records/:id'}}}})
            save_json(root / '.arc/implementation_paths.json', {'api': {'UPDATE': 'backend/src/update.ts'}})
            save_text(root / 'backend/src/update.ts', 'export const update = true;')
            feedback = {'acceptance': {'returncode': 1, 'failed': 1, 'diagnostics': [{
                'test_file': 'failed.spec.ts', 'events': [{'kind': 'http', 'method': 'PATCH', 'path': '/api/records/42', 'status': 500}]}]}}
            before = deepcopy(feedback)
            result = repair_evidence(root, {'original_requirement': {'id': 'REQ'}}, feedback)
            self.assertEqual(result['related_api_ids'], ['UPDATE'])
            self.assertEqual(result['suggested_source_paths'], ['backend/src/update.ts'])
            self.assertEqual(result['requirement_ids'], ['REQ'])
            self.assertEqual(feedback, before)

    def test_implementation_agent_receives_evidence_and_linked_source(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save_text(root / 'frontend/src/App.tsx', 'export const App = true;')
            save_text(root / 'backend/src/update.ts', 'export const update = true;')
            feedback = {'returncode': 1, 'errors': ['Error: backend/src/update.ts(3,4): error TS2322: invalid type']}
            tools = FileTools(root, ['frontend/src/App.tsx'])
            def generate(instructions, payload):
                self.assertIn('repair_evidence', payload['task'])
                self.assertIn('backend/src/update.ts', payload['files'])
                return {'tool_calls': []}
            run_file_agent(Mock(generate_json=generate), '', {}, tools, lambda: {'status': 'GREEN'}, 1, Mock(), 'repair', feedback=feedback)
            self.assertTrue(list((root / '.arc/diagnostics').glob('*.json')))

    def test_independent_test_agent_does_not_receive_application_repair_context(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = 'frontend/tests/e2e/acceptance/test.spec.ts'
            save_text(root / path, 'test source')
            tools = FileTools(root, [path], readable=[path])
            def generate(instructions, payload):
                self.assertNotIn('repair_evidence', payload['task'])
                self.assertNotIn('runtime_helpers', payload['task'])
                return {'tool_calls': []}
            run_file_agent(Mock(generate_json=generate), '', {}, tools, lambda: {}, 1, Mock(), 'test', feedback={'error': 'Error: application failed'})

    def test_baseline_profile_keeps_original_fixture(self):
        with TemporaryDirectory() as directory, patch.dict('os.environ', {'ARC_AGENT_PROFILE': 'b1'}, clear=True):
            root = Path(directory)
            save_json(root / 'package.json', {})
            prepare_e2e(root, {})
            self.assertNotIn('observeApplication', (root / FIXTURE).read_text())
            self.assertFalse((root / DIAGNOSTICS).exists())

    def test_failure_observations_survive_many_successful_requests_without_duplication(self):
        with TemporaryDirectory() as directory:
            events = [{'kind': 'http', 'method': 'POST', 'path': '/api/save', 'status': 500}]
            events += [{'kind': 'http', 'method': 'GET', 'path': f'/api/read/{i}', 'status': 200} for i in range(20)]
            feedback = {'returncode': 1, 'failures': ['Error: assertion'], 'diagnostics': [{'events': events}]}
            result = repair_evidence(Path(directory), {}, feedback)
            self.assertEqual(result['observations'][0]['status'], 500)
            self.assertGreater(result['omitted_observations'], 0)
            projected = feedback_without_diagnostic_duplicates(feedback)
            self.assertEqual(projected['failures'], feedback['failures'])
            self.assertNotIn('diagnostics', projected)
            self.assertIn('diagnostics', feedback)


if __name__ == '__main__':
    unittest.main()
