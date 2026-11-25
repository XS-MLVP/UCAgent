"""Check project contracts and derive honest delivery summaries from signed test evidence."""

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

import yaml

from .layout import project_layout
from .implementation import collect_test_files, non_verifying_cases, non_verifying_tests
from .paths import digest, local_path
from .runner import current_run
from .reports import SUMMARY_END, SUMMARY_START, render_summary
from .sources import confirmed_source_documents


class ContractLoader(yaml.SafeLoader):
    """Reject duplicate mapping keys rather than silently changing a maintained contract."""

    def construct_mapping(self, node, deep=False):
        """Read one safe mapping only when all keys have an unambiguous definition."""
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError("Contract mappings require unique string keys")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def read_spec(path, kind, dut=None, *, required=True):
    """Read the single typed YAML block embedded in a maintained Markdown document."""
    blocks = []
    for body in re.findall(r"^```yaml\s*\n(.*?)^```\s*$", Path(path).read_text(), re.M | re.S):
        value = yaml.load(body, Loader=ContractLoader)
        if isinstance(value, dict) and value.get("kind") == kind and (dut is None or value.get("dut") == dut):
            blocks.append(value)
    if not blocks and not required:
        return None
    if len(blocks) != 1:
        raise ValueError(f"{path}: expected exactly one YAML block with kind: {kind}")
    return blocks[0]


def contracts(workspace, dut, project):
    """Validate requirement/scenario identities and require reasons for excluded work."""
    layout = project_layout(workspace, dut, project)
    root = layout["root"]
    path = local_path(workspace, (Path(project) / layout["design_spec"]).as_posix())
    if "<!-- toffee-ut:unfilled -->" in path.read_text():
        raise ValueError("Complete the design contract and remove its unfilled skeleton marker")
    design = read_spec(path, "design", dut)
    if design.get("dut") != dut or not isinstance(design.get("requirements"), list) or not design["requirements"]:
        raise ValueError("Design spec must name the DUT and contain nonempty requirements")
    requirements = {}
    confirmed_sources = None
    for row in design["requirements"]:
        if not isinstance(row, dict):
            raise ValueError("Each requirement must be an object")
        for field in ("id", "statement", "precondition", "observation", "timing", "source", "basis"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"Requirement is missing a nonempty {field}")
        if row["id"] in requirements or row["basis"] not in {"confirmed", "inferred", "open"}:
            raise ValueError(f"Duplicate requirement or invalid basis: {row['id']}")
        if row["basis"] != "open":
            url = urlsplit(row["source"])
            if url.scheme:
                if url.scheme not in {"http", "https"} or not url.netloc:
                    raise ValueError(f"Source must be an HTTP(S) URL or workspace-relative file: {row['id']}")
                if row["basis"] == "confirmed":
                    raise ValueError(f"Confirmed requirement {row['id']} needs a captured independent input file, not an unverified URL")
            else:
                source = local_path(workspace, row["source"].split("#", 1)[0])
                if not source.is_file():
                    raise ValueError(f"Requirement source does not exist: {row['source']}")
                resolved_source = source.resolve()
                if row["basis"] == "confirmed" and (resolved_source == path.resolve() or any(
                        candidate.suffix.lower() in {".v", ".sv", ".vh", ".svh", ".scala"}
                        for candidate in (source, resolved_source))):
                    raise ValueError(f"Confirmed requirement {row['id']} needs an independent source, not its own contract or RTL")
                if row["basis"] == "confirmed":
                    if confirmed_sources is None:
                        confirmed_sources = confirmed_source_documents(workspace, dut, project)
                    relative = resolved_source.relative_to(Path(workspace).resolve()).as_posix()
                    if confirmed_sources.get(relative) != digest(resolved_source):
                        raise ValueError(f"Confirmed requirement {row['id']} needs an unchanged independent source captured at startup: {row['source']}; "
                                         "ask the operator to supply the source, or keep this requirement inferred/open with next_action")
        if row["basis"] != "confirmed" and (not isinstance(row.get("next_action"), str) or not row["next_action"].strip()):
            raise ValueError(f"Unconfirmed requirement needs a next_action: {row['id']}")
        requirements[row["id"]] = row
    return root, requirements


