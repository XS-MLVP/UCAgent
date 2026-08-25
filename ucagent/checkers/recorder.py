# -*- coding: utf-8 -*-
"""Structured record checker with pluggable record types."""

from __future__ import annotations

import builtins
import copy
import json
import os
import re
import sys
from html import escape
from typing import Any, Dict, Optional, Tuple, Type, Union
from urllib.parse import quote

import ucagent.util.functions as fc
from ucagent.checkers.base import Checker, format_stage_args_examples
from ucagent.checkers.static_bug import (
    parse_confirmed_static_bug_links,
    parse_source_location,
)
from ucagent.checkers.toffee_report import parse_bug_label
from ucagent.util.functions import import_class_from_str
from ucagent.util.log import info, warning
from ucagent.util.markdown import ensure_markdown_heading_spacing


class RecordType:
    """Base contract for Recorder type implementations.

    Subclasses implement :meth:`record` and return ``(passed, payload, message)``.
    The payload must be JSON serializable because Recorder persists it in stage data
    even when ``passed`` is false. This allows a type to retain accepted batch
    progress while asking the LLM to continue. Validation failures should return the
    unchanged current payload, or ``None`` when no payload has been accepted.

    Deferred types can disable :attr:`persist_on_check`, enable
    :attr:`persist_on_stage_complete`, and build their final payload in
    :meth:`on_stage_complete`.
    """

    record_type = ""
    persist_on_check = True
    persist_on_stage_complete = False

    def __init__(self, **kwargs):
        self.options = dict(kwargs)
        self.recorder: Optional[Recorder] = None

    def bind(self, recorder: "Recorder") -> "RecordType":
        self.recorder = recorder
        return self

    def record(
        self,
        current_payload: Any,
        is_complete: bool = False,
        **kwargs,
    ) -> Tuple[bool, Any, object]:
        """Validate input and return the complete payload to persist."""
        raise NotImplementedError

    def on_stage_complete(self, current_payload: Any) -> Any:
        """Return the payload to persist from the stage completion callback."""
        return current_payload

    def on_init(self) -> None:
        """Initialize type-specific state when the Recorder stage is entered."""

    def get_template_data(self) -> dict:
        """Return type-specific values used to render stage descriptions and tasks."""
        return {}


