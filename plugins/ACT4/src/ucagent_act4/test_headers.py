"""Shared static preflight of native ACT test-selection headers, not DUT eligibility."""

from __future__ import annotations

import re

import yaml


class _HeaderLoader(yaml.SafeLoader):
    """Reject duplicate fields instead of silently replacing test constraints."""

    def construct_mapping(self, node, deep=False):
        """Build a mapping only when each YAML field has one unambiguous definition."""
        mapping = super().construct_mapping(node, deep=deep)
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate header field {key!r}", key_node.start_mark)
            seen.add(key)
        return mapping


def inspect_test_header(text: str, path: str) -> dict:
    """Return native header metadata and located errors without executing untrusted sources.

    Preserve YAML nesting after removing one comment prefix. This preflight covers
    selection syntax only; the pinned ACT parser, UDB selection and actual build
    remain authoritative for target eligibility and instruction support.
    """
    findings = []
    result = {"file": path, "metadata": {}, "findings": findings}

    def issue(code, message, line=1, field=None):
        """Attach a source location and an explicit regeneration action to one defect."""
        record = {"severity": "error", "check": code, "file": path, "line": line,
                  "message": message,
                  "next_action": "Fix the native generator/header source, regenerate this test, then rerun validation."}
        if field is not None:
            record["field"] = field
        findings.append(record)

    markers = {}
    for name in ("START_TEST_CONFIG", "END_TEST_CONFIG"):
        markers[name] = list(re.finditer(
            rf"^[ \t]*(?:#+|//+|/\*+|\*+)[ \t]*{name}\b[^\n]*", text, re.MULTILINE))
    if any(len(matches) != 1 for matches in markers.values()):
        issue("test_config_markers", "Require exactly one native START_TEST_CONFIG / END_TEST_CONFIG block")
        return result
    start, end = markers["START_TEST_CONFIG"][0], markers["END_TEST_CONFIG"][0]
    first_line = text.count("\n", 0, start.start()) + 1
    if end.start() <= start.end():
        issue("test_config_order", "END_TEST_CONFIG must follow START_TEST_CONFIG", first_line)
        return result
    prefix = re.sub(r"/\*.*?\*/", "", text[:start.start()], flags=re.DOTALL)
    if any(line.strip() and not line.lstrip().startswith(("#", "//", "/*", "*"))
           for line in prefix.splitlines()):
        issue("test_config_order", "Place the test header before assembly code", first_line)
    body = text[start.end():end.start()].splitlines()[1:]
    header_lines = []
    for offset, line in enumerate(body, first_line + 1):
        stripped = line.lstrip()
        if stripped and not stripped.startswith(("#", "//", "*")):
            issue("test_config_comment", "Header YAML must remain inside assembly/C comments", offset)
        header_lines.append(re.sub(r"^\s*(?:#|//|\*)", "", line, count=1))
    try:
        header = yaml.load("\n".join(header_lines), Loader=_HeaderLoader)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        issue("test_config_parse", f"Invalid header YAML: {getattr(error, 'problem', str(error))}",
              first_line + 1 + (mark.line if mark else 0))
        return result
    if not isinstance(header, dict):
        issue("test_config_schema", "Test header must be a nonempty YAML mapping", first_line)
        return result
    allowed = {"REQUIRED_EXTENSIONS", "FORBIDDEN_EXTENSIONS", "MARCH", "MIN_HARTS", "params", "NEEDS_SIGNATURE"}
    for field in header:
        if field not in allowed:
            issue("test_config_field", f"Unknown native test header key: {field}", first_line, str(field))
    required = header.get("REQUIRED_EXTENSIONS")
    valid_extensions = isinstance(required, list) and bool(required)
    if valid_extensions:
        for requirement in required:
            choices = requirement if isinstance(requirement, list) else [requirement]
            valid_extensions = valid_extensions and bool(choices) and all(
                isinstance(choice, str) and bool(choice.strip()) and not re.search(r"\s", choice)
                for choice in choices)
    if not valid_extensions:
        issue("test_config_extensions", "REQUIRED_EXTENSIONS needs a nonempty list of names or nonempty OR lists",
              first_line, "REQUIRED_EXTENSIONS")
    forbidden = header.get("FORBIDDEN_EXTENSIONS", [])
    if not isinstance(forbidden, list) or any(
            not isinstance(value, str) or not value.strip() or re.search(r"\s", value) for value in forbidden):
        issue("test_config_extensions", "FORBIDDEN_EXTENSIONS must be a list of extension names",
              first_line, "FORBIDDEN_EXTENSIONS")
    march = header.get("MARCH")
    if not isinstance(march, str) or not re.fullmatch(r"rv(?:32|64|\$\{XLEN\})[ieg][a-z0-9_]*", march):
        issue("test_config_march", "MARCH must be a native rv32/rv64/rv${XLEN} compiler ISA string",
              first_line, "MARCH")
    harts = header.get("MIN_HARTS", 1)
    if type(harts) is not int or harts < 1:
        issue("test_config_harts", "MIN_HARTS must be a positive integer", first_line, "MIN_HARTS")
    if type(header.get("NEEDS_SIGNATURE", True)) is not bool:
        issue("test_config_signature", "NEEDS_SIGNATURE must be a YAML boolean", first_line, "NEEDS_SIGNATURE")
    params = header.get("params", {})
    if not isinstance(params, dict) or any(
            not isinstance(name, str) or not name.strip() or type(value) not in {int, bool, str}
            for name, value in params.items()):
        issue("test_config_params", "params must map UDB names to integer, boolean or string constraints",
              first_line, "params")
    if not findings:
        result["metadata"] = header
    return result
