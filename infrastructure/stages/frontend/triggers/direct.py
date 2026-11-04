"""Deterministic requirement-to-UI/API bindings for acceptance-first implementation."""

from infrastructure.stages.backend.primitives import validate_design
from infrastructure.stages.frontend.triggers.design import empty_triggers, relevant_pages


DIRECT_IMPLEMENT_INSTRUCTIONS = """Implement the current ORIGINAL requirement in the real React/Express/SQLite application.
The independent test was derived from Given/When/Then before implementation. It is
read-only; fix application code, not expectations, fixtures or selectors in tests.
Use task.original_requirement (or requirement) as authority, the supplied UI routes,
element names and backend_apis as integration contracts. There is no generated trigger
DSL to implement; an empty target_trigger_ids list does NOT mean there is no work.
Read current components/entrypoints, then implement the actual UI -> HTTP -> database
-> response -> displayed state flow using existing framework code and helpers.
Preserve explicit names, roles, routes, object identity, session isolation, persistence,
reload behavior, required rejection-without-writes and all previously working behavior.
Use one submission owner; avoid duplicate handlers/effects/requests. Use real APIs,
browser-managed cookies and database state. Never fabricate results, inject test state,
detect the benchmark, mock business requests, or weaken security/validation to pass.
Make small exact edits. Follow current imports and relevant test/network/console evidence.
Use the context tools for missing original requirements or canonical API definitions.
Shared fixtures and independent tests stay protected. Explain genuine scope blockers.
"""


def plan_bindings(tree, backend, ui, obligations, registry=None):
    """Keep original upstream obligation checks; do not ask an LLM to restate joins."""
    result = empty_triggers(tree)
    result.update(mode='direct_bindings', bindings={})
    for rid in tree.leaves:
        ids = backend['requirements'].get(rid, [])
        missing = set(ids) - backend['apis'].keys()
        if missing:
            raise ValueError(f'{rid} references undefined APIs: {sorted(missing)}')
        missing_elements = set(ui['requirements'].get(rid, [])) - ui['elements'].keys()
        if missing_elements:
            raise ValueError(f'{rid} references undefined UI elements: {sorted(missing_elements)}')
        pages = relevant_pages(ui, rid)
        if pages:
            validate_design({'apis': backend['apis'], 'requirements': {rid: ids}},
                obligations, complete=False, tree=tree)
        result['bindings'][rid] = {'pages': sorted(pages), 'apis': list(ids),
            'steps': list(tree.own_steps[rid])}
        if registry is not None:
            result['bindings'][rid]['contract_context'] = registry.context_for(rid)
    return result
