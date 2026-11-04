"""Compare compatible local reports without treating characters as tokens or costs."""
import argparse
import json
from pathlib import Path


def compare(reports):
    keys = ('kind', 'stage', 'scope', 'targets', 'workload_sha256')
    same = all(all(report.get(key) == reports[0].get(key) for key in keys) for report in reports)
    same = same and bool(reports[0].get('workload_sha256'))
    same = same and all(set(report.get('checks', {})) == set(reports[0].get('checks', {}))
                        for report in reports)
    rows = [{key: report.get(key) for key in ('status', 'seconds', 'stage', 'scripted_model_calls',
             'request_characters', 'instruction_characters', 'real_model_requests')} for report in reports]
    return {'comparable_workload': same, 'rows': rows,
            'interpretation': ('Same recorded workload and selected checks; wall time still depends on environment.' if same
                else 'Different or missing workload/scope/checks. Do not attribute timing differences to the agent.'),
            'token_savings': None, 'monetary_savings': None, 'official_score': None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', type=Path, nargs='+')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if len(args.reports) < 2:
        parser.error('Provide at least two report JSON files')
    result = compare([json.loads(p.read_text(encoding='utf-8-sig')) for p in args.reports])
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
