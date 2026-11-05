"""Repeat B6's full build/browser gate locally, without models or dependency downloads."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infrastructure.compact.compiler import CompactCompiler
from infrastructure.stages.frontend.triggers.testing import E2EChecks
from infrastructure.utils.files import save_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('application', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    output = args.application.resolve()
    receipt = args.report or output / '.arc/compact-local-check.json'
    try:
        state = json.loads((output / '.arc/compact-state.json').read_text(encoding='utf8'))
        compiler = CompactCompiler(output / '.arc/unused-input', output)
        compiler.data = {'coverage': state['coverage_ids']}
        compiler.frozen_tests = state['test_sha256']
        compiler.checks = E2EChecks(output)
        result = {'status': 'GREEN', 'checks': compiler.verify(), 'model_calls': 0}
    except Exception as error:
        result = {'status': 'FAILED', 'error': str(error), 'model_calls': 0}
    save_json(receipt, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'GREEN' else 1


if __name__ == '__main__': raise SystemExit(main())
