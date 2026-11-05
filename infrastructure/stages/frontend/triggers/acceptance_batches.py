"""One independent acceptance suite family, batched authoring and application repair."""
from infrastructure.shared.agent.batching import chunks, setting, protect, feedback_for, log_plan, split_failed, enabled
from infrastructure.shared.agent.context import SourceFiles
from infrastructure.shared.agent.discovery import project_index
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.recovery import implementation_task, final_checks, complete_report
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.stages.backend.context import requirement_context, related_schema
from infrastructure.stages.backend.testing import BackendChecks, require_green as backend_green
from infrastructure.stages.frontend.triggers.acceptance import INSTRUCTIONS, acceptance_path, original_requirements
from infrastructure.stages.frontend.triggers.batching import require_suites
from infrastructure.stages.frontend.triggers.design import relevant_pages, api_ids
from infrastructure.stages.frontend.triggers.direct import IMPLEMENT_RULES
from infrastructure.stages.frontend.triggers.e2e_runtime import FIXTURE, prepare_e2e
from infrastructure.stages.frontend.triggers.implementation import editable_runtime_path, scenario_context
from infrastructure.stages.frontend.triggers.scope import TriggerCheckFailure
from infrastructure.stages.frontend.triggers.testing import E2EChecks
from infrastructure.stages.frontend.ui.runtime import prepare_frontend, APPLICATION_ENTRYPOINTS
from infrastructure.stages.frontend.ui.testing import FrontendChecks, require_green, test_path as ui_path
from infrastructure.utils.files import save_json
from infrastructure.stages.frontend.triggers.coverage import (RULES, JOURNEY_RULES, JOURNEY_PATH,
    coverage_steps, require_coverage, journey_records, shared_failure_context)


AUTHOR_RULES = '''BATCH CONTRACT overrides the single-requirement task shape:
task.requirements maps requirement IDs to {original_requirement, test_path, ui_interfaces,
api_interfaces}. Write EVERY member's test_path. shared_schema contains their complete
relevant database definitions once. Each file imports the shared fixture by a relative
path from its actual nested acceptance directory. Cover every original scenario's meaningful
business outcomes; combine compatible cases without omitting rejection/identity/persistence
requirements. Do not add arbitrary numbers of tests. Only supplied test_paths are writable.
No application or process-test sources are available. The gate compiles every member.
Do not query implementation source or derive an oracle from application observations.
'''


def acceptance_task(tree, schema, backend, ui, design, rids):
    tasks, all_apis = {}, {}
    for rid in rids:
        pages = relevant_pages(ui, rid)
        aids = set(backend['requirements'].get(rid, []))
        context = scenario_context(ui, design, rid)
        for trigger in context['triggers'].values():
            aids.update(api_ids(trigger))
        apis = {aid: backend['apis'][aid] for aid in sorted(aids)}
        all_apis.update(apis)
        if not pages:
            raise ValueError('No UI interface for original acceptance: ' + rid)
        tasks[rid] = {'original_requirement': requirement_context(tree, rid),
            'test_path': acceptance_path(rid),
            'ui_interfaces': {pid: {key: value for key, value in page.items()
                                   if key in ('route', 'root', 'elements')} for pid, page in pages.items()},
            'api_interfaces': {aid: {key: value for key, value in api.items()
                                    if key in ('signature', 'request', 'response')} for aid, api in apis.items()}}
    return {'requirements': tasks, 'shared_schema': related_schema(schema, all_apis.values())}, all_apis


