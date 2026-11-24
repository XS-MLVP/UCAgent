"""Pure build-contract substitutes: no Picker, native compilation or DUT simulation."""

import ast
import json
from pathlib import Path

import pytest

from toffee_ut.build import build_dut
from toffee_ut.paths import digest


@pytest.fixture
def recipe_workspace(tmp_path):
    """Provide text inputs only, with spaces to exercise command-file quoting."""
    workspace = tmp_path / "workspace with spaces"
    inputs = workspace / "provided"
    inputs.mkdir(parents=True)
    (workspace / "ut_project").mkdir()
    (inputs / "Top.sv").write_text("// Text fixture, never compiled.\n")
    (inputs / "Package.sv").write_text("// Dependency text fixture.\n")
    headers = inputs / "shared headers"
    headers.mkdir()
    (headers / "config.svh").write_text("// Header text fixture.\n")
    (headers / "legacy.vh").write_text("// Legacy header text fixture.\n")
    return workspace


@pytest.fixture
def controlled_picker(monkeypatch):
    """Intercept every build invocation; never start an external tool."""
    calls = []
    monkeypatch.setattr("toffee_ut.build.shutil.which", lambda name: "/controlled/picker")

    def substitute(command, cwd, stdout, stderr, timeout, cancelled, progress):
        """Record argv and create only the package-presence contract in temporary storage."""
        calls.append({"command": command, "cwd": cwd, "timeout": timeout,
                      "cancelled": cancelled, "progress": progress})
        destination = Path(command[command.index("--tdir") + 1])
        destination.mkdir()
        (destination / "__init__.py").write_text('"""Text substitute; not a native DUT."""\n')
        stdout.write_text("original stdout\n")
        stderr.write_text("original stderr\n")
        return 0, ""

    monkeypatch.setattr("toffee_ut.build.execute", substitute)
    return calls, substitute


def test_defaults_preserve_bounded_picker_recipe(recipe_workspace, controlled_picker):
    """Default options do not enable timing, macros, warning suppression or extra flags."""
    calls, _ = controlled_picker
    result = build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv")
    command = calls[0]["command"]
    assert result["ok"] and command[:3] == ["/controlled/picker", "export", str(recipe_workspace / "provided/Top.sv")]
    assert command[3:11] == ["--sim", "verilator", "--rw", "mem_direct", "--sname", "Top", "--tname", "Top"]
    assert command[-2:] == ["-j", "2"]
    assert not {"-e", "-V", "-S", "--rtl-define", "--fs"}.intersection(command)
    assert calls[0]["cwd"] == recipe_workspace / "ut_project"
    assert result["inputs"] == {"provided/Top.sv": digest(recipe_workspace / "provided/Top.sv")}
    assert result["options"] == {"timing": False, "rtl_defines": [], "include_dirs": [],
                                 "source_file": "provided/Top.sv", "filelist": [], "top": "Top",
                                 "export_name": "Top", "jobs": 2}


def test_structured_recipe_uses_canonical_flags_and_quoted_filelist(recipe_workspace, controlled_picker):
    """One macro channel and a controlled filelist preserve both stages' input identities."""
    (recipe_workspace / "provided/Top.sv").write_text('`include "config.svh"\n')
    calls, _ = controlled_picker
    result = build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv",
                       filelist=["provided/Package.sv"], include_dirs=["provided/shared headers"],
                       timing=True, rtl_defines=["FEATURE", "WIDTH=32", "RESET=1'b0"], jobs=3, timeout=17)
    assert result["ok"]
    command = calls[0]["command"]
    assert command[command.index("-V") + 1] == "--timing" and command.count("-V") == 1
    assert [command[index + 1] for index, item in enumerate(command) if item == "--rtl-define"] == [
        "FEATURE", "WIDTH=32", "RESET=1'b0"]
    assert "-S" not in command and not any(item.startswith("-D") or "Wno" in item for item in command)
    recipe = Path(command[command.index("--fs") + 1])
    assert recipe.read_text().splitlines() == [f'"+incdir+{recipe_workspace}/provided/shared headers"',
                                              f'"{recipe_workspace}/provided/Package.sv"']
    assert result["generated_inputs"] == {"inputs.f": digest(recipe)}
    assert set(result["inputs"]) == {"provided/Top.sv", "provided/Package.sv",
                                      "provided/shared headers/config.svh", "provided/shared headers/legacy.vh"}
    assert calls[0]["timeout"] == 17
    persisted = json.loads((recipe.parent / "build.json").read_text())
    assert persisted == result
    assert result["options"]["timing"] is True and result["options"]["jobs"] == 3


