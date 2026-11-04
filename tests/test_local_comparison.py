"""Do not attribute different selected workloads to an optimization."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest


class LocalComparison(unittest.TestCase):
    def test_same_sources_but_different_api_or_check_selection_are_not_comparable(self):
        spec = importlib.util.spec_from_file_location('compare_local',
            Path(__file__).resolve().parents[1] / 'team-tools/compare-local.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        first = {'kind': 'local_generated_stage_check', 'stage': '08', 'scope': 'selected_targets',
                 'workload_sha256': 'same-source', 'targets': {'A': 'backend/tests/A.test.ts'},
                 'checks': {'tests': {'status': 'GREEN'}}, 'status': 'GREEN', 'seconds': 2}
        other = deepcopy(first)
        other.update(targets={'B': 'backend/tests/B.test.ts'}, seconds=1)
        self.assertFalse(module.compare([first, other])['comparable_workload'])
        other = deepcopy(first)
        other['checks'] = {'typecheck': {'status': 'GREEN'}}
        self.assertFalse(module.compare([first, other])['comparable_workload'])
        matching = module.compare([first, deepcopy(first)])
        self.assertTrue(matching['comparable_workload'])
        self.assertIsNone(matching['token_savings'])
        self.assertIsNone(matching['monetary_savings'])


if __name__ == '__main__':
    unittest.main()
