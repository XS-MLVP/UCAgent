"""Validate upstream-native plans, parameter mappings, and contribution file policy."""

from __future__ import annotations

import csv
import fnmatch
import hashlib
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
GENERATION_EXTENSION_PATHS = (*UNPRIVILEGED_EXTENSION_PATHS,
    "generators/testgen/src/testgen/priv/extensions/*.py",
    "generators/testgen/scripts/*.py",
    "config/*",
)


def declared_generation_sources(root: Path, contract: dict) -> list[str]:
    """Bound AI-authored extensions to native asset interfaces and additive target configurations."""
    sources = contract.get("extension_sources", [])
    if (not isinstance(sources, list) or any(not isinstance(name, str) for name in sources)
            or len(set(sources)) != len(sources)):
        raise ValueError("extension_sources must list distinct native source paths")
    for name in sources:
        safe_path(root, name)
        if not any(fnmatch.fnmatchcase(name, pattern) for pattern in GENERATION_EXTENSION_PATHS):
            raise ValueError(f"Invalid instruction/generator/template contribution: {name}")
        if name.startswith("config/"):
            tracked = subprocess.run(["git", "-C", str(root), "ls-tree", "--name-only", "HEAD", "--", name],
                                           check=True, capture_output=True, text=True, timeout=30)
            if tracked.stdout.strip():
                raise ValueError(f"Keep pinned target configurations unchanged; create a distinct new config: {name}")
    return sources


