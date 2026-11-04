"""Build a versioned ARC-Bench agent ZIP without local secrets or task data."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "d3da23e9897db84cfd37ce04a4ab5b38424ef399"
B1_SOURCE = "4a7d3df00d009d95f0a2b85bb7890d30e4276c89"
B2_SOURCE = "c1cde93a4f73b19500a14b44d9438459fb2643a5"
B21_SOURCE = "aeb123530991ae6392bc3888e81bcd758a2f3eec"
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

README_B1 = """# WebApp Builder Agent: B1 efficient execution

Based on requirement-compilation-structure revision
d3da23e9897db84cfd37ce04a4ab5b38424ef399.
Source: https://github.com/YAH0723/webapp-builder-agent

Entry point:
python3 main.py REQUIREMENTS_DIRECTORY --output-dir APPLICATION_DIRECTORY
Install dependencies with pip install -r requirements.txt.
Runtime also needs Node.js 22.12+, npm, Git and Bash.

B1 removes exact duplicate context, advertises restricted file access and stops
internal E2E execution after the first failed test. Failed/skipped acceptance
is not successful; an all-passing run still executes the complete selected suite.
The official evaluator and all 13 generation stages remain in place.

Default profile: b1. ARC_AGENT_PROFILE=b0 disables the B1 mechanisms for comparison.
Independent feature switches: ARC_B1_CONTEXT_REUSE, ARC_B1_ACCESS_HINTS,
ARC_B1_FAIL_FAST (0 or 1). These are runtime settings, never bundled secrets.
Context size telemetry is saved to .arc/b1_context.jsonl; it counts characters,
not actual model tokens or monetary cost.

Model default remains deepseek-flash. OPENAI_BASE_URL and OPENAI_API_KEY are
supplied by the platform. No .env file, key, task data or local logs are bundled.
Offline mechanism checks do not establish an official ARC-Bench score or cost reduction.
Inspect .arc/compilation.json as well as the process exit status.
"""


README_B2 = """# WebApp Builder Agent: B2 acceptance-first

Source: https://github.com/YAH0723/webapp-builder-agent
Reference: d3da23e9897db84cfd37ce04a4ab5b38424ef399
Entry: python3 main.py REQUIREMENTS_DIRECTORY --output-dir APPLICATION_DIRECTORY
Dependencies: pip install -r requirements.txt; Node.js 22.12+, npm, Git, Bash.

Default profile b2 replaces stage 12's duplicate process-smoke and independent
acceptance authoring with a single original-requirement acceptance-first loop.
Tests are authored/reviewed separately; implementation repair cannot write tests.
Current/accepted acceptance checks run during local repair. Complete acceptance,
UI, backend and build regression run at the end, with a bounded final repair.
Full final acceptance disables fail-fast and rejects missing/empty suites.
Stage 11 builds validated requirement/UI/API binding tables without model calls;
original DB-obligation capability checks remain active.

B2 also interns exact repeated JSON containers with input-only context references,
provides scope-specific tool examples, and bounds actual model calls per task,
including internal file/context lookups. Backend test-only generation defers its
redundant accepted-suite run to the full implementation regression immediately after.

ARC_AGENT_PROFILE=b0/b1/b2 selects the execution profile. Per-feature environment
overrides take precedence. ARC_B2_MAX_TASK_CALLS defaults to 16.
Model remains deepseek-flash; platform supplies OPENAI_BASE_URL/OPENAI_API_KEY.
No keys, .env files, task data, generated apps or local logs are bundled.

Tests and offline smoke results do not establish official ARC-Bench quality,
runtime or monetary savings. Compare the same task/model on the platform.
Inspect .arc/compilation.json and .arc/frontend_e2e.json, not just exit code.
"""


README_B21 = README_B2 + """

B2.1 adds a task-independent contract registry and lightweight requirement index.
.arc/contracts.json links requirement IDs, schema fields, API definitions and pages.
Explicit depends_on IDs are preserved and checked for unknown references/cycles;
containment is not treated as an execution dependency. Static validation is
report-only. The original runtime gates remain authoritative.
Repair context can retrieve contract/dependency records and use actual failed
test paths to find related requirements and sources. Impact is conservative;
it is not permission to skip tests or a causal diagnosis.
ARC_B2_CONTRACT_REGISTRY=0 disables this layer. Execution profile remains b2.
Multi-domain mechanism tests do not establish multi-task generation quality.
"""

README_B22 = README_B21.replace('B2 acceptance-first', 'B2.2 coordinated API design', 1) + """

