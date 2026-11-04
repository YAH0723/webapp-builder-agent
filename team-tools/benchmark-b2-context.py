"""Compare serialized context sizes using versioned sample data; no model requests."""
import json
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from infrastructure.shared.agent.efficiency import (
    CONTEXT_RULES, REFERENCE_RULES, compact_context, intern_context)
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.tools.protocol import FILE_TOOL_RULES, scoped_file_rules
from infrastructure.stages.frontend.triggers.acceptance import INSTRUCTIONS


def measure():
    requirement = yaml.safe_load((ROOT / 'input/requirements.yaml').read_text(encoding='utf-8-sig'))
    fixture = 'backend/tests/support/context.ts'
    template = ROOT / 'infrastructure/shared/project/templates'
    source = (template / fixture).read_text(encoding='utf-8')
    payload = {'task': {'requirement': requirement, 'original_requirement': requirement},
        'files': {fixture: {'content': source, 'writable': False}},
        'read_files': {fixture: [{'content': source, 'start_line': 1,
            'end_line': len(source.splitlines()), 'total_lines': len(source.splitlines())}]},
        'context_records': {'requirement': {'SAMPLE': requirement}},
        'context_result': {'kind': 'requirement', 'records': {'SAMPLE': requirement}}}
    b1 = compact_context(payload)
    b2 = intern_context(b1)
    prompts = {'b0': INSTRUCTIONS + FILE_TOOL_RULES,
        'b1': INSTRUCTIONS + FILE_TOOL_RULES + CONTEXT_RULES,
        'b2': INSTRUCTIONS + scoped_file_rules(FileTools(template, readable=[fixture])) + CONTEXT_RULES + REFERENCE_RULES}
    sizes = {profile: {'payload_chars': len(json.dumps(data, ensure_ascii=False)),
        'instructions_chars': len(prompts[profile]),
        'combined_chars': len(json.dumps(data, ensure_ascii=False)) + len(prompts[profile])}
        for profile, data in {'b0': payload, 'b1': b1, 'b2': b2}.items()}
    return {'kind': 'controlled repeated-context fixture, not a platform run',
        'fixture': 'versioned authentication sample requirement and backend test helper',
        'real_model_requests': 0, 'measured_tokens': None, 'measured_cost': None,
        'profiles': sizes, 'b2_vs_b0_char_reduction': 1 - sizes['b2']['combined_chars'] / sizes['b0']['combined_chars'],
        'b2_vs_b1_char_reduction': 1 - sizes['b2']['combined_chars'] / sizes['b1']['combined_chars']}


if __name__ == '__main__':
    result = measure()
    path = ROOT / 'releases/b2-context-benchmark.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
