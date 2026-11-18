"""Validate source-grounded testcase, coverpoint and normative-rule handoff links."""

from __future__ import annotations

import fnmatch
import hashlib
import re
from functools import lru_cache
from pathlib import Path

import yaml

from . import xiangshan_bundle as bundle
from .checkers.act4_asset_consistency import parse_mapping_targets


def citation(root: Path, record: dict, source=None) -> dict:
    """Validate an exact, bounded citation and attach the current source identity."""
    if not isinstance(record, dict) or set(record) != {"path", "lines", "quote"}:
        raise ValueError("Evidence requires path, lines and an exact quote")
    path = bundle.safe_path(root, record["path"])
    if source is None:
        content = path.read_bytes()
        lines, digest = content.decode("utf-8").splitlines(), hashlib.sha256(content).hexdigest()
    else:
        lines, digest = source(record["path"])
    bounds = record["lines"]
    if (not isinstance(bounds, list) or len(bounds) != 2
            or any(type(number) is not int for number in bounds)
            or not 1 <= bounds[0] <= bounds[1] <= len(lines) or bounds[1] - bounds[0] >= 100):
        raise ValueError(f"Evidence needs an existing 1..100-line range: {record['path']}")
    if record["quote"] != "\n".join(lines[bounds[0] - 1:bounds[1]]):
        raise ValueError(f"Evidence quote changed: {record['path']}:{bounds}")
    return {**record, "sha256": digest}


def records_by_id(records: list, label: str, key: str = "id") -> dict:
    """Reject empty, duplicate or malformed identity lists instead of silently overwriting."""
    if not isinstance(records, list) or not records:
        raise ValueError(f"{label} must be a nonempty list")
    indexed = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get(key), str) or not record[key].strip():
            raise ValueError(f"{label} entries require {key}")
        if record[key] in indexed:
            raise ValueError(f"Duplicate {label} identity: {record[key]}")
        indexed[record[key]] = record
    return indexed


def require_text(record: dict, *fields: str) -> None:
    """Require substantive task descriptions without accepting empty placeholder fields."""
    for field in fields:
        value = record.get(field)
        if not isinstance(value, str) or not value.strip() or value.strip().lower() in {"todo", "tbd", "unknown", "n/a"}:
            raise ValueError(f"Provide a specific {field} for {record.get('id', record.get('path', 'record'))}")


def testcase_inventory(root: Path, paths: list[str]) -> dict:
    """Inventory every native ACT testcase label, or explicit testcase comment/file boundary."""
    inventory = {}
    for name in paths:
        path = bundle.safe_path(root, f"tests/{name}")
        lines = path.read_text(encoding="utf-8").splitlines()
        anchors = []
        for number, line in enumerate(lines, 1):
            match = re.fullmatch(r"\s*([A-Za-z_.$][\w.$]*_cg_[\w.$]+):\s*(?://.*)?", line)
            if match and not match[1].endswith("_str"):
                anchors.append((number, match[1]))
        if not anchors:
            anchors = [(number, f"line-{number}") for number, line in enumerate(lines, 1)
                       if re.match(r"\s*(?:#|//)\s*Testcase\b", line)]
        if not anchors:
            anchors = [(1, "file")]
        cases = []
        for index, (number, identifier) in enumerate(anchors):
            end = anchors[index + 1][0] - 1 if index + 1 < len(anchors) else len(lines)
            cases.append({"id": identifier, "lines": [number, end]})
        records_by_id(cases, f"testcases in {name}")
        inventory[name] = {"sha256": bundle.sha256(path), "cases": cases}
    return inventory


