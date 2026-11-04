"""Generic contract transport generation, ownership and real HTTP/client behavior."""
from copy import deepcopy
import json
import os
import posixpath
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from infrastructure.shared.project.contract_codegen import (prepare_contracts, managed, schema_type,
    endpoints, REGISTRY, CLIENT, FRONT_TYPES, BACK_TYPES, STATE)
from infrastructure.shared.agent.files import editable_application_path
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.utils.files import save_text

TEMPLATES = Path(__file__).resolve().parents[1] / 'infrastructure/shared/project/templates'


def contract(method, path, status=200, body=None, errors=()):
    return {'signature': {'name': method.lower(), 'method': method, 'path': path},
        'request': {'params': {'type': 'object', 'properties': {'id': {'type': 'string'}}},
                    'query': {'type': 'object'}, 'body': {'type': 'object'}, 'headers': {'type': 'object'}},
        'response': {'success': {'status': status, 'body': body or {'type': 'object'}, 'headers': {}},
                     'errors': list(errors)}, 'read': [], 'write': []}


class Ownership(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)
        self.contracts = {'apis': {'GET-item': contract('GET', '/api/items/{id}')}, 'requirements': {}}
        save_text(self.output / REGISTRY, (TEMPLATES / REGISTRY).read_text(encoding='utf8'))

    def test_registry_and_client_are_managed_but_501_business_stub_stays_editable(self):
        report = prepare_contracts(self.output, self.contracts)
        self.assertTrue(report['managed_registry'])
        self.assertTrue(report['managed_client'])
        for path in (REGISTRY, CLIENT, FRONT_TYPES, BACK_TYPES):
            self.assertTrue(managed(self.output, path))
            self.assertFalse(editable_application_path(self.output, path))
        handler = selected_path(self.output, 'api', 'GET-item')
        self.assertIn('status: 501', (self.output / handler).read_text(encoding='utf8'))
        self.assertTrue(editable_application_path(self.output, handler))
        before = (self.output / REGISTRY).read_bytes()
        prepare_contracts(self.output, self.contracts)
        self.assertEqual((self.output / REGISTRY).read_bytes(), before)

    def test_custom_registry_and_client_are_preserved_and_not_taken_over(self):
        save_text(self.output / REGISTRY, '// custom middleware and routes\n')
        save_text(self.output / CLIENT, '// custom request transport\n')
        report = prepare_contracts(self.output, self.contracts)
        self.assertFalse(report['managed_registry'])
        self.assertFalse(report['managed_client'])
        self.assertEqual((self.output / REGISTRY).read_text(encoding='utf8'), '// custom middleware and routes\n')
        self.assertEqual((self.output / CLIENT).read_text(encoding='utf8'), '// custom request transport\n')
        self.assertIsNone(selected_path(self.output, 'api', 'GET-item'))

    def test_changed_contract_regenerates_owned_glue_but_preserves_business_and_custom_edits(self):
        prepare_contracts(self.output, self.contracts)
        handler = selected_path(self.output, 'api', 'GET-item')
        save_text(self.output / handler, '// actual business implementation\n')
        value = deepcopy(self.contracts)
        value['apis']['GET-item']['signature']['path'] = '/api/records/{id}'
        prepare_contracts(self.output, value)
        self.assertIn('/api/records/:id', (self.output / REGISTRY).read_text(encoding='utf8'))
        self.assertEqual((self.output / handler).read_text(encoding='utf8'), '// actual business implementation\n')
        save_text(self.output / CLIENT, '// deliberate custom override\n')
        report = prepare_contracts(self.output, value)
        self.assertFalse(report['managed_client'])
        self.assertFalse(managed(self.output, FRONT_TYPES))
        self.assertTrue(editable_application_path(self.output, FRONT_TYPES))

    def test_unsupported_or_duplicate_route_falls_back_and_releases_owned_stale_glue(self):
        prepare_contracts(self.output, self.contracts)
        before = (self.output / REGISTRY).read_bytes()
        value = deepcopy(self.contracts)
        value['apis']['duplicate'] = contract('GET', '/api/items/{other}')
        report = prepare_contracts(self.output, value)
        self.assertEqual(report['status'], 'SKIPPED_UNSUPPORTED_CONTRACT')
        self.assertEqual((self.output / REGISTRY).read_bytes(), before)
        self.assertFalse(managed(self.output, REGISTRY))
        self.assertTrue(editable_application_path(self.output, REGISTRY))
        for path in ['//outside.invalid/api', '/api/x?query=y', '/api/{bad-name}', '/api/中文']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                endpoints({'apis': {'A': contract('GET', path)}})

    def test_schema_types_preserve_required_null_arrays_and_unknown_references(self):
        schema = {'type': 'object', 'properties': {'id': {'type': 'string'},
            'values': {'type': 'array', 'items': {'type': ['number', 'null']}}}, 'required': ['id'], 'additionalProperties': False}
        result = schema_type(schema)
        self.assertIn('"id": string', result)
        self.assertIn('"values"?: Array<(number | null)>', result)
        self.assertEqual(schema_type({'$ref': '#/unresolved'}), 'unknown')
        self.assertEqual(schema_type({'const': False}), 'false')

    def test_redirect_contract_retains_server_generation_and_uses_custom_browser_transport(self):
        value = {'apis': {'redirect': contract('GET', '/api/continue', 302)}}
        report = prepare_contracts(self.output, value)
        self.assertTrue(report['managed_registry'])
        self.assertFalse(report['managed_client'])
        self.assertIn('custom browser transport', report['skipped'][CLIENT])


