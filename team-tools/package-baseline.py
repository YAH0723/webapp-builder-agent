"""Build an ARC-Bench ZIP from compiler sources, without local secrets or data."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "d3da23e9897db84cfd37ce04a4ab5b38424ef399"
README = """# WebApp Builder Agent: baseline B0

Unoptimized reference requirement compiler, packaged for ARC-Bench Web tasks.
Source: https://github.com/code-philia/requirement-compilation-structure
Reference revision: d3da23e9897db84cfd37ce04a4ab5b38424ef399

Entry point (the platform supplies both paths):
python3 main.py REQUIREMENTS_DIRECTORY --output-dir APPLICATION_DIRECTORY

Install Python dependencies with pip install -r requirements.txt.
The runtime also needs Node.js 22.12+, npm, Git and Bash.
The generated application includes deploy.sh for installation/build/start.

Model default: deepseek-flash, inherited from the reference implementation.
The same default is used for reference-image analysis and must support images.
The endpoint must provide this model, or configure MODEL/VISUAL_MODEL in the
runtime environment (or change the code and rebuild before uploading).
OPENAI_BASE_URL and OPENAI_API_KEY are supplied by ARC-Bench at runtime.
No credentials or .env file are bundled. Do not override the platform proxy.

This archive contains the agent, not a pre-generated BookStack application.
The platform supplies the task requirements. No model calls or official
BookStack evaluation were performed as part of packaging.

The compiler sources are unchanged from the reference revision. Its current
CLI can finish with code 0 even when compilation.json records stage failures;
inspect compilation and platform logs, not only the process exit status.
"""


def git(*arguments: str) -> bytes:
    return subprocess.check_output(["git", *arguments], cwd=ROOT)


README_B3 = """# WebApp Builder Agent: B3 flow batching

Based on B0 compiler e529ae516a2f231e41439b750dfb5b88f7e20657.
Source: https://github.com/YAH0723/webapp-builder-agent
Entry: python3 main.py REQUIREMENTS_DIRECTORY --output-dir APPLICATION_DIRECTORY
Install pip requirements.txt; runtime needs Node.js 22.12+, npm, Git and Bash.

Stage 12 separately authors scenario suites, then jointly implements adjacent
requirements sharing pages/APIs. Groups preserve order and split at four requirements
or 60000 task-context characters. Tests are read-only during group implementation.
Failed groups restore their baseline; original B0 independent final acceptance follows.
The earlier B0 stages and validators remain, including model-authored stage 11 design.

Other changes: exact context deduplication, permission-consistent tool examples,
shared API owner evidence, deterministic failed-check localization, bounded logical
model calls (32/task, 32/design, 48/group) and four-repeat acceptance-failure stop.
SDK retries are outside logical counters. No semantic summary or context-reference DSL.
ARC_AGENT_PROFILE=b3 is default; b0 disables features but is not the frozen B0 ZIP.
Boolean switches: ARC_B3_FLOW_BATCHES, ARC_B3_SHARED_CONTRACTS, ARC_B3_CONTEXT_REUSE,
ARC_B3_SCOPED_TOOLS, ARC_B3_FAILURE_EVIDENCE, ARC_B3_BOUNDED_REPAIR.
Task/context/group metadata: .arc/b3_metrics.jsonl and .arc/b3_flow_plan.json.

Model, reasoning and output defaults remain B0's (deepseek-flash).
Platform supplies OPENAI_BASE_URL and OPENAI_API_KEY; no .env/key is bundled.
This is a general agent, not a generated site or benchmark-specific answer.
Offline checks do not establish official quality, cost, speed or composite-score gains.
Inspect compilation.json and actual evaluator results, not just process exit status.
"""


README_B4 = """# WebApp Builder Agent: B4.2 contract transport generation

General requirement-to-web-application compiler, not a pre-generated application.
Entry: python3 main.py REQUIREMENTS_DIRECTORY --output-dir APPLICATION_DIRECTORY
Install pip requirements.txt; runtime needs Node.js 22.12+, npm, Git and Bash.

B4 groups backend HTTP contract tests/implementation (5 APIs), UI design (6 requirements),
page implementation with business wiring (4 pages), deterministic UI/API bindings and
ONE independently authored acceptance family (4 requirements) with grouped app repair.
Tests are read-only during app repair. Independent authors cannot read application code.
Previously accepted suites regress per group; final full tests and builds remain required.
Model/reasoning and platform credential loading are unchanged from B0/B3.

