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


def compiler_path(name: str) -> bool:
    path = PurePosixPath(name)
    if path.parts[0] == "infrastructure":
        return True
    return name in {"main.py", "requirements.txt", "pyproject.toml", "uv.lock", "principle.md"} or bool(
        re.fullmatch(r"\d{2}_[^/]+\.py", name)
    )


def build(output: Path) -> dict:
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
    if not unchanged:
        raise ValueError("B0 requires unchanged reference compiler sources. Review changes before packaging.")
    payload["README.md"] = README.encode("utf-8")
    manifest = {
        "variant": "B0-reference", "source_commit": git("rev-parse", "HEAD").decode().strip(),
        "upstream_commit": UPSTREAM, "compiler_unchanged": unchanged,
        "entrypoint": "main.py", "default_model": "deepseek-flash",
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())},
    }
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
        "default_model": manifest["default_model"]}
    output.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "releases/webapp-builder-agent-B0.zip")
    print(json.dumps(build(parser.parse_args().output), ensure_ascii=False, indent=2))