def verification_plan(root, dut, requirements):
    """Validate scenario obligations without mistaking planned tags for executed coverage."""
    layout = project_layout(root, dut, ".")
    plan = read_spec(root / layout["verification_spec"], "verification", dut)
    if plan.get("dut") != dut or not isinstance(plan.get("scenarios"), list) or not plan["scenarios"]:
        raise ValueError("Verification spec must name the DUT and contain nonempty scenarios")
    scenarios = {}
    for row in plan["scenarios"]:
        if not isinstance(row, dict):
            raise ValueError("Each scenario must be an object")
        for field in ("id", "requirement", "stimulus", "expected", "oracle", "completion", "status"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"Scenario is missing a nonempty {field}")
        if row["id"] in scenarios or row["requirement"] not in requirements:
            raise ValueError(f"Duplicate scenario or unknown requirement: {row['id']}")
        if row["status"] not in {"active", "deferred", "out-of-domain"}:
            raise ValueError(f"Invalid scenario status: {row['id']}")
        if row["status"] != "active" and (not isinstance(row.get("reason"), str) or not row["reason"].strip()):
            raise ValueError(f"Excluded scenario requires a reason: {row['id']}")
        scenarios[row["id"]] = row
    missing = set(requirements) - {row["requirement"] for row in scenarios.values()}
    if missing:
        raise ValueError(f"Requirements have no scenario or explicit scope disposition: {sorted(missing)[:12]}")
    if not any(row["status"] == "active" for row in scenarios.values()):
        raise ValueError("At least one active DUT scenario is required")
    return scenarios


def current_issues(workspace, dut, project, checked, requirements, *, nodeids=None):
    """Validate current issue attribution and per-node WaveInfo evidence, optionally for selected nodes."""
    root = project_layout(workspace, dut, project)["root"]
    cases = checked["cases"]["cases"]
    failures = {node for node, case in cases.items() if case["status"] in {"FAIL", "ERROR", "XPASS", "INCOMPLETE"}}
    issues = []
    for state in ("open", "closed"):
        for path in sorted((root / f"docs/bugs/{state}").glob("*.md")):
            issue = read_spec(path, "issue", required=False)
            if issue is None:
                # Historical notes cannot classify this workflow's current run.
                continue
            if issue.get("classification") not in {"rtl", "verification", "unconfirmed", "out-of-domain", "ruled-out"}:
                raise ValueError(f"Invalid issue classification: {path}")
            nodes = issue.get("nodeids", [])
            if not isinstance(nodes, list) or not nodes or any(not isinstance(node, str) for node in nodes):
                raise ValueError(f"Issue needs a nonempty nodeids list: {path}")
            if nodeids is not None and not set(nodes) & nodeids:
                continue
            if any(node not in cases for node in nodes):
                if issue.get("run") == checked["record"]["run"]:
                    raise ValueError(f"Issue references unknown current nodes: {path}")
                continue
            if issue.get("run") != checked["record"]["run"]:
                continue
            for field in ("evidence", "next_action"):
                if not isinstance(issue.get(field), str) or not issue[field].strip():
                    raise ValueError(f"Issue needs {field}: {path}")
            if state == "closed" and any(node in failures for node in nodes):
                raise ValueError(f"A current failure cannot be classified by a closed issue: {path}")
            if issue["classification"] == "rtl":
                requirement = issue.get("requirement")
                if requirement not in requirements or requirements[requirement]["basis"] != "confirmed":
                    raise ValueError(f"RTL classification needs a confirmed requirement; otherwise use unconfirmed: {path}")
                if any(cases[node]["status"] != "FAIL" for node in nodes):
                    raise ValueError(f"RTL classification requires actual assertion failures, not setup/teardown errors: {path}")
                from .waveform import validate_waveform_evidence
                validate_waveform_evidence(workspace, project, dut, checked, nodes, issue.get("waveform_evidence"))
            issues.append({**issue, "path": path.relative_to(root).as_posix(), "state": state})
    return issues


