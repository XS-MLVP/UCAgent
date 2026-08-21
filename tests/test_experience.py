# -*- coding: utf-8 -*-

import os
import sys
import tempfile
import unittest

import yaml

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.experience import ExperienceAccumulator, StageExperience


class TestExperienceAccumulator(unittest.TestCase):
    def _make_accumulator(self, log_text="", prior_rules=None):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        log_path = os.path.join(temp_dir.name, "stage.log")
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write(log_text)
        return ExperienceAccumulator(
            workspace=temp_dir.name,
            log_path=log_path,
            prior_rules=prior_rules or [],
        )

    def test_audit_requires_checker_context_and_honors_checker_filter(self):
        log_text = """
Task description: [Parse Error] is only an example in the task prompt.
Tool Calls:
  Check (call-1)
Tool Result:
- name: RandomTestCasesChecker
  count_fail: 1
  error: [Parse Error] checker failure
"""
        rule = {
            "id": "parse_error",
            "patterns": ["[Parse Error]"],
            "checkers": ["UnityChipCheckerTestCase"],
        }
        accumulator = self._make_accumulator(log_text, [rule])

        audit = accumulator.audit_prior_rules()

        self.assertEqual(audit["matched_rules"], [])
        self.assertEqual(len(audit["unmatched_rules"]), 1)

        matching_rule = dict(rule, checkers=["RandomTestCasesChecker"])
        accumulator = self._make_accumulator(log_text, [matching_rule])
        audit = accumulator.audit_prior_rules()
        self.assertEqual(len(audit["matched_rules"]), 1)
        self.assertEqual(audit["matched_rules"][0]["hit_count"], 1)
        self.assertEqual(audit["matched_rules"][0]["hits"][0]["line"], "8")
        self.assertFalse(
            accumulator._rule_matches_failure_event(
                {"patterns": ["[Parse Error]"]},
                {"event_type": "failure", "signature": "[Parse Error]", "excerpt": ""},
            )
        )

    def test_triggered_fallback_rejects_orphan_keywords(self):
        orphan = self._make_accumulator("Task text mentions [Parse Error] without a tool call.\n")
        self.assertEqual(orphan.extract_failure_events(), [])

        stale_context = self._make_accumulator(
            "Tool Calls:\n  Check (old-call)\n"
            "Tool Calls:\n  RunTestCases (new-call)\n"
            "[Parse Error] test output, not checker output\n"
        )
        self.assertEqual(stale_context.extract_failure_events(), [])

        contextual = self._make_accumulator(
            "Tool Calls:\n  Check (call-1)\n[Parse Error] checker failure\n"
        )
        events = contextual.extract_failure_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "failure")

    def test_audit_matches_custom_checker_error_inside_valid_checker_block(self):
        log_text = """
Tool Calls:
  Check (call-1)
- name: CustomChecker
  error: custom invariant violated
"""
        accumulator = self._make_accumulator(log_text, [{
            "id": "custom_invariant",
            "patterns": ["custom invariant violated"],
            "checkers": ["CustomChecker"],
        }])

        audit = accumulator.audit_prior_rules()

        self.assertEqual(len(audit["matched_rules"]), 1)
        self.assertEqual(audit["matched_rules"][0]["hit_count"], 1)

    def test_structured_events_prefer_specific_error_over_count_fail(self):
        log_text = """
Tool Calls:
  Check (call-1)
- name: UnityChipCheckerBatchTestsImplementation
  count_fail: 3
  error: '[Missing Assertions] The listed tests do not contain assert statements.'
Tool Calls:
  Check (call-2)
- name: UnityChipCheckerTestCase
  count_fail: 1
  error: '[Confidence Parse Error] BG label confidence must be an integer.'
"""
        accumulator = self._make_accumulator(log_text)

        events = accumulator.extract_failure_events()

        self.assertEqual(len(events), 2)
        self.assertIn("[Missing Assertions]", events[0]["signature"])
        self.assertEqual(accumulator._failure_family_key(events[0]), "missing_assertions")
        self.assertIn("[Confidence Parse Error]", events[1]["signature"])
        self.assertEqual(accumulator._failure_family_key(events[1]), "confidence_parse_error")

    def test_low_value_count_without_specific_error_is_not_an_event(self):
        log_text = """
Tool Calls:
  Check (call-1)
- name: UnityChipCheckerTestCase
  count_fail: 4
  error:
    - '[Solution]'
"""
        accumulator = self._make_accumulator(log_text)

        self.assertEqual(accumulator.extract_failure_events(), [])

    def test_bug_stage_keeps_safe_artifacts_and_source_but_not_bug_details(self):
        accumulator = self._make_accumulator()
        stage = StageExperience(
            index=23,
            title="comprehensive_verification_and_bug_analysis",
            score=12,
            fail_count=2,
            is_completed=True,
            is_skipped=False,
            changed_files={
                "unity_test/DUT_bug_analysis.md": "modified",
                "unity_test/tests/test_behavior.py": "modified",
            },
            journal="""
- Checker workflow was completed after targeted validation.
- Root cause was in dut.v line 12.
""",
            has_changes=True,
            categories={"bug analysis", "test implementation"},
        )

        rendered = accumulator.render_verification_experience([stage])

        self.assertIn("`unity_test/tests/test_behavior.py` (modified)", rendered)
        self.assertNotIn("DUT_bug_analysis.md", rendered)
        self.assertIn("stage 23: comprehensive_verification_and_bug_analysis", rendered)
        self.assertNotIn("Root cause was in dut.v", rendered)

    def test_general_rules_cover_reviewed_checker_families(self):
        general_path = os.path.join(
            current_dir,
            "..",
            "ucagent",
            "lang",
            "zh",
            "experience",
            "general.yaml",
        )
        with open(general_path, "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
        rules = {
            rule["id"]: rule
            for rule in payload["experience"]["candidate_failure_hints"]
        }

        self.assertIn(
            "UnityChipCheckerBatchTestsImplementation",
            rules["test_case_missing_assertions"]["checkers"],
        )
        self.assertIn(
            "UnityChipCheckerTestCase",
            rules["bug_confidence_suffix_parse_error"]["checkers"],
        )
        self.assertIn("21", rules["essential_checkpoint_missing"]["stages"])
        self.assertIn(
            "UnityChipCheckerTestTemplate",
            rules["essential_checkpoint_missing"]["checkers"],
        )

    def test_general_failure_attribution_requires_independent_dut_neutral_evidence(self):
        general_path = os.path.join(
            current_dir,
            "..",
            "ucagent",
            "lang",
            "zh",
            "experience",
            "general.yaml",
        )
        with open(general_path, "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

        rules = {
            rule["id"]: rule
            for rule in payload["experience"]["candidate_failure_hints"]
        }
        undocumented_hint = rules["undocumented_failed_cases"]["hint"]
        for classification in (
            "TEST_ERROR",
            "API_ENV_ERROR",
            "DUT_BUG",
            "UNRESOLVED",
        ):
            self.assertIn(classification, undocumented_hint)
        self.assertIn("独立推导预期", undocumented_hint)
        self.assertIn("不得把测试中已有的 expected 表达式当作正确性证据", undocumented_hint)

        injected_text = "\n".join(
            [
                str(value)
                for key, value in payload.items()
                if key.startswith("stage[")
            ]
            + [
                "\n".join(
                    [str(rule.get("hint", ""))]
                    + [
                        str(item)
                        for item in rule.get("source", {}).get("evidence", [])
                    ]
                )
                for rule in rules.values()
            ]
        ).lower()
        for instance_token in ("adder", "fifo", "ifu", "lsu", "e203"):
            self.assertNotIn(instance_token, injected_text)
        self.assertNotRegex(injected_text, r"\b(?:0x[0-9a-f]+|0b[01]+|\d+'[bdho][0-9a-fx_z]+)\b")

    def test_adder_overlay_only_enables_general_experience_hooks(self):
        overlay_path = os.path.join(
            current_dir,
            "..",
            "ucagent",
            "lang",
            "zh",
            "experience",
            "adder.yaml",
        )
        with open(overlay_path, "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

        self.assertEqual(payload["include"], ["general.yaml"])
        self.assertNotIn("experience", payload)
        self.assertFalse(any(key.endswith(".task") for key in payload))
        hook_overrides = {
            key: value
            for key, value in payload.items()
            if key.endswith(".experience-hook")
        }
        self.assertTrue(hook_overrides)
        self.assertTrue(all(hook_overrides.values()))

    def test_recovery_ignores_later_checker_failure(self):
        accumulator = self._make_accumulator()
        events = [
            {
                "checker": "UnityChipCheckerA",
                "event_type": "failure",
                "signature": "error: first",
            },
            {
                "checker": "UnityChipCheckerB",
                "event_type": "failure",
                "signature": "error: later",
            },
        ]
        self.assertIsNone(accumulator._next_meaningful_recovery_event(events, 1))
        result = "next_checker_result: later_checker_failure; UnityChipCheckerB / family / error"
        self.assertIn(
            "not confirmed",
            accumulator._infer_likely_effective_step(["edit generic artifact"], result, "generic"),
        )

    def test_recovery_action_window_reaches_same_checker_after_other_checker(self):
        accumulator = self._make_accumulator()
        lines = [
            "Tool Calls:",
            "  Check (first)",
            "- name: UnityChipCheckerA",
            "error: [Parse Error] first",
            "Tool Calls:",
            "  EditTextFile (change-a)",
            "  path: guide_doc/a.md",
            "- name: UnityChipCheckerB",
            "error: Validation failed",
            "Tool Calls:",
            "  EditTextFile (change-after-other)",
            "  path: guide_doc/b.md",
            "- name: UnityChipCheckerA",
            "error: Validation failed",
        ]
        events = [
            {
                "checker": "UnityChipCheckerA",
                "event_type": "failure",
                "signature": "error: [Parse Error] first",
                "_log_index": "3",
                "_action_start_index": "4",
            },
            {
                "checker": "UnityChipCheckerB",
                "event_type": "failure",
                "signature": "error: Validation failed",
                "_log_index": "8",
                "_action_start_index": "9",
            },
            {
                "checker": "UnityChipCheckerA",
                "event_type": "failure",
                "signature": "error: Validation failed",
                "_log_index": "13",
                "_action_start_index": "14",
            },
        ]

        accumulator._attach_stage_action_trace(events, lines, set())

        self.assertIn("change-after-other", events[0]["actions_after_failure"])
        self.assertIn("same_checker_changed_result", events[0]["actions_after_failure"])

    def test_llm_hint_removes_instance_details_and_keeps_valid_checkers(self):
        accumulator = self._make_accumulator()
        raw = {
            "id": "generic_validation_recovery",
            "hint": "先依据 checker 的稳定错误文本核对最小 artifact 关系，再重新执行 checker。",
            "patterns": ["Validation failed"],
            "checkers": ["RandomTestCasesChecker", "FilesMustNotExist", "not_a_checker"],
            "source": {
                "evidence": [
                    "测试在 test_specific.py 第 12 行出现失败",
                    "checker 报告了稳定的 Validation failed 文本",
                ]
            },
        }

        hint = accumulator._normalize_llm_hint(raw)

        self.assertIsNotNone(hint)
        self.assertEqual(hint["checkers"], ["RandomTestCasesChecker", "FilesMustNotExist"])
        self.assertEqual(hint["source"]["evidence"], ["checker 报告了稳定的 Validation failed 文本"])

        raw["hint"] = "请修复 test_specific.py 第 12 行并重新运行 checker。"
        self.assertIsNone(accumulator._normalize_llm_hint(raw))

        raw["hint"] = "请先核对 checker 报告，再重新执行验证。"
        raw["source"]["evidence"] = ["第 12 行需要修复", "Validation failed"]
        hint = accumulator._normalize_llm_hint(raw)
        self.assertEqual(hint["source"]["evidence"], [])

        raw["hint"] = "Inspect the checker result and rerun validation carefully."
        self.assertIsNone(accumulator._normalize_llm_hint(raw))

        raw["hint"] = "当 dut 的 checker 出现稳定错误时，先核对最小 artifact 关系再重试。"
        raw["patterns"] = ["Validation failed for dut"]
        hint = accumulator._normalize_llm_hint(raw)
        self.assertEqual(hint["patterns"], ["Validation failed for {DUT}"])

    def test_llm_distill_uses_same_checker_recovery_trajectory(self):
        class StaticModel:
            def __init__(self):
                self.input = None

            def invoke(self, model_input, config=None):
                self.input = model_input
                return """
experience:
  candidate_failure_hints:
    - id: custom_validation_recovery
      patterns:
        - Validation failed
      checkers:
        - CustomChecker
      hint: checker 报告稳定的 Validation failed 时，先核对最小 artifact 关系再重新验证，不要修改无关实现。
      source:
        evidence:
          - 同一 checker 复验后结果变化，说明应优先处理该稳定错误。
"""

        log_text = """
Tool Calls:
  Check (call-1)
- name: CustomChecker
  count_fail: 1
  error: Validation failed: first condition
Tool Calls:
  EditTextFile (change-1)
  path: guide_doc/checks.md
Tool Calls:
  Check (call-2)
- name: CustomChecker
  count_fail: 1
  error: Validation failed: second condition
"""
        model = StaticModel()
        accumulator = self._make_accumulator(log_text)
        accumulator.llm_model = model
        os.makedirs(accumulator.out_dir, exist_ok=True)

        hints = accumulator.distill_failure_hints_with_llm()

        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["checkers"], ["CustomChecker"])
        prompt = model.input[-1].content if isinstance(model.input, list) else model.input
        self.assertIn("same_checker_changed_result", prompt)


if __name__ == "__main__":
    unittest.main()
