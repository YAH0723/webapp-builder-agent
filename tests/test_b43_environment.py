"""Reproduce dependency/manifest failures without npm downloads or paid inference."""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.project import environment as env
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.tasks import TaskFailures
from infrastructure.compiler import Compiler


class EnvironmentGuards(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.output = Path(temp.name)
        shutil.copytree(Path(env.__file__).parent / 'templates', self.output, dirs_exist_ok=True)
        flags = patch.dict(os.environ, {'ARC_AGENT_PROFILE': 'b4'})
        flags.start(); self.addCleanup(flags.stop)

    def test_backend_only_workspace_is_restored_without_deleting_dependency_additions(self):
        path = self.output / 'package.json'
        root = json.loads(path.read_text(encoding='utf8'))
        root.update(workspaces=['backend']); root['scripts']['build'] = 'npm run build -w @arc/backend'
        root['dependencies'] = {'extra-user-library': '1.0.0'}
        path.write_text(json.dumps(root), encoding='utf8')
        env.workspace_contract(self.output)
        restored = json.loads(path.read_text(encoding='utf8'))
        self.assertEqual(restored['workspaces'], ['backend', 'frontend'])
        self.assertIn('@arc/frontend', restored['scripts']['build'])
        self.assertEqual(restored['dependencies'], root['dependencies'])

    def test_configuration_cannot_be_edited_even_with_explicit_writable_and_callback(self):
        workspace = FileTools(self.output, ['package.json'], allow_write=lambda p: True)
        self.assertFalse(workspace.can_write('package.json'))
        original = (self.output / 'package.json').read_bytes()
        with self.assertRaises(ValueError):
            workspace.execute([{'tool': 'edit_file', 'path': 'package.json', 'operation': 'append', 'new_content': '\n{}'}])
        self.assertEqual((self.output / 'package.json').read_bytes(), original)

    def test_persistent_npm_failure_never_reaches_database_model_repair(self):
        from infrastructure.stages.database.implementation import verify_database_runtime
        model = Mock()
        with patch.object(env, 'probe', return_value={'returncode': 1, 'output': 'missing vite/client'}), \
             patch('infrastructure.shared.project.dependencies._install_once', side_effect=RuntimeError('ETARGET')) as install:
            with self.assertRaises(env.EnvironmentBlocked):
                verify_database_runtime(self.output / '.arc', {'entities': {}}, model, Mock())
        self.assertEqual(install.call_count, 2)
        model.generate_json.assert_not_called()
        report = json.loads((self.output / '.arc/environment.json').read_text(encoding='utf8'))
        self.assertEqual(report['status'], 'BLOCKED_ENVIRONMENT')

    def test_one_transient_install_failure_recovers_without_changing_api_or_removing_frontend(self):
        with patch('infrastructure.shared.project.dependencies._install_once', side_effect=[RuntimeError('ETARGET'), None]) as install, \
             patch.object(env, 'probe', return_value={'returncode': 0, 'output': 'all modules resolve'}):
            install_dependencies(self.output)
        self.assertEqual([call.kwargs['refresh'] for call in install.call_args_list], [False, True])
        self.assertEqual(json.loads((self.output / '.arc/environment.json').read_text(encoding='utf8'))['status'], 'GREEN')

    def test_npm_exit_zero_cannot_hide_missing_frontend_dependency(self):
        with patch('infrastructure.shared.project.dependencies._install_once') as install, \
             patch.object(env, 'probe', return_value={'returncode': 1, 'output': 'missing vite/client'}):
            with self.assertRaises(env.EnvironmentBlocked):
                install_dependencies(self.output)
        self.assertEqual(install.call_count, 2)

    def test_pipeline_skips_every_later_model_stage_after_environment_failure(self):
        compiler = Compiler(self.output, self.output)
        visited = []
        def module(name):
            visited.append(name)
            def stage(*args, **kwargs):
                if name == '05_implement_db':
                    raise env.EnvironmentBlocked('ETARGET with frontend unavailable')
                return {'status': 'GREEN'}
            return Mock(**{function: stage for function in ['project_initialization', 'explore_requirement',
                'build_db_schema', 'infer_db_obligations', 'check_db_obligations', 'implement_db']})
        with patch('infrastructure.compiler.import_module', side_effect=module), \
             patch.object(env, 'require_environment'), \
             patch('infrastructure.compiler.console_log', side_effect=lambda *a, **k: nullcontext()), \
             patch('infrastructure.compiler.checkpoint'), patch('infrastructure.compiler.show_panel'):
            compiler.compile()
        self.assertEqual(len(visited), 6)
        self.assertEqual(compiler.report['status'], 'BLOCKED_ENVIRONMENT')
        self.assertEqual(compiler.report['stages']['12_implement_frontend_tdd']['status'], 'BLOCKED_ENVIRONMENT')

    def test_failed_initial_preflight_stops_before_first_model_stage(self):
        compiler = Compiler(self.output, self.output)
        scaffold = Mock(project_initialization=Mock(return_value=[]))
        with patch('infrastructure.compiler.import_module', return_value=scaffold) as modules, \
             patch.object(env, 'require_environment', side_effect=env.EnvironmentBlocked('registry unavailable')), \
             patch('infrastructure.compiler.console_log', side_effect=lambda *a, **k: nullcontext()), \
             patch('infrastructure.compiler.checkpoint'), patch('infrastructure.compiler.show_panel'):
            compiler.compile()
        self.assertEqual(modules.call_count, 1)
        self.assertEqual(compiler.report['stages']['01_explore_requirement']['status'], 'BLOCKED_ENVIRONMENT')

    def test_environment_error_bypasses_local_repair_and_design_task_suppression(self):
        model = Mock(); model.generate_json.return_value = {'tool_calls': []}
        def gate():
            raise env.EnvironmentBlocked('missing vite/client')
        with self.assertRaises(env.EnvironmentBlocked):
            run_file_agent(model, 'repair', {}, FileTools(self.output), gate, 10, Mock(), 'test')
        self.assertEqual(model.generate_json.call_count, 1)
        with self.assertRaises(env.EnvironmentBlocked):
            with TaskFailures(self.output / '.arc', 'test', Mock()).task('A'):
                gate()

    def test_business_failure_does_not_activate_pipeline_environment_block(self):
        compiler = Compiler(self.output, self.output)
        module = Mock(run=Mock(side_effect=[ValueError('business assertion failed'), {'status': 'GREEN'}]))
        with patch('infrastructure.compiler.import_module', return_value=module), \
             patch('infrastructure.compiler.console_log', side_effect=lambda *a, **k: nullcontext()), \
             patch('infrastructure.compiler.checkpoint'), patch('infrastructure.compiler.show_panel'):
            compiler._run('first', 'run')
            result = compiler._run('next', 'run')
        self.assertEqual(result['status'], 'GREEN')
        self.assertIsNone(compiler.environment_failure)


if __name__ == '__main__':
    unittest.main()
