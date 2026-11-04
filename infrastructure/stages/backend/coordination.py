"""Coordinate shared API designs without relaxing exact write obligations.

No task vocabulary, API alias inference, or synthesized business behavior belongs
here. A rejected candidate never becomes the canonical design.
"""

from collections import Counter
from copy import deepcopy
import json

from infrastructure.stages.backend.context import requirement_context
from infrastructure.stages.backend.primitives import ObligationCoverageError


API_FIELDS = ('description', 'read', 'write', 'signature', 'request', 'response',
    'precondition', 'postcondition')
RESULT_CONTRACT = {
    'required_top_level': {'apis': 'object of COMPLETE new or changed API definitions',
        'requirement_apis': 'array of existing or newly defined API ID strings'},
    'api_required_fields': list(API_FIELDS),
    'reuse': 'Unchanged accepted APIs may be referenced by ID without repeating their definitions.',
    'no_inference': 'Missing associations/definitions are errors; never guess IDs or omit required behavior.'}
COORDINATION_RULES = '''Before reusing a shared API, check api_compatibility and the
current exact write obligation. A shared operation has one canonical possible-write
set. Do not alternately add/remove effects to satisfy different owners. If it is
incompatible, leave the accepted operation unchanged and select/design the distinct
operation actually supported by the current scenarios. Given setup is not a new
mutation. Different API IDs cannot disguise one method/path with conflicting effects.
Updates must preserve every earlier owner's coverage. Query their original scenarios
when needed. If obligations themselves conflict with the original evidence, report
the conflict; do not silently change obligations, validation rules or test expectations.
Return both required root keys: apis and requirement_apis. Match result_contract.
Never return an API map directly, correction metadata, or only a partial association.
'''


class APIResponseError(ValueError):
    def __init__(self, message, **details):
        self.feedback = details
        super().__init__(message)


def validate_response(response, design):
    """Fail with local, actionable shape/reference errors before merging artifacts."""
    if not isinstance(response, dict):
        raise APIResponseError('API result must be an object with apis and requirement_apis')
    changes, selected = response['apis'], response['requirement_apis']
    if not isinstance(changes, dict) or not isinstance(selected, list) or any(
            not isinstance(aid, str) for aid in selected):
        raise APIResponseError('apis must be an object; requirement_apis must be an array of ID strings')
    if len(selected) != len(set(selected)):
        raise APIResponseError('requirement_apis contains duplicate IDs')
    for aid, api in changes.items():
        if not isinstance(aid, str) or not aid or not isinstance(api, dict):
            raise APIResponseError('Every API ID must map to a complete object')
        for field in API_FIELDS:
            api[field]  # Preserve a precise KeyError for a missing field.
        if not isinstance(api['description'], str):
            raise APIResponseError('API description must be a string', api_id=aid)
        for mode in ('read', 'write'):
            if not isinstance(api[mode], list) or any(not isinstance(item, str) for item in api[mode]):
                raise APIResponseError('API read/write must be arrays of qualified field strings', api_id=aid)
        signature = api['signature']
        if not isinstance(signature, dict) or any(not isinstance(signature.get(key), str)
                or not signature[key] for key in ('name', 'method', 'path')):
            raise APIResponseError('API signature requires name, method and path strings', api_id=aid)
        if signature['method'].upper() not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'} or not signature['path'].startswith('/api/'):
            raise APIResponseError('API signature requires an HTTP method and /api/ path', api_id=aid)
        request, result = api['request'], api['response']
        if not isinstance(request, dict) or any(not isinstance(request.get(key), dict)
                for key in ('params', 'query', 'body', 'headers')):
            raise APIResponseError('API request requires params/query/body/headers JSON Schema objects', api_id=aid)
        if not isinstance(result, dict) or not isinstance(result.get('success'), dict) or not isinstance(result.get('errors'), list):
            raise APIResponseError('API response requires success object and errors array', api_id=aid)
        for branch in [result['success'], *result['errors']]:
            if not isinstance(branch, dict) or type(branch.get('status')) is not int or not 100 <= branch['status'] <= 599 or any(
                    not isinstance(branch.get(key), dict) for key in ('body', 'headers')):
                raise APIResponseError('Response branches require HTTP status and body/headers schema objects', api_id=aid)
        for field in ('precondition', 'postcondition'):
            if not isinstance(api[field], list) or any(not isinstance(item, dict) for item in api[field]):
                raise APIResponseError('API conditions must be arrays of objects', api_id=aid)
    unknown = sorted(set(selected) - (set(design['apis']) | set(changes)))
    if unknown:
        raise APIResponseError('Selected API IDs have no accepted or proposed definition: ' + ', '.join(unknown),
            unknown_api_ids=unknown, accepted_api_ids=sorted(design['apis']))


