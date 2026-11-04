"""B3 orchestration, protected tests, exact contexts and bounded failure behavior."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from infrastructure.shared.agent.efficiency import compact_context, enabled, failure_fingerprint
from infrastructure.shared.agent.loop import run_file_agent, AgentExhausted
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.agent.discovery import ContextIndex
from infrastructure.shared.agent.evidence import repair_evidence
from infrastructure.shared.models.text import TextModel
from infrastructure.shared.project.entrypoints import remember_path
from infrastructure.stages.backend.context import requirement_context
from infrastructure.stages.frontend.triggers.batching import plan_groups, group_context, require_suites, lock_tests, run_flow_batches, check_ui
from infrastructure.stages.frontend.triggers.scope import TriggerCheckFailure
from test_frontend_flow import frontend_fixture


class B3Mechanisms(unittest.TestCase):
    def setUp(self):
        self.flags = patch.dict(os.environ, {'ARC_AGENT_PROFILE': 'b3'})
        self.flags.start()
        self.addCleanup(self.flags.stop)

    def test_grouping_preserves_order_and_splits_disjoint_or_oversized_work(self):
        def row(i, page):
            return {'id': i, 'pages': [page], 'apis': [], 'context': {'text': 'x' * 20}}
        records = [row('a', 'editor'), row('b', 'editor'), row('c', 'reader'), row('d', 'reader')]
        self.assertEqual([[r['id'] for r in g] for g in plan_groups(records, 3, 1000)], [['a','b'],['c','d']])
        self.assertEqual([len(g) for g in plan_groups(records, 1, 1000)], [1]*4)
        self.assertEqual([len(g) for g in plan_groups(records, 4, 40)], [1]*4)
        self.assertEqual([r['id'] for g in plan_groups(records, 2, 1000) for r in g], ['a','b','c','d'])

    def test_exact_dedup_keeps_distinct_or_stale_excerpts_and_aliased_records(self):
        records = {'x': {'name': 'canonical'}}
        payload = {'files': {'x.ts': {'content': 'a\nb\n'}}, 'read_files': {'x.ts': [
            {'content':'a\n','start_line':1,'end_line':1,'total_lines':2},
            {'content':'old','start_line':2,'end_line':2,'total_lines':2}]},
            'context_result': {'kind':'api','records':records}, 'context_records':{'api':records}}
        value = compact_context(payload)
        self.assertEqual(value['read_files']['x.ts'][0]['content'], 'old')
        self.assertEqual(value['context_result']['retained_record_ids'], ['x'])
        self.assertEqual(value['context_records']['api'], records)
        self.assertEqual(len(payload['read_files']['x.ts']), 2)

    def test_controls_can_be_disabled_individually(self):
        with patch.dict(os.environ, {'ARC_B3_FLOW_BATCHES':'0'}):
            self.assertFalse(enabled('flow_batches'))
            self.assertTrue(enabled('context_reuse'))
        with patch.dict(os.environ, {'ARC_AGENT_PROFILE':'b0'}):
            self.assertFalse(enabled('bounded_repair'))

    def test_text_transport_sends_compacted_context_without_a_real_client(self):
        model=TextModel.__new__(TextModel)
        model.name='offline';model.reasoning='provider'
        model._request=Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content='{"ok":true}',refusal=None))]))
        payload={'files':{'x.ts':{'content':'same\n'}},'read_files':{'x.ts':[
            {'content':'same\n','start_line':1,'end_line':1,'total_lines':1}]}}
        self.assertEqual(model.generate_json('rules',payload),{'ok':True})
        sent=json.loads(model._request.call_args.kwargs['messages'][1]['content'])
        self.assertNotIn('read_files',sent)
        self.assertIn('read_files',payload)

    def test_tool_examples_never_point_outside_restricted_read_scope(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            p=root/'frontend/tests/e2e/support/context.ts';p.parent.mkdir(parents=True);p.write_text('fixture')
            files=FileTools(root, references=['frontend/tests/e2e/support/context.ts'],
                readable=['frontend/tests/e2e/support/context.ts'])
            examples=[s['example'] for s in files.schemas() if 'example' in s]
            self.assertTrue(examples)
            self.assertTrue(all(x['path'] in files.readable for x in examples))
            with self.assertRaises(ValueError) as error:
                files.execute([{'tool':'read_file','path':'backend/src/db/initialize.ts'}])
            self.assertNotIn('backend/src/db/initialize.ts',json.dumps(error.exception.feedback.get('example')))

    def test_fingerprint_ignores_timings_but_not_test_identity(self):
        a={'elapsed_seconds':1,'failures':['test-A failed'],'output':'long duration 1'}
        b={**a,'elapsed_seconds':100,'output':'long duration 100'}
        self.assertEqual(failure_fingerprint(a),failure_fingerprint(b))
        self.assertNotEqual(failure_fingerprint(a),failure_fingerprint({**b,'failures':['test-B failed']}))

    def test_repeated_acceptance_failures_stop_and_read_queries_have_actual_call_bound(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            p=root/'frontend/src/a.ts';p.parent.mkdir(parents=True);p.write_text('export const a = 0;')
            files=FileTools(root, ['frontend/src/a.ts'])
            model=Mock();model.generate_json.return_value={'tool_calls':[]}
            gate=Mock(side_effect=TriggerCheckFailure('broken',{'failures':['same assertion'],'elapsed_seconds':1}))
            with patch.dict(os.environ,{'ARC_B3_MAX_SAME_FAILURES':'2'}), self.assertRaises(AgentExhausted):
                run_file_agent(model,'repair',{},files,gate,10,Mock(),'task')
            self.assertEqual(model.generate_json.call_count,2)
            model.reset_mock();model.generate_json.return_value={'tool_calls':[{'tool':'read_file','path':'frontend/src/a.ts'}]}
            with self.assertRaises(AgentExhausted):
                run_file_agent(model,'read',{},files,gate,10,Mock(),'reads',max_calls=3)
            self.assertEqual(model.generate_json.call_count,3)

    def test_locked_tests_cannot_become_writable_after_expansion(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            p=root/'frontend/tests/e2e/a.spec.ts';p.parent.mkdir(parents=True);p.write_text('assert required;')
            workspace=FileTools(root,['frontend/tests/e2e/a.spec.ts','frontend/src/a.ts'])
            lock_tests(workspace,lambda p:p.startswith('frontend/src/'))
            with self.assertRaisesRegex(ValueError,'not writable'):
                workspace.execute([{'tool':'edit_file','path':'frontend/tests/e2e/a.spec.ts',
                    'operation':'append','new_content':'weakened'}])
            self.assertEqual(p.read_text(),'assert required;')

    def test_design_discovery_cannot_escape_the_logical_call_budget(self):
        model=Mock();model.generate_json.return_value={'context_request':{'kind':'api','ids':['a']}}
        with patch.dict(os.environ, {'ARC_B3_MAX_DESIGN_CALLS':'3'}), self.assertRaisesRegex(RuntimeError,'3 calls'):
            propose_json(model,'design',{},lambda x:x,Mock(),'design',context_index=ContextIndex({'api':{'a':{'description':'a'}}}))
        self.assertEqual(model.generate_json.call_count,3)

    def test_green_aggregate_cannot_hide_missing_suite_or_skipped_tests(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            with self.assertRaises(ValueError):
                require_suites({'returncode':0,'passed':1,'failed':0,'files':{'a.spec.ts':1}},
                    ['frontend/tests/e2e/a.spec.ts','frontend/tests/e2e/b.spec.ts'],root)
            with self.assertRaises(ValueError):
                require_suites({'returncode':0,'passed':1,'failed':0,'skipped':1,'files':{'a.spec.ts':1}},
                    ['frontend/tests/e2e/a.spec.ts'],root)

    def test_group_contract_context_includes_other_owners(self):
        _,tree,ui,design,backend,_=frontend_fixture()
        contexts={rid:requirement_context(tree,rid) for rid in tree.leaves}
        record={'id':'REQ-A','apis':['API-SAVE'],'context':{'page_subtrees':{},'triggers':{},'obligations':{}}}
        value=group_context([record],backend,contexts)
        self.assertEqual(value['shared_api_owners']['API-SAVE'],['REQ-A','REQ-B'])
        self.assertIn('REQ-B',value['owner_requirements'])

    def test_pre_repair_recheck_is_bounded_and_keeps_the_first_failure(self):
        first={'returncode':1,'passed':0,'failed':1,'failures':['locator timeout']}
        green={'returncode':0,'passed':1,'failed':0}
        checks=Mock();checks.tests.side_effect=[first,green]
        group={}
        self.assertEqual(check_ui(checks,['a'],group,recheck_before_repair=True),green)
        self.assertEqual(checks.tests.call_count,2)
        self.assertEqual(group['ui_pre_repair_rechecks'][0]['first'],first)
        checks.tests.reset_mock();checks.tests.side_effect=[first,first]
        self.assertEqual(check_ui(checks,['a'],{},recheck_before_repair=True),first)
        self.assertEqual(checks.tests.call_count,2)

    def test_evidence_uses_failed_check_sources_and_paths_not_successful_inventory(self):
        evidence=repair_evidence({'ok':{'returncode':0,'output':'backend/src/unrelated.ts /api/ignored'},
            'bad':{'returncode':1,'failures':['HTTP 500 /api/items/123 at backend/src/api/items.ts:17']}},
            {'apis':{'API-ITEM':{'signature':{'method':'GET','path':'/api/items/{id}'}}}})
        self.assertEqual(evidence['referenced_sources'],['backend/src/api/items.ts'])
        self.assertEqual(evidence['related_api_ids'],['API-ITEM'])
        self.assertIn('http',evidence['categories'])

    def exercise_group(self, fail_group=False):
        from infrastructure.stages.frontend.triggers import implementation as impl
        with TemporaryDirectory() as temp:
            root=Path(temp);arc=root/'.arc';arc.mkdir()
            _,tree,ui,design,backend,_=frontend_fixture()
            contexts={rid:requirement_context(tree,rid) for rid in tree.leaves}
            schema={'entities':{'Note':{'fields':{}}}}
            source=root/'frontend/src/state.ts';source.parent.mkdir(parents=True);source.write_text('export const ready = false;\n')
            for pid in ui['pages']:
                remember_path(root,'page',pid,'frontend/src/state.ts')
            checks=Mock();checks.typecheck.return_value={'returncode':0,'output':''}
            def tests(paths):
                good='true' in source.read_text()
                return {'returncode':0 if good else 1,'passed':len(paths) if good else 0,
                    'failed':0 if good else 1,'output':'passed' if good else 'real failure',
                    'files':{p.removeprefix('frontend/tests/e2e/'):1 for p in paths}}
            checks.tests.side_effect=tests
            ui_checks=Mock();ui_checks.tests.return_value={'returncode':0,'passed':1,'failed':0}
            labels=[]; implementations=[]
            def agent(model,instructions,task,workspace,gate,max_turns,console,label,**kw):
                labels.append(label)
                if 'test generation' in label:
                    rid=task['requirement']['id']
                    path=f'frontend/tests/e2e/{rid}.spec.ts'
                    workspace.execute([{'tool':'edit_file','path':path,'operation':'create','new_content':'test content'}])
                else:
                    implementations.append(task['requirement_ids'])
                    self.assertFalse(workspace.can_write('frontend/tests/e2e/REQ-A.spec.ts'))
                    workspace.execute([{'tool':'edit_file','path':'frontend/src/state.ts','operation':'replace',
                        'old_content':'false','new_content':'true'}])
                    if fail_group and task['requirement_ids']==['REQ-A','REQ-B']:
                        raise AgentExhausted(label,1,{'error':'injected'})
                return {'turns':1,'checks':gate()}
            report={'requirements':{}}
            with patch.dict(os.environ, {'ARC_B3_FLOW_SIZE':'2'}), \
                 patch('infrastructure.stages.frontend.triggers.batching.run_file_agent',side_effect=agent), \
                 patch.object(impl,'verify_frontend',side_effect=lambda *args:args[-1]):
                result=run_flow_batches(arc,tree,schema,backend,ui,design,contexts,Mock(),Mock(),
                    report,checks,ui_checks,5,2)
            if fail_group:
                self.assertEqual(result['requirements']['REQ-A']['status'],'FAILED')
                self.assertEqual(result['requirements']['REQ-B']['status'],'FAILED')
                self.assertEqual(result['requirements']['REQ-C']['status'],'GREEN')
                self.assertIn(['REQ-C'],implementations)
            else:
                self.assertEqual(implementations,[['REQ-A','REQ-B']])
                self.assertTrue(all(result['requirements'][rid]['status']=='GREEN' for rid in tree.leaves))
            self.assertEqual(len([x for x in labels if 'test generation' in x]),3)

    def test_two_related_requirements_share_one_implementation_loop(self):
        self.exercise_group()

    def test_failed_group_rolls_back_and_later_group_is_attempted(self):
        self.exercise_group(fail_group=True)


if __name__=='__main__':
    unittest.main()
