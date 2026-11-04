"""Replay boundaries and UI batch recovery without remote inference."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.agent.replay import ReplayTape
from infrastructure.stages.frontend.ui.batching import synthesize_batches
from test_frontend_flow import frontend_fixture


class OfflineReplay(unittest.TestCase):
    def test_tape_requires_expected_task_and_complete_consumption(self):
        tape = ReplayTape([{'expect': {'task_contains': {'apis': {'A': {'name': 'A'}}},
            'task_keys': ['apis'], 'instructions_contain': ['author']}, 'response': {'tool_calls': []}}])
        with self.assertRaises(ValueError):
            tape.generate_json('author', {'task': {'apis': {'B': {}}}})
        with self.assertRaises(ValueError):
            tape.finish()
        response = tape.generate_json('author batch', {'task': {'apis': {'A': {'name': 'A', 'extra': 1}}}})
        response['tool_calls'].append('mutated')
        self.assertEqual(tape.records[0]['response']['tool_calls'], [])
        summary = tape.finish()
        self.assertEqual(summary['real_model_requests'], 0)
        self.assertEqual(summary['scripted_model_calls'], 1)
        with self.assertRaises(ValueError):
            tape.generate_json('anything', {})

    def test_invalid_task_and_instruction_cannot_consume_an_edit_response(self):
        tape = ReplayTape([{'expect': {'task_keys': ['safe'], 'instructions_contain': ['independent']},
                            'response': {'tool_calls': []}}])
        with self.assertRaises(ValueError):
            tape.generate_json('independent', {'task': {}})
        with self.assertRaises(ValueError):
            tape.generate_json('application repair', {'task': {'safe': True}})
        self.assertEqual(tape.calls, [])

    def test_ui_design_failed_parent_recovers_in_two_children_without_omitting_requirements(self):
        raw, tree, ui, _, _, _ = frontend_fixture()
        for node in ui['elements'].values():
            node['data'] = []
        contexts = {rid: {'id': rid} for rid in tree.leaves}
        calls = []
        def proposal(instructions, request):
            rids = list(request['requirements'])
            calls.append(rids)
            if len(rids) == 3:
                return {'elements': {}, 'pages': {}, 'requirement_ui': {}, 'step_ui': {}}
            return {'elements': deepcopy(ui['elements']), 'pages': deepcopy(ui['pages']),
                'requirement_ui': {rid: ui['requirements'][rid] for rid in rids},
                'step_ui': {sid: ui['steps'][sid] for rid in rids for sid in tree.own_steps[rid]}}
        with TemporaryDirectory() as directory, patch.dict('os.environ', {'ARC_AGENT_PROFILE': 'b4'}):
            arc = Path(directory) / '.arc'
            result = synthesize_batches(arc, tree, {}, contexts, Mock(generate_json=proposal), Mock(), 1)
            self.assertEqual([len(ids) for ids in calls], [3, 2, 1])
            self.assertTrue(all(result['requirements'][rid] for rid in tree.leaves))
            import json
            report = json.loads((arc / 'ui_design_batches.json').read_text(encoding='utf8'))
            self.assertEqual(report['status'], 'GREEN')
            self.assertEqual(report['tasks']['batch-1']['status'], 'SPLIT_RECOVERY')

    def test_ui_design_bad_child_remains_failed_and_valid_sibling_is_saved(self):
        from infrastructure.shared.agent.tasks import StageIncomplete
        _, tree, ui, _, _, _ = frontend_fixture()
        for node in ui['elements'].values():
            node['data'] = []
        def proposal(instructions, request):
            rids = list(request['requirements'])
            if 'REQ-A' in rids:
                return {'elements': {}, 'pages': {}, 'requirement_ui': {}, 'step_ui': {}}
            return {'elements': ui['elements'], 'pages': ui['pages'],
                'requirement_ui': {rid: ui['requirements'][rid] for rid in rids},
                'step_ui': {sid: ui['steps'][sid] for rid in rids for sid in tree.own_steps[rid]}}
        with TemporaryDirectory() as directory, patch.dict('os.environ', {'ARC_AGENT_PROFILE': 'b4'}):
            arc = Path(directory) / '.arc'
            with self.assertRaises(StageIncomplete):
                synthesize_batches(arc, tree, {}, {rid: {'id': rid} for rid in tree.leaves},
                                   Mock(generate_json=proposal), Mock(), 1)
            import json
            result = json.loads((arc / 'ui_design.json').read_text(encoding='utf8'))
            self.assertTrue(result['requirements']['REQ-C'])
            self.assertFalse(result['requirements']['REQ-A'])

    def test_stage_replay_uses_tape_and_blocks_real_sdk_construction(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('stage_replay_tool', root / 'team-tools/replay-stage.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stage = importlib.import_module('08_implement_backend_tdd')
        def run(arc, max_turns):
            from infrastructure.shared.models.text import OpenAI
            with self.assertRaises(AssertionError):
                OpenAI(api_key='offline')
            response = stage.TextModel().generate_json('author', {'task': {'id': 'A'}})
            self.assertEqual(response, {'tool_calls': []})
            return {'status': 'GREEN'}
        with TemporaryDirectory() as directory:
            output = Path(directory)
            for name in ['.arc', 'node_modules', 'requirements']:
                (output / name).mkdir()
            with patch.object(stage, 'implement_backend_tdd', side_effect=run):
                report = module.replay(output, output / 'requirements', '08',
                    [{'expect': {'task_contains': {'id': 'A'}}, 'response': {'tool_calls': []}}])
            self.assertEqual(report['status'], 'GREEN')
            self.assertEqual(report['real_model_requests'], 0)


if __name__ == '__main__':
    unittest.main()