def plan_records(path: Path, kind: str, suite: str, schema: Path | None = None,
                 *, source: bool = False, allow_empty: bool = False) -> dict[str, dict]:
    """Read native plan identities without confusing instruction columns and privileged rows."""
    native_plan_path(suite, kind)
    records = {}
    if kind == "privileged":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if schema is not None:
            definition = json.loads(schema.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(definition)
            Draft202012Validator(definition).validate(data)
        if not isinstance(data, dict) or (not source and data.get("suite") != suite) or not isinstance(data.get("coverpoints"), list):
            raise ValueError(f"{path}: require the exact suite and a coverpoints array")
        for entry in data["coverpoints"]:
            if not isinstance(entry, dict):
                raise ValueError(f"{path}: coverpoint entries must be objects")
            if "heading" in entry or not entry.get("name"):
                continue
            if not isinstance(entry["name"], str):
                raise ValueError(f"{path}: coverpoint names must be strings")
            names = [name.strip() for name in re.split(r"\n|\s+/\s+", entry["name"]) if name.strip()]
            if not names or (not source and any(not re.fullmatch(r"[A-Za-z_]\w*", name) for name in names)):
                raise ValueError(f"{path}: coverpoint rows need real coverage identifiers")
            if not source:
                for field in ("goal", "description", "expectation", "check"):
                    if not isinstance(entry.get(field), str) or not entry[field].strip():
                        raise ValueError(f"{path}: {entry['name']} needs an explanatory {field} in each scenario row")
            for name in names:
                if name in records:
                    for field, value in entry.items():
                        previous = records[name].get(field)
                        if isinstance(value, list) and isinstance(previous, list):
                            records[name][field] = list(dict.fromkeys([*previous, *value]))
                        elif value != previous and field != "name":
                            records[name][field] = "\n".join(str(item) for item in (previous, value) if item)
                else:
                    records[name] = dict(entry)
    else:
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames or []
            if fields[:4] != ["Instruction", "Type", "RV32", "RV64"] or len(fields) != len(set(fields)):
                raise ValueError(f"{path}: require unique native Instruction,Type,RV32,RV64 columns")
            columns = fields[5:] if fields[4:5] == ["ExtraExtensions"] else fields[4:]
            points = [name for name in columns if not re.fullmatch(r"EFFEW\d+", name)]
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
                identity = "|".join((instruction, row["Type"], row.get("ExtraExtensions", "")))
                if identity in records:
                    raise ValueError(f"{path}:{number}: duplicate instruction/type/extensions variant")
                records[identity] = row
            if not source and not any(row[point].strip() for row in records.values() for point in points):
                raise ValueError(f"{path}: native testplan must select actual coverpoints")
    if not records and not source and not allow_empty:
        raise ValueError(f"{path}: native testplan must contain real test requests")
    return records


def contribution_path_allowed(root: Path, relative: str, *, allow_missing: bool = False) -> bool:
    """Allow upstream-tracked/trackable tests, never ignored assembly or build evidence."""
    path = safe_path(root, relative)
    if ((path.exists() and not path.is_file()) or (not path.exists() and not allow_missing)
            or relative.startswith(".git/") or path.suffix in {".elf", ".bin", ".sig", ".results", ".log"}
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
    receipt_path = inputs / "receipt.json"
    prepared = json.loads(receipt_path.read_text(encoding="utf-8"))
    plans = prepared.get("native_plans")
    if not isinstance(plans, list) or not plans or len(plans) != len(set(plans)):
        raise ValueError("Prepare a nonempty, distinct native_plans scope before validating assets")
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8")) if contract_path.is_file() else {}
    if not isinstance(contract, dict):
        raise ValueError(f"{contract_path}: require an asset contract mapping")
    records, original, identities = {}, {}, {}
    source_plans = prepared["source_plans"]
    if source_plans.keys() - set(plans):
        raise ValueError("Native plans must retain every captured source plan")
    for native_path in plans:
        plan = safe_path(root, native_path)
        captured = plan_records(safe_path(inputs, source_plans[native_path]), kind, plan.stem, source=True) if native_path in source_plans else {}
        current = plan_records(plan, kind, plan.stem, inputs / "testplan.schema.json" if kind == "privileged" else None,
                               allow_empty=native_path in source_plans and not captured)
        for name, record in captured.items():
            original[f"{native_path}#{name}"] = record
        for name, record in current.items():
            identity = f"{native_path}#{name}"
            records[identity] = record
            identities[identity] = (native_path, name)
    if not records:
        raise ValueError("Native plans must contain real test requests; headings alone are not test coverage")
    request_map = contract.get("source_request_map", {})
    if not isinstance(request_map, dict) or request_map.keys() - original.keys():
        raise ValueError("source_request_map must map captured path#request identities to final path#request identities")
    for name, targets in request_map.items():
        if not isinstance(targets, list) or not targets or any(not isinstance(target, str) or target not in records for target in targets):
            raise ValueError(f"{name}: source_request_map needs existing final plan identifiers; never discard a request")
    missing = sorted(original.keys() - records.keys() - request_map.keys())
    if missing:
        raise ValueError(f"Native plan drops source requests: {missing[:20]}; preserve their coverage")
    if kind == "unprivileged":
        for instruction, before in original.items():
            for target in request_map.get(instruction, [instruction]):
                for field, value in before.items():
                    if field not in {"Instruction", "Type"} and value.strip() and records[target].get(field) != value:
                        raise ValueError(f"{target}: preserve {instruction}/{field}={value}; do not drop source coverage or XLENs")
    rules = load_rules(inputs / "norm-rules.json")
    if kind == "privileged":
        projected = {}
        for identity, record in records.items():
            native_path, name = identities[identity]
            selected = record.get("rules")
            if (not isinstance(selected, list) or not selected or any(not isinstance(rule, str) for rule in selected)
                    or len(selected) != len(set(selected)) or set(selected) - rules.keys()):
                raise ValueError(f"{native_path}: {name} must reference distinct captured normative rules")
            source_items = [old for old in original if identity in request_map.get(old, [old])]
            row = projected.setdefault(name, {"source_items": set(), "source_requests": set(),
                                              "plan_requests": set(), "normative_rules": set()})
            row["source_items"].update("src_" + hashlib.sha256(json.dumps([old, identity]).encode()).hexdigest()
                                       for old in source_items)
            row["source_requests"].update(source_items)
            row["plan_requests"].add(identity)
            row["normative_rules"].update(selected)
        if normalized_csv is not None:
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=["source_items", "coverpoint", "normative_rules", "disposition",
                                                       "source_requests", "plan_requests"])
            writer.writeheader()
            writer.writerows({"coverpoint": name, "disposition": "coverpoint",
                              **{field: json.dumps(sorted(values)) for field, values in row.items()}}
                             for name, row in projected.items())
            normalized_csv.parent.mkdir(parents=True, exist_ok=True)
            normalized_csv.write_text(buffer.getvalue(), encoding="utf-8")
    if human_plan is not None:
        text = f"\n# {suite} Native Test Plan\n\nSources: " + ", ".join(f"`{name}`" for name in plans) + ". This view is derived; edit the native plans.\n"
        for name, record in records.items():
            text += f"\n## {name}\n\n"
            text += "\n".join(f"- {field}: {value}" for field, value in record.items() if str(value).strip()) + "\n"
        human_plan.parent.mkdir(parents=True, exist_ok=True)
        human_plan.write_text(text, encoding="utf-8")
    result = {"native_plans": plans, "requests": len(records), "required_sources": list(plans)}
    if phase == "plan":
        return result
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
    pending = {name for name in mapped_rules if rules[name].get("status") == "pending_source_binding"}
    if pending and (not isinstance(mapping.get("untagged_upstream"), str) or not mapping["untagged_upstream"].strip()):
        raise ValueError(f"{mapping_path}: source-bound pending rules require native untagged_upstream tracking: {sorted(pending)}")
    result["pending_rules"] = sorted(pending)
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
    for table in [*(f"{Path(name).stem}.adoc" for name in plans), f"{suite}_norm_rules.adoc"]:
        if not re.search(r"(?m)^include::[^\n]*[/}]" + re.escape(table) + r"\[", combined):
            raise ValueError(f"CTP sources do not include {table}; integrate the native generated tables")
    if parameters["status"] == "required":
        consumer = safe_path(root, "generators/ctp/generate_norm_table.py").read_text(encoding="utf-8")
        if "_parameters.adoc" not in consumer and f"{suite}_parameters.adoc" not in combined:
            raise ValueError("Include the parameter table in CTP or use its native norm-table include")
    result["required_sources"].extend(ctp_sources)
    result["ctp_dependencies"] = sorted(reachable)
    extension_sources = declared_generation_sources(root, contract)
    for name in extension_sources:
        if not contribution_path_allowed(root, name):
            raise ValueError(f"Invalid instruction/generator/template contribution: {name}")
    result["required_sources"].extend(extension_sources)
    native_suites = contract.get("native_suites", [suite])
    if (not isinstance(native_suites, list) or not native_suites
            or any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]+", name) for name in native_suites)
            or len(set(native_suites)) != len(native_suites)):
        raise ValueError("native_suites must list distinct native make EXTENSIONS selections for the requested scope")
    result["native_suites"] = native_suites
    for companion, snapshot in prepared.get("companion_plans", {}).items():
        before = plan_records(inputs / snapshot, "unprivileged", Path(companion).stem, source=True)
        after = plan_records(safe_path(root, companion), "unprivileged", Path(companion).stem)
        for identity, row in before.items():
            if identity not in after or any(value.strip() and after[identity].get(field) != value for field, value in row.items()):
                raise ValueError(f"{companion}: preserve source instruction variant {identity}")
        result["required_sources"].append(companion)
    if kind == "privileged":
        generator_sources = [name for name in extension_sources if name.endswith(".py") and name.startswith("generators/testgen/")]
        if not generator_sources:
            raise ValueError("Declare actual privileged generator sources in extension_sources, including shared/nested generators")
        for name in (f"coverpoints/priv/{suite}_coverage.svh", f"coverpoints/priv/{suite}_coverage_init.svh"):
            if not safe_path(root, name).is_file():
                raise ValueError(f"Missing privileged contribution source: {name}")
            result["required_sources"].append(name)
    else:
        coverage_paths = []
        for selected_suite in native_suites:
            for suffix in ("coverage", "coverage_init"):
                name = f"coverpoints/unpriv/{selected_suite}_{suffix}.svh"
                if not safe_path(root, name).is_file():
                    raise ValueError(f"Missing native generated coverage: {name}; run native make tests")
                result["required_sources"].append(name)
                if suffix == "coverage":
                    coverage_paths.append(safe_path(root, name))
        for filename in ("RISCV_coverage_base_init.svh", "RISCV_coverage_base_sample.svh", "RISCV_instruction_sample.svh"):
            name = "coverpoints/coverage/" + filename
            if not safe_path(root, name).is_file():
                raise ValueError(f"Missing native aggregate coverage: {name}; run make tests")
            result["required_sources"].append(name)
        generated_tests = []
        for identity, row in records.items():
            instruction = row["Instruction"]
            widths = [field.removeprefix("EFFEW") for field in row if re.fullmatch(r"EFFEW\d+", field) and row[field]]
            if not any(value.strip() for field, value in row.items()
                       if field not in {"Instruction", "Type", "RV32", "RV64", "ExtraExtensions"} and not field.startswith("EFFEW")):
                continue
            for field, value in row.items():
                if field in {"Instruction", "Type", "RV32", "RV64", "ExtraExtensions"} or field.startswith("EFFEW") or not value.strip():
                    continue
                variant = "" if value == "x" else "_" + value
                templates = root / "generators/coverage/src/covergroupgen/templates"
                if not widths and not list(templates.rglob(f"{field}{variant}.sv")):
                    raise ValueError(f"{instruction}/{field}: missing native coverage template {field}{variant}.sv")
            sample = f"sample_{row['Type'].removesuffix('_RD_NX0')}.sv"
            if not list((root / "generators/coverage/src/covergroupgen/templates").rglob(sample)):
                raise ValueError(f"{instruction}: missing instruction sample template {sample}")
            extra = row.get("ExtraExtensions", "")
            if extra and not re.fullmatch(r"[A-Za-z0-9_]+(?::[A-Za-z0-9_]+)*", extra):
                raise ValueError(f"{instruction}: ExtraExtensions must contain colon-separated native extension names")
            for selected_suite in native_suites:
                selected_width = re.search(r"(\d+)$", selected_suite)
                if widths and selected_width and selected_width[1] not in widths:
                    continue
                prefix = selected_suite + extra.replace(":", "")
                for xlen in (32, 64):
                    if row[f"RV{xlen}"] != "x":
                        continue
                    base = "e" if selected_suite == "E" else "i"
                    directory = safe_path(root, f"tests/rv{xlen}{base}/{selected_suite}")
                    tests = sorted(directory.glob(f"{prefix}-{instruction}-*.S"))
                    if not tests or any(not test.is_file() or not test.stat().st_size for test in tests):
                        raise ValueError(f"{identity}/RV{xlen}/{selected_suite}: missing or empty native generated assembly; run make tests")
                    for test in tests:
                        name = test.relative_to(root).as_posix()
                        header = inspect_test_header(test.read_text(encoding="utf-8"), name)
                        if header["findings"]:
                            raise ValueError(f"{name}: invalid native test header: {header['findings'][:8]}")
                        generated_tests.append(name)
                        if contribution_path_allowed(root, name):
                            result["required_sources"].append(name)
        result["generated_tests"] = sorted(set(generated_tests))
        findings = []
        coverage = scan_systemverilog(coverage_paths, findings)
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
    result["required_sources"] = sorted(set(result["required_sources"]))
    result["parameters"] = parameters
    return result