def delivery_data(workspace, dut, project, *, line_coverage_required=None):
    """Compute verdict, unproved scope and classified failures without changing raw results."""
    root, requirements = contracts(workspace, dut, project)
    scenarios = verification_plan(root, dut, requirements)
    checked = current_run(workspace, project)
    if checked["record"]["dut"] != dut:
        raise ValueError("The current run belongs to another DUT; call RunToffee for this DUT")
    cases = checked["cases"]["cases"]
    functional = {node: row for node, row in cases.items() if not row["selftest"]}
    problems, missing = [], []
    if non_verifying_cases(workspace, project, functional):
        problems.append("non_verifying_tests")
    if not checked["record"]["full_selection"]:
        problems.append("partial_selection")
    scenario_results = {}
    for scenario, row in scenarios.items():
        matches = [node for node, case in functional.items() if scenario in case["scenarios"]
                   and case["phases"].get("call", {}).get("outcome") in {"passed", "failed"}]
        scenario_results[scenario] = {"scope": row["status"], "nodeids": matches,
                                      "outcomes": dict(Counter(functional[node]["status"] for node in matches))}
        if row["status"] == "active" and not matches:
            missing.append(scenario)
    unknown_tags = sorted({tag for case in functional.values() for tag in case["scenarios"]} - set(scenarios))
    if unknown_tags:
        raise ValueError(f"Executed cases reference unknown scenarios: {unknown_tags[:12]}")
    unproved = [key for key, row in requirements.items() if row["basis"] != "confirmed"]
    excluded = [key for key, row in scenarios.items() if row["status"] != "active"]
    static_file = root / f"docs/reviews/{dut}-static-review.md"
    if static_file.is_file():
        static_review = read_spec(static_file, "static_review", dut)
        static_candidates = [{"id": row.get("id"), "status": row.get("status"), "source": row.get("source")}
                             for row in static_review.get("candidates", [])]
        excluded.extend(f"static:{row['id']}" for row in static_candidates if row["status"] in {"unconfirmed", "out-of-domain", None})
    else:
        static_candidates = []
        problems.append("static_review_missing")
    native_builds = [row["build"] for row in checked["manifest"].get("artifacts", []) if row["kind"] == "native"]
    expected_class = "DUT" + project_layout(workspace, dut, project)["export_name"]
    native_missing = [node for node, case in functional.items()
                      if case["phases"].get("call", {}).get("outcome") in {"passed", "failed"}
                      and not any(identity["class"] == build["name"] == expected_class and identity["source"] in build["files"]
                                  for identity in case["native_duts"] for build in native_builds)]
    if native_missing or not functional:
        problems.append("missing_per_case_native_registration")
    if not native_builds:
        problems.append("missing_native_build_evidence")
    from .coverage import coverage_data
    native_coverage = coverage_data(workspace, project, dut, checked)
    native_coverage["required"] = (checked["record"]["line_coverage_required"]
                                   if line_coverage_required is None else line_coverage_required)
    if native_coverage["required"]:
        if native_coverage["line"]["state"] != "collected":
            problems.append("native_line_coverage_not_collected")
        if native_coverage["review"]["state"] != "complete":
            problems.append("native_line_coverage_review_" + native_coverage["review"]["state"])
    functional_coverage = {"groups": [], "covered": False}
    for artifact in checked["manifest"].get("artifacts", []):
        if artifact["kind"] == "functional":
            from toffee import CoverageDatabase
            report = CoverageDatabase.read_json(artifact["path"]).report()
            functional_coverage = {"covered": report["covered"], "coverage": report["coverage"],
                                   "groups": [{key: group[key] for key in ("instance", "samples", "coverage", "goal",
                                               "covered", "has_illegal", "collection_complete")}
                                              for group in report["groups"]]}
    outcomes = Counter(case["status"] for case in cases.values())
    failures = [node for node, case in cases.items() if case["status"] in {"FAIL", "ERROR", "XPASS", "INCOMPLETE"}]
    issues = current_issues(workspace, dut, project, checked, requirements)
    classified = {node for issue in issues if issue["state"] == "open" for node in issue["nodeids"]}
    unclassified = sorted(set(failures) - classified)
    if failures:
        status = "FAIL"
    elif (problems or missing or unproved or excluded or not functional_coverage["covered"]
          or any(outcomes[key] for key in ("UNCERTAIN", "SKIP", "XFAIL"))):
        status = "INCOMPLETE"
    else:
        status = "PASS"
    record = checked["record"]
    layout = project_layout(workspace, dut, project)
    source_map = record.get("source_after")
    provenance = {"project_root": str(root.resolve()), "workspace_root": str(Path(workspace).resolve()),
                  "runtime": record.get("runtime"), "selection": record.get("selection"),
                  "returncode": record.get("returncode"),
                  "source_identity": None if source_map is None else {
                      "files": len(source_map), "sha256": hashlib.sha256(json.dumps(
                          source_map, sort_keys=True, separators=(",", ":")).encode()).hexdigest()},
                  "native_builds": [{"name": build["name"], "build_id": build["build_id"],
                      "file_count": len(build["files"]),
                      "native_duts": [{"class": name, "source": source} for name, source in sorted({
                          (identity["class"], identity["source"]) for case in cases.values() for identity in case["native_duts"]
                          if identity["class"] == build["name"] and identity["source"] in build["files"]})]}
                      for build in native_builds],
                  "raw_artifacts": sorted({f"{record['run']}/{name}" for name in
                      {*record.get("files", {}), "receipt.json", "manifest.json", "cases.json"}})}
    return {"status": status, "run": checked["record"]["run"], "tests": dict(outcomes),
            "full_selection": checked["record"]["full_selection"], "problems": problems,
            "missing_scenarios": missing, "unconfirmed_requirements": unproved,
             "scope_exclusions": excluded, "static_candidates": static_candidates, "unregistered_cases": native_missing,
            "unclassified_failures": unclassified, "failing_nodes": failures, "issues": issues,
             "scenarios": scenario_results, "functional_coverage": functional_coverage,
             "native_coverage": native_coverage,
            "requested_seed": checked["record"]["seed"],
            "coverage_artifacts": [row["path"] for row in checked["manifest"].get("artifacts", [])
                                   if row["kind"] in {"html", "functional", "lcov"}],
             "receipt_signature": checked["record"]["signature"],
             "case_counts": {label: {"total": len(rows), "outcomes": dict(Counter(row["status"] for row in rows))}
                             for label, rows in (("all", list(cases.values())), ("functional", list(functional.values())),
                                                  ("selftest", [row for row in cases.values() if row["selftest"]]))},
             "case_details": cases, "provenance": provenance,
             "contracts": {"design_path": layout["design_spec"], "verification_path": layout["verification_spec"],
                           "requirements": requirements, "scenarios": scenarios}}