@pytest.mark.parametrize("options", [
    {"timing": 1}, {"timing": "false"}, {"jobs": True}, {"jobs": 0}, {"jobs": 33}, {"top": ""},
    {"top": "bad-name"}, {"rtl_defines": "FEATURE"}, {"rtl_defines": [1]}, {"include_dirs": "provided"},
    {"filelist": "provided/Package.sv"}, {"filelist": ["provided/shared headers/config.svh"]},
    {"rtl_defines": [""]}, {"rtl_defines": [" "]}, {"rtl_defines": ["NAME="]},
    {"rtl_defines": ["9NAME"]}, {"rtl_defines": ["-DNAME"]}, {"rtl_defines": ["A B=1"]},
    {"rtl_defines": ["NAME", "NAME=2"]}, {"rtl_defines": ["N=1\x00x"]},
    {"rtl_defines": ["N\nX"]}, {"rtl_defines": ["N=1\rX"]}, {"rtl_defines": ["N=1\nX"]},
    {"rtl_defines": ["N=1 --timing"]}, {"rtl_defines": ["N=$(shell touch sentinel)"]},
    {"rtl_defines": ["N=1;cmd"]}, {"rtl_defines": ['N="x"']}, {"rtl_defines": ["N=`cmd`"]},
    {"rtl_defines": ["N=foo\\bar"]}, {"rtl_defines": ["N=1#comment"]},
    {"rtl_defines": ["N=1+define+ESCAPE"]}, {"rtl_defines": ["N='foo'"]},
    {"include_dirs": ["../escape"]}, {"include_dirs": ["/absolute"]},
    {"include_dirs": ["missing"]}, {"include_dirs": ["provided/Top.sv"]},
    {"include_dirs": ["ut_project"]},
    {"include_dirs": ["provided\n+define+X"]}, {"filelist": ["-V --timing"]},
])
def test_invalid_options_create_no_output(recipe_workspace, controlled_picker, options):
    """Invalid inputs/options are rejected before creating dut/results or invoking Picker."""
    with pytest.raises(ValueError):
        build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv", **options)
    assert list((recipe_workspace / "ut_project").iterdir()) == []
    assert controlled_picker[0] == []


@pytest.mark.parametrize("relative", ["../outside.sv", "/outside.sv", "provided/Package.sv,other.sv", "provided/\x00.sv"])
def test_invalid_source_paths_are_rejected(recipe_workspace, controlled_picker, relative):
    """The top path cannot inject Picker's comma-delimited positional inputs or escape."""
    with pytest.raises(ValueError):
        build_dut(recipe_workspace, "Top", "ut_project", relative)
    assert controlled_picker[0] == []
    assert list((recipe_workspace / "ut_project").iterdir()) == []


