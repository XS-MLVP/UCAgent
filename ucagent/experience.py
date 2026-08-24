# -*- coding: utf-8 -*-
"""Accumulate reusable UCAgent experience from structured run records.

The accumulator treats ``.ucagent/ucagent_info.json`` and ``.ucagent/history``
as the primary source of truth for stage artifacts. Logs are used only within
the requested stage slice to audit configured hints and distill uncovered
checker failure signatures.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import os
import re
import subprocess
import time
from typing import Any

import yaml

from ucagent.util import functions as fc
from ucagent.util.log import info, warning


BUG_LEAK_PATTERNS = (
    re.compile(r"\b[A-Za-z0-9_./\\-]+\.(?:v|sv|svh|vh)\b", re.I),
    re.compile(r"\bline\s*\d+\b", re.I),
    re.compile(r"\bBUG\b|\bFIX\b|root\s*cause|defect|bug\s*#", re.I),
    re.compile(r"\b(?:WIDTH|XData|assign|output|input|wire|sum|cout)\b", re.I),
    re.compile(r"\b0x[0-9a-f_]+\b", re.I),
    re.compile(r"\b(?:expected|actual|should\s+be|failure|failed)\b", re.I),
    re.compile(r"<BG-[^>]+>|<BG-STATIC-[^>]+>|<LINK-BUG-[^>]+>"),
)

BUG_RELATED_FILES = (
    "bug_analysis.md",
    "static_bug_analysis.md",
    "test_summary.md",
)

REUSABLE_ARTIFACT_PATTERNS = (
    "functions_and_checks.md",
    "_api.py",
    "_bundle_def.py",
    "_function_coverage_def.py",
    "test_",
)

LLM_HINT_REJECT_PATTERNS = (
    re.compile(r"\b[A-Za-z0-9_./\\-]+\.(?:v|sv|svh|vh)\b", re.I),
    re.compile(r"\b(?:verilog|systemverilog|rtl)\b", re.I),
    re.compile(r"\b(?:WIDTH|assign|wire|input|output|sum|cout|port\s+width)\b", re.I),
    re.compile(r"\b0x[0-9a-f_]+\b", re.I),
    re.compile(r"\broot\s*cause\b|\bconcrete\s+(?:bug\s+)?fix\b", re.I),
    re.compile(r"\bupdate\s+(?:the\s+)?checker\s+(?:configuration|config)\b", re.I),
    re.compile(r"\bfalse\s+positive\b|\balready\s+implemented\s+and\s+failing\b", re.I),
    re.compile(r"\bRunTestCases\b.{0,100}\b(?:0\s+fails|fails:\s*0)\b", re.I),
    re.compile(r"\buntil\s+RunTestCases\s+shows\s+0\s+fails\b", re.I),
)

LLM_TEMPLATE_HINT_REJECT_PATTERNS = (
    re.compile(r"\bexpected_failure\b", re.I),
    re.compile(r"\bdecorator\b", re.I),
    re.compile(r"\bregister(?:ed|ing)?\b", re.I),
    re.compile(r"_template`?\s+suffix", re.I),
    re.compile(r"renam(?:e|ing).{0,80}_template", re.I),
    re.compile(r"recognized\s+as\s+a\s+template", re.I),
    re.compile(r"not\s+run\s+as\s+a\s+normal\s+test", re.I),
    re.compile(r"do\s+not\s+just\s+add\s+assert\s+false", re.I),
    re.compile(r"required\s+convention", re.I),
)

CHECKER_NAME_PATTERN = r"(?:[A-Za-z0-9_]*Checker[A-Za-z0-9_]*|FilesMustNotExist)"

@dataclass
class StageExperience:
    index: int
    title: str
    score: int
    fail_count: int
    is_completed: bool
    is_skipped: bool
    changed_files: dict[str, str] = field(default_factory=dict)
    journal: str = ""
    commit_hash: str = ""
    has_changes: bool = False
    categories: set[str] = field(default_factory=set)


class ExperienceAccumulator:
    """Build reusable experience artifacts for a completed or partial run."""

    def __init__(
        self,
        workspace: str,
        dut_name: str | None = None,
        log_path: str | None = None,
        out_dir: str | None = None,
        prior_rule_audit: bool = False,
        llm_distill: bool = False,
        llm_model: Any | None = None,
        llm_max_events: int = 20,
        prior_rules: list[Any] | None = None,
        target_stage_index: int | None = None,
        target_stage_name: str | None = None,
        stage_task_info: Any | None = None,
        log_start_offset: int | None = None,
        log_end_offset: int | None = None,
        log_start_identity: dict[str, int] | None = None,
        lang: str = "zh",
    ) -> None:
        self.workspace = os.path.abspath(workspace)
        self.history_dir = fc.get_abs_path_cwd_ucagent(self.workspace, "history")
        self.info_path = fc.get_abs_path_cwd_ucagent(self.workspace, "ucagent_info.json")
        self.ucagent_info = fc.load_ucagent_info(self.workspace)
        self.dut_name = dut_name or self.ucagent_info.get("dut_name") or self.ucagent_info.get("DUT") or "DUT"
        self.log_path = os.path.abspath(log_path) if log_path else self._find_default_log()
        self.out_dir = self._resolve_out_dir(out_dir)
        self.prior_rule_audit = prior_rule_audit
        self.llm_distill = llm_distill
        self.llm_model = llm_model
        self.llm_max_events = max(1, int(llm_max_events or 20))
        self.prior_rules = self._normalize_rules(prior_rules or [])
        self.target_stage_index = self._safe_int(target_stage_index, -1) if target_stage_index is not None else None
        self.target_stage_name = str(target_stage_name or "")
        self.target_stage_status = self._target_stage_status()
        self.stage_task_info = stage_task_info
        self.log_start_offset = self._safe_int(log_start_offset, 0) if log_start_offset is not None else None
        self.log_end_offset = self._safe_int(log_end_offset, 0) if log_end_offset is not None else None
        self.log_start_identity = self._normalize_log_identity(log_start_identity)
        self.lang = str(lang or "zh")
        self.llm_raw_output_path: str | None = None
        self.uncovered_failure_events: list[dict[str, str]] = []
        self.uncovered_failure_event_total = 0

    def accumulate(self) -> dict[str, Any]:
        os.makedirs(self.out_dir, exist_ok=True)
        stages = self.collect_stage_experience()
        prior_rule_audit = self.audit_prior_rules() if self.prior_rule_audit else self._empty_prior_rule_audit()
        llm_failure_hints = self.distill_failure_hints_with_llm() if self.llm_distill else []

        written: dict[str, str] = {}
        written["verification_experience"] = self._write_text(
            f"{self.dut_name}_verification_experience.md",
            self.render_verification_experience(stages),
        )
        if self.prior_rule_audit:
            written["prior_rule_audit"] = self._write_text(
                f"{self.dut_name}_prior_rule_audit.yaml",
                self.render_prior_rule_audit(prior_rule_audit),
            )
        if self.llm_raw_output_path:
            written["llm_raw_output"] = self.llm_raw_output_path
        if self.llm_distill and self.llm_raw_output_path:
            written["llm_failure_hints"] = self._write_text(
                f"{self.dut_name}_llm_failure_hints.yaml",
                self.render_failure_hints(llm_failure_hints),
            )

        index_payload = self._build_index(stages, prior_rule_audit, llm_failure_hints, written)
        index_path = os.path.join(self.out_dir, "index.json")
        self._write_json(index_path, index_payload)
        written["index"] = index_path
        info(f"Experience artifacts saved to {self.out_dir}")
        return {
            "workspace": self.workspace,
            "dut_name": self.dut_name,
            "out_dir": self.out_dir,
            "stage_count": len(stages),
            "prior_rule_hit_count": len(prior_rule_audit.get("matched_rules", [])),
            "prior_rule_total_hit_count": sum(
                self._safe_int(rule.get("hit_count", 0), 0)
                for rule in prior_rule_audit.get("matched_rules", [])
            ),
            "failure_hint_count": len(prior_rule_audit.get("matched_rules", [])),
            "uncovered_failure_event_count": self.uncovered_failure_event_total,
            "llm_distill_event_count": len(self.uncovered_failure_events),
            "llm_failure_hint_count": len(llm_failure_hints),
            "written": written,
        }

    def collect_stage_experience(self) -> list[StageExperience]:
        raw_stages = self.ucagent_info.get("stages_info", {})
        if not isinstance(raw_stages, dict):
            return []
        collected = []
        for key, raw_stage in sorted(raw_stages.items(), key=lambda item: self._safe_int(item[0], 0)):
            if not isinstance(raw_stage, dict):
                continue
            stage_index = self._safe_int(key, 0)
            if self.target_stage_index is not None and stage_index != self.target_stage_index:
                continue
            stage = self._stage_from_info(stage_index, raw_stage)
            if self.target_stage_index is not None or stage.score >= 4:
                collected.append(stage)
        return collected

    def audit_prior_rules(self) -> dict[str, Any]:
        audit = self._empty_prior_rule_audit()
        audit["rule_count"] = len(self.prior_rules)
        if not self.log_path or not os.path.isfile(self.log_path):
            return audit
        try:
            text, line_base, scope = self._read_scoped_log(max_bytes=4_000_000)
        except OSError as exc:
            warning(f"Failed to read experience log {self.log_path}: {exc}")
            return audit

        audit["scope"].update(scope)
        for rule in self.prior_rules:
            if not self._safe_bool(rule.get("enabled", True), True):
                audit["skipped_rules"].append(self._audit_rule_summary(rule, reason="disabled"))
                continue
            if not self._rule_applies_to_stage(rule):
                audit["skipped_rules"].append(self._audit_rule_summary(rule, reason="stage_not_matched"))
                continue
            matches = self._match_rule(rule, text, line_base=line_base)
            if not matches:
                audit["unmatched_rules"].append(self._audit_rule_summary(rule))
                continue
            item = self._audit_rule_summary(rule)
            item["hit_count"] = len(matches)
            item["hits"] = matches[:20]
            audit["matched_rules"].append(item)
        audit["matched_rules"].sort(key=lambda item: item.get("priority", 100))
        audit["unmatched_rules"].sort(key=lambda item: item.get("priority", 100))
        audit["skipped_rules"].sort(key=lambda item: item.get("priority", 100))
        self.uncovered_failure_events = self.extract_failure_events(
            max_events=self.llm_max_events,
            uncovered_only=True,
        )
        audit["prior_rule_total_hit_count"] = sum(
            self._safe_int(rule.get("hit_count", 0), 0)
            for rule in audit["matched_rules"]
        )
        audit["uncovered_failure_event_count"] = self.uncovered_failure_event_total
        audit["llm_distill_event_count"] = len(self.uncovered_failure_events)
        audit["uncovered_failure_events"] = [
            {
                "line": event.get("line", ""),
                "signature": event.get("signature", ""),
            }
            for event in self.uncovered_failure_events
        ]
        return audit

    def distill_failure_hints_with_llm(self) -> list[dict[str, Any]]:
        if self.llm_model is None:
            warning("Experience LLM distill is enabled, but no model is available.")
            return []
        all_events, selected_events, formatted_events = self.build_recovery_trajectory_report(
            max_events=self.llm_max_events,
        )
        if not all_events:
            info("No checker failure events found for LLM experience distill.")
            return []
        if not formatted_events.strip():
            info("No high-confidence checker evidence found for LLM experience distill.")
            return []
        system_prompt, user_prompt_template = self._load_distill_prompts()
        prompt = user_prompt_template.format(
            stage_index=str(self.target_stage_index) if self.target_stage_index is not None else "",
            stage_task=self._format_stage_task_info(),
            events=formatted_events,
        )
        try:
            try:
                from langchain_core.messages import HumanMessage, SystemMessage
                model_input = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=prompt),
                ]
            except ImportError:
                model_input = system_prompt + "\n\n" + prompt
            response = self._invoke_distill_model(model_input)
            content = self._message_content_to_text(response).strip()
            if content:
                self.llm_raw_output_path = self._write_text(
                    f"{self.dut_name}_llm_failure_hints.raw.txt",
                    content + "\n",
                )
            parsed_hints = self._parse_llm_hint_yaml(content)
            hints = self._filter_llm_hints_against_prior_rules(parsed_hints, all_events)
        except Exception as exc:
            warning(f"Failed to distill experience with LLM: {exc}")
            return []
        if hints:
            info(f"LLM distilled {len(hints)} candidate experience hint(s).")
        elif parsed_hints:
            info(
                "LLM produced candidate experience hint(s), but all were covered "
                "by existing prior rules or post-filtered."
            )
        else:
            info("LLM did not produce valid candidate experience hints.")
        return hints

    def build_recovery_trajectory_report(
        self,
        max_events: int = 20,
    ) -> tuple[list[dict[str, str]], list[dict[str, str]], str]:
        """Return full events, selected events, and a compact recovery report.

        The LLM should reason over a failure-to-success trajectory, not just a
        bag of checker snippets. We therefore extract a broad stage timeline
        first, then select representative events while preserving the first
        failure, signature/result changes, and terminal progress/outcome.
        """
        broad_limit = max(max_events * 8, 200)
        all_events = self.extract_failure_events(max_events=broad_limit, uncovered_only=False)
        if not all_events:
            return [], [], ""
        selected_events, omitted_count = self._select_recovery_timeline_events(
            all_events,
            max_events=max_events,
        )
        return (
            all_events,
            selected_events,
            self._format_recovery_trajectory(
                selected_events,
                total_events=len(all_events),
                omitted_count=omitted_count,
            ),
        )

    def _invoke_distill_model(self, model_input: Any) -> Any:
        with self._without_msg_logger():
            try:
                return self.llm_model.invoke(model_input, config={"callbacks": []})
            except TypeError as exc:
                text = str(exc)
                if "config" not in text and "unexpected keyword" not in text:
                    raise
                return self.llm_model.invoke(model_input)

    @contextmanager
    def _without_msg_logger(self):
        import ucagent.util.log as log_module

        old_msg_logger = getattr(log_module, "__msg_logger__", None)
        try:
            setattr(log_module, "__msg_logger__", None)
            yield
        finally:
            setattr(log_module, "__msg_logger__", old_msg_logger)

    def extract_failure_events(
        self,
        max_events: int = 20,
        uncovered_only: bool = False,
    ) -> list[dict[str, str]]:
        if not self.log_path or not os.path.isfile(self.log_path):
            return []
        try:
            text, line_base, _scope = self._read_scoped_log(max_bytes=6_000_000)
        except OSError as exc:
            warning(f"Failed to read experience log {self.log_path}: {exc}")
            return []

        lines = text.splitlines()
        llm_noise_lines = self._llm_distill_noise_line_indexes(lines)
        events = self._extract_structured_checker_events(lines, line_base, llm_noise_lines)
        if not events:
            events = self._extract_triggered_failure_events(lines, line_base, llm_noise_lines)
        events = self._dedupe_failure_events(events, lines)
        events = self._drop_orphan_progress_events(events)
        events = [event for event in events if self._event_has_specific_failure_evidence(event)]
        self._attach_stage_action_trace(events, lines, llm_noise_lines)
        if uncovered_only:
            events = [
                event for event in events
                if event.get("event_type") == "failure"
                and not self._event_is_covered_by_prior_rules(event)
            ]
            self.uncovered_failure_event_total = len(events)
            self.uncovered_failure_events = events[-max_events:]
            return self.uncovered_failure_events
        return events[-max_events:]

    def _extract_structured_checker_events(
        self,
        lines: list[str],
        line_base: int,
        llm_noise_lines: set[int],
        include_nonstandard_failures: bool = False,
    ) -> list[dict[str, str]]:
        events: list[dict[str, str]] = []
        idx = 0
        while idx < len(lines):
            if idx in llm_noise_lines or self._is_llm_distill_noise_line(lines[idx]):
                idx += 1
                continue
            match = re.match(rf"^\s*-\s*name:\s*['\"]?({CHECKER_NAME_PATTERN})\b", lines[idx])
            if not match:
                idx += 1
                continue
            if not self._checker_block_has_valid_tool_context(lines, idx):
                idx += 1
                continue
            end = self._checker_block_end(lines, idx + 1)
            block_with_offsets = [
                (offset, line)
                for offset, line in enumerate(lines[idx:end], start=idx)
                if offset not in llm_noise_lines and not self._is_llm_distill_noise_line(line)
            ]
            block_text = "\n".join(line for _, line in block_with_offsets)
            has_failed = (
                re.search(r"\bcount_fail:\s*[1-9][0-9]*\b", block_text) is not None
                or re.search(r"^[ \t]*error:[ \t]*\S", block_text, re.I | re.M) is not None
            )
            if (
                not has_failed
                and not self._line_has_checker_failure_signal(block_text)
                and not include_nonstandard_failures
            ):
                idx = end
                continue
            evidence = self._checker_block_relevant_lines(block_with_offsets)
            if not evidence:
                idx = end
                continue
            signature_idx, signature = self._find_signature_in_lines(evidence)
            if signature_idx is None:
                idx = end
                continue
            events.append({
                "line": str(line_base + signature_idx),
                "_log_index": signature_idx,
                "_action_start_index": self._checker_action_start_index(lines, end),
                "event_type": self._classify_checker_event(signature, evidence),
                "checker": match.group(1),
                "signature": signature,
                "excerpt": "\n".join(line for _, line in evidence),
            })
            idx = end
        return events

    def _drop_orphan_progress_events(self, events: list[dict[str, str]]) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        has_failure = False
        for event in events:
            if event.get("event_type") == "failure":
                has_failure = True
                result.append(event)
            elif has_failure:
                result.append(event)
        return result

    def _checker_action_start_index(self, lines: list[str], block_end: int) -> int:
        for pos in range(block_end, len(lines)):
            if re.match(r"^\s*Tool Calls:\s*$", lines[pos]):
                return pos
        return len(lines)

    def _checker_block_has_valid_tool_context(self, lines: list[str], checker_idx: int) -> bool:
        checker_tools = ("Check", "Complete")
        ignored_tools = ("CurrentTips", "AllStageJournal", "RoleInfo")
        start = max(0, checker_idx - 180)
        for pos in range(checker_idx - 1, start - 1, -1):
            compact = self._compact_line(lines[pos])
            if not compact:
                continue
            if re.match(rf"^(?:-\s*)?Name:\s*(?:{'|'.join(checker_tools)})\b", compact, re.I):
                return True
            if re.match(rf"^(?:-\s*)?(?:{'|'.join(checker_tools)})\s*\(", compact, re.I):
                return True
            if re.match(rf"^(?:-\s*)?Name:\s*(?:{'|'.join(ignored_tools)})\b", compact, re.I):
                return False
            if re.match(rf"^(?:-\s*)?(?:{'|'.join(ignored_tools)})\s*\(", compact, re.I):
                return False
            if re.match(r"^Name:\s*[A-Za-z_][A-Za-z0-9_]*\b", compact):
                return False
            if re.match(r"^(?:-\s*)?[A-Za-z_][A-Za-z0-9_]*\s*\(", compact):
                return False
        return False

    def _checker_block_end(self, lines: list[str], start: int) -> int:
        idx = start
        while idx < len(lines):
            line = lines[idx]
            if re.match(rf"^\s*-\s*name:\s*{CHECKER_NAME_PATTERN}\b", line):
                break
            if re.match(r"^\s*(?:check_pass|complete|action):\s*", line):
                break
            if line.startswith("[Important]"):
                break
            idx += 1
        return idx

    def _checker_block_relevant_lines(self, block: list[tuple[int, str]]) -> list[tuple[int, str]]:
        selected: list[tuple[int, str]] = []
        capture_budget = 0
        for offset, raw_line in block:
            compact = self._compact_line(raw_line)
            if not compact:
                continue
            if re.match(rf"^\s*-\s*name:\s*{CHECKER_NAME_PATTERN}\b", raw_line):
                selected.append((offset, compact))
                continue
            if re.search(r"\bcount_fail:\s*[1-9][0-9]*\b", compact):
                selected.append((offset, compact))
                continue
            if re.match(r"^\s*(?:error|suggestion|details|note|success):", compact):
                selected.append((offset, compact))
                capture_budget = 16
                continue
            if self._line_has_checker_failure_signal(compact):
                selected.append((offset, compact))
                capture_budget = max(capture_budget, 6)
                continue
            if capture_budget > 0:
                capture_budget -= 1
                if self._line_has_checker_context(compact):
                    selected.append((offset, compact))
        return self._dedupe_offset_lines(selected, limit=36)

    def _extract_triggered_failure_events(
        self,
        lines: list[str],
        line_base: int,
        llm_noise_lines: set[int],
    ) -> list[dict[str, str]]:
        trigger = re.compile(
            r"(\[Parse Error\]|"
            r"\[(?:Missing Assertions|Confidence Parse Error)\]|"
            r"\[(?:Test Case|Checkpoint|Documentation|Coverage|Unmarked|Undocumented)[^\]]+\]|"
            r"Test template structure validation failed|"
            r"You need use tool `ReadTextFile`|Not readed, need ReadTextFile|"
            r"No bin matched for pattern|KeyError:\s*'FG-|Validation failed|"
            r"FilesMustNotExist check fail|Can not use conftest\.py|must not exist, but find|"
            r"remaining to be implemented|need to be completed|Process status:|"
            r"not found in the failed test list|expected to be FAILED but actually PASSED|"
            r"not documented in the bug analysis file)",
            re.I,
        )
        events: list[dict[str, str]] = []
        last_end = -1
        for idx, line in enumerate(lines):
            if idx in llm_noise_lines or self._is_llm_distill_noise_line(line):
                continue
            match = trigger.search(line)
            if not match:
                continue
            if not self._checker_block_has_valid_tool_context(lines, idx):
                continue
            start = max(0, idx - 25)
            end = min(len(lines), idx + 55)
            excerpt_lines = [
                item
                for offset, item in enumerate(lines[start:end], start=start)
                if offset not in llm_noise_lines and not self._is_llm_distill_noise_line(item)
            ]
            if start <= last_end:
                if events:
                    merge_lines = [
                        item
                        for offset, item in enumerate(lines[max(0, idx - 5):end], start=max(0, idx - 5))
                        if offset not in llm_noise_lines and not self._is_llm_distill_noise_line(item)
                    ]
                    events[-1]["excerpt"] = self._compact_excerpt(merge_lines)
                    events[-1]["line"] = str(line_base + idx)
                    events[-1]["_log_index"] = idx
                    events[-1]["signature"] = self._compact_line(line)
                    checker = self._extract_checker_name("\n".join(merge_lines))
                    if checker:
                        events[-1]["checker"] = checker
                last_end = end
                continue
            last_end = end
            events.append({
                "line": str(line_base + idx),
                "_log_index": idx,
                "event_type": "failure",
                "checker": self._extract_checker_name("\n".join(excerpt_lines)),
                "signature": self._compact_line(line),
                "excerpt": self._compact_excerpt(excerpt_lines),
            })
        return events

    def _event_has_specific_failure_evidence(self, event: dict[str, str]) -> bool:
        if event.get("event_type") == "progress":
            return self._has_progress_signal(event.get("signature", ""), event.get("excerpt", ""))
        evidence_lines = self._filtered_evidence_lines(event.get("excerpt", ""))
        return self._has_specific_failure_evidence(event.get("signature", ""), evidence_lines)

    def _signature_is_low_value_failure(self, signature: str) -> bool:
        compact = self._compact_line(str(signature or ""))
        if not compact:
            return True
        low_value_patterns = (
            r"^count_fail:\s*\d+\s*$",
            r"^count_check:\s*\d+\s*$",
            r"^count_pass:\s*\d+\s*$",
            r"^check_pass:\s*(?:true|false)\s*$",
            r"^complete:\s*(?:true|false)\s*$",
            r"^run_test_success:\s*(?:true|false)\s*$",
            r"^total:\s*\d+\s*$",
            r"^fails:\s*\d+\s*$",
        )
        return any(re.search(pattern, compact, re.I) for pattern in low_value_patterns)

    def _classify_checker_event(self, signature: str, evidence: list[tuple[int, str]]) -> str:
        text = "\n".join([signature, *[line for _, line in evidence]])
        if self._has_progress_signal(signature, text) and not self._has_error_signal(text):
            return "progress"
        return "failure"

    def _has_progress_signal(self, signature: str, text: str) -> bool:
        combined = f"{signature}\n{text}"
        return bool(re.search(r"\bsuccess:\s*['\"]?Congratulations!|Process status:\s*\d+/\d+", combined, re.I))

    def _has_error_signal(self, text: str) -> bool:
        return bool(
            re.search(
                r"^\s*error:|\[Parse Error\]|Validation failed|not properly failing|"
                r"not documented in the bug analysis file|not found in the failed test list|"
                r"expected to be FAILED but actually PASSED|test_function_with_no_check_point_mark:\s*[1-9]",
                text,
                re.I | re.M,
            )
        )

    def _dedupe_failure_events(
        self,
        events: list[dict[str, str]],
        lines: list[str] | None = None,
    ) -> list[dict[str, str]]:
        deduped: list[dict[str, str]] = []
        for event in events:
            signature = self._normalize_failure_signature(event.get("signature", ""))
            checker = event.get("checker", "")
            try:
                idx = int(event.get("_log_index", -1))
            except (TypeError, ValueError):
                idx = -1
            if deduped:
                previous = deduped[-1]
                previous_signature = self._normalize_failure_signature(previous.get("signature", ""))
                previous_checker = previous.get("checker", "")
                try:
                    previous_idx = int(previous.get("_log_index", -1))
                except (TypeError, ValueError):
                    previous_idx = -1
                if (
                    signature
                    and signature == previous_signature
                    and checker == previous_checker
                    and previous_idx >= 0
                    and idx >= 0
                    and not self._has_new_tool_call_between(lines, previous_idx, idx)
                ):
                    deduped[-1] = event
                    continue
            deduped.append(event)
        return deduped

    def _has_new_tool_call_between(
        self,
        lines: list[str] | None,
        start: int,
        end: int,
    ) -> bool:
        if not lines:
            return False
        for line in lines[start + 1:end]:
            if re.match(r"^\s*Tool Calls:\s*$", line):
                return True
        return False

    def render_verification_experience(self, stages: list[StageExperience]) -> str:
        return "\n".join([
            f"# {self.dut_name} Verification Experience",
            "",
            "This file is generated from structured UCAgent stage records. Its purpose is to accelerate the next DUT verification run by reusing proven artifacts, workflow reminders, and stage-level lessons.",
            "",
            "## Reusable Focus Areas",
            *self._aggregate_categories(stages),
            "",
            "## Changed Artifacts",
            *self._changed_file_lines(stages),
            "",
            "## Stage Notes",
            *self._safe_journal_lines(stages, limit=16),
            "",
            "## Checker Workflow Reminders",
            "- Read the stage reference_files explicitly before Check/Complete.",
            "- When Check fails, fix the specific checker-reported item first instead of rewriting broad documents.",
            "- Keep FG/FC/CK names synchronized between functions_and_checks.md, coverage definitions, tests, and bug_analysis.md.",
            "- Treat candidate failure hints as triage aids; the original checker report remains the source of truth.",
            "",
            "## Source Stages",
            *self._source_stage_lines(stages),
            "",
        ])

    def render_failure_hints(self, hints: list[dict[str, Any]]) -> str:
        rules = []
        for hint in hints:
            rule = {
                "id": hint["id"],
                "priority": hint.get("priority", 100),
            }
            if hint.get("enabled") is False:
                rule["enabled"] = False
            if hint.get("stages"):
                rule["stages"] = hint["stages"]
            if hint.get("checkers"):
                rule["checkers"] = hint["checkers"]
            if hint.get("patterns"):
                rule["patterns"] = hint["patterns"]
            if hint.get("regex"):
                rule["regex"] = hint["regex"]
            if hint.get("source"):
                rule["source"] = hint["source"]
            rule["hint"] = hint["hint"]
            rules.append(rule)
        return yaml.safe_dump(
            {
                "experience": {
                    "max_candidate_failure_hints": 2,
                    "candidate_failure_hints": rules,
                }
            },
            allow_unicode=True,
            sort_keys=False,
        )

    def render_prior_rule_audit(self, audit: dict[str, Any]) -> str:
        return yaml.safe_dump(
            audit,
            allow_unicode=True,
            sort_keys=False,
        )

    def _stage_from_info(self, index: int, raw_stage: dict[str, Any]) -> StageExperience:
        meta = raw_stage.get("meta_data") if isinstance(raw_stage.get("meta_data"), dict) else {}
        commit = meta.get("commit") if isinstance(meta.get("commit"), dict) else {}
        commit_hash = str(commit.get("hash") or "")
        has_changes = bool(commit.get("has_changes", False))
        changed_files = self._commit_changed_files(commit_hash) if has_changes else {}
        stage = StageExperience(
            index=index,
            title=self._stage_title(raw_stage, meta, index),
            score=0,
            fail_count=self._safe_int(raw_stage.get("fail_count", 0), 0),
            is_completed=bool(raw_stage.get("is_completed", False)),
            is_skipped=bool(raw_stage.get("is_skipped", False)),
            changed_files=changed_files,
            journal=self._stringify(meta.get("journal", "")),
            commit_hash=commit_hash,
            has_changes=has_changes,
        )
        stage.categories = self._categorize_stage(stage)
        stage.score = self._score_stage(stage)
        return stage

    def _score_stage(self, stage: StageExperience) -> int:
        if stage.is_skipped:
            return 0
        score = 0
        if stage.is_completed:
            score += 1
        if stage.fail_count > 0:
            score += 3
        if stage.has_changes:
            score += 2
        for path in stage.changed_files:
            lower = path.lower()
            if "functions_and_checks.md" in lower:
                score += 3
            if lower.endswith("_api.py") or lower.endswith("_bundle_def.py"):
                score += 2
            if lower.endswith("_function_coverage_def.py"):
                score += 2
            if "/test_" in lower or lower.startswith("test_"):
                score += 3
            if any(name in lower for name in BUG_RELATED_FILES):
                score += 3
        if not stage.journal and not stage.changed_files:
            return 0
        return score

    def _categorize_stage(self, stage: StageExperience) -> set[str]:
        categories = set()
        text = f"{stage.title}\n" + "\n".join(stage.changed_files).lower()
        if "functions_and_checks.md" in text:
            categories.add("FG/FC/CK organization")
        if "_api.py" in text or "fixture" in text or "env" in text:
            categories.add("API/fixture")
        if "coverage" in text or "_function_coverage_def.py" in text:
            categories.add("coverage model")
        if "/test_" in text or "test_" in text:
            categories.add("test implementation")
        if any(name in text for name in BUG_RELATED_FILES):
            categories.add("bug analysis")
        if stage.fail_count > 0:
            categories.add("checker failure recovery")
        return categories

    def _commit_changed_files(self, commit_hash: str) -> dict[str, str]:
        if not commit_hash or not os.path.isdir(self.history_dir):
            return {}
        try:
            from ucagent.util import diff_ops
            return diff_ops.get_commit_changed_file_statuses(self.history_dir, commit_hash)
        except Exception:
            return self._commit_changed_files_with_git(commit_hash)

    def _commit_changed_files_with_git(self, commit_hash: str) -> dict[str, str]:
        try:
            proc = subprocess.run(
                [
                    "git",
                    "-C",
                    self.history_dir,
                    "diff-tree",
                    "--root",
                    "--no-commit-id",
                    "--name-status",
                    "-r",
                    commit_hash,
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as exc:
            warning(f"Failed to read history commit {commit_hash}: {exc}")
            return {}

        statuses = {}
        for line in proc.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            status_code = parts[0]
            path = parts[-1].replace(os.sep, "/")
            if not path:
                continue
            if status_code.startswith("A"):
                status = "added"
            elif status_code.startswith("D"):
                status = "deleted"
            elif status_code.startswith("R"):
                status = "renamed"
            else:
                status = "modified"
            statuses[path] = status
        return statuses

    def _aggregate_categories(self, stages: list[StageExperience]) -> list[str]:
        counts: dict[str, int] = {}
        for stage in stages:
            for category in stage.categories:
                if category == "bug analysis":
                    continue
                counts[category] = counts.get(category, 0) + 1
        if not counts:
            return ["- No high-confidence reusable focus areas were found."]
        return [f"- {name}: observed in {count} selected stage(s)." for name, count in sorted(counts.items())]

    def _changed_file_lines(self, stages: list[StageExperience]) -> list[str]:
        seen = {}
        for stage in stages:
            for path, status in stage.changed_files.items():
                if any(name in path.lower() for name in BUG_RELATED_FILES):
                    continue
                if self._file_is_useful(path):
                    seen[path] = status
        if not seen:
            return ["- No selected artifact changes."]
        return [f"- `{path}` ({status})" for path, status in sorted(seen.items())[:40]]

    def _source_stage_lines(self, stages: list[StageExperience]) -> list[str]:
        if not stages:
            return ["- No selected source stages."]
        lines = []
        for stage in stages[:30]:
            lines.append(
                f"- stage {stage.index}: {stage.title} "
                f"(score={stage.score}, fail_count={stage.fail_count}, changes={len(stage.changed_files)})"
            )
        return lines or ["- No selected source stages."]

    def _safe_journal_lines(self, stages: list[StageExperience], limit: int) -> list[str]:
        lines = []
        for stage in stages:
            if self._is_bug_related_stage(stage):
                continue
            for bullet in self._journal_bullets(stage.journal):
                if self._looks_like_bug_leak(bullet):
                    continue
                lines.append(f"- stage {stage.index}: {bullet}")
                if len(lines) >= limit:
                    return lines
        return lines or ["- No safe journal notes were selected."]

    def _journal_bullets(self, journal: str) -> list[str]:
        if not journal:
            return []
        bullets = []
        for raw_line in journal.splitlines():
            line = raw_line.strip()
            line = re.sub(r"^[-*#\d.\s]+", "", line).strip()
            if len(line) < 12:
                continue
            if len(line) > 180:
                line = line[:177].rstrip() + "..."
            bullets.append(line)
            if len(bullets) >= 8:
                break
        return bullets

    def _is_bug_related_stage(self, stage: StageExperience) -> bool:
        if "bug analysis" in stage.categories:
            return True
        lower_title = stage.title.lower()
        return "bug" in lower_title or "summary" in lower_title or "review" in lower_title

    def _file_is_useful(self, path: str) -> bool:
        lower = path.lower()
        return any(token in lower for token in REUSABLE_ARTIFACT_PATTERNS)

    def _looks_like_bug_leak(self, text: str) -> bool:
        return any(pattern.search(text) for pattern in BUG_LEAK_PATTERNS)

    def _normalize_rules(self, prior_rules: Any) -> list[dict[str, Any]]:
        if hasattr(prior_rules, "as_dict"):
            prior_rules = prior_rules.as_dict()
        if isinstance(prior_rules, dict):
            exp = prior_rules.get("experience", prior_rules)
            if isinstance(exp, dict) and isinstance(exp.get("candidate_failure_hints"), list):
                prior_rules = exp.get("candidate_failure_hints")
            else:
                prior_rules = [prior_rules]
        if not isinstance(prior_rules, list):
            return []

        normalized = []
        for idx, raw_rule in enumerate(prior_rules):
            if hasattr(raw_rule, "as_dict"):
                raw_rule = raw_rule.as_dict()
            if not isinstance(raw_rule, dict):
                continue
            rule_id = str(raw_rule.get("id") or f"rule_{idx}").strip()
            hint = str(raw_rule.get("hint") or "").strip()
            patterns = self._string_list(raw_rule.get("patterns", []))
            regexes = self._string_list(raw_rule.get("regex", []))
            if not rule_id or (not patterns and not regexes):
                continue

            item: dict[str, Any] = {
                "id": rule_id,
                "priority": self._safe_int(raw_rule.get("priority", 100), 100),
                "patterns": patterns,
                "regex": regexes,
                "hint": hint,
                "enabled": self._safe_bool(raw_rule.get("enabled", True), True),
            }
            stages = self._string_list(raw_rule.get("stages", []))
            checkers = self._string_list(raw_rule.get("checkers", []))
            if stages:
                item["stages"] = stages
            if checkers:
                item["checkers"] = checkers
            source = raw_rule.get("source")
            if isinstance(source, dict):
                item["source"] = source
            normalized.append(item)
        normalized.sort(key=lambda item: item.get("priority", 100))
        return normalized

    def _empty_prior_rule_audit(self) -> dict[str, Any]:
        return {
            "kind": "prior_rule_audit",
            "stage": {
                "index": self.target_stage_index,
                "name": self.target_stage_name,
            },
            "scope": {
                "log_path": self.log_path or "",
                "start_offset": self.log_start_offset,
                "end_offset": self.log_end_offset,
                "line_base": 1,
            },
            "rule_count": 0,
            "matched_rules": [],
            "unmatched_rules": [],
            "skipped_rules": [],
            "uncovered_failure_events": [],
            "uncovered_failure_event_count": 0,
            "llm_distill_event_count": 0,
        }

    def _llm_distill_noise_line_indexes(self, lines: list[str]) -> set[int]:
        noise: set[int] = set()
        idx = 0
        while idx < len(lines):
            line = lines[idx].strip()
            window = "\n".join(lines[idx:min(len(lines), idx + 160)])
            starts_distill_block = (
                line.startswith("<think>")
                or line.startswith("Quoted checker evidence:")
                or (
                    line in {"experience:", "candidate_failure_hints:"}
                    and "llm_distilled" in window
                )
            )
            if starts_distill_block and (
                "candidate_failure_hints" in window
                or "llm_distilled" in window
                or "Quoted checker evidence" in window
            ):
                end = min(len(lines), idx + 240)
                for next_idx in range(idx, min(len(lines), idx + 400)):
                    if (
                        "complete: true" in lines[next_idx]
                        or re.search(r"message:\s*'Stage\s+\d+\s+completed successfully", lines[next_idx])
                    ):
                        end = next_idx + 1
                        break
                noise.update(range(idx, end))
                idx = end
                continue
            idx += 1
        return noise

    def _is_llm_distill_noise_line(self, line: str) -> bool:
        text = str(line or "")
        return (
            "candidate_failure_hints" in text
            or "kind: llm_distilled" in text
            or "Quoted checker evidence:" in text
            or "Distill reusable checker-failure hints" in text
            or "UCAgent experience distiller" in text
        )

    def _load_distill_prompts(self) -> tuple[str, str]:
        prompt_path = os.path.join(
            os.path.dirname(__file__),
            "lang",
            self.lang,
            "experience",
            "distill_prompt.yaml",
        )
        if not os.path.isfile(prompt_path):
            raise FileNotFoundError(f"Experience distill prompt not found: {prompt_path}")
        with open(prompt_path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        system_prompt = data.get("system") if isinstance(data, dict) else None
        user_prompt = data.get("user") if isinstance(data, dict) else None
        if not isinstance(system_prompt, str) or not isinstance(user_prompt, str):
            raise ValueError(f"Experience distill prompt must define string system and user fields: {prompt_path}")
        return system_prompt, user_prompt

    def _read_scoped_log(self, max_bytes: int) -> tuple[str, int, dict[str, Any]]:
        if not self.log_path:
            return "", 1, {}
        if not os.path.isfile(self.log_path):
            return "", 1, {}

        start = self.log_start_offset if self.log_start_offset is not None else None
        end = self.log_end_offset if self.log_end_offset is not None else None
        active_size = os.path.getsize(self.log_path)
        if self.target_stage_index is not None and start is None:
            return "", 1, {
                "log_path": self.log_path,
                "start_offset": None,
                "end_offset": None,
                "log_size": active_size,
                "line_base": 1,
                "bytes_read": 0,
                "stage_scoped": False,
                "reason": "missing_stage_log_start_offset",
            }

        active_has_scope = (
            start is not None
            and 0 <= start <= active_size
            and (end is None or (start <= end <= active_size))
        )
        if not active_has_scope:
            rotated = self._read_rotated_scoped_log(
                start=start,
                end=end,
                active_size=active_size,
                max_bytes=max_bytes,
            )
            if rotated is not None:
                text, line_base, scope = rotated
                return text, line_base, scope

        if self.target_stage_index is not None and (start is None or start < 0 or start > active_size):
            return "", 1, {
                "log_path": self.log_path,
                "start_offset": start,
                "end_offset": end,
                "log_size": active_size,
                "line_base": 1,
                "bytes_read": 0,
                "stage_scoped": False,
                "reason": "invalid_stage_log_start_offset",
            }
        if start is None or start < 0 or start > active_size:
            start = max(0, active_size - max_bytes)
        if end is None or end < start or end > active_size:
            end = active_size
        if end - start > max_bytes:
            start = max(0, end - max_bytes)

        data, line_base = self._read_file_slice_with_line_base(self.log_path, start, end)
        scope = {
            "log_path": self.log_path,
            "start_offset": start,
            "end_offset": end,
            "log_size": active_size,
            "line_base": line_base,
            "bytes_read": len(data),
            "stage_scoped": self.target_stage_index is not None,
        }
        return data.decode("utf-8", errors="replace"), line_base, scope

    def _read_rotated_scoped_log(
        self,
        start: int | None,
        end: int | None,
        active_size: int,
        max_bytes: int,
    ) -> tuple[str, int, dict[str, Any]] | None:
        if self.target_stage_index is None or start is None or start < 0:
            return None
        start_rank = self._find_log_identity_rank()
        if start_rank is None or start_rank == 0:
            return None
        if end is None or end < 0 or end > active_size:
            return None

        segments = []
        for rank in range(start_rank, -1, -1):
            path = self.log_path if rank == 0 else f"{self.log_path}.{rank}"
            if not os.path.isfile(path):
                return None
            size = os.path.getsize(path)
            segment_start = start if rank == start_rank else 0
            segment_end = end if rank == 0 else size
            if segment_start < 0 or segment_start > segment_end:
                return None
            segments.append([path, segment_start, segment_end])

        total = sum(segment_end - segment_start for _, segment_start, segment_end in segments)
        while total > max_bytes and segments:
            overflow = total - max_bytes
            path, segment_start, segment_end = segments[0]
            consumed = min(overflow, segment_end - segment_start)
            segments[0] = [path, segment_start + consumed, segment_end]
            total -= consumed
            if segments[0][1] == segments[0][2]:
                segments.pop(0)
        if not segments:
            return "", 1, {
                "log_path": self.log_path,
                "stage_scoped": True,
                "rotated_log": True,
                "rotation_count": start_rank,
                "bytes_read": 0,
            }

        chunks = []
        line_base = 1
        for index, (path, segment_start, segment_end) in enumerate(segments):
            data, current_line_base = self._read_file_slice_with_line_base(path, segment_start, segment_end)
            if index == 0:
                line_base = current_line_base
            chunks.append(data)
        data = b"".join(chunks)
        return data.decode("utf-8", errors="replace"), line_base, {
            "log_path": self.log_path,
            "resolved_log_paths": [path for path, _, _ in segments],
            "start_offset": segments[0][1],
            "end_offset": end,
            "log_size": active_size,
            "line_base": line_base,
            "bytes_read": len(data),
            "stage_scoped": True,
            "rotated_log": True,
            "rotation_count": start_rank,
        }

    def _normalize_log_identity(self, value: Any) -> dict[str, int] | None:
        if not isinstance(value, dict):
            return None
        try:
            return {"dev": int(value["dev"]), "ino": int(value["ino"])}
        except (KeyError, TypeError, ValueError):
            return None

    def _find_log_identity_rank(self) -> int | None:
        if self.log_start_identity is None:
            return None
        for rank in range(0, 6):
            path = self.log_path if rank == 0 else f"{self.log_path}.{rank}"
            if not os.path.isfile(path):
                continue
            try:
                stat = os.stat(path)
            except OSError:
                continue
            if stat.st_dev == self.log_start_identity["dev"] and stat.st_ino == self.log_start_identity["ino"]:
                return rank
        return None

    def _read_file_slice_with_line_base(self, path: str, start: int, end: int) -> tuple[bytes, int]:
        with open(path, "rb") as handle:
            handle.seek(0)
            line_base = 1
            remaining = max(0, start)
            chunk_size = 1024 * 1024
            while remaining > 0:
                chunk = handle.read(min(chunk_size, remaining))
                if not chunk:
                    break
                line_base += chunk.count(b"\n")
                remaining -= len(chunk)
            handle.seek(start)
            data = handle.read(max(0, end - start))
        return data, line_base

    def _rule_applies_to_stage(self, rule: dict[str, Any]) -> bool:
        stages = rule.get("stages", [])
        if not stages:
            return True
        if self.target_stage_index is None:
            return True
        stage_text = self.target_stage_name.lower()
        for stage in stages:
            stage_key = str(stage).strip()
            if not stage_key:
                continue
            if stage_key.isdigit() and self.target_stage_index == int(stage_key):
                return True
            if not stage_key.isdigit() and stage_key.lower() in stage_text:
                return True
        return False

    def _audit_rule_summary(self, rule: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
        item: dict[str, Any] = {
            "id": rule.get("id", ""),
            "priority": rule.get("priority", 100),
            "stages": rule.get("stages", []),
            "checkers": rule.get("checkers", []),
            "patterns": rule.get("patterns", []),
            "regex": rule.get("regex", []),
            "hint": rule.get("hint", ""),
        }
        if reason:
            item["reason"] = reason
        return item

    def _match_rule(
        self,
        rule: dict[str, Any],
        text: str,
        line_base: int = 1,
    ) -> list[dict[str, str]]:
        lines = text.splitlines()
        llm_noise_lines = self._llm_distill_noise_line_indexes(lines)
        events = self._extract_structured_checker_events(
            lines,
            line_base,
            llm_noise_lines,
            include_nonstandard_failures=True,
        )
        if not events:
            events = self._extract_triggered_failure_events(lines, line_base, llm_noise_lines)
        events = self._dedupe_failure_events(events, lines)

        examples = []
        seen = set()
        for event in events:
            if not self._rule_matches_failure_event(rule, event):
                continue
            event_text = "\n".join([
                str(event.get("signature", "") or ""),
                str(event.get("excerpt", "") or ""),
            ])
            matched_by = self._first_rule_match(rule, event_text)
            if matched_by:
                compact = self._compact_line(event.get("signature", ""))
                if not compact:
                    compact = self._compact_line(event.get("excerpt", ""))
                key = (event.get("line", ""), matched_by, compact)
                if compact and key not in seen:
                    seen.add(key)
                    examples.append({
                        "line": str(event.get("line", "")),
                        "match": matched_by,
                        "text": compact[:500],
                    })
        return examples

    def _filter_llm_hints_against_prior_rules(
        self,
        hints: list[dict[str, Any]],
        events: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        if not hints or not self.prior_rules or not events:
            return hints
        kept = []
        for hint in hints:
            if self._llm_hint_is_covered_by_prior_rules(
                self._string_list(hint.get("patterns", [])),
                self._string_list(hint.get("regex", [])),
                hint=str(hint.get("hint", "")),
                evidence=self._string_list(hint.get("source", {}).get("evidence", [])),
            ):
                continue
            if self._llm_hint_is_covered_on_stage_events(hint, events):
                continue
            kept.append(hint)
        return kept

    def _llm_hint_is_covered_on_stage_events(
        self,
        hint: dict[str, Any],
        events: list[dict[str, str]],
    ) -> bool:
        candidate_discriminators = self._candidate_specialized_discriminators(
            self._string_list(hint.get("patterns", [])),
            self._string_list(hint.get("regex", [])),
            str(hint.get("hint", "")),
            self._string_list(hint.get("source", {}).get("evidence", [])),
        )
        for event in events:
            if not self._rule_matches_failure_event(hint, event):
                continue
            covering_rules = self._event_covering_prior_rules(event)
            if covering_rules and not self._candidate_has_new_specialized_delta(candidate_discriminators, covering_rules):
                return True
        return False

    def _event_is_covered_by_prior_rules(self, event: dict[str, str]) -> bool:
        return bool(self._event_covering_prior_rules(event))

    def _event_covering_prior_rules(self, event: dict[str, str]) -> list[dict[str, Any]]:
        matched = []
        for rule in self.prior_rules:
            if self._rule_matches_failure_event(rule, event):
                matched.append(rule)
        return matched

    def _rule_matches_failure_event(self, rule: dict[str, Any], event: dict[str, str]) -> bool:
        if event.get("event_type") == "progress":
            return False
        if not self._safe_bool(rule.get("enabled", True), True):
            return False
        if not self._rule_applies_to_stage(rule):
            return False
        checker = str(event.get("checker", "") or "")
        if not checker:
            return False
        checkers = self._string_list(rule.get("checkers", []))
        if checkers and checker not in checkers:
            return False
        text = "\n".join([
            str(event.get("signature", "") or ""),
            str(event.get("excerpt", "") or ""),
        ])
        return self._coverage_matches(rule, text)

    def _coverage_matches(self, rule: dict[str, Any], text: str) -> bool:
        return bool(self._first_rule_match(rule, text))

    def _first_rule_match(self, rule: dict[str, Any], text: str) -> str:
        for pattern in rule.get("patterns", []):
            if str(pattern) in text:
                return str(pattern)
        for pattern in rule.get("regex", []):
            try:
                if re.search(str(pattern), text, re.S):
                    return str(pattern)
            except re.error as exc:
                warning(f"Invalid experience rule regex '{pattern}': {exc}")
        return ""

    def _attach_stage_action_trace(
        self,
        events: list[dict[str, str]],
        lines: list[str],
        llm_noise_lines: set[int],
    ) -> None:
        for pos, event in enumerate(events):
            try:
                idx = int(event.get("_log_index", -1))
            except (TypeError, ValueError):
                continue
            if idx < 0 or idx >= len(lines):
                continue
            if pos + 1 < len(events):
                try:
                    next_idx = int(events[pos + 1].get("_log_index", len(lines)))
                except (TypeError, ValueError):
                    next_idx = len(lines)
            else:
                next_idx = len(lines)
            try:
                action_start = int(event.get("_action_start_index", idx + 1))
            except (TypeError, ValueError):
                action_start = idx + 1
            start = min(max(idx + 1, action_start), len(lines))
            action_lines = self._filtered_stage_action_lines(
                lines,
                start,
                min(max(start, next_idx), start + 800, len(lines)),
                llm_noise_lines,
            )
            recovery_event = self._next_meaningful_recovery_event(
                events,
                pos + 1,
                current_checker=str(event.get("checker", "") or ""),
            )
            if recovery_event is not None:
                try:
                    recovery_idx = int(recovery_event.get("_log_index", next_idx))
                except (TypeError, ValueError):
                    recovery_idx = next_idx
                recovery_end = min(max(start, recovery_idx), start + 800, len(lines))
                action_lines = self._filtered_stage_action_lines(
                    lines,
                    start,
                    recovery_end,
                    llm_noise_lines,
                )
                action_lines.append(
                    self._failure_relation_summary(event, recovery_event)
                )
            elif not any("completed successfully" in line.lower() for line in action_lines):
                status = self._format_target_stage_status()
                if status:
                    action_lines.append(f"final_stage_status: {status}")
                else:
                    action_lines.append("next_checker_result: no later high-confidence checker failure in this stage slice")
            event["actions_after_failure"] = "\n".join(self._limit_action_lines(action_lines, limit=24))

    def _next_meaningful_recovery_event(
        self,
        events: list[dict[str, str]],
        start_pos: int,
        current_checker: str = "",
    ) -> dict[str, str] | None:
        if not current_checker and start_pos > 0:
            current_checker = str(events[start_pos - 1].get("checker", "") or "")
        for pos in range(start_pos, len(events)):
            event = events[pos]
            if current_checker and event.get("checker", "") != current_checker:
                continue
            if not current_checker:
                continue
            if event.get("event_type") == "progress":
                return event
            if not self._signature_is_low_value_failure(event.get("signature", "")):
                return event
        return None

    def _limit_action_lines(self, action_lines: list[str], limit: int) -> list[str]:
        if len(action_lines) <= limit:
            return action_lines
        result_lines = [
            line for line in action_lines
            if line.startswith(("next_checker_result:", "final_stage_status:"))
        ]
        regular_lines = [
            line for line in action_lines
            if not line.startswith(("next_checker_result:", "final_stage_status:"))
        ]
        keep_regular = max(0, limit - len(result_lines))
        return regular_lines[:keep_regular] + result_lines[-limit:]

    def _failure_relation_summary(self, event: dict[str, str], next_event: dict[str, str]) -> str:
        current_sig = self._normalize_failure_signature(event.get("signature", ""))
        next_sig = self._normalize_failure_signature(next_event.get("signature", ""))
        current_checker = event.get("checker", "")
        next_checker = next_event.get("checker", "")
        next_type = next_event.get("event_type", "failure")
        if next_type == "progress":
            relation = "same_checker_progress" if current_checker and current_checker == next_checker else "later_checker_progress"
        elif current_checker and current_checker == next_checker and current_sig and current_sig == next_sig:
            relation = "repeated_same_checker_failure"
        elif current_checker and current_checker == next_checker:
            relation = "same_checker_changed_result"
        else:
            relation = "unrelated_checker_failure"
        return (
            f"next_checker_result: {relation}; "
            f"{next_checker or 'checker'} / {self._failure_family_key(next_event)} / {next_event.get('signature', '')}"
        )

    def _select_recovery_timeline_events(
        self,
        events: list[dict[str, str]],
        max_events: int,
    ) -> tuple[list[dict[str, str]], int]:
        if not events:
            return [], 0
        max_events = max(2, int(max_events or 20))
        if len(events) <= max_events:
            return events, 0

        selected_indexes: list[int] = []

        def add(index: int) -> None:
            if 0 <= index < len(events) and index not in selected_indexes:
                selected_indexes.append(index)

        add(0)
        for idx, event in enumerate(events):
            previous = events[idx - 1] if idx > 0 else None
            next_event = events[idx + 1] if idx + 1 < len(events) else None
            if event.get("event_type") == "progress":
                add(idx)
                continue
            if previous is not None and self._event_relation_key(event) != self._event_relation_key(previous):
                add(idx)
                continue
            if next_event is not None and self._event_relation_key(event) != self._event_relation_key(next_event):
                add(idx)
                continue
        add(len(events) - 1)

        if len(selected_indexes) > max_events:
            first = selected_indexes[0]
            failure_indexes = [
                idx for idx in selected_indexes
                if events[idx].get("event_type") == "failure"
            ]
            last_failure = failure_indexes[-1] if failure_indexes else selected_indexes[-1]
            required = []
            for index in (first, last_failure):
                if index not in required:
                    required.append(index)
            middle = [
                index for index in selected_indexes
                if index not in required and events[index].get("event_type") == "failure"
            ]
            budget = max_events - len(required)
            if budget <= 0:
                selected_indexes = required[:max_events]
            elif len(middle) <= budget:
                selected_indexes = [*required, *middle]
            else:
                step = max(1, len(middle) / budget)
                sampled = []
                cursor = 0.0
                while len(sampled) < budget and int(cursor) < len(middle):
                    sampled.append(middle[int(cursor)])
                    cursor += step
                selected_indexes = [*required, *sampled[:budget]]

        selected_indexes = sorted(set(selected_indexes))
        selected = []
        omitted_before = 0
        selected_set = set(selected_indexes)
        for idx, event in enumerate(events):
            if idx not in selected_set:
                omitted_before += 1
                continue
            item = dict(event)
            if omitted_before:
                item["_omitted_before"] = str(omitted_before)
                omitted_before = 0
            selected.append(item)
        selected = self._dedupe_recovery_cases_by_failure_family(selected)
        omitted_count = len(events) - len(selected)
        return selected, omitted_count

    def _event_relation_key(self, event: dict[str, str]) -> tuple[str, str, str]:
        return (
            str(event.get("event_type", "failure")),
            str(event.get("checker", "")),
            self._normalize_failure_signature(event.get("signature", "")),
        )

    def _dedupe_recovery_cases_by_failure_family(
        self,
        events: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        by_family: dict[tuple[str, str, str], dict[str, str]] = {}
        passthrough: list[dict[str, str]] = []
        for event in events:
            if event.get("event_type") != "failure":
                passthrough.append(event)
                continue
            key = (
                str(event.get("checker", "")),
                self._failure_family_key(event),
                self._event_specialization_key(event),
            )
            by_family[key] = event
        result = list(by_family.values()) + passthrough
        result.sort(key=lambda event: self._safe_int(event.get("_log_index", 0), 0))
        return result

    def _failure_family_key(self, event: dict[str, str]) -> str:
        text = "\n".join([
            str(event.get("signature", "")),
            str(event.get("excerpt", "")),
        ])
        families = (
            ("missing_assertions", r"\[Missing Assertions\]|do not contain assert statements"),
            ("confidence_parse_error", r"\[Confidence Parse Error\]|confidence integer from 0 to 100"),
            ("undocumented_failed_cases", r"\[Undocumented Failed Cases\]|not documented in the bug analysis file"),
            ("remaining_to_be_implemented", r"remaining to be implemented"),
            ("test_case_not_found", r"\[Test Case Not Found\]|not found in the failed test list"),
            ("checkpoint_not_marked", r"\[Checkpoint Not Marked\]|without checkpoint marks"),
            ("status_mismatch", r"\[Test Case Status Mismatch\]|expected to be FAILED but actually PASSED"),
            ("unmarked_test_functions", r"\[Unmarked Test Functions\]|test_function_with_no_check_point_mark"),
            ("parse_error_parent_missing", r"\[Parse Error\].*parent .* was not found"),
            ("parse_error_duplicate_label", r"\[Parse Error\].*defined multiple times"),
            ("read_reference_files", r"ReadTextFile|Not readed, need ReadTextFile"),
            ("files_must_not_exist", r"FilesMustNotExist|must not exist, but find|Can not use conftest\.py"),
        )
        for name, pattern in families:
            if re.search(pattern, text, re.I | re.S):
                return name
        return self._normalize_failure_signature(event.get("signature", ""))

    def _extract_specialized_discriminators(self, texts: list[str]) -> list[str]:
        if not texts:
            return []
        counter: dict[str, int] = {}
        token_order: list[str] = []
        token_re = re.compile(r"\b(?:FG|FC|CK|BG|BG-STATIC)-[A-Z0-9][A-Z0-9-]*\b")
        blocked_parts = {"XXX", "YYY", "ZZZ", "TBD", "NULL", "GROUP", "FUNCTION", "CHECK1", "CHECK2"}
        for text in texts:
            normalized = str(text or "").replace("\\", "")
            for token in token_re.findall(normalized):
                if set(token.split("-")) & blocked_parts:
                    continue
                if token not in counter:
                    token_order.append(token)
                    counter[token] = 0
                counter[token] += 1
        result = []
        for token in token_order:
            if counter.get(token, 0) < 2:
                continue
            result.append(token)
        return result[:8]

    def _rule_specialized_discriminators(self, rule: dict[str, Any]) -> list[str]:
        texts = [
            *self._string_list(rule.get("patterns", [])),
            *self._string_list(rule.get("regex", [])),
            str(rule.get("hint", "")),
        ]
        source = rule.get("source")
        if isinstance(source, dict):
            texts.extend(self._string_list(source.get("evidence", [])))
        return self._extract_specialized_discriminators(texts)

    def _candidate_specialized_discriminators(
        self,
        patterns: list[str],
        regexes: list[str],
        hint: str,
        evidence: list[str],
    ) -> list[str]:
        return self._extract_specialized_discriminators([
            *patterns,
            *regexes,
            hint,
            *evidence,
        ])

    def _candidate_has_new_specialized_delta(
        self,
        candidate_discriminators: list[str],
        prior_rules: list[dict[str, Any]],
    ) -> bool:
        if not candidate_discriminators:
            return False
        covered = set()
        for rule in prior_rules:
            covered.update(self._rule_specialized_discriminators(rule))
        new_tokens = [token for token in candidate_discriminators if token not in covered]
        if not new_tokens:
            return False
        return any(token.startswith(("CK-", "BG-", "BG-STATIC-")) for token in new_tokens) or len(new_tokens) >= 2

    def _event_specialization_key(self, event: dict[str, str]) -> str:
        discriminators = self._extract_specialized_discriminators([
            str(event.get("signature", "")),
            str(event.get("excerpt", "")),
        ])
        if not discriminators:
            return ""
        return "|".join(discriminators[:3])

    def _target_stage_status(self) -> dict[str, Any]:
        if self.target_stage_index is None:
            return {}
        stages = self.ucagent_info.get("stages_info", {})
        if not isinstance(stages, dict):
            return {}
        raw_stage = stages.get(str(self.target_stage_index), {})
        if not isinstance(raw_stage, dict):
            return {}
        return {
            "is_completed": raw_stage.get("is_completed"),
            "check_pass": raw_stage.get("check_pass"),
            "fail_count": raw_stage.get("fail_count"),
            "is_skipped": raw_stage.get("is_skipped"),
        }

    def _format_target_stage_status(self) -> str:
        if not self.target_stage_status:
            return ""
        return ", ".join(
            f"{key}={value}"
            for key, value in self.target_stage_status.items()
            if value is not None
        )

    def _filtered_stage_action_lines(
        self,
        lines: list[str],
        start: int,
        end: int,
        llm_noise_lines: set[int],
    ) -> list[str]:
        keep_patterns = (
            r"^\s*Tool Calls:",
            r"^\s*(ReadTextFile|SearchText|FindFiles|ReplaceStringInFile|EditTextFile|WriteTextFile|CreateFile|DeleteFile|RunTestCases|Check|Complete|CurrentTips)\b",
            r"^\s*Name:\s*(ReadTextFile|SearchText|FindFiles|ReplaceStringInFile|EditTextFile|WriteTextFile|CreateFile|DeleteFile|RunTestCases|Check|Complete)\b",
            r"^\s*(path|file_path|filepath|directory|pattern|target):\s*(Guide_Doc|unity_test|tests|[^ ]+\.(?:md|py|v|sv|yaml|json)|def\s+test_)",
            r"\[INFO\]\s+Successfully\s+(?:replaced|wrote|written|created|deleted)",
            r"FilesMustNotExist check fail|Can not use conftest\.py|must not exist, but find",
            r"Found\s+\d+\s+matching lines?",
            r"Line\s+\d+:\s*def\s+test_",
            r"^\s*\d+:\s*def\s+test_",
            r"\bTool(Check|Complete):",
            r"\b(check_pass|complete):\s*(true|false)",
            r"\b(run_test_success|total|fails):\s*(true|false|\d+)",
            r"^\s*(REPORT|TEST_REPORT):\s*$",
            r"^\s*(failed_tc|failed_ck):\s*$",
            r"message:\s*'Stage\s+\d+\s+completed successfully",
            r"success:\s+Congratulations!",
            r"Stage\s+\d+\s+completed successfully|All stages completed",
            r"Reading text file .*|Reference file .* has been read",
            r"(Writing|Replacing string|Creating|Deleting|Moving|Editing).{0,80}file",
            r"Run command:|RunTestCases|Checking \d+ test cases",
            r"Current batch:|Completed \d+ out of|Returned \d+ test cases",
        )
        drop_patterns = (
            r"candidate_failure_hints|llm_distilled|Quoted checker evidence",
            r"^\s*STDOUT:|^\s*STDERR:",
            r"pytest|test session starts|generated report",
            r"^\s*[\{\}\[\],]?\s*$",
            r"^\s*DEBUG\b",
        )
        kept = []
        for offset in range(start, min(end, len(lines))):
            if offset in llm_noise_lines or self._is_llm_distill_noise_line(lines[offset]):
                continue
            line = self._compact_line(lines[offset])
            if not line:
                continue
            if any(re.search(pattern, line, re.I) for pattern in drop_patterns):
                continue
            if any(re.search(pattern, line, re.I) for pattern in keep_patterns):
                if line not in kept:
                    kept.append(line)
            if len(kept) >= 24:
                break
        return kept

    def _format_failure_events(self, events: list[dict[str, str]]) -> str:
        chunks = []
        for event in events:
            evidence_lines = self._filtered_evidence_lines(event.get("excerpt", ""))
            if not self._has_specific_failure_evidence(event.get("signature", ""), evidence_lines):
                continue
            action_lines = [
                line for line in str(event.get("actions_after_failure", "")).splitlines()
                if line.strip()
            ]
            chunks.append(
                "\n".join([
                    f"- line: {event.get('line', '')}",
                    f"  event_type: {event.get('event_type', 'failure')}",
                    f"  checker: {event.get('checker', '')}",
                    f"  signature: {event.get('signature', '')}",
                    "  evidence: |",
                    *[f"    {line}" for line in evidence_lines],
                    "  agent_actions_and_next_result: |",
                    *([f"    {line}" for line in action_lines] if action_lines else ["    (no compact action trace found)"]),
                ])
            )
        return "\n\n".join(chunks)

    def _format_recovery_trajectory(
        self,
        events: list[dict[str, str]],
        total_events: int,
        omitted_count: int,
    ) -> str:
        if not events:
            return ""
        failure_events = [event for event in events if event.get("event_type") == "failure"]
        lines = [
            "stage_recovery_summary:",
            f"  stage_index: {self.target_stage_index if self.target_stage_index is not None else ''}",
            f"  stage_name: {self.target_stage_name}",
            f"  total_checker_events_in_stage: {total_events}",
            f"  selected_failure_cases: {len(failure_events)}",
            f"  omitted_intermediate_steps: {omitted_count}",
            f"  final_stage_status: {self._format_target_stage_status() or 'unknown'}",
            "checker_recovery_cases:",
        ]
        case_no = 0
        for event in events:
            if event.get("event_type") != "failure":
                continue
            evidence_lines = self._filtered_evidence_lines(event.get("excerpt", ""))
            if not self._has_specific_failure_evidence(event.get("signature", ""), evidence_lines):
                continue
            if self._signature_is_low_value_failure(event.get("signature", "")):
                continue
            action_text = str(event.get("actions_after_failure", ""))
            omitted_before = event.get("_omitted_before", "")
            action_summary = self._summarize_recovery_actions(
                action_text,
                self._failure_family_key(event),
            )
            case_no += 1
            lines.extend([
                f"- case: {case_no}",
                f"  checker: {event.get('checker', '')}",
                f"  failure_family: {self._failure_family_key(event)}",
                f"  error: {event.get('signature', '')}",
            ])
            if omitted_before:
                lines.append(f"  omitted_intermediate_steps_before: {omitted_before}")
            lines.extend([
                "  checker_evidence: |",
                *[f"    {line}" for line in evidence_lines[:10]],
                "  observed_steps: |",
                *[f"    {line}" for line in action_summary["observed_steps"]],
                f"  likely_effective_step: {action_summary['likely_effective_step']}",
                f"  verification_step: {action_summary['verification_step']}",
                f"  result: {action_summary['result']}",
                "  candidate_experience: one concise hint for this checker/error if the recovery is reusable",
            ])
        return "\n".join(lines)

    def _compact_recovery_actions(self, action_text: str) -> list[str]:
        lines = [self._compact_line(line) for line in str(action_text or "").splitlines()]
        result: list[str] = []
        current_tool = ""
        test_metrics: dict[str, str] = {}
        checker_metrics: dict[str, str] = {}
        saw_test_definition = False
        for line in lines:
            if not line:
                continue
            if line.startswith(("next_checker_result:", "final_stage_status:")):
                continue
            match = re.match(
                r"^(ReadTextFile|SearchText|FindFiles|ReplaceStringInFile|EditTextFile|WriteTextFile|CreateFile|DeleteFile|RunTestCases|Check|Complete|CurrentTips)\b",
                line,
            )
            if match:
                current_tool = match.group(1)
                continue
            if line.startswith("Name: "):
                continue
            if line.startswith(("path:", "target:", "directory:", "pattern:")):
                role = self._recovery_target_role(line)
                if role:
                    if current_tool == "ReadTextFile":
                        self._append_unique_limited(result, f"read {role}")
                    elif current_tool in {"SearchText", "FindFiles"}:
                        self._append_unique_limited(result, f"search {role}")
                    elif current_tool in {"ReplaceStringInFile", "EditTextFile", "WriteTextFile", "CreateFile", "DeleteFile"}:
                        self._append_unique_limited(result, f"edit {role}")
                    elif current_tool == "RunTestCases":
                        self._append_unique_limited(result, f"rerun tests against {role}")
                continue
            if re.search(r"\[INFO\]\s+Successfully\s+(?:replaced|wrote|written|created|deleted)", line, re.I):
                role = self._recovery_target_role(line)
                self._append_unique_limited(result, f"confirm edit applied to {role or 'target file'}")
                continue
            if re.search(r"\b(run_test_success|total|fails):\s*(true|false|\d+)", line, re.I):
                key, value = [item.strip() for item in line.split(":", 1)]
                test_metrics[key] = value
                continue
            if re.search(r"Found\s+\d+\s+matching lines?", line, re.I):
                role = self._recovery_target_role(line)
                self._append_unique_limited(result, f"inspect matches in {role or 'current file'}")
                continue
            if re.search(r"\b(check_pass|complete):\s*(true|false)\b", line, re.I):
                key, value = [item.strip() for item in line.split(":", 1)]
                checker_metrics[key] = value
                continue
            if re.search(r"(Line\s+\d+:\s*def\s+test_|^\d+:\s*def\s+test_)", line, re.I):
                saw_test_definition = True
                continue
        if saw_test_definition:
            self._append_unique_limited(result, "inspect failing test definitions")
        if test_metrics:
            summary = ", ".join(
                f"{key}={value}"
                for key, value in test_metrics.items()
                if key in {"run_test_success", "total", "fails"}
            )
            if summary:
                self._append_unique_limited(result, f"rerun tests: {summary}")
        if checker_metrics:
            summary = ", ".join(
                f"{key}={value}"
                for key, value in checker_metrics.items()
                if key in {"check_pass", "complete"}
            )
            if summary:
                self._append_unique_limited(result, f"rerun checker: {summary}")
        return result[:12] or ["(no compact recovery action found)"]

    def _summarize_recovery_actions(self, action_text: str, failure_family: str) -> dict[str, Any]:
        observed_steps = self._compact_recovery_actions(action_text)
        result = self._recovery_result_from_action(action_text)
        verification_steps = [
            step for step in observed_steps
            if step.startswith(("rerun checker:", "rerun tests:"))
        ]
        action_steps = [
            step for step in observed_steps
            if step not in verification_steps
        ]
        likely_effective_step = self._infer_likely_effective_step(action_steps, result, failure_family)
        verification_step = " ; ".join(verification_steps) if verification_steps else "no explicit verification step captured"
        return {
            "observed_steps": action_steps or ["(no compact recovery action found)"],
            "likely_effective_step": likely_effective_step,
            "verification_step": verification_step,
            "result": result,
        }

    def _infer_likely_effective_step(self, action_steps: list[str], result: str, failure_family: str) -> str:
        relation = self._parse_recovery_relation(result)
        has_edit = any(
            step.startswith(("edit ", "confirm edit applied to "))
            for step in action_steps
        )
        read_can_be_effective_families = {
            "read_reference_files",
            "files_must_not_exist",
        }
        if relation == "repeated_same_checker_failure":
            last_edit = self._last_step_with_prefix(action_steps, ("edit ", "confirm edit applied to "))
            if last_edit:
                return f"no clearly effective step observed; last attempted change was {last_edit}"
            return "no clearly effective step observed before the same checker failure repeated"

        confirmed_relations = {
            "same_checker_changed_result",
            "same_checker_progress",
            "final_stage_completed",
        }
        if relation not in confirmed_relations:
            return "no clearly effective step observed; recovery was not confirmed by the same checker or final stage status"

        if not has_edit and failure_family not in read_can_be_effective_families:
            return "no clearly effective step observed; only inspection/search steps were captured before the checker changed"

        priorities = (
            ("edit ", "confirm edit applied to "),
            ("read reference_doc",),
            ("read bug_analysis_doc", "read static_bug_doc", "read functions_and_checks_doc", "read coverage_def", "read test_file", "read api_file", "read fixture_file"),
            ("search ", "inspect matches in "),
            ("inspect failing test definitions",),
        )
        for prefixes in priorities:
            step = self._last_step_with_prefix(action_steps, prefixes)
            if step:
                return step
        return "no clear recovery step captured"

    def _last_step_with_prefix(self, steps: list[str], prefixes: tuple[str, ...]) -> str:
        for step in reversed(steps):
            if step.startswith(prefixes):
                return step
        return ""

    def _parse_recovery_relation(self, result: str) -> str:
        text = self._compact_line(result)
        if text.startswith("final_stage_status:"):
            if "is_completed=true" in text.lower() and "check_pass=true" in text.lower():
                return "final_stage_completed"
            return "final_stage_status"
        match = re.match(r"^next_checker_result:\s*([^;]+)", text)
        return match.group(1).strip() if match else ""

    def _append_unique_limited(self, result: list[str], line: str, limit: int = 12) -> None:
        if line and line not in result and len(result) < limit:
            result.append(line)

    def _recovery_result_from_action(self, action_text: str) -> str:
        for line in str(action_text or "").splitlines():
            compact = self._compact_line(line)
            if compact.startswith("next_checker_result:"):
                return compact
            if compact.startswith("final_stage_status:"):
                return compact
        return "no later checker result in this stage slice"

    def _recovery_target_role(self, line: str) -> str:
        text = self._compact_line(line)
        if not text:
            return ""
        lowered = text.lower()
        if "guide_doc/" in lowered:
            return "reference_doc"
        if "_static_bug_analysis.md" in lowered:
            return "static_bug_doc"
        if "_bug_analysis.md" in lowered:
            return "bug_analysis_doc"
        if "functions_and_checks.md" in lowered:
            return "functions_and_checks_doc"
        if "_function_coverage_def.py" in lowered or "coverage_def" in lowered:
            return "coverage_def"
        if "/tests/" in lowered or re.search(r"\btest_[^ ]+\.py\b", lowered):
            return "test_file"
        if "_api.py" in lowered:
            return "api_file"
        if "fixture" in lowered or "_env_" in lowered:
            return "fixture_file"
        if "unity_test" in lowered:
            return "unity_test_workspace"
        if "rtl" in lowered or re.search(r"\.(?:v|sv|scala|vh)\b", lowered):
            return "rtl_source"
        return ""

    def _format_stage_task_info(self) -> str:
        if self.stage_task_info is None:
            return "(stage task context unavailable)"
        try:
            return yaml.safe_dump(
                self._compact_stage_task_info(self.stage_task_info),
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            ).strip()
        except Exception:
            return self._compact_line(str(self.stage_task_info))

    def _compact_stage_task_info(self, value: Any, depth: int = 0) -> Any:
        if depth > 4:
            return self._compact_line(str(value))
        if hasattr(value, "as_dict"):
            value = value.as_dict()
        if isinstance(value, dict):
            compacted = {}
            for key, item in value.items():
                text_key = str(key)
                if text_key in {"reference_files", "output_files", "skill_list", "upper_task", "notes"}:
                    compacted[text_key] = self._compact_stage_task_info(item, depth + 1)
                elif text_key in {"title", "description"}:
                    compacted[text_key] = self._compact_stage_task_info(item, depth + 1)
            return compacted
        if isinstance(value, list):
            return [self._compact_stage_task_info(item, depth + 1) for item in value[:24]]
        if isinstance(value, str):
            text = value.strip()
            return text if len(text) <= 300 else text[:297].rstrip() + "..."
        return value

    def _line_has_checker_failure_signal(self, line: str) -> bool:
        text = str(line or "")
        signal_patterns = (
            r"\[Parse Error\]",
            r"\[(?:Missing Assertions|Confidence Parse Error)\]",
            r"\[(?:Test Case|Checkpoint|Documentation|Coverage|Unmarked|Undocumented)[^\]]+\]",
            r"Test template structure validation failed",
            r"You need use tool `ReadTextFile`",
            r"Not readed, need ReadTextFile",
            r"test_function_with_no_check_point_mark:\s*[1-9]",
            r"No bin matched for pattern",
            r"KeyError:\s*'FG-",
            r"FilesMustNotExist check fail",
            r"Can not use conftest\.py",
            r"must not exist, but find",
            r"Validation failed",
            r"remaining to be implemented",
            r"need to be completed",
            r"Process status:\s*\d+/\d+",
            r"not found in the failed test list",
            r"expected to be FAILED but actually PASSED",
            r"not documented in the bug analysis file",
            r"parent (?:FG|FC|CK|BG) tag .*was not found",
        )
        return any(re.search(pattern, text, re.I) for pattern in signal_patterns)

    def _line_has_checker_context(self, line: str) -> bool:
        text = str(line or "")
        context_patterns = (
            r"Tag hierarchy:",
            r"<FG-|<FC-|<CK-|<BG-|<TC-",
            r"assert False, \"Not implemented\"",
            r"mark_function",
            r"Process status:\s*\d+/\d+",
            r"Please ensure|Please check|Possible Causes|Solution|Correct Format|Bug Analysis Document Format",
        )
        return self._line_has_checker_failure_signal(text) or any(
            re.search(pattern, text, re.I) for pattern in context_patterns
        )

    def _find_signature_in_lines(self, lines: list[tuple[int, str]]) -> tuple[int | None, str]:
        fallback: tuple[int | None, str] = (None, "")
        progress: tuple[int | None, str] = (None, "")
        has_error = self._has_error_signal("\n".join(line for _, line in lines))
        for offset, line in lines:
            compact = self._compact_line(line)
            if not compact:
                continue
            if fallback[0] is None and not re.match(r"^\s*(-\s*)?name:\s+", compact):
                fallback = (offset, compact)
            if progress[0] is None and self._line_has_progress_signal(compact):
                progress = (offset, compact)
                continue
            if re.match(r"^[ \t]*error:[ \t]*\S", compact, re.I):
                return offset, compact
            if self._line_has_checker_failure_signal(compact):
                return offset, compact
        if progress[0] is not None and not has_error:
            return progress
        return fallback

    def _line_has_progress_signal(self, line: str) -> bool:
        return bool(re.search(r"\bsuccess:\s*['\"]?Congratulations!|Process status:\s*\d+/\d+", str(line or ""), re.I))

    def _dedupe_offset_lines(
        self,
        lines: list[tuple[int, str]],
        limit: int,
    ) -> list[tuple[int, str]]:
        result: list[tuple[int, str]] = []
        seen: set[str] = set()
        for offset, line in lines:
            compact = self._compact_line(line)
            if not compact:
                continue
            key = compact.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append((offset, compact))
            if len(result) >= limit:
                break
        return result

    def _has_specific_failure_evidence(self, signature: str, evidence_lines: list[str]) -> bool:
        text = signature + "\n" + "\n".join(evidence_lines)
        if not self._has_checker_signal_line(evidence_lines):
            return False
        if self._has_specific_checker_failure_label(text):
            return True
        specific_patterns = (
            r"^[ \t]*error:[ \t]*\S",
            r"ReadTextFile|No bin matched|KeyError:\s*'FG-",
            r"FilesMustNotExist check fail|Can not use conftest\.py|must not exist, but find",
            r"test_function_with_no_check_point_mark:\s*[1-9]",
            r"Parse Error|Validation failed",
            r"remaining to be implemented",
            r"need to be completed|Process status:\s*\d+/\d+",
            r"not found in the failed test list",
            r"expected to be FAILED but actually PASSED",
            r"not documented in the bug analysis file",
        )
        return any(re.search(pattern, text, re.I | re.M) for pattern in specific_patterns)

    def _has_specific_checker_failure_label(self, text: str) -> bool:
        explanation_labels = {
            "bug analysis document format",
            "cause",
            "correct format",
            "possible causes",
            "problem",
            "solution",
        }
        labels = re.findall(r"\[([A-Za-z][^\]]{2,80})\]", str(text or ""))
        return any(label.strip().lower() not in explanation_labels for label in labels)

    def _has_checker_signal_line(self, evidence_lines: list[str]) -> bool:
        signal_patterns = (
            rf"^\s*-?\s*name:\s+{CHECKER_NAME_PATTERN}\b",
            r"^\s*(error|suggestion|details|note):",
            r"ReadTextFile|No bin matched|KeyError:\s*'FG-",
            r"FilesMustNotExist check fail|Can not use conftest\.py|must not exist, but find",
            r"test_function_with_no_check_point_mark:\s*[1-9]",
            r"Parse Error|Validation failed",
            r"remaining to be implemented",
            r"need to be completed|Process status:\s*\d+/\d+",
            r"not found in the failed test list",
            r"expected to be FAILED but actually PASSED",
            r"not documented in the bug analysis file",
            r"\[(?:Test Case|Checkpoint|Documentation|Coverage|Unmarked|Undocumented|Possible Causes|Solution|Bug Analysis Document Format)[^\]]+\]",
        )
        return any(
            any(re.search(pattern, line, re.I) for pattern in signal_patterns)
            for line in evidence_lines
        )

    def _filtered_evidence_lines(self, excerpt: str) -> list[str]:
        keep_patterns = (
            rf"^\s*-?\s*name:\s+{CHECKER_NAME_PATTERN}\b",
            r"^\s*(error|suggestion|details|note|action):",
            r"\[(?:Parse Error|Test Case|Checkpoint|Documentation|Coverage|Unmarked|Undocumented|Possible Causes|Solution|Bug Analysis Document Format)[^\]]*\]",
            r"You need use tool `ReadTextFile`",
            r"Not readed, need ReadTextFile",
            r"FilesMustNotExist check fail|Can not use conftest\.py|must not exist, but find",
            r"test_function_with_no_check_point_mark:\s*[1-9]",
            r"No bin matched for pattern",
            r"KeyError:\s*'FG-",
            r"Traceback|AssertionError|Validation failed|Parse Error",
            r"remaining to be implemented",
            r"need to be completed|Process status:\s*\d+/\d+",
            r"not found in the failed test list",
            r"expected to be FAILED but actually PASSED",
            r"not documented in the bug analysis file",
        )
        drop_patterns = (
            r"^\s*</?think>",
            r"^\s*Tool Calls:",
            r"^\s*Call ID:",
            r"^\s*Args:",
            r"^\s*\[Important\]",
            r"^\s*\[(?:INFO|RETURN|TXT_DATA|DIFF)\]",
            r"^\s*action:\s*Please fix",
            r"^\s*STDOUT:",
            r"^\s*STDERR:",
            r"^\s*Name:\s*(SearchText|FindFiles|ReadTextFile|WriteTextFile|ReplaceText)",
            r"No matches found for",
            r"false positive|already implemented and failing|failing due to the bug",
            r"root cause|具体代码缺陷|修复建议|验证方法",
            r"expected .* got|AssertionError:",
            r"\b(?:Adder|IntegerDivider|ALU754)\.v\b",
            r"\*\*Bug\s*\d+\*\*|Bug-\d+|line\s*\d+.*(output|assign|wire|input)",
            r"\b(?:output|input|wire|assign)\s+(?:\[[^\]]+\]\s+)?[A-Za-z_][A-Za-z0-9_]*",
            r"\b0x[0-9a-f_]+\b",
        )
        kept = []
        for raw_line in excerpt.splitlines():
            line = self._compact_line(raw_line)
            if not line:
                continue
            if any(re.search(pattern, line, re.I) for pattern in drop_patterns):
                continue
            if any(re.search(pattern, line, re.I) for pattern in keep_patterns):
                if line not in kept:
                    kept.append(line)
            if len(kept) >= 24:
                break
        return kept or [self._compact_line(line) for line in excerpt.splitlines() if self._compact_line(line)][:8]

    def _message_content_to_text(self, response: Any) -> str:
        content = getattr(response, "content", response)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or item))
                else:
                    parts.append(str(item))
            return "\n".join(parts)
        return str(content)

    def _parse_llm_hint_yaml(self, content: str) -> list[dict[str, Any]]:
        content = self._strip_think_blocks(content)
        raw_hints = []
        for yaml_text in self._candidate_yaml_texts(content):
            data = self._safe_load_llm_hint_yaml(yaml_text)
            if data is None:
                continue
            raw_hints = self._raw_hints_from_yaml_data(data)
            if raw_hints:
                break
        if not raw_hints:
            return []

        hints = []
        seen = set()
        for raw in raw_hints:
            if not isinstance(raw, dict):
                continue
            normalized = self._normalize_llm_hint(raw)
            if not normalized or normalized["id"] in seen:
                continue
            seen.add(normalized["id"])
            hints.append(normalized)
            if len(hints) >= 5:
                break
        return hints

    def _safe_load_llm_hint_yaml(self, yaml_text: str) -> Any:
        try:
            return yaml.safe_load(yaml_text)
        except yaml.YAMLError:
            repaired = self._repair_invalid_yaml_double_quoted_escapes(yaml_text)
            if repaired == yaml_text:
                return None
            try:
                return yaml.safe_load(repaired)
            except yaml.YAMLError:
                return None

    def _repair_invalid_yaml_double_quoted_escapes(self, text: str) -> str:
        valid_yaml_escapes = set('0abtnvfre "/\\N_LPuxU')
        out: list[str] = []
        in_single = False
        in_double = False
        idx = 0
        while idx < len(text):
            char = text[idx]
            if in_single:
                out.append(char)
                if char == "'" and idx + 1 < len(text) and text[idx + 1] == "'":
                    out.append(text[idx + 1])
                    idx += 2
                    continue
                if char == "'":
                    in_single = False
                idx += 1
                continue

            if in_double:
                if char == "\\" and idx + 1 < len(text):
                    nxt = text[idx + 1]
                    if nxt not in valid_yaml_escapes and nxt not in "\r\n":
                        out.append("\\")
                        out.append("\\")
                        out.append(nxt)
                    else:
                        out.append(char)
                        out.append(nxt)
                    idx += 2
                    continue
                out.append(char)
                if char == '"':
                    in_double = False
                idx += 1
                continue

            out.append(char)
            if char == "'":
                in_single = True
            elif char == '"':
                in_double = True
            idx += 1
        return "".join(out)

    def _raw_hints_from_yaml_data(self, data: Any) -> list[Any]:
        if not data:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            exp = data.get("experience", data)
            if isinstance(exp, dict):
                raw_hints = exp.get("candidate_failure_hints", [])
                return raw_hints if isinstance(raw_hints, list) else []
        return []

    def _candidate_yaml_texts(self, content: str) -> list[str]:
        candidates = []
        stripped = self._strip_markdown_fence(content)
        if stripped:
            candidates.append(stripped)
        for match in re.finditer(r"```(?:yaml|yml)?\s*(.*?)```", content, re.I | re.S):
            block = match.group(1).strip()
            if block:
                candidates.append(block)

        lines = content.splitlines()
        for idx, line in enumerate(lines):
            stripped_line = line.strip()
            if stripped_line == "experience:" or re.match(r"^-\s+id\s*:", stripped_line):
                block = self._trim_yaml_block(lines[idx:])
                if block:
                    candidates.append(block)

        unique = []
        for candidate in candidates:
            text = candidate.strip()
            if text and text not in unique:
                unique.append(text)
        return unique

    def _trim_yaml_block(self, lines: list[str]) -> str:
        if not lines:
            return ""
        first = lines[0].strip()
        collect = []
        if first == "experience:":
            for idx, line in enumerate(lines):
                stripped = line.strip()
                if idx > 0 and stripped and not line.startswith((" ", "\t")) and not stripped.startswith("#"):
                    break
                collect.append(line)
        elif re.match(r"^-\s+id\s*:", first):
            for idx, line in enumerate(lines):
                stripped = line.strip()
                if idx > 0 and stripped and not line.startswith((" ", "\t")) and not stripped.startswith(("-", "#")):
                    break
                collect.append(line)
        return "\n".join(collect).strip()

    def _strip_markdown_fence(self, content: str) -> str:
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines:
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text

    def _strip_think_blocks(self, content: str) -> str:
        return re.sub(r"<think>.*?</think>\s*", "", str(content or ""), flags=re.I | re.S).strip()

    def _normalize_llm_hint(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        raw_id = str(raw.get("id", "")).strip().lower()
        rule_id = re.sub(r"[^a-z0-9_]+", "_", raw_id).strip("_")
        if not rule_id:
            return None
        hint = self._generalize_dut_name(str(raw.get("hint", "")).strip())
        if len(hint) < 20:
            return None
        if not self._contains_chinese_text(hint):
            return None
        if self._is_over_specific_llm_text(hint):
            return None
        patterns = self._drop_over_specific_llm_patterns([
            self._generalize_dut_name(pattern)
            for pattern in self._string_list(raw.get("patterns", []))
        ])
        regexes = self._drop_over_specific_llm_patterns([
            self._generalize_dut_name(pattern)
            for pattern in self._string_list(raw.get("regex", []))
        ], allow_regex=True)
        patterns, regexes = self._strengthen_llm_hint_patterns(patterns, regexes)
        patterns, regexes = self._prune_cross_family_llm_triggers(patterns, regexes)
        if not patterns and not regexes:
            return None
        source = raw.get("source")
        if isinstance(source, dict):
            raw_evidence = self._string_list(source.get("evidence", []))
        else:
            raw_evidence = self._string_list(raw.get("evidence", []))
        evidence = self._drop_over_specific_llm_patterns([
            self._generalize_dut_name(item)
            for item in raw_evidence
        ])
        evidence = [item for item in evidence if self._contains_chinese_text(item)]
        if self._llm_hint_should_be_rejected(rule_id, hint, patterns, regexes, evidence):
            return None
        item: dict[str, Any] = {
            "id": rule_id,
            "priority": self._safe_int(raw.get("priority", 80), 80),
            "hint": hint,
        }
        if patterns:
            item["patterns"] = patterns[:5]
        if regexes:
            item["regex"] = regexes[:3]
        if self.target_stage_index is not None:
            stages = [str(self.target_stage_index)]
        else:
            stages = self._string_list(raw.get("stages", []))
        if stages:
            item["stages"] = stages[:10]
        checkers = [
            checker for checker in self._string_list(raw.get("checkers", []))
            if re.fullmatch(CHECKER_NAME_PATTERN, checker)
        ]
        if checkers:
            item["checkers"] = checkers[:10]
        item["source"] = {
            "kind": "llm_distilled",
            "stage": str(self.target_stage_index) if self.target_stage_index is not None else "",
            "stage_name": self.target_stage_name,
            "evidence": evidence[:5],
        }
        return item

    def _generalize_dut_name(self, text: str) -> str:
        if not self.dut_name:
            return text
        return re.sub(re.escape(self.dut_name), "{DUT}", text, flags=re.I)

    def _contains_chinese_text(self, text: str) -> bool:
        return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", str(text or "")))

    def _drop_over_specific_llm_patterns(
        self,
        values: list[str],
        allow_regex: bool = False,
    ) -> list[str]:
        result = []
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            if self._is_over_specific_llm_text(text):
                continue
            if not allow_regex and self._looks_like_regex_pattern(text):
                continue
            if text not in result:
                result.append(text)
        return result

    def _is_over_specific_llm_text(self, text: str) -> bool:
        value = str(text or "")
        instance_patterns = (
            r"\b(?:unity_test|tests?)[/\\]",
            r"\.py(?::|\b)",
            r"\b[A-Za-z0-9_.\\/-]+\.py(?::\d+(?:-\d+)?)?::[A-Za-z0-9_]+\b",
            r":\d+(?:-\d+)?::",
            r"(?:\bline\s*\d+\b|\u7b2c\s*\d+\s*\u884c)",
            r"\btest_(?!function_with_no_check_point_mark\b)[A-Za-z0-9_]+\s*(?:\(|=|::|:)",
        )
        return any(re.search(pattern, value, re.I) for pattern in instance_patterns)

    def _looks_like_regex_pattern(self, text: str) -> bool:
        return bool(re.search(r"\\[dwsb]|\.\*|\[[^^\]]+\][+*?]|\([^)]*\)\?", str(text or "")))

    def _llm_hint_should_be_rejected(
        self,
        rule_id: str,
        hint: str,
        patterns: list[str],
        regexes: list[str],
        evidence: list[str],
    ) -> bool:
        text = "\n".join([rule_id, hint, *patterns, *regexes, *evidence])
        if any(pattern.search(text) for pattern in LLM_HINT_REJECT_PATTERNS):
            return True
        trigger_text = " ".join([*patterns, *regexes]).lower()
        if (
            "test template structure validation failed" in trigger_text
            or "not all test functions" in trigger_text
            or "properly failing" in trigger_text
        ):
            if any(pattern.search(hint) for pattern in LLM_TEMPLATE_HINT_REJECT_PATTERNS):
                return True
        if (
            "remaining to be implemented" in trigger_text
            and re.search(r"assert\s+False|Not implemented", hint, re.I)
        ):
            return True
        if not self._llm_hint_uses_checker_like_pattern(patterns, regexes):
            return True
        return False

    def _llm_hint_uses_checker_like_pattern(self, patterns: list[str], regexes: list[str]) -> bool:
        if regexes:
            return True
        checker_terms = (
            "parse error",
            "validation failed",
            "test template structure validation failed",
            "not all test functions",
            "remaining to be implemented",
            "not found in the failed test list",
            "expected to be failed but actually passed",
            "not documented in the bug analysis file",
            "checkpoint not marked",
            "checkpoint not found",
            "documentation inconsistency",
            "test coverage gap",
            "unmarked test functions",
            "undocumented failed cases",
            "readtextfile",
            "no bin matched",
            "keyerror: 'fg-",
        )
        return any(any(term in pattern.lower() for term in checker_terms) for pattern in patterns)

    def _strengthen_llm_hint_patterns(
        self,
        patterns: list[str],
        regexes: list[str],
    ) -> tuple[list[str], list[str]]:
        clean_patterns: list[str] = []
        regexes = list(regexes)
        for pattern in patterns:
            placeholder_regex = self._placeholder_pattern_to_regex(pattern)
            if placeholder_regex:
                if placeholder_regex not in regexes:
                    regexes.append(placeholder_regex)
                continue
            clean_patterns.append(pattern)
        patterns = clean_patterns
        if any(self._looks_like_missing_parent_tag_pattern(pattern) for pattern in patterns):
            parent_regex = (
                r"\[Parse Error\].*bug_analysis\.md.*Found (?:FC|CK|BG) tag '<(?:FC|CK|BG)-'.*"
                r"parent (?:FG|FC|CK) tag '<(?:FG|FC|CK)-'.*was not found"
            )
            if parent_regex not in regexes:
                regexes.append(parent_regex)
        return patterns, regexes

    def _placeholder_pattern_to_regex(self, pattern: str) -> str:
        text = str(pattern or "").strip()
        if not re.search(r"\b(?:N|X)\b", text):
            return ""
        if not re.search(r"remaining to be implemented|failed test case", text, re.I):
            return ""
        regex = re.escape(text)
        regex = re.sub(r"(?<![A-Za-z0-9_])(?:N|X)(?![A-Za-z0-9_])", r"\\d+", regex)
        regex = regex.replace(r"\ ", " ")
        return regex

    def _prune_cross_family_llm_triggers(
        self,
        patterns: list[str],
        regexes: list[str],
    ) -> tuple[list[str], list[str]]:
        trigger_text = "\n".join([*patterns, *regexes]).lower()
        has_undocumented = (
            "[undocumented failed cases]" in trigger_text
            or "not documented in the bug analysis file" in trigger_text
        )
        has_remaining = "remaining" in trigger_text and "implemented" in trigger_text
        if has_undocumented and has_remaining:
            patterns = [
                pattern for pattern in patterns
                if not re.search(r"remaining.*implemented", pattern, re.I)
            ]
            regexes = [
                regex for regex in regexes
                if not re.search(r"remaining.*implemented", regex, re.I)
            ]
        return patterns, regexes

    def _looks_like_missing_parent_tag_pattern(self, pattern: str) -> bool:
        text = str(pattern or "").lower()
        return (
            "found " in text
            and " tag '<" in text
            and "parent " in text
            and "was not found" in text
        )

    def _llm_hint_is_covered_by_prior_rules(
        self,
        patterns: list[str],
        regexes: list[str],
        hint: str = "",
        evidence: list[str] | None = None,
    ) -> bool:
        proposed = "\n".join([*patterns, *regexes]).lower()
        if not proposed:
            return False
        evidence = evidence or []
        candidate_discriminators = self._candidate_specialized_discriminators(
            patterns,
            regexes,
            hint,
            evidence,
        )
        matched_rules: list[dict[str, Any]] = []
        for rule in self.prior_rules:
            if not self._safe_bool(rule.get("enabled", True), True):
                continue
            if not self._rule_applies_to_stage(rule):
                continue
            for pattern in rule.get("patterns", []):
                text = str(pattern).strip().lower()
                if text and (text in proposed or any(text in item.lower() for item in patterns)):
                    matched_rules.append(rule)
                    break
            for regex in rule.get("regex", []):
                text = str(regex).strip().lower()
                if text and text in proposed:
                    matched_rules.append(rule)
                    break
            if (
                self._looks_like_missing_parent_tag_pattern(proposed)
                and self._rule_covers_bug_analysis_parent_tag(rule)
            ):
                matched_rules.append(rule)
        if not matched_rules:
            return False
        return not self._candidate_has_new_specialized_delta(candidate_discriminators, matched_rules)

    def _rule_covers_bug_analysis_parent_tag(self, rule: dict[str, Any]) -> bool:
        text = "\n".join([
            *self._string_list(rule.get("patterns", [])),
            *self._string_list(rule.get("regex", [])),
            str(rule.get("hint", "")),
        ]).lower()
        return (
            "bug_analysis" in text
            and "parent" in text
            and "tag" in text
            and "was not found" in text
        )

    def _string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, list):
            values = value
        else:
            return []
        result = []
        for item in values:
            text = str(item).strip()
            if text and text not in result:
                result.append(text)
        return result

    def _extract_checker_name(self, text: str) -> str:
        content = str(text or "")
        match = re.search(rf"\bname:\s*['\"]?({CHECKER_NAME_PATTERN})\b", content)
        if match:
            return match.group(1)
        match = re.search(rf"\b({CHECKER_NAME_PATTERN})\b", content)
        return match.group(1) if match else ""

    def _normalize_failure_signature(self, text: str) -> str:
        compact = self._compact_line(str(text or "")).lower()
        compact = re.sub(r"line\s+\d+", "line N", compact)
        compact = re.sub(r":\d+(?:-\d+)?::", ":N::", compact)
        compact = re.sub(r"\b\d+/\d+\b", "N/N", compact)
        compact = re.sub(r"\b\d+\b", "N", compact)
        return compact

    def _compact_line(self, line: str) -> str:
        return re.sub(r"\s+", " ", line.strip())[:500]

    def _compact_excerpt(self, lines: list[str]) -> str:
        compacted = []
        for line in lines:
            text = line.rstrip()
            if not text:
                continue
            compacted.append(text[:320])
            if len(compacted) >= 80:
                break
        return "\n".join(compacted)

    def _find_default_log(self) -> str | None:
        candidates = []
        for log_dir in (os.path.join(self.workspace, "log"), os.path.join(os.getcwd(), "log")):
            if not os.path.isdir(log_dir):
                continue
            for name in os.listdir(log_dir):
                if name.endswith(".log") or ".log." in name:
                    candidates.append(os.path.join(log_dir, name))
        if not candidates:
            return None
        candidates.sort(key=lambda path: os.path.getmtime(path), reverse=True)
        return candidates[0]

    def _resolve_out_dir(self, out_dir: str | None) -> str:
        if not out_dir:
            return fc.get_abs_path_cwd_ucagent(self.workspace, "experience")
        if os.path.isabs(out_dir):
            return os.path.abspath(out_dir)
        return os.path.abspath(os.path.join(self.workspace, out_dir))

    def _build_index(
        self,
        stages: list[StageExperience],
        prior_rule_audit: dict[str, Any],
        llm_hints: list[dict[str, Any]],
        written: dict[str, str],
    ) -> dict[str, Any]:
        matched_rules = prior_rule_audit.get("matched_rules", [])
        uncovered_events = prior_rule_audit.get("uncovered_failure_events", self.uncovered_failure_events)
        if not uncovered_events and self.uncovered_failure_events:
            uncovered_events = self.uncovered_failure_events
        prior_rule_total_hit_count = prior_rule_audit.get("prior_rule_total_hit_count")
        if prior_rule_total_hit_count is None:
            prior_rule_total_hit_count = sum(
                self._safe_int(rule.get("hit_count", 0), 0)
                for rule in matched_rules
            )
        uncovered_failure_event_count = prior_rule_audit.get("uncovered_failure_event_count", 0)
        if not uncovered_failure_event_count and self.uncovered_failure_event_total:
            uncovered_failure_event_count = self.uncovered_failure_event_total
        llm_distill_event_count = prior_rule_audit.get("llm_distill_event_count", len(uncovered_events))
        if not llm_distill_event_count and self.uncovered_failure_events:
            llm_distill_event_count = len(self.uncovered_failure_events)
        return {
            "version": 1,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "workspace": self.workspace,
            "dut_name": self.dut_name,
            "ucagent_info": self.info_path,
            "history": self.history_dir if os.path.isdir(self.history_dir) else "",
            "log_path": self.log_path or "",
            "selected_stages": [
                {
                    "index": stage.index,
                    "title": stage.title,
                    "score": stage.score,
                    "fail_count": stage.fail_count,
                    "commit": stage.commit_hash,
                    "changed_files": stage.changed_files,
                    "categories": sorted(stage.categories),
                }
                for stage in stages
            ],
            "prior_rule_audit": {
                "rule_count": prior_rule_audit.get("rule_count", 0),
                "matched_rule_count": len(matched_rules),
                "total_hit_count": prior_rule_total_hit_count,
                "unmatched_rule_count": len(prior_rule_audit.get("unmatched_rules", [])),
                "skipped_rule_count": len(prior_rule_audit.get("skipped_rules", [])),
                "uncovered_failure_event_count": uncovered_failure_event_count,
                "llm_distill_event_count": llm_distill_event_count,
                "scope": prior_rule_audit.get("scope", {}),
                "matched_rules": [
                    {
                        "id": rule.get("id", ""),
                        "hit_count": rule.get("hit_count", 0),
                        "hits": rule.get("hits", [])[:5],
                    }
                    for rule in matched_rules
                ],
            },
            "uncovered_failure_events": [
                {
                    "line": event.get("line", ""),
                    "signature": event.get("signature", ""),
                }
                for event in uncovered_events
            ],
            "failure_hints": [
                {
                    "id": rule.get("id", ""),
                    "count": rule.get("hit_count", 0),
                    "examples": rule.get("hits", [])[:5],
                }
                for rule in matched_rules
            ],
            "llm_failure_hints": [
                {
                    "id": hint["id"],
                    "evidence": hint.get("source", {}).get("evidence", []),
                }
                for hint in llm_hints
            ],
            "written": written,
        }

    def _write_text(self, name: str, content: str) -> str:
        path = os.path.join(self.out_dir, name)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        return path

    def _write_json(self, path: str, payload: dict[str, Any]) -> None:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

    def _read_text_file(self, path: str, max_bytes: int) -> str:
        with open(path, "rb") as handle:
            data = handle.read()
        if len(data) > max_bytes:
            data = data[-max_bytes:]
        return data.decode("utf-8", errors="replace")

    def _stage_title(self, raw_stage: dict[str, Any], meta: dict[str, Any], index: int) -> str:
        task = raw_stage.get("task") if isinstance(raw_stage.get("task"), dict) else {}
        title = str(task.get("title") or "").strip()
        if not title:
            commit = meta.get("commit") if isinstance(meta.get("commit"), dict) else {}
            title = str(commit.get("stage_title") or "").strip()
        return title or f"stage-{index}"

    def _stringify(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
        except Exception:
            return str(value)

    def _safe_bool(self, value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        raw = str(value).strip().lower()
        if raw in {"1", "true", "yes", "y", "on"}:
            return True
        if raw in {"0", "false", "no", "n", "off"}:
            return False
        return default

    def _safe_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default


def accumulate_experience(
    workspace: str,
    dut_name: str | None = None,
    log_path: str | None = None,
    out_dir: str | None = None,
    prior_rule_audit: bool = False,
    llm_distill: bool = False,
    llm_model: Any | None = None,
    llm_max_events: int = 20,
    prior_rules: list[Any] | None = None,
    target_stage_index: int | None = None,
    target_stage_name: str | None = None,
    stage_task_info: Any | None = None,
    log_start_offset: int | None = None,
    log_end_offset: int | None = None,
    log_start_identity: dict[str, int] | None = None,
    lang: str = "zh",
) -> dict[str, Any]:
    """Accumulate experience artifacts for ``workspace`` and return a summary."""

    return ExperienceAccumulator(
        workspace=workspace,
        dut_name=dut_name,
        log_path=log_path,
        out_dir=out_dir,
        prior_rule_audit=prior_rule_audit,
        llm_distill=llm_distill,
        llm_model=llm_model,
        llm_max_events=llm_max_events,
        prior_rules=prior_rules,
        target_stage_index=target_stage_index,
        target_stage_name=target_stage_name,
        stage_task_info=stage_task_info,
        log_start_offset=log_start_offset,
        log_end_offset=log_end_offset,
        log_start_identity=log_start_identity,
        lang=lang,
    ).accumulate()
