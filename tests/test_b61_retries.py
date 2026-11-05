"""Inject tool and acceptance failures and assert transport stops after three attempts."""
from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.agent.batching import split_failed
from infrastructure.shared.agent.loop import AgentExhausted, run_file_agent
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.proposals import propose_json


class ThreeAttemptRecovery(unittest.TestCase):
    def setUp(self):
        self.settings=patch.dict(os.environ,{'ARC_AGENT_PROFILE':'b4','ARC_B3_MAX_EDIT_ROUNDS':'3',
            'ARC_B3_MAX_PROPOSAL_ATTEMPTS':'3','ARC_B3_MAX_SAME_FAILURES':'3'})
        self.settings.start();self.addCleanup(self.settings.stop)

    def test_protected_writes_stop_after_three_changing_responses_and_preserve_files(self):
        with TemporaryDirectory() as directory:
            output=Path(directory)
            app='frontend/src/app.ts';frozen='frontend/tests/e2e/acceptance/frozen.spec.ts'
            for path,text in ((app,'export const value = 1;\n'),(frozen,'original assertion')):
                (output/path).parent.mkdir(parents=True,exist_ok=True);(output/path).write_text(text,encoding='utf8')
            workspace=FileTools(output,[app],[frozen]);requests=[]
            def generate(rules,payload):
                requests.append(deepcopy(payload));number=len(requests)
                # Vary the response, diagnosis, call index and content; same protected path.
                return {'diagnosis':{'attempt':number},'tool_calls':[
                    *[{'tool':'edit_file','path':app,'operation':'append','new_content':'// staged\n'} for _ in range(number)],
                    {'tool':'edit_file','path':frozen,'operation':'append','new_content':'// bad '+str(number)}]}
            gate=Mock()
            # Raising the total cap proves stable permission identity itself still stops at three.
            with patch.dict(os.environ,{'ARC_B3_MAX_EDIT_ROUNDS':'8'}), self.assertRaises(AgentExhausted) as failure:
                run_file_agent(Mock(generate_json=generate),'repair',{},workspace,gate,10,Mock(),'permission')
            self.assertEqual(len(requests),3);gate.assert_not_called()
            self.assertEqual((output/app).read_text(),'export const value = 1;\n')
            self.assertEqual((output/frozen).read_text(),'original assertion')
            hint=requests[1]['feedback'][-1]['file_permissions']
            self.assertEqual(hint['blocked_path'],frozen)
            self.assertEqual(hint['writable_existing_paths'],[app])
            self.assertFalse(failure.exception.feedback['retryable'])
            records=[json.loads(line) for line in (output/'.arc/b3_metrics.jsonl').read_text().splitlines()]
            self.assertEqual(records[-1]['repeats'],3)
            queue=[([{'id':'A'},{'id':'B'}],0)]
            entry={'status':'FAILED','feedback':failure.exception.feedback}
            split_failed(queue,1,queue[0][0],0,entry,output,'08')
            self.assertEqual(len(queue),1)
            self.assertEqual(entry['recovery'],'stopped_nonretryable_tool_failure')

    def test_different_check_failures_still_cannot_use_a_fourth_edit_round(self):
        with TemporaryDirectory() as directory:
            output=Path(directory);model=Mock();model.generate_json.return_value={'tool_calls':[]}
            gate=Mock(side_effect=[ValueError('A failed'),ValueError('B failed'),ValueError('C failed'),{'green':True}])
            with self.assertRaises(AgentExhausted) as failure:
                run_file_agent(model,'repair',{},FileTools(output),gate,10,Mock(),'changing failures')
            self.assertEqual(model.generate_json.call_count,3)
            self.assertEqual(gate.call_count,3);self.assertEqual(failure.exception.turns,3)

    def test_tool_error_can_recover_without_unprotecting_target(self):
        with TemporaryDirectory() as directory:
            output=Path(directory);app='frontend/src/app.ts'
            (output/app).parent.mkdir(parents=True);(output/app).write_text('export const x=0;\n',encoding='utf8')
            workspace=FileTools(output,[app]);model=Mock()
            model.generate_json.side_effect=[
                {'tool_calls':[{'tool':'edit_file','path':'frontend/src/runtime/ui.tsx','operation':'create','new_content':'bad'}]},
                {'tool_calls':[{'tool':'edit_file','path':app,'operation':'append','new_content':'// fixed\n'}]}]
            gate=Mock(return_value={'green':True})
            result=run_file_agent(model,'repair',{},workspace,gate,10,Mock(),'recover')
            self.assertEqual(result['turns'],2);gate.assert_called_once()
            self.assertFalse((output/'frontend/src/runtime/ui.tsx').exists())

    def test_no_matches_error_does_not_gain_extra_attempts_from_new_span_text(self):
        with TemporaryDirectory() as directory:
            output=Path(directory);app='frontend/src/app.ts'
            (output/app).parent.mkdir(parents=True);(output/app).write_text('existing\n',encoding='utf8')
            model=Mock();calls=[]
            def generate(rules,payload):
                calls.append(payload)
                return {'tool_calls':[{'tool':'edit_file','path':app,'operation':'replace',
                    'old_content':'missing-'+str(len(calls)),'new_content':'new'}]}
            model.generate_json.side_effect=generate
            with patch.dict(os.environ,{'ARC_B3_MAX_EDIT_ROUNDS':'8'}),self.assertRaises(AgentExhausted):
                run_file_agent(model,'repair',{},FileTools(output,[app]),Mock(),10,Mock(),'stale span')
            self.assertEqual(len(calls),3)
            self.assertEqual((output/app).read_text(),'existing\n')

    def test_bad_json_stops_at_three_without_calling_an_acceptance_gate(self):
        with TemporaryDirectory() as directory:
            model=Mock();model.generate_json.side_effect=json.JSONDecodeError('Invalid JSON','?',0)
            gate=Mock()
            with self.assertRaises(AgentExhausted):
                run_file_agent(model,'repair',{},FileTools(Path(directory)),gate,10,Mock(),'JSON')
            self.assertEqual(model.generate_json.call_count,3);gate.assert_not_called()
        model=Mock();model.generate_json.return_value={}
        with self.assertRaisesRegex(RuntimeError,'exhausted 3 proposals'):
            propose_json(model,'plan',{},lambda result:result['entities'],Mock(),'plan',10)
        self.assertEqual(model.generate_json.call_count,3)


if __name__=='__main__':unittest.main()
