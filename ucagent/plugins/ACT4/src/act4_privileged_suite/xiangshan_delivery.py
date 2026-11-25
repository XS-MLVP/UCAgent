"""Publish minimal recipient assets while retaining build and audit evidence with the producer."""

from __future__ import annotations

import json
import copy
from pathlib import Path
import re
import shutil

from . import xiangshan_bundle as bundle


def publish(directory: Path, package: Path, plan: dict, result: dict, trace: dict, scope: dict,
            target: dict, status: str, summary: str, environment: list[dict], run: dict | None) -> dict:
    """Create one guide, one ACT index and reproducible consumer inputs from verified producer records."""
    directory.mkdir(parents=True)
    for name in plan["files"]:
        if not name.startswith("act4/"):
            continue
        relative = name.removeprefix("act4/")
        if relative.endswith((".log", ".sig", ".results")):
            continue
        if relative.startswith("selected-tests/"):
            destination = "src/" + relative.removeprefix("selected-tests/")
        elif relative.startswith("config/xiangshan-kmhv3/"):
            destination = "config/" + relative.removeprefix("config/xiangshan-kmhv3/")
        elif relative.startswith("tests/") and not relative.startswith("tests/env/"):
            continue
        else:
            destination = "framework/" + relative
        output = bundle.safe_path(directory, destination)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundle.safe_path(package, name), output)
    run_tests = {test["source"]: test for test in run["tests"]} if run else {}
    built = {test["source"]: test for test in result["tests"]} if result["status"] == "passed" else {}
    tests = []
    for test in plan["tests"]:
        source = test["path"]
        record = {**test, "build_status": "passed" if source in built else "not_built",
                  "run_status": run_tests.get(source, {}).get("status", "not_run")}
        if run_tests.get(source, {}).get("reason"):
            record["run_reason"] = run_tests[source]["reason"]
        if source in built:
            for kind in ("elf", "bin", "disass"):
                relative = f"{kind}/{Path(source).with_suffix('.' + kind)}"
                output = bundle.safe_path(directory, relative)
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(bundle.safe_path(package, built[source][kind]), output)
                record[kind] = relative
            record["entry"] = built[source]["entry"]
            record["binary_load_address"] = built[source]["binary_load_address"]
        tests.append(record)
    resources = Path(__file__).parent
    shutil.copy2(resources / "xiangshan_recipient.py", directory / "handoff.py")
    shutil.copy2(resources / "xiangshan_bundle.py", directory / "act4_driver.py")
    shutil.copy2(resources / "handoff/Makefile", directory / "Makefile")
    versions = {}
    for label, tool in result["tool_versions"].items():
        versions[label] = (package / tool["log"]).read_text(errors="replace")[:1000].strip()
    required_commands = set(plan["tools"].values()) | {"{PYTHON}", "python", "python3", "bash", "git", "curl", "make", "tar", "ruby", "bundle", "bundler"}
    recipes = [copy.deepcopy(tool) for tool in environment if tool["id"] != "lint" and tool["probe"][0] in required_commands]
    for tool in recipes:
        if any(part.startswith(("/", "~/")) or re.search(r"=/|=~/", part) for command in tool["install"] for part in command):
            tool["install"] = []
            tool["basis"] = "Use the specified version from PATH; the producer used a host-local installation recipe that cannot be transferred"
            tool["unavailable_reason"] = "Provide a matching local installation or a portable installation recipe; no producer-local paths are shipped"
    known = {tool["probe"][0] for tool in recipes}
    for label, executable in plan["tools"].items():
        if executable not in known:
            version = versions.get(label, "").splitlines()[0] if versions.get(label) and result["tool_versions"][label]["status"] == "passed" else ""
            recipes.append({"id": label, "version": version, "basis": "Recorded build tool probe; inspect local/setup on mismatch",
                            "probe": [executable, "--version"], "expected_output": re.escape(version) or ".+",
                            "install": [], "bin_dirs": ["bin"]})
    provenance = json.loads((package / "provenance.json").read_text())["repositories"]
    manifest = {"schema_version": 1, "suite": plan["suite"], "status": status, "target": plan["target"],
                "memory": plan["memory"], "tools": plan["tools"], "tool_versions": versions, "environment": recipes,
                "tests": tests, "provenance": provenance}
    text = (resources / "handoff/README.md").read_text(encoding="utf-8")
    target_summary = f"{target['family']} / {target['configuration']} / {target['top']} / {target['commit']}"
    substitutions = {"@@SUITE@@": plan["suite"], "@@STATUS@@": status, "@@SUMMARY@@": summary,
                     "@@TARGET@@": target_summary, "@@COUNT@@": str(len(tests)), "@@EXAMPLE@@": tests[0]["path"],
                     "@@LIMITATIONS@@": "\n".join(f"- {item}" for item in target["limitations"]) or "- See TESTS.md for per-program scope.",
                     "@@VERSIONS@@": "\n".join(f"- `{label}`: `{value.splitlines()[0] if value else 'not measured'}`" for label, value in versions.items())}
    for marker, replacement in substitutions.items():
        text = text.replace(marker, replacement)
    (directory / "README.md").write_text(text, encoding="utf-8")
    (directory / "TESTS.md").write_text(bundle.trace_report(trace, tests, scope["features"]), encoding="utf-8")
    manifest["files"] = {str(path.relative_to(directory)): bundle.identity(path) for path in directory.rglob("*") if path.is_file()}
    bundle.write_json(directory / "manifest.json", manifest)
    return manifest
