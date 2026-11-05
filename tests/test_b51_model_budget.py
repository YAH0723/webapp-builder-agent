"""Transport policy, exact context preservation and local budget rejection."""
from copy import deepcopy
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.agent.model_policy import (inference_policy, budget_context,
    ContextBudgetExceeded, task_call, serialized_size)
from infrastructure.shared.models.text import TextModel
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.tools import FileTools
from pathlib import Path
from tempfile import TemporaryDirectory


class ModelBudgets(unittest.TestCase):
    def setUp(self):
        self.flags = patch.dict(os.environ, {'ARC_AGENT_PROFILE':'b4'})
        self.flags.start();self.addCleanup(self.flags.stop)
        self.reason = os.environ.pop('MODEL_REASONING', None)
        self.addCleanup(lambda: os.environ.__setitem__('MODEL_REASONING',self.reason) if self.reason is not None else os.environ.pop('MODEL_REASONING',None))
        self.model = SimpleNamespace(reasoning='low',max_output_tokens=70000)

    def test_task_modes_preserve_explicit_user_choice_and_only_escalate_once(self):
        edit={'task':{'page_paths':{'x':'x.tsx'}}}
        self.assertEqual(inference_policy(edit,self.model)['reasoning'],'none')
        self.assertEqual(inference_policy({'task':{'coverage_steps':{}}},self.model)['reasoning'],'low')
        with patch.dict(os.environ,{'MODEL_REASONING':'low'}):
            self.assertEqual(inference_policy(edit,self.model)['reasoning'],'low')
        state={}
        with task_call(state,3,2):
            upgraded=inference_policy(edit,self.model)
            self.assertEqual(upgraded['reasoning'],'high')
            self.assertLessEqual(upgraded['output_limit'],32000)
            self.assertEqual(inference_policy(edit,self.model)['reasoning'],'low')
        with task_call(state,4,3):
            self.assertEqual(inference_policy(edit,self.model)['reasoning'],'low')

    def test_output_budget_expands_after_rejection_but_honors_global_ceiling(self):
        task={'task':{'page_paths':{}}}
        self.assertEqual(inference_policy(task,self.model)['output_limit'],48000)
        with task_call({},2,0):
            self.assertEqual(inference_policy(task,self.model)['output_limit'],70000)

    def test_windowed_files_keep_scope_existence_and_complete_canonical_requirements(self):
        task={'requirements':{'R':{'Given':'existing','When':'save','Then':'persist'}}}
        payload={'task':task,'files':{'large.ts':{'content':'export const value=1;\n'*2000,'writable':True}},
                 'file_access':{'readable_paths':['large.ts']}}
        original=deepcopy(payload)
        with patch.dict(os.environ,{'ARC_B5_MAX_REQUEST_CHARS':'12000'}):
            result,metrics=budget_context('rules',payload)
        self.assertLessEqual(serialized_size('rules',result),12000)
        self.assertEqual(result['task'],task)
        self.assertEqual(result['file_access'],payload['file_access'])
        self.assertTrue(result['files']['large.ts']['exists'])
        self.assertTrue(result['files']['large.ts']['writable'])
        self.assertIsNone(result['files']['large.ts']['content'])
        self.assertEqual(payload,original)

    def test_paginated_reads_keep_exact_line_coordinates_and_signal_remaining_text(self):
        text=''.join(f'line {i} '+('x'*60)+'\n' for i in range(1,1001))
        payload={'task':{'id':'R'},'read_files':{'x.ts':[{'content':text,'start_line':1,'end_line':1000,'total_lines':1000}]}}
        with patch.dict(os.environ,{'ARC_B5_MAX_REQUEST_CHARS':'20000'}):
            result,metrics=budget_context('rules',payload)
        excerpt=result['read_files']['x.ts'][0]
        self.assertEqual(excerpt['content'],''.join(text.splitlines(keepends=True)[:160]))
        self.assertEqual(excerpt['end_line'],160)
        self.assertEqual(excerpt['next_start_line'],161)
        self.assertTrue(excerpt['has_more'])

    def test_only_exact_repair_duplicates_are_removed(self):
        original={'id':'R','When':'save','Then':'persist'}
        api={'signature':{'path':'/api/items'},'response':{'status':200},'postcondition':['persist']}
        payload={'task':{'requirements':{'R':{'original_requirement':original,'test_path':'r.spec.ts',
            'api_interfaces':{'A':{'signature':api['signature'],'response':api['response']}}}},
            'original_requirements':{'R':original},'backend_apis':{'A':api}}}
        result,_=budget_context('rules',payload)
        self.assertEqual(result['task']['original_requirements'],{'R':original})
        self.assertEqual(result['task']['backend_apis'],{'A':api})
        self.assertEqual(result['task']['requirements']['R'],{'test_path':'r.spec.ts'})
        payload['task']['requirements']['R']['original_requirement']={'id':'R','Then':'different'}
        result,_=budget_context('rules',payload)
        self.assertIn('original_requirement',result['task']['requirements']['R'])

    def make_model(self):
        model=TextModel.__new__(TextModel)
        model.name='deepseek-flash';model.reasoning='low';model.max_output_tokens=70000
        model.json_mode=True;model._token_parameter='max_completion_tokens';model.client=object()
        return model

    def test_actual_transport_receives_budget_and_reasoning_without_private_parameters(self):
        response=SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content='{"ok":true}',refusal=None))])
        model=self.make_model()
        with patch('infrastructure.shared.models.text.invoke',return_value=response) as invoke:
            self.assertEqual(model.generate_json('edit',{'task':{'page_paths':{}},'files':{}}),{'ok':True})
        args=invoke.call_args.args[1]
        self.assertEqual(args['max_completion_tokens'],48000)
        self.assertEqual(args['extra_body'],{'thinking':{'type':'disabled'}})
        self.assertNotIn('_output_limit',args)

    def test_oversized_canonical_task_sends_no_request_and_cannot_retry_locally(self):
        model=self.make_model(); model._request=Mock()
        with patch.dict(os.environ,{'ARC_B5_MAX_REQUEST_CHARS':'1000'}):
            with self.assertRaises(ContextBudgetExceeded):
                model.generate_json('rules',{'task':{'original_requirements':{'R':'z'*10000}}})
        model._request.assert_not_called()
        scripted=Mock(generate_json=Mock(side_effect=ContextBudgetExceeded('split')))
        with self.assertRaises(ContextBudgetExceeded):
            propose_json(scripted,'design',{},lambda p:p,Mock(),'design',10)
        self.assertEqual(scripted.generate_json.call_count,1)
        scripted.reset_mock()
        with TemporaryDirectory() as directory, self.assertRaises(ContextBudgetExceeded):
            run_file_agent(scripted,'edit',{},FileTools(Path(directory)),lambda:{},10,Mock(),'edit')
        self.assertEqual(scripted.generate_json.call_count,1)

    def test_cache_layout_keeps_stable_readonly_inputs_before_mutable_task(self):
        payload={'feedback':[{'error':'current'}],'task':{'id':'R'},'files':{
            'a.ts':{'content':'mutable','writable':True},'z.sql':{'content':'fixed','writable':False}},'tools':[]}
        result,_=budget_context('rules',payload)
        self.assertEqual(list(result)[:3],['tools','files','task'])
        self.assertEqual(list(result['files']),['z.sql','a.ts'])
        self.assertEqual(result['feedback'],payload['feedback'])

    def test_windowed_source_can_be_read_and_edited_through_actual_file_tools(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ,{'ARC_B5_MAX_REQUEST_CHARS':'16000'}):
            output=Path(directory);path=output/'large.ts'
            path.write_text(''.join(f'export const item{i}=0;\n' for i in range(1,3001)),encoding='utf8')
            model=self.make_model();calls=[]
            def response(**kwargs):
                payload=json.loads(kwargs['messages'][1]['content']);calls.append(payload)
                self.assertTrue(payload['files']['large.ts']['content_omitted_for_budget'])
                if len(calls)==1:
                    result={'tool_calls':[{'tool':'read_file','path':'large.ts','start_line':1200,'end_line':1200}]}
                else:
                    self.assertIn('export const item1200=0;',payload['read_files']['large.ts'][0]['content'])
                    result={'tool_calls':[{'tool':'edit_file','path':'large.ts','operation':'replace',
                                          'old_content':'export const item1200=0;','new_content':'export const item1200=1;'}]}
                return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=json.dumps(result),refusal=None))])
            model._request=response
            def gate():
                self.assertIn('export const item1200=1;',path.read_text(encoding='utf8'))
                return {'returncode':0}
            run_file_agent(model,'Read the relevant symbol and repair it',{'id':'R'},FileTools(output,['large.ts']),gate,2,Mock(),'windowed')
            self.assertEqual(len(calls),2)

    def test_design_windowing_requires_an_actual_advertised_retrieval_index(self):
        payload={'requirements':{'R':{'Then':'persist'}},'existing_design':{'pages':{},'elements':{
            'UI':{'prop':{'text':'x'*20000}}}},'context_kinds':['page','ui_element']}
        with patch.dict(os.environ,{'ARC_B5_MAX_REQUEST_CHARS':'2000'}):
            result,metrics=budget_context('rules',payload)
            self.assertEqual(result['requirements'],payload['requirements'])
            self.assertTrue(result['existing_design']['elements_omitted_for_budget'])
            self.assertEqual(result['existing_design']['existing_element_ids'],['UI'])
            self.assertTrue(metrics['design_windowed'])
            payload.pop('context_kinds')
            with self.assertRaises(ContextBudgetExceeded):budget_context('rules',payload)


if __name__=='__main__':unittest.main()
