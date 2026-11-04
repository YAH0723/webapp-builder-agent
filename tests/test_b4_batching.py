"""Offline orchestration and failure isolation; no model clients or paid calls."""
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.agent.batching import chunks, enabled, target_path, bind_files, feedback_for, split_failed
from infrastructure.shared.agent.context import SourceFiles
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.stages.frontend.ui.batching import accept_design, synthesize_batches
from infrastructure.stages.frontend.ui.design import empty_design
from infrastructure.stages.frontend.triggers.acceptance_batches import acceptance_task, run_acceptance_batches
from infrastructure.stages.frontend.triggers.acceptance import acceptance_path
from infrastructure.stages.backend.batching import implement_batches
from infrastructure.utils.files import save_json, save_text
from test_frontend_flow import frontend_fixture


class B4Mechanisms(unittest.TestCase):
    def setUp(self):
        self.flags = patch.dict(os.environ, {'ARC_AGENT_PROFILE': 'b4'})
        self.flags.start()
        self.addCleanup(self.flags.stop)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)
        self.arc = self.output / '.arc'
        self.raw, self.tree, self.ui, self.design, self.backend, _ = frontend_fixture()
        for node in self.ui['elements'].values():
            node['data'] = []
        self.schema = {'entities': {}}

    def test_default_profile_and_independent_switches(self):
        self.assertTrue(enabled('backend_batches'))
        with patch.dict(os.environ, {'ARC_B4_BACKEND_BATCHES': '0'}):
            self.assertFalse(enabled('backend_batches'))
            self.assertTrue(enabled('acceptance_first'))
        with patch.dict(os.environ, {'ARC_AGENT_PROFILE': 'b3'}):
            self.assertFalse(enabled('backend_batches'))
        with patch.dict(os.environ, {'ARC_AGENT_PROFILE': 'typo'}):
            with self.assertRaises(ValueError):
                enabled('backend_batches')

    def test_bounded_chunks_keep_every_complete_oversized_record(self):
        records = [{'id': str(i), 'text': 'x' * n} for i, n in enumerate([10, 10, 1000, 10, 10])]
        groups = chunks(records, 3, 120)
        self.assertEqual([len(g) for g in groups], [2, 1, 2])
        self.assertEqual([r for g in groups for r in g], records)
        self.assertEqual(groups[1][0]['text'], 'x' * 1000)

    def test_failed_batch_splits_once_preserving_source_order(self):
        records = [{'id': str(i)} for i in range(5)]
        queue = [(records, 0)]
        entry = {'status': 'FAILED'}
        split_failed(queue, 1, records, 0, entry, self.output, '08')
        self.assertEqual([len(group) for group, depth in queue], [5, 3, 2])
        self.assertEqual([r['id'] for group, depth in queue[1:] for r in group], ['0', '1', '2', '3', '4'])
        split_failed(queue, 2, queue[1][0], 1, entry, self.output, '08')
        self.assertEqual(len(queue), 3)

    def test_paths_are_safe_stable_and_bind_only_complete_batches(self):
        ids = ['../../bad/id', 'normal']
        paths = {key: target_path(self.output, 'api', key) for key in ids}
        self.assertEqual(len(set(paths.values())), 2)
        self.assertTrue(all('..' not in path for path in paths.values()))
        save_text(self.output / paths[ids[0]], 'export const handle = 1;')
        with self.assertRaises(ValueError):
            bind_files(self.output, 'api', paths)
        self.assertIsNone(selected_path(self.output, 'api', ids[0]))
        save_text(self.output / paths[ids[1]], 'export const handle = 2;')
        bind_files(self.output, 'api', paths)
        self.assertEqual(target_path(self.output, 'api', ids[0]), paths[ids[0]])

    def proposal(self):
        return {'elements': deepcopy(self.ui['elements']), 'pages': deepcopy(self.ui['pages']),
                'requirement_ui': {rid: self.ui['requirements'][rid] for rid in self.tree.leaves},
                'step_ui': deepcopy(self.ui['steps'])}

    def test_ui_batch_rejects_missing_member_step_unknown_id_and_cycle(self):
        proposal = self.proposal()
        result = accept_design(empty_design(), proposal, self.tree.leaves, self.tree)
        self.assertEqual(result['requirements']['REQ-B'], self.ui['requirements']['REQ-B'])
        for mutation in ('requirement', 'step', 'unknown', 'cycle'):
            value = deepcopy(proposal)
            if mutation == 'requirement':
                del value['requirement_ui']['REQ-B']
            elif mutation == 'step':
                del value['step_ui']['STEP-REQ-A']
            elif mutation == 'unknown':
                value['requirement_ui']['REQ-A'] = ['missing']
            else:
                value['elements']['UI-FORM']['parent'] = 'UI-TEXT'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                accept_design(empty_design(), value, self.tree.leaves, self.tree)
        self.assertEqual(proposal, self.proposal())

    def test_ui_design_three_requirements_share_one_proposal(self):
        model = Mock()
        model.generate_json.return_value = self.proposal()
        contexts = {rid: {'id': rid, 'name': rid} for rid in self.tree.leaves}
        result = synthesize_batches(self.arc, self.tree, {}, contexts, model, Mock(), 2)
        self.assertEqual(model.generate_json.call_count, 1)
        self.assertTrue(all(result['requirements'][rid] for rid in self.tree.leaves))

    def test_feedback_cannot_reenable_tests_for_application_repair(self):
        app, test = 'frontend/src/page.tsx', 'frontend/tests/ui/page.spec.ts'
        save_text(self.output / app, 'export const Page = 1;')
        save_text(self.output / test, 'test("case", () => {});')
        selection = SourceFiles(self.output)
        workspace = selection.workspace(paths=[app], references=[test])
        allow = lambda p: p.startswith('frontend/src/') and p != 'frontend/src/ui-runtime.ts'
        feedback = feedback_for(workspace, [selection], allow)
        feedback({'error': test})
        self.assertFalse(workspace.can_write(test))
        with self.assertRaises(ValueError):
            workspace.execute([{'tool': 'edit_file', 'path': test, 'operation': 'append', 'new_content': 'weaken'}])
        self.assertTrue(workspace.can_write(app))

    def test_independent_author_task_has_original_scenarios_not_application_sources(self):
        backend = deepcopy(self.backend)
        for api in backend['apis'].values():
            api.update(read=[], write=[])
        task, apis = acceptance_task(self.tree, self.schema, backend, self.ui, self.design, self.tree.leaves)
        self.assertEqual(set(task['requirements']), set(self.tree.leaves))
        self.assertTrue(task['requirements']['REQ-A']['original_requirement']['steps'])
        self.assertNotIn('files', task)
        self.assertEqual(set(apis), set(backend['apis']))

    def backend_run(self, missing_last=False):
        backend = deepcopy(self.backend)
        for api in backend['apis'].values():
            api.update(read=[], write=[])
        support = ['backend/src/api/types.ts', 'backend/src/db/client.ts', 'backend/tests/support/context.ts']
        for path in support:
            save_text(self.output / path, '// fixed utility')
        checks = Mock()
        checks.typecheck.return_value = {'returncode': 0, 'output': ''}
        checks.build.return_value = {'returncode': 0, 'output': ''}
        checks.tests.return_value = {'returncode': 0, 'tests': 2, 'pass': 2, 'fail': 0,
                                     'skipped': 0, 'todo': 0, 'output': ''}
        calls = []
        class Model:
            def generate_json(inner, instructions, request):
                task = request['task']
                calls.append(task)
                if 'implementation_paths' not in task:
                    mapping = task['test_paths']
                    self.assertTrue(all(not item['writable'] for path, item in request['files'].items()
                                        if path in support))
                else:
                    mapping = task['implementation_paths']
                    self.assertTrue(all(not value['writable'] for path, value in request['files'].items()
                                        if '/tests/' in path))
                items = list(mapping.items())
                if missing_last and 'implementation_paths' not in task:
                    items = items[:-1]
                return {'tool_calls': [{'tool': 'edit_file', 'path': path, 'operation': 'create',
                                       'new_content': 'export const generated = 1;'} for _, path in items]}
        with patch('infrastructure.stages.backend.batching.BackendChecks', return_value=checks), \
                patch.dict(os.environ, {'ARC_B4_ADAPTIVE_SPLIT': '0'}):
            result = implement_batches(self.arc, self.tree, self.schema, backend, Model(), Mock(),
                                       1, 5, 'author', 'implement')
        return result, calls

    def test_backend_two_apis_one_author_one_implementation_all_owners_supplied(self):
        result, calls = self.backend_run()
        self.assertEqual(result['status'], 'GREEN')
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]['owners']['API-SAVE'], ['REQ-A', 'REQ-B'])
        self.assertEqual(set(calls[0]['owner_requirements']), set(self.tree.leaves))
        self.assertTrue(all(selected_path(self.output, 'api', aid) for aid in self.backend['apis']))

    def test_backend_incomplete_author_batch_rolls_back_and_remains_failed(self):
        result, _ = self.backend_run(missing_last=True)
        self.assertEqual(result['status'], 'COMPLETED_WITH_FAILURES')
        self.assertTrue(all(entry['status'] == 'FAILED' for entry in result['apis'].values()))
        self.assertFalse((self.arc / 'implementation_paths.json').exists())
        self.assertFalse(list((self.output / 'backend/tests/api').glob('*.test.ts')))

    def test_b4_stage12_bypasses_both_old_process_and_second_acceptance(self):
        module = importlib.import_module('12_implement_frontend_tdd')
        fake = {'status': 'GREEN', 'summary': {}}
        with patch.object(module, 'load_e2e_context', return_value=(self.tree, self.schema, self.backend,
                self.ui, self.design, {}, {})), patch.object(module, 'TextModel'), \
                patch('infrastructure.stages.frontend.triggers.acceptance_batches.run_acceptance_batches', return_value=fake) as batch, \
                patch.object(module, 'run_trigger_tdd') as old, patch.object(module, 'run_independent_acceptance') as second:
            self.assertIs(module.implement_frontend_triggers(self.output, self.arc), fake)
            batch.assert_called_once()
            old.assert_not_called()
            second.assert_not_called()


class LocalStageChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        path = Path(__file__).resolve().parents[1] / 'team-tools/check-stage.py'
        spec = importlib.util.spec_from_file_location('local_stage_check', path)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)
        save_json(self.output / '.arc/backend_apis.json', {'apis': {'A': {}, 'B': {}}})
        from infrastructure.shared.project.entrypoints import remember_path
        for identity in ('A', 'B'):
            path = f'backend/tests/{identity}.test.ts'
            remember_path(self.output, 'backend_test', identity, path)
            save_text(self.output / path, 'export const test = 1;')

    def test_focused_typecheck_never_runs_tests_build_or_model(self):
        checks = Mock()
        checks.typecheck.return_value = {'returncode': 0, 'output': ''}
        with patch.object(self.module, 'BackendChecks', return_value=checks):
            result = self.module.check(self.output, '08', ['B'], ['typecheck'])
        self.assertEqual(result['status'], 'GREEN')
        self.assertEqual(result['scope'], 'selected_targets')
        self.assertEqual(result['model_requests'], 0)
        checks.typecheck.assert_called_once_with(['backend/tests/B.test.ts'])
        checks.tests.assert_not_called()
        checks.build.assert_not_called()

    def test_list_does_not_construct_a_runtime_and_missing_member_cannot_pass(self):
        with patch.object(self.module, 'BackendChecks') as runtime:
            result = self.module.check(self.output, '08', list_only=True)
            self.assertEqual(result['status'], 'LISTED_NOT_TESTED')
            runtime.assert_not_called()
            (self.output / 'backend/tests/A.test.ts').unlink()
            result = self.module.check(self.output, '08', selected_checks=['typecheck'])
            self.assertEqual(result['status'], 'FAILED')
            self.assertIn('A', result['error'])
            runtime.assert_not_called()

    def test_failed_check_is_retained_and_other_requested_checks_still_run(self):
        checks = Mock()
        checks.typecheck.return_value = {'returncode': 1, 'output': 'type error'}
        checks.build.return_value = {'returncode': 0, 'output': ''}
        with patch.object(self.module, 'BackendChecks', return_value=checks):
            result = self.module.check(self.output, '08', selected_checks=['typecheck', 'build'])
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['checks']['typecheck']['error'], 'type error')
        self.assertEqual(result['checks']['build']['status'], 'GREEN')


if __name__ == '__main__':
    unittest.main()
