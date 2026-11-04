"""Exercise B2 with real React/Express/SQLite/Chromium and a scripted, offline model.

This verifies orchestration and repair, not language-model generation quality or
an ARC-Bench score. It makes no paid model requests.
"""
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from infrastructure.shared.project.initialize import initialize_project
from infrastructure.stages.frontend.triggers.unified import run_acceptance_first
from infrastructure.stages.frontend.triggers.direct import plan_bindings
from infrastructure.stages.frontend.triggers.acceptance import acceptance_path
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.utils.files import save_json, save_text
from infrastructure.utils.presentation.logging import console_log


APP = '''import { useState } from "react";
export function App() {
  const [status, setStatus] = useState("Waiting");
  return <main><h1>Sample app</h1><button onClick={() => {}}>Check server</button><p>{status}</p></main>;
}
'''
FIX = '''async () => {
  const response = await fetch("/api/health");
  const data = await response.json();
  setStatus(response.ok && data.status === "ok" ? "Server ready" : "Server error");
}'''


class ScriptedModel:
    def __init__(self):
        self.calls = 0

    def generate_json(self, instructions, payload):
        self.calls += 1
        task = payload['task']
        if 'test_path' in task and 'file_target' in task:
            path = task['test_path']
            if payload['files'].get(path, {}).get('content') is not None:
                return {'diagnosis': {'cause': 'implementation', 'reason': 'The original test is valid.'},
                    'tool_calls': []}
            rid = task['original_requirement']['id']
            body = "await expect(page.getByRole('heading', {name: 'Sample app'})).toBeVisible();"
            if rid == 'REQ-HEALTH':
                body = """const response = page.waitForResponse(r => r.url().endsWith('/api/health'), {timeout: 3000});
await page.getByRole('button', {name: 'Check server'}).click();
expect((await response).ok()).toBeTruthy();
await expect(page.getByText('Server ready', {exact: true})).toBeVisible();"""
            code = ("import {test, expect} from '../support/context.js';\n"
                "test('original requirement', async ({page}) => {await page.goto('/');\n" + body + "\n});\n")
            return {'tool_calls': [{'tool': 'edit_file', 'path': path, 'operation': 'create', 'new_content': code}]}
        return {'diagnosis': {'cause': 'implementation', 'reason': 'The button has no HTTP handler.'},
            'tool_calls': [{'tool': 'edit_file', 'path': 'frontend/src/App.tsx', 'operation': 'replace',
                'old_content': '() => {}', 'new_content': FIX}]}


def run(output, reuse_tests=False):
    output = output.resolve()
    if not output.is_relative_to(ROOT / 'releases'):
        raise ValueError('Use a dedicated output directory inside releases/')
    initialize_project(output)
    save_text(output / 'frontend/src/App.tsx', APP)
    raw = {'id': 'ROOT', 'children': [
        {'id': 'REQ-TITLE', 'name': 'Home title', 'description': 'The home page shows a Sample app heading.'},
        {'id': 'REQ-HEALTH', 'name': 'Check server', 'description':
            'Click Check server to GET /api/health and show Server ready when status is ok.'}]}
    source = output / '.arc/smoke-input'
    save_text(source / 'requirements.yaml', json.dumps(raw))
    tree = RequirementTree(raw)
    if not reuse_tests:
        for rid in tree.leaves:
            suite = output / acceptance_path(rid)
            suite.unlink(missing_ok=True)
    ui = {'pages': {'PAGE-HOME': {'route': '/', 'root': 'UI-ROOT'}},
        'elements': {'UI-ROOT': {'parent': None}, 'UI-TITLE': {'parent': 'UI-ROOT'},
            'UI-BUTTON': {'parent': 'UI-ROOT'}, 'UI-STATUS': {'parent': 'UI-ROOT'}},
        'requirements': {'REQ-TITLE': ['UI-TITLE'], 'REQ-HEALTH': ['UI-BUTTON', 'UI-STATUS']}}
    backend, schema = {'apis': {}, 'requirements': {}}, {'entities': {}}
    design = plan_bindings(tree, backend, ui, {'requirements': {rid: {'read': [], 'write': []}
        for rid in tree.requirements}, 'steps': {}})
    for name, data in {'requirements.json': raw, 'ui_design.json': ui,
            'frontend_triggers.json': design, 'backend_apis.json': backend, 'db_schema.json': schema}.items():
        save_json(output / '.arc' / name, data)
    model = ScriptedModel()
    started = perf_counter()
    with console_log(output, model_log=False, stage='B2 real-app smoke'):
        result = run_acceptance_first(source, output / '.arc', tree, schema, backend, ui, design,
            model, Mock(), max_turns=4)
    assert result['status'] == 'GREEN', result
    assert result['summary']['e2e_tests'] == 2, result
    assert model.calls <= 6, model.calls
    summary = {'kind': 'real-app workflow smoke with scripted model; not a benchmark score',
        'status': result['status'], 'browser_tests_passed': 2,
        'model_tool_decisions': model.calls, 'real_model_requests': 0,
        'reused_existing_tests': reuse_tests,
        'wall_seconds_including_dependency_setup': round(perf_counter() - started, 3),
        'verification': {name: value['status'] for name, value in result['verification'].items()}}
    save_json(output / '.arc/b2-smoke-summary.json', summary)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'releases/b2-smoke')
    parser.add_argument('--reuse-tests', action='store_true')
    args = parser.parse_args()
    run(args.output, args.reuse_tests)
