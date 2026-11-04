"""Batch UI planning and implementation; original interface contracts remain authority."""
from copy import deepcopy

from infrastructure.shared.agent.batching import (chunks, setting, target_path, bind_files,
    protect, feedback_for, log_plan, split_failed)
from infrastructure.shared.agent.context import SourceFiles
from infrastructure.shared.agent.discovery import ContextIndex, project_index
from infrastructure.shared.agent.files import editable_application_path
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.agent.recovery import implementation_task, final_checks, complete_report
from infrastructure.shared.agent.tasks import TaskFailures
from infrastructure.stages.frontend.ui.design import (INSTRUCTIONS as DESIGN_RULES, empty_design,
    normalize_design, page_context, owners, data_symbols)
from infrastructure.stages.frontend.ui.synthesis import bind_requirement_image_pages
from infrastructure.stages.frontend.ui.runtime import APPLICATION_ENTRYPOINTS
from infrastructure.stages.frontend.ui.testing import existence_suite, test_path, require_green
from infrastructure.utils.files import save_json, save_text, read_artifact


DESIGN_BATCH_RULES = '''BATCH OUTPUT CONTRACT replaces requirement_ui's single list:
task.requirements contains several original requirements. requirement_ui MUST be an object
mapping EVERY supplied requirement ID to its element-ID array. step_ui MUST include EVERY
supplied scenario step ID, using [] only when that step has no UI. elements/pages retain
their original formats. Design every member together; reuse shared navigation/layout,
pages and data declarations without dropping existing owners' controls or constraints.
Each page needs one valid root, each element a valid acyclic parent chain, and every
referenced UI ID must exist. Return changes only; existing records remain available.
Keep screens focused on original user interactions; avoid inventing extra screens.'''


def accept_design(design, proposal, rids, tree):
    if set(proposal) != {'elements', 'pages', 'requirement_ui', 'step_ui'}:
        raise ValueError('Batch UI proposal requires exactly four root maps')
    if not all(isinstance(proposal[k], dict) for k in proposal):
        raise ValueError('All four batch UI fields must be maps')
    if set(proposal['requirement_ui']) != set(rids):
        raise ValueError('requirement_ui must cover exactly the batch requirement IDs')
    steps = {sid for rid in rids for sid in tree.own_steps[rid]}
    if set(proposal['step_ui']) != steps:
        raise ValueError('step_ui must cover exactly every batch scenario step ID')
    updated = deepcopy(design)
    for kind in ('elements', 'pages'):
        updated[kind].update(deepcopy(proposal[kind]))
    updated['requirements'].update(deepcopy(proposal['requirement_ui']))
    updated['steps'].update(deepcopy(proposal['step_ui']))
    normalize_design(updated, tree)
    for links in [*updated['requirements'].values(), *updated['steps'].values()]:
        if not isinstance(links, list) or any(uid not in updated['elements'] for uid in links):
            raise ValueError('Unknown UI ID or invalid association array')
    for pid, page in updated['pages'].items():
        if not isinstance(page.get('route'), str) or not page['route'].startswith('/'):
            raise ValueError('Page route must be an absolute URL path: ' + pid)
        root = updated['elements'].get(page.get('root'), {})
        if root.get('type') != 'page' or root.get('parent') is not None:
            raise ValueError('Page requires a valid page root: ' + pid)
    roots = {page['root'] for page in updated['pages'].values()}
    for uid in updated['elements']:
        seen, current = set(), uid
        while current is not None:
            if current in seen or current not in updated['elements']:
                raise ValueError('Dangling or cyclic UI parent: ' + uid)
            seen.add(current)
            current = updated['elements'][current].get('parent')
        if not seen.intersection(roots):
            raise ValueError('Element is not owned by a page: ' + uid)
    return updated


def synthesize_batches(arc_dir, tree, images, contexts, model, console, max_attempts):
    design = normalize_design(empty_design(), tree)
    groups = chunks([{'id': rid, 'requirement': contexts[rid]} for rid in tree.leaves],
                    setting('UI_DESIGN_BATCH_SIZE', 6), setting('BATCH_CONTEXT_CHARS', 80000))
    log_plan(arc_dir.parent, '09', groups, len(tree.leaves))
    failures = TaskFailures(arc_dir, '09_design_ui', console)
    for number, group in enumerate(groups, 1):
        rids = [record['id'] for record in group]
        with failures.task('batch-' + str(number)):
            request = {'requirements': {r['id']: r['requirement'] for r in group},
                       'existing_design': design}
            updated, _ = propose_json(model, DESIGN_RULES + '\n' + DESIGN_BATCH_RULES, request,
                lambda proposal: accept_design(design, proposal, rids, tree), console,
                'UI design batch ' + str(number), max_attempts,
                context_index=ContextIndex(lambda: {'page': design['pages'],
                    'ui_element': design['elements'], 'ui_data': data_symbols(design['elements'])}))
            for rid in rids:
                bind_requirement_image_pages(updated, contexts[rid], rid)
            design = updated
            save_json(arc_dir / 'ui_design.json', design)
    failures.finish()
    save_json(arc_dir / 'ui_design.json', design)
    return design


