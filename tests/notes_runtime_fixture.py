"""Small general app for real local stage replay; no benchmark task artifacts."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import yaml
from test_frontend_flow import frontend_fixture
from infrastructure.utils.files import save_json, save_text
from infrastructure.shared.project.entrypoints import remember_path
from infrastructure.stages.frontend.triggers.design import empty_triggers


def create_notes_app(output):
    templates = Path(__file__).resolve().parents[1] / 'infrastructure/shared/project/templates'
    shutil.copytree(templates, output, dirs_exist_ok=True)
    for name in ('seeds', 'tables'): (output / 'backend/src/db' / name).mkdir(parents=True, exist_ok=True)
    raw, tree, ui, _, backend, _ = frontend_fixture()
    for node in ui['elements'].values(): node['data'] = []
    for page in ui['pages'].values(): page.pop('fixtures', None)
    ui.pop('bindings', None)
    schema = {'entities': {'Note': {'fields': {'id': {'type':'integer','references':None},
                                             'text': {'type':'string','references':None}}}}}
    for aid, api in backend['apis'].items():
        api.update(signature={'name':aid,'method':'POST' if aid=='API-SAVE' else 'GET',
                              'path':'/api/notes' if aid=='API-SAVE' else '/api/count'},
                   request={'body':{'type':'object'}},
                   response={'success':{'status':200,'body':{'type':'object'}},'errors':[]})
    save_text(output / 'requirements/requirements.yaml', yaml.safe_dump(raw, allow_unicode=True))
    for name, value in [('requirements.json',raw),('db_schema.json',schema),('backend_apis.json',backend),
                        ('ui_design.json',ui),('frontend_triggers.json',empty_triggers(tree))]:
        save_json(output / '.arc' / name, value)
    save_text(output/'backend/src/db/tables/Note.sql','CREATE TABLE IF NOT EXISTS Note (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL);\n')
    path=output/'backend/src/db/initialize.ts'
    save_text(path,path.read_text(encoding='utf8').replace('export const tableFiles: readonly string[] = [];',
                                                        'export const tableFiles: readonly string[] = ["Note.sql"];'))
    save_text(output/'backend/src/api/register.ts', '''import type {Express} from "express";
import type Database from "better-sqlite3";
export function registerApis(app:Express,db:Database.Database) {
 app.post("/api/notes",(q,r)=>{if(typeof q.body.text!=="string"||!q.body.text.trim()){r.status(400).json({error:"Text required"});return;}
 db.prepare("INSERT INTO Note(text) VALUES (?)").run(q.body.text);r.json({saved:true});});
 app.get("/api/count",(_q,r)=>{r.json(db.prepare("SELECT count(*) count FROM Note").get());});
}
''')
    save_text(output/'frontend/src/App.tsx', '''import React,{useEffect,useState} from "react";
export function App(){const [text,setText]=useState("");const [error,setError]=useState("");const [count,setCount]=useState<number|null>(null);
const summary=location.pathname==="/summary";
useEffect(()=>{if(summary)fetch("/api/count").then(r=>r.json()).then(d=>setCount(d.count));},[summary]);
async function save(e:React.FormEvent){e.preventDefault();const r=await fetch("/api/notes",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({text})});
const d=await r.json();if(!r.ok){setError(d.error);return;}location.href="/summary";}
return summary?<main data-testid="UI-SUMMARY"><p data-testid="UI-COUNT">{count??"Loading"}</p><a data-testid="UI-BACK" href="/">Back</a></main>:
<main data-testid="UI-EDITOR"><form data-testid="UI-FORM" onSubmit={save}><label htmlFor="note">Note</label><input id="note" data-testid="UI-TEXT" value={text} onChange={e=>setText(e.target.value)}/><button data-testid="UI-SAVE">Save</button></form>{error&&<div role="alert" data-testid="UI-ERROR">{error}</div>}</main>;}
''')
    for pid in ui['pages']: remember_path(output,'page',pid,'frontend/src/App.tsx')
    for aid in backend['apis']: remember_path(output,'api',aid,'backend/src/api/register.ts')
    return tree,schema,backend,ui,empty_triggers(tree)


def isolated_source(rid):
    prefix='import {test,expect} from "../support/context";\n'
    annotation="{annotation:[{type:'arc-step',description:'STEP-"+rid+"'}]}"
    if rid in ('REQ-A','REQ-B'):
        return prefix+"test('save and persist "+rid+"',"+annotation+''',async({page,database})=>{
database.prepare("INSERT INTO Note(text) VALUES ('existing')").run();
await page.goto('/');
'''+('''await page.getByRole('button',{name:'Save',exact:true}).click();await expect(page.getByRole('alert')).toHaveText('Text required');
expect((database.prepare('SELECT count(*) n FROM Note').get() as {n:number}).n).toBe(1);
''' if rid=='REQ-A' else '')+'''await page.getByLabel('Note',{exact:true}).fill('new note');await page.getByRole('button',{name:'Save',exact:true}).click();
await expect(page.getByTestId('UI-COUNT')).toHaveText('2');await page.reload();await expect(page.getByTestId('UI-COUNT')).toHaveText('2');});
'''
    return prefix+"test('read unchanged count and return',"+annotation+''',async({page,database})=>{
database.prepare("INSERT INTO Note(text) VALUES ('first'),('second')").run();await page.goto('/summary');
await expect(page.getByTestId('UI-COUNT')).toHaveText('2');await page.reload();await expect(page.getByTestId('UI-COUNT')).toHaveText('2');
expect((database.prepare('SELECT count(*) n FROM Note').get() as {n:number}).n).toBe(2);await page.getByRole('link',{name:'Back',exact:true}).click();await expect(page.getByLabel('Note')).toBeVisible();});
'''


JOURNEY_SOURCE = '''import {test,expect} from "../support/context";
test('create prerequisite then two notes, read and refresh the persisted summary',
{annotation:['REQ-A','REQ-B','REQ-C'].map(id=>({type:'arc-step',description:'STEP-'+id}))},async({page})=>{
for(const [index,text] of ['existing prerequisite','first actual note','second actual note'].entries()) {
 await page.goto('/');await page.getByLabel('Note',{exact:true}).fill(text);await page.getByRole('button',{name:'Save',exact:true}).click();
 await expect(page.getByTestId('UI-COUNT')).toHaveText(String(index+1));
}
await page.reload();await expect(page.getByTestId('UI-COUNT')).toHaveText('3');await page.getByRole('link',{name:'Back',exact:true}).click();await expect(page.getByLabel('Note')).toBeVisible();});
'''
