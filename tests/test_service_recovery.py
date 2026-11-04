"""Inject upstream 503s and verify recovery/completeness without a real model."""
from collections import Counter
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from importlib import import_module
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.compiler import Compiler
from infrastructure.shared.agent.service_recovery import retryable_service_error, check_prerequisites, PrerequisiteBlocked
from infrastructure.shared.agent.tasks import TaskFailures, StageIncomplete
from infrastructure.utils.files import save_json, save_text


class HTTPFault(Exception):
    def __init__(self, status=503, message='Service unavailable'):
        self.status_code = status
        super().__init__(message)


def outage():
    error = RuntimeError('Model request failed')
    error.__cause__ = HTTPFault()
    return error


RAW = {'id': 'ROOT', 'children': [{'id': 'A', 'name': 'Static A'}, {'id': 'B', 'name': 'Static B'}]}


class ServiceRecovery(unittest.TestCase):
    def setUp(self):
        context = patch.dict('os.environ', {'ARC_AGENT_PROFILE': 'b2'}, clear=True)
        context.start()
        self.addCleanup(context.stop)
        sleep = patch('infrastructure.shared.agent.tasks.time.sleep')
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_retry_classifier_uses_status_cause_and_excludes_quota_and_auth(self):
        self.assertTrue(retryable_service_error(outage()))
        self.assertTrue(retryable_service_error(HTTPFault(429, 'Rate limit exceeded')))
        for error in (HTTPFault(401), HTTPFault(429, 'insufficient_quota: Free quota exhausted'),
                ValueError('Bad JSON'), RuntimeError('503 is merely quoted text')):
            self.assertFalse(retryable_service_error(error))

    def test_deferred_pass_retries_failed_task_once_without_repeating_accepted_neighbor(self):
        with TemporaryDirectory() as directory:
            tasks = TaskFailures(Path(directory), 'test', Mock())
            calls = []
            for _, identity in tasks.iterate(['A', 'B']):
                with tasks.task(identity):
                    calls.append(identity)
                    if calls == ['A']:
                        raise outage()
            tasks.finish()
            self.assertEqual(calls, ['A', 'B', 'A'])
            self.assertEqual(tasks.report['tasks']['A']['attempts'], 2)
            self.assertEqual(tasks.report['tasks']['B']['attempts'], 1)

    def test_persistent_outage_has_only_one_deferred_pass_and_stays_failed(self):
        with TemporaryDirectory() as directory:
            tasks = TaskFailures(Path(directory), 'test', Mock())
            calls = []
            for _, identity in tasks.iterate(['A']):
                with tasks.task(identity):
                    calls.append(identity)
                    raise outage()
            with self.assertRaises(StageIncomplete):
                tasks.finish()
            self.assertEqual(calls, ['A', 'A'])

    def test_semantic_and_quota_errors_do_not_receive_service_retries(self):
        for failure in (ValueError('schema conflict'), HTTPFault(429, 'balance too low')):
            with TemporaryDirectory() as directory:
                tasks = TaskFailures(Path(directory), 'test', Mock())
                calls = []
                for _, identity in tasks.iterate(['A']):
                    with tasks.task(identity):
                        calls.append(identity)
                        raise failure
                self.assertEqual(calls, ['A'])

    def test_visual_reference_failures_do_not_discard_accepted_images(self):
        stage = import_module('01_explore_requirement')
        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = {'id': 'ROOT', 'description': {'text': 'Static app', 'image': [
                {'id': 'I-A', 'reference': 'a.png'}, {'id': 'I-B', 'reference': 'b.png'}]}}
            save_text(root / 'requirements.yaml', json.dumps(raw))
            (root / 'a.png').write_bytes(b'fixture')
            (root / 'b.png').write_bytes(b'fixture')
            calls = []
            def analyze(path):
                calls.append(path.name)
                if calls == ['a.png']:
                    raise outage()
                return {'layout': path.name, 'elements': [], 'style': ''}
            with patch.object(stage, 'VisualModel', return_value=Mock(analyze=analyze)), patch.object(stage, 'DemoConsole'), redirect_stdout(StringIO()):
                stage.explore_requirement(root, root / '.arc')
            self.assertEqual(calls, ['a.png', 'b.png', 'a.png'])
            self.assertEqual(len(json.loads((root / '.arc/visual_analysis.json').read_text())), 2)

    def test_schema_and_obligations_complete_after_transient_failure(self):
        schema_stage = import_module('02_build_db_schema')
        obligation_stage = import_module('03_infer_db_obligations')
        with TemporaryDirectory() as directory:
            arc = Path(directory)
            save_json(arc / 'requirements.json', RAW)
            calls = []
            def schema(_, request):
                rid = request['requirement']['id']
                calls.append(rid)
                if calls == ['A']:
                    raise outage()
                return {'entities': {}, 'related_fields': []}
            with patch.object(schema_stage, 'TextModel', return_value=Mock(generate_json=schema)), patch.object(schema_stage, 'DemoConsole'), redirect_stdout(StringIO()):
                result = schema_stage.build_db_schema(arc)
            self.assertEqual(calls, ['A', 'B', 'A'])
            self.assertEqual(set(result['requirements']), {'A', 'B'})
            calls.clear()
            def obligations(_, request):
                rid = request['requirement']['id']
                calls.append(rid)
                if calls == ['A']:
                    raise outage()
                return {'requirement': {'read': [], 'write': []}, 'steps': {}}
            with patch.object(obligation_stage, 'TextModel', return_value=Mock(generate_json=obligations)), patch.object(obligation_stage, 'DemoConsole'), redirect_stdout(StringIO()):
                result = obligation_stage.infer_db_obligations(arc)
            self.assertEqual(calls, ['A', 'B', 'A'])
            self.assertEqual(set(result['requirements']), {'ROOT', 'A', 'B'})
            check_prerequisites('06_design_backend_apis', arc)

    def test_missing_records_are_blocked_not_filled_with_empty_obligations(self):
        with TemporaryDirectory() as directory:
            arc = Path(directory)
            save_json(arc / 'requirements.json', RAW)
            save_json(arc / 'db_schema.json', {'entities': {}, 'requirements': {'A': [], 'B': []}})
            save_json(arc / 'db_obligations.json', {'requirements': {'ROOT': {'read': [], 'write': []}, 'B': {'read': [], 'write': []}}, 'steps': {}})
            with self.assertRaises(PrerequisiteBlocked):
                check_prerequisites('06_design_backend_apis', arc)
            self.assertNotIn('A', json.loads((arc / 'db_obligations.json').read_text())['requirements'])

    def test_compiler_does_not_call_expensive_dependents_when_prerequisites_are_missing(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            compiler = Compiler(root, root / 'output')
            with patch.object(import_module('09_design_ui'), 'design_frontend_ui') as generation, redirect_stdout(StringIO()):
                result = compiler._run('09_design_ui', 'design_frontend_ui', root, compiler.arc_dir)
            generation.assert_not_called()
            self.assertEqual(result['status'], 'BLOCKED')

    def test_cli_returns_nonzero_for_blocked_prerequisites(self):
        entry = import_module('main')
        compiler = Mock(report={'status': 'BLOCKED'}, arc_dir=Path('report'))
        with patch.object(entry, 'parse_args', return_value=Mock(requirement_path=Path('.'), output_dir=Path('.'), model_log=False, port=3000)), \
                patch.object(entry, 'Compiler', return_value=compiler), patch.object(entry, 'configure_console'), redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as failure:
                entry.main([])
        self.assertEqual(failure.exception.code, 2)

    def test_all_real_passes_can_finish_after_injected_schema_and_obligation_503s(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'input'
            save_text(source / 'requirements.yaml', json.dumps(RAW))
            compiler = Compiler(source, root / 'application')
            counts = Counter()
            def schema(_, request):
                rid = request['requirement']['id']; counts['schema:' + rid] += 1
                if rid == 'A' and counts['schema:A'] == 1:
                    raise outage()
                return {'entities': {}, 'related_fields': []}
            def obligations(_, request):
                rid = request['requirement']['id']; counts['obligations:' + rid] += 1
                if rid == 'A' and counts['obligations:A'] == 1:
                    raise outage()
                return {'requirement': {'read': [], 'write': []}, 'steps': {}}
            with ExitStack() as stack, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                for module, generate in [('02_build_db_schema', schema), ('03_infer_db_obligations', obligations),
                        ('06_design_backend_apis', Mock(return_value={'apis': {}, 'requirement_apis': []})),
                        ('09_design_ui', Mock(return_value={'pages': {}, 'elements': {}, 'bindings': {}, 'requirement_ui': [], 'step_ui': {}}))]:
                    stack.enter_context(patch.object(import_module(module), 'TextModel', return_value=Mock(generate_json=generate)))
                stack.enter_context(patch.object(import_module('05_implement_db'), 'verify_database_runtime', return_value={'status': 'GREEN'}))
                stack.enter_context(patch.object(import_module('08_implement_backend_tdd'), 'install_dependencies'))
                compiler.compile()
            self.assertEqual(len(compiler.report['stages']), 13)
            self.assertEqual(compiler.report['status'], 'GREEN', compiler.report)
            self.assertEqual(counts, {'schema:A': 2, 'schema:B': 1, 'obligations:A': 2, 'obligations:B': 1})
            self.assertTrue((compiler.arc_dir / 'backend_apis.json').is_file())


if __name__ == '__main__':
    unittest.main()