def validate_endpoints(design):
    seen = {}
    for aid, api in design['apis'].items():
        signature = api['signature']
        endpoint = (signature['method'].upper(), signature['path'])
        if endpoint in seen:
            raise APIResponseError('Different API IDs share one method/path; reuse the canonical ID or design a genuinely distinct operation',
                api_ids=[seen[endpoint], aid], endpoint=list(endpoint))
        seen[endpoint] = aid


def compatibility(design, obligations, current, api_ids):
    result = {}
    current_writes = set(obligations['requirements'][current]['write'])
    for aid in api_ids:
        api = design['apis'][aid]
        owners = [rid for rid, ids in design['requirements'].items() if aid in ids]
        result[aid] = {'owners': owners, 'accepted_write_fields': api['write'],
            'fits_current_write_boundary': set(api['write']) <= current_writes,
            'owner_write_boundaries': {rid: obligations['requirements'][rid]['write'] for rid in owners}}
    return deepcopy(result)


class APIDesignRecovery:
    """Expose impacted owners, replan once, then stop repeated failures explicitly."""
    def __init__(self, design, obligations, tree, current):
        self.design, self.obligations, self.tree, self.current = design, obligations, tree, current
        self.counts, self.history = Counter(), []

    def __call__(self, error, response, feedback):
        details = deepcopy(getattr(error, 'feedback', {}))
        if isinstance(error, ObligationCoverageError):
            fingerprint = json.dumps({key: details.get(key) for key in ('requirement_id', 'missing', 'excess')}, sort_keys=True)
        else:
            fingerprint = type(error).__name__ + ':' + str(error)
        self.counts[fingerprint] += 1
        changed = set(response.get('apis', {})) if isinstance(response, dict) and isinstance(response.get('apis'), dict) else set()
        affected = {self.current}
        affected.update(rid for rid, ids in self.design['requirements'].items() if changed.intersection(ids))
        owner = details.get('requirement_id')
        if owner in self.tree.requirements:
            affected.add(owner)
        context = {'result_contract': RESULT_CONTRACT,
            'affected_requirements': {rid: {'source': requirement_context(self.tree, rid),
                'obligations': self.obligations['requirements'][rid],
                'accepted_api_ids': self.design['requirements'].get(rid, [])} for rid in sorted(affected)},
            'shared_api_constraints': compatibility(self.design, self.obligations, self.current, changed.intersection(self.design['apis']))}
        self.history.append({'error_type': type(error).__name__, 'error': feedback['error'],
            'occurrences': self.counts[fingerprint]})
        feedback['repair_context'] = context
        feedback['recent_failures'] = self.history[-4:]
        feedback['retry_guidance'] = ('Use repair_context to repair the complete output shape and coordinate all affected owners. '
            'Preserve the accepted API definitions unless a compatible change is supported by source evidence.')
        if self.counts[fingerprint] >= 2:
            # Do not feed the same malformed answer back as a de facto template.
            feedback.pop('previous_response', None)
            feedback.pop('invalid_response', None)
            feedback['recovery_mode'] = 'replan_from_accepted_contracts'
            feedback['retry_guidance'] = ('The same failure has recurred. Replan from the original task, result_contract and accepted contracts. '
                'Do not repeat or oscillate the rejected shared-API change. Return BOTH apis and requirement_apis. '
                'For incompatible write boundaries, retain the existing operation and use a scenario-supported compatible operation; '
                'do not rename the same endpoint to bypass the check.')
        if self.counts[fingerprint] >= 3:
            feedback['stop_retrying'] = True
        return feedback
