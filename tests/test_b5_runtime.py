"""Real app + original scenarios + a browser-only journey, with scripted model edits."""
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from notes_runtime_fixture import create_notes_app, isolated_source, JOURNEY_SOURCE
from infrastructure.stages.frontend.triggers.acceptance_batches import run_acceptance_batches
from infrastructure.stages.frontend.triggers.testing import E2EChecks


class RealScenarioAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.getenv('ARC_CONTRACT_TEST_NODE_MODULES')
        if not path or not shutil.which('node'):
            raise unittest.SkipTest('Set ARC_CONTRACT_TEST_NODE_MODULES to existing Node dependencies')
        cls.dependencies = Path(path).resolve()

    def test_independent_coverage_user_journey_and_protected_application_repair(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            tree,schema,backend,ui,design = create_notes_app(output)
            junction = output / 'node_modules'
            if os.name == 'nt':
                quote=lambda p:"'"+str(p).replace("'","''")+"'"
                subprocess.run(['powershell','-NoProfile','-Command','New-Item -ItemType Junction -Path '
                                +quote(junction)+' -Target '+quote(self.dependencies)+' | Out-Null'],check=True)
            else: junction.symlink_to(self.dependencies,target_is_directory=True)
            try:
                app = output / 'frontend/src/App.tsx'
                app.write_text(app.read_text(encoding='utf8').replace('fetch("/api/notes"','fetch("/api/broken"'),encoding='utf8')
                calls=[]
                class Model:
                    def generate_json(inner, instructions, request):
                        task=request['task'];calls.append(task)
                        if 'original_requirements' in task:
                            self.assertTrue(all(not item['writable'] for path,item in request['files'].items() if '/tests/' in path))
                            self.assertIn('shared_failure_context',task)
                            return {'tool_calls':[{'tool':'edit_file','path':'frontend/src/App.tsx','operation':'replace',
                                'old_content':'fetch("/api/broken"','new_content':'fetch("/api/notes"'}]}
                        self.assertFalse(any(path.startswith(('frontend/src/','backend/src/')) for path in request['files']))
                        if task.get('journey'):
                            return {'tool_calls':[{'tool':'edit_file','path':task['journey']['test_path'],
                                                  'operation':'create','new_content':JOURNEY_SOURCE}]}
                        return {'tool_calls':[{'tool':'edit_file','path':item['test_path'],'operation':'create',
                            'new_content':isolated_source(rid)} for rid,item in task['requirements'].items()]}
                with patch.dict(os.environ,{'ARC_AGENT_PROFILE':'b4'}), \
                     patch('infrastructure.stages.frontend.triggers.acceptance_batches.install_dependencies'), \
                     patch.object(E2EChecks,'install_browser'):
                    result=run_acceptance_batches(output/'requirements',output/'.arc',schema,backend,ui,design,Model(),Mock(),max_turns=2)
                self.assertEqual(result['status'],'GREEN',result.get('verification'))
                self.assertEqual(result['summary']['e2e_tests'],4)
                self.assertEqual(result['journey']['status'],'GREEN')
                self.assertEqual(result['scenario_coverage']['requirements'],tree.leaves)
                self.assertEqual(len(calls),3) # one independent batch, one app repair, one journey author
                self.assertEqual(result['journey_coverage']['requirements'],tree.leaves)
            finally:
                if os.name=='nt':os.rmdir(junction)
                else:junction.unlink()


if __name__=='__main__':unittest.main()
