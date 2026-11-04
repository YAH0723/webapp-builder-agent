"""Versioned execution controls and lossless removal of repeated model context.

Only duplicated evidence is removed. Requirements, distinct file ranges, failed
checks and write permissions are never shortened or relaxed.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os


CONTEXT_RULES = """CONTEXT REUSE:
Use input.files[path].content before requesting that file again. Read calls may
contain several relevant paths in one batch. input.file_access, when present,
lists the only readable paths; a missing application source is not permission
to read it. Independent test tasks must use their declared contracts/fixtures.
context_result.retained_record_ids refers to definitions already present in
input.context_records under the same kind. Those definitions have not been lost.
"""


def enabled(feature):
    """Keep one profile switch and independent switches for ablation runs."""
    profile = os.getenv("ARC_AGENT_PROFILE", "b2").lower()
    if profile not in {"b0", "b1", "b2"}:
        raise ValueError("ARC_AGENT_PROFILE must be b0, b1 or b2")
    b2 = feature in {"acceptance_first", "direct_bindings", "task_budget", "context_interning", "scoped_tools", "backend_precheck", "contract_registry", "api_coordination", "diagnostics", "feature_runtime"}
    prefix = "ARC_B2_" if b2 else "ARC_B1_"
    value = os.getenv(prefix + feature.upper())
    if value is None:
        return profile == "b2" if b2 else profile != "b0"
    if value.lower() not in {"0", "1", "false", "true"}:
        raise ValueError(prefix + feature.upper() + " must be 0 or 1")
    return value.lower() in {"1", "true"}


def task_call_limit():
    """Bound actual model invocations, including reads inside one edit round."""
    value = int(os.getenv("ARC_B2_MAX_TASK_CALLS", "16"))
    if value < 1:
        raise ValueError("ARC_B2_MAX_TASK_CALLS must be positive")
    return value


def needs_generation_regression(changed_paths, test_path):
    """Test-only generation is followed by full implementation regression anyway."""
    return not enabled('backend_precheck') or bool(set(changed_paths) - {test_path})


REFERENCE_RULES = """Exact duplicate context may use {\"$context_ref\": \"/path/to/value\"}.
Resolve it within this input as a JSON Pointer (decode ~1 as / and ~0 as ~).
It is the identical complete value stored at that location, not missing evidence.
Do not request it again. References point to earlier canonical values, never cycles.
These references are input-only; return normal complete values in stage results and edits.
"""


def intern_context(payload, minimum_chars=800):
    """Intern exact repeated containers without truncating facts or file content."""
    seen = {}

    def visit(value, path):
        if not isinstance(value, (dict, list)):
            return value
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        eligible = len(encoded) >= minimum_chars and not (isinstance(value, dict) and "$context_ref" in value)
        if eligible and encoded in seen:
            return {"$context_ref": seen[encoded]}
        if eligible:
            seen[encoded] = path
        if isinstance(value, list):
            return [visit(child, path + "/" + str(i)) for i, child in enumerate(value)]
        return {key: visit(child, path + "/" + str(key).replace("~", "~0").replace("/", "~1"))
            for key, child in value.items()}

    return visit(payload, "")


def compact_context(payload):
    """Return a copy with exact duplicate excerpts/last-query records removed."""
    result = deepcopy(payload)
    files = result.get("files", {})
    reads = result.get("read_files", {})
    for path, excerpts in list(reads.items()):
        source = files.get(path, {}).get("content")
        if not isinstance(source, str):
            continue
        lines = source.splitlines(keepends=True)
        reads[path] = [item for item in excerpts if not (
            item.get("total_lines") == len(lines)
            and type(item.get("start_line")) is int
            and type(item.get("end_line")) is int
            and 1 <= item["start_line"] <= item["end_line"] <= len(lines)
            and "".join(lines[item["start_line"] - 1:item["end_line"]]) == item.get("content"))]
        if not reads[path]:
            del reads[path]
    if "read_files" in result and not reads:
        del result["read_files"]
    query = result.get("context_result")
    if isinstance(query, dict) and isinstance(query.get("records"), dict):
        retained = result.get("context_records", {}).get(query.get("kind"), {})
        duplicates = [key for key, value in query["records"].items()
            if key in retained and retained[key] == value]
        if duplicates:
            query["retained_record_ids"] = duplicates
            # deepcopy preserves aliases: a last query can share the same map
            # with retained evidence. Never delete from the canonical map.
            query["records"] = dict(query["records"])
            for key in duplicates:
                del query["records"][key]
            if not query["records"]:
                del query["records"]
    return result


def record_context_sizes(before, after):
    """Record payload sizes, not prompt text, credentials or estimated tokens."""
    from infrastructure.utils.presentation.logging import session_info
    session = session_info()
    if session is None:
        return
    before_chars = len(json.dumps(before, ensure_ascii=False))
    after_chars = len(json.dumps(after, ensure_ascii=False))
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": session["stage"], "before_chars": before_chars,
        "after_chars": after_chars, "saved_chars": before_chars - after_chars}
    destination = session["output"] / ".arc/b1_context.jsonl"
    with session["lock"]:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")