@pytest.mark.parametrize("kind", ["directory", "header", "source", "nested_directory", "cycle"])
def test_input_links_cannot_escape_or_cycle(recipe_workspace, controlled_picker, tmp_path, kind):
    """Include roots and descendants are checked even if no active include names the link."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "external.svh").write_text("// Outside input.\n")
    includes = recipe_workspace / "provided/shared headers"
    options = {"include_dirs": ["provided/shared headers"]}
    source = "provided/Top.sv"
    if kind == "directory":
        (recipe_workspace / "provided/escape").symlink_to(outside, target_is_directory=True)
        options["include_dirs"] = ["provided/escape"]
    elif kind == "header":
        (includes / "external.svh").symlink_to(outside / "external.svh")
    elif kind == "source":
        (recipe_workspace / "provided/escape.sv").symlink_to(outside / "external.svh")
        source = "provided/escape.sv"
    else:
        (includes / "nested").symlink_to(includes if kind == "cycle" else outside, target_is_directory=True)
    with pytest.raises(ValueError):
        build_dut(recipe_workspace, "Top", "ut_project", source, **options)
    assert controlled_picker[0] == []
    assert list((recipe_workspace / "ut_project").iterdir()) == []


def test_source_adjacent_transitive_headers_are_hashed(recipe_workspace, controlled_picker):
    """Literal includes outside explicit include roots participate by byte content."""
    inputs = recipe_workspace / "provided"
    (inputs / "Top.sv").write_text('// `include "not-real"\n`include "first.svh"\n')
    (inputs / "first.svh").write_text('/* `include "not-real" */\n`include "second.inc"\n')
    (inputs / "second.inc").write_text("// Arbitrary header extension.\n")
    result = build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv")
    assert result["ok"]
    assert set(result["inputs"]) == {"provided/Top.sv", "provided/first.svh", "provided/second.inc"}


def test_include_parent_lookup_preserves_symlink_semantics(recipe_workspace, controlled_picker):
    """A link/.. header lookup hashes the real file, not an incorrect lexical sibling."""
    inputs = recipe_workspace / "provided"
    (inputs / "real/nested").mkdir(parents=True)
    (inputs / "link").symlink_to(inputs / "real/nested", target_is_directory=True)
    (inputs / "value.svh").write_text("// Wrong lexical sibling.\n")
    actual = inputs / "real/value.svh"
    actual.write_text("// Header actually reached through link/..\n")
    (inputs / "Top.sv").write_text('`include "link/../value.svh"\n')
    result = build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv")
    assert result["ok"]
    assert result["inputs"]["provided/real/value.svh"] == digest(actual)
    assert "provided/value.svh" not in result["inputs"]
    assert result["input_targets"]["provided/link/../value.svh"] == "provided/real/value.svh"


def test_project_cwd_include_is_tracked(recipe_workspace, controlled_picker):
    """Headers found through the tool's working directory are included in fingerprints."""
    (recipe_workspace / "ut_project/cwd.svh").write_text("// Cwd header.\n")
    (recipe_workspace / "provided/Top.sv").write_text('`include "cwd.svh"\n')
    result = build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv")
    assert result["ok"] and "ut_project/cwd.svh" in result["inputs"]


@pytest.mark.parametrize("include", ['"../../escape.svh"', '"/outside.svh"', '`COMPUTED', '"missing.svh"'])
def test_unprovable_includes_fail_before_output(recipe_workspace, controlled_picker, include):
    """Unsafe or unresolved dependency closure is not silently omitted from fingerprints."""
    (recipe_workspace / "provided/Top.sv").write_text(f"`include {include}\n")
    with pytest.raises(ValueError):
        build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv")
    assert controlled_picker[0] == []
    assert list((recipe_workspace / "ut_project").iterdir()) == []


@pytest.mark.parametrize("mutation", ["edit_header", "delete_header", "new_header", "retarget_link", "escaping_link",
                                      "recipe", "source", "dependency"])
