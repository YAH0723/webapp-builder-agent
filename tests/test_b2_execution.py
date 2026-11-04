"""B2 removes duplicate workflows, bounds calls and fails closed on coverage."""
from contextlib import ExitStack
from copy import deepcopy
import importlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.agent.discovery import ContextIndex
from infrastructure.shared.agent.efficiency import enabled, intern_context, needs_generation_regression
from infrastructure.shared.agent.loop import AgentCallBudgetExceeded, AgentExhausted, run_file_agent
from infrastructure.shared.agent.proposals import ProposalCallBudgetExceeded, propose_json
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.tools.protocol import scoped_file_rules
from infrastructure.stages.frontend.triggers.acceptance import acceptance_path, lock_application_repair
from infrastructure.stages.frontend.triggers.unified import require_coverage, run_acceptance_first
from infrastructure.stages.frontend.triggers.direct import plan_bindings
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.utils.files import save_text


def expand_references(packed):
    def expand(value):
        if isinstance(value, dict):
            if set(value) == {'$context_ref'}:
                target = packed
                for part in value['$context_ref'].split('/')[1:]:
                    part = part.replace('~1', '/').replace('~0', '~')
                    target = target[int(part)] if isinstance(target, list) else target[part]
                return expand(target)
            return {key: expand(child) for key, child in value.items()}
        return [expand(child) for child in value] if isinstance(value, list) else value
    return expand(packed)


