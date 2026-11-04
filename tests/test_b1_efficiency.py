"""B1 must reduce duplicate work without losing evidence or accepting failed tests."""

from copy import deepcopy
import json
from threading import RLock
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.agent.efficiency import compact_context, enabled, record_context_sizes
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.models.text import TextModel
from infrastructure.stages.frontend.triggers.acceptance import require_acceptance
from infrastructure.stages.frontend.triggers.testing import E2EChecks


class ContextReuseTests(unittest.TestCase):
    def test_last_query_reuses_retained_definitions_and_preserves_missing(self):
        definition = {"fields": {"name": {"type": "string"}}, "description": "x" * 4000}
        payload = {"context_records": {"schema": {"Shelf": definition}},
            "context_result": {"kind": "schema", "records": {"Shelf": definition,
                "NewEntity": {"fields": {}}}, "missing": ["Unknown"]}}
        original = deepcopy(payload)
        result = compact_context(payload)
        self.assertEqual(payload, original)
        self.assertEqual(result["context_records"]["schema"]["Shelf"], definition)
        self.assertEqual(result["context_result"]["records"], {"NewEntity": {"fields": {}}})
        self.assertEqual(result["context_result"]["retained_record_ids"], ["Shelf"])
        self.assertEqual(result["context_result"]["missing"], ["Unknown"])
        self.assertLess(len(json.dumps(result)), len(json.dumps(payload)))

    def test_different_definition_is_not_silently_removed(self):
        payload = {"context_records": {"schema": {"X": {"version": 1}}},
            "context_result": {"kind": "schema", "records": {"X": {"version": 2}}}}
        self.assertEqual(compact_context(payload), payload)

    def test_aliased_record_maps_keep_canonical_evidence(self):
        records = {"Entity": {"fields": {"id": "integer"}}}
        payload = {"context_records": {"schema": records},
            "context_result": {"kind": "schema", "records": records}}
        packed = compact_context(payload)
        self.assertEqual(packed["context_records"]["schema"], records)
        self.assertIn("Entity", payload["context_result"]["records"])

    def test_pinned_exact_excerpt_deduplicated_but_distinct_evidence_retained(self):
        excerpt = {"start_line": 2, "end_line": 2, "total_lines": 3, "content": "second\n"}
        payload = {"files": {"a.ts": {"content": "first\nsecond\nthird\n", "writable": False}},
            "read_files": {"a.ts": [excerpt], "b.ts": [excerpt]}}
        result = compact_context(payload)
        self.assertEqual(result["files"], payload["files"])
        self.assertNotIn("a.ts", result["read_files"])
        self.assertEqual(result["read_files"]["b.ts"], [excerpt])
        payload["read_files"]["a.ts"][0]["content"] = "different\n"
        self.assertIn("a.ts", compact_context(payload)["read_files"])

    def test_empty_and_non_agent_payloads_are_unchanged(self):
        for payload in ({}, {"entities": {}}, {"files": ["a.ts"]}, {"requirement": "x" * 190000}):
            self.assertEqual(compact_context(payload), payload)

    def test_transport_uses_compacted_copy_and_baseline_switch_restores_original(self):
        definition = {"description": "source evidence " * 300}
        payload = {"context_records": {"api": {"API-A": definition}},
            "context_result": {"kind": "api", "records": {"API-A": definition}}}
        for profile in ("b0", "b1"):
            with self.subTest(profile=profile), patch.dict("os.environ", {"ARC_AGENT_PROFILE": profile}, clear=True):
                model = TextModel.__new__(TextModel)
                model.reasoning = "provider"
                model.name = "test"
                model._request = Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(
                    finish_reason="stop", message=SimpleNamespace(content='{"ok": true}'))]))
                self.assertEqual(model.generate_json("original instructions", payload), {"ok": True})
                messages = model._request.call_args.kwargs["messages"]
                sent = json.loads(messages[1]["content"])
                self.assertEqual(sent, compact_context(payload) if profile == "b1" else payload)
                self.assertIn("original instructions", messages[0]["content"])
                self.assertIn("API-A", payload["context_result"]["records"])

    def test_restricted_read_scope_is_advertised_without_expanding_it(self):
        with TemporaryDirectory() as directory, patch.dict("os.environ", {"ARC_AGENT_PROFILE": "b1"}, clear=True):
            root = Path(directory)
            tools = FileTools(root, readable=["allowed.ts"])
            model = Mock(generate_json=Mock(return_value={"tool_calls": []}))
            gate = Mock(return_value={"green": True})
            with patch("infrastructure.shared.agent.loop.checkpoint"):
                run_file_agent(model, "", {}, tools, gate, 1, Mock(), "restricted")
            sent = model.generate_json.call_args.args[1]
            self.assertEqual(sent["file_access"]["readable_paths"], ["allowed.ts"])
            self.assertEqual(tools.readable, {"allowed.ts"})
            gate.assert_called_once()

    def test_telemetry_records_sizes_without_context_or_credentials(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            session = {"output": root, "stage": "test-stage", "lock": RLock()}
            with patch("infrastructure.utils.presentation.logging.session_info", return_value=session):
                record_context_sizes({"content": "private-marker"}, {"content": "short"})
            text = (root / ".arc/b1_context.jsonl").read_text(encoding="utf-8")
            record = json.loads(text)
            self.assertNotIn("private-marker", text)
            self.assertEqual(record["stage"], "test-stage")
            self.assertEqual(record["saved_chars"], len("private-marker") - len("short"))


class FailFastTests(unittest.TestCase):
    def report(self, root, profile, failed=False):
        suite = "frontend/tests/e2e/check.spec.ts"
        stats = {"expected": 0 if failed else 3, "unexpected": 1 if failed else 0,
            "skipped": 2 if failed else 0, "flaky": 0}
        checks = E2EChecks(root)
        checks.execute = Mock(return_value={"returncode": 1 if failed else 0,
            "output": "", "stdout": json.dumps({"suites": [], "stats": stats})})
        with patch.dict("os.environ", {"ARC_AGENT_PROFILE": profile}, clear=True):
            result = checks.tests([suite])
        return result, checks.execute.call_args.args[0]

    def test_failure_stops_early_but_is_never_green(self):
        with TemporaryDirectory() as directory:
            result, command = self.report(Path(directory), "b1", failed=True)
            self.assertIn("--max-failures=1", command)
            self.assertEqual(result["skipped"], 2)
            with self.assertRaises(ValueError):
                require_acceptance(result)

    def test_all_pass_runs_full_suite_and_baseline_has_no_limit(self):
        with TemporaryDirectory() as directory:
            for profile in ("b0", "b1"):
                result, command = self.report(Path(directory), profile)
                self.assertEqual("--max-failures=1" in command, profile == "b1")
                self.assertEqual(result["passed"], 3)
                require_acceptance(result)

    def test_skips_without_failures_still_cannot_be_accepted(self):
        with self.assertRaises(ValueError):
            require_acceptance({"returncode": 0, "passed": 2, "failed": 0, "skipped": 1})

    def test_feature_switches_support_ablation_and_reject_invalid_config(self):
        with patch.dict("os.environ", {"ARC_AGENT_PROFILE": "b1", "ARC_B1_FAIL_FAST": "0"}, clear=True):
            self.assertFalse(enabled("fail_fast"))
            self.assertTrue(enabled("context_reuse"))
        with patch.dict("os.environ", {"ARC_AGENT_PROFILE": "typo"}, clear=True):
            with self.assertRaises(ValueError):
                enabled("context_reuse")


if __name__ == "__main__":
    unittest.main()