def test_mutated_inputs_invalidate_success_without_losing_logs(recipe_workspace, controlled_picker, monkeypatch, mutation):
    """A zero-return substitute cannot certify changed input bytes, membership or link identity."""
    _, substitute = controlled_picker
    headers = recipe_workspace / "provided/shared headers"
    if mutation == "retarget_link":
        (headers / "same.svh").write_text((headers / "config.svh").read_text())
        (headers / "alias.svh").symlink_to(headers / "config.svh")

    def mutate(command, *args):
        """Change exactly one build input while the substitute owns the operation."""
        result = substitute(command, *args)
        if mutation == "edit_header":
            (headers / "config.svh").write_text("// Changed bytes.\n")
        elif mutation == "delete_header":
            (headers / "config.svh").unlink()
        elif mutation == "new_header":
            (headers / "new.vh").write_text("// Newly visible header.\n")
        elif mutation == "retarget_link":
            (headers / "alias.svh").unlink()
            (headers / "alias.svh").symlink_to(headers / "same.svh")
        elif mutation == "escaping_link":
            (headers / "escaped.svh").symlink_to(recipe_workspace.parent / "outside.svh")
        elif mutation == "recipe":
            Path(command[command.index("--fs") + 1]).write_text("// Changed generated recipe.\n")
        else:
            (recipe_workspace / ("provided/Top.sv" if mutation == "source" else "provided/Package.sv")).write_text("// Changed.\n")
        return result

    monkeypatch.setattr("toffee_ut.build.execute", mutate)
    result = build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv",
                       filelist=["provided/Package.sv"], include_dirs=["provided/shared headers"])
    assert not result["ok"] and result["source_changed"]
    assert result["changed_inputs"] or result["input_error"]
    log = recipe_workspace / "ut_project" / result["logs"]
    assert (log / "stdout.log").read_text() == "original stdout\n"
    assert (log / "stderr.log").read_text() == "original stderr\n"
    assert json.loads((log / "build.json").read_text())["error_code"] == "DUT_BUILD_FAILED"
    assert (recipe_workspace / "ut_project/dut/Top/__init__.py").is_file()


@pytest.mark.parametrize("existing", ["directory", "dangling_link"])
def test_existing_package_is_never_replaced(recipe_workspace, controlled_picker, existing):
    """Existing or partially built package paths are preserved, including broken links."""
    destination = recipe_workspace / "ut_project/dut/Top"
    destination.parent.mkdir()
    if existing == "directory":
        destination.mkdir()
        (destination / "sentinel").write_text("user work")
    else:
        destination.symlink_to(recipe_workspace / "absent")
    with pytest.raises(ValueError, match="already exists"):
        build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv")
    assert destination.is_symlink() if existing == "dangling_link" else (destination / "sentinel").read_text() == "user work"
    assert controlled_picker[0] == [] and not (recipe_workspace / "ut_project/results").exists()


def test_input_mutation_before_invocation_never_calls_picker(recipe_workspace, controlled_picker):
    """Revalidate inputs immediately before dispatch; a changed file cannot launch a build."""
    source = recipe_workspace / "provided/Top.sv"

    def mutate_before_dispatch():
        """Use the cancellation checkpoint to model an external edit between snapshots."""
        source.write_text("// Concurrent external edit.\n")
        return False

    result = build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv", cancelled=mutate_before_dispatch)
    assert not result["ok"] and result["source_changed"]
    assert result["changed_inputs"] == ["provided/Top.sv"]
    assert not controlled_picker[0] and not (recipe_workspace / "ut_project/dut/Top").exists()


def test_package_appearing_before_dispatch_is_preserved(recipe_workspace, controlled_picker):
    """Recheck the destination after setup to preserve newly created user output."""
    destination = recipe_workspace / "ut_project/dut/Top"

    def create_before_dispatch():
        """Model another authorized owner creating its package before tool dispatch."""
        destination.mkdir()
        (destination / "sentinel").write_text("user package")
        return False

    result = build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv", cancelled=create_before_dispatch)
    assert not result["ok"] and "nothing was replaced" in result["execution_error"]
    assert not controlled_picker[0] and (destination / "sentinel").read_text() == "user package"


@pytest.mark.parametrize("directory", ["dut", "results"])
def test_output_aliases_are_not_authorized(recipe_workspace, controlled_picker, directory):
    """Workspace-local links cannot redirect outputs outside the project's own output roots."""
    (recipe_workspace / "ut_project" / directory).symlink_to(recipe_workspace / "provided", target_is_directory=True)
    with pytest.raises(ValueError, match="own dut/results"):
        build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv")
    assert controlled_picker[0] == []
    assert not (recipe_workspace / "provided/Top").exists()


