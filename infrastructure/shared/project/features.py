"""Install optional application helpers without replacing accepted/user code."""
import hashlib
import json
from pathlib import Path

from infrastructure.shared.agent.efficiency import enabled
from infrastructure.utils.files import read_source, save_json, save_text


PREFIX = 'frontend/src/arc-lib/'
MANIFEST = '.arc/feature_runtime.json'
CLIENT = PREFIX + 'api-client.ts'
API_CLIENT = '''// Generated contract identities/routes only; business behavior stays in application code.
import { requestJson } from "./http.js";
type Contract = {method: string; path: string};
export const apiContracts = __CONTRACTS__ satisfies Record<string, Contract>;
export type ApiId = keyof typeof apiContracts;
type QueryValue = string | number | boolean;
export type ApiOptions = {params?: Record<string, string | number>;
  query?: Record<string, QueryValue | QueryValue[] | null | undefined>;
  body?: unknown; headers?: HeadersInit; signal?: AbortSignal};
export function callApi<T = unknown>(id: ApiId, options: ApiOptions = {}): Promise<T> {
  const contract = (apiContracts as Record<string, Contract>)[id];
  if (!contract) throw new Error(`Unknown API contract: ${String(id)}`);
  const path = contract.path.replace(/:([A-Za-z_][A-Za-z0-9_]*)/g, (_match, key: string) => {
    const value = options.params?.[key];
    if (value === undefined || value === null) throw new Error(`Missing route parameter: ${key}`);
    return encodeURIComponent(String(value));
  });
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined && value !== null) for (const item of Array.isArray(value) ? value : [value]) query.append(key, String(item));
  }
  return requestJson<T>(path + (query.size ? "?" + query.toString() : ""),
    {method: contract.method, body: options.body, headers: options.headers, signal: options.signal});
}
'''
GUIDE = {
    PREFIX + 'http.ts': 'requestJson<T=unknown>(path, {method?, body?, headers?, signal?}); HttpError has status/data. T does not validate response data.',
    PREFIX + 'useSubmit.ts': 'useSubmit<T>() returns {state, pending, run(action), reset}. run shares one in-flight promise; caller handles rejection and success navigation/refresh.',
    PREFIX + 'AsyncBoundary.tsx': 'AsyncBoundary<T> accepts state, idle?, pending, error(error), children(data). Caller supplies all visible wording and roles.',
    CLIENT: 'callApi<T=unknown>(apiId, {params?, query?, body?, headers?, signal?}) uses canonical method/path; imports from ./arc-lib/api-client.js relative to App.tsx.'}


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def prepare_features(output):
    if not enabled('feature_runtime'):
        return
    output = Path(output)
    previous = {}
    try:
        previous = json.loads((output / MANIFEST).read_text(encoding='utf-8-sig')).get('managed_hashes', {})
    except (OSError, ValueError, AttributeError):
        pass
    sources = {PREFIX + path.name: read_source(path) for path in Path(__file__).with_suffix('').glob('*') if path.is_file()}
    apis = {}
    try:
        backend = json.loads((output / '.arc/backend_apis.json').read_text(encoding='utf-8-sig'))
        for aid, api in backend.get('apis', {}).items():
            signature = api.get('signature', {})
            method, path = signature.get('method'), signature.get('path')
            if isinstance(method, str) and isinstance(path, str) and path.startswith('/api/'):
                apis[aid] = {'method': method, 'path': path}
    except (OSError, ValueError, AttributeError):
        pass
    # Computed property names preserve arbitrary IDs, including __proto__, as data.
    definitions = '{\n' + ',\n'.join('  [' + json.dumps(aid, ensure_ascii=False) + ']: '
        + json.dumps(record, ensure_ascii=False) for aid, record in apis.items()) + '\n}'
    sources[CLIENT] = API_CLIENT.replace('__CONTRACTS__', definitions)
    managed, available, preserved = {}, {}, []
    for relative, content in sources.items():
        target = output / relative
        if target.is_symlink() or not target.resolve().is_relative_to(output.resolve()):
            raise ValueError('Feature helper path escapes the application: ' + relative)
        current = read_source(target) if target.is_file() else None
        if current is None or _digest(current) == previous.get(relative):
            save_text(target, content)
            current = content
        if current == content:
            managed[relative] = _digest(content)
            if relative in GUIDE:
                available[relative] = GUIDE[relative]
        else:
            preserved.append(relative)
    if PREFIX + 'http.ts' not in managed:
        available.pop(CLIENT, None)
    save_json(output / MANIFEST, {'version': 1, 'managed_hashes': managed,
        'helpers': available, 'preserved_custom_files': preserved,
        'notice': 'Optional transport/state helpers, not business implementations. Use original API payloads, validation, security and UI wording. Never change tests to use these helpers.'})


def runtime_context(output):
    if not enabled('feature_runtime'):
        return None
    try:
        data = json.loads((Path(output) / MANIFEST).read_text(encoding='utf-8-sig'))
        available = {path: guide for path, guide in data.get('helpers', {}).items()
            if path in GUIDE and (Path(output) / path).is_file()
            and not (Path(output) / path).is_symlink()
            and (Path(output) / path).resolve().is_relative_to(Path(output).resolve())
            and _digest(read_source(Path(output) / path)) == data['managed_hashes'].get(path)}
        if PREFIX + 'http.ts' not in available:
            available.pop(CLIENT, None)
        return {'helpers': available, 'notice': data['notice']} if available else None
    except (OSError, ValueError, KeyError, AttributeError):
        return None
