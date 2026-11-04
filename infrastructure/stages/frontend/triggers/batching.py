"""Bounded cross-layer implementation groups; original independent acceptance follows."""
import json
from infrastructure.shared.agent.context import SourceFiles
from infrastructure.shared.agent.efficiency import positive_setting, record_event
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.efficiency import enabled
from infrastructure.shared.agent.evidence import repair_evidence
from infrastructure.shared.agent.recovery import implementation_task
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.stages.backend.context import related_schema
from infrastructure.stages.backend.testing import BackendChecks, require_green as backend_green
from infrastructure.stages.frontend.triggers.design import api_ids, trigger_obligations
from infrastructure.stages.frontend.triggers.e2e_runtime import CONFIG, FIXTURE
from infrastructure.stages.frontend.triggers.scope import TriggerCheckFailure
from infrastructure.stages.frontend.triggers.testing import test_path
from infrastructure.stages.frontend.ui.runtime import APPLICATION_ENTRYPOINTS
from infrastructure.stages.frontend.ui.testing import require_green, test_path as ui_test_path
from infrastructure.utils.files import save_json


FLOW_RULES = '''This task owns ALL supplied requirement_ids and target_trigger_ids together.
Implement their complete user flows across existing frontend, HTTP handlers and persistence.
The shared_contracts are canonical; preserve all owners' behaviors and exact write boundaries.
Reuse existing event/request owners and implement related transitions in one edit batch.
Read several missing relevant files together. Do not implement only the first requirement.
Use real persisted data, response/error states, reload and selected-object identity.
Preserve original Given/When/Then and explicit UI contracts. All tests are READ-ONLY during
this implementation task, including process smoke tests. Repair application sources, never
loosen assertions, detect tests or install production fixture shortcuts.
Earlier successful flows remain required. The gate includes their regression suites.
Original requirement evidence, shared API owners and failed-check evidence are supplied;
use them before guessing a repair. A group replaces individual implementation loops.
'''


def plan_groups(records, maximum=None, max_chars=None):
    """Group adjacent related requirements without reordering or dropping any record."""
    maximum = maximum or positive_setting('FLOW_SIZE', 4)
    max_chars = max_chars or positive_setting('FLOW_CONTEXT_CHARS', 60000)
    groups, current, resources, chars = [], [], set(), 0
    for record in records:
        related = {'page:' + x for x in record['pages']} | {'api:' + x for x in record['apis']}
        size = len(json.dumps(record['context'], ensure_ascii=False))
        if current and (len(current) >= maximum or chars + size > max_chars or not resources.intersection(related)):
            groups.append(current)
            current, resources, chars = [], set(), 0
        current.append(record)
        resources.update(related)
        chars += size
    if current:
        groups.append(current)
    return groups


def lock_tests(workspace, allow):
    workspace.writable = {p for p in workspace.writable if allow(p)}
    workspace.allow_write = allow


def require_suites(result, paths, output):
    require_green(result)
    if result.get('skipped') or result.get('flaky'):
        raise TriggerCheckFailure('Selected suites must execute without skips/flaky passes', result)
    seen = {k.replace('\\', '/'): v for k, v in result.get('files', {}).items()}
    missing = []
    for path in paths:
        variants = {path, path.removeprefix('frontend/'), path.removeprefix('frontend/tests/e2e/'),
                    (output / path).as_posix()}
        if not any(seen.get(p, 0) > 0 for p in variants):
            missing.append(path)
    if missing:
        raise TriggerCheckFailure('Required process suites did not execute', {'missing': missing})


def check_ui(checks, paths, group, *, recheck_before_repair=False):
    """Re-observe one failed presentation check before spending a repair call; retain both results."""
    result = checks.tests(paths)
    if result.get('returncode') and recheck_before_repair:
        first = result
        result = checks.tests(paths)
        group.setdefault('ui_pre_repair_rechecks', []).append({'first': first, 'recheck': result})
    return result


