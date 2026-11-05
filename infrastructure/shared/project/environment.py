"""Compiler-owned environment recovery and pipeline-wide stop conditions."""
import json
from pathlib import Path
import shutil
import subprocess

from infrastructure.shared.agent.batching import enabled
from infrastructure.utils.files import save_json, save_text
from infrastructure.utils.processes import capture_process


class EnvironmentBlocked(Exception):
    """Not a business/test failure; must bypass local model repair and rollback loops."""


def active():
    return enabled('environment_guards')


def protected(path):
    return active() and path in {'package.json', 'package-lock.json', 'backend/package.json',
        'frontend/package.json', 'backend/tsconfig.json', 'frontend/tsconfig.json', 'deploy.sh', '.npmrc'}


def block(output, reason, **details):
    save_json(output / '.arc/environment.json', {'status': 'BLOCKED_ENVIRONMENT',
        'reason': reason, 'details': details, 'model_repair_allowed': False})
    raise EnvironmentBlocked(reason)


def workspace_contract(output):
    """Protect fixed scaffold topology, without overwriting dependency additions or custom fields."""
    if not active():
        return
    templates = Path(__file__).parent / 'templates'
    for name, keys in [('package.json', ('workspaces',)), ('frontend/package.json', ('name',)),
                       ('backend/package.json', ('name',))]:
        try:
            actual = json.loads((output / name).read_text(encoding='utf-8-sig'))
            expected = json.loads((templates / name).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError) as error:
            block(output, 'Missing or invalid workspace manifest: ' + name, error=str(error))
        # Restore only compiler-defined topology/build/start fields, never dependencies.
        changed = [key for key in keys if actual.get(key) != expected.get(key)]
        required_scripts = ('build', 'start') if name != 'frontend/package.json' else ('build',)
        scripts = actual.setdefault('scripts', {})
        if not isinstance(scripts, dict):
            block(output, 'Invalid scripts map in ' + name)
        changed += ['scripts.' + key for key in required_scripts
                    if scripts.get(key) != expected['scripts'].get(key)]
        if changed:
            for key in keys:
                actual[key] = expected[key]
            for key in required_scripts:
                if key in expected['scripts']:
                    scripts[key] = expected['scripts'][key]
            save_json(output / name, actual)
            path = output / '.arc/environment_repairs.jsonl'
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf8') as stream:
                stream.write(json.dumps({'file': name, 'restored_fields': changed}) + '\n')


PROBE = r'''import {createRequire} from "node:module";
import {resolve} from "node:path";
import {pathToFileURL} from "node:url";
const failures=[];
for(const [workspace,names] of [["backend",["express","better-sqlite3","tsx","typescript"]],
 ["frontend",["vite","@vitejs/plugin-react","@playwright/test","react","react-dom","typescript"]]]) {
 const require=createRequire(resolve(workspace,"package.json"));
 for(const name of names) {
  try { require.resolve(name); }
  catch(error) { failures.push({workspace,dependency:name,error:String(error)}); }
 }
}
if(!failures.length) {
 try {
  const require=createRequire(resolve("frontend/package.json")); const ts=require("typescript");
  const config=ts.readConfigFile(resolve("frontend/tsconfig.json"),ts.sys.readFile);
  if(config.error) throw new Error(ts.flattenDiagnosticMessageText(config.error.messageText,"\n"));
  const parsed=ts.parseJsonConfigFileContent(config.config,ts.sys,resolve("frontend"));
  for(const name of ["vite/client","node"]) {
   if(!ts.resolveTypeReferenceDirective(name,resolve("frontend/__environment__.ts"),parsed.options,ts.sys).resolvedTypeReferenceDirective)
    throw new Error(`Cannot resolve TypeScript type library ${name}`);
  }
 } catch(error) { failures.push({dependency:"frontend TypeScript libraries",error:String(error)}); }
 try { const require=createRequire(resolve("backend/package.json")); const Database=require("better-sqlite3"); new Database(":memory:").close(); }
 catch(error) { failures.push({dependency:"better-sqlite3 native runtime",error:String(error)}); }
 for(const name of ["vite","@vitejs/plugin-react"]) {
  try { const require=createRequire(resolve("frontend/package.json")); await import(pathToFileURL(require.resolve(name)).href); }
  catch(error) { failures.push({dependency:name,error:String(error)}); }
 }
}
console.log(JSON.stringify({failures})); process.exitCode=failures.length?1:0;
'''


def probe(output):
    node = shutil.which('node')
    if not node:
        return {'returncode': 1, 'output': 'Node.js is unavailable'}
    try:
        path = output / '.arc/environment-probe.mjs'
        save_text(path, PROBE)
        return capture_process([node, str(path)], cwd=output, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'returncode': 1, 'output': str(error)}


def require_environment(output, recover=False):
    if not active():
        return
    workspace_contract(output)
    result = probe(output)
    if result['returncode'] and recover:
        from infrastructure.shared.project.dependencies import install_dependencies
        install_dependencies(output)
        return
    if result['returncode']:
        block(output, 'Workspace dependencies are not executable; stop model repair', evidence=result)
    save_json(output / '.arc/environment.json', {'status': 'GREEN', 'checks': result,
                                                'model_repair_allowed': False})
