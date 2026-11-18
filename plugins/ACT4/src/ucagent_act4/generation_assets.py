"""Validate upstream-native plans, parameter mappings, and contribution file policy."""

from __future__ import annotations

import csv
import fnmatch
import io
import json
from pathlib import Path
import re
import subprocess

import yaml
from jsonschema import Draft202012Validator

from .checkers.act4_asset_consistency import parse_mapping_targets, scan_systemverilog
from .generation_inputs import load_rules, native_plan_path
from .test_headers import inspect_test_header
from .xiangshan_bundle import safe_path


UNPRIVILEGED_EXTENSION_PATHS = (
    "generators/coverage/src/covergroupgen/templates/*.sv",
    "generators/testgen/src/testgen/coverpoints/*.py",
    "generators/testgen/src/testgen/formatters/types/*.py",
    "framework/src/act/fcov/disassemble.svh",
    "testplans/coverage/instruction_formats.csv",
)


def plan_records(path: Path, kind: str, suite: str, schema: Path | None = None) -> dict[str, dict]:
    """Read native plan identities without confusing instruction columns and privileged rows."""
    native_plan_path(suite, kind)
    records = {}
    if kind == "privileged":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if schema is not None:
            definition = json.loads(schema.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(definition)
            Draft202012Validator(definition).validate(data)
        if not isinstance(data, dict) or data.get("suite") != suite or not isinstance(data.get("coverpoints"), list):
            raise ValueError(f"{path}: require the exact suite and a coverpoints array")
        for entry in data["coverpoints"]:
            if not isinstance(entry, dict):
                raise ValueError(f"{path}: coverpoint entries must be objects")
            if "heading" in entry or not entry.get("name"):
                continue
            if not isinstance(entry["name"], str):
                raise ValueError(f"{path}: coverpoint names must be strings")
            names = [name.strip() for name in entry["name"].splitlines() if name.strip()]
            if not names or any(not re.fullmatch(r"(?:cp|cr|cmp)_\w+", name) for name in names):
                raise ValueError(f"{path}: coverpoint rows need real coverage identifiers")
            for name in names:
                if name in records:
                    raise ValueError(f"{path}: duplicate coverpoint {name}")
                records[name] = entry
    else:
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames or []
            if fields[:4] != ["Instruction", "Type", "RV32", "RV64"] or len(fields) != len(set(fields)):
                raise ValueError(f"{path}: require unique native Instruction,Type,RV32,RV64 columns")
            points = fields[5:] if fields[4:5] == ["ExtraExtensions"] else fields[4:]
            if not points or "ExtraExtensions" in points or any(not name.strip() for name in points):
                raise ValueError(f"{path}: require coverpoint columns after the optional ExtraExtensions column")
            for number, row in enumerate(reader, 2):
                instruction = (row.get("Instruction") or "").strip()
                if not instruction and all(not str(value or "").strip() for value in row.values()):
                    continue
                if (None in row or any(value is None for value in row.values()) or not instruction
                        or not re.fullmatch(r"[A-Za-z0-9_.]+", instruction) or not row["Type"].strip()
                        or any(row[key] not in {"", "x"} for key in ("RV32", "RV64"))
                        or not any(row[key] == "x" for key in ("RV32", "RV64"))):
                    raise ValueError(f"{path}:{number}: invalid instruction, formatter, row width or XLEN selection")
                if instruction in records or not any(row[point].strip() for point in points):
                    raise ValueError(f"{path}:{number}: duplicate instruction or no selected coverpoints")
                records[instruction] = row
    if not records:
        raise ValueError(f"{path}: native testplan must contain real test requests")
    return records


def contribution_path_allowed(root: Path, relative: str) -> bool:
    """Allow upstream-tracked/trackable tests, never ignored assembly or build evidence."""
    path = safe_path(root, relative)
    if (not path.is_file() or relative.startswith(".git/") or path.suffix in {".elf", ".bin", ".sig", ".results", ".log"}
            or any(part in {"work", ".venv", "__pycache__"} or part.startswith("work_") for part in Path(relative).parts)):
        return False
    if path.suffix not in {".S", ".c"} or not relative.startswith("tests/"):
        return path.suffix != ".S"
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", "--", relative],
                             capture_output=True, timeout=30)
    if tracked.returncode == 0:
        return True
    ignored = subprocess.run(["git", "-C", str(root), "check-ignore", "--no-index", "--", relative],
                             capture_output=True, timeout=30)
    if ignored.returncode not in {0, 1}:
        raise ValueError(f"Cannot determine upstream generated-file policy: {relative}")
    return ignored.returncode == 1