def summarize(workspace, dut, project, *, line_coverage_required=None):
    """Update only the owned block of docs/README.md; preserve user-authored text."""
    data = delivery_data(workspace, dut, project, line_coverage_required=line_coverage_required)
    path = local_path(workspace, (Path(project) / "docs/README.md").as_posix())
    start, end = SUMMARY_START, SUMMARY_END
    block = render_summary(data).encode("utf-8")
    # Byte slicing preserves user content, including CRLF and final whitespace.
    original = path.read_bytes() if path.exists() else b"\n# Verification report\n\n"
    start, end = start.encode(), end.encode()
    if start in original or end in original:
        if original.count(start) != 1 or original.count(end) != 1 or original.index(start) > original.index(end):
            raise ValueError("Summary markers are malformed; repair only the marker boundaries")
        a, b = original.index(start), original.index(end) + len(end)
        text = original[:a] + block + original[b:]
    else:
        text = original + b"\n\n" + block + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text)
    return data


def audit_project(workspace, dut, project="ut_project", phase="tests", *, line_coverage_required=None):
    """Run deterministic phase checks, returning bounded repair instructions."""
    from .stage_audit import RESTORED_PHASES, audit_restored_phase
    if phase in RESTORED_PHASES:
        return audit_restored_phase(workspace, dut, project, phase, line_coverage_required=line_coverage_required)
    try:
        if phase not in {"inputs", "design", "plan", "environment", "tests", "triage", "final"}:
            raise ValueError("Unknown UT audit phase")
        root = local_path(workspace, project, allow_root=True)
        if phase == "inputs":
            inventory = json.loads((root / "results/input_inventory.json").read_text())
            if not inventory["rtl"]:
                raise ValueError("No RTL input found; configure runtime_options.ut_rtl_dirs")
            if inventory["dut"] != dut or inventory["project"] != project:
                raise ValueError("Input inventory belongs to another task; call UTProject(action='inspect')")
            for key in ("documents", "rtl"):
                for path, expected in inventory[key].items():
                    if digest(local_path(workspace, path)) != expected:
                        raise ValueError(f"Input changed: {path}; call UTProject(action='inspect')")
            for path in (root / "conftest.py", root / "pytest.ini"):
                if not path.is_file():
                    raise ValueError("Create or adopt the project pytest entrypoints with UTProject(action='scaffold')")
        else:
            root, requirements = contracts(workspace, dut, project)
            if phase != "design":
                verification_plan(root, dut, requirements)
            if phase in {"environment", "tests", "triage", "final"}:
                layout = project_layout(workspace, dut, project)
                bench = root / "testbenches" / layout["testbench"]
                required = [root / "conftest.py", root / "pytest.ini", root / layout["environment"],
                            *[root / path for path in layout["tests"]]]
                if not all(path.exists() for path in required):
                    raise ValueError("Missing project pytest configuration, DUT environment or tests")
                code = list(bench.rglob("*.py"))
                if not code:
                    raise ValueError("Testbench contains no Python implementation")
                for path in [root / "conftest.py", *code]:
                    local_path(workspace, path.relative_to(Path(workspace).resolve()).as_posix())
                    ast.parse(path.read_text(), filename=str(path))
                for role in ("env", "transactions", "model", "checker", "coverage"):
                    if (bench / role).exists() and (bench / f"{role}.py").exists():
                        raise ValueError(f"Use either {role}.py or {role}/, not both")
                if list(bench.rglob("conftest.py")) or list(bench.rglob("pytest.ini")):
                    raise ValueError("Keep pytest fixtures and configuration at the project root only")
                if phase != "environment":
                    tests = collect_test_files(root, layout["tests"])
                    if not tests:
                        raise ValueError("No Python test files match the declared test locations and pytest naming options")
                    for path in tests:
                        tree = ast.parse(path.read_text())
                        if any(isinstance(node, ast.Assert) and isinstance(node.test, ast.Constant)
                               and not node.test.value and isinstance(node.msg, ast.Constant)
                               and node.msg.value == "Not implemented" for node in ast.walk(tree)):
                            raise ValueError(f"Unimplemented placeholder assertion: {path.relative_to(root)}")
                        empty = non_verifying_tests(path, project=root)
                        if empty:
                            name, line = next(iter(empty.items()))
                            raise ValueError(f"Unimplemented failure-only or vacuous test: {path.relative_to(root)}:{line}::{name}; "
                                             "implement real stimulus, comparison and completion obligations instead of relabeling its failure")
            if phase in {"triage", "final"}:
                data = delivery_data(workspace, dut, project, line_coverage_required=line_coverage_required)
                if data["unclassified_failures"]:
                    raise ValueError(f"Classify failing nodes in docs/bugs/open: {data['unclassified_failures'][:12]}")
                if phase == "final":
                    for stage_phase in ("static", "static_validation"):
                        check = audit_restored_phase(workspace, dut, project, stage_phase)
                        if not check["ok"]:
                            raise ValueError(f"{stage_phase} is not complete: {check['error']}")
                    if any(problem.startswith("native_line_coverage_") for problem in data["problems"]):
                        raise ValueError("Native coverage is missing, unreviewed or has unresolved gaps. Call CoverageInfo and repair the current coverage review; rerun tests only if collection or stimulus must change")
                    if not data["full_selection"] or data["missing_scenarios"] or data["problems"]:
                        raise ValueError("Run the complete DUT selection with scenario and native DUT evidence before delivery")
                    if (any(data["tests"].get(key) for key in ("ERROR", "XPASS"))
                            or any(issue["classification"] == "verification" and set(issue["nodeids"]) & set(data["failing_nodes"])
                                   for issue in data["issues"] if issue["state"] == "open")):
                        raise ValueError("Fix current verification-infrastructure failures before delivery")
                    text = (root / "docs/README.md").read_bytes()
                    start, end = SUMMARY_START.encode(), SUMMARY_END.encode()
                    if (text.count(start) != 1 or text.count(end) != 1 or text.index(start) > text.index(end)
                            or text[text.index(start):text.index(end) + len(end)] != render_summary(data).encode("utf-8")):
                        raise ValueError("Call UTProject(action='summary') for the current run")
                    return {"ok": True, "phase": phase, "verification_status": data["status"],
                            "note": "Workflow delivery is not a claim that all hardware behavior passed."}
        return {"ok": True, "phase": phase}
    except (ValueError, KeyError, TypeError, OSError, SyntaxError, yaml.YAMLError) as error:
        return {"ok": False, "error_code": "UT_ARTIFACT_INVALID", "phase": phase,
                "error": str(error)[:2000], "next_action": "Repair the named artifact using Guide_Doc/ut-contracts.md, then call Check again."}