def run_acceptance_batches(input_dir, arc_dir, schema, backend, ui, design, model, console,
                           max_turns=10):
    output = arc_dir.parent.resolve()
    tree = original_requirements(input_dir)
    prepare_frontend(output)
    prepare_e2e(output, backend)
    install_dependencies(output)
    checks, ui_checks, backend_checks = E2EChecks(output), FrontendChecks(output), BackendChecks(output)
    checks.install_browser()
    front = SourceFiles(output, ui)
    back = SourceFiles(output, root='backend/src', tests_root='backend/tests')
    records = [{'id': rid, 'requirement': requirement_context(tree, rid)} for rid in tree.leaves]
    groups = chunks(records, setting('ACCEPTANCE_BATCH_SIZE', 4), setting('BATCH_CONTEXT_CHARS', 80000))
    log_plan(output, '12', groups, len(records))
    report = {'status': 'RUNNING', 'mode': 'b5_scenario_acceptance',
              'requirements': {}, 'groups': [], 'scenario_coverage_enabled': enabled('scenario_coverage')}
    accepted = []
    ui_files = [ui_path(pid) for pid in ui['pages'] if (output / ui_path(pid)).is_file()]
    api_files = [p for aid in backend['apis'] if (p := selected_path(output, 'backend_test', aid))]
    index = project_index(output,
        kinds=('schema', 'api', 'page', 'ui_element', 'requirement', 'test_requirement', 'convention', 'file'),
        file_roots=('frontend/src', 'backend/src'))
    queue = [(group, 0) for group in groups]
    journey = journey_records([r for r in records if r['requirement']['steps']], backend, ui)
    if journey:
        queue.append((journey, 1))
    for number, (group, depth) in enumerate(queue, 1):
        rids = [record['id'] for record in group]
        is_journey = bool(group[0].get('_journey'))
        entry = {'status': 'GENERATING_TESTS', 'requirements': rids, 'split_depth': depth}
        report['groups'].append(entry)
        if is_journey:
            report['journey'] = entry
        else:
            for rid in rids:
                report['requirements'][rid] = {'status': 'GENERATING_TESTS', 'test_path': acceptance_path(rid)}
        save_json(arc_dir / 'independent_acceptance.json', report)
        # Independent generation is separately committed. A failed app repair must not
        # roll back or overwrite its independent oracle.
        try:
            task, apis = acceptance_task(tree, schema, backend, ui, design, rids)
            task['coverage_steps'] = coverage_steps(tree, rids)
            paths = [JOURNEY_PATH] if is_journey else [acceptance_path(rid) for rid in rids]
            if is_journey:
                task['journey'] = {'test_path': JOURNEY_PATH, 'requirement_ids': rids}
            author = FileTools(output, paths, references=[FIXTURE, 'backend/tests/support/context.ts'],
                readable=[*paths, FIXTURE, 'backend/tests/support/context.ts'])

            def compile_tests():
                missing = [path for path in paths if not (output / path).is_file()
                           or not (output / path).read_text(encoding='utf-8-sig').strip()]
                if missing:
                    raise ValueError('Missing independent suites: ' + ', '.join(missing))
                result = checks.typecheck(paths, full_source=False)
                if result['returncode']:
                    raise ValueError(result['output'])
                if enabled('scenario_coverage') or is_journey:
                    inventory = checks.inventory(paths)
                    if inventory['returncode']:
                        raise ValueError(inventory['output'])
                    require_coverage(inventory, tree, rids, executed=False, journey=is_journey)
                return result

            initial = None
            try:
                compile_tests()
            except (ValueError, RuntimeError) as error:
                initial = {'error': str(error)}
            if initial is not None:
                rules = INSTRUCTIONS + '\n' + AUTHOR_RULES + ('\n' + RULES if enabled('scenario_coverage') else '')
                if is_journey:
                    rules += '\n' + RULES + '\n' + JOURNEY_RULES
                agent = run_file_agent(model, rules, task, author,
                    compile_tests, max_turns, console, f'Acceptance batch {number} / independent author',
                    allow_discovery=False, max_calls=setting('BATCH_CALLS', 48), feedback=initial)
                entry['generation_turns'] = agent['turns']
            regression = list(dict.fromkeys([acceptance_path(rid) for rid in [*accepted, *([] if is_journey else rids)] ] + ([JOURNEY_PATH] if is_journey else [])))
            pages = {pid for rid in rids for pid in relevant_pages(ui, rid)}
            workspace = front.workspace(paths=front.paths('page', pages),
                references=[*regression, *ui_files, FIXTURE, 'frontend/src/ui-runtime.ts',
                            *APPLICATION_ENTRYPOINTS, 'frontend/package.json', 'frontend/tsconfig.json'])
            back.include(workspace, [*back.paths('api', apis), 'backend/src/api/register.ts'])
            from infrastructure.shared.project.contract_codegen import state as current_transport
            if current_transport(output).get('managed_registry'):
                workspace.files.discard('backend/src/api/register.ts')
            allow = lambda path: path.startswith(('frontend/src/', 'backend/src/')) and editable_runtime_path(output, path)
            protect(workspace, allow)

            def gate():
                evidence = {}
                try:
                    evidence['typecheck'] = checks.typecheck(regression)
                    if evidence['typecheck']['returncode']:
                        raise ValueError(evidence['typecheck']['output'])
                    evidence['acceptance'] = checks.tests(regression)
                    require_suites(evidence['acceptance'], regression, output)
                    if enabled('scenario_coverage'):
                        require_coverage(evidence['acceptance'], tree, list(dict.fromkeys([*accepted, *([] if is_journey else rids)])), executed=True)
                    if is_journey:
                        require_coverage(evidence['acceptance'], tree, rids, executed=True, journey=True)
                    if ui_files:
                        evidence['ui'] = ui_checks.tests(ui_files)
                        require_green(evidence['ui'])
                    if any(path.startswith('backend/') for path in workspace.changed_paths):
                        evidence['backend_typecheck'] = backend_checks.typecheck()
                        if evidence['backend_typecheck']['returncode']:
                            raise ValueError(evidence['backend_typecheck']['output'])
                        if api_files:
                            evidence['backend_tests'] = backend_checks.tests(api_files)
                            backend_green(evidence['backend_tests'])
                except (ValueError, RuntimeError) as error:
                    raise TriggerCheckFailure(str(error), evidence) from error
                return evidence

            entry['status'] = 'IMPLEMENTING'
            with implementation_task(output, entry, console, '12 / batch-' + str(number)):
                try:
                    result = gate()
                    agent = {'turns': 0, 'checks': result}
                except (ValueError, RuntimeError) as error:
                    observed = getattr(error, 'feedback', {'error': str(error)})
                    repair_task = {**task, 'original_requirements': {rid: requirement_context(tree, rid) for rid in rids},
                        'backend_apis': apis, 'page_subtrees': {pid: relevant_pages(ui, rid)[pid]
                            for rid in rids for pid in relevant_pages(ui, rid)},
                        'application_entrypoints': list(APPLICATION_ENTRYPOINTS),
                        'backend_entrypoints': {'registry': 'backend/src/api/register.ts',
                            'app': 'backend/src/app.ts', 'server': 'backend/src/server.ts'}}
                    if enabled('shared_failure_diagnosis'):
                        repair_task['shared_failure_context'] = shared_failure_context(observed, tree, backend, output)
                        entry['shared_failure_context'] = repair_task['shared_failure_context']
                    from infrastructure.shared.project.contract_codegen import state as transport_state, CLIENT
                    if transport_state(output).get('managed_client'):
                        repair_task['contract_client'] = {'path': CLIENT,
                            'usage': 'Reuse callApi for canonical JSON requests; status/body preserve success and rejection cases. '
                                     'Registry/client/types are read-only. Repair handlers and application state.'}
                        workspace.files.add(CLIENT)
                    agent = run_file_agent(model, IMPLEMENT_RULES, repair_task, workspace, gate,
                        max_turns, console, f'Acceptance batch {number} / application repair',
                        feedback=getattr(error, 'feedback', {'error': str(error)}),
                        feedback_filter=feedback_for(workspace, [back, front], allow),
                        context_index=index, max_calls=setting('BATCH_CALLS', 48))
                entry.update(status='GREEN', implementation_turns=agent['turns'], checks=agent['checks'])
                if not is_journey:
                    accepted.extend(rids)
        except (ValueError, RuntimeError) as error:
            entry.update(status='FAILED', error=str(error), feedback=getattr(error, 'feedback', None))
        if not is_journey:
            for rid in rids:
                report['requirements'][rid].update(status=entry['status'], group=number)
        split_failed(queue, number, group, depth, entry, output, '12')
        save_json(arc_dir / 'independent_acceptance.json', report)
    # Require all intended suites, including previously failed/uncreated ones, at final verification.
    all_paths = [acceptance_path(rid) for rid in tree.leaves]
    if journey:
        all_paths.append(JOURNEY_PATH)
    def accept_final(result):
        require_suites(result, all_paths, output)
        if enabled('scenario_coverage'):
            report['scenario_coverage'] = require_coverage(result, tree, tree.leaves, executed=True)
        if journey:
            report['journey_coverage'] = require_coverage(result, tree, [r['id'] for r in journey], executed=True, journey=True)
    verification = final_checks(console,
        typecheck=(lambda: checks.typecheck(all_paths), None),
        acceptance=(lambda: checks.tests(all_paths), accept_final),
        backend_typecheck=(backend_checks.typecheck, None),
        backend_tests=(lambda: backend_checks.tests(api_files), backend_green if api_files else None),
        build=(checks.build, None))
    if ui_files:
        verification.update(final_checks(console, ui=(lambda: ui_checks.tests(ui_files), require_green)))
    complete_report(report, [*report['requirements'].values(), *([report['journey']] if journey else [])], verification)
    actual = verification['acceptance'].get('result') or {}
    report['summary'] = {'requirements': len(accepted), 'e2e_tests': actual.get('passed', 0),
                         'failed': actual.get('failed', 0), 'triggers': 0,
                         'ui_tests': (verification.get('ui', {}).get('result') or {}).get('passed', 0)}
    save_json(arc_dir / 'independent_acceptance.json', report)
    save_json(arc_dir / 'frontend_e2e.json', report)
    return report