B2.2 adds scenario-grounded shared API coordination in stage 06. Tasks see accepted
API owners and exact write boundaries. Rejected updates expose affected source
requirements together; exact write and earlier-owner checks remain mandatory.
Complete API result shapes/references and duplicate method/path identities are checked
before acceptance. No missing association, endpoint alias or business rule is inferred.
Repeated identical failures trigger targeted replanning on their second occurrence;
a third occurrence stops that task as failed, preserving accepted neighboring work.
The stage uses at most 6 proposals and 8 logical model calls per requirement,
including context queries (SDK transport retries are outside this logical count).
ARC_B2_API_COORDINATION=0 restores the previous stage-06 behavior.
Offline regressions are not an official accuracy, duration or cost result.
"""


def git(*arguments: str) -> bytes:
    return subprocess.check_output(["git", *arguments], cwd=ROOT)


def compiler_path(name: str) -> bool:
    path = PurePosixPath(name)
    if path.parts[0] == "infrastructure":
        return True
    return name in {"main.py", "requirements.txt", "pyproject.toml", "uv.lock", "principle.md"} or bool(
        re.fullmatch(r"\d{2}_[^/]+\.py", name)
    )


def build(output: Path, variant: str = "B0") -> dict:
    if variant not in {"B0", "B1", "B2", "B2.1", "B2.2"}:
        raise ValueError("variant must be B0, B1, B2, B2.1 or B2.2")
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
    if not required.issubset(payload):
        raise ValueError(f"Missing runtime files: {required - payload.keys()}")
    unchanged = not git("diff", UPSTREAM, "--", *names).strip()
    if variant == "B0" and not unchanged:
        raise ValueError("B0 requires unchanged reference compiler sources. Review changes before packaging.")
    if variant == "B1" and git("diff", B1_SOURCE, "--", *names).strip():
        raise ValueError("B1 is frozen at " + B1_SOURCE + "; use --variant B2 for the revised compiler.")
    if variant == "B2" and git("diff", B2_SOURCE, "--", *names).strip():
        raise ValueError("B2 is frozen at " + B2_SOURCE + "; use --variant B2.1 for the contract-index version.")
    if variant == "B2.1" and git("diff", B21_SOURCE, "--", *names).strip():
        raise ValueError("B2.1 is frozen at " + B21_SOURCE + "; use --variant B2.2 for API coordination.")
    if git("diff", "HEAD", "--", *names).strip():
        raise ValueError("Commit runtime changes before packaging so source_commit identifies the shipped code.")
    payload["README.md"] = {"B0": README, "B1": README_B1, "B2": README_B2,
        "B2.1": README_B21, "B2.2": README_B22}[variant].encode("utf-8")
    manifest = {
        "variant": {"B0": "B0-reference", "B1": "B1-efficiency", "B2": "B2-acceptance-first",
            "B2.1": "B2.1-generic-contracts", "B2.2": "B2.2-api-coordination"}[variant],
        "source_commit": git("rev-parse", "HEAD").decode().strip(),
        "upstream_commit": UPSTREAM, "compiler_unchanged": unchanged,
        "entrypoint": "main.py", "default_model": "deepseek-flash",
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())},
    }
    if variant == "B1":
        manifest["default_profile"] = "b1"
        manifest["features"] = ["context_reuse", "access_hints", "fail_fast"]
    if variant in {"B2", "B2.1", "B2.2"}:
        manifest["default_profile"] = "b2"
        manifest["features"] = ["acceptance_first", "direct_bindings", "context_reuse", "context_interning",
            "access_hints", "scoped_tools", "task_budget", "fail_fast", "backend_precheck"]
        manifest["default_task_call_limit"] = 16
    if variant in {"B2.1", "B2.2"}:
        manifest["features"].append("contract_registry")
    if variant == "B2.2":
        manifest["features"].append("api_coordination")
        manifest["api_design_limits"] = {"proposals": 6, "logical_calls": 8, "same_failure_occurrences": 3}
    payload["submission-manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    output = output.resolve()
    if output.is_relative_to(ROOT / "infrastructure"):
        raise ValueError("Output must not overwrite compiler sources")
    if output.is_file():
        with zipfile.ZipFile(output) as existing:
            old = json.loads(existing.read('submission-manifest.json'))
        if old['variant'] != manifest['variant']:
            raise ValueError('Do not overwrite a published archive with a different variant')
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
        "size_bytes": output.stat().st_size, "file_count": len(payload),
        "source_commit": manifest["source_commit"], "compiler_unchanged": unchanged,
        "default_model": manifest["default_model"], "variant": manifest["variant"]}
    output.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=("B0", "B1", "B2", "B2.1", "B2.2"), default="B0")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / f"releases/webapp-builder-agent-{args.variant}.zip"
    print(json.dumps(build(output, args.variant), ensure_ascii=False, indent=2))