class ContextAndBudgetTests(unittest.TestCase):
    def test_interned_context_round_trips_with_escaped_keys(self):
        record = {'source': 'required behavior ' * 100, 'fields': {'id': 'integer'}}
        payload = {'task': {'api/path~id': record}, 'original': record, 'list': [record, {'different': True}]}
        before = deepcopy(payload)
        packed = intern_context(payload)
        self.assertEqual(expand_references(packed), before)
        self.assertEqual(payload, before)
        self.assertIn('~1', packed['original']['$context_ref'])
        self.assertLess(len(json.dumps(packed)), len(json.dumps(payload)))

    def test_distinct_requirements_are_not_conflated(self):
        payload = {'a': {'text': 'a' * 1000}, 'b': {'text': 'b' * 1000}}
        self.assertEqual(intern_context(payload), payload)

    def test_profiles_keep_baselines_available(self):
        for profile in ('b0', 'b1', 'b2'):
            with self.subTest(profile=profile), patch.dict('os.environ', {'ARC_AGENT_PROFILE': profile}, clear=True):
                self.assertEqual(enabled('acceptance_first'), profile == 'b2')
                self.assertEqual(enabled('context_reuse'), profile != 'b0')

    def test_file_budget_counts_reads_inside_one_edit_round(self):
        with TemporaryDirectory() as directory, patch.dict('os.environ', {
                'ARC_AGENT_PROFILE': 'b2', 'ARC_B2_MAX_TASK_CALLS': '3'}, clear=True):
            root = Path(directory)
            save_text(root / 'source.ts', 'one\ntwo\nthree\nfour\n')
            responses = [{'tool_calls': [{'tool': 'read_file', 'path': 'source.ts',
                'start_line': i, 'end_line': i}]} for i in range(1, 5)]
            model = Mock(generate_json=Mock(side_effect=responses))
            gate = Mock()
            with patch('infrastructure.shared.agent.loop.checkpoint'), self.assertRaises(AgentCallBudgetExceeded):
                run_file_agent(model, '', {}, FileTools(root), gate, 10, Mock(), 'bounded')
            self.assertEqual(model.generate_json.call_count, 3)
            gate.assert_not_called()
            self.assertEqual((root / 'source.ts').read_text(), 'one\ntwo\nthree\nfour\n')

    def test_design_budget_counts_context_queries(self):
        with patch.dict('os.environ', {'ARC_AGENT_PROFILE': 'b2', 'ARC_B2_MAX_TASK_CALLS': '3'}, clear=True):
            model = Mock(generate_json=Mock(side_effect=[{'context_request': {'kind': 'schema', 'ids': [str(i)]}}
                for i in range(5)]))
            accept = Mock()
            with self.assertRaises(ProposalCallBudgetExceeded):
                propose_json(model, '', {}, accept, Mock(), 'design',
                    context_index=ContextIndex({'schema': {str(i): {'fields': {}} for i in range(5)}}))
            self.assertEqual(model.generate_json.call_count, 3)
            accept.assert_not_called()

    def test_scoped_examples_never_advertise_forbidden_source(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = 'frontend/tests/e2e/support/context.ts'
            save_text(root / fixture, 'export const fixture = true;')
            rules = scoped_file_rules(FileTools(root, references=[fixture], readable=[fixture]))
            self.assertNotIn('backend/src/db/initialize.ts', rules)
            self.assertIn(fixture, rules)

    def test_tool_schema_uses_allowed_example_and_enum(self):
        with TemporaryDirectory() as directory, patch.dict('os.environ', {'ARC_AGENT_PROFILE': 'b2'}, clear=True):
            root = Path(directory)
            save_text(root / 'allowed.ts', 'fixture')
            tools = FileTools(root, readable=['allowed.ts'])
            schema = next(item for item in tools.schemas() if item['tool'] == 'read_file')
            self.assertEqual(schema['example']['path'], 'allowed.ts')
            self.assertEqual(schema['parameters']['properties']['path']['enum'], ['allowed.ts'])
            edit = next(item for item in tools.schemas() if item['tool'] == 'edit_file')
            self.assertNotIn('enum', edit['parameters']['properties']['new_content'])
            self.assertNotIn('enum', edit['parameters']['properties']['path'])

    def test_backend_test_only_precheck_does_not_suppress_changed_source_regression(self):
        with patch.dict('os.environ', {'ARC_AGENT_PROFILE': 'b2'}, clear=True):
            self.assertFalse(needs_generation_regression({'backend/tests/current.test.ts'}, 'backend/tests/current.test.ts'))
            self.assertTrue(needs_generation_regression({'backend/src/handler.ts'}, 'backend/tests/current.test.ts'))
            self.assertTrue(needs_generation_regression({'backend/tests/older.test.ts'}, 'backend/tests/current.test.ts'))
        with patch.dict('os.environ', {'ARC_AGENT_PROFILE': 'b0'}, clear=True):
            self.assertTrue(needs_generation_regression(set(), 'backend/tests/current.test.ts'))

    def test_application_repair_cannot_write_tests_or_fixtures(self):
        with TemporaryDirectory() as directory:
            paths = ['frontend/tests/a.spec.ts', 'frontend/tests/e2e/acceptance/a.spec.ts',
                'backend/tests/a.test.ts', 'backend/src/features/save.ts']
            tools = FileTools(Path(directory), paths)
            lock_application_repair(tools)
            self.assertTrue(tools.can_write(paths[-1]))
            for path in paths[:-1]:
                self.assertFalse(tools.can_write(path))


class UnifiedWorkflowTests(unittest.TestCase):
    def test_direct_bindings_reuse_contracts_without_inventing_trigger_code(self):
        tree = RequirementTree({'id': 'ROOT', 'children': [{'id': 'REQ-A'}]})
        backend = {'apis': {}, 'requirements': {'REQ-A': []}}
        ui = {'pages': {'PAGE': {'root': 'ROOT-UI', 'route': '/'}},
            'elements': {'ROOT-UI': {'parent': None}, 'BUTTON': {'parent': 'ROOT-UI'}},
            'requirements': {'REQ-A': ['BUTTON']}}
        obligations = {'requirements': {'REQ-A': {'read': [], 'write': []}}, 'steps': {}}
        plan = plan_bindings(tree, backend, ui, obligations)
        self.assertEqual(plan['bindings']['REQ-A']['pages'], ['PAGE'])
        self.assertEqual(plan['triggers'], {})
        with self.assertRaisesRegex(ValueError, 'undefined APIs'):
            plan_bindings(tree, {'apis': {}, 'requirements': {'REQ-A': ['MISSING']}}, ui, obligations)

    def test_stage11_direct_binding_path_never_constructs_a_model(self):
        stage = importlib.import_module('11_design_frontend_triggers')
        tree = RequirementTree({'id': 'ROOT'})
        backend, ui = {'apis': {}, 'requirements': {}}, {'pages': {}, 'elements': {}, 'requirements': {}}
        obligations = {'requirements': {'ROOT': {'read': [], 'write': []}}, 'steps': {}}
        with TemporaryDirectory() as directory, patch.dict('os.environ', {'ARC_AGENT_PROFILE': 'b2'}, clear=True), \
                patch.object(stage, 'load_frontend_context', return_value=(tree, {}, backend, {}, {})), \
                patch.object(stage, 'load_ui_design', return_value=ui), \
                patch.object(stage, 'read_artifact', return_value=obligations), \
                patch.object(stage, 'TextModel') as model:
            result = stage.design_frontend_triggers(Path(directory), Path(directory) / '.arc')
            self.assertEqual(result['mode'], 'direct_bindings')
            model.assert_not_called()

    def test_green_aggregate_cannot_hide_missing_requirement_suite(self):
        with TemporaryDirectory() as directory:
            result = {'returncode': 0, 'passed': 1, 'failed': 0, 'files': {'acceptance/a.spec.ts': 1}}
            with self.assertRaisesRegex(ValueError, 'No executed test cases'):
                require_coverage(result, ['frontend/tests/e2e/acceptance/a.spec.ts',
                    'frontend/tests/e2e/acceptance/b.spec.ts'], Path(directory))

    def test_final_coverage_accepts_reporter_paths_and_rejects_skips(self):
        with TemporaryDirectory() as directory:
            files = ['frontend/tests/e2e/acceptance/a.spec.ts']
            result = {'returncode': 0, 'passed': 1, 'failed': 0, 'files': {'acceptance/a.spec.ts': 1}}
            require_coverage(result, files, Path(directory))
            with self.assertRaises(ValueError):
                require_coverage({**result, 'skipped': 1}, files, Path(directory))

    def fixture(self, root, *, broken=False, missing=False, repair_fails=False):
        tree = SimpleNamespace(leaves=['REQ-A', 'REQ-B'])
        ui, backend = {'pages': {}, 'elements': {}, 'requirements': {}}, {'apis': {}, 'requirements': {}}
        marker = root / 'frontend/src/state.ts'
        save_text(marker, 'broken' if broken else 'fixed')
        checks, api = Mock(), Mock()
        checks.typecheck.return_value = checks.build.return_value = {'returncode': 0}
        api.typecheck.return_value = api.tests.return_value = {'returncode': 0}

        def tests(paths, *, fail_fast=None):
            self.assertIs(fail_fast, False)
            failed = marker.read_text() == 'broken'
            return {'returncode': int(failed), 'passed': 0 if failed else len(paths),
                'failed': int(failed), 'failures': ['missing behavior'] if failed else [],
                'files': {path.removeprefix('frontend/tests/e2e/'): 1 for path in paths}}
        checks.tests.side_effect = tests

        def author(*args, **kwargs):
            self.assertTrue(kwargs['focused'])
            for rid in tree.leaves[:1] if missing else tree.leaves:
                save_text(root / acceptance_path(rid), 'original requirement assertion')
            return {'status': 'GREEN', 'requirements': {rid: {'status': 'GREEN'} for rid in tree.leaves}}

        def repair(model, instructions, task, workspace, gate, *args, **kwargs):
            for rid in tree.leaves:
                self.assertFalse(workspace.can_write(acceptance_path(rid)))
            save_text(marker, 'fixed')
            if repair_fails:
                raise AgentExhausted('fixture', 1, {})
            return {'turns': 1, 'checks': gate()}

        prefix = 'infrastructure.stages.frontend.triggers.unified.'
        with ExitStack() as stack:
            for name in ('prepare_frontend', 'prepare_e2e', 'install_dependencies'):
                stack.enter_context(patch(prefix + name))
            stack.enter_context(patch(prefix + 'E2EChecks', return_value=checks))
            stack.enter_context(patch(prefix + 'FrontendChecks', return_value=Mock()))
            stack.enter_context(patch(prefix + 'BackendChecks', return_value=api))
            author_mock = stack.enter_context(patch(prefix + 'run_independent_acceptance', side_effect=author))
            coder = stack.enter_context(patch(prefix + 'run_file_agent', side_effect=repair))
            result = run_acceptance_first(root, root / '.arc', tree, {}, backend, ui, {}, Mock(), Mock())
            author_mock.assert_called_once()
            return result, checks, coder.call_count

    def test_one_authoring_workflow_and_full_final_regression(self):
        with TemporaryDirectory() as directory:
            result, checks, repairs = self.fixture(Path(directory))
            self.assertEqual(result['status'], 'GREEN')
            self.assertEqual(result['summary']['e2e_tests'], 2)
            self.assertEqual(repairs, 0)
            checks.build.assert_called_once()
            checks.tests.assert_called_once()

    def test_final_repair_preserves_original_tests(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            result, _, repairs = self.fixture(root, broken=True)
            self.assertEqual(result['status'], 'GREEN')
            self.assertEqual(repairs, 1)
            self.assertEqual((root / acceptance_path('REQ-A')).read_text(), 'original requirement assertion')

    def test_failed_repair_rolls_back_and_rechecks_restored_app(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            result, checks, _ = self.fixture(root, broken=True, repair_fails=True)
            self.assertEqual(result['status'], 'COMPLETED_WITH_FAILURES')
            self.assertEqual((root / 'frontend/src/state.ts').read_text(), 'broken')
            self.assertEqual(result['verification']['acceptance']['status'], 'FAILED')
            self.assertEqual(checks.tests.call_count, 2)

    def test_missing_test_never_becomes_green(self):
        with TemporaryDirectory() as directory:
            result, checks, repairs = self.fixture(Path(directory), missing=True)
            self.assertEqual(result['status'], 'COMPLETED_WITH_FAILURES')
            self.assertEqual(repairs, 0)
            checks.tests.assert_not_called()

    def test_stage_selects_b2_without_duplicate_smoke_authoring(self):
        stage = importlib.import_module('12_implement_frontend_tdd')
        tree = SimpleNamespace(requirements={'REQ': {}}, children={'REQ': []})
        with TemporaryDirectory() as directory, patch.dict('os.environ', {'ARC_AGENT_PROFILE': 'b2'}, clear=True), \
                patch.object(stage, 'load_e2e_context', return_value=(tree, {}, {}, {'pages': {'P': {}}}, {}, {}, {})), \
                patch.object(stage, 'TextModel'), patch.object(stage, 'save_json'), \
                patch.object(stage, 'run_trigger_tdd') as old, \
                patch('infrastructure.stages.frontend.triggers.unified.run_acceptance_first', return_value={'status': 'GREEN'}) as new:
            root = Path(directory)
            self.assertEqual(stage.implement_frontend_triggers(root, root / '.arc'), {'status': 'GREEN'})
            old.assert_not_called()
            new.assert_called_once()


if __name__ == '__main__':
    unittest.main()
