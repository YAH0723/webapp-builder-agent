"""Coverage detects omissions/expected failures; never claims semantic proof."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from test_frontend_flow import frontend_fixture
from infrastructure.stages.frontend.triggers.coverage import (require_coverage, journey_records,
    JOURNEY_PATH, shared_failure_context)
from infrastructure.stages.frontend.triggers.acceptance import acceptance_path
from infrastructure.stages.frontend.ui.testing import parse_playwright_result


class CoverageTests(unittest.TestCase):
    def setUp(self):
        _, self.tree, self.ui, _, self.backend, _ = frontend_fixture()

    def case(self, rid, status='passed', path=None):
        return {'file': path or acceptance_path(rid), 'expected_status': 'passed',
                'outcomes': [status], 'annotations': [{'type': 'arc-step', 'description': step}
                    for step in self.tree.own_steps[rid]]}

    def test_missing_skipped_failed_and_expected_failure_cannot_count_as_execution(self):
        result = {'cases': [self.case('REQ-A')]}
        self.assertFalse(require_coverage(result, self.tree, ['REQ-A'], executed=True)['semantic_coverage_proven'])
        for alteration in ['missing', 'skipped', 'failed', 'expected_failure', 'wrong_file']:
            case = self.case('REQ-A')
            if alteration == 'missing': case['annotations'] = []
            elif alteration == 'expected_failure': case['expected_status'] = 'failed'
            elif alteration == 'wrong_file': case['file'] = acceptance_path('REQ-B')
            else: case['outcomes'] = [alteration]
            with self.subTest(alteration=alteration), self.assertRaises(ValueError):
                require_coverage({'cases': [case]}, self.tree, ['REQ-A'], executed=True)

    def test_collection_is_not_treated_as_execution(self):
        case = self.case('REQ-A'); case['outcomes'] = []
        require_coverage({'cases': [case]}, self.tree, ['REQ-A'], executed=False)
        with self.assertRaises(ValueError):
            require_coverage({'cases': [case]}, self.tree, ['REQ-A'], executed=True)

    def test_journey_needs_two_distinct_original_requirements(self):
        one = self.case('REQ-A', path=JOURNEY_PATH)
        with self.assertRaises(ValueError):
            require_coverage({'cases': [one]}, self.tree, self.tree.leaves, executed=True, journey=True)
        both = [one, self.case('REQ-B', path=JOURNEY_PATH)]
        require_coverage({'cases': both}, self.tree, self.tree.leaves, executed=True, journey=True)

    def test_reporter_retains_annotations_expected_status_and_actual_outcomes(self):
        report = {'suites': [{'specs': [{'file': 'acceptance/test.spec.ts', 'title': 'outcome',
            'tests': [{'expectedStatus': 'passed', 'annotations': [{'type':'arc-step','description':'STEP'}],
                       'results': [{'status':'passed'}]}]}]}], 'stats': {'expected':1}}
        result = parse_playwright_result({'returncode':0,'stdout':json.dumps(report),'output':''}, include_files=True)
        self.assertEqual(result['cases'][0]['outcomes'], ['passed'])
        self.assertEqual(result['cases'][0]['annotations'][0]['description'], 'STEP')

    def test_related_requirement_selection_and_failure_owner_context(self):
        records = [{'id': rid, 'requirement': {'id':rid}} for rid in self.tree.leaves]
        chosen = journey_records(records, self.backend, self.ui)
        self.assertGreaterEqual(len(chosen), 2)
        backend = deepcopy(self.backend)
        backend['apis']['API-SAVE']['signature'] = {'method':'POST','path':'/api/notes'}
        context = shared_failure_context({'returncode':1,'failures':['HTTP POST /api/notes returned 500']}, self.tree, backend)
        self.assertEqual(context['shared_api_owners']['API-SAVE'], ['REQ-A', 'REQ-B'])
        self.assertIn('REQ-B', context['owner_requirements'])


if __name__ == '__main__': unittest.main()