class BugRecordType(RecordType):
    """Record every non-zero-confidence Bug declared in an analysis document."""

    record_type = "bug"
    _SEVERITY_VALUES = ("lowest", "low", "medium", "high", "highest")
    _SEVERITY_VALUES_TEXT = ", ".join(_SEVERITY_VALUES)

    def __init__(
        self,
        bug_file: Optional[str] = None,
        static_bug_file: Optional[str] = None,
        output: Optional[str] = None,
        batch_size: int = 10,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.bug_file = "{{DUT}}_bug_analysis.md" if bug_file is None else bug_file
        self.static_bug_file = (
            "{{DUT}}_static_bug_analysis.md"
            if static_bug_file is None
            else static_bug_file
        )
        if not isinstance(self.bug_file, str) or not self.bug_file.strip():
            raise ValueError("BugRecordType 'bug_file' must be a non-empty string.")
        if not isinstance(self.static_bug_file, str) or not self.static_bug_file.strip():
            raise ValueError(
                "BugRecordType 'static_bug_file' must be a non-empty string."
            )
        if output is not None and not isinstance(output, str):
            raise ValueError("BugRecordType 'output' must be a string or null.")
        self.output = output.strip() if output and output.strip() else None
        self.persist_on_stage_complete = self.output is not None
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError("BugRecordType 'batch_size' must be a positive integer.")
        self.batch_size = batch_size
        self._document: Optional[str] = None
        self._expected_bugs: Optional[Dict[str, Dict[str, Any]]] = None
        self._initialization_error: Optional[str] = None

    def _resolve_path(
        self,
        configured_path: str,
        parameter_name: str,
        path_kind: str,
        require_file: bool = True,
    ) -> Tuple[str, str]:
        if self.recorder is None:
            raise ValueError("BugRecordType is not bound to a Recorder.")

        agent = getattr(getattr(self.recorder, "stage_manager", None), "agent", None)
        dut_name = self.recorder.dut_name or getattr(agent, "dut_name", None)
        document = configured_path.strip()
        if "{{DUT}}" in document or "{DUT}" in document:
            if not dut_name:
                raise ValueError(
                    f"Cannot resolve DUT placeholder in '{document}'. Configure the DUT name "
                    f"or pass an explicit '{parameter_name}' through Recorder arguments."
                )
        if dut_name:
            document = document.replace("{{DUT}}", str(dut_name)).replace(
                "{DUT}", str(dut_name)
            )
            document = document.replace(f"{{{dut_name}}}", str(dut_name))
        try:
            document_path = self.recorder.get_path(document)
        except AssertionError as exc:
            raise ValueError(str(exc)) from exc
        if require_file and not os.path.isfile(document_path):
            raise ValueError(
                f"{path_kind.capitalize()} '{document}' does not exist "
                "in the workspace."
            )
        return document, document_path

    @staticmethod
    def _format_document_ref(document: str, ranges: list) -> str:
        unique_ranges = []
        for line_range in ranges:
            normalized = (line_range["start"], line_range["end"])
            if normalized not in unique_ranges:
                unique_ranges.append(normalized)
        range_text = ",".join(
            str(start) if start == end else f"{start}-{end}"
            for start, end in unique_ranges
        )
        return f"{document}:{range_text}"

    @staticmethod
    def _escape_markdown_cell(value: Any) -> str:
        return (
            escape(str(value), quote=False)
            .replace("|", "\\|")
            .replace("\r\n", "<br>")
            .replace("\n", "<br>")
        )

    def _markdown_location_links(self, values: list, output_directory: str) -> str:
        links = []
        for value in values:
            parsed = parse_source_location(value)
            target_path = self.recorder.get_path(parsed["path"])
            relative_target = os.path.relpath(
                target_path,
                output_directory,
            ).replace(os.sep, "/")
            encoded_target = quote(relative_target, safe="/")
            for line_range in parsed["ranges"]:
                start = line_range["start"]
                end = line_range["end"]
                range_text = str(start) if start == end else f"{start}-{end}"
                anchor = f"#L{start}" if start == end else f"#L{start}-L{end}"
                label = self._escape_markdown_cell(
                    f"{parsed['path']}:{range_text}"
                )
                links.append(f"[{label}]({encoded_target}{anchor})")
        return "<br>".join(links)

    def _load_expected_bugs(self) -> Tuple[str, Dict[str, Dict[str, Any]]]:
        document, document_path = self._resolve_path(
            self.bug_file,
            "bug_file",
            "bug analysis document",
            require_file=False,
        )
        static_document, static_document_path = self._resolve_path(
            self.static_bug_file,
            "static_bug_file",
            "static bug analysis document",
        )

        try:
            static_links = parse_confirmed_static_bug_links(static_document_path)
        except (AssertionError, ValueError) as exc:
            raise ValueError(
                f"Failed to parse static bug analysis document '{static_document}': {exc}"
            ) from exc
        if not os.path.isfile(document_path):
            if static_links:
                aliases = [link["alias"] for link in static_links]
                raise ValueError(
                    f"Bug analysis document '{document}' does not exist, but the static Bug "
                    "analysis contains confirmed dynamic links for "
                    f"{fc.list_str_abbr(aliases)}. Restore the dynamic Bug document and its "
                    "verified waveform evidence before recording Bugs."
                )
            return document, {}

        try:
            document_marks, document_blocks = fc.get_unity_chip_doc_marks(
                document_path,
                leaf_node="BG",
                mini_leaf_count=0,
                return_line_block=True,
            )
        except Exception as exc:
            raise ValueError(
                f"Failed to parse bug analysis document '{document}': {exc}"
            ) from exc

        with open(document_path, "r", encoding="utf-8") as bug_document_file:
            document_lines = bug_document_file.read().splitlines()
        bug_occurrences = []
        for line_number, line in enumerate(document_lines, start=1):
            match = re.search(r"<(BG-[^<>]+)>", line)
            if match:
                bug_occurrences.append((match.group(1), line_number))
        ranges_by_label = {}
        for index, (bug_label, start) in enumerate(bug_occurrences):
            end = len(document_lines)
            next_start = (
                bug_occurrences[index + 1][1]
                if index + 1 < len(bug_occurrences)
                else None
            )
            for candidate in range(start + 1, (next_start or len(document_lines) + 1)):
                line = document_lines[candidate - 1]
                if re.search(r"<(?:FG|FC|CK)-[^<>]+>", line) or re.match(
                    r"^\s*#{1,3}\s+", line
                ):
                    end = candidate - 1
                    break
            else:
                if next_start is not None:
                    end = next_start - 1
            while end > start and not document_lines[end - 1].strip():
                end -= 1
            ranges_by_label.setdefault(bug_label, []).append({
                "start": start,
                "end": end,
            })

        expected_bugs: Dict[str, Dict[str, Any]] = {}
        expected_by_label = {}
        label_offsets = {}
        for mark in document_marks:
            parts = mark.split("/")
            try:
                bug_name, confidence = parse_bug_label(parts[-1])
            except ValueError as exc:
                raise ValueError(
                    f"Invalid bug label '{parts[-1]}' in '{document}': {exc}"
                ) from exc
            bug_label = parts[-1]
            if confidence == 0:
                expected_by_label[bug_label.upper()] = None
                continue
            if len(parts) < 4:
                raise ValueError(
                    f"Bug document mark '{mark}' does not contain an FG/FC/CK/BG path."
                )
            ck_path = "/".join(parts[:-1])
            expected_bug = expected_bugs.get(bug_name)
            if expected_bug is None:
                expected_bug = {
                    "CK": [],
                    "confidence": confidence,
                    "alias": [],
                    "ref": [],
                    "document_marks": [],
                    "document_blocks": [],
                    "document_ranges": [],
                    "static_document_ranges": [],
                }
                expected_bugs[bug_name] = expected_bug
            elif abs(expected_bug["confidence"] - confidence) > 1e-9:
                raise ValueError(
                    f"Bug '{bug_name}' has conflicting confidence values in '{document}'. "
                    "Use one confidence value for all of its CK associations."
                )
            if ck_path not in expected_bug["CK"]:
                expected_bug["CK"].append(ck_path)
            expected_bug["document_marks"].append(mark)
            expected_bug["document_blocks"].append(
                copy.deepcopy(document_blocks.get(mark, []))
            )
            label_ranges = ranges_by_label.get(bug_label, [])
            label_index = label_offsets.get(bug_label, 0)
            if label_index >= len(label_ranges):
                raise ValueError(
                    f"Cannot determine the document range for dynamic Bug '<{bug_label}>' "
                    f"in '{document}'."
                )
            expected_bug["document_ranges"].append(label_ranges[label_index])
            label_offsets[bug_label] = label_index + 1
            expected_by_label[bug_label.upper()] = bug_name

        for static_link in static_links:
            for dynamic_tag in static_link["dynamic_bug_tags"]:
                normalized_dynamic_tag = dynamic_tag.upper()
                if normalized_dynamic_tag not in expected_by_label:
                    raise ValueError(
                        f"Static Bug '<{static_link['alias']}>' links to '<{dynamic_tag}>', "
                        f"which is not declared in '{document}'."
                    )
                bug_name = expected_by_label[normalized_dynamic_tag]
                if bug_name is None:
                    continue
                expected_bug = expected_bugs[bug_name]
                if static_link["alias"] not in expected_bug["alias"]:
                    expected_bug["alias"].append(static_link["alias"])
                expected_bug["static_document_ranges"].append(static_link["range"])

        for expected_bug in expected_bugs.values():
            if expected_bug["static_document_ranges"]:
                expected_bug["ref"].append(self._format_document_ref(
                    static_document,
                    expected_bug["static_document_ranges"],
                ))
            expected_bug["ref"].append(self._format_document_ref(
                document,
                expected_bug["document_ranges"],
            ))
        return document, expected_bugs

    def on_init(self) -> None:
        self._document = None
        self._expected_bugs = None
        self._initialization_error = None
        try:
            self._document, self._expected_bugs = self._load_expected_bugs()
        except ValueError as exc:
            self._initialization_error = str(exc)
            warning(f"Failed to initialize BugRecordType: {exc}")

    def _normalize_bug_list(
        self,
        bug_list: Any,
        expected_bugs: Dict[str, Dict[str, Any]],
        argument_name: str,
        allow_legacy_string: bool = False,
    ) -> list:
        if isinstance(bug_list, str):
            if not allow_legacy_string:
                raise ValueError(
                    f"'{argument_name}' must be a JSON array, got str. Pass the "
                    "complete stage_args object as a JSON string when the tool caller "
                    "cannot serialize nested JSON."
                )
            bug_list_text = bug_list.strip()
            if bug_list_text.startswith("```") and bug_list_text.endswith("```"):
                bug_list_lines = bug_list_text.splitlines()
                if len(bug_list_lines) >= 2:
                    bug_list_text = "\n".join(bug_list_lines[1:-1]).strip()
            if bug_list_text.startswith(f"{argument_name}="):
                bug_list_text = bug_list_text.split("=", 1)[1].strip()
            elif bug_list_text.startswith(f"{argument_name}:"):
                bug_list_text = bug_list_text.split(":", 1)[1].strip()
            try:
                bug_list = json.loads(bug_list_text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"'{argument_name}' string must contain a valid JSON array: "
                    f"{exc.msg} at line {exc.lineno} column {exc.colno}."
                ) from exc
        if not isinstance(bug_list, list):
            raise ValueError(
                f"'{argument_name}' must be a JSON array, "
                f"got {type(bug_list).__name__}."
            )

        normalized = []
        seen_names = set()
        for index, raw_bug in enumerate(bug_list):
            label = f"{argument_name}[{index}]"
            if not isinstance(raw_bug, dict):
                raise ValueError(
                    f"{label} must be an object, got {type(raw_bug).__name__}."
                )

            raw_name = raw_bug.get("bug_name")
            if not isinstance(raw_name, str) or not raw_name.strip():
                raise ValueError(f"{label}.bug_name must be a non-empty string.")
            bug_name = raw_name.strip()
            confidence_from_label = None
            if bug_name.strip("<>").startswith("BG-"):
                try:
                    bug_name, confidence_from_label = parse_bug_label(bug_name)
                except ValueError as exc:
                    raise ValueError(f"{label}.bug_name is invalid: {exc}") from exc
            elif "<" in bug_name or ">" in bug_name:
                raise ValueError(
                    f"{label}.bug_name must not contain angle brackets unless it is a "
                    "complete <BG-NAME-XX> tag."
                )
            if bug_name in seen_names:
                raise ValueError(f"Duplicate bug_name '{bug_name}' in {argument_name}.")
            seen_names.add(bug_name)

            expected_bug = expected_bugs.get(bug_name)
            if expected_bug is None:
                raise ValueError(
                    f"{label}.bug_name '{bug_name}' is not declared in "
                    f"'{self.bug_file}'."
                )

            raw_aliases = raw_bug.get("alias")
            if isinstance(raw_aliases, str):
                raw_aliases = [raw_aliases]
            if not isinstance(raw_aliases, list):
                raise ValueError(f"{label}.alias must be a string array.")
            aliases = []
            for raw_alias in raw_aliases:
                if not isinstance(raw_alias, str) or not raw_alias.strip():
                    raise ValueError(
                        f"Every value in {label}.alias must be a non-empty string."
                    )
                alias = raw_alias.strip().strip("<>")
                if alias in aliases:
                    raise ValueError(f"Duplicate alias '{alias}' in {label}.alias.")
                aliases.append(alias)
            missing_aliases = [
                alias for alias in expected_bug["alias"] if alias not in aliases
            ]
            extra_aliases = [
                alias for alias in aliases if alias not in expected_bug["alias"]
            ]
            if missing_aliases or extra_aliases:
                raise ValueError(
                    f"{label}.alias does not exactly match confirmed static Bugs for "
                    f"'{bug_name}'. Missing: {missing_aliases}; extra: {extra_aliases}."
                )

            raw_confidence = raw_bug.get("confidence")
            if raw_confidence is None and confidence_from_label is None:
                raise ValueError(f"{label}.confidence is required.")
            if raw_confidence is None:
                confidence = confidence_from_label
            elif isinstance(raw_confidence, bool) or not isinstance(
                raw_confidence, (int, float)
            ):
                raise ValueError(
                    f"{label}.confidence must be numeric: use 0.0-1.0 or percentage 0-100."
                )
            else:
                confidence = float(raw_confidence)
                if confidence > 1:
                    confidence /= 100.0
                if not 0 <= confidence <= 1:
                    raise ValueError(
                        f"{label}.confidence must be in 0.0-1.0 or percentage 0-100, "
                        f"got {raw_confidence}."
                    )
            if confidence_from_label is not None and abs(
                confidence - confidence_from_label
            ) > 1e-9:
                raise ValueError(
                    f"{label}.confidence ({confidence}) does not match the confidence encoded "
                    f"in bug_name ({confidence_from_label})."
                )
            if abs(confidence - expected_bug["confidence"]) > 1e-9:
                raise ValueError(
                    f"{label}.confidence ({confidence}) does not match "
                    f"'{self.bug_file}' ({expected_bug['confidence']})."
                )

            raw_cks = raw_bug.get("CK", raw_bug.get("ck"))
            if isinstance(raw_cks, str):
                raw_cks = [raw_cks]
            if not isinstance(raw_cks, list) or not raw_cks:
                raise ValueError(f"{label}.CK must be a non-empty string array.")
            resolved_cks = []
            for raw_ck in raw_cks:
                if not isinstance(raw_ck, str) or not raw_ck.strip():
                    raise ValueError(
                        f"Every value in {label}.CK must be a non-empty string."
                    )
                ck = raw_ck.strip().strip("<>")
                if ck in expected_bug["CK"]:
                    matches = [ck]
                elif "/" not in ck:
                    matches = [
                        path for path in expected_bug["CK"] if path.split("/")[-1] == ck
                    ]
                else:
                    matches = []
                if not matches:
                    raise ValueError(
                        f"{label}.CK value '{ck}' is not associated with bug '{bug_name}' in "
                        f"'{self.bug_file}'. Expected: {expected_bug['CK']}."
                    )
                if len(matches) > 1:
                    raise ValueError(
                        f"{label}.CK value '{ck}' is ambiguous. Use one of these full paths: "
                        f"{matches}."
                    )
                if matches[0] not in resolved_cks:
                    resolved_cks.append(matches[0])
            missing_cks = [ck for ck in expected_bug["CK"] if ck not in resolved_cks]
            if missing_cks:
                raise ValueError(
                    f"{label}.CK is missing associations declared for bug '{bug_name}' in "
                    f"'{self.bug_file}': {missing_cks}."
                )

            desc = raw_bug.get("desc")
            if not isinstance(desc, str) or not desc.strip():
                raise ValueError(
                    f"{label}.desc must contain the bug description and root cause."
                )

            raw_locations = raw_bug.get("locations")
            if isinstance(raw_locations, str):
                raw_locations = [raw_locations]
            if not isinstance(raw_locations, list) or not raw_locations:
                raise ValueError(
                    f"{label}.locations must be a non-empty source location array."
                )
            locations = []
            for raw_location in raw_locations:
                try:
                    location = parse_source_location(raw_location)["location"]
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid source location in {label}.locations: {exc}"
                    ) from exc
                if location not in locations:
                    locations.append(location)

            raw_refs = raw_bug.get("ref")
            if isinstance(raw_refs, str):
                raw_refs = [raw_refs]
            if not isinstance(raw_refs, list) or not raw_refs:
                raise ValueError(f"{label}.ref must be a non-empty document reference array.")
            refs = []
            for raw_ref in raw_refs:
                try:
                    ref = parse_source_location(raw_ref)["location"]
                except ValueError as exc:
                    raise ValueError(f"Invalid document reference in {label}.ref: {exc}") from exc
                if ref in refs:
                    raise ValueError(f"Duplicate document reference '{ref}' in {label}.ref.")
                refs.append(ref)
            missing_refs = [ref for ref in expected_bug["ref"] if ref not in refs]
            extra_refs = [ref for ref in refs if ref not in expected_bug["ref"]]
            if missing_refs or extra_refs:
                raise ValueError(
                    f"{label}.ref does not exactly match Bug document records for "
                    f"'{bug_name}'. Missing: {missing_refs}; extra: {extra_refs}."
                )

            if "severity" not in raw_bug:
                raise ValueError(
                    f"{label}.severity is required; allowed values: "
                    f"{self._SEVERITY_VALUES_TEXT} (case-insensitive)."
                )
            raw_severity = raw_bug["severity"]
            if not isinstance(raw_severity, str) or not raw_severity.strip():
                raise ValueError(
                    f"{label}.severity must be a non-empty string; "
                    f"allowed values: {self._SEVERITY_VALUES_TEXT} (case-insensitive)."
                )
            severity = raw_severity.strip()
            if severity.lower() not in self._SEVERITY_VALUES:
                raise ValueError(
                    f"{label}.severity must be one of {self._SEVERITY_VALUES_TEXT} "
                    f"(case-insensitive), got {raw_severity!r}."
                )
            normalized_record = {
                "bug_name": bug_name,
                "alias": list(expected_bug["alias"]),
                "CK": list(expected_bug["CK"]),
                "desc": desc.strip(),
                "locations": locations,
                "severity": severity,
                "confidence": confidence,
                "ref": list(expected_bug["ref"]),
            }
            normalized.append(normalized_record)
        return normalized

    @staticmethod
    def _current_batch_info(
        bug_names: list,
        expected_bugs: Dict[str, Dict[str, Any]],
    ) -> list:
        return [
            {
                "bug_name": name,
                "alias": list(expected_bugs[name]["alias"]),
                "CK": list(expected_bugs[name]["CK"]),
                "confidence": expected_bugs[name]["confidence"],
                "ref": list(expected_bugs[name]["ref"]),
                "document_marks": list(expected_bugs[name]["document_marks"]),
                "document_blocks": copy.deepcopy(expected_bugs[name]["document_blocks"]),
            }
            for name in bug_names
        ]

    def get_template_data(self) -> dict:
        data = {
            "TOTAL_BUGS": "-",
            "COMPLETED_BUGS": "-",
            "LIST_CURRENT_BUGS": [],
        }
        if self._initialization_error is not None:
            data["LIST_CURRENT_BUGS"] = [{"error": self._initialization_error}]
            return data
        if (
            self.recorder is None
            or self.recorder.stage_manager is None
            or self._expected_bugs is None
        ):
            return data
        try:
            current_payload = self.recorder.smanager_get_value(
                self.recorder.data_key,
                None,
            )
            existing_records = (
                self._normalize_bug_list(
                    current_payload,
                    self._expected_bugs,
                    "stored_bug_list",
                    allow_legacy_string=True,
                )
                if current_payload is not None
                else []
            )
        except ValueError as exc:
            warning(f"Failed to build BugRecordType template data: {exc}")
            data["LIST_CURRENT_BUGS"] = [{"error": str(exc)}]
            return data

        completed_names = {record["bug_name"] for record in existing_records}
        remaining_names = [
            name for name in self._expected_bugs if name not in completed_names
        ]
        data["TOTAL_BUGS"] = len(self._expected_bugs)
        data["COMPLETED_BUGS"] = len(completed_names)
        data["LIST_CURRENT_BUGS"] = self._current_batch_info(
            remaining_names[:self.batch_size],
            self._expected_bugs,
        )
        return data

    def record(
        self,
        current_payload: Any,
        is_complete: bool = False,
        bug_list: Optional[list] = None,
        **kwargs,
    ) -> Tuple[bool, Any, object]:
        if self._initialization_error is not None:
            return False, current_payload, {"error": self._initialization_error}
        if self._document is None or self._expected_bugs is None:
            return False, current_payload, {
                "error": (
                    "BugRecordType has not been initialized. Enter the Recorder stage "
                    "before calling Check or Complete."
                )
            }
        document = self._document
        expected_bugs = self._expected_bugs

        existing_records = []
        if current_payload is not None:
            try:
                existing_records = self._normalize_bug_list(
                    current_payload,
                    expected_bugs,
                    "stored_bug_list",
                    allow_legacy_string=True,
                )
            except ValueError as exc:
                return False, current_payload, {"error": str(exc)}
        existing_by_name = {record["bug_name"]: record for record in existing_records}
        expected_names = list(expected_bugs)
        remaining_names = [name for name in expected_names if name not in existing_by_name]
        current_batch = remaining_names[:self.batch_size]
        tool_name = "Complete" if is_complete else "Check"

        def bug_list_call_guidance(candidate_bug_names=None):
            """Build object and JSON-string bug_list examples for the current batch."""
            candidates = list(
                current_batch
                if candidate_bug_names is None
                else candidate_bug_names
            )
            if not candidates:
                return (
                    "No Bug records are pending. Call Complete() without stage_args "
                    "to finish the stage."
                )

            example_name = candidates[0]
            expected_bug = expected_bugs[example_name]
            example_record = {
                "bug_name": example_name,
                "alias": list(expected_bug["alias"]),
                "CK": list(expected_bug["CK"]),
                "desc": "REPLACE_WITH_BUG_DESCRIPTION_AND_SOURCE_LEVEL_ROOT_CAUSE",
                "locations": [
                    "REPLACE_WITH_WORKSPACE_RELATIVE_SOURCE_PATH:START-END"
                ],
                "severity": "REPLACE_WITH_LOWEST_LOW_MEDIUM_HIGH_HIGHEST",
                "confidence": expected_bug["confidence"],
                "ref": list(expected_bug["ref"]),
            }
            object_example, string_example = format_stage_args_examples(
                tool_name,
                {"bug_list": [example_record]},
            )
            return (
                f"Call the {tool_name} tool with the stage_args JSON object. "
                "For this stage, stage_args.bug_list must be a JSON array. "
                "The template below already contains the exact bug_name, alias, CK, confidence, "
                f"and ref values for '{example_name}'. Replace the `desc`, `locations`, and "
                "`severity` placeholders with the analyzed Bug description, source-level root "
                "cause, real workspace-relative source lines, and Bug severity before submitting "
                f"it. Required `severity` accepts {self._SEVERITY_VALUES_TEXT} "
                "(case-insensitive). "
                f"Object template: {object_example} "
                f"JSON-string fallback: {string_example} "
                f"Allowed current-batch bug_name values: {', '.join(candidates)}. "
                "Do not submit Bugs outside the current batch. Pass stage_args directly as shown; "
                "do not use a top-level bug_list field or nest stage_args under args or parameters."
            )

        if bug_list is None:
            if remaining_names:
                return False, existing_records, {
                    "error": (
                        f"{len(remaining_names)} bug(s) from '{document}' have not been recorded. "
                        f"{bug_list_call_guidance()}"
                    ),
                    "progress": f"{len(existing_records)}/{len(expected_names)}",
                    "current_batch": self._current_batch_info(current_batch, expected_bugs),
                }
            return True, existing_records, {
                "message": f"All {len(expected_names)} bug(s) from '{document}' are recorded.",
                "bug_count": len(existing_records),
                "progress": f"{len(existing_records)}/{len(expected_names)}",
            }

        try:
            submitted_records = self._normalize_bug_list(
                bug_list,
                expected_bugs,
                "bug_list",
            )
        except ValueError as exc:
            return False, current_payload, {
                "error": f"{exc} {bug_list_call_guidance()}",
                "current_batch": self._current_batch_info(
                    current_batch,
                    expected_bugs,
                ),
            }

        new_names = [
            record["bug_name"]
            for record in submitted_records
            if record["bug_name"] not in existing_by_name
        ]
        if submitted_records and remaining_names and not new_names:
            return False, current_payload, {
                "error": (
                    "The submitted bug_list only contains bugs that were already recorded. "
                    f"{bug_list_call_guidance()}"
                ),
                "current_batch": self._current_batch_info(current_batch, expected_bugs),
            }
        out_of_batch = [name for name in new_names if name not in current_batch]
        if out_of_batch:
            return False, current_payload, {
                "error": (
                    f"These bug records are not in the current batch: {out_of_batch}. "
                    f"{bug_list_call_guidance()}"
                ),
                "current_batch": self._current_batch_info(current_batch, expected_bugs),
            }

        for record in submitted_records:
            existing_by_name[record["bug_name"]] = record
        merged_records = [
            existing_by_name[name] for name in expected_names if name in existing_by_name
        ]
        remaining_names = [name for name in expected_names if name not in existing_by_name]
        next_batch = remaining_names[:self.batch_size]
        progress = f"{len(merged_records)}/{len(expected_names)}"

        if remaining_names:
            if submitted_records and hasattr(self.recorder.stage_manager, "get_current_stage"):
                self.recorder.reset_continue_fail_count_with_batch_pass()
            message_key = "error" if is_complete or not submitted_records else "success"
            return False, merged_records, {
                message_key: (
                    f"Recorded {len(submitted_records)} bug(s); {len(remaining_names)} bug(s) "
                    f"from '{document}' remain."
                    + (
                        f" {bug_list_call_guidance(next_batch)}"
                        if message_key == "error"
                        else ""
                    )
                ),
                "bug_count": len(merged_records),
                "progress": progress,
                "current_batch": self._current_batch_info(next_batch, expected_bugs),
            }

        return True, merged_records, {
            "message": f"All {len(expected_names)} bug(s) from '{document}' are recorded.",
            "bug_count": len(merged_records),
            "progress": progress,
        }

    def on_stage_complete(self, current_payload: Any) -> Any:
        if self.output is None:
            return current_payload

        if self._initialization_error is not None:
            raise ValueError(self._initialization_error)
        if self._expected_bugs is None:
            raise ValueError(
                "BugRecordType has not been initialized before stage completion."
            )
        expected_bugs = self._expected_bugs
        records = self._normalize_bug_list(
            current_payload if current_payload is not None else [],
            expected_bugs,
            "stored_bug_list",
            allow_legacy_string=True,
        )
        recorded_names = {record["bug_name"] for record in records}
        missing_names = [name for name in expected_bugs if name not in recorded_names]
        if missing_names:
            raise ValueError(
                f"Cannot generate Bug summary before all Bugs are recorded. Missing: "
                f"{missing_names}."
            )

        output_name, output_path = self._resolve_path(
            self.output,
            "output",
            "bug summary output",
            require_file=False,
        )
        workspace_path = os.path.realpath(self.recorder.workspace)
        resolved_output_path = os.path.realpath(output_path)
        try:
            output_is_in_workspace = (
                os.path.commonpath([workspace_path, resolved_output_path])
                == workspace_path
            )
        except ValueError:
            output_is_in_workspace = False
        if not output_is_in_workspace:
            raise ValueError(
                f"Bug summary output '{output_name}' must stay inside the workspace."
            )

        _bug_name, bug_path = self._resolve_path(
            self.bug_file,
            "bug_file",
            "bug analysis document",
            require_file=bool(expected_bugs or records),
        )
        _static_name, static_bug_path = self._resolve_path(
            self.static_bug_file,
            "static_bug_file",
            "static bug analysis document",
        )
        if resolved_output_path in {
            os.path.realpath(bug_path),
            os.path.realpath(static_bug_path),
        }:
            raise ValueError(
                "Bug summary output must not overwrite a Bug analysis source document."
            )

        output_directory = os.path.dirname(resolved_output_path)
        os.makedirs(output_directory, exist_ok=True)
        agent = getattr(getattr(self.recorder, "stage_manager", None), "agent", None)
        dut_name = self.recorder.dut_name or getattr(agent, "dut_name", None)
        title = f"{dut_name} Bug Summary" if dut_name else "Bug Summary"
        markdown_lines = [
            f"# {self._escape_markdown_cell(title)}",
            "",
            f"Total Bugs: {len(records)}",
            "",
            "| Name | Severity | Alias | CK | Analysis | Locations | Confidence | Ref |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for record in records:
            severity = record["severity"]
            aliases = "<br>".join(
                self._escape_markdown_cell(alias) for alias in record["alias"]
            )
            ck_paths = "<br>".join(
                self._escape_markdown_cell(ck) for ck in record["CK"]
            )
            markdown_lines.append(
                "| "
                + " | ".join([
                    self._escape_markdown_cell(record["bug_name"]),
                    self._escape_markdown_cell(severity),
                    aliases,
                    ck_paths,
                    self._escape_markdown_cell(record["desc"]),
                    self._markdown_location_links(
                        record["locations"],
                        output_directory,
                    ),
                    self._escape_markdown_cell(record["confidence"]),
                    self._markdown_location_links(
                        record["ref"],
                        output_directory,
                    ),
                ])
                + " |"
            )

        with open(resolved_output_path, "w", encoding="utf-8") as summary_file:
            summary_file.write(
                ensure_markdown_heading_spacing("\n".join(markdown_lines) + "\n")
            )
        info(
            f"Recorder generated Bug summary with {len(records)} record(s) at "
            f"'{output_name}'."
        )
        return records


class LaunchRecordType(RecordType):
    """Record configured launch tasks only after the stage completes."""

    record_type = "launch"
    persist_on_check = False
    persist_on_stage_complete = True

    def __init__(self, task_list: Optional[list] = None, **kwargs):
        super().__init__(**kwargs)
        self.configured_payload = {
            **({"task_list": copy.deepcopy(task_list)} if task_list is not None else {}),
            **copy.deepcopy(kwargs),
        }

    def record(
        self,
        current_payload: Any,
        is_complete: bool = False,
        **kwargs,
    ) -> Tuple[bool, Any, object]:
        task_list = self.configured_payload.get("task_list", [])
        return True, current_payload, {
            "message": "Launch recording is deferred until the stage completes.",
            "task_count": (
                len(task_list) if isinstance(task_list, list) else 0
            ),
        }

    def on_stage_complete(self, current_payload: Any) -> Any:
        return copy.deepcopy(self.configured_payload)


BUILTIN_RECORD_TYPES: Dict[str, Type[RecordType]] = {
    "bug": BugRecordType,
    "launch": LaunchRecordType,
}


class Recorder(Checker):
    """Checker that persists structured information through a pluggable type."""

    def __init__(
        self,
        type: Union[str, Type[RecordType]] = "bug",
        data_key: Optional[str] = None,
        type_args: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        cfg = kwargs.pop("cfg", None)
        if cfg is not None:
            self.update_dut_name(cfg)
        if isinstance(type, str):
            type_name = type.strip()
            if not type_name:
                raise ValueError("Recorder 'type' must not be empty.")
            record_type_class = BUILTIN_RECORD_TYPES.get(type_name.lower())
            if record_type_class is None:
                checker_module = sys.modules.get("ucagent.checkers")
                record_type_class = import_class_from_str(type_name, checker_module)
        elif isinstance(type, builtins.type) and issubclass(type, RecordType):
            record_type_class = type
        else:
            raise TypeError("Recorder 'type' must be a built-in type name or a RecordType subclass.")
        if not isinstance(record_type_class, builtins.type) or not issubclass(
            record_type_class, RecordType
        ):
            raise TypeError(
                f"Recorder type '{type_name if isinstance(type, str) else type}' must resolve "
                "to a RecordType subclass."
            )

        record_type_args = dict(type_args or {})
        for key, value in kwargs.items():
            record_type_args.setdefault(key, value)
        self.type_handler = record_type_class(**record_type_args).bind(self)
        self.record_type = (
            str(self.type_handler.record_type or "").strip()
            or f"{record_type_class.__module__}.{record_type_class.__qualname__}"
        )
        safe_type = re.sub(r"[^A-Za-z0-9]+", "_", self.record_type).strip("_").upper()
        self.data_key = data_key or f"_RECORDER_{safe_type or 'DATA'}"
        self._sync_callback_stage = None

    def get_template_data(self) -> dict:
        return self.type_handler.get_template_data()

    def on_init(self):
        self.type_handler.on_init()
        return super().on_init()

    def set_stage(self, stage):
        super().set_stage(stage)
        self._register_sync_callback()
        return self

    def set_stage_manager(self, manager):
        super().set_stage_manager(manager)
        self._register_sync_callback()
        return self

    def _register_sync_callback(self) -> None:
        if (
            self.stage_manager is not None
            and self.stage is not None
            and self._sync_callback_stage is not self.stage
        ):
            self.stage.append_on_complete_callback(self._sync_to_masters)
            self._sync_callback_stage = self.stage

    def do_check(self, timeout=0, is_complete=False, **kwargs) -> Tuple[bool, object]:
        """Record structured information for the configured type.

        The built-in ``bug`` type reads every BG entry from its configured bug
        analysis document and accepts records for the current batch:
        ``Check(stage_args={'bug_list': [{'bug_name': 'overflow_bug', 'alias': [],
        'CK': ['CK-OVERFLOW'],
        'desc': 'Description and root cause', 'locations': ['rtl/dut.sv:128-229'],
        'severity': 'high', 'confidence': 0.76,
        'ref': ['DUT_bug_analysis.md:30-42']}]})``.
        Configure it with dynamic and static Bug document paths plus ``batch_size``.
        When ``output`` is a non-empty workspace-relative path, the Bug type writes a
        Markdown summary with line-linked source and document references from the
        stage completion callback.

        The built-in ``launch`` type takes its complete payload from Recorder checker
        arguments, including an ordered ``task_list``. Its Check and Complete calls
        are no-ops; it stores and reports the configured payload only from the stage
        completion callback.
        """
        current_payload = self.smanager_get_value(self.data_key, None)
        result = self.type_handler.record(
            copy.deepcopy(current_payload),
            is_complete=is_complete,
            **kwargs,
        )
        if not isinstance(result, tuple) or len(result) != 3:
            return False, {
                "error": (
                    f"Recorder type '{self.record_type}' must return "
                    "(passed, payload, message)."
                )
            }
        passed, payload, message = result
        if not isinstance(passed, bool):
            return False, {
                "error": f"Recorder type '{self.record_type}' returned a non-boolean pass status."
            }
        try:
            json.dumps(payload, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            return False, {
                "error": f"Recorder type '{self.record_type}' returned a non-JSON payload: {exc}"
            }
        if self.type_handler.persist_on_check and (
            passed or payload is not None or current_payload is not None
        ):
            self.smanager_set_value(self.data_key, copy.deepcopy(payload))
            info(
                f"Recorder cached type '{self.record_type}' data under manager key "
                f"'{self.data_key}'."
            )
        return passed, message

    def _sync_to_masters(self, completed_stage) -> None:
        stage_name = getattr(completed_stage, "name", None)
        payload = self.smanager_get_value(self.data_key, None)
        if self.type_handler.persist_on_stage_complete:
            try:
                payload = self.type_handler.on_stage_complete(copy.deepcopy(payload))
                json.dumps(payload, ensure_ascii=False, allow_nan=False)
            except Exception as exc:
                warning(
                    f"Recorder type '{self.record_type}' failed to build its stage "
                    f"completion payload; Master synchronization was aborted: {exc}"
                )
                return
            self.smanager_set_value(self.data_key, copy.deepcopy(payload))
            info(
                f"Recorder cached type '{self.record_type}' data under manager key "
                f"'{self.data_key}' after stage completion."
            )

        agent = getattr(self.stage_manager, "agent", None)
        pdb = getattr(agent, "pdb", None)
        master_clients = getattr(pdb, "_master_clients", {}) if pdb is not None else {}
        if not master_clients:
            info(
                f"Recorder skipped Master synchronization for type '{self.record_type}' "
                f"under key '{self.data_key}' from stage '{stage_name}': no Master "
                "clients are configured."
            )
            return

        configured_count = len(master_clients)
        attempted_count = 0
        succeeded_count = 0
        failed_count = 0
        skipped_count = 0
        info(
            f"Recorder starting Master synchronization for type '{self.record_type}' "
            f"under key '{self.data_key}' from stage '{stage_name}' with "
            f"{configured_count} configured client(s)."
        )

        stage_index = None
        try:
            stage_index = self.stage_manager.stages.index(completed_stage)
        except (AttributeError, ValueError):
            pass
        report = {
            "schema_version": 1,
            "record_type": self.record_type,
            "data_key": self.data_key,
            "payload": copy.deepcopy(payload),
            "source": {
                "dut_name": self.dut_name or getattr(agent, "dut_name", None),
                "workspace": self.workspace,
                "stage_name": stage_name,
                "stage_index": stage_index,
            },
        }
        for master_url, client in list(master_clients.items()):
            if not getattr(client, "is_running", False):
                skipped_count += 1
                warning(
                    f"Recorder skipped Master synchronization to '{master_url}' for type "
                    f"'{self.record_type}': the client is not running."
                )
                continue
            report_records = getattr(client, "report_records", None)
            if not callable(report_records):
                skipped_count += 1
                warning(
                    f"Recorder skipped Master synchronization to '{master_url}' for type "
                    f"'{self.record_type}': the client does not support record reports."
                )
                continue
            attempted_count += 1
            info(
                f"Recorder sending type '{self.record_type}' records under key "
                f"'{self.data_key}' to Master '{master_url}'."
            )
            try:
                ok, message = report_records(copy.deepcopy(report))
            except Exception as exc:
                failed_count += 1
                warning(
                    f"Recorder failed to synchronize type '{self.record_type}' records to "
                    f"Master '{master_url}': {exc}"
                )
                continue
            if ok:
                succeeded_count += 1
                info(
                    f"Recorder synchronized type '{self.record_type}' records to Master "
                    f"'{master_url}' successfully: {message}"
                )
            else:
                failed_count += 1
                warning(
                    f"Recorder failed to synchronize type '{self.record_type}' records to "
                    f"Master '{master_url}': {message}"
                )

        summary = (
            f"Recorder Master synchronization finished for type '{self.record_type}' under "
            f"key '{self.data_key}' from stage '{stage_name}': configured="
            f"{configured_count}, attempted={attempted_count}, succeeded={succeeded_count}, "
            f"failed={failed_count}, skipped={skipped_count}."
        )
        if failed_count or skipped_count:
            warning(summary)
        else:
            info(summary)
