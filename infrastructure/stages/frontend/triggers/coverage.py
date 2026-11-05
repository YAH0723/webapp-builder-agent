"""Executed scenario traceability and requirement-grounded user journeys."""
import json
import re
from infrastructure.shared.agent.batching import enabled
from infrastructure.shared.agent.evidence import repair_evidence
from infrastructure.stages.backend.context import requirement_context
from infrastructure.stages.frontend.triggers.acceptance import acceptance_path
from infrastructure.stages.frontend.triggers.design import relevant_pages

JOURNEY_PATH = 'frontend/tests/e2e/acceptance/user-journey.spec.ts'
RULES = '''SCENARIO TRACEABILITY: each Playwright test declares static details annotations:
test('meaningful business outcome', { annotation: [{type:'arc-step',description:'ORIGINAL_STEP_ID'}] }, async ({page}) => {...}).
Use the exact original step IDs supplied in coverage_steps. Every original step must have
an executable test that actually checks its When/Then outcome. One test can cover several
compatible steps with several annotations. An annotation alone is not an assertion.
Do not stamp unrelated IDs onto a smoke test, skip tests, mark required failures expected,
or weaken assertions to satisfy coverage. Both collection and actual passing execution
are checked. There is no minimum arbitrary case count. Preserve all original outcomes.
'''
JOURNEY_RULES = '''USER JOURNEY OVERRIDE: write ONLY task.journey.test_path, not the individual
requirement test_paths. Author a meaningful continuous browser flow across at least TWO
of the supplied original requirements, using their actual Given/When/Then and UI/API
contracts. Cover the selected step IDs using arc-step annotations as above. Prefer a core
flow that creates/changes actual data, finds/opens the same object and verifies its result
after navigation/reload WHEN these behaviors are required. Do not invent authentication,
CRUD operations or prerequisite dependencies that the original requirements do not have.
Within each journey test, carry real created identities/state forward. Produce intermediate
objects through the browser instead of SQL seeds or direct API mutations. Use only the page
fixture for setup/actions; the supplied fixture handles original startup data. Do not import
application code or a database client. Assert required visible business outcomes. Keep
normal isolated requirement suites unchanged. This journey supplements their isolation.
'''


def coverage_steps(tree, rids):
    return {rid: list(tree.own_steps[rid]) for rid in rids}


def file_matches(reported, expected):
    path = reported.replace('\\', '/')
    variants = {expected, expected.removeprefix('frontend/'), expected.removeprefix('frontend/tests/e2e/')}
    return any(path == value or path.endswith('/' + value) for value in variants)


def require_coverage(result, tree, rids, *, executed, journey=False):
    """Only validate recorded mapping/execution, not the semantic strength of assertions."""
    cases = result.get('cases', [])
    missing = []
    mapped = set()
    for rid in rids:
        expected = JOURNEY_PATH if journey else acceptance_path(rid)
        found = set()
        for case in cases:
            if not file_matches(case.get('file', ''), expected):
                continue
            if case.get('expected_status', 'passed') != 'passed':
                continue
            if executed and (not case.get('outcomes') or any(s != 'passed' for s in case['outcomes'])):
                continue
            found.update(a.get('description') for a in case.get('annotations', []) if a.get('type') == 'arc-step')
        valid = found.intersection(tree.own_steps[rid])
        if valid:
            mapped.add(rid)
        if not journey:
            missing.extend(step for step in tree.own_steps[rid] if step not in valid)
    if journey and len(mapped) < 2:
        raise ValueError('Journey must map executed steps from at least two original requirements')
    if missing:
        raise ValueError('Original scenario steps lack ' + ('passing execution: ' if executed else 'collected tests: ') + ', '.join(missing))
    return {'status': 'MAPPED_AND_PASSED' if executed else 'MAPPED',
            'requirements': sorted(mapped), 'semantic_coverage_proven': False}


def journey_records(records, backend, ui):
    """Select related source-order requirements, without inventing a semantic dependency DAG."""
    if not enabled('user_journeys'):
        return []
    resources = {}
    for record in records:
        rid = record['id']
        resources[rid] = {'api:' + aid for aid in backend['requirements'].get(rid, [])}
        resources[rid].update('page:' + pid for pid in relevant_pages(ui, rid))
        evidence = json.dumps(record.get('requirement', {}), ensure_ascii=False)
        for pid, page in ui['pages'].items():
            route = page.get('route', '')
            if route and route != '/' and re.search(re.escape(route) + r'(?![A-Za-z0-9_/])', evidence):
                resources[rid].add('page:' + pid)
    best = []
    for seed in records:
        members, used = [seed['id']], set(resources[seed['id']])
        for record in records:
            rid = record['id']
            if rid not in members and used.intersection(resources[rid]) and len(members) < 4:
                members.append(rid); used.update(resources[rid])
        if len(members) > len(best):
            best = members
    return [{**record, '_journey': True} for record in records if record['id'] in best] if len(best) >= 2 else []


def shared_failure_context(value, tree, backend, output=None):
    evidence = repair_evidence(value, backend)
    apis = set(evidence['related_api_ids'])
    if output is not None:
        from infrastructure.shared.project.entrypoints import selected_path
        apis.update(aid for aid in backend['apis'] if selected_path(output, 'api', aid) in evidence['referenced_sources'])
    owners = {aid: [rid for rid, ids in backend['requirements'].items()
                   if aid in ids and rid in tree.requirements] for aid in sorted(apis)}
    return {'observed_evidence': evidence, 'shared_api_owners': owners,
            'owner_requirements': {rid: requirement_context(tree, rid)
                                  for ids in owners.values() for rid in ids},
            'instruction': 'Investigate common referenced sources/request owners before per-test patches. '
                           'These are localization hints, not proof of one shared cause. Preserve all owners.'}
