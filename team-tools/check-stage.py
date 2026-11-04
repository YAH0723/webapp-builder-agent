"""Check one generated stage locally, without creating a model client or running compilation."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.stages.backend.context import load_context
from infrastructure.stages.backend.testing import BackendChecks, require_green as backend_green
from infrastructure.stages.frontend.ui.testing import FrontendChecks, test_path as ui_path, require_green
from infrastructure.stages.frontend.triggers.testing import E2EChecks, test_path as e2e_path
from infrastructure.stages.frontend.triggers.acceptance import acceptance_path
from infrastructure.stages.frontend.triggers.batching import require_suites
from infrastructure.stages.frontend.triggers.direct import plan_bindings
from infrastructure.stages.frontend.ui.batching import accept_design
from infrastructure.utils.files import read_artifact


def select_files(output, stage, ids):
    """Select expected files, not just existing files: omissions cannot silently pass."""
    arc = output / '.arc'
    if stage == '08':
        known = read_artifact(arc, 'backend_apis.json')['apis']
        kind = 'backend_test'
        path_for = lambda identity: selected_path(output, kind, identity)
    elif stage == '10':
        known = read_artifact(arc, 'ui_design.json')['pages']
        path_for = ui_path
    elif stage == '12':
        tree, _, _ = load_context(arc)
        known = tree.leaves
        report = read_artifact(arc, 'frontend_e2e.json') if (arc / 'frontend_e2e.json').is_file() else {}
        independent = 'b4' in report.get('mode', '') or (arc / 'independent_acceptance.json').is_file()
        path_for = acceptance_path if independent else lambda identity: e2e_path(identity, output)
    else:
        raise ValueError('File selection is available only for stages 08, 10, 12')
    chosen = list(dict.fromkeys(ids)) if ids else list(known)
    unknown = set(chosen) - set(known)
    if unknown:
        raise ValueError('Unknown selected IDs: ' + ', '.join(sorted(unknown)))
    if not chosen:
        raise ValueError('No targets for this stage; nothing was verified')
    paths = {identity: path_for(identity) for identity in chosen}
    missing = [identity for identity, path in paths.items() if not path or not (output / path).is_file()]
    if missing:
        raise ValueError('Missing indexed/expected suites: ' + ', '.join(missing))
    return paths


def check(output, stage, ids=(), selected_checks=('typecheck', 'tests', 'build'), list_only=False):
    output = output.resolve()
    report = {'kind': 'local_generated_stage_check', 'stage': stage, 'workspace': str(output),
              'scope': 'selected_targets' if ids else 'all_stage_targets', 'model_requests': 0,
              'official_evaluation': False, 'checks': {}, 'status': 'RUNNING'}
    start = time.monotonic()
    try:
        if stage in {'09', '11'}:
            if ids:
                raise ValueError('Design/binding validation checks the complete artifact; omit --id')
            tree, _, obligations = load_context(output / '.arc')
            ui = read_artifact(output / '.arc', 'ui_design.json')
            if stage == '09':
                proposal = {'pages': ui['pages'], 'elements': ui['elements'],
                    'requirement_ui': {rid: ui['requirements'][rid] for rid in tree.requirements},
                    'step_ui': {sid: ui['steps'][sid] for sid in tree.steps}}
                accept_design(deepcopy(ui), proposal, list(tree.requirements), tree)
                report['checks']['design'] = {'status': 'GREEN', 'pages': len(ui['pages'])}
            else:
                backend = read_artifact(output / '.arc', 'backend_apis.json')
                bindings = plan_bindings(tree, backend, ui, obligations)
                report['checks']['bindings'] = {'status': 'GREEN', 'requirements': len(bindings['bindings'])}
        else:
            paths = select_files(output, stage, ids)
            report['targets'] = paths
            if list_only:
                report['status'] = 'LISTED_NOT_TESTED'
                return report
            checks = {'08': BackendChecks, '10': FrontendChecks, '12': E2EChecks}[stage](output)
            for name in dict.fromkeys(selected_checks):
                began = time.monotonic()
                result = None
                try:
                    result = getattr(checks, name)(list(paths.values())) if name != 'build' else checks.build()
                    if result.get('returncode'):
                        raise ValueError(result.get('output', 'Command failed'))
                    if name == 'tests':
                        if stage == '08':
                            backend_green(result)
                        elif stage == '12':
                            require_suites(result, list(paths.values()), output)
                        else:
                            require_green(result)
                    entry = {'status': 'GREEN', 'result': result}
                except (ValueError, RuntimeError, OSError) as error:
                    entry = {'status': 'FAILED', 'error': str(error), 'result': result}
                entry['seconds'] = round(time.monotonic() - began, 3)
                report['checks'][name] = entry
        report['status'] = 'FAILED' if any(c['status'] == 'FAILED' for c in report['checks'].values()) else 'GREEN'
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        report.update(status='FAILED', error=str(error))
    finally:
        report['seconds'] = round(time.monotonic() - start, 3)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path, help='Generated application containing .arc and installed node_modules')
    parser.add_argument('--stage', required=True, choices=['08', '09', '10', '11', '12'])
    parser.add_argument('--id', action='append', default=[], help='Repeat API/page/requirement IDs for a focused check')
    parser.add_argument('--checks', nargs='+', choices=['typecheck', 'tests', 'build'], default=['typecheck', 'tests', 'build'])
    parser.add_argument('--list', action='store_true', help='List selected suites without running Node')
    parser.add_argument('--report', type=Path, help='Write full machine-readable evidence outside the team repository')
    args = parser.parse_args()
    result = check(args.workspace, args.stage, args.id, args.checks, args.list)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'checks'}, ensure_ascii=False, indent=2))
    for name, entry in result['checks'].items():
        print(f"{name}: {entry['status']} ({entry.get('seconds', 0):.2f}s)")
        if entry['status'] == 'FAILED':
            print(entry.get('error', '')[:4000])
    raise SystemExit(1 if result['status'] == 'FAILED' else 0)


if __name__ == '__main__':
    main()