class RealTransport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        location = os.getenv('ARC_CONTRACT_TEST_NODE_MODULES')
        if not location or not shutil.which('node'):
            raise unittest.SkipTest('Set ARC_CONTRACT_TEST_NODE_MODULES to existing compatible Node dependencies')
        cls.dependencies = Path(location).resolve()
        if not (cls.dependencies / 'tsx').is_dir():
            raise unittest.SkipTest('tsx dependency not available')

    def test_new_batch_implements_501_stubs_in_two_scripted_rounds_with_real_http_tests(self):
        from infrastructure.stages.backend.batching import implement_batches
        from infrastructure.stages.backend.runtime import prepare_runtime
        from infrastructure.stages.requirements.tree import RequirementTree
        from unittest.mock import Mock, patch
        with TemporaryDirectory() as directory:
            output = Path(directory)
            shutil.copytree(TEMPLATES, output, dirs_exist_ok=True)
            junction = output / 'node_modules'
            if os.name == 'nt':
                quote = lambda p: "'" + str(p).replace("'", "''") + "'"
                subprocess.run(['powershell', '-NoProfile', '-Command', 'New-Item -ItemType Junction -Path '
                    + quote(junction) + ' -Target ' + quote(self.dependencies) + ' | Out-Null'], check=True)
            else:
                junction.symlink_to(self.dependencies, target_is_directory=True)
            try:
                prepare_runtime(output)
                for name in ('seeds', 'tables'):
                    (output / 'backend/src/db' / name).mkdir(parents=True, exist_ok=True)
                apis = {'ping': contract('GET', '/api/ping'), 'echo': contract('POST', '/api/echo')}
                tree = RequirementTree({'id': 'ROOT', 'name': 'Transport demo', 'children': [
                    {'id': rid, 'name': rid, 'description': 'Return the documented pure response without writes.',
                     'scenarios': [{'id': 'SCN-' + rid, 'steps': [{'id': 'STEP-' + rid,
                         'Given': 'A running API', 'When': 'Call ' + rid,
                         'Then': 'Return ' + ('{"ok":true}' if rid == 'ping' else 'the supplied text')}]}]}
                    for rid in apis]})
                calls = []
                class Model:
                    def generate_json(inner, instructions, request):
                        task = request['task']
                        calls.append(task)
                        if 'implementation_paths' not in task:
                            edits = []
                            for aid, path in task['test_paths'].items():
                                imported = posixpath.relpath('backend/tests/support/context.ts', str(Path(path).parent).replace('\\', '/'))[:-3] + '.js'
                                expected = '{ok:true}' if aid == 'ping' else '{echo:"hello"}'
                                method = apis[aid]['signature']['method']
                                source = 'import {test} from "node:test"; import assert from "node:assert/strict";\n'
                                source += 'import {createApiTest} from ' + json.dumps(imported) + ';\n'
                                source += 'test("canonical ' + aid + '",async t=>{const {baseURL}=createApiTest(t);'
                                source += 'const r=await fetch(new URL(' + json.dumps(apis[aid]['signature']['path']) + ',baseURL),'
                                source += '{method:' + json.dumps(method)
                                if aid == 'echo':
                                    source += ',headers:{"content-type":"application/json"},body:JSON.stringify({text:"hello"})'
                                source += '});assert.equal(r.status,200);assert.deepEqual(await r.json(),' + expected + ');});\n'
                                edits.append({'tool': 'edit_file', 'path': path, 'operation': 'create', 'new_content': source})
                            return {'tool_calls': edits}
                        self.assertTrue(task['compiler_transport']['managed'])
                        self.assertNotIn(REGISTRY, request['files'])
                        self.assertTrue(all(not v['writable'] for p, v in request['files'].items() if '/tests/' in p))
                        return {'tool_calls': [{'tool': 'edit_file', 'path': path, 'operation': 'replace',
                            'old_content': '({ status: 501, body: { error: "Not implemented" } })',
                            'new_content': '({status:200,body:' + ('{ok:true}' if aid == 'ping' else '{echo:request.body.text}') + '})',
                            } for aid, path in task['implementation_paths'].items()]}
                # The generated stubs use _request; choose the echo expression's actual parameter.
                class ActualModel(Model):
                    def generate_json(inner, instructions, request):
                        result = super().generate_json(instructions, request)
                        for edit in result['tool_calls']:
                            edit['new_content'] = edit['new_content'].replace('request.body.text', '_request.body.text')
                        return result
                with patch.dict(os.environ, {'ARC_AGENT_PROFILE': 'b4'}):
                    result = implement_batches(output / '.arc', tree, {'entities': {}},
                        {'apis': apis, 'requirements': {rid: [rid] for rid in apis}}, ActualModel(), Mock(),
                        2, 5, 'author tests from canonical requirements', 'implement handlers')
                self.assertEqual(result['status'], 'GREEN', result.get('verification'))
                self.assertEqual(len(calls), 2)
                self.assertEqual(result['summary']['pass'], 2)
                self.assertTrue(managed(output, REGISTRY))
                # The method set deliberately omits HEAD, catching literal-union
                # comparisons that compile only when every method is present.
                compiled = subprocess.run(['node', 'node_modules/typescript/bin/tsc', '--noEmit', '-p', 'frontend/tsconfig.json'],
                    cwd=output, text=True, encoding='utf8', capture_output=True, timeout=60)
                self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            finally:
                if os.name == 'nt':
                    os.rmdir(junction)
                else:
                    junction.unlink()

    def test_real_registry_client_types_cookies_route_identity_queries_and_empty_responses(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            shutil.copytree(TEMPLATES, output, dirs_exist_ok=True)
            junction = output / 'node_modules'
            if os.name == 'nt':
                quote = lambda p: "'" + str(p).replace("'", "''") + "'"
                subprocess.run(['powershell', '-NoProfile', '-Command', 'New-Item -ItemType Junction -Path '
                    + quote(junction) + ' -Target ' + quote(self.dependencies) + ' | Out-Null'], check=True)
            else:
                junction.symlink_to(self.dependencies, target_is_directory=True)
            try:
                apis = {'get': contract('GET', '/api/items/{id}'),
                    'search': contract('GET', '/api/items/search'),
                    'post': contract('POST', '/api/items', 201, errors=[{'status': 422, 'body': {'type': 'object'}}]),
                    'delete': contract('DELETE', '/api/items/{id}', 204),
                    'head': contract('HEAD', '/api/items/{id}'),
                    'text': contract('GET', '/api/plain', 200, {'type': 'string'}),
                    'unexpected': contract('GET', '/api/unexpected')}
                report = prepare_contracts(output, {'apis': apis})
                self.assertTrue(report['managed_registry'])
                implementations = {
                    'get': 'return {status:200, body:{id:request.params.id,tags:request.query.tag,token:request.headers["x-token"]},headers:{"x-role":"get"}};',
                    'search': 'return {status:200,body:{id:"static-search"}};',
                    'post': '''if (typeof request.body.title !== "string") return {status:422,body:{error:"title required"}};
connection.prepare("INSERT INTO items (title) VALUES (?)").run(request.body.title);
return {status:201,body:{title:request.body.title},headers:{"set-cookie":["a=1; HttpOnly; Path=/","b=2; Path=/"]}};''',
                    'delete': 'connection.prepare("DELETE FROM items").run(); return {status:204,body:undefined,headers:{"x-deleted":"yes"}};',
                    'head': 'return {status:200,body:undefined,headers:{"x-role":"head"}};',
                    'text': 'return {status:200,body:"plain response",headers:{"content-type":"text/plain"}};',
                    'unexpected': 'return {status:503,body:{error:"temporary"}};'}
                for aid, body in implementations.items():
                    path = report['handlers'][aid]
                    save_text(output / path, 'import type { ApiHandler } from "./types.js";\n'
                        'export const handle: ApiHandler = async (request, connection) => { ' + body + ' };\n')
                script = '''import assert from "node:assert/strict";
import express from "express";
import Database from "better-sqlite3";
import { registerApis } from "./backend/src/api/register.ts";
import { callApi, UnexpectedApiStatusError } from "./frontend/src/generated/api-client.ts";
const database=new Database(":memory:"); database.exec("CREATE TABLE items(title TEXT NOT NULL)");
const app=express(); let requests=0; app.use((_q,_r,next)=>{requests++;next()}); app.use(express.json()); registerApis(app,database);
const server=app.listen(0,"127.0.0.1"); await new Promise(resolve=>server.once("listening",resolve));
const baseURL=`http://127.0.0.1:${server.address().port}`;
try {
 const found=await callApi("get",{baseURL,params:{id:"a/b 中文"},query:{tag:["one","two"]},headers:{"x-token":"token"}});
 assert.equal(found.body.id,"a/b 中文"); assert.deepEqual(found.body.tags,["one","two"]); assert.equal(found.body.token,"token");
 const search=await callApi("search",{baseURL}); assert.equal(search.body.id,"static-search");
 const before=requests; await assert.rejects(callApi("get",{baseURL}),/Missing route parameter/); assert.equal(requests,before);
 const created=await callApi("post",{baseURL,body:{title:"created"}}); assert.equal(created.status,201);
 assert.equal(created.body.title,"created"); assert.equal(created.headers.getSetCookie().length,2);
 assert.equal(database.prepare("SELECT count(*) n FROM items").get().n,1);
 const rejected=await callApi("post",{baseURL,body:{}}); assert.equal(rejected.status,422);
 assert.equal(database.prepare("SELECT count(*) n FROM items").get().n,1);
 const head=await callApi("head",{baseURL,params:{id:"x"}}); assert.equal(head.headers.get("x-role"),"head"); assert.equal(head.body,undefined);
 const plain=await callApi("text",{baseURL}); assert.equal(plain.body,"plain response");
 const count=requests; await assert.rejects(callApi("unexpected",{baseURL}),error=>error instanceof UnexpectedApiStatusError && error.status===503 && error.body.error==="temporary"); assert.equal(requests,count+1);
 const noJSON=requests; await assert.rejects(callApi("post",{baseURL,body:{title:"wrong protocol"},headers:{"content-type":"text/plain"}}),/custom transport/); assert.equal(requests,noJSON);
 const deleted=await callApi("delete",{baseURL,params:{id:"x"}}); assert.equal(deleted.status,204); assert.equal(deleted.body,undefined); assert.equal(deleted.headers.get("x-deleted"),"yes");
 assert.equal(database.prepare("SELECT count(*) n FROM items").get().n,0);
 console.log(JSON.stringify({status:"GREEN",real_model_requests:0}));
} finally { await new Promise(resolve=>server.close(resolve)); database.close(); }
'''
                save_text(output / 'verify.mjs', script)
                result = subprocess.run(['node', '--import', 'tsx', 'verify.mjs'], cwd=output,
                                        text=True, encoding='utf8', capture_output=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for config in ('backend/tsconfig.json', 'frontend/tsconfig.json'):
                    compiled = subprocess.run(['node', 'node_modules/typescript/bin/tsc', '--noEmit', '-p', config],
                        cwd=output, text=True, encoding='utf8', capture_output=True, timeout=60)
                    self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            finally:
                if os.name == 'nt':
                    os.rmdir(junction)
                else:
                    junction.unlink()


if __name__ == '__main__':
    unittest.main()
