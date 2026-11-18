"""Freeze native ACT plans and authenticated normative-rule inputs for generation."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from urllib.request import urlopen

from .resources import git_text
from .xiangshan_bundle import safe_path, sha256, write_json


RULES_URL = "https://riscv.github.io/riscv-isa-manual/snapshot/norm-rules/norm-rules.json"


def native_plan_path(suite: str, kind: str) -> str:
    """Return the canonical upstream testplan path, rejecting ambiguous suite identifiers."""
    if not re.fullmatch(r"[A-Za-z0-9_]+", suite) or kind not in {"privileged", "unprivileged"}:
        raise ValueError("Specify an exact ACT suite and privileged or unprivileged generation")
    return f"testplans/priv/{suite}.yaml" if kind == "privileged" else f"testplans/{suite}.csv"


def load_rules(path: Path) -> dict[str, dict]:
    """Read the native norm-rules.json structure without accepting author-invented aliases."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("normative_rules"), list):
        raise ValueError(f"{path}: require a normative_rules array of name/text records")
    rules = {}
    for record in data["normative_rules"]:
        if (not isinstance(record, dict) or not isinstance(record.get("name"), str)
                or not re.fullmatch(r"[\w.-]+", record["name"])
                or not isinstance(record.get("text"), str)):
            raise ValueError(f"{path}: every rule needs a nonempty native name and a string text field")
        if record["name"] in rules:
            raise ValueError(f"{path}: duplicate normative rule {record['name']}")
        rules[record["name"]] = record
    if not rules:
        raise ValueError(f"{path}: normative rule set is empty")
    return rules


def read_generation_inputs(directory: Path, get_value) -> dict:
    """Verify recorded preparation, immutable snapshots, and both pinned repositories."""
    receipt = directory / "receipt.json"
    if not receipt.is_file() or get_value(f"act4_generation_inputs:{directory}", None) != sha256(receipt):
        raise ValueError("Return to prepare_generation_inputs and prepare the sources; do not edit its receipt")
    data = json.loads(receipt.read_text(encoding="utf-8"))
    for name, digest in data["files"].items():
        if sha256(safe_path(directory, name)) != digest:
            raise ValueError(f"Generation input changed: {name}; restore the captured input")
    for role in ("act4", "manual"):
        if git_text(Path(data[role]["path"]), "rev-parse", "HEAD") != data[role]["head"]:
            raise ValueError(f"Pinned {role} revision changed; start a new generation run")
    for name, digest in data["manual_sources"].items():
        if sha256(safe_path(Path(data["manual"]["path"]), name)) != digest:
            raise ValueError(f"Read-only ISA source changed: {name}; restore the pinned checkout")
    return data


def prepare_generation_inputs(directory: Path, act4: Path, manual: Path, suite: str,
                              kind: str, manual_files: list[str]) -> dict:
    """Snapshot pinned native inputs; the public rule index and manual revisions remain distinct."""
    plan = native_plan_path(suite, kind)
    if (not isinstance(manual_files, list) or not manual_files
            or any(not isinstance(name, str) for name in manual_files)
            or len(set(manual_files)) != len(manual_files)):
        raise ValueError("manual_files must list distinct source ADOC files relevant to this suite")
    heads = {"act4": {"path": str(act4), "head": git_text(act4, "rev-parse", "HEAD")},
             "manual": {"path": str(manual), "head": git_text(manual, "rev-parse", "HEAD")}}
    if git_text(manual, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("ISA source has tracked modifications; use a clean pinned manual checkout")
    directory.mkdir(parents=True, exist_ok=True)
    files, manual_sources, tags, locations = {}, {}, set(), {}
    for name in manual_files:
        if not name.startswith("src/") or not name.endswith(".adoc"):
            raise ValueError(f"Select ISA source files under src/: {name}")
        source = safe_path(manual, name)
        content = source.read_bytes()
        original = subprocess.run(["git", "-C", str(manual), "show", f"{heads['manual']['head']}:{name}"],
                                  check=True, capture_output=True, timeout=30).stdout
        if original != content:
            raise ValueError(f"ISA source is not from the pinned commit: {name}")
        target = safe_path(directory, "manual/" + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        files[target.relative_to(directory).as_posix()] = sha256(target)
        manual_sources[name] = sha256(source)
        for number, line in enumerate(content.decode("utf-8").splitlines(), 1):
            for tag in set(re.findall(r"norm:([\w.-]+)", line)):
                tags.add(tag)
                locations.setdefault(tag, []).append({"file": target.relative_to(directory).as_posix(), "line": number})
    with urlopen(RULES_URL, timeout=60) as response:
        if not response.geturl().startswith("https://riscv.github.io/riscv-isa-manual/"):
            raise ValueError("Normative-rule download redirected outside the official ISA publication")
        content = response.read(20_000_001)
    if len(content) > 20_000_000:
        raise ValueError("Normative-rule response exceeds the bounded snapshot size")
    published = directory / "published-norm-rules.json"
    published.write_bytes(content)
    rules = load_rules(published)
    selected = sorted(tags & rules.keys())
    if not selected:
        raise ValueError("Selected ISA sources have no rules in the published index; select relevant tagged sources")
    write_json(directory / "norm-rules.json", {"normative_rules": [rules[name] for name in selected]})
    files[published.name] = sha256(published)
    files["norm-rules.json"] = sha256(directory / "norm-rules.json")
    source_plan = subprocess.run(["git", "-C", str(act4), "show", f"{heads['act4']['head']}:{plan}"],
                                 capture_output=True, timeout=30)
    tracked = git_text(act4, "ls-tree", "--name-only", heads["act4"]["head"], "--", plan)
    if source_plan.returncode and tracked:
        raise ValueError(f"Cannot capture tracked native testplan: {plan}")
    if not source_plan.returncode:
        target = directory / ("source-plan.yaml" if kind == "privileged" else "source-plan.csv")
        target.write_bytes(source_plan.stdout)
        files[target.name] = sha256(target)
    schema_path = "testplans/priv/testplan.schema.json"
    if kind == "privileged":
        schema = subprocess.run(["git", "-C", str(act4), "show", f"{heads['act4']['head']}:{schema_path}"],
                                check=True, capture_output=True, timeout=30)
        (directory / "testplan.schema.json").write_bytes(schema.stdout)
        files["testplan.schema.json"] = sha256(directory / "testplan.schema.json")
    non_text_rules = [name for name in selected if not rules[name]["text"].strip()]
    limitations = ["Published rule text and pinned manual are separate snapshots; compare semantics before implementation."]
    if non_text_rules:
        limitations.append("Selected non-text rules require inspection of the original encoding figures/tables and their dependencies; empty published text is not a semantic explanation.")
    data = {"schema_version": 1, "suite": suite, "kind": kind, **heads, "native_plan": plan,
            "source_plan": target.name if not source_plan.returncode else None,
            "new_suite": bool(source_plan.returncode), "files": files, "manual_sources": manual_sources,
            "rules_url": RULES_URL, "unpublished_tags": sorted(tags - rules.keys()),
            "rule_locations": {name: locations[name] for name in selected}, "non_text_rules": non_text_rules,
            "limitations": limitations}
    write_json(directory / "receipt.json", data)
    return data