def group_context(records, backend, contexts):
    rids = [r['id'] for r in records]
    apis = {aid for r in records for aid in r['apis']}
    owners = {aid: [rid for rid, ids in backend['requirements'].items() if aid in ids] for aid in sorted(apis)}
    evidence = {rid for ids in owners.values() for rid in ids if rid in contexts}
    clean = lambda value: {k: v for k, v in value.items() if k != 'images'}
    return {'requirement_ids': rids, 'requirements': {r['id']: clean(contexts[r['id']]) for r in records},
        'page_subtrees': {pid: page for r in records for pid, page in r['context']['page_subtrees'].items()},
        'triggers': {tid: item for r in records for tid, item in r['context']['triggers'].items()},
        'obligations': {tid: item for r in records for tid, item in r['context']['obligations'].items()},
        'target_trigger_ids': sorted({tid for r in records for tid in r['context']['triggers']}),
        'shared_contracts': {aid: backend['apis'][aid] for aid in sorted(apis)},
        'shared_api_owners': owners, 'owner_requirements': {rid: clean(contexts[rid]) for rid in sorted(evidence)}}


def run_flow_batches(arc_dir, tree, schema, backend, ui, design, contexts, model, console,
                     report, checks, ui_checks, max_turns, max_tests):
    from infrastructure.stages.frontend.triggers.implementation import (
        scenario_context, TEST_INSTRUCTIONS, IMPLEMENT_INSTRUCTIONS, editable_runtime_path,
        test_run_status, verify_frontend)
    output = arc_dir.parent.resolve()
    selection = SourceFiles(output, ui)
    back = SourceFiles(output, root='backend/src', tests_root='backend/tests')
    records = []
    for rid in tree.leaves:
        context = scenario_context(ui, design, rid)
        tids = design['requirements'][rid]
        if not context['page_subtrees'] and not tids:
            report['requirements'][rid] = {'status': 'NO_TRIGGERS', 'triggers': []}
            continue
        called = {aid for trigger in context['triggers'].values() for aid in api_ids(trigger)}
        called.update(backend['requirements'].get(rid, []))
        context['obligations'] = {tid: trigger_obligations(t, backend) for tid, t in context['triggers'].items()}
        records.append({'id': rid, 'pages': list(context['page_subtrees']), 'apis': sorted(called), 'context': context})
    groups = plan_groups(records)
    report['mode'], report['groups'] = 'b3_flow_batches', []
    save_json(arc_dir / 'b3_flow_plan.json', [[r['id'] for r in group] for group in groups])
    accepted = []
    for number, records in enumerate(groups, 1):
        ready = []
        # Tests remain separately authored from original requirement evidence.
        for record in records:
            rid, context = record['id'], record['context']
            entry = {'status': 'GENERATING_TESTS', 'triggers': list(context['triggers']),
                     'target_triggers': list(context['triggers']), 'steps': list(tree.own_steps[rid])}
            report['requirements'][rid] = entry
            with implementation_task(output, entry, console, 'B3 tests / ' + rid):
                path = test_path(rid, output)
                task = {**context, 'requirement': {k: v for k, v in contexts[rid].items() if k != 'images'},
                    'target_trigger_ids': list(context['triggers']),
                    'backend_apis': {aid: backend['apis'][aid] for aid in record['apis']},
                    'schema': related_schema(schema, [backend['apis'][aid] for aid in record['apis']]),
                    'max_tests': max_tests, 'test_path': path if (output / path).is_file() else None}
                workspace = selection.workspace(target=('e2e_test', rid), existing=path,
                    references=[CONFIG, FIXTURE, 'backend/tests/support/context.ts',
                        *selection.paths('page', record['pages']), *APPLICATION_ENTRYPOINTS,
                        *back.paths('api', record['apis']), 'frontend/src/ui-runtime.ts'])
                workspace.writable = {p for p in workspace.writable if p.startswith('frontend/tests/e2e/') and '/support/' not in p}
                workspace.allow_write = None

                def test_gate():
                    path = test_path(rid, output)
                    compiled = checks.typecheck([path], full_source=False)
                    if compiled['returncode']:
                        raise TriggerCheckFailure('Generated test compilation failed', {'typecheck': compiled})
                    result = checks.tests([path])
                    status = test_run_status(result)
                    if status == 'GREEN':
                        require_suites(result, [path], output)
                    return {'typecheck': compiled, 'behavior': result, 'status': status}

                current = None
                if (output / path).is_file():
                    try:
                        current = {'turns': 0, 'checks': test_gate()}
                    except ValueError:
                        pass
                if current is None:
                    current = run_file_agent(model, TEST_INSTRUCTIONS + '\nWhen the original Given explicitly requires '
                        'UI-created data, preserve that UI prerequisite chain; this overrides the general SQL-setup '
                        'suggestion. Do not silently replace required navigation/creation with SQL or a direct URL.',
                        task, workspace, test_gate, max_turns, console, 'B3 test generation / ' + rid,
                        allow_discovery=False)
                entry.update(status='TESTS_READY', test_path=test_path(rid, output), test_turns=current['turns'])
                ready.append(record)
            save_json(arc_dir / 'frontend_e2e.json', report)
        if not ready:
            continue
        group = {'id': number, 'requirements': [r['id'] for r in ready], 'status': 'IMPLEMENTING'}
        report['groups'].append(group)
        with implementation_task(output, group, console, 'B3 flow group ' + str(number)):
            task = group_context(ready, backend, contexts)
            task.update(application_entrypoints=list(APPLICATION_ENTRYPOINTS),
                backend_entrypoints={'registry': 'backend/src/api/register.ts', 'app': 'backend/src/app.ts', 'server': 'backend/src/server.ts'})
            paths = [test_path(rid, output) for rid in [*accepted, *group['requirements']]]
            pages = {pid for r in ready for pid in r['pages']}
            apis = {aid for r in ready for aid in r['apis']}
            ui_files = [ui_test_path(pid) for pid in pages if (output / ui_test_path(pid)).is_file()]
            workspace = selection.workspace(paths=[*APPLICATION_ENTRYPOINTS, *selection.paths('page', pages)],
                references=[*paths, *ui_files, FIXTURE, CONFIG, 'frontend/src/ui-runtime.ts', 'backend/tests/support/context.ts'])
            back.include(workspace, [*back.paths('api', apis), 'backend/src/api/register.ts', 'backend/src/app.ts'])
            allowed = lambda p: editable_runtime_path(output, p) and '/tests/' not in p
            lock_tests(workspace, allowed)

            def feedback(value):
                result = selection.feedback(workspace, back.feedback(workspace, value))
                if enabled('failure_evidence'):
                    evidence = repair_evidence(result, backend)
                    selection.include(workspace, [p for p in evidence['referenced_sources'] if p in selection.sources])
                    back.include(workspace, [p for p in evidence['referenced_sources'] if p in back.sources])
                    result = {'failure_evidence': evidence, 'checks': result}
                lock_tests(workspace, allowed)
                return result

            def gate(recheck_before_repair=False):
                result = {'typecheck': checks.typecheck(paths)}
                try:
                    if result['typecheck']['returncode']:
                        raise ValueError('Frontend compilation failed')
                    if any(p.startswith('backend/') for p in workspace.changed_paths):
                        bc = BackendChecks(output)
                        result['backend_typecheck'] = bc.typecheck()
                        if result['backend_typecheck']['returncode']:
                            raise ValueError('Backend compilation failed')
                        suites = [p for aid in backend['apis'] if (p := selected_path(output, 'backend_test', aid)) and (output / p).is_file()]
                        if suites:
                            result['backend_tests'] = bc.tests(suites)
                            backend_green(result['backend_tests'])
                    result['e2e'] = checks.tests(paths)
                    require_suites(result['e2e'], paths, output)
                    if ui_files:
                        result['ui'] = check_ui(ui_checks, ui_files, group,
                            recheck_before_repair=recheck_before_repair)
                        require_green(result['ui'])
                except ValueError as error:
                    raise TriggerCheckFailure('Flow integration failed: ' + str(error).split(':', 1)[0], result) from error
                return result

            try:
                initial = gate(recheck_before_repair=enabled('bounded_repair'))
                agent = {'turns': 0, 'checks': initial}
            except ValueError as error:
                # One implementation loop replaces individual loops for every member.
                agent = run_file_agent(model, IMPLEMENT_INSTRUCTIONS + '\n' + FLOW_RULES,
                    task, workspace, gate, max_turns, console, 'B3 flow implementation ' + str(number),
                    feedback=getattr(error, 'feedback', {'error': str(error)}), feedback_filter=feedback,
                    allow_discovery=False, max_calls=positive_setting('MAX_FLOW_CALLS', 48))
            group.update(status='GREEN', implementation_turns=agent['turns'])
            accepted.extend(group['requirements'])
        for record in ready:
            report['requirements'][record['id']].update(status=group['status'],
                group=number, implementation_turns=group.get('implementation_turns', 0))
            if group['status'] == 'FAILED':
                report['requirements'][record['id']]['error'] = group.get('error', 'Group repair failed; baseline restored')
        record_event(output, 'flow_group', **{k: group[k] for k in ('id', 'requirements', 'status')})
        save_json(arc_dir / 'frontend_e2e.json', report)
    return verify_frontend(arc_dir, tree, backend, ui, console, report)
