"""The same registry handles unrelated domains without business-specific branches."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from infrastructure.shared.contracts import ContractRegistry
from infrastructure.shared.agent.discovery import project_index
from infrastructure.stages.backend.context import requirement_context
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.utils.files import save_json
from infrastructure.stages.frontend.triggers.unified import locate_failures
from infrastructure.stages.frontend.triggers.acceptance import acceptance_path


DOMAINS = [('knowledge-base', 'Document', 'title'), ('store', 'Product', 'stock'),
    ('task-manager', 'WorkItem', 'state')]


def fixture(domain, entity, field):
    raw = {'id': 'ROOT', 'children': [
        {'id': 'VIEW', 'depends_on': ['CREATE'], 'scenarios': [{'id': 'SCENARIO-VIEW',
            'steps': [{'id': 'STEP-VIEW', 'Given': 'An existing item', 'When': 'Open it', 'Then': 'See its value'}]}]},
        {'id': 'CREATE'}, {'id': 'UNRELATED'}]}
    tree = RequirementTree(raw)
    symbol = entity + '.' + field
    schema = {'entities': {entity: {'fields': {field: {'type': 'string'}}}}}
    backend = {'apis': {
        'WRITE': {'signature': {'method': 'POST', 'path': '/api/' + domain},
            'read': [], 'write': [symbol], 'response': {'value': field}},
        'READ': {'signature': {'method': 'GET', 'path': '/api/' + domain + '/:id'},
            'read': [symbol], 'write': []}},
        'requirements': {'CREATE': ['WRITE'], 'VIEW': ['READ']}}
    ui = {'pages': {'EDITOR': {'route': '/' + domain + '/new', 'root': 'EDIT-ROOT'},
        'DETAIL': {'route': '/' + domain + '/:id', 'root': 'VIEW-ROOT'}},
        'elements': {'EDIT-ROOT': {'parent': None}, 'SAVE': {'parent': 'EDIT-ROOT'},
            'VIEW-ROOT': {'parent': None}, 'VALUE': {'parent': 'VIEW-ROOT'}},
        'requirements': {'CREATE': ['SAVE'], 'VIEW': ['VALUE']}}
    return tree, schema, backend, ui


class GenericContracts(unittest.TestCase):
    def test_same_builder_indexes_three_domains(self):
        for domain, entity, field in DOMAINS:
            with self.subTest(domain=domain):
                tree, schema, backend, ui = fixture(domain, entity, field)
                registry = ContractRegistry(tree, schema, backend, ui)
                data = registry.export()
                self.assertFalse(data['validation']['issues'])
                self.assertIn('DB:' + entity + '.' + field, data['contracts'])
                self.assertEqual(registry.context_for('VIEW')['depends_on'], ['CREATE'])
                self.assertIn('API:READ', registry.context_for('VIEW')['contract_refs'])
                self.assertEqual(data['contracts']['API:WRITE']['response'], {'value': field})
                self.assertEqual(data['requirements']['VIEW']['scenario_ids'], ['SCENARIO-VIEW'])

    def test_declared_dependencies_order_tasks_without_inventing_containment_edges(self):
        registry = ContractRegistry(*fixture(*DOMAINS[0]))
        order = registry.topological_order()
        self.assertLess(order.index('CREATE'), order.index('VIEW'))
        edges = registry.export()['links']
        self.assertTrue(any(e['kind'] == 'contains' for e in edges))
        dependencies = [e for e in edges if e['kind'] == 'declared_dependency']
        self.assertEqual(dependencies, [{'from': 'REQ:VIEW', 'to': 'REQ:CREATE', 'kind': 'declared_dependency'}])

    def test_field_change_finds_owners_and_pages_but_not_unrelated_requirement(self):
        for domain, entity, field in DOMAINS:
            registry = ContractRegistry(*fixture(domain, entity, field))
            impact = registry.impact(fields=[entity + '.' + field])
            self.assertEqual(impact['requirements'], ['CREATE', 'VIEW'])
            self.assertEqual(impact['apis'], ['READ', 'WRITE'])
            self.assertEqual(impact['pages'], ['DETAIL', 'EDITOR'])

    def test_requirement_change_includes_explicit_downstream_dependencies(self):
        registry = ContractRegistry(*fixture(*DOMAINS[1]))
        self.assertEqual(registry.impact(requirements=['CREATE'])['requirements'], ['CREATE', 'VIEW'])
        self.assertEqual(registry.impact(requirements=['UNRELATED'])['requirements'], ['UNRELATED'])

    def test_undefined_field_and_api_are_reported_with_owners(self):
        tree, schema, backend, ui = fixture(*DOMAINS[1])
        backend['apis']['READ']['read'] = ['Product.undefined']
        backend['requirements']['CREATE'].append('MISSING')
        registry = ContractRegistry(tree, schema, backend, ui)
        issues = registry.export()['validation']['issues']
        self.assertIn('UNDEFINED_DB_FIELD', {x['code'] for x in issues})
        self.assertIn('UNDEFINED_API', {x['code'] for x in issues})
        self.assertTrue(registry.context_for('VIEW')['issues'])

    def test_cycles_and_missing_dependencies_report_without_hiding_artifacts(self):
        tree, schema, backend, ui = fixture(*DOMAINS[2])
        tree.dependencies['CREATE'] = ['VIEW', 'MISSING']
        registry = ContractRegistry(tree, schema, backend, ui)
        codes = {issue['code'] for issue in registry.export()['validation']['issues']}
        self.assertIn('DEPENDENCY_CYCLE', codes)
        self.assertIn('UNDEFINED_DEPENDENCY', codes)
        with self.assertRaises(ValueError):
            registry.topological_order()
        self.assertEqual(registry.impact(requirements=['CREATE'])['requirements'], ['CREATE', 'VIEW'])

    def test_domains_are_isolated_and_exports_cannot_mutate_registry(self):
        first = ContractRegistry(*fixture(*DOMAINS[0]))
        second = ContractRegistry(*fixture(*DOMAINS[1]))
        exported = first.export()
        exported['contracts'].clear()
        self.assertTrue(first.export()['contracts'])
        self.assertNotIn('DB:Document.title', second.export()['contracts'])
        self.assertEqual(second.impact(fields=['Document.title'])['requirements'], [])

    def test_context_tools_retrieve_contract_and_dependency_records(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            registry = ContractRegistry(*fixture(*DOMAINS[0]))
            save_json(root / '.arc/contracts.json', registry.export())
            index = project_index(root, kinds=('contract', 'dependency'))
            api = index.query({'kind': 'contract', 'ids': ['API:READ']})['records']['API:READ']
            self.assertEqual(api['signature']['method'], 'GET')
            requirement = index.query({'kind': 'dependency', 'ids': ['VIEW']})['records']['VIEW']
            self.assertEqual(requirement['depends_on'], ['CREATE'])

    def test_explicit_dependencies_survive_requirement_context(self):
        tree, *_ = fixture(*DOMAINS[0])
        self.assertEqual(requirement_context(tree, 'VIEW')['depends_on'], ['CREATE'])
        self.assertNotIn('depends_on', requirement_context(tree, 'CREATE'))
        with self.assertRaises(ValueError):
            RequirementTree({'id': 'ROOT', 'depends_on': 'CREATE'})

    def test_failure_localization_ignores_inventory_of_passing_suites(self):
        tree, schema, backend, ui = fixture(*DOMAINS[0])
        registry = ContractRegistry(tree, schema, backend, ui)
        verification = {'acceptance': {'status': 'FAILED', 'result': {
            'files': {acceptance_path('CREATE'): 1, acceptance_path('VIEW'): 1},
            'failures': ['Wrong result\nTest file: ' + acceptance_path('VIEW')]}}}
        with TemporaryDirectory() as directory:
            result = locate_failures(verification, tree, backend, ui, Path(directory), registry)
        self.assertEqual(result['roots'], ['VIEW'])
        self.assertEqual(result['related']['requirements'], ['VIEW'])
        self.assertNotIn('CREATE', result['roots'])


if __name__ == '__main__':
    unittest.main()
