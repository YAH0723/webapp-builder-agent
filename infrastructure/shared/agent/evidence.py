"""Deterministic localization hints from failed checks, never invented tool evidence."""
import re


def repair_evidence(value, backend):
    texts = []
    def visit(item):
        if isinstance(item, dict):
            if item.get('returncode') == 0:
                return
            for key, child in item.items():
                if key not in {'stdout', 'files'}:
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, str):
            texts.append(item)
    visit(value)
    text = '\n'.join(texts).replace('\\\\', '/').replace('\\', '/')
    sources = sorted(set(re.findall(r'(?:frontend|backend)/src/[A-Za-z0-9_./-]+\.(?:tsx?|jsx?|sql)', text)))
    paths = set(re.findall(r'/api/[A-Za-z0-9_./%{}:-]+', text))
    ids = []
    for aid, api in backend.get('apis', {}).items():
        path = api.get('signature', {}).get('path', '')
        if not path:
            continue
        pattern = re.sub(r'\\\{[^}]+\\\}|:[A-Za-z_][A-Za-z0-9_]*', '[^/]+', re.escape(path))
        if any(re.fullmatch(pattern, found) for found in paths):
            ids.append(aid)
    categories = []
    for name, pattern in [('typecheck', r'error TS\d+'), ('runtime', r'(?:TypeError|ReferenceError|pageerror|RUNTIME_ERROR)'),
                          ('http', r'(?:HTTP|status|/api/)'), ('assertion', r'(?:expect\(|assert|locator\.)')]:
        if re.search(pattern, text, re.I):
            categories.append(name)
    return {'categories': categories, 'referenced_sources': sources, 'related_api_ids': sorted(ids),
            'note': 'Localization hints from failed checks, not proof of the root cause.'}
