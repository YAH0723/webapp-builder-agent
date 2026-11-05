"""Install versioned, business-neutral helpers and protect their ownership."""
from hashlib import sha256
import json
from pathlib import Path

from infrastructure.shared.project.initialize import initialize_project
from infrastructure.utils.files import save_json, save_text

SOURCE = Path(__file__).with_name('runtime')
REGISTER = '''import type {Express} from "express";
import type Database from "better-sqlite3";
import {registerBusiness} from "../business/index.js";
import {errorHandler} from "../runtime/http.js";
export function registerApis(app: Express, db: Database.Database) {
  registerBusiness(app, db);
  app.use(errorHandler);
}
'''
BUSINESS = '''import type {Express} from "express";
import type Database from "better-sqlite3";
// Application-owned: define actual schema/startup data and routes from requirements.
export function initializeBusiness(_db: Database.Database): void {}
export function registerBusiness(_app: Express, _db: Database.Database): void {}
'''

API_GUIDE = '''REUSABLE RUNTIME (read-only; import helpers, do not copy their implementations)
backend/src/runtime/store.ts: DocumentStore(db). create(resource,data,id?), get(resource,id),
list(resource), update(resource,id,partialData), delete(resource,id), transaction(() => value).
Records are {id:string,data:Record<string,unknown>,createdAt,updatedAt}. list returns ALL records,
in insertion order: business filtering/pagination/sorting/relationships remain application-owned.
This is optional JSON document storage backed by real SQLite, not a relational schema compiler.
Use the supplied better-sqlite3 db directly for SQL tables, joins, constraints, and complex queries.
Create schema idempotently in initializeBusiness(db); seed ONLY explicit requirement startup data,
idempotently. No general business API, authorization, relationships, cascades or seed data are installed.
backend/src/runtime/http.ts: HttpError(status,message,details?), endpoint(async(req,res)=>...),
requiredText(value,label,maxLength?), positiveInteger(value,label). endpoint forwards exceptions
to the fixed error handler. Register real routes in registerBusiness(app,db), not an unused module.
The fixed server calls initializeBusiness then registerBusiness and serves built frontend assets.
backend imports MUST use .js suffixes (NodeNext); frontend imports omit suffixes.
frontend/src/runtime/api.ts: api<T>(relativePath,{method?,json?,...RequestInit}) returns parsed body,
throws ApiError(status,body) on non-2xx; 204 returns undefined. Cookies are same-origin. No retries.
frontend/src/runtime/ui.tsx:
- Layout({title,navigation?,actions?,children}), Link({href,...anchorProps}), navigate(path,replace?)
- useLocation() -> {path,search:URLSearchParams,url}; supports real routes and browser back/forward.
- useResource<T>(path|null) -> {data?,loading,error?,reload()}; reload after mutation.
- Field({label,error?,children:oneControl}) provides associated label/id, required input still native.
- Notice({error?,children}), DataTable<T>({rows,columns:[{key,title,render(row)}],rowKey,empty?})
- ConfirmDialog({open,title,children?,confirmLabel,cancelLabel,busy?,onConfirm(),onCancel()}).
App.tsx must export App; main.tsx mounts it. Use real data and exact requirement labels/routes.
Compose these primitives or write custom UI/CSS for specialized requirements. Runtime styling is
only a starting point: match references with business CSS; never substitute a screenshot for UI.
'''


def writable(path):
    return (path.startswith('backend/src/business/') and path.endswith(('.ts', '.sql'))) or (
        path.startswith('frontend/src/') and '/runtime/' not in path
        and path != 'frontend/src/main.tsx' and path.endswith(('.ts', '.tsx', '.css')))


def install_runtime(output, port=3000):
    output = Path(output).resolve()
    initialize_project(output, port=port)
    templates = Path(__file__).parents[1] / 'shared/project/templates'
    state_path = output / '.arc/compact-runtime.json'
    previous = json.loads(state_path.read_text(encoding='utf8')) if state_path.is_file() else {'files': {}}
    replacements = {p.relative_to(SOURCE).as_posix(): p.read_text(encoding='utf8')
                    for p in SOURCE.rglob('*') if p.is_file()}
    initializer = (templates / 'backend/src/db/initialize.ts').read_text(encoding='utf-8-sig')
    initializer = 'import {initializeBusiness} from "../business/index.js";\n' + initializer
    initializer = initializer.replace('      seedDatabase(connection);', '      seedDatabase(connection);\n      initializeBusiness(connection);')
    replacements.update({'backend/src/api/register.ts': REGISTER, 'backend/src/db/initialize.ts': initializer})
    # Validate every destination before writing anything: old business sources are never erased.
    for relative, content in replacements.items():
        path = output / relative
        if path.is_symlink() or not path.resolve().is_relative_to(output):
            raise ValueError('Unsafe runtime path: ' + relative)
        if path.exists():
            actual = path.read_text(encoding='utf-8-sig')
            original = templates / relative
            pristine = original.is_file() and actual == original.read_text(encoding='utf-8-sig')
            owned = previous['files'].get(relative) == sha256(path.read_bytes()).hexdigest()
            if actual != content and not pristine and not owned:
                raise ValueError('Refusing to overwrite custom runtime source: ' + relative)
    if not state_path.is_file():
        app = output / 'frontend/src/App.tsx'
        if app.read_text(encoding='utf-8-sig') != (templates / 'frontend/src/App.tsx').read_text(encoding='utf-8-sig'):
            raise ValueError('Compact generation requires a fresh scaffold; existing application was preserved')
    for relative, content in replacements.items(): save_text(output / relative, content)
    entry = output / 'backend/src/business/index.ts'
    if not entry.exists(): save_text(entry, BUSINESS)
    save_json(state_path, {'version': 1, 'files': {p: sha256((output / p).read_bytes()).hexdigest() for p in replacements}})
    return sorted(replacements)


def verify_runtime(output):
    output = Path(output)
    state = json.loads((output / '.arc/compact-runtime.json').read_text(encoding='utf8'))
    for relative, expected in state['files'].items():
        path = output / relative
        if not path.is_file() or path.is_symlink() or sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Compiler-owned runtime changed: ' + relative)
