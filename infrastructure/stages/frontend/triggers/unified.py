"""B2: one requirement-grounded test suite drives implementation and final acceptance."""

from infrastructure.shared.agent.context import SourceFiles
from infrastructure.shared.agent.discovery import project_index
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.recovery import complete_report, final_checks, implementation_task
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.stages.backend.testing import BackendChecks, require_green as require_backend_green
from infrastructure.stages.frontend.triggers.acceptance import (
    acceptance_path, lock_application_repair, require_acceptance, run_independent_acceptance)
from infrastructure.stages.frontend.triggers.e2e_runtime import FIXTURE, prepare_e2e
from infrastructure.stages.frontend.triggers.direct import DIRECT_IMPLEMENT_INSTRUCTIONS
from infrastructure.stages.frontend.triggers.testing import E2EChecks
from infrastructure.stages.frontend.ui.runtime import APPLICATION_ENTRYPOINTS, prepare_frontend
from infrastructure.stages.frontend.ui.testing import FrontendChecks, test_path as ui_test_path
from infrastructure.utils.files import save_json


def require_coverage(result, files, output):
    """A green aggregate cannot hide a missing or empty requirement test file."""
    require_acceptance(result)
    reported = {path.replace('\\', '/'): count for path, count in result.get('files', {}).items()}
    missing = []
    for relative in files:
        variants = {relative, relative.removeprefix('frontend/'),
            relative.removeprefix('frontend/tests/e2e/'), (output / relative).as_posix()}
        if not any(reported.get(path, 0) > 0 for path in variants):
            missing.append(relative)
    if missing:
        raise ValueError('No executed test cases for required suites: ' + ', '.join(missing))


def run_acceptance_first(input_dir, arc_dir, tree, schema, backend, ui, design,
        model, console, max_turns=10):
    """Generate each independent oracle once; repair app only; finish with full regression."""
    output = arc_dir.parent.resolve()
    prepare_frontend(output)
    prepare_e2e(output, backend)
    install_dependencies(output)
    checks, ui_checks, api_checks = E2EChecks(output), FrontendChecks(output), BackendChecks(output)
    checks.install_browser()
    console.show('B2 | Acceptance-first integration',
        'Generate original-requirement acceptance once, implement against it, then run complete final regression.')
    acceptance = run_independent_acceptance(input_dir, arc_dir, schema, backend, ui, design,
        model, console, min(max_turns, 6), process_report={'requirements': {}, 'verification': {}}, focused=True)
    files = [acceptance_path(rid) for rid in tree.leaves]
    ui_files = [ui_test_path(pid) for pid in ui['pages'] if (output / ui_test_path(pid)).is_file()]
    api_files = [path for aid in backend['apis'] if (path := selected_path(output, 'backend_test', aid))
        and (output / path).is_file()]

    def all_acceptance():
        missing = [path for path in files if not (output / path).is_file()]
        if missing:
            raise ValueError('Missing independent requirement suites: ' + ', '.join(missing))
        # Full final evaluation explicitly disables early stopping.
        return checks.tests(files, fail_fast=False)

    def verify():
        actions = {'typecheck': (lambda: checks.typecheck(files), None),
            'acceptance': (all_acceptance, lambda result: require_coverage(result, files, output))}
        if ui_files:
            actions['ui'] = (lambda: ui_checks.tests(ui_files), require_acceptance)
        actions.update(backend_typecheck=(api_checks.typecheck, None),
            backend_tests=(lambda: api_checks.tests(api_files), require_backend_green if api_files else None),
            build=(checks.build, None))
        return final_checks(console, **actions)

    verification = verify()
    repair_entry = {'status': 'NOT_NEEDED'}
    if any(item['status'] == 'FAILED' for item in verification.values()) and all((output / f).is_file() for f in files):
        selection = SourceFiles(output, ui)
        backend_selection = SourceFiles(output, root='backend/src', tests_root='backend/tests')
        workspace = selection.workspace(paths=APPLICATION_ENTRYPOINTS,
            references=[FIXTURE, 'backend/tests/support/context.ts', 'frontend/src/ui-runtime.ts',
                'frontend/package.json', 'frontend/tsconfig.json'])
        lock_application_repair(workspace)
        index = project_index(output, kinds=('schema', 'api', 'page', 'ui_element', 'ui_data',
            'trigger', 'requirement', 'test_requirement', 'convention', 'file'),
            file_roots=('frontend/src', 'frontend/tests', 'backend/src', 'backend/tests'))

        def feedback(value):
            # Failed results contain structured diagnostics; do not repeat the
            # same report again inside an exception's repr string.
            value = {name: {key: child for key, child in item.items()
                if key != 'error' or item.get('result') is None}
                for name, item in value.items()} if isinstance(value, dict) and all(
                    isinstance(item, dict) and 'status' in item for item in value.values()) else value
            result = selection.feedback(workspace, backend_selection.feedback(workspace, value))
            lock_application_repair(workspace)
            return result

        def gate():
            nonlocal verification
            verification = verify()
            if any(item['status'] == 'FAILED' for item in verification.values()):
                from infrastructure.stages.frontend.triggers.scope import TriggerCheckFailure
                raise TriggerCheckFailure('Full regression remains failed', verification)
            return verification

        repair_entry['status'] = 'REPAIRING'
        with implementation_task(output, repair_entry, console, 'B2 / final regression repair'):
            run_file_agent(model, DIRECT_IMPLEMENT_INSTRUCTIONS + '\nRepair the full-regression failures. All tests are read-only. '
                'Use original requirement evidence before changing shared behavior; preserve all accepted workflows.',
                {'task': 'final_regression_repair', 'requirement_ids': list(tree.leaves),
                    'acceptance_suites': files, 'application_entrypoints': list(APPLICATION_ENTRYPOINTS)},
                workspace, gate, min(max_turns, 4), console, 'B2 / final regression repair',
                feedback=verification, feedback_filter=feedback, context_index=index)
            repair_entry['status'] = 'GREEN'
        if repair_entry['status'] == 'FAILED':
            # Failed repair restores the baseline; never publish the rejected candidate's checks.
            verification = verify()

    complete = verification.get('acceptance', {}).get('status') == 'GREEN'
    if complete:
        for rid in tree.leaves:
            entry = acceptance['requirements'].setdefault(rid, {})
            if entry.get('status') != 'GREEN':
                entry['previous_status'] = entry.get('status')
                entry['recovery'] = 'full_final_acceptance'
            entry['status'] = 'GREEN'
        acceptance['status'] = 'GREEN'
    result = {'mode': 'acceptance_first', 'requirements': acceptance['requirements'],
        'final_repair': repair_entry, 'summary': {'requirements': len(tree.leaves),
            'e2e_tests': (verification.get('acceptance', {}).get('result') or {}).get('passed', 0),
            'ui_tests': (verification.get('ui', {}).get('result') or {}).get('passed', 0)}}
    complete_report(result, result['requirements'].values(), verification)
    save_json(arc_dir / 'independent_acceptance.json', acceptance)
    save_json(arc_dir / 'frontend_e2e.json', result)
    return result
