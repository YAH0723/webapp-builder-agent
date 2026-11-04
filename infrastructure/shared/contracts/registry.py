"""Index compiler artifacts without embedding any website's business vocabulary.

Explicit dependencies are distinct from containment and shared-contract impact.
Validation is report-only; impact is conservative, not a proof of causality or
permission to omit regression tests.
"""

from collections import defaultdict, deque
from copy import deepcopy


class ContractRegistry:
    def __init__(self, tree, schema, backend, ui):
        self.requirements, self.contracts, self.links, self.issues = {}, {}, [], []
        self.dependencies = deepcopy(getattr(tree, 'dependencies', {}))
        self.api_owners, self.page_owners, self.field_apis = defaultdict(set), defaultdict(set), defaultdict(set)
        self.requirement_apis, self.requirement_pages = defaultdict(set), defaultdict(set)
        self.dependents = defaultdict(set)

        def issue(code, owner, message):
            self.issues.append({'code': code, 'owner': owner, 'message': message})

        for entity, record in schema.get('entities', {}).items():
            for field, definition in record.get('fields', {}).items():
                self.contracts['DB:' + entity + '.' + field] = {'kind': 'db_field',
                    'entity': entity, 'field': field, 'definition': deepcopy(definition)}
        endpoints = {}
        for aid, record in backend.get('apis', {}).items():
            signature = record.get('signature', {})
            self.contracts['API:' + aid] = {**deepcopy(record), 'kind': 'api', 'id': aid}
            endpoint = (signature.get('method'), signature.get('path'))
            if not all(isinstance(value, str) and value for value in endpoint):
                issue('INVALID_ENDPOINT', 'API:' + aid, 'Method and path must be defined')
            else:
                if endpoint in endpoints:
                    issue('SHARED_ENDPOINT', 'API:' + aid, 'Also declared by ' + endpoints[endpoint])
                endpoints[endpoint] = aid
            for mode in ('read', 'write'):
                for field in record.get(mode, []):
                    self.field_apis[field].add(aid)
                    self.links.append({'from': 'API:' + aid, 'to': 'DB:' + field, 'kind': mode})
                    if 'DB:' + field not in self.contracts:
                        issue('UNDEFINED_DB_FIELD', 'API:' + aid, field)

        element_pages = defaultdict(set)
        elements = ui.get('elements', {})
        for pid, page in ui.get('pages', {}).items():
            self.contracts['UI:' + pid] = {'kind': 'page', 'id': pid,
                'route': page.get('route'), 'root': page.get('root')}
            root = page.get('root')
            if root not in elements:
                issue('UNDEFINED_UI_ROOT', 'UI:' + pid, str(root))
            for uid in elements:
                current, visited = uid, set()
                while current in elements and current not in visited:
                    if current == root:
                        element_pages[uid].add(pid)
                        break
                    visited.add(current)
                    current = elements[current].get('parent')

        for rid in tree.requirements:
            self.requirements[rid] = {'id': rid, 'source_ref': 'requirements.json#' + rid,
                'step_ids': list(tree.own_steps[rid]),
                'scenario_ids': sorted({tree.steps[s]['scenario']['id'] for s in tree.own_steps[rid]}),
                'depends_on': list(self.dependencies.get(rid, []))}
            for child in tree.children[rid]:
                self.links.append({'from': 'REQ:' + rid, 'to': 'REQ:' + child, 'kind': 'contains'})
            for dependency in self.dependencies.get(rid, []):
                if dependency not in tree.requirements:
                    issue('UNDEFINED_DEPENDENCY', 'REQ:' + rid, dependency)
                self.dependents[dependency].add(rid)
                self.links.append({'from': 'REQ:' + rid, 'to': 'REQ:' + dependency, 'kind': 'declared_dependency'})
            for aid in backend.get('requirements', {}).get(rid, []):
                self.requirement_apis[rid].add(aid)
                self.api_owners[aid].add(rid)
                self.links.append({'from': 'REQ:' + rid, 'to': 'API:' + aid, 'kind': 'uses'})
                if 'API:' + aid not in self.contracts:
                    issue('UNDEFINED_API', 'REQ:' + rid, aid)
            for uid in ui.get('requirements', {}).get(rid, []):
                if uid not in elements:
                    issue('UNDEFINED_UI_ELEMENT', 'REQ:' + rid, uid)
                self.requirement_pages[rid].update(element_pages.get(uid, set()))
            for pid in sorted(self.requirement_pages[rid]):
                self.page_owners[pid].add(rid)
                self.links.append({'from': 'REQ:' + rid, 'to': 'UI:' + pid, 'kind': 'uses'})
        try:
            self.topological_order()
        except ValueError as error:
            issue('DEPENDENCY_CYCLE', 'requirements', str(error))

    def topological_order(self):
        """Order declared dependencies only; containment is not an execution edge."""
        visited, active, result = set(), set(), []

        def visit(rid):
            if rid in active:
                raise ValueError('Cycle in explicitly declared dependencies at ' + rid)
            if rid in visited:
                return
            active.add(rid)
            for dependency in self.dependencies.get(rid, []):
                if dependency in self.requirements:
                    visit(dependency)
            active.remove(rid)
            visited.add(rid)
            result.append(rid)
        for rid in self.requirements:
            visit(rid)
        return result

    def context_for(self, rid):
        """Small references for a model task; full definitions are retrieved on demand."""
        apis, pages = sorted(self.requirement_apis[rid]), sorted(self.requirement_pages[rid])
        refs = ['API:' + aid for aid in apis] + ['UI:' + pid for pid in pages]
        owners = {'REQ:' + rid, *refs}
        return {'requirement_id': rid, 'contract_refs': refs,
            'depends_on': list(self.dependencies.get(rid, [])),
            'notice': 'contract_refs are index keys, not API IDs or routes. Reuse definitions already supplied in the task.',
            'validation_mode': 'report_only',
            'issues': [deepcopy(item) for item in self.issues if item['owner'] in owners]}

    def impact(self, *, requirements=(), apis=(), fields=(), pages=()):
        """Return a conservative related set, not an automatic regression selection."""
        api_set, page_set, reqs = set(apis), set(pages), set(requirements)
        for field in fields:
            api_set.update(self.field_apis.get(field, ()))
        for aid in api_set:
            reqs.update(self.api_owners.get(aid, ()))
        for pid in page_set:
            reqs.update(self.page_owners.get(pid, ()))
        pending = deque(reqs)
        while pending:
            rid = pending.popleft()
            for dependent in self.dependents.get(rid, ()):
                if dependent not in reqs:
                    reqs.add(dependent)
                    pending.append(dependent)
        for rid in reqs:
            api_set.update(self.requirement_apis.get(rid, ()))
            page_set.update(self.requirement_pages.get(rid, ()))
        return {'requirements': sorted(reqs), 'apis': sorted(api_set), 'pages': sorted(page_set),
            'basis': 'conservative declared dependencies and shared contract references'}

    def export(self):
        return deepcopy({'version': 1, 'requirements': self.requirements,
            'contracts': self.contracts, 'links': self.links,
            'validation': {'mode': 'report_only', 'issues': self.issues}})
