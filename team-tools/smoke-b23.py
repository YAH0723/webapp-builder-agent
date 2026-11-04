"""Real browser/HTTP/SQLite checks for B2.3 helpers and failure evidence; no LLM."""
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infrastructure.shared.project.initialize import initialize_project
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.shared.project.features import prepare_features
from infrastructure.shared.agent.diagnostics import repair_evidence
from infrastructure.shared.agent.feedback import compact_feedback
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.tools import FileTools
from unittest.mock import Mock
from infrastructure.stages.frontend.ui.runtime import prepare_frontend
from infrastructure.stages.frontend.triggers.e2e_runtime import prepare_e2e
from infrastructure.stages.frontend.triggers.testing import E2EChecks
from infrastructure.utils.files import save_json, save_text


APP = '''import {useEffect, useState} from "react";
import {callApi} from "./arc-lib/api-client.js";
import {HttpError} from "./arc-lib/http.js";
import {useSubmit} from "./arc-lib/useSubmit.js";
import {AsyncBoundary} from "./arc-lib/AsyncBoundary.js";
type Row = {id: number; value: string};
export function App() {
  const [value, setValue] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const submit = useSubmit<Row[]>();
  useEffect(() => {void callApi<Row[]>("LIST").then(setRows);}, []);
  return <main><h1>Record demo</h1><form onSubmit={event => {
    event.preventDefault();
    void submit.run(async () => {
      await callApi("SAVE", {body: {value}, query: {token: "diagnostic-sentinel"}});
      return callApi<Row[]>("LIST");
    }).then(data => {setRows(data); setValue("");}).catch(() => {});
  }}><label>Value<input value={value} onChange={event => setValue(event.target.value)}/></label>
  <button disabled={submit.pending}>Save</button></form>
  <AsyncBoundary state={submit.state} pending={<p role="status">Saving</p>}
    error={error => <p role="alert">{error instanceof HttpError && typeof error.data === "object" && error.data !== null
      ? String((error.data as {error?: string}).error ?? "Request failed") : error.message}</p>}>
    {() => null}
  </AsyncBoundary>
  <ul>{rows.map(row => <li key={row.id}>{row.value}</li>)}</ul></main>;
}
'''
REGISTER = '''import type {Express} from "express";
import type Database from "better-sqlite3";
export function registerApis(app: Express, connection: Database.Database) {
  connection.exec("CREATE TABLE IF NOT EXISTS DemoRecord (id INTEGER PRIMARY KEY AUTOINCREMENT, value TEXT NOT NULL)");
  app.post("/api/records", async (request, response) => {
    await new Promise(resolve => setTimeout(resolve, 100));
    if (typeof request.body?.value !== "string" || !request.body.value.trim()) {
      response.status(400).json({error: "Value required"}); return;
    }
    const result = connection.prepare("INSERT INTO DemoRecord (__COLUMN__) VALUES (?)").run(request.body.value);
    response.status(201).json({id: Number(result.lastInsertRowid)});
  });
  app.get("/api/records", (_request, response) => response.json(connection.prepare("SELECT id, value FROM DemoRecord ORDER BY id").all()));
  app.delete("/api/records", (_request, response) => {connection.prepare("DELETE FROM DemoRecord").run(); response.status(204).end();});
  app.get("/api/echo/:id", (request, response) => response.json({id: request.params.id, tags: request.query.tags, active: request.query.active}));
  app.get("/api/reject", (_request, response) => response.status(400).json({error: "Expected rejection"}));
}
'''
SPEC = '''import {test, expect} from "./support/context.js";
test("duplicate submit makes one persistent record", async ({page}) => {
  await page.goto("/"); await page.getByLabel("Value", {exact: true}).fill("Alpha");
  const saved = page.waitForResponse(response => response.url().includes("/api/records") && response.request().method() === "POST");
  await page.evaluate(() => {const form = document.querySelector("form")!; form.requestSubmit(); form.requestSubmit();});
  const savedResponse = await saved;
  // Successful polling must not evict the preceding failure observation.
  await page.evaluate(() => Promise.all(Array.from({length: 45}, () => fetch("/api/records"))));
  expect(savedResponse.status()).toBe(201);
  await expect(page.getByRole("listitem")).toHaveCount(1);
  await page.reload(); await expect(page.getByRole("listitem")).toHaveText(["Alpha"]);
});
test("expected rejection resets submission and allows retry", async ({page}) => {
  await page.goto("/"); await page.getByRole("button", {name: "Save", exact: true}).click();
  await expect(page.getByRole("alert")).toHaveText("Value required");
  await expect(page.getByRole("button", {name: "Save", exact: true})).toBeEnabled();
  await page.getByLabel("Value", {exact: true}).fill("Beta");
  await page.getByRole("button", {name: "Save", exact: true}).click();
  await expect(page.getByRole("listitem")).toHaveText(["Beta"]);
});
test("route parameters and repeated queries are encoded", async ({page}) => {
  await page.goto("/");
  const result = await page.evaluate(async () => {
    const path = "/src/arc-lib/api-client.ts"; const {callApi} = await import(path);
    return callApi("ECHO", {params: {id: "a/b"}, query: {tags: ["x y", "z&k"], active: false}});
  });
  expect(result).toEqual({id: "a/b", tags: ["x y", "z&k"], active: "false"});
});
test("empty success and structured HTTP rejection retain meaning", async ({page}) => {
  await page.goto("/");
  const result = await page.evaluate(async () => {
    const path = "/src/arc-lib/api-client.ts"; const {callApi} = await import(path);
    const empty = await callApi("CLEAR");
    try {await callApi("REJECT"); return {unexpected: true};}
    catch(error) {const e = error as {status: number; data: unknown}; return {empty: empty === undefined, status: e.status, data: e.data};}
  });
  expect(result).toEqual({empty: true, status: 400, data: {error: "Expected rejection"}});
});
test("invalid route arguments and GET bodies do not become business requests", async ({page}) => {
  await page.goto("/");
  const result = await page.evaluate(async () => {
    const path = "/src/arc-lib/api-client.ts"; const {callApi} = await import(path);
    const errors = [];
    try {await callApi("ECHO");} catch(error) {errors.push(String(error));}
    try {await callApi("LIST", {body: {invalid: true}});} catch(error) {errors.push(String(error));}
    return errors;
  });
  expect(result[0]).toContain("Missing route parameter"); expect(result[1]).toContain("GET requests cannot");
});
'''


