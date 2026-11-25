"""Distinct acceptance gates for restored UnitTest stages using ToffeeUT artifacts."""

import ast
from pathlib import Path

import yaml

from .layout import project_layout
from .implementation import collect_test_files, collected_scenarios, non_verifying_cases
from .paths import digest, local_path
from .runner import current_run


RESTORED_PHASES = frozenset({
    "requirements", "dut", "groups", "points", "checkpoints", "line_map", "refine",
    "static", "wrapper", "fixture", "coverage_groups", "coverage_points",
    "coverage_checks", "env_spec_review", "bundle", "mock", "mock_fixture",
    "mock_tests", "mock_batch", "environment_impl", "env_selftest", "env_review", "api", "model",
    "model_fixture", "api_tests", "templates", "case_batch", "refine_tests",
    "static_validation", "line_coverage", "random", "review", "comprehensive",
})


def _validate_functional_failures(workspace, dut, project, checked, requirements, scenarios, cases):
    """Reject vacuous cases and require native identity plus current attribution for RTL FAILs."""
    from .audit import current_issues

    empty = non_verifying_cases(workspace, project, cases)
    if empty:
        raise ValueError(f"Unimplemented failure-only or vacuous test cannot receive functional execution credit: {empty[:12]}; "
                         "implement its stimulus, comparison and completion obligations")
    failures = {node: case for node, case in cases.items() if case["status"] == "FAIL"}
    if not failures:
        return
    if checked["record"]["dut"] != dut:
        raise ValueError("The current run belongs to another DUT; call RunToffee for this DUT")
    layout = project_layout(workspace, dut, project)
    expected_class = "DUT" + layout["export_name"]
    builds = [row["build"] for row in checked["manifest"].get("artifacts", []) if row["kind"] == "native"]
    for node, case in failures.items():
        if case["phases"].get("call", {}).get("outcome") != "failed":
            raise ValueError(f"Functional FAIL needs an actual call-phase assertion failure: {node}")
        if not any(identity["class"] == build["name"] == expected_class and identity["source"] in build["files"]
                   for identity in case["native_duts"] for build in builds):
            raise ValueError(f"Functional FAIL needs this DUT's matching per-case native manifest identity: {node}")
        if not case["scenarios"] or any(tag not in scenarios for tag in case["scenarios"]):
            raise ValueError(f"Functional FAIL needs declared scenario identities: {node}")
    # Reuse delivery's attribution without imposing full-selection, coverage or residual closure here.
    issues = current_issues(workspace, dut, project, checked, requirements, nodeids=set(failures))
    for node, case in failures.items():
        related = [issue for issue in issues if node in issue["nodeids"]]
        if any(issue["classification"] == "verification" for issue in related):
            raise ValueError(f"Fix the current verification-infrastructure failure before advancing: {node}")
        linked_requirements = {scenarios[tag]["requirement"] for tag in case["scenarios"]}
        if not any(issue["state"] == "open" and issue["classification"] == "rtl"
                   and issue["requirement"] in linked_requirements for issue in related):
            raise ValueError(f"Functional FAIL needs a current open RTL issue for its confirmed requirement "
                             f"and validated per-node WaveInfo evidence: {node}")


