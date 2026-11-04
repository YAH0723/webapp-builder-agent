"""Canonical API contract TDD in bounded batches, without per-API model loops."""
from infrastructure.shared.agent.batching import (chunks, setting, target_path, bind_files,
    protect, feedback_for, log_plan, split_failed)
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.files import editable_application_path
from infrastructure.shared.agent.context import SourceFiles
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.discovery import project_index
from infrastructure.shared.agent.recovery import implementation_task, final_checks, complete_report
from infrastructure.stages.backend.context import requirement_context, related_schema, supplied_sources
from infrastructure.stages.backend.runtime import REGISTER_PATH, TEST_SUPPORT_PATH
from infrastructure.stages.backend.testing import BackendChecks, require_green
from infrastructure.utils.files import save_json


TEST_RULES = '''BATCH CONTRACT: task.apis contains several canonical APIs. Create EVERY supplied
test_paths[api_id] in one edit batch. Each API keeps its own real HTTP contract suite.
Use all original owner_requirements and P/Q/read/write contracts; do not test only the
first owner. The max_tests hint applies per API. Only test_paths are writable; application
sources and fixtures are read-only. The generation gate compiles tests, not business
GREEN: missing handlers are expected at this point. Do not weaken business assertions.
The single-target fields in earlier instructions apply separately to each batch member.'''

IMPLEMENT_RULES = '''BATCH IMPLEMENTATION: implement ALL task.apis together. Create each
implementation_paths[api_id], export the canonical handle function, and register every
method/path in api_wiring.registry. Shared database/validation helpers may be reused.
These are the sole owners of these canonical contracts, including every supplied original
owner requirement. Tests and fixtures are READ-ONLY. Preserve previously accepted routes.
The single-target fields in earlier instructions apply separately to every batch member.
Use one edit batch for coherent handler/registry/helper changes before requesting checks.'''


def implement_batches(arc_dir, tree, schema, contracts, model, console, max_turns,
                      max_tests, test_instructions, implementation_instructions):
    output = arc_dir.parent.resolve()
    checks = BackendChecks(output)
    selection = SourceFiles(output, root='backend/src', tests_root='backend/tests')
    owners = {aid: [rid for rid in tree.leaves
                   if aid in contracts['requirements'].get(rid, [])] for aid in contracts['apis']}
    if any(not ids for ids in owners.values()):
        raise ValueError('Every canonical API needs at least one original owner requirement')
    records = [{'id': aid, 'api': api, 'owners': owners[aid]}
               for aid, api in contracts['apis'].items()]
    groups = chunks(records, setting('API_BATCH_SIZE', 5), setting('BATCH_CONTEXT_CHARS', 80000))
    log_plan(output, '08', groups, len(records))
    targets = {aid: target_path(output, 'backend_test', aid) for aid in owners}
    paths = {aid: target_path(output, 'api', aid) for aid in owners}
    report = {'status': 'RUNNING', 'mode': 'b4_backend_batches', 'requirements': {},
              'apis': {}, 'tests': {}, 'agents': {}, 'groups': []}
    accepted = []
    index = project_index(output, kinds=('schema', 'api', 'requirement', 'convention', 'file'),
                          file_roots=('backend/src', 'backend/tests'))
    queue = [(group, 0) for group in groups]
    for number, (group, depth) in enumerate(queue, 1):
        ids = [record['id'] for record in group]
        apis = {aid: contracts['apis'][aid] for aid in ids}
        rids = list(dict.fromkeys(rid for aid in ids for rid in owners[aid]))
        entry = {'status': 'GENERATING_TESTS', 'apis': ids, 'split_depth': depth}
        report['groups'].append(entry)
        save_json(arc_dir / 'backend_tdd.json', report)
        with implementation_task(output, entry, console, f'08 / batch-{number}'):
            tests = {aid: targets[aid] for aid in ids}
            sources = {p for api in apis.values() for p in supplied_sources(output, api, schema)}
            task = {'apis': apis, 'owners': {aid: owners[aid] for aid in ids},
                    'owner_requirements': {rid: requirement_context(tree, rid) for rid in rids},
                    'db_schema': related_schema(schema, apis.values()), 'test_paths': tests,
                    'max_tests': max_tests, 'support_module': TEST_SUPPORT_PATH}
            author = FileTools(output, tests.values(), references=sorted(sources),
                               readable=[*tests.values(), *sources])

            def compile_tests():
                bind_files(output, 'backend_test', tests)
                result = checks.typecheck(list(tests.values()))
                if result['returncode']:
                    raise ValueError(result['output'])
                return result

            generated = run_file_agent(model, test_instructions + '\n' + TEST_RULES,
                task, author, compile_tests, max_turns, console, f'API batch {number} / tests',
                allow_discovery=False, max_calls=setting('BATCH_CALLS', 48))
            entry['test_turns'] = generated['turns']
            regression = [targets[aid] for aid in [*accepted, *ids]]
            workspace = selection.workspace(paths=[REGISTER_PATH, *[paths[aid] for aid in ids]],
                references=[*regression, *sources])
            allow = lambda path: path.startswith('backend/src/') and editable_application_path(output, path)
            protect(workspace, allow)

            def gate():
                bind_files(output, 'api', {aid: paths[aid] for aid in ids})
                result = {'typecheck': checks.typecheck(regression)}
                if result['typecheck']['returncode']:
                    raise ValueError(result['typecheck']['output'])
                result['tests'] = checks.tests(regression)
                require_green(result['tests'])
                return result

            entry['status'] = 'IMPLEMENTING'
            task.update(implementation_paths={aid: paths[aid] for aid in ids},
                        api_wiring={'registry': REGISTER_PATH, 'app': 'backend/src/app.ts',
                                    'server': 'backend/src/server.ts'})
            try:
                current = gate()
                agent = {'turns': 0, 'checks': current}
            except (ValueError, RuntimeError) as error:
                agent = run_file_agent(model, implementation_instructions + '\n' + IMPLEMENT_RULES,
                    task, workspace, gate, max_turns, console, f'API batch {number} / implementation',
                    feedback=getattr(error, 'feedback', {'error': str(error)}), feedback_filter=feedback_for(workspace, [selection], allow),
                    context_index=index, max_calls=setting('BATCH_CALLS', 48))
            entry.update(status='GREEN', implementation_turns=agent['turns'], checks=agent['checks'])
            accepted.extend(ids)
        for aid in ids:
            report['apis'][aid] = {'status': entry['status'], 'test_path': targets[aid]}
            for rid in owners[aid]:
                report['tests'].setdefault(rid, {})[aid] = targets[aid]
        split_failed(queue, number, group, depth, entry, output, '08')
        save_json(arc_dir / 'backend_tdd.json', report)
    for rid in tree.leaves:
        ids = contracts['requirements'].get(rid, [])
        report['requirements'][rid] = {'apis': ids, 'status':
            ('GREEN' if all(aid in accepted for aid in ids) else 'FAILED') if ids else 'NO_DIRECT_APIS'}
    all_files = list(targets.values())
    verification = final_checks(console, typecheck=(checks.typecheck, None),
        tests=(lambda: checks.tests(all_files), require_green), build=(checks.build, None))
    final = verification['tests'].get('result') or {}
    report['summary'] = {key: final.get(key, 0) for key in ('tests', 'pass', 'fail')}
    complete_report(report, report['apis'].values(), verification)
    save_json(arc_dir / 'backend_tdd.json', report)
    return report