def validate_native_assets(root: Path, inputs: Path, suite: str, kind: str, contract_path: Path,
                           phase: str, normalized_csv: Path | None = None,
                           human_plan: Path | None = None) -> dict:
    """Check native asset completeness and emit only derived local reading/checking views."""
    native_path = native_plan_path(suite, kind)
    plan = safe_path(root, native_path)
    records = plan_records(plan, kind, suite, inputs / "testplan.schema.json" if kind == "privileged" else None)
    source = inputs / ("source-plan.yaml" if kind == "privileged" else "source-plan.csv")
    if source.exists():
        original = plan_records(source, kind, suite)
        missing = sorted(original.keys() - records.keys())
        if missing:
            raise ValueError(f"Native plan drops source requests: {missing[:20]}; preserve their coverage")
        if kind == "unprivileged":
            for instruction, before in original.items():
                for field, value in before.items():
                    if field not in {"Instruction", "Type"} and value.strip() and records[instruction].get(field) != value:
                        raise ValueError(f"{native_path}: preserve {instruction}/{field}={value}; do not drop source coverage or XLENs")
    rules = load_rules(inputs / "norm-rules.json")
    if kind == "privileged":
        rows = []
        for name, record in records.items():
            for field in ("goal", "description", "expectation", "check"):
                if not isinstance(record.get(field), str) or not record[field].strip():
                    raise ValueError(f"{native_path}: {name} needs an explanatory {field}")
            selected = record.get("rules")
            if (not isinstance(selected, list) or not selected or any(not isinstance(rule, str) for rule in selected)
                    or len(selected) != len(set(selected)) or set(selected) - rules.keys()):
                raise ValueError(f"{native_path}: {name} must reference distinct captured normative rules")
            rows.append({"source_items": json.dumps([name] if source.exists() and name in original else []),
                         "coverpoint": name, "normative_rules": json.dumps(selected), "disposition": "coverpoint"})
        if normalized_csv is not None:
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=["source_items", "coverpoint", "normative_rules", "disposition"])
            writer.writeheader()
            writer.writerows(rows)
            normalized_csv.parent.mkdir(parents=True, exist_ok=True)
            normalized_csv.write_text(buffer.getvalue(), encoding="utf-8")
    if human_plan is not None:
        text = f"\n# {suite} Native Test Plan\n\nSource: `{native_path}`. This view is derived; edit the native plan.\n"
        for name, record in records.items():
            text += f"\n## {name}\n\n"
            text += "\n".join(f"- {field}: {value}" for field, value in record.items() if str(value).strip()) + "\n"
        human_plan.parent.mkdir(parents=True, exist_ok=True)
        human_plan.write_text(text, encoding="utf-8")
    result = {"native_plan": native_path, "requests": len(records), "required_sources": [native_path]}
    if phase == "plan":
        return result
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    if (not isinstance(contract, dict) or contract.get("schema_version") != 1
            or contract.get("suite") != suite or contract.get("kind") != kind):
        raise ValueError(f"{contract_path}: require schema_version=1 and matching suite/kind")
    mapping_path = safe_path(root, f"coverpoints/norm/{suite}.yaml")
    mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    if not isinstance(mapping, dict) or not isinstance(mapping.get("normative_rule_definitions"), list):
        raise ValueError(f"{mapping_path}: require native normative_rule_definitions")
    mapped_rules, target_points = set(), set()
    for entry in mapping["normative_rule_definitions"]:
        if not isinstance(entry, dict) or set(entry) not in ({"name", "coverpoint"}, {"names", "coverpoint"}):
            raise ValueError(f"{mapping_path}: use native name/names and coverpoint entries")
        names = entry.get("names", [entry.get("name")])
        if (not isinstance(names, list) or not names or any(not isinstance(name, str) for name in names)
                or len(set(names)) != len(names)
                or set(names) - rules.keys() or mapped_rules.intersection(names)):
            raise ValueError(f"{mapping_path}: unknown or repeated normative rules")
        targets = entry["coverpoint"]
        if not isinstance(targets, list) or not targets or any(not isinstance(target, str) or not target.strip() for target in targets):
            raise ValueError(f"{mapping_path}: each rule needs coverage targets or an explicit native explanation")
        mapped_rules.update(names)
        parsed_targets, _ = parse_mapping_targets(targets)
        target_points.update(target["coverpoint"] for target in parsed_targets
                             if re.fullmatch(r"(?:cp|cr|cmp)_\w+", target["coverpoint"]))
    if not mapped_rules:
        raise ValueError(f"{mapping_path}: normative mapping must not be empty")
    if kind == "privileged":
        plan_rules = {rule for record in records.values() for rule in record["rules"]}
        if plan_rules - mapped_rules:
            raise ValueError(f"{mapping_path}: native plan rules absent from mapping: {sorted(plan_rules - mapped_rules)}")
    result["required_sources"].append(mapping_path.relative_to(root).as_posix())
    parameters = contract.get("parameters")
    if not isinstance(parameters, dict) or parameters.get("status") not in {"required", "not_applicable"}:
        raise ValueError("asset contract needs parameters.status=required|not_applicable")
    if not isinstance(parameters.get("rationale"), str) or not parameters["rationale"].strip():
        raise ValueError("Explain how ISA/configuration parameters affect this suite, including a no-parameter decision")
    param_file = safe_path(root, f"coverpoints/param/{suite}.yaml")
    if parameters["status"] == "required":
        names = parameters.get("names")
        if not isinstance(names, list) or not names or any(not isinstance(name, str) for name in names) or len(set(names)) != len(names):
            raise ValueError("Required parameters need distinct UDB names")
        parameter_data = yaml.safe_load(param_file.read_text(encoding="utf-8"))
        if not isinstance(parameter_data, dict) or set(parameter_data) != {"parameter_definitions"}:
            raise ValueError(f"{param_file}: require native parameter_definitions")
        entries = parameter_data["parameter_definitions"]
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"{param_file}: parameter mappings must not be empty")
        seen = set()
        for entry in entries:
            if (not isinstance(entry, dict) or set(entry) != {"name", "coverpoint", "effect"}
                    or not isinstance(entry["name"], str) or entry["name"] in seen):
                raise ValueError(f"{param_file}: require unique name/coverpoint/effect entries")
            seen.add(entry["name"])
            for field in ("coverpoint", "effect"):
                if not isinstance(entry[field], list) or not entry[field] or any(not isinstance(value, str) or not value.strip() for value in entry[field]):
                    raise ValueError(f"{param_file}: {field} must explain the parameter's affected tests")
            for target in entry["coverpoint"]:
                referenced = set(re.findall(r"\b(?:cp|cr|cmp)_\w+", target))
                if target != "all tests" and (not referenced or not referenced <= target_points):
                    raise ValueError(f"{param_file}: parameter target absent from normative mapping: {target}")
        if seen != set(names):
            raise ValueError(f"{param_file}: parameter list differs from the declared applicability")
        result["required_sources"].append(param_file.relative_to(root).as_posix())
    elif parameters.get("names") != [] or param_file.exists():
        raise ValueError("No-parameter disposition requires names=[] and no contradictory parameter mapping")
    ctp_sources = contract.get("ctp_sources")
    if (not isinstance(ctp_sources, list) or not ctp_sources or any(not isinstance(name, str) for name in ctp_sources)
            or len(set(ctp_sources)) != len(ctp_sources)):
        raise ValueError("Declare actual CTP chapter sources that include this suite's plan/norm/parameter tables")
    chapters = []
    for name in ctp_sources:
        if not isinstance(name, str) or not name.startswith("docs/ctp/src/") or not name.endswith(".adoc"):
            raise ValueError("CTP source entries must be native docs/ctp/src/*.adoc paths")
        chapters.append(safe_path(root, name).read_text(encoding="utf-8"))
    combined = "\n".join(chapters)
    reachable, pending = set(), ["docs/ctp/src/ctp.adoc"]
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable.add(name)
        chapter = safe_path(root, name)
        for include in re.findall(r"(?m)^include::([^\n\[{}]+)\[", chapter.read_text(encoding="utf-8")):
            target = (chapter.parent / include).resolve()
            if target.is_relative_to(root / "docs/ctp/src") and target.suffix == ".adoc" and target.is_file():
                pending.append(target.relative_to(root).as_posix())
    if set(ctp_sources) - reachable:
        raise ValueError(f"CTP chapters are not included from docs/ctp/src/ctp.adoc: {sorted(set(ctp_sources) - reachable)}")
    for table in (f"{suite}.adoc", f"{suite}_norm_rules.adoc"):
        if not re.search(r"(?m)^include::[^\n]*[/}]" + re.escape(table) + r"\[", combined):
            raise ValueError(f"CTP sources do not include {table}; integrate the native generated tables")
    if parameters["status"] == "required":
        consumer = safe_path(root, "generators/ctp/generate_norm_table.py").read_text(encoding="utf-8")
        if "_parameters.adoc" not in consumer and f"{suite}_parameters.adoc" not in combined:
            raise ValueError("Include the parameter table in CTP or use its native norm-table include")
    result["required_sources"].extend(ctp_sources)
    result["ctp_dependencies"] = sorted(reachable)
    if kind == "privileged":
        for name in (f"coverpoints/priv/{suite}_coverage.svh", f"coverpoints/priv/{suite}_coverage_init.svh",
                     f"generators/testgen/src/testgen/priv/extensions/{suite}.py"):
            if not safe_path(root, name).is_file():
                raise ValueError(f"Missing privileged contribution source: {name}")
            result["required_sources"].append(name)
    else:
        extension_sources = contract.get("extension_sources")
        if (not isinstance(extension_sources, list) or any(not isinstance(name, str) for name in extension_sources)
                or len(set(extension_sources)) != len(extension_sources)):
            raise ValueError("Declare extension_sources, or [] when existing coverpoints/formatters/decoder suffice")
        for name in extension_sources:
            if not any(fnmatch.fnmatchcase(name, pattern) for pattern in UNPRIVILEGED_EXTENSION_PATHS) or not contribution_path_allowed(root, name):
                raise ValueError(f"Invalid instruction-generator/template/decoder contribution: {name}")
        result["required_sources"].extend(extension_sources)
        for suffix in ("coverage", "coverage_init"):
            name = f"coverpoints/unpriv/{suite}_{suffix}.svh"
            if not safe_path(root, name).is_file():
                raise ValueError(f"Missing native generated coverage: {name}; run make tests for this suite")
            result["required_sources"].append(name)
        for filename in ("RISCV_coverage_base_init.svh", "RISCV_coverage_base_sample.svh", "RISCV_instruction_sample.svh"):
            name = "coverpoints/coverage/" + filename
            if not safe_path(root, name).is_file():
                raise ValueError(f"Missing native aggregate coverage: {name}; run make tests")
            result["required_sources"].append(name)
        generated_tests = []
        for instruction, row in records.items():
            for field, value in row.items():
                if field in {"Instruction", "Type", "RV32", "RV64", "ExtraExtensions"} or not value.strip():
                    continue
                variant = "" if value == "x" else "_" + value
                template = f"generators/coverage/src/covergroupgen/templates/{field}{variant}.sv"
                if not safe_path(root, template).is_file():
                    raise ValueError(f"{instruction}/{field}: missing native coverage template {template}")
            sample = f"generators/coverage/src/covergroupgen/templates/sample_{row['Type']}.sv"
            if not safe_path(root, sample).is_file():
                raise ValueError(f"{instruction}: missing instruction sample template {sample}")
            extra = row.get("ExtraExtensions", "")
            if extra and not re.fullmatch(r"[A-Za-z0-9_]+(?::[A-Za-z0-9_]+)*", extra):
                raise ValueError(f"{instruction}: ExtraExtensions must contain colon-separated native extension names")
            prefix = suite + extra.replace(":", "")
            for xlen in (32, 64):
                if row[f"RV{xlen}"] != "x":
                    continue
                directory = safe_path(root, f"tests/rv{xlen}/{suite}")
                tests = sorted(directory.glob(f"{prefix}-{instruction}-*.S"))
                if not tests or any(not test.is_file() or not test.stat().st_size for test in tests):
                    raise ValueError(f"{instruction}/RV{xlen}: missing or empty native generated assembly; run make tests")
                for test in tests:
                    name = test.relative_to(root).as_posix()
                    header = inspect_test_header(test.read_text(encoding="utf-8"), name)
                    if header["findings"]:
                        raise ValueError(f"{name}: invalid native test header: {header['findings'][:8]}")
                    generated_tests.append(name)
                    if contribution_path_allowed(root, name):
                        result["required_sources"].append(name)
        result["generated_tests"] = generated_tests
        findings = []
        coverage = scan_systemverilog([safe_path(root, f"coverpoints/unpriv/{suite}_coverage.svh")], findings)
        if not coverage["groups"] or any(finding["severity"] == "error" for finding in findings):
            raise ValueError("Generated instruction coverage has no valid groups; inspect native covergroupgen output")
        for entry in mapping["normative_rule_definitions"]:
            targets, waivers = parse_mapping_targets(entry["coverpoint"])
            if not targets and not waivers:
                raise ValueError(f"{mapping_path}: each rule requires a real target or an explicit coverage limitation")
            for target in targets:
                groups = coverage["groups"]
                selected_groups = [groups.get(target["covergroup"], {})] if target["covergroup"] else groups.values()
                if not any(target["coverpoint"] in group.get("coverpoints", []) for group in selected_groups):
                    raise ValueError(f"{mapping_path}: mapped coverage target does not exist: {target['raw']}")
    result["parameters"] = parameters
    return result
