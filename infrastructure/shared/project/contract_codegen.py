"""Compile transport glue from canonical API contracts; business rules stay model-owned."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re

from infrastructure.shared.agent.batching import target_path
from infrastructure.shared.project.entrypoints import remember_path
from infrastructure.utils.files import save_json, save_text

STATE = '.arc/contract_codegen.json'
REGISTRY = 'backend/src/api/register.ts'
BACK_TYPES = 'backend/src/api/contract-types.ts'
FRONT_TYPES = 'frontend/src/generated/api-contracts.ts'
CLIENT = 'frontend/src/generated/api-client.ts'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def state(output):
    path = output / STATE
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {'files': {}}


def managed(output, relative):
    path = output / relative
    expected = state(output).get('files', {}).get(relative)
    return bool(expected and path.is_file() and not path.is_symlink() and digest(path) == expected)


def schema_type(schema, depth=0):
    """Render common JSON-schema shapes; unsupported references remain honest unknowns."""
    if not isinstance(schema, dict) or depth > 12 or '$ref' in schema:
        return 'unknown'
    render = lambda item: schema_type(item, depth + 1)
    if 'const' in schema:
        return json.dumps(schema['const'], ensure_ascii=True)
    if isinstance(schema.get('enum'), list) and schema['enum']:
        return '(' + ' | '.join(json.dumps(v, ensure_ascii=True) for v in schema['enum']) + ')'
    for key, joiner in [('oneOf', ' | '), ('anyOf', ' | '), ('allOf', ' & ')]:
        if schema.get(key):
            return '(' + joiner.join(render(item) for item in schema[key]) + ')'
    kind = schema.get('type')
    if isinstance(kind, list):
        return '(' + ' | '.join(render({**schema, 'type': value}) for value in kind) + ')'
    if kind == 'array':
        value = 'Array<' + render(schema.get('items', {})) + '>'
    elif kind == 'object' or 'properties' in schema:
        required = set(schema.get('required', []))
        fields = [json.dumps(name) + ('' if name in required else '?') + ': ' + render(item)
                  for name, item in schema.get('properties', {}).items()]
        additional = schema.get('additionalProperties', True)
        if additional is not False:
            # An unknown index signature keeps declared property types valid, without
            # claiming extra fields are validated or inventing stronger constraints.
            fields.append('[key: string]: unknown')
        value = '{ ' + '; '.join(fields) + ' }'
    else:
        value = {'string': 'string', 'integer': 'number', 'number': 'number',
                 'boolean': 'boolean', 'null': 'null'}.get(kind, 'unknown')
    return '(' + value + ' | null)' if schema.get('nullable') and kind != 'null' else value


def endpoints(contracts):
    result, seen = [], set()
    for aid, api in contracts['apis'].items():
        signature = api['signature']
        method, path = signature['method'].upper(), signature['path']
        if method not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'}:
            raise ValueError('Unsupported transport method: ' + method)
        if not isinstance(path, str) or not path.isascii() or not path.startswith('/') or path.startswith('//') or '#' in path or re.search(r'[?*+()[\]\\]', path):
            raise ValueError('Unsupported route pattern: ' + str(path))
        route = re.sub(r'\{([A-Za-z_][A-Za-z0-9_]*)\}', r':\1', path)
        if '{' in route or '}' in route or re.search(r':(?![A-Za-z_])', route):
            raise ValueError('Unsupported route parameter: ' + path)
        # Parameter names do not distinguish HTTP routes.
        identity = (method, re.sub(r':[A-Za-z_][A-Za-z0-9_]*', ':param', route))
        if identity in seen:
            raise ValueError('Duplicate canonical method/path: ' + method + ' ' + path)
        seen.add(identity)
        result.append({'id': aid, 'method': method, 'path': path, 'route': route, 'api': api})
    # Register static paths before parameterized alternatives. Preserve canonical
    # order among equally specific routes and install explicit HEAD before GET.
    return sorted(result, key=lambda item: (item['route'].count(':'), item['method'] != 'HEAD'))


def type_source(records, frontend=False):
    lines = ['// Compiler-owned transport types; JSON-schema validation and business rules remain in handlers.',
             'export interface ApiContractMap {']
    for record in records:
        api = record['api']
        request = '{ ' + '; '.join(key + '?: ' + schema_type(api.get('request', {}).get(key, {}))
                                  for key in ('params', 'query', 'body', 'headers')) + ' }'
        response = api.get('response', {})
        cases = [response.get('success', {}), *response.get('errors', [])]
        variants = []
        for case in cases:
            status = case.get('status')
            if not isinstance(status, int) or not 100 <= status <= 599:
                raise ValueError('Every response case needs a concrete HTTP status')
            body = 'undefined' if status in {204, 304} or record['method'] == 'HEAD' else schema_type(case.get('body', {}))
            variants.append('{ status: ' + str(status) + '; body: ' + body + ' }')
        lines.append('  ' + json.dumps(record['id']) + ': { request: ' + request + '; response: '
                     + ' | '.join(variants) + ' };')
    lines += ['}', 'export type ApiId = keyof ApiContractMap;',
              'export type ContractRequest<K extends ApiId> = ApiContractMap[K]["request"];',
              'export type ContractResponse<K extends ApiId> = ApiContractMap[K]["response"];']
    if frontend:
        table = {r['id']: {'method': r['method'], 'path': r['path'],
                 'statuses': sorted({case['status'] for case in [r['api']['response']['success'],
                                      *r['api']['response'].get('errors', [])]})} for r in records}
        lines.append('export const apiEndpoints = ' + json.dumps(table, ensure_ascii=True) + ' as const;')
    return '\n'.join(lines) + '\n'


def registry_source(records, paths):
    lines = ['// Compiler-owned canonical route transport. Implement business rules in the handlers.',
        'import type { Express } from "express";', 'import type Database from "better-sqlite3";']
    for number, record in enumerate(records):
        relative = posixpath.relpath(paths[record['id']], 'backend/src/api')
        relative = relative[:-3] + '.js'
        if not relative.startswith('.'):
            relative = './' + relative
        lines.append(f'import {{ handle as api{number} }} from {json.dumps(relative)};')
    lines.append('export function registerApis(app: Express, connection: Database.Database): void {')
    for number, record in enumerate(records):
        lines += [f'  app.{record["method"].lower()}({json.dumps(record["route"])}, async (request, response, next) => {{',
            '    try {', f'      const result = await api{number}({{',
            '        params: Object.fromEntries(Object.entries(request.params).map(([k, v]) => [k, String(v)])),',
            '        query: request.query as Record<string, unknown>,',
            '        body: (request.body ?? {}) as Record<string, unknown>,',
            '        headers: Object.fromEntries(Object.entries(request.headers).map(([k, v]) => [k, Array.isArray(v) ? v.join(", ") : v]))',
            '      }, connection);', '      if (result.headers) response.set(result.headers);',
            '      response.status(result.status);',
            '      if (request.method === "HEAD" || result.status === 204 || result.status === 304 || result.body === undefined) { response.end(); return; }',
            '      const type = response.getHeader("content-type");',
            '      if (Buffer.isBuffer(result.body) || (typeof result.body === "string" && typeof type === "string" && !type.includes("json"))) response.send(result.body);',
            '      else response.json(result.body);', '    } catch (error) { next(error); }', '  });']
    return '\n'.join([*lines, '}', ''])


CLIENT_SOURCE = '''// Compiler-owned JSON transport; no retries, response fabrication or business state.
import { apiEndpoints, type ApiId, type ContractRequest, type ContractResponse } from "./api-contracts";
export type CallOptions<K extends ApiId> = ContractRequest<K> & {
  signal?: AbortSignal; baseURL?: string | URL; credentials?: RequestCredentials;
};
export class UnexpectedApiStatusError extends Error {
  constructor(public status: number, public body: unknown, public headers: Headers) {
    super(`Unexpected API status ${status}`); this.name = "UnexpectedApiStatusError";
  }
}
export async function callApi<K extends ApiId>(id: K, options: CallOptions<K> = {} as CallOptions<K>): Promise<ContractResponse<K> & { headers: Headers }> {
  const endpoint = apiEndpoints[id];
  const method = String(endpoint.method);
  const params = (options.params ?? {}) as Record<string, unknown>;
  const used = new Set<string>();
  const path = endpoint.path.replace(/\\{([A-Za-z_][A-Za-z0-9_]*)\\}|:([A-Za-z_][A-Za-z0-9_]*)/g, (_match, a: string, b: string) => {
    const key = a || b; used.add(key); const value = params[key];
    if (value === undefined || value === null) throw new TypeError(`Missing route parameter ${key}`);
    return encodeURIComponent(String(value));
  });
  const url = new URL(path, options.baseURL ?? globalThis.location.origin);
  for (const [key, value] of Object.entries((options.query ?? {}) as Record<string, unknown>)) {
    if (value === undefined) continue;
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item !== undefined) url.searchParams.append(key, String(item));
    }
  }
  const headers = new Headers(options.headers as HeadersInit | undefined);
  let body: string | undefined;
  if (options.body !== undefined) {
    if (method === "GET" || method === "HEAD") throw new TypeError("GET/HEAD cannot send a body");
    if (headers.has("content-type") && !(headers.get("content-type") ?? "").includes("json"))
      throw new TypeError("Use a custom transport for non-JSON request bodies");
    body = JSON.stringify(options.body);
    if (!headers.has("content-type")) headers.set("content-type", "application/json");
  }
  const response = await fetch(url, { method, headers, body,
    credentials: options.credentials ?? "same-origin", signal: options.signal });
  let value: unknown = undefined;
  if (method !== "HEAD" && response.status !== 204 && response.status !== 304) {
    const text = await response.text();
    if (text) value = (response.headers.get("content-type") ?? "").includes("json") ? JSON.parse(text) : text;
  }
  if (!(endpoint.statuses as readonly number[]).includes(response.status))
    throw new UnexpectedApiStatusError(response.status, value, response.headers);
  return { status: response.status, body: value, headers: response.headers } as ContractResponse<K> & { headers: Headers };
}
'''


def prepare_contracts(output, contracts):
    output = output.resolve()
    previous = state(output)
    report = {'status': 'GENERATED', 'files': dict(previous.get('files', {})), 'skipped': {},
              'managed_registry': False, 'managed_client': False, 'handlers': {}}
    try:
        records = endpoints(contracts)
        if not records:
            raise ValueError('No canonical APIs need transport generation')
        back_types = type_source(records)
        front_types = type_source(records, frontend=True)
        paths = {r['id']: target_path(output, 'api', r['id']) for r in records}
        for path in paths.values():
            target = output / path
            if not target.resolve().is_relative_to(output / 'backend/src') or target.suffix != '.ts' or target.is_symlink():
                raise ValueError('Unsafe or unsupported handler path: ' + path)
        registry = registry_source(records, paths)
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        report.update(status='SKIPPED_UNSUPPORTED_CONTRACT', reason=str(error), files={})
        save_json(output / STATE, report)
        return report

    def writable(path, template=None):
        target = output / path
        if target.is_symlink():
            return False
        if not target.exists() or managed(output, path):
            return True
        return template is not None and target.read_text(encoding='utf-8-sig').replace('\r\n', '\n') == template.replace('\r\n', '\n')

    def publish(path, content):
        save_text(output / path, content)
        report['files'][path] = digest(output / path)

    template = (Path(__file__).parent / 'templates' / REGISTRY).read_text(encoding='utf-8-sig')
    if writable(REGISTRY, template):
        for record in records:
            aid, path = record['id'], paths[record['id']]
            if not (output / path).is_file():
                # An honest TDD stub, never a fabricated successful implementation.
                relative = posixpath.relpath('backend/src/api/types.ts', str(PurePosixPath(path).parent))[:-3] + '.js'
                if not relative.startswith('.'):
                    relative = './' + relative
                save_text(output / path, 'import type { ApiHandler } from ' + json.dumps(relative) + ';\n'
                          'export const handle: ApiHandler = async (_request, _connection) => ({ status: 501, body: { error: "Not implemented" } });\n')
            remember_path(output, 'api', aid, path)
        publish(REGISTRY, registry)
        report.update(managed_registry=True, handlers=paths)
    else:
        report['skipped'][REGISTRY] = 'Existing custom registry preserved'
        report['files'].pop(REGISTRY, None)
    if writable(BACK_TYPES):
        publish(BACK_TYPES, back_types)
    else:
        report['skipped'][BACK_TYPES] = 'Existing custom type file preserved'
        report['files'].pop(BACK_TYPES, None)
    redirects = any(300 <= case['status'] < 400 for record in records
                    for case in [record['api']['response']['success'], *record['api']['response'].get('errors', [])])
    if not redirects and all(writable(path) for path in (CLIENT, FRONT_TYPES)):
        publish(FRONT_TYPES, front_types)
        publish(CLIENT, CLIENT_SOURCE)
        report['managed_client'] = True
    else:
        report['skipped'][CLIENT] = ('Redirect/cache status needs custom browser transport' if redirects
                                    else 'Existing custom client/type files preserved as a pair')
        for path in (CLIENT, FRONT_TYPES):
            report['files'].pop(path, None)
    save_json(output / STATE, report)
    return report
