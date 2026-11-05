"""Run one generation stage against explicit offline responses and real local checks."""
import argparse
from contextlib import ExitStack
import importlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from infrastructure.shared.agent.replay import ReplayTape, workload_digest
from infrastructure.shared.project.environment import EnvironmentBlocked

STAGES = {
    '08': ('08_implement_backend_tdd', 'implement_backend_tdd'),
    '09': ('09_design_ui', 'design_frontend_ui'),
    '10': ('10_implement_ui', 'implement_frontend_ui'),
    '11': ('11_design_frontend_triggers', 'design_frontend_triggers'),
    '12': ('12_implement_frontend_tdd', 'implement_frontend_triggers'),
}


def replay(workspace, requirements, stage, responses, max_turns=3):
    output = workspace.resolve()
    if not (output / '.arc').is_dir() or not (output / 'node_modules').is_dir():
        raise ValueError('Replay requires an existing local application, .arc artifacts and installed dependencies')
    if not requirements.is_dir():
        raise ValueError('Original requirements directory does not exist')
    tape = ReplayTape(responses)
    module_name, function_name = STAGES[stage]
    module = importlib.import_module(module_name)
    start = time.monotonic()
    report = {'kind': 'scripted_stage_replay', 'stage': stage, 'workspace': str(output),
              'real_model_requests': 0, 'official_evaluation': False, 'status': 'RUNNING'}
    report['workload_sha256'] = workload_digest(output, requirements)
    try:
        # No package installation, browser download or real model construction. Actual
        # compiler typechecks, HTTP servers, browser scenarios and builds still execute.
        with ExitStack() as stack:
            stack.enter_context(patch.object(module, 'TextModel', return_value=tape))
            for path in ['infrastructure.shared.models.text.OpenAI',
                         'infrastructure.shared.models.vision.OpenAI']:
                stack.enter_context(patch(path, side_effect=AssertionError('Real model disabled during replay')))
            for path in ['infrastructure.shared.project.dependencies.install_dependencies',
                'infrastructure.stages.frontend.ui.implementation.install_dependencies',
                'infrastructure.stages.frontend.triggers.implementation.install_dependencies',
                'infrastructure.stages.frontend.triggers.acceptance_batches.install_dependencies',
                'infrastructure.stages.frontend.ui.testing.FrontendChecks.install_browser']:
                stack.enter_context(patch(path))
            if hasattr(module, 'install_dependencies'):
                stack.enter_context(patch.object(module, 'install_dependencies'))
            function = getattr(module, function_name)
            if stage == '08':
                result = function(output / '.arc', max_turns=max_turns)
            elif stage in {'09', '11'}:
                result = function(requirements.resolve(), output / '.arc', max_attempts=max_turns)
            else:
                result = function(requirements.resolve(), output / '.arc', max_turns=max_turns)
        report.update(tape.finish())
        report['stage_status'] = result.get('status', 'DESIGNED')
        report['stage_summary'] = result.get('summary')
        report['status'] = 'FAILED' if result.get('status') in {'FAILED', 'COMPLETED_WITH_FAILURES'} else 'GREEN'
    except (ValueError, RuntimeError, OSError, AssertionError, EnvironmentBlocked) as error:
        report.update(status='FAILED', error=str(error), calls=tape.calls,
                      scripted_model_calls=len(tape.calls))
    report['seconds'] = round(time.monotonic() - start, 3)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path, help='DISPOSABLE generated application; source edits and build outputs are applied here')
    parser.add_argument('--requirements', required=True, type=Path)
    parser.add_argument('--stage', required=True, choices=list(STAGES))
    parser.add_argument('--responses', required=True, type=Path, help='JSON array of expect/response records')
    parser.add_argument('--max-turns', type=int, default=3)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    result = replay(args.workspace, args.requirements, args.stage,
                    json.loads(args.responses.read_text(encoding='utf-8-sig')), args.max_turns)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result['status'] == 'FAILED' else 0)


if __name__ == '__main__':
    main()
