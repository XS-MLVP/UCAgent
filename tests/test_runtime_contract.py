"""Verify completed migration decisions, real command destinations and retained test coverage."""

from __future__ import annotations

import ast
from collections import Counter
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import sysconfig

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_FILE = REPOSITORY_ROOT / "tests/fixtures/runtime/command_contract.json"


@pytest.fixture(scope="module")
def contract() -> dict:
    """Load the reviewed migration decisions without constructing any agent."""
    return json.loads(CONTRACT_FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _class_members(path: Path, class_name: str) -> dict[str, ast.AST]:
    """Read declared methods and assignment aliases from a class, without imports."""
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    classes = [
        node for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    ]
    assert len(classes) == 1, f"Expected one {class_name} declaration in {path}"
    members = {}
    for node in classes[0].body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            members[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    members[target.id] = node.value
    return members


def _assert_repository_path(relative: str, *, must_exist: bool) -> Path:
    """Require a repository-local path, including for planned future test files."""
    path = Path(relative)
    assert not path.is_absolute() and ".." not in path.parts, relative
    resolved = (REPOSITORY_ROOT / path).resolve()
    assert resolved.is_relative_to(REPOSITORY_ROOT), relative
    if must_exist:
        assert resolved.is_file(), f"Inventory references missing file: {relative}"
    return resolved


def test_custom_command_inventory_matches_source(contract: dict) -> None:
    """Retain the frozen baseline decisions while verifying the retired source is absent."""
    recorded = [item["source_symbol"] for item in contract["commands"]]
    assert len(recorded) == len(set(recorded))
    assert recorded == contract["baseline"]["command_symbols"]
    assert not (REPOSITORY_ROOT / contract["baseline"]["source_file"]).exists()


def test_business_aliases_have_explicit_canonical_destinations(contract: dict) -> None:
    """Aliases cannot hide removed commands, create cycles, or lose their owner."""
    entries = {item["name"]: item for item in contract["commands"]}
    for item in contract["commands"] + contract["inherited_commands"]:
        if item["disposition"] == "remove":
            assert item["canonical_name"] is None and item["owner"] is None, item
            continue
        canonical = item["canonical_name"]
        assert canonical in entries, item["name"]
        target = entries[canonical]
        assert target["disposition"] != "remove", item["name"]
        assert target["canonical_name"] == canonical, f"Alias chain: {item['name']}"
        if "source_kind" in item:
            assert item["owner"] == target["owner"], item["name"]


def test_inherited_debugger_surface_is_classified(contract: dict) -> None:
    """Inherited commands must be removed or explicitly bound as business aliases."""
    stdlib_pdb = Path(sysconfig.get_path("stdlib")) / "pdb.py"
    members = _class_members(stdlib_pdb, "Pdb")
    custom = {item["name"] for item in contract["commands"]}
    actual = {name[3:] for name in members if name.startswith("do_")} - custom
    entries = {item["name"]: item for item in contract["inherited_commands"]}
    assert len(entries) == len(contract["inherited_commands"])
    # The inventory includes debugger-only names found in both Python 3.12 and
    # 3.13; an absent optional name must not become a required product command.
    assert not actual - entries.keys(), f"Unclassified inherited commands: {actual - entries.keys()}"
    aliases = {name: item["canonical_name"] for name, item in entries.items()
               if item["disposition"] != "remove"}
    assert aliases == {"c": "continue", "cont": "continue", "h": "help"}
    for alias, canonical in aliases.items():
        declaration = members["do_" + alias]
        assert isinstance(declaration, ast.Name) and declaration.id == "do_" + canonical
    assert entries["clear"]["disposition"] == "remove"


def test_frontend_clear_is_distinct_from_debugger_clear(contract: dict) -> None:
    """Keep TUI output clearing without retaining PDB breakpoint clearing."""
    entries = contract["frontend_commands"]
    keys = [(item["scope"], item["name"]) for item in entries]
    assert len(keys) == len(set(keys))
    assert ("tui", "clear") in keys
    for item in entries:
        members = _class_members(
            _assert_repository_path(item["source_file"], must_exist=True), "KeyHandler"
        )
        comparisons = [node for node in ast.walk(members["process_command"])
                       if isinstance(node, ast.Compare)]
        assert any(
            isinstance(node.left, ast.Name) and node.left.id == "name"
            and any(isinstance(value, ast.Constant) and value.value == item["name"]
                    for value in node.comparators)
            for node in comparisons
        ), item["name"]
        assert item["disposition"] == "preserve"


def test_python_api_inventory_matches_source(contract: dict) -> None:
    """Every retired API has a concrete method on its current owner."""
    assert [item["source_symbol"] for item in contract["python_api"]] == contract["baseline"]["api_symbols"]
    for item in contract["python_api"]:
        owner, method = item["target_symbol"].split(".")
        assert method in _class_members(REPOSITORY_ROOT / item["owner"], owner), item


def test_inventory_destinations_and_references_are_actionable(contract: dict) -> None:
    """Each decision identifies a valid batch, owner, consumers and planned tests."""
    assert contract["schema_version"] == 1
    batches = contract["batches"]
    assert set(batches) == {f"B{number:02}" for number in range(11)}
    planned = {path for batch in batches.values() for path in batch["planned_new_tests"]}
    for path in planned:
        _assert_repository_path(path, must_exist=False)
        assert Path(path).name.startswith("test_") and path.endswith(".py"), path
    for name, entry in contract["entrypoints"].items():
        _assert_repository_path(entry["file"], must_exist=True)
        assert entry["batch"] in batches, name
    for section in ["commands", "inherited_commands", "frontend_commands", "python_api"]:
        for item in contract[section]:
            identity = item.get("name", item.get("source_symbol"))
            assert item["batch"] in batches, identity
            assert item["contract"].strip(), identity
            assert item["target_tests"], identity
            if "disposition" in item:
                assert item["disposition"] in {"preserve", "remap", "remove"}, identity
            if item["owner"] is not None:
                _assert_repository_path(item["owner"], must_exist=False)
                assert item["owner"].startswith("ucagent/"), identity
            for target in item["target_tests"]:
                _assert_repository_path(target, must_exist=target not in planned)
            for entrypoint in item.get("entrypoints", []):
                assert entrypoint in contract["entrypoints"], identity
            for relative in item.get("symbol_reference_files", []):
                path = _assert_repository_path(relative, must_exist=True)
                assert re.search(
                    r"(?<!\w)" + re.escape(item["source_symbol"]) + r"(?!\w)",
                    path.read_text(encoding="utf-8"),
                ), (identity, relative)


def test_reference_audit_has_no_unassigned_consumers(contract: dict) -> None:
    """Find new PDB/command references across code, clients, docs and examples."""
    scan = contract["reference_scan"]
    patterns = {
        name: re.compile(pattern, re.I if name == "pdb_mention" else 0)
        for name, pattern in scan["patterns"].items()
    }
    suffixes = set(scan["suffixes"])
    excluded_dirs = set(scan["excluded_directory_names"])
    excluded_files = set(scan["excluded_files"])
    paths = set()
    for relative in scan["roots"]:
        root = REPOSITORY_ROOT / relative
        assert root.exists(), relative
        if root.is_file():
            paths.add(root)
            continue
        for directory, dirs, files in os.walk(root):
            dirs[:] = sorted(name for name in dirs if name not in excluded_dirs
                             and not (Path(directory) / name).is_symlink())
            paths.update(Path(directory) / name for name in files
                         if Path(name).suffix in suffixes or name == "Makefile")
    recorded = {item["path"]: item for item in contract["reference_files"]}
    assert len(recorded) == len(contract["reference_files"])
    unassigned = {}
    for path in sorted(paths):
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        if path.is_symlink() or relative in excluded_files:
            continue
        content = path.read_text(encoding="utf-8")
        markers = {name for name, pattern in patterns.items() if pattern.search(content)}
        missing = markers - set(recorded.get(relative, {}).get("markers", []))
        if missing:
            unassigned[relative] = sorted(missing)
    assert not unassigned, f"Assign new reference files/markers to a batch: {unassigned}"
    for relative, item in recorded.items():
        _assert_repository_path(relative, must_exist=True)
        assert item["batches"] and set(item["batches"]) <= contract["batches"].keys(), relative
        assert item["markers"] and set(item["markers"]) <= patterns.keys(), relative
        assert item["review_scope"] in {
            "inspect_command_usage", "migrate_dependency_or_documentation"
        }, relative
    for connection in contract["additional_connections"]:
        assert connection["file"] in recorded
        assert connection["batch"] in recorded[connection["file"]]["batches"]


def test_test_migration_ledger_covers_each_baseline_test(contract: dict) -> None:
    """Every original test function has one migration destination and rationale."""
    planned = {path for batch in contract["batches"].values()
               for path in batch["planned_new_tests"]}
    files = [entry["source_file"] for entry in contract["test_migrations"]]
    assert len(files) == len(set(files))
    assert set(contract["baseline_suites"]) <= set(files)
    for entry in contract["test_migrations"]:
        source_file = entry["source_file"]
        if entry.get("retired"):
            assert not (REPOSITORY_ROOT / source_file).exists()
            assert set(entry["destinations"]) == set(entry["baseline_tests"])
            for destination in entry["destinations"].values():
                module = ast.parse((REPOSITORY_ROOT / destination["file"]).read_text())
                names = {node.name for node in ast.walk(module) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
                assert destination["test"] in names, destination
            continue
        path = _assert_repository_path(source_file, must_exist=True)
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        actual = []
        for node in module.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                actual.append(node.name)
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                actual.extend(node.name + "::" + child.name for child in node.body
                              if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                              and child.name.startswith("test_"))
        recorded = []
        for group in entry["groups"]:
            assert group["disposition"] in {"retain", "move", "adapt", "replace"}, source_file
            assert group["batch"] in contract["batches"] and group["contract"].strip(), source_file
            target = group["target_file"]
            _assert_repository_path(target, must_exist=target not in planned)
            assert group["tests"], source_file
            if group["disposition"] == "move" and target != source_file and set(group["tests"]).isdisjoint(actual):
                migrated = ast.parse((REPOSITORY_ROOT / target).read_text())
                names = {node.name for node in ast.walk(migrated) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
                assert set(group["tests"]) <= names, group
            else:
                recorded.extend(group["tests"])
        assert len(recorded) == len(set(recorded)), f"Duplicate test assignments: {source_file}"
        assert Counter(recorded) == Counter(actual), {
            "file": source_file,
            "unclassified": sorted(set(actual) - set(recorded)),
            "stale": sorted(set(recorded) - set(actual)),
        }


def test_replaced_behaviors_are_not_accidentally_preserved(contract: dict) -> None:
    """The migration cannot treat obsolete debugger behavior as acceptance criteria."""
    commands = {item["name"]: item for item in contract["commands"]}
    removed = {name for name, item in commands.items() if item["disposition"] == "remove"}
    assert removed == {"export_agent", "export_stage_manager", "export_checker", "exit_unset"}
    for name in ["quit", "q", "exit", "continue", "tui"]:
        assert commands[name]["disposition"] == "remap", name
    ledger = {
        entry["source_file"] + "::" + name: group
        for entry in contract["test_migrations"]
        for group in entry["groups"] for name in group["tests"]
    }
    for change in contract["behavior_changes"]:
        assert change["source_test"] in ledger, change["id"]
        group = ledger[change["source_test"]]
        assert group["disposition"] in {"replace", "adapt"}, change["id"]
        assert group["batch"] == change["batch"], change["id"]
        assert change["contract"].strip(), change["id"]


def test_explicit_registry_covers_retained_commands_and_aliases(contract: dict) -> None:
    """B01 declarations must cover every retained name, with plugin-only visibility."""
    from types import SimpleNamespace

    from ucagent.control.commands import create_registry
    from unity_test.operations.waveform_replay import waveform_commands
    from ucagent.control.controller import Controller

    registry = create_registry(Controller(SimpleNamespace(workspace=str(REPOSITORY_ROOT))))
    plugin_specs = waveform_commands(registry.controller)
    plugin_names = {spec.name for spec in plugin_specs}
    assert plugin_names == {"waveform_replay"}
    assert plugin_names.isdisjoint({row["name"] for row in registry.describe()})
    for spec in plugin_specs:
        registry.register(spec)
    entries = [entry for section in ("commands", "inherited_commands", "frontend_commands")
               for entry in contract[section] if entry["disposition"] != "remove"]
    expected = {entry["name"]: entry["canonical_name"] for entry in entries}
    expected.update({row["name"]: row["canonical_name"] for row in contract["additional_commands"]})
    actual = {name: row["name"] for row in registry.describe() for name in [row["name"], *row["aliases"]]}
    assert actual == expected
    for name, canonical in expected.items():
        spec = registry.resolve(name)
        assert spec is registry.resolve(canonical)
        assert spec.handler is not None or spec.owner in {
            "operations", "services", "stages", "host", "session", "view", "unitytest"
        }
    b01 = {entry["canonical_name"] for entry in contract["commands"] if entry["batch"] == "B01"}
    long_business = {"tool_invoke", "messages_summary"}
    assert all(callable(registry.resolve(name).handler) for name in b01 - long_business)
    assert all(registry.resolve(name).owner == "operations" for name in long_business)
