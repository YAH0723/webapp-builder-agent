"""Independent B3 controls; context reduction removes exact duplicates only."""
from copy import deepcopy
import hashlib
import json
import os
import re


def enabled(feature):
    profile = os.getenv('ARC_AGENT_PROFILE', 'b4').lower()
    if profile not in {'b0', 'b3', 'b4'}:
        raise ValueError('ARC_AGENT_PROFILE must be b0, b3 or b4')
    value = os.getenv('ARC_B3_' + feature.upper())
    if value is None:
        return profile in {'b3', 'b4'}
    if value.lower() not in {'0', '1', 'false', 'true'}:
        raise ValueError('ARC_B3_' + feature.upper() + ' must be 0 or 1')
    return value.lower() in {'1', 'true'}


def positive_setting(name, default):
    value = int(os.getenv('ARC_B3_' + name, str(default)))
    if value < 1:
        raise ValueError('ARC_B3_' + name + ' must be positive')
    return value


CONTEXT_RULES = '''Use input.files content and retained read_files before requesting reads.
Read several relevant missing files in one tool_calls batch. Exact repeated excerpts
and query records have been removed, not summarized. retained_record_ids refer to
unchanged records already supplied in context_records. Respect file_access when present.
Return only necessary edits; preserve original requirements and earlier behavior.'''


def compact_context(payload):
    result = deepcopy(payload)
    for path, excerpts in list(result.get('read_files', {}).items()):
        source = result.get('files', {}).get(path, {}).get('content')
        if not isinstance(source, str):
            continue
        lines = source.splitlines(keepends=True)
        kept = [e for e in excerpts if not (
            e.get('total_lines') == len(lines) and type(e.get('start_line')) is int
            and type(e.get('end_line')) is int and 1 <= e['start_line'] <= e['end_line'] <= len(lines)
            and ''.join(lines[e['start_line'] - 1:e['end_line']]) == e.get('content'))]
        if kept:
            result['read_files'][path] = kept
        else:
            del result['read_files'][path]
    if 'read_files' in result and not result['read_files']:
        del result['read_files']
    query = result.get('context_result')
    if isinstance(query, dict) and isinstance(query.get('records'), dict):
        retained = result.get('context_records', {}).get(query.get('kind'), {})
        duplicate = [k for k, v in query['records'].items() if k in retained and retained[k] == v]
        if duplicate:
            query['retained_record_ids'] = duplicate
            query['records'] = {k: v for k, v in query['records'].items() if k not in duplicate}
    return result


def failure_fingerprint(value):
    """Discard timing noise, retaining assertions, paths and test identities."""
    volatile = {'elapsed_seconds', 'test_seconds', 'duration_ms', 'timestamp', 'stdout', 'stderr', 'previous_diagnosis'}
    def normalize(item):
        if isinstance(item, dict):
            return {k: normalize(v) for k, v in item.items() if k not in volatile
                    and not (k == 'output' and any(item.get(x) for x in ('failures', 'errors')))}
        if isinstance(item, list):
            return [normalize(v) for v in item]
        if isinstance(item, str):
            item = re.sub(r'\x1b\[[0-9;]*m', '', item)
            return re.sub(r'(?m)^.*(?:duration_ms:|elapsed_seconds:|built in \d).*$', '', item)
        return item
    return hashlib.sha256(json.dumps(normalize(value), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def record_event(output, event, **values):
    destination = output / '.arc/b3_metrics.jsonl'
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'event': event, **values}, ensure_ascii=False) + '\n')


def scoped_rules(files):
    candidates = sorted(files.readable if files.readable is not None else files.files)
    path = next((p for p in candidates if files.path(p).is_file()), None)
    example = json.dumps({'tool_calls': [{'tool': 'read_file', 'path': path}]}) if path else None
    return '''Use only the FLAT read_file/edit_file schemas in input.tools.
Return JSON tool_calls; batch related reads together and related edits together.
Input.files already contains source contents; use them without another read.
Paths are workspace-relative with forward slashes. Respect file_access; unavailable
sources are not permission to bypass it. Preserve code with unique local replacements;
whole-file replacements remain forbidden. Actual checks decide task completion.
Use task.file_target for a missing primary output, then create application helpers.
Tests and fixtures remain protected according to actual tool permissions.
Use diagnosis with actual evidence before repairing a failed check.
''' + ('Allowed read example: ' + example if example else 'Use supplied evidence; no readable file example exists.')