def implement_batches(arc_dir, design, model, console, report, checks, selection,
                      max_turns, images, contexts, instructions):
    output = arc_dir.parent.resolve()
    backend = read_artifact(arc_dir, 'backend_apis.json')
    records = [{'id': pid, 'page': page_context(design, pid)} for pid in design['pages']]
    groups = chunks(records, setting('PAGE_BATCH_SIZE', 4), setting('BATCH_CONTEXT_CHARS', 80000))
    log_plan(output, '10', groups, len(records))
    paths = {pid: target_path(output, 'page', pid) for pid in design['pages']}
    accepted = []
    report.update(mode='b4_page_batches', groups=[])
    index = project_index(output, kinds=('page', 'ui_element', 'ui_data', 'api', 'requirement', 'file'),
                          file_roots=('frontend/src', 'backend/src'))
    # All presence suites are deterministic and immutable during implementation.
    for pid in design['pages']:
        save_text(output / test_path(pid), existence_suite(design, pid))
        report['pages'][pid] = {'status': 'TESTS_READY', 'test_path': test_path(pid)}
    # B4 implements canonical API loading/actions now, avoiding a later rewrite of every page.
    instructions = instructions.replace(
        'This stage builds presentation, native editing and navigation, not business API operations,\n'
        "session restoration or later requirements' workflows. Step 12 adds those interactions.",
        'Implement canonical business API loading, actions and session restoration required by the\n'
        'supplied original requirements now. Independent browser acceptance follows in step 12.')
    instructions += '''\nBATCH: implement every supplied page and its owner requirements together, including
canonical backend_apis. Create EVERY page_paths entry; preserve existing routes and one
clear request/submit owner. Reuse shared layout, request and state helpers. Tests are
READ-ONLY. UI presence passing is only a presentation gate, never proof of business GREEN.
Application loading must respect the existing display-only presentation adapter.
The single-page fields above apply separately to every member of task.pages.'''
    queue = [(group, 0) for group in groups]
    for number, (group, depth) in enumerate(queue, 1):
        pids = [record['id'] for record in group]
        rids = list(dict.fromkeys(rid for pid in pids for rid in owners(design, pid)))
        aids = list(dict.fromkeys(aid for rid in rids for aid in backend['requirements'].get(rid, [])))
        entry = {'status': 'IMPLEMENTING', 'pages': pids, 'split_depth': depth}
        report['groups'].append(entry)
        with implementation_task(output, entry, console, '10 / batch-' + str(number)):
            files = [test_path(pid) for pid in [*accepted, *pids]]
            workspace = selection.workspace(paths=[paths[pid] for pid in pids],
                references=[*files, 'frontend/src/ui-runtime.ts', *APPLICATION_ENTRYPOINTS,
                            'frontend/package.json', 'frontend/tsconfig.json'])
            allow = lambda path: path.startswith('frontend/src/') and editable_application_path(output, path)
            protect(workspace, allow)

            def gate():
                bind_files(output, 'page', {pid: paths[pid] for pid in pids})
                result = {'typecheck': checks.typecheck(files)}
                if result['typecheck']['returncode']:
                    raise ValueError(result['typecheck']['output'])
                result['tests'] = checks.tests(files)
                require_green(result['tests'])
                return result

            task = {'pages': {r['id']: r['page'] for r in group},
                    'page_paths': {pid: paths[pid] for pid in pids},
                    'requirements': {rid: {k: v for k, v in contexts.get(rid, {'id': rid}).items()
                                          if k != 'images'} for rid in rids},
                    'backend_apis': {aid: backend['apis'][aid] for aid in aids},
                    'application_entrypoints': list(APPLICATION_ENTRYPOINTS),
                    'visual_references': {iid: images[iid] for pid in pids
                        for iid in design['pages'][pid]['images'] if iid in images}}
            try:
                current = gate()
                agent = {'turns': 0, 'checks': current}
            except (ValueError, RuntimeError) as error:
                agent = run_file_agent(model, instructions, task, workspace, gate, max_turns,
                    console, f'Page batch {number}', feedback=getattr(error, 'feedback', {'error': str(error)}),
                    feedback_filter=feedback_for(workspace, [selection], allow), context_index=index,
                    max_calls=setting('BATCH_CALLS', 48))
            entry.update(status='GREEN', turns=agent['turns'], checks=agent['checks'])
            accepted.extend(pids)
        for pid in pids:
            report['pages'][pid].update(status=entry['status'], implementation_path=paths[pid])
        split_failed(queue, number, group, depth, entry, output, '10')
        save_json(arc_dir / 'ui_checks.json', report)
    files = [test_path(pid) for pid in design['pages']]
    verification = final_checks(console, typecheck=(lambda: checks.typecheck(files), None),
        tests=(lambda: checks.tests(files), require_green), build=(checks.build, None))
    result = verification['tests'].get('result') or {}
    report['summary'] = {'pages': len(accepted), 'tests': result.get('passed', 0),
                         'failed': result.get('failed', 0)}
    complete_report(report, report['pages'].values(), verification)
    save_json(arc_dir / 'ui_checks.json', report)
    return report