def run(output):
    output = output.resolve()
    if not output.is_relative_to(ROOT / 'releases'):
        raise ValueError('Smoke output must be a dedicated directory under releases/')
    started = perf_counter()
    initialize_project(output)
    contracts = {'apis': {aid: {'signature': {'method': method, 'path': path}}
        for aid, method, path in [('SAVE', 'POST', '/api/records'), ('LIST', 'GET', '/api/records'),
            ('CLEAR', 'DELETE', '/api/records'), ('ECHO', 'GET', '/api/echo/:id'), ('REJECT', 'GET', '/api/reject')]}}
    save_json(output / '.arc/backend_apis.json', contracts)
    save_json(output / '.arc/implementation_paths.json', {'api': {'SAVE': 'backend/src/api/register.ts'}})
    prepare_frontend(output)
    prepare_e2e(output, contracts)
    install_dependencies(output)
    save_text(output / 'frontend/src/App.tsx', APP)
    save_text(output / 'backend/src/api/register.ts', REGISTER.replace('__COLUMN__', 'missing_column'))
    path = 'frontend/tests/e2e/b23.spec.ts'
    save_text(output / path, SPEC)
    checks = E2EChecks(output)
    checks.install_browser()
    compiled = checks.typecheck([path])
    assert compiled['returncode'] == 0, compiled
    broken = checks.tests([path])
    assert broken['returncode'] != 0 and broken.get('diagnostics'), broken
    observed = [event for case in broken['diagnostics'] for event in case['events']]
    assert any(event.get('kind') == 'http' and event.get('status') == 500 for event in observed), observed
    assert 'diagnostic-sentinel' not in json.dumps(broken['diagnostics']), broken['diagnostics']
    evidence = repair_evidence(output, {'original_requirement': {'id': 'SAVE-RECORD'}}, broken)
    assert 'SAVE' in evidence['related_api_ids'], evidence
    assert 'backend/src/api/register.ts' in evidence['suggested_source_paths'], evidence
    save_json(output / '.arc/observed-broken-evidence.json', evidence)
    # A scripted model consumes the real evidence and repairs source through the
    # same tools/gate as an implementation agent. No acceptance is edited.
    decisions = []
    def generate(instructions, payload):
        decisions.append(payload['task']['repair_evidence'])
        assert 'SAVE' in payload['task']['repair_evidence']['related_api_ids']
        assert 'backend/src/api/register.ts' in payload['files']
        assert 'runtime_helpers' in payload['task']
        return {'tool_calls': [{'tool': 'edit_file', 'path': 'backend/src/api/register.ts',
            'operation': 'replace', 'old_content': 'INSERT INTO DemoRecord (missing_column) VALUES (?)',
            'new_content': 'INSERT INTO DemoRecord (value) VALUES (?)'}]}
    def gate():
        checked = checks.typecheck([path])
        assert checked['returncode'] == 0, checked
        result = checks.tests([path], fail_fast=False)
        assert result['returncode'] == 0 and result['passed'] == 5, result
        return result
    repaired = run_file_agent(Mock(generate_json=generate), 'Repair the application; tests are read-only.',
        {'original_requirement': {'id': 'SAVE-RECORD'}}, FileTools(output, ['frontend/src/App.tsx']),
        gate, 2, Mock(), 'B23 evidence-driven smoke', feedback=broken, feedback_filter=compact_feedback)
    fixed = repaired['checks']
    assert fixed['returncode'] == 0 and fixed['passed'] == 5 and not fixed.get('failed'), fixed
    built = checks.build()
    assert built['returncode'] == 0, built
    summary = {'kind': 'real browser/HTTP/SQLite fixture; not agent generation or official benchmark',
        'real_model_requests': 0, 'scripted_model_calls': len(decisions),
        'deliberate_http_500_captured': True, 'http_500_survives_success_noise': True,
        'linked_api_and_source': True,
        'credentials_query_removed': True, 'browser_tests_passed': fixed['passed'],
        'checks': ['duplicate submit', 'persistent reload', 'HTTP rejection and retry',
            'parameter/query encoding', 'empty response', 'invalid request arguments'],
        'build': 'GREEN', 'wall_seconds_including_setup': round(perf_counter() - started, 3)}
    save_json(output / '.arc/b23-smoke-summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'releases/b23-smoke')
    run(parser.parse_args().output)
