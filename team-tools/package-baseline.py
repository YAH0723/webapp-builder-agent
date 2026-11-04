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
    if variant not in {"B0", "B1"}:
        raise ValueError("variant must be B0 or B1")
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
    if git("diff", "HEAD", "--", *names).strip():
        raise ValueError("Commit runtime changes before packaging so source_commit identifies the shipped code.")
    payload["README.md"] = (README if variant == "B0" else README_B1).encode("utf-8")
    manifest = {
        "variant": "B0-reference" if variant == "B0" else "B1-efficiency",
        "source_commit": git("rev-parse", "HEAD").decode().strip(),
        "upstream_commit": UPSTREAM, "compiler_unchanged": unchanged,
        "entrypoint": "main.py", "default_model": "deepseek-flash",
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())},
    }
    if variant == "B1":
        manifest["default_profile"] = "b1"
        manifest["features"] = ["context_reuse", "access_hints", "fail_fast"]
    payload["submission-manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    output = output.resolve()
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
        "size_bytes": output.stat().st_size, "file_count": len(payload),
        "source_commit": manifest["source_commit"], "compiler_unchanged": unchanged,
        "default_model": manifest["default_model"], "variant": manifest["variant"]}
    output.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=("B0", "B1"), default="B0")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / f"releases/webapp-builder-agent-{args.variant}.zip"
    print(json.dumps(build(output, args.variant), ensure_ascii=False, indent=2))
