"""Read complete requirements and deduplicate local reference images without inference."""
from hashlib import sha256
from pathlib import Path

import yaml
from infrastructure.stages.requirements.tree import RequirementTree


def load_requirements(directory):
    directory = Path(directory).resolve()
    source = (directory / 'requirements.yaml').read_bytes()
    root = yaml.safe_load(source.decode('utf-8-sig'))
    if not isinstance(root, dict): raise ValueError('requirements.yaml must contain a requirement object')
    ids, scenario_ids, step_ids, images = set(), set(), set(), {}
    def visit(node):
        if not isinstance(node, dict) or not isinstance(node.get('id'), str) or not node['id']:
            raise ValueError('Each requirement needs a nonempty string id')
        if node['id'] in ids: raise ValueError('Duplicate requirement id: ' + node['id'])
        ids.add(node['id'])
        for scenario in node.get('scenarios', []) or []:
            sid = scenario.get('id')
            if not isinstance(sid, str) or not sid or sid in scenario_ids: raise ValueError('Missing/duplicate scenario id')
            scenario_ids.add(sid)
            for step in scenario.get('steps', []) or []:
                identity = step.get('id')
                if not isinstance(identity, str) or not identity or identity in step_ids: raise ValueError('Missing/duplicate step id')
                step_ids.add(identity)
        description = node.get('description', {})
        for image in description.get('image', []) if isinstance(description, dict) else []:
            if not isinstance(image, dict) or not isinstance(image.get('reference'), str):
                raise ValueError('Image needs a local reference')
            path = (directory / image['reference']).resolve()
            if not path.is_relative_to(directory) or not path.is_file(): raise ValueError('Invalid image reference: ' + image['reference'])
            if path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp', '.gif'}:
                raise ValueError('Unsupported image reference: ' + image['reference'])
            digest = sha256(path.read_bytes()).hexdigest()
            record = images.setdefault(digest, {'path': path, 'references': []})
            record['references'].append({'requirement': node['id'], 'id': image.get('id'), 'reference': image['reference']})
        for child in node.get('children', []) or []: visit(child)
    visit(root)
    tree = RequirementTree(root)
    # IDs without scenarios still need a test mapping: do not silently omit description-only leaves.
    coverage = list(tree.steps) + ['requirement:' + rid for rid in tree.leaves if not tree.own_steps[rid]]
    return {'root': root, 'tree': tree, 'coverage': coverage, 'images': list(images.values()),
            'fingerprint': sha256(source + ''.join(sorted(images)).encode()).hexdigest()}


def validate_plan(value, requirement_ids):
    if not isinstance(value, dict): raise ValueError('Plan must be an object')
    for key in ('entities', 'routes', 'workflows'):
        if not isinstance(value.get(key), list): raise ValueError('Plan needs array: ' + key)
    routes = value['routes']
    if not routes or any(not isinstance(r, dict) or not isinstance(r.get('path'), str)
        or not r['path'].startswith('/') or r['path'].startswith('//') for r in routes):
        raise ValueError('Plan routes need same-origin paths')
    mapping = value.get('requirements')
    if not isinstance(mapping, dict) or set(mapping) != set(requirement_ids):
        raise ValueError('Plan must account for every original requirement id, without invented IDs')
    if any(not isinstance(item, str) or not item.strip() for item in mapping.values()):
        raise ValueError('Each requirement needs a concrete implementation obligation')
    return value
