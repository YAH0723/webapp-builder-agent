"""Offline B1 mechanism benchmark; no model API or ARC-Bench score is used."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from infrastructure.shared.agent.efficiency import CONTEXT_RULES, compact_context


def context_benchmark():
    """Use a controlled duplicated schema and a real compiler template excerpt."""
    schema = {f"Entity{i}": {"description": "A persistent entity with validated fields.",
        "fields": {f"field{j}": {"type": "string", "description": "Required persisted value"}
            for j in range(12)}} for i in range(16)}
    path = "backend/src/db/initialize.ts"
    source = (ROOT / "infrastructure/shared/project/templates" / path).read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    payload = {"task": {"id": "controlled-context"},
        "context_records": {"schema": schema},
        "context_result": {"kind": "schema", "records": schema, "missing": []},
        "files": {path: {"content": source, "writable": False}},
        "read_files": {path: [{"content": source, "start_line": 1,
            "end_line": len(lines), "total_lines": len(lines), "writable": False}]}}
    packed = compact_context(payload)
    assert packed["context_records"]["schema"] == schema
    assert packed["files"][path]["content"] == source
    before = len(json.dumps(payload, ensure_ascii=False))
    after = len(json.dumps(packed, ensure_ascii=False)) + len(CONTEXT_RULES)
    return {"fixture": "controlled duplicated schema + compiler template",
        "before_chars": before, "after_chars_including_extra_rules": after,
        "reduction_fraction": 1 - after / before,
        "all_schema_definitions_and_source_preserved": True,
        "measured_tokens": None, "measured_api_cost": None}


def run_suite(node, cli, fixture, *, fixed, fail_fast):
    args = [node, str(cli), "test", "--config", str(fixture / "playwright.config.cjs")]
    if fail_fast:
        args.append("--max-failures=1")
    args.extend(["--grep", "fixed" if fixed else "broken"])
    start = perf_counter()
    result = subprocess.run(args, cwd=fixture, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60)
    elapsed = perf_counter() - start
    try:
        stats = json.loads(result.stdout)["stats"]
    except (ValueError, KeyError) as error:
        raise RuntimeError("Playwright benchmark failed: " + result.stderr[-2000:]) from error
    row = {"wall_seconds": round(elapsed, 3), "returncode": result.returncode,
        "passed": stats.get("expected", 0), "failed": stats.get("unexpected", 0),
        "skipped": stats.get("skipped", 0)}
    if fixed:
        assert row["returncode"] == 0 and row["passed"] == 8 and not row["skipped"], row
    else:
        assert row["returncode"] != 0 and row["failed"] == 1, row
        assert row["skipped"] == (7 if fail_fast else 0), row
    return row


def benchmark(playwright_root, repeats):
    package = playwright_root.resolve() / "node_modules/@playwright/test"
    cli = package / "cli.js"
    if not cli.is_file():
        raise ValueError("Install @playwright/test in --playwright-root first")
    node = shutil.which("node")
    if not node:
        raise ValueError("Node.js is required")
    report = {"kind": "offline mechanism benchmark, not application or platform evaluation",
        "checked_at": datetime.now(timezone.utc).isoformat(), "real_model_requests": 0,
        "context": context_benchmark(), "repeats": repeats, "runs": []}
    with TemporaryDirectory(prefix="b1-check-") as directory:
        fixture = Path(directory)
        (fixture / "playwright.config.cjs").write_text(
            'module.exports = {testDir: __dirname, testMatch: "*.spec.cjs", workers: 1, '
            'retries: 0, reporter: "json", timeout: 10000};\n', encoding="utf-8")
        (fixture / "controlled.spec.cjs").write_text(
            "const {test, expect} = require(" + json.dumps(str(package)) + ");\n"
            "for (const state of ['broken', 'fixed']) {\n"
            " for (let i = 0; i < 8; i++) {\n"
            "  test(`${state} scenario ${i}`, async () => {\n"
            "   await new Promise(resolve => setTimeout(resolve, 150));\n"
            "   expect(state === 'broken' && i === 0 ? 'broken' : 'ok').toBe('ok');\n"
            "  });\n }\n}\n", encoding="utf-8")
        for repeat in range(repeats):
            # Alternate the order to reduce systematic cold/warm startup bias.
            for fixed in (False, True):
                for fast in ((False, True) if repeat % 2 == 0 else (True, False)):
                    row = run_suite(node, cli, fixture, fixed=fixed, fail_fast=fast)
                    report["runs"].append({"repeat": repeat + 1, "fixed": fixed,
                        "profile": "b1" if fast else "b0", **row})
    medians = {}
    for fixed in (False, True):
        for profile in ("b0", "b1"):
            key = ("fixed" if fixed else "broken") + "_" + profile
            medians[key] = round(statistics.median(row["wall_seconds"] for row in report["runs"]
                if row["fixed"] == fixed and row["profile"] == profile), 3)
    report["median_wall_seconds"] = medians
    report["broken_run_time_reduction_fraction"] = 1 - medians["broken_b1"] / medians["broken_b0"]
    report["all_fixed_runs_executed_all_eight_tests"] = True
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playwright-root", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, default=ROOT / "releases/b1-benchmark.json")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    result = benchmark(args.playwright_root, args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