def audit_restored_phase(workspace, dut, project, phase, *, line_coverage_required=None):
    """Validate the concrete artifact for one restored stage, never merely its name."""
    from .audit import audit_project, contracts, delivery_data, read_spec, verification_plan

    if phase not in RESTORED_PHASES:
        raise ValueError(f"Unknown restored phase: {phase}")
    try:
        acceptance = {}
        layout = project_layout(workspace, dut, project)
        root = layout["root"]
        bench = root / "testbenches" / layout["testbench"]
        design_path = root / layout["design_spec"]
        verification_path = root / layout["verification_spec"]
        inventory_path = root / "results/input_inventory.json"
        review_path = root / f"docs/reviews/{dut}-stage-evidence.md"
        static_path = root / f"docs/reviews/{dut}-static-review.md"
        if phase == "requirements":
            result = audit_project(workspace, dut, project, "inputs")
            if not result["ok"]:
                return {**result, "phase": phase}
            if not design_path.is_file():
                raise ValueError(f"Create or adopt the design specification: {design_path.relative_to(root)}")
            return {"ok": True, "phase": phase}

        root, requirements = contracts(workspace, dut, project)
        design = read_spec(design_path, "design", dut)
        if phase == "dut":
            if not (root / layout["environment"]).exists():
                raise ValueError(f"Inspect the declared DUT interface at {layout['environment']}")
        elif phase in {"groups", "points", "checkpoints", "line_map"}:
            groups = design.get("behavior_groups")
            if not isinstance(groups, list) or not groups:
                raise ValueError(f"Define nonempty behavior_groups in {design_path.relative_to(root)}")
            ids = set()
            assigned = set()
            for row in groups:
                if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key].strip()
                                                    for key in ("id", "behavior", "source", "responsibility")):
                    raise ValueError("Each behavior group needs id, behavior, source and responsibility")
                if row["id"] in ids:
                    raise ValueError(f"Duplicate behavior group: {row['id']}")
                ids.add(row["id"])
                members = row.get("requirements")
                if not isinstance(members, list) or not members or any(key not in requirements for key in members):
                    raise ValueError(f"Group {row['id']} must link existing design requirements")
                assigned.update(members)
            if assigned != set(requirements):
                raise ValueError(f"Behavior groups must classify all requirements: {sorted(set(requirements) - assigned)}")
            if phase == "groups":
                return {"ok": True, "phase": phase}
            points = design.get("checkpoints")
            if phase in {"checkpoints", "line_map"} or phase == "points":
                if not isinstance(points, list) or not points:
                    raise ValueError("Define nonempty checkpoints linked to requirements in the design specification")
                seen = set()
                covered = set()
                for row in points:
                    if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key].strip()
                                                        for key in ("id", "requirement", "stimulus", "observation", "comparison")):
                        raise ValueError("Each checkpoint needs id, requirement, stimulus, observation and comparison")
                    if row["id"] in seen or row["requirement"] not in requirements:
                        raise ValueError(f"Checkpoint duplicates an ID or refers to an unknown requirement: {row.get('id')}")
                    seen.add(row["id"])
                    covered.add(row["requirement"])
                if covered != set(requirements):
                    raise ValueError(f"Requirements without checkpoints: {sorted(set(requirements) - covered)}")
            if phase == "line_map":
                import json
                inventory = json.loads(inventory_path.read_text())
                paths = inventory["documents"]
                if paths:
                    lines = read_spec(root / f"docs/spec/verification/{dut}-line-map.md", "line_map", dut)
                    rows = lines.get("sources")
                    if (not isinstance(rows, list) or len(rows) != len(paths)
                            or {row.get("path") for row in rows if isinstance(row, dict)} != set(paths)):
                        raise ValueError("Map each inventoried source document in the line-map document")
                    for row in rows:
                        source = local_path(workspace, row["path"])
                        if source.suffix.lower() not in {".md", ".txt", ".rst"}:
                            raise ValueError(f"Line mapping needs stable physical text lines; convert {row['path']} to a text document before mapping")
                        if digest(source) != row.get("sha256"):
                            raise ValueError(f"Input changed; remap current source lines: {row['path']}")
                        content = source.read_text().splitlines()
                        segments = row.get("lines")
                        if not isinstance(segments, list):
                            raise ValueError(f"Missing source line mappings: {row['path']}")
                        found = set()
                        for segment in segments:
                            if not isinstance(segment, dict) or type(segment.get("start")) is not int or type(segment.get("end")) is not int:
                                raise ValueError("Line mappings require inclusive integer start and end")
                            first, last = segment["start"], segment["end"]
                            if first < 1 or last < first or last > len(content) or last - first >= 100:
                                raise ValueError(f"Invalid line block in {row['path']}: {first}-{last}")
                            if segment.get("checkpoint") not in seen and not (segment.get("checkpoint") == "IGNORE" and
                                    isinstance(segment.get("reason"), str) and segment["reason"].strip()):
                                raise ValueError(f"Line block needs a real checkpoint or reasoned IGNORE: {row['path']}:{first}-{last}")
                            block = set(range(first, last + 1))
                            if found & block:
                                raise ValueError(f"Overlapping source mappings in {row['path']}: {first}-{last}")
                            found.update(block)
                        missing = [i for i, value in enumerate(content, 1) if value.strip() and i not in found]
                        if missing:
                            raise ValueError(f"Nonblank source lines remain unmapped in {row['path']}: {missing[:12]}")
        else:
            scenarios = verification_plan(root, dut, requirements)
            if phase == "refine":
                specification = read_spec(verification_path, "verification", dut)
                matrix = specification.get("behavior_matrix")
                if not isinstance(matrix, list) or not matrix:
                    raise ValueError("Add an explicit category-by-outcome behavior_matrix to the verification spec")
                covered, cells = set(), set()
                for row in matrix:
                    if not isinstance(row, dict) or row.get("status") not in {"planned", "gap", "na", "out-of-domain"} or row.get("scenario") not in scenarios:
                        raise ValueError("Each matrix cell must link a scenario and a supported status")
                    if not isinstance(row.get("outcome"), str) or not row["outcome"].strip():
                        raise ValueError("Each matrix cell needs a named response outcome")
                    if row["status"] != "planned" and not (isinstance(row.get("reason"), str) and row["reason"].strip()):
                        raise ValueError("Matrix gap/na/out-of-domain entries need a reason and next action")
                    cell = (row["scenario"], row["outcome"])
                    if cell in cells or row["status"] == "planned" and scenarios[row["scenario"]]["status"] != "active":
                        raise ValueError(f"Duplicated or falsely planned response cell: {cell}")
                    cells.add(cell)
                    covered.add(row["scenario"])
                if set(scenarios) - covered:
                    raise ValueError(f"Scenarios missing from outcome matrix: {sorted(set(scenarios) - covered)}")
            elif phase in {"static", "static_validation"}:
                import json
                inventory = json.loads(inventory_path.read_text())
                if not inventory["rtl"]:
                    raise ValueError("Static review requires actual inventoried RTL inputs")
                review = read_spec(static_path, "static_review", dut)
                sources = review.get("sources")
                if (not isinstance(sources, list) or len(sources) != len(inventory["rtl"])
                        or {row.get("path") for row in sources if isinstance(row, dict)} != set(inventory["rtl"])):
                    raise ValueError("Static review must enumerate every inventoried RTL source")
                for row in sources:
                    source = local_path(workspace, row["path"])
                    if (row.get("sha256") != inventory["rtl"][row["path"]] or row["sha256"] != digest(source)
                            or not isinstance(row.get("review"), str) or not row["review"].strip()):
                        raise ValueError(f"Static review source or analysis is stale/missing: {row['path']}")
                candidates = review.get("candidates")
                if not isinstance(candidates, list):
                    raise ValueError("Static review candidates must be an array (empty when none found)")
                ids = set()
                for row in candidates:
                    if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in ids or row.get("source") not in inventory["rtl"]:
                        raise ValueError("Static candidate needs a unique ID and an inventoried source")
                    if type(row.get("line")) is not int or row["line"] < 1 or row["line"] > len(local_path(workspace, row["source"]).read_text().splitlines()):
                        raise ValueError(f"Static candidate needs a real source line: {row.get('id')}")
                    if not isinstance(row.get("hypothesis"), str) or not row["hypothesis"].strip():
                        raise ValueError(f"Static candidate needs a falsifiable hypothesis: {row['id']}")
                    if phase == "static_validation" and row.get("status") not in {"unconfirmed", "rtl", "ruled-out", "out-of-domain"}:
                        raise ValueError(f"Classify candidate with current evidence and next experiment: {row['id']}")
                    if phase == "static_validation" and (not isinstance(row.get("evidence"), str) or not row["evidence"].strip()):
                        raise ValueError(f"Static candidate needs evidence or an explicit missing-evidence reason: {row['id']}")
                    ids.add(row["id"])
                if phase == "static_validation" and any(row["status"] == "rtl" for row in candidates):
                    from .waveform import validate_waveform_evidence
                    if any(not row.get("nodeids") for row in candidates if row["status"] == "rtl"):
                        raise ValueError("Confirmed static candidates need actual failing nodeids and WaveInfo evidence")
                    checked = current_run(workspace, project)
                    for row in candidates:
                        if row["status"] != "rtl":
                            continue
                        nodes = row.get("nodeids", [])
                        if (row.get("run") != checked["record"]["run"] or not nodes
                                or row.get("requirement") not in requirements
                                or requirements[row["requirement"]]["basis"] != "confirmed"
                                or any(checked["cases"]["cases"].get(node, {}).get("status") != "FAIL" for node in nodes)):
                            raise ValueError("Confirmed static candidate needs a confirmed requirement and current run/nodeids with real FAIL; use WaveInfo for evidence")
                        validate_waveform_evidence(workspace, project, dut, checked, nodes, row.get("waveform_evidence"))
            elif phase in {"wrapper", "fixture", "bundle", "environment_impl", "api", "model", "model_fixture",
                           "coverage_groups", "coverage_points", "coverage_checks", "mock", "mock_fixture"}:
                if phase == "wrapper":
                    native = root / f"dut/{dut}/__init__.py"
                    if not native.is_file():
                        raise ValueError(f"Build or adopt the real DUT package under dut/{dut}")
                    if not native.resolve().is_relative_to(Path(workspace).resolve()):
                        raise ValueError(f"Native DUT package points outside the selected workspace: {native}")
                    if f"DUT{layout['export_name']}" not in native.read_text():
                        raise ValueError(f"Native package does not export DUT{layout['export_name']}: {native}")
                    from .build_receipts import validate_package_receipts
                    acceptance["build_evidence"] = validate_package_receipts(workspace, layout)
                if phase in {"fixture", "mock_fixture", "model_fixture"} and not (root / "conftest.py").is_file():
                    raise ValueError("The project root conftest.py must own fixture registration")
                if phase == "fixture" and not any(token in (root / "conftest.py").read_text()
                                                   for token in ("native_dut", "pytest_plugins")):
                    raise ValueError("Register a native DUT fixture or explicit fixture plugin at the project root")
                if phase in {"coverage_groups", "coverage_points", "coverage_checks"}:
                    code = [path for path in bench.rglob("*.py") if path.stem == "coverage" or "coverage" in path.parts]
                    names = {node.id for path in code for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, ast.Name)}
                    if not code or "CoverGroupDef" not in names:
                        raise ValueError("Implement actual Toffee CoverGroupDef in the DUT coverage responsibility")
                if phase in {"coverage_points", "coverage_checks"} and not {"CoverPointDef", "Bin"} <= names:
                        raise ValueError("Add meaningful CoverPointDef and Bin definitions to the DUT coverage model")
                if phase in {"bundle", "environment_impl", "api", "fixture"} and not (root / layout["environment"]).is_file():
                    raise ValueError(f"Implement the declared DUT environment: {layout['environment']}")
                if phase in {"bundle", "environment_impl", "api"}:
                    paths = [path for path in bench.rglob("*.py") if "tests" not in path.parts]
                    if not paths or any("NotImplementedError" in path.read_text() for path in paths):
                        raise ValueError("Complete the DUT environment; unimplemented methods cannot pass this stage")
                    trees = [ast.parse(path.read_text()) for path in paths]
                    if phase == "environment_impl":
                        base = audit_project(workspace, dut, project, "environment")
                        if not base["ok"]:
                            return {**base, "phase": phase}
                        if not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                                   and node.name in {"__aenter__", "__enter__"}
                                   for tree in trees for node in ast.walk(tree)):
                            raise ValueError("Implement the DUT environment fixture lifecycle, driver and monitor under the declared testbench")
                    if phase == "bundle" and not any(isinstance(node, ast.Name) and node.id == "Bundle" for tree in trees for node in ast.walk(tree)):
                        raise ValueError("Bind actual DUT ports through a Toffee Bundle with unique ownership")
                    if phase == "api" and not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and
                            not node.name.startswith("_") and node.name not in {"reset", "step"} for tree in trees for node in ast.walk(tree)):
                        raise ValueError("Implement a public transaction method instead of exposing raw pins/steps")
                if phase == "model" and not any((bench / candidate).exists() for candidate in ("model.py", "model", "checker.py", "checker")):
                    raise ValueError("Implement an independent model or checker under the DUT testbench")
                if phase == "model_fixture":
                    cases = current_run(workspace, project)["cases"]["cases"]
                    if not any(row["status"] == "PASS" and row["selftest"] and "modelcheck" in row.get("roles", [])
                               for row in cases.values()):
                        raise ValueError("Run an independent modelcheck selftest with RunToffee before this stage")
                if phase == "mock" and not any("mock" in path.stem for path in bench.rglob("*.py")):
                    raise ValueError("Add the explicitly needed Mock/producer under the DUT environment")
                if phase == "coverage_checks":
                    result = audit_project(workspace, dut, project, "environment")
                    if not result["ok"]:
                        return {**result, "phase": phase}
                    paths = [path for path in bench.rglob("*.py") if path.is_file() and "tests" not in path.parts]
                    if not any(isinstance(node, ast.Attribute) and node.attr == "sample" for path in paths
                               for node in ast.walk(ast.parse(path.read_text()))):
                        raise ValueError("Coverage needs a real sample call in the DUT observation path")
            elif phase in {"templates", "case_batch", "refine_tests"}:
                result = audit_project(workspace, dut, project, "environment" if phase == "templates" else "tests")
                if not result["ok"]:
                    return {**result, "phase": phase}
                tests = collect_test_files(root, layout["tests"])
                if not tests:
                    raise ValueError("Create tests for the DUT scenarios before completing this stage")
                names = {name for path in tests for name in collected_scenarios(path, project=root)}
                missing = {name for name, row in scenarios.items() if row["status"] == "active"} - names
                if missing:
                    raise ValueError("Each active scenario requires an implemented or explicitly failing test template: "
                                     + ", ".join(sorted(missing)))
                if phase in {"case_batch", "refine_tests"}:
                    checked = current_run(workspace, project)
                    functional = [case for case in checked["cases"]["cases"].values() if not case["selftest"]]
                    if {name for name, row in scenarios.items() if row["status"] == "active"} - {tag for case in functional for tag in case["scenarios"]}:
                        raise ValueError("Execute all active scenarios using RunToffee before advancing")
                    if any(not case["native_duts"] for case in functional):
                        raise ValueError("Real functional cases must register their native DUT in the signed run")
                    if phase == "refine_tests":
                        data = delivery_data(workspace, dut, project)
                        if data["unregistered_cases"] or data["missing_scenarios"]:
                            raise ValueError("Review each active scenario on a registered real DUT with current execution evidence")
                        review = read_spec(review_path, "stage_evidence", dut)
                        entry = review.get("reviews", {}).get(phase)
                        if not isinstance(entry, dict) or entry.get("run") != checked["record"]["run"]:
                            raise ValueError("Add a source-linked refine_tests review for this exact signed run")
                        if not isinstance(entry.get("observation"), str) or not entry["observation"].strip():
                            raise ValueError("Review the real assertions and completion obligations, not merely their labels")
                        source = local_path(workspace, entry.get("source", "").split("#", 1)[0])
                        if not source.is_file() or source.resolve() == review_path.resolve() or digest(source) != entry.get("sha256"):
                            raise ValueError("The refine_tests review must cite a current independent source and its actual sha256")
            elif phase in {"env_selftest", "mock_tests", "mock_batch", "api_tests"}:
                checked = current_run(workspace, project)
                cases = checked["cases"]["cases"]
                role = {"env_selftest": "envcheck", "mock_tests": "mockcheck",
                        "mock_batch": "mockcheck", "api_tests": "api"}[phase]
                subset = {node: row for node, row in cases.items() if role in row.get("roles", [])
                          and row["selftest"] == (phase != "api_tests")}
                accepted = {"PASS", "FAIL"} if phase == "api_tests" else {"PASS"}
                if not subset or any(row["status"] not in accepted for row in subset.values()):
                    raise ValueError("Execute the relevant real selftests or native API cases successfully with RunToffee")
                if phase == "api_tests" and any(not row["native_duts"] for row in subset.values()):
                    raise ValueError("Every API functional test must execute a registered native DUT")
                if phase == "api_tests":
                    _validate_functional_failures(workspace, dut, project, checked, requirements, scenarios, subset)
            elif phase == "comprehensive":
                result = audit_project(workspace, dut, project, "triage")
                if not result["ok"]:
                    return {**result, "phase": phase}
                data = delivery_data(workspace, dut, project)
                if not data["full_selection"] or data["missing_scenarios"] or data["unregistered_cases"]:
                    raise ValueError("Run the complete DUT selection with registered native DUT and all active scenarios")
                if any(data["tests"].get(kind, 0) for kind in ("ERROR", "XPASS")):
                    raise ValueError("Fix environment errors and unexpected passes before completing comprehensive verification")
            elif phase == "line_coverage":
                from .stage_checks.line_coverage import check

                return check(workspace, dut, project)
            elif phase in {"env_spec_review", "env_review", "random", "review"}:
                review = read_spec(review_path, "stage_evidence", dut)
                entry = review.get("reviews", {}).get(phase)
                if not isinstance(entry, dict) or not all(isinstance(entry.get(field), str) and entry[field].strip()
                                                           for field in ("observation", "source", "next_action")):
                    raise ValueError(f"Record evidence, source and next action for {phase} in {review_path.relative_to(root)}")
                source = local_path(workspace, entry["source"].split("#", 1)[0])
                if not source.is_file() or source.resolve() == review_path.resolve() or digest(source) != entry.get("sha256"):
                    raise ValueError(f"Review {phase} must cite a current independent input with its actual sha256")
                if phase in {"random", "review"}:
                    checked = current_run(workspace, project)
                    if phase == "random":
                        strategies = entry.get("strategies")
                        if (not isinstance(strategies, list) or len(strategies) != len(scenarios)
                                or {row.get("scenario") for row in strategies if isinstance(row, dict)} != set(scenarios)):
                            raise ValueError("Decide the random-testing strategy for every declared scenario")
                        tested = {}
                        for row in strategies:
                            if row.get("status") == "not-applicable":
                                if not isinstance(row.get("reason"), str) or not row["reason"].strip():
                                    raise ValueError("Explain why random stimulus adds no useful verification to this scenario")
                            elif row.get("status") == "tested":
                                case = checked["cases"]["cases"].get(row.get("nodeid"))
                                if not case or case["selftest"] or row["scenario"] not in case["scenarios"] or "random" not in case.get("roles", []) or not case["native_duts"] or case["status"] not in {"PASS", "FAIL"} or case.get("declared_native_seed") != checked["record"]["seed"]:
                                    raise ValueError(f"Random scenario {row['scenario']} needs a current, native-seeded real DUT "
                                                     "PASS or evidence-validated RTL FAIL node")
                                tested[row["nodeid"]] = case
                            else:
                                raise ValueError(f"Unknown random-test disposition for scenario: {row.get('scenario')}")
                        _validate_functional_failures(workspace, dut, project, checked, requirements, scenarios, tested)
                    if phase == "review":
                        data = delivery_data(workspace, dut, project, line_coverage_required=line_coverage_required)
                        if any(problem.startswith("native_line_coverage_") for problem in data["problems"]):
                            raise ValueError("Use CoverageInfo to finish the current native coverage review and resolve required gaps; do not rerun an unchanged valid selection just to edit analysis")
                        if (data["unclassified_failures"] or not data["full_selection"]
                                or data["missing_scenarios"] or data["unregistered_cases"] or data["problems"]):
                            raise ValueError("Review a full current DUT run, its registered native cases, every scenario and all classified failures")
                        if entry.get("run") != data["run"]:
                            raise ValueError("Review must identify the exact current signed run")
                        static_check = audit_restored_phase(workspace, dut, project, "static_validation")
                        if not static_check["ok"]:
                            raise ValueError(f"Resolve the separate static-validation gate: {static_check['error']}")
            else:
                raise ValueError(f"The phase {phase} has no acceptance implementation")
        return {"ok": True, "phase": phase, "note": "Structural evidence checked; a passing gate alone does not prove behavioral correctness.",
                **acceptance}
    except (ValueError, KeyError, TypeError, OSError, SyntaxError, yaml.YAMLError) as error:
        return {"ok": False, "error_code": "UT_STAGE_EVIDENCE_MISSING", "phase": phase,
                "error": str(error)[:2000], "next_action": "Repair the named stage artifact using Guide_Doc/ut-stages.md, then call Check again."}