ARC_AGENT_PROFILE=b4 is default; b3 selects previous orchestration, b0 disables features
but is not the frozen B0 ZIP. Switches: ARC_B4_BACKEND_BATCHES,
ARC_B4_UI_DESIGN_BATCHES, ARC_B4_UI_IMPLEMENTATION_BATCHES,
ARC_B4_DIRECT_BINDINGS, ARC_B4_ACCEPTANCE_FIRST. Direct bindings require acceptance-first;
otherwise original trigger design is used. B3 switches remain available.
Positive settings: ARC_B4_API_BATCH_SIZE=5, ARC_B4_UI_DESIGN_BATCH_SIZE=6,
ARC_B4_PAGE_BATCH_SIZE=4, ARC_B4_ACCEPTANCE_BATCH_SIZE=4,
ARC_B4_BATCH_CONTEXT_CHARS=80000, ARC_B4_BATCH_CALLS=48.
Reports and .arc/b3_metrics.jsonl retain plans, failures and actual check evidence.
B4.1 adds one bounded split for failed UI design batches and local replay tooling.
B4.2 additionally compiles canonical API route registration, transport types and a JSON
request client. ARC_B4_CONTRACT_CODEGEN=0 disables this addition for a fresh workspace.
Existing custom registry/client files are preserved. Generated transport stays read-only;
business handlers, validation and application state remain model-owned. Unsupported
contracts fall back to model-owned wiring. No business behaviors are pre-generated.

Platform supplies OPENAI_BASE_URL and OPENAI_API_KEY. No .env or key is bundled.
No paid inference or official evaluation is performed during packaging. Local checks
do not establish actual cost, time, quality or composite-score improvements.
Inspect compilation.json and evaluator results, not only exit status.
"""


def compiler_path(name: str) -> bool:
    path = PurePosixPath(name)
    if path.parts[0] == "infrastructure":
        return True
    return name in {"main.py", "requirements.txt", "pyproject.toml", "uv.lock", "principle.md"} or bool(
        re.fullmatch(r"\d{2}_[^/]+\.py", name)
    )


def build(output: Path, variant: str = 'B4.2') -> dict:
    if variant not in {'B0', 'B4.2'}:
        raise ValueError('Use frozen branches/packages for previous variants; this branch packages B4.2')
    names = sorted(name.decode("utf-8") for name in git("ls-files", "-z").split(b"\0")
        if name and compiler_path(name.decode("utf-8")))
    payload = {}
    for name in names:
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Expected a regular source file: {name}")
        if any(part in {".git", "node_modules", "__pycache__", ".venv"} for part in path.parts):
            raise ValueError(f"Unexpected runtime dependency/cache: {name}")
        if path.name == ".env" or path.name.startswith(".env."):
            raise ValueError(f"Unexpected environment file: {name}")
        data = path.read_bytes()
        if path.suffix == ".sh":
            data = data.replace(b"\r\n", b"\n")
        payload[name] = data
    required = {"main.py", "requirements.txt", "infrastructure/compiler.py",
        "infrastructure/shared/project/templates/deploy.sh"}
    if variant == 'B4.2':
        required.update({'infrastructure/shared/agent/efficiency.py',
            'infrastructure/shared/agent/batching.py', 'infrastructure/stages/backend/batching.py',
            'infrastructure/stages/frontend/ui/batching.py',
            'infrastructure/stages/frontend/triggers/acceptance_batches.py',
            'infrastructure/stages/frontend/triggers/direct.py',
            'infrastructure/shared/project/contract_codegen.py'})
    if not required.issubset(payload):
        raise ValueError(f"Missing runtime files: {required - payload.keys()}")
    unchanged = not git("diff", UPSTREAM, "--", *names).strip()
    if variant == 'B0' and not unchanged:
        raise ValueError("B0 requires unchanged reference compiler sources. Review changes before packaging.")
    if variant != 'B0' and git('diff', 'HEAD', '--', *names).strip():
        raise ValueError('Commit the reviewed compiler before packaging')
    payload["README.md"] = (README if variant == 'B0' else README_B4).encode("utf-8")
    manifest = {
        "variant": "B0-reference" if variant == 'B0' else 'B4.2-contract-codegen', "source_commit": git("rev-parse", "HEAD").decode().strip(),
        "baseline_compiler_commit": "e529ae516a2f231e41439b750dfb5b88f7e20657",
        "upstream_commit": UPSTREAM, "compiler_unchanged": unchanged,
        "entrypoint": "main.py", "default_model": "deepseek-flash",
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())},
    }
    payload["submission-manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    output = output.resolve()
    if output.suffix.lower() != '.zip' or output.exists():
        raise ValueError('Use a new .zip output path; released archives are never overwritten')
    if output.is_relative_to(ROOT / "infrastructure"):
        raise ValueError("Output must not overwrite compiler sources")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(payload.items()):
            entry = zipfile.ZipInfo(name, date_time=(2026, 11, 4, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None or set(archive.namelist()) != set(payload):
            raise ValueError("Archive verification failed")
    summary = {"archive": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "variant": manifest['variant'],
        "size_bytes": output.stat().st_size, "file_count": len(payload),
        "source_commit": manifest["source_commit"], "compiler_unchanged": unchanged,
        "default_model": manifest["default_model"]}
    output.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant', choices=['B0','B4.2'], default='B4.2')
    parser.add_argument("--output", type=Path)
    args=parser.parse_args()
    print(json.dumps(build(args.output or ROOT / f'releases/webapp-builder-agent-{args.variant}.zip', args.variant), ensure_ascii=False, indent=2))
