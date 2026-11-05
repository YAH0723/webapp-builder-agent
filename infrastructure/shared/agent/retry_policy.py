"""Small retry budgets and stable identities for tool failures before acceptance."""
from infrastructure.shared.agent.efficiency import failure_fingerprint, positive_setting

PERMISSION_CODES = {'WRITE_NOT_ALLOWED', 'READ_NOT_ALLOWED', 'INVALID_PATH'}


def attempt_limit(requested, kind='EDIT_ROUNDS'):
    return min(requested, positive_setting('MAX_' + kind, 3))


def tool_details(error):
    value = getattr(error, 'feedback', None)
    return value if isinstance(value, dict) and value.get('code') else None


def rejection_identity(error, feedback, checking):
    details = tool_details(error)
    if details:
        # Previous response, edit span, call index, examples and diagnosis can vary
        # while the actual blocked operation/path stays identical.
        return failure_fingerprint({'phase': 'tool', 'code': details['code'],
            'path': details.get('path'), 'tool': details.get('tool')})
    if checking:
        return failure_fingerprint({'phase': 'acceptance', 'evidence': feedback})
    return failure_fingerprint({'phase': 'response', 'type': type(error).__name__,
                                'message': getattr(error, 'msg', str(error))})


def permission_hint(error, files):
    details = tool_details(error)
    if not details or details['code'] not in PERMISSION_CODES: return None
    return {'code': details['code'], 'blocked_path': details.get('path'),
            'writable_existing_paths': sorted(path for path in files.files | files.changed_paths
                                              if files.can_write(path)),
            'new_files_allowed_by_stage_scope': files.allow_write is not None,
            'instruction': 'Do not repeat the blocked operation. Use permitted business sources. '
                           'Tests, fixtures, configuration and compiler runtime remain protected. '
                           'New paths must pass the same stage ownership checks.'}
