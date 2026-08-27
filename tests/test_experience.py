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

    def test_scoped_log_reconstructs_stage_across_multiple_rotations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = os.path.join(temp_dir, "stage.log")
            original = b"before-stage\nstage-start\n"
            middle_one = b"after-first-rotation\n"
            middle_two = b"after-second-rotation\n"
            active = b"stage-end\n"
            with open(f"{log_path}.3", "wb") as handle:
                handle.write(original)
            with open(f"{log_path}.2", "wb") as handle:
                handle.write(middle_one)
            with open(f"{log_path}.1", "wb") as handle:
                handle.write(middle_two)
            with open(log_path, "wb") as handle:
                handle.write(active)
            stat = os.stat(f"{log_path}.3")
            accumulator = ExperienceAccumulator(
                workspace=temp_dir,
                log_path=log_path,
                target_stage_index=22,
                log_start_offset=len(b"before-stage\n"),
                log_end_offset=len(active),
                log_start_identity={"dev": stat.st_dev, "ino": stat.st_ino},
            )

            text, line_base, scope = accumulator._read_scoped_log(max_bytes=4096)

        self.assertEqual(
            text,
            "stage-start\nafter-first-rotation\nafter-second-rotation\nstage-end\n",
        )
        self.assertEqual(line_base, 2)
        self.assertEqual(scope["rotation_count"], 3)
        self.assertEqual(scope["resolved_log_paths"], [
            f"{log_path}.3",
            f"{log_path}.2",
            f"{log_path}.1",
            log_path,
        ])

    def test_scoped_log_uses_identity_after_rotation_when_active_log_grows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = os.path.join(temp_dir, "stage.log")
            prefix = b"before-stage\n"
            old_stage_data = b"stage-before-rotation\n"
            active_stage_data = b"stage-after-rotation-a\nstage-after-rotation-b\n"
            with open(f"{log_path}.1", "wb") as handle:
                handle.write(prefix + old_stage_data)
            stat = os.stat(f"{log_path}.1")
            with open(log_path, "wb") as handle:
                handle.write(active_stage_data)
            self.assertGreater(len(active_stage_data), len(prefix))
            accumulator = ExperienceAccumulator(
                workspace=temp_dir,
                log_path=log_path,
                target_stage_index=22,
                log_start_offset=len(prefix),
                log_end_offset=len(active_stage_data),
                log_start_identity={"dev": stat.st_dev, "ino": stat.st_ino},
            )

            text, _line_base, scope = accumulator._read_scoped_log(max_bytes=4096)

        self.assertEqual(text, (old_stage_data + active_stage_data).decode("utf-8"))
        self.assertEqual(scope["resolved_log_paths"], [f"{log_path}.1", log_path])

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
        self.assertIn(
            "create_test_case_templates",
            rules["essential_checkpoint_missing"]["stages"],
        )
        self.assertIn(
            "UnityChipCheckerTestTemplate",
            rules["essential_checkpoint_missing"]["checkers"],
        )
        self.assertIn(
            "[Bug Checkpoint Association Missing]",
            rules["dynamic_bug_checkpoint_association_convergence"]["patterns"],
        )
        self.assertIn(
            "[Waveform Record Anchor Error]",
            rules["dynamic_bug_container_anchor_minimal_repair"]["patterns"],
        )
        repair_hint = rules["dynamic_bug_evidence_repair_order"]["hint"]
        self.assertIn("每个失败 TC", repair_hint)
        self.assertIn("唯一中央记录", repair_hint)
        self.assertIn("test_case_tag", repair_hint)
        self.assertIn(
            "UnityChipCheckerDutApiTest",
            rules["dynamic_bug_evidence_repair_order"]["checkers"],
        )
        self.assertIn(
            "basic_api_functional_test",
            rules["dynamic_bug_evidence_repair_order"]["stages"],
        )

        self.assertIn("不以增加 CK 数量为目标", payload["stage[3].task"])
        self.assertIn("test_case_tag 禁止为空", payload["stage[11].task"])

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

    def test_mcp_log_checker_context_and_action_trace(self):
        log_text = """
2026-08-26 14:58:16,809 - ucagent-log - INFO - ToolComplete:
failure_summary:
  status: checker_failed
  stage_index: 22
  stage_name: basic_api_functional_test
  failed_checker_name: api_test_check
  failed_checker_class: UnityChipCheckerDutApiTest
  error_code: UNRESOLVED_FAILED_CASES
  error:
  - '[Unresolved Failed Cases] Found 4 failed test case(s) without a confirmed DUT Bug record: test_api_Adder_add_carry_chain'
check_pass: false
check_info:
- name: FilesMustNotExist
  checker_class: FilesMustNotExist
  last_check_pass: true
  count_pass: 1
  count_fail: 0
- name: UnityChipCheckerDutApiTest
  checker_class: UnityChipCheckerDutApiTest
  last_check_pass: false
  last_msg:
    error:
    - '[Unresolved Failed Cases] Found 4 failed test case(s) without a confirmed DUT Bug record: test_api_Adder_add_carry_chain'
2026-08-26 14:58:59,425 - ucagent-log - INFO - call WaveInfo in Stream-MPC mode
2026-08-26 14:59:50,995 - ucagent-log - INFO - call ApplyWaveInfoEvidence in Stream-MPC mode
2026-08-26 15:05:19,478 - ucagent-log - INFO - call ToolDoComplete in Stream-MPC mode
2026-08-26 15:05:19,500 - ucagent-log - INFO - ToolComplete:
complete: true
message: 'Stage 22 completed successfully.'
last_check_result:
  check_pass: true
  check_info:
  - name: UnityChipCheckerDutApiTest
    last_check_pass: true
"""
        accumulator = self._make_accumulator(log_text)
        events = accumulator.extract_failure_events()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["checker"], "UnityChipCheckerDutApiTest")
        self.assertIn("[Unresolved Failed Cases]", events[0]["signature"])
        self.assertEqual(accumulator._failure_family_key(events[0]), "unresolved_failed_cases")

        all_events, selected_cases, report = accumulator.build_recovery_trajectory_report()
        self.assertEqual(len(all_events), 1)
        self.assertEqual(len(selected_cases), 1)
        self.assertIn("WaveInfo", report)
        self.assertIn("ApplyWaveInfoEvidence", report)


if __name__ == "__main__":
    unittest.main()