def validate_trace(root: Path, document: dict, paths: list[str]) -> dict:
    """Require total testcase coverage and real source evidence for every static mapping edge."""
    @lru_cache(maxsize=32)
    def source(name):
        """Read bounded working-set evidence once per validation, never across checks."""
        content = bundle.safe_path(root, name).read_bytes()
        return content.decode("utf-8").splitlines(), hashlib.sha256(content).hexdigest()

    @lru_cache(maxsize=16)
    def native_mapping(name):
        """Parse each immutable native mapping once within this validation."""
        return yaml.safe_load("\n".join(source(name)[0]))

    @lru_cache(maxsize=8)
    def coverage_groups(name):
        """Index source group boundaries once without keeping all coverage files in memory."""
        text = "\n".join(source(name)[0])
        text = re.sub(r"/\*.*?\*/|//[^\n]*", lambda match: re.sub(r"[^\n]", " ", match[0]), text, flags=re.DOTALL)
        result = {}
        for match in re.finditer(r"\bcovergroup\s+(\w+)\b.*?\bendgroup\b", text, re.DOTALL):
            start = text[:match.start()].count("\n") + 1
            result.setdefault(match[1], []).append((start, start + match[0].count("\n"), match[0]))
        return result

    if document.get("schema_version") != 1:
        raise ValueError("traceability.yaml requires schema_version: 1")
    tests = records_by_id(document.get("tests"), "tests", "path")
    points = records_by_id(document.get("coverpoints"), "coverpoints")
    rules = records_by_id(document.get("rules"), "norm rules")
    inventory = testcase_inventory(root, paths)
    if set(tests) != set(paths):
        raise ValueError("traceability.tests must describe every included .S exactly once, without excluded tests")
    for identifier, rule in rules.items():
        require_text(rule, "description")
        definition = citation(root, rule.get("definition"), source)
        if not re.search(rf"(?<![\w.-]){re.escape(identifier)}(?![\w.-])", definition["quote"]):
            raise ValueError(f"Norm rule ID {identifier} is absent from its definition citation")
        rule["definition"] = definition
    used_rules, used_points = set(), set()
    for identifier, point in points.items():
        require_text(point, "intent")
        if not re.fullmatch(r"[A-Za-z_][\w$]*/[A-Za-z_][\w$]*", identifier):
            raise ValueError(f"Use exact covergroup/coverpoint IDs: {identifier}")
        group, name = identifier.split("/")
        definition = citation(root, point.get("definition"), source)
        if not re.search(rf"\b{re.escape(name)}\s*:\s*(?:coverpoint|cross)\b", definition["quote"]):
            raise ValueError(f"Coverpoint declaration not present in cited source: {identifier}")
        group_source = citation(root, point.get("group"), source)
        if not re.search(rf"\bcovergroup\s+{re.escape(group)}\b", group_source["quote"]):
            raise ValueError(f"Covergroup declaration missing: {identifier}")
        group_path = bundle.safe_path(root, group_source["path"])
        blocks = coverage_groups(group_source["path"]).get(group, [])
        target_path = bundle.safe_path(root, definition["path"])
        applicable = False
        for start, end, block in blocks:
            if target_path == group_path and start <= definition["lines"][0] <= definition["lines"][1] <= end:
                applicable = True
            pending = [(group_path, block)]
            visited = set()
            while pending:
                parent, text = pending.pop()
                for include in re.findall(r'`include\s+"([^"\n]+)"', text):
                    candidates = [parent.parent / include, root / include, root / "coverpoints" / include]
                    for candidate in candidates:
                        if not candidate.is_relative_to(root):
                            continue
                        child = bundle.safe_path(root, str(candidate.relative_to(root)))
                        if not child.is_file() or child in visited:
                            continue
                        visited.add(child)
                        if len(visited) > 100:
                            raise ValueError(f"Coverage include graph is too large for {identifier}; provide a bounded selected definition")
                        applicable |= child == target_path
                        pending.append((child, child.read_text(encoding="utf-8")))
                        break
        if not applicable:
            raise ValueError(f"Coverpoint declaration is not in the named covergroup or its includes: {identifier}")
        point.update(definition=definition, group=group_source)
        links = records_by_id(point.get("rules"), f"norm links for {identifier}")
        for rule_id, link in links.items():
            if rule_id not in rules:
                raise ValueError(f"Undefined norm rule {rule_id} for {identifier}")
            require_text(link, "reason")
            evidence = citation(root, link.get("evidence"), source)
            if link.get("kind") == "native_mapping":
                mapping = native_mapping(evidence["path"])
                found = False
                for entry in mapping.get("normative_rule_definitions", []) if isinstance(mapping, dict) else []:
                    if not isinstance(entry, dict):
                        raise ValueError(f"Malformed norm mapping entry in {evidence['path']}")
                    names = entry.get("names", entry.get("name", []))
                    names = [part.strip() for part in names.split(",")] if isinstance(names, str) else names
                    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
                        raise ValueError(f"Norm mapping names must be strings in {evidence['path']}")
                    names = [part.strip() for name in names for part in name.split(",")]
                    targets, _ = parse_mapping_targets(entry.get("coverpoint"))
                    if rule_id in names and any(fnmatch.fnmatchcase(group, target["covergroup"] or "")
                            and fnmatch.fnmatchcase(name, target["coverpoint"] or "") for target in targets):
                        found = True
                if not found or rule_id not in evidence["quote"]:
                    raise ValueError(f"Native norm mapping does not connect {identifier} to {rule_id}")
            elif link.get("kind") == "isa_reasoned":
                if evidence != rules[rule_id]["definition"]:
                    raise ValueError(f"ISA-derived mapping must cite the declared norm definition: {rule_id}")
            else:
                raise ValueError("Norm links require kind: native_mapping or isa_reasoned; do not invent upstream mappings")
            link["evidence"] = evidence
            used_rules.add(rule_id)
    for name, test in tests.items():
        require_text(test, "summary", "preconditions", "setup", "exercise", "check", "limitations")
        cases = records_by_id(test.get("cases"), f"cases for {name}")
        expected = records_by_id(inventory[name]["cases"], f"source cases for {name}")
        if cases.keys() != expected.keys():
            raise ValueError(f"Describe every testcase in {name}; missing={sorted(expected.keys() - cases.keys())[:12]}, extra={sorted(cases.keys() - expected.keys())[:12]}")
        for identifier, case in cases.items():
            require_text(case, "description", "stimulus", "expected")
            mapped = case.get("coverpoints")
            if not isinstance(mapped, list) or not mapped or any(not isinstance(point, str) for point in mapped) or len(set(mapped)) != len(mapped) or not set(mapped) <= points.keys():
                raise ValueError(f"Testcase {name}:{identifier} needs unique defined coverpoint IDs")
            evidence = citation(root, case.get("evidence"), source)
            if evidence["path"] != f"tests/{name}" or not expected[identifier]["lines"][0] <= evidence["lines"][0] <= evidence["lines"][1] <= expected[identifier]["lines"][1]:
                raise ValueError(f"Testcase evidence must be inside its actual source block: {name}:{identifier}")
            if "_cg_" in identifier:
                group = identifier.split("_cg_", 1)[0] + "_cg"
                if any(point.split("/", 1)[0] != group for point in mapped):
                    raise ValueError(f"Testcase coverpoints must belong to its native covergroup: {name}:{identifier}")
                direct = any(identifier.startswith(point.replace("/", "_") + "_") or identifier == point.replace("/", "_") for point in mapped)
                if not direct:
                    count = points.get(group + "/cp_asm_count") if group + "/cp_asm_count" in mapped else None
                    instruction = re.search(r'\bins\.ins_str\s*==\s*"([^"\n]+)"', count["definition"]["quote"]) if count else None
                    require_text(case, "mapping_reason")
                    if not instruction or not re.search(rf"(?m)^\s*{re.escape(instruction[1])}(?:\s|$)", evidence["quote"]):
                        raise ValueError(f"Expanded testcase labels require same-group cp_asm_count and the actual instruction in source evidence: {name}:{identifier}")
            case.update(evidence=evidence, lines=expected[identifier]["lines"])
            used_points.update(mapped)
        test["source_sha256"] = inventory[name]["sha256"]
    if used_points != points.keys() or used_rules != rules.keys():
        raise ValueError("Traceability may only declare coverpoints and rules linked to delivered tests")
    return {"schema_version": 1, "evidence_level": "static_design_mapping_not_measured_coverage",
            "tests": list(tests.values()), "coverpoints": list(points.values()), "rules": list(rules.values())}
