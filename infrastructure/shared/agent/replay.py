"""Strict scripted model responses for local stage replay. No API client or credentials."""
from copy import deepcopy
import hashlib
import json


def workload_digest(output, requirements=None):
    """Hash explicit inputs only; never scan secrets, model logs or installed dependencies."""
    digest = hashlib.sha256()
    paths = set()
    for root in ('backend/src', 'backend/tests', 'frontend/src', 'frontend/tests'):
        paths.update(path for path in (output / root).rglob('*') if path.is_file()
                     and not path.is_symlink() and not path.name.startswith('.env'))
    for root in ('', 'backend', 'frontend'):
        for name in ('package.json', 'package-lock.json', 'tsconfig.json', 'tsconfig.test.json'):
            path = output / root / name
            if path.is_file():
                paths.add(path)
    for name in ('requirements.json', 'db_schema.json', 'db_obligations.json', 'backend_apis.json',
                 'ui_design.json', 'frontend_triggers.json', 'shared_conventions.json', 'implementation_paths.json'):
        path = output / '.arc' / name
        if path.is_file():
            paths.add(path)
    for path in sorted(paths):
        digest.update(path.relative_to(output).as_posix().encode())
        digest.update(b'\0' + path.read_bytes() + b'\0')
    if requirements is not None:
        for path in sorted(requirements.rglob('*')):
            if path.is_file() and not path.is_symlink() and not path.name.startswith('.env'):
                digest.update(b'input/' + path.relative_to(requirements).as_posix().encode())
                digest.update(b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def contains(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and contains(actual[key], value)
                                                for key, value in expected.items())
    return actual == expected


class ReplayTape:
    def __init__(self, records):
        if not isinstance(records, list):
            raise ValueError('Replay responses must be an array')
        self.records = deepcopy(records)
        self.calls = []

    def generate_json(self, instructions, request):
        number = len(self.calls)
        if number >= len(self.records):
            raise ValueError('Offline replay exhausted; real inference is disabled')
        record = self.records[number]
        task = request.get('task', request)
        expected = record.get('expect', {})
        if not contains(task, expected.get('task_contains', {})):
            raise ValueError('Replay task mismatch at response ' + str(number + 1))
        if any(key not in task for key in expected.get('task_keys', [])):
            raise ValueError('Replay task is missing an expected key')
        if any(text not in instructions for text in expected.get('instructions_contain', [])):
            raise ValueError('Replay instruction mismatch at response ' + str(number + 1))
        payload = json.dumps(request, ensure_ascii=False, sort_keys=True)
        self.calls.append({'number': number + 1, 'task_keys': sorted(task),
            'request_characters': len(payload), 'instruction_characters': len(instructions),
            'request_sha256': hashlib.sha256(payload.encode()).hexdigest(),
            'supplied_files': len(request.get('files', {})),
            'writable_files': sum(bool(v.get('writable')) for v in request.get('files', {}).values())})
        response = record.get('response')
        if not isinstance(response, dict):
            raise ValueError('Every replay response must be a JSON object')
        return deepcopy(response)

    def finish(self):
        if len(self.calls) != len(self.records):
            raise ValueError(f'Unused offline responses: {len(self.records) - len(self.calls)}')
        return {'scripted_model_calls': len(self.calls), 'real_model_requests': 0,
                'request_characters': sum(c['request_characters'] for c in self.calls),
                'instruction_characters': sum(c['instruction_characters'] for c in self.calls),
                'calls': self.calls}
