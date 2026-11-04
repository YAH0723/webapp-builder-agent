"""Deterministic joins replace a model-generated intermediate trigger description."""
from infrastructure.stages.backend.primitives import validate_design
from infrastructure.stages.frontend.triggers.design import empty_triggers, relevant_pages


def plan_bindings(tree, backend, ui, obligations):
    result = empty_triggers(tree)
    result.update(mode='direct_bindings', bindings={})
    for rid in tree.leaves:
        ids = backend['requirements'].get(rid, [])
        if set(ids) - backend['apis'].keys():
            raise ValueError('Undefined API binding for ' + rid)
        if set(ui['requirements'].get(rid, [])) - ui['elements'].keys():
            raise ValueError('Undefined UI binding for ' + rid)
        pages = relevant_pages(ui, rid)
        if pages:
            validate_design({'apis': backend['apis'], 'requirements': {rid: ids}},
                            obligations, complete=False, tree=tree)
        result['bindings'][rid] = {'pages': sorted(pages), 'apis': list(ids),
                                  'steps': list(tree.own_steps[rid])}
    return result


IMPLEMENT_RULES = '''Implement ALL supplied original_requirements in the real application.
There is no trigger DSL to interpret: empty trigger maps do not mean no work.
Use original Given/When/Then as authority and canonical backend_apis as contracts.
Connect browser actions -> real HTTP -> persistence -> displayed state. Preserve exact
required names, identity/ownership, session isolation, reload, rejection-without-writes,
one submit owner, cancellation and previously accepted behavior. Tests and shared fixtures
are READ-ONLY. Never detect tests, fabricate success, seed production examples, mock
business HTTP or loosen validation. Preserve the display-only presentation adapter.
Make coherent edits across the supplied pages/APIs and their shared helpers together.
The gate runs this batch plus all previously accepted independent acceptance suites.
Use failed source/network/console evidence before guessing. Read missing files together.
'''
