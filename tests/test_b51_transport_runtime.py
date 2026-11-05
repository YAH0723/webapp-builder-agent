"""Exercise the real request policy against the existing real-browser scenario replay."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_b5_runtime as fixture
from infrastructure.shared.models.text import TextModel


class PolicyBrowserReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.RealScenarioAcceptance.setUpClass()

    def test_real_model_request_path_preserves_independent_author_and_journey_behavior(self):
        original=fixture.run_acceptance_batches
        requests=[]
        def run(input_dir,arc_dir,schema,backend,ui,design,scripted,console,max_turns):
            model=TextModel.__new__(TextModel)
            model.name='deepseek-flash';model.reasoning='low';model.max_output_tokens=320000;model.json_mode=True
            def transport(**kwargs):
                frame=json.loads(kwargs['messages'][1]['content'])
                requests.append({'limit':kwargs['_output_limit'],'frame':frame})
                result=scripted.generate_json(kwargs['messages'][0]['content'],frame)
                return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=json.dumps(result),refusal=None))])
            model._request=transport
            return original(input_dir,arc_dir,schema,backend,ui,design,model,console,max_turns=max_turns)
        test=fixture.RealScenarioAcceptance('test_independent_coverage_user_journey_and_protected_application_repair')
        with patch.object(fixture,'run_acceptance_batches',side_effect=run):
            test.test_independent_coverage_user_journey_and_protected_application_repair()
        self.assertEqual(len(requests),3)
        self.assertTrue(all(r['limit']<=48000 for r in requests))
        repair=next(r['frame'] for r in requests if 'original_requirements' in r['frame']['task'])
        self.assertTrue(all('original_requirement' not in member for member in repair['task']['requirements'].values()))


if __name__=='__main__':unittest.main()