@pytest.mark.parametrize("reason", ["cancelled", "timeout", "nonzero", "launch_error", "missing_package", "pre_cancelled"])
def test_failures_and_cancellation_keep_diagnostics(recipe_workspace, controlled_picker, monkeypatch, reason):
    """Cancellation and launch/build failures retain the original logs plus a failed receipt."""
    calls, _ = controlled_picker

    def fail(command, cwd, stdout, stderr, timeout, cancelled, progress):
        """Supply deterministic failure modes without a process or native tool."""
        calls.append(command)
        stdout.write_text("untouched stdout\n")
        stderr.write_text("untouched stderr\n")
        if reason == "launch_error":
            raise OSError("controlled launch failure")
        return (0 if reason == "missing_package" else 7), (reason if reason in {"cancelled", "timeout"} else "")

    monkeypatch.setattr("toffee_ut.build.execute", fail)
    result = build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv",
                       cancelled=lambda: reason == "pre_cancelled")
    assert not result["ok"] and result["error_code"] == "DUT_BUILD_FAILED"
    assert not result["source_changed"]
    log = recipe_workspace / "ut_project" / result["logs"]
    assert json.loads((log / "build.json").read_text()) == result
    if reason == "pre_cancelled":
        assert not calls and result["interrupted"] == "cancelled"
        assert (log / "stdout.log").read_text() == (log / "stderr.log").read_text() == ""
    else:
        assert len(calls) == 1
        assert (log / "stderr.log").read_text() == "untouched stderr\n"
        assert (log / "stdout.log").read_text() == "untouched stdout\n"
    if reason == "launch_error":
        assert result["execution_error"] == result["error"] == "controlled launch failure"


def test_missing_picker_does_not_write_or_install(recipe_workspace, controlled_picker, monkeypatch):
    """Toolchain discovery fails before output and never attempts environment setup."""
    monkeypatch.setattr("toffee_ut.build.shutil.which", lambda name: None)
    with pytest.raises(ValueError, match="operator"):
        build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv")
    assert controlled_picker[0] == []
    assert list((recipe_workspace / "ut_project").iterdir()) == []


def test_workspace_local_include_alias_is_fingerprinted(recipe_workspace, controlled_picker):
    """Local include-directory links remain supported with actual bytes and targets recorded."""
    alias = recipe_workspace / "provided/alias"
    alias.symlink_to(recipe_workspace / "provided/shared headers", target_is_directory=True)
    result = build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv", include_dirs=["provided/alias"])
    assert result["ok"]
    assert result["input_targets"]["provided/alias/config.svh"] == "provided/shared headers/config.svh"
    assert result["inputs"]["provided/alias/legacy.vh"] == digest(alias / "legacy.vh")


def test_public_tool_declares_and_forwards_structured_options():
    """Inspect tool wiring without importing unavailable MCP/Pydantic/Toffee dependencies."""
    source = Path(__file__).parents[1] / "src/toffee_ut/tools.py"
    tree = ast.parse(source.read_text())
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    fields = {node.target.id: node for node in classes["BuildArgs"].body if isinstance(node, ast.AnnAssign)}
    assert {"timing", "rtl_defines", "include_dirs"} <= fields.keys()
    assert ast.unparse(fields["timing"].annotation) == "bool"
    assert ast.unparse(fields["rtl_defines"].annotation) == "list[str]"
    assert ast.unparse(fields["include_dirs"].annotation) == "list[str]"
    method = next(node for node in classes["BuildToffeeDUT"].body if isinstance(node, ast.FunctionDef) and node.name == "_run")
    assert {"timing", "rtl_defines", "include_dirs"} <= {node.arg for node in method.args.args}
    call = next(node for node in ast.walk(method) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "build_dut")
    forwarded = {node.arg: ast.unparse(node.value) for node in call.keywords}
    assert {name: forwarded[name] for name in ("timing", "rtl_defines", "include_dirs")} == {
        "timing": "args.timing", "rtl_defines": "args.rtl_defines", "include_dirs": "args.include_dirs"}
