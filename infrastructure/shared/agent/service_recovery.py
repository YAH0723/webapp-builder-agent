"""Classify transient transport failures and validate critical pass inputs."""
from infrastructure.utils.files import read_artifact
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.database.schema import check_related_fields
from infrastructure.stages.database.obligations.records import normalize_obligations, check_symbols
from infrastructure.stages.backend.primitives import validate_design


def retryable_service_error(error):
    """Use retained exception status/cause; do not retry quota or schema failures."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        status = getattr(error, 'status_code', None)
        if status == 429:
            message = str(error).lower()
            return not any(word in message for word in ('insufficient_quota', 'quota exhausted', 'balance too low', 'free allocated quota exceeded'))
        if status in {408, 409, 500, 502, 503, 504}:
            return True
        if type(error).__name__ in {'APIConnectionError', 'APITimeoutError'}:
            return True
        error = error.__cause__ or error.__context__
    return False


class PrerequisiteBlocked(ValueError):
    """A complete required artifact is unavailable; do not spend on dependents."""


def check_prerequisites(module, arc_dir):
    """Completeness gates, not defaults for missing requirements or business data."""
    number = int(module[:2])
    if number < 3:
        return
    try:
        tree = RequirementTree(read_artifact(arc_dir, 'requirements.json'))
        schema = read_artifact(arc_dir, 'db_schema.json')
        missing = [rid for rid in tree.leaves if rid not in schema.get('requirements', {})]
        if missing:
            raise ValueError('Missing schema associations for requirements: ' + ', '.join(missing))
        for rid in tree.leaves:
            check_related_fields(schema, schema['requirements'][rid])
        if number >= 4:
            obligations = normalize_obligations(read_artifact(arc_dir, 'db_obligations.json'), tree)
            check_symbols([*obligations['requirements'].values(), *obligations['steps'].values()], schema)
        if number >= 7:
            backend = read_artifact(arc_dir, 'backend_apis.json')
            validate_design(backend, obligations, tree=tree)
            check_symbols(backend['apis'].values(), schema)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise PrerequisiteBlocked(f'{module} blocked by incomplete prerequisite artifacts: {error}. '
            'Recover the upstream task before dependent generation; no records were fabricated.') from error
