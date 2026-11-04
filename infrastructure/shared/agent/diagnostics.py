"""Bounded observations from failed checks, never a new acceptance oracle."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from infrastructure.shared.project.entrypoints import selected_path


def clean_text(value, limit=600):
    value = re.sub(r'\x1b\[[0-9;]*m', '', str(value))
    value = re.sub(r'https?://[^\s\)"<>]+', lambda match: safe_url(match[0]), value)
    value = re.sub(r'(?i)\bBearer\s+[^\s,;]+', 'Bearer [redacted]', value)
    value = re.sub(r'(?i)\b(api[_-]?key|password|token|secret)\s*[=:]\s*[^\s,;]+', r'\1=[redacted]', value)
    return value[:limit]


def safe_url(value):
    """Keep route evidence without URL credentials, query parameters or fragments."""
    try:
        return urlsplit(str(value)).path[:300]
    except ValueError:
        return '[invalid URL]'


def diagnostic_attachment(attachments, output=None):
    """Decode only the compiler attachment, with strict size/path boundaries."""
    for attachment in attachments:
        if attachment.get('name') != 'arc-diagnostics' or attachment.get('contentType') != 'application/json':
            continue
        try:
            if isinstance(attachment.get('body'), str):
                if len(attachment['body']) > 90000:
                    continue
                content = base64.b64decode(attachment['body'], validate=True)
            elif output is not None and isinstance(attachment.get('path'), str):
                root = Path(output).resolve()
                path = Path(attachment['path'])
                path = (root / path).resolve() if not path.is_absolute() else path.resolve()
                if not path.is_relative_to(root / 'frontend/test-results') or path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
                    continue
                content = path.read_bytes()
            else:
                continue
            if len(content) > 65536:
                continue
            data = json.loads(content)
            events = []
            for event in data.get('events', [])[-40:]:
                if not isinstance(event, dict) or event.get('kind') not in {'http', 'network', 'runtime', 'console'}:
                    continue
                item = {'kind': event['kind']}
                if event.get('path'):
                    item['path'] = safe_url(event['path'])
                if event.get('method'):
                    item['method'] = clean_text(event['method'], 12)
                if type(event.get('status')) is int:
                    item['status'] = event['status']
                if event.get('message'):
                    item['message'] = clean_text(event['message'])
                events.append(item)
            return events
        except (ValueError, TypeError, AttributeError, OSError):
            continue
    return []


def _matches_route(route, path):
    # Exact literals and Express-style named segments; no semantic route guesses.
    segments = route.split('/')
    pattern = '/'.join('[^/]+' if part.startswith(':') else re.escape(part) for part in segments)
    return re.fullmatch(pattern, path) is not None


def repair_evidence(output, task, feedback):
    """Tie observed failures to current contracts and existing source paths."""
    output = Path(output)
    observations, messages = [], []
    requirement_ids = set()
    for key in ('original_requirement', 'requirement'):
        value = task.get(key)
        if isinstance(value, dict) and isinstance(value.get('id'), str):
            requirement_ids.add(value['id'])
    failed_files = set()

    def visit(value):
        if isinstance(value, dict):
            if value.get('returncode') == 0 or value.get('status') == 'GREEN':
                return
            if isinstance(value.get('diagnostics'), list):
                for case in value['diagnostics']:
                    if isinstance(case, dict):
                        if isinstance(case.get('test_file'), str):
                            failed_files.add(clean_text(case['test_file'], 300))
                        for event in case.get('events', []):
                            if isinstance(event, dict):
                                observations.append(deepcopy(event))
            for key, child in value.items():
                if key == 'diagnostics':
                    continue
                if key in {'failures', 'errors', 'error', 'output'}:
                    messages.append(child if isinstance(child, str) else json.dumps(child, ensure_ascii=False))
                elif isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str):
            messages.append(value)
    visit(feedback)
    apis, allocations = {}, {}
    try:
        backend = json.loads((output / '.arc/backend_apis.json').read_text(encoding='utf-8-sig'))
        apis, allocations = backend.get('apis', {}), backend.get('requirements', {})
    except (OSError, ValueError, AttributeError):
        pass
    related_apis = set()
    for event in observations:
        if 'path' not in event or 'method' not in event:
            continue
        for aid, api in apis.items():
            signature = api.get('signature', {})
            if signature.get('method', '').upper() == event['method'].upper() and _matches_route(signature.get('path', ''), event['path']):
                related_apis.add(aid)
    requirement_ids.update(rid for rid, aids in allocations.items() if related_apis.intersection(aids))
    sources = set()
    for aid in related_apis:
        relative = selected_path(output, 'api', aid)
        if relative and (output / relative).is_file():
            sources.add(relative)
    text = '\n'.join(messages).replace('\\', '/')
    for match in re.finditer(r'(?:backend|frontend)/src/[\w./@-]+\.(?:tsx?|jsx?)', text):
        relative = match[0]
        if '..' not in Path(relative).parts and (output / relative).is_file():
            sources.add(relative)
    # Keep actual failure text once as a short navigation hint; full reports survive.
    for message in messages:
        for line in message.splitlines():
            if any(marker in line for marker in ('error TS', 'Error:', 'AssertionError', 'E2E_', 'BACKEND_')):
                observations.append({'kind': 'check', 'message': clean_text(line)})
                break
    unique = []
    seen = set()
    for event in observations:
        key = json.dumps(event, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            unique.append(event)
    if not unique and not sources:
        return None
    def priority(event):
        if event.get('kind') in {'network', 'runtime'}:
            return 0
        if event.get('kind') == 'http' and event.get('status', 0) >= 500:
            return 1
        return {'console': 2, 'check': 3}.get(event.get('kind'), 4 if event.get('status', 0) >= 400 else 5)
    chosen = sorted(unique, key=priority)[:12]
    return {'version': 1, 'requirement_ids': sorted(requirement_ids),
        'related_api_ids': sorted(related_apis), 'suggested_source_paths': sorted(sources)[:12],
        'failed_test_files': sorted(failed_files)[:8], 'observations': chosen,
        'omitted_observations': len(unique) - len(chosen),
        'notice': 'Observed evidence, not a proven root cause. HTTP rejection may be expected. Preserve original requirements and read-only tests.'}


def feedback_without_diagnostic_duplicates(value):
    """The evidence task field carries browser observations; keep assertions once."""
    if isinstance(value, dict):
        return {key: feedback_without_diagnostic_duplicates(child) for key, child in value.items() if key != 'diagnostics'}
    if isinstance(value, list):
        return [feedback_without_diagnostic_duplicates(child) for child in value]
    return value
