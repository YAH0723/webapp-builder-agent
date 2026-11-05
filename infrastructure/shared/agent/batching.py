"""B4 bounded work units: complete records, stable paths, explicit coverage."""
import hashlib
import json
import os

from infrastructure.shared.agent.efficiency import record_event
from infrastructure.shared.project.entrypoints import selected_path, remember_path


def enabled(feature):
    profile = os.getenv('ARC_AGENT_PROFILE', 'b4').lower()
    if profile not in {'b0', 'b3', 'b4'}:
        raise ValueError('ARC_AGENT_PROFILE must be b0, b3 or b4')
    value = os.getenv('ARC_B4_' + feature.upper())
    if value is None:
        return profile == 'b4'
    if value.lower() not in {'0', '1', 'false', 'true'}:
        raise ValueError('ARC_B4_' + feature.upper() + ' must be 0 or 1')
    return value.lower() in {'1', 'true'}


def setting(name, default):
    value = int(os.getenv('ARC_B4_' + name, str(default)))
    if value < 1:
        raise ValueError('ARC_B4_' + name + ' must be positive')
    return value


def chunks(records, maximum, max_chars=80000):
    """Keep source order and every complete record; an oversized item stays alone."""
    result, group, size = [], [], 0
    for record in records:
        count = len(json.dumps(record, ensure_ascii=False))
        if group and (len(group) >= maximum or size + count > max_chars):
            result.append(group)
            group, size = [], 0
        group.append(record)
        size += count
    if group:
        result.append(group)
    return result


def target_path(output, kind, identity):
    roots = {'api': ('backend/src/api', '.ts'), 'backend_test': ('backend/tests/api', '.test.ts'),
             'page': ('frontend/src/pages', '.tsx')}
    root, suffix = roots[kind]
    return selected_path(output, kind, identity) or root + '/generated-' + hashlib.sha256(
        identity.encode()).hexdigest()[:16] + suffix


def bind_files(output, kind, targets):
    missing = [path for path in targets.values() if not (output / path).is_file()
               or not (output / path).read_text(encoding='utf-8-sig').strip()]
    if missing:
        raise ValueError('Required batch files missing or empty: ' + ', '.join(missing))
    for identity, path in targets.items():
        remember_path(output, kind, identity, path)


def protect(workspace, allow):
    workspace.writable = {p for p in workspace.writable if allow(p)}
    workspace.allow_write = allow


def feedback_for(workspace, selections, allow):
    def feedback(value):
        for selection in selections:
            value = selection.feedback(workspace, value)
        protect(workspace, allow)
        return value
    return feedback


def log_plan(output, stage, groups, individual_units):
    record_event(output, 'b4_batch_plan', stage=stage, individual_units=individual_units,
                 groups=len(groups), unit_counts=[len(group) for group in groups])


def split_failed(queue, position, group, depth, entry, output, stage):
    """One bounded bisection contains batch coupling without returning to per-item loops."""
    if entry.get('status') != 'FAILED' or depth or len(group) < 2 or not enabled('adaptive_split'):
        return
    if isinstance(entry.get('feedback'), dict) and entry['feedback'].get('retryable') is False:
        entry['recovery'] = 'stopped_nonretryable_tool_failure'
        return
    middle = (len(group) + 1) // 2
    queue[position:position] = [(group[:middle], 1), (group[middle:], 1)]
    entry['recovery'] = 'split_once_after_baseline_restore'
    record_event(output, 'b4_split_failed', stage=stage, members=[r['id'] for r in group],
                 child_sizes=[middle, len(group) - middle])
