"""File authorization across stage handoffs, split workers and CLI sandbox presentation."""

import json
import stat
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from test_multi_agent import finish, make_agent, stage, submit_ready, tool


@pytest.mark.parametrize("scope", ["stage", "task"])
@pytest.mark.parametrize("backend", ["langchain", "codex"])
def test_later_stage_can_read_and_update_previous_output(tmp_path, backend, scope):
    """A later owner may revise an existing artifact explicitly declared as its output."""
    relative = "out/shared.txt"
    agent = make_agent(tmp_path, stages=[stage("first", output_files=[relative]),
                                       stage("second", output_files=[relative])],
                       config_overrides={"backend.key_name": backend})
    observed = []

    def run(worker):
        """Use production bound file tools in two distinct stage workers."""
        artifact = worker.artifact_path(relative)
        index = worker.stage_manager.stage_index
        if index:
            assert artifact.read_text() == "first stage"
            assert artifact.stat().st_mode & stat.S_IWUSR
            assert relative not in tool(worker, "CurrentTips")["file_access"]["un_write_dirs"]
        tool(worker, "EditTextFile", path=relative, content="second stage" if index else "first stage")
        if not worker.record.split:
            tool(worker, "SetCurrentStageJournal", journal="Updated the assigned artifact.")
        submit_ready(worker, summary="Updated the assigned artifact.")
        observed.append(worker.session_id)

    agent.multi_agent.runner_factory = run
    try:
        for index in range(2):
            plan_id = f"stage-{index}"
            agent.multi_agent.submit({"plan_id": plan_id, "scope": scope, "tasks": [{
                "id": "author", "instruction": "Revise the assigned artifact.",
                "inputs": [relative] if index else [], "outputs": [relative]}]})
            result = finish(agent.multi_agent, plan_id)
            assert result["plans"][plan_id]["state"] == "completed", result
            if index == 0:
                (tmp_path / relative).chmod(0o640)
        assert (tmp_path / relative).read_text() == "second stage"
        assert stat.S_IMODE((tmp_path / relative).stat().st_mode) == 0o640
        assert len(observed) == len(set(observed)) == 2
    finally:
        agent._startup_cleanup.close()


@pytest.mark.parametrize("backend", ["langchain", "codex"])
def test_split_worker_can_create_only_its_output_parent_directories(tmp_path, backend):
    """Nested output scaffolding is writable without granting sibling files or directories."""
    relative = "out/nested/deep/result.txt"
    agent = make_agent(tmp_path, stages=[stage("split", output_files=[relative])],
                       config_overrides={"backend.key_name": backend})

    def run(worker):
        """Create required directories and prove task output fences still reject siblings."""
        result = tool(worker, "CreateDirectory", path="out/nested/deep")
        assert (Path(worker.workspace) / "out/nested/deep").is_dir(), result
        with pytest.raises(PermissionError, match="outside this task"):
            tool(worker, "CreateDirectory", path="out/unassigned")
        with pytest.raises(PermissionError, match="outside this task"):
            tool(worker, "EditTextFile", path="out/nested/deep/other.txt", content="denied")
        tool(worker, "EditTextFile", path=relative, content="assigned evidence")
        submit_ready(worker, summary="Created the assigned output.")

    agent.multi_agent.runner_factory = run
    try:
        agent.multi_agent.submit({"plan_id": "nested", "scope": "task", "tasks": [{
            "id": "author", "instruction": "Create the nested output.", "outputs": [relative]}]})
        result = finish(agent.multi_agent, "nested")
        assert result["plans"]["nested"]["state"] == "completed", result
        assert (tmp_path / relative).read_text() == "assigned evidence"
        assert not (tmp_path / "out/unassigned").exists()
    finally:
        agent._startup_cleanup.close()


@pytest.mark.parametrize("backend", ["langchain", "codex"])
def test_split_input_only_artifact_is_reported_and_enforced_as_read_only(tmp_path, backend):
    """Input protection is task-local and denies edits before corrupting source content."""
    source = "out/reference.txt"
    output = "out/result.txt"
    agent = make_agent(tmp_path, stages=[stage("one", output_files=[output])],
                       config_overrides={"backend.key_name": backend})
    (tmp_path / "out").mkdir(exist_ok=True)
    (tmp_path / source).write_text("reference evidence")

    def run(worker):
        """Observe the same effective write policy used by the actual file tools."""
        with pytest.raises(PermissionError, match="read-only input"):
            tool(worker, "EditTextFile", path=source, content="must not replace source")
        assert (tmp_path / source).read_text() == "reference evidence"
        access = tool(worker, "CurrentTips")["file_access"]
        assert source in access["un_write_dirs"]
        tool(worker, "EditTextFile", path=output, content="derived evidence")
        submit_ready(worker, summary="Derived output ready.")

    agent.multi_agent.runner_factory = run
    try:
        agent.multi_agent.submit({"plan_id": "read-only-input", "scope": "task", "tasks": [{
            "id": "author", "instruction": "Use the reference.", "inputs": [source], "outputs": [output]}]})
        result = finish(agent.multi_agent, "read-only-input")
        assert result["plans"]["read-only-input"]["state"] == "completed", result
        assert agent.cfg.un_write_dirs == []
    finally:
        agent._startup_cleanup.close()


def test_unprotect_all_does_not_reprotect_previous_files(tmp_path):
    """Removing all active protections must not leave stale entries for the next call."""
    agent = make_agent(tmp_path)
    first, second = tmp_path / "out/first.txt", tmp_path / "out/second.txt"
    first.parent.mkdir(exist_ok=True)
    first.write_text("first")
    second.write_text("second")
    try:
        agent.protect_files_on(["out/first.txt"])
        agent.protect_files_off([])
        assert first.stat().st_mode & stat.S_IWUSR
        agent.protect_files_on(["out/second.txt"])
        assert first.stat().st_mode & stat.S_IWUSR
        assert not second.stat().st_mode & stat.S_IWUSR
    finally:
        agent._startup_cleanup.close()


@pytest.mark.parametrize("managed", [True, False])
def test_codex_managed_sandbox_banner_does_not_override_mcp_file_authority(managed):
    """Managed MCP authorization remains separate from native Codex sandbox presentation."""
    assets = Path(__file__).parents[1] / "ucagent/core/backends/assets"
    template = Environment(loader=FileSystemLoader(assets), undefined=StrictUndefined)
    argv = json.loads(template.get_template("cli_codex_args.json.j2").render(
        executable="codex", managed=managed, inherited=[], server_name="ucagent_test",
        mcp_url="http://127.0.0.1:12345/mcp", tool_timeout=300, mcp_token="test-token",
        tools=["EditTextFile"]))
    if managed:
        assert 'sandbox_mode="read-only"' in argv
        assert 'features.shell_tool=false' in argv
        assert "include_permissions_instructions=false" in argv
        assert 'mcp_servers.ucagent_test.tools.EditTextFile.approval_mode="approve"' in argv
    else:
        assert 'sandbox_mode="workspace-write"' in argv
        assert "include_permissions_instructions=false" not in argv
        assert 'mcp_servers.ucagent_test.tools.EditTextFile.approval_mode="approve"' in argv


@pytest.mark.parametrize("managed", [False, True])
def test_codex_inherited_servers_share_one_complete_override(managed):
    """Whole-table overrides retain every disabled server and a valid transport."""
    import tomllib

    inherited = [
        {"name": "local", "transport": {"type": "stdio", "command": "mcp-local"}},
        {"name": "remote.with.dot", "transport": {"type": "streamable_http", "url": "http://localhost:1/mcp"}},
        {"name": 'quoted"name', "transport": {"type": "stdio", "command": "mcp-other"}},
    ]
    template = Environment(loader=FileSystemLoader(Path(__file__).parents[1] / "ucagent/core/backends/assets"),
                           undefined=StrictUndefined)
    argv = json.loads(template.get_template("cli_codex_args.json.j2").render(
        executable="codex", managed=managed, inherited=inherited, server_name="ucagent_test",
        mcp_url="http://localhost:12345/mcp", tool_timeout=300, mcp_token="", tools=[]))
    overrides = [argument for argument in argv if argument.startswith("mcp_servers=")]
    assert len(overrides) == 1
    servers = tomllib.loads(overrides[0])["mcp_servers"]
    assert set(servers) == {server["name"] for server in inherited}
    for server in inherited:
        transport = server["transport"]
        field = "command" if transport["type"] == "stdio" else "url"
        assert servers[server["name"]] == {"enabled": False, field: transport[field]}


@pytest.mark.parametrize("declare_output", [False, True])
def test_in_place_output_still_requires_its_declared_input(tmp_path, declare_output):
    """An absent declared input cannot become a fabricated in-place update."""
    relative = "out/missing.txt"
    agent = make_agent(tmp_path, stages=[stage("one", output_files=[relative])])
    started = []

    def run(worker):
        """Record an invalid execution that must be rejected before tools are exposed."""
        started.append(worker.record.key)
        tool(worker, "EditTextFile", path=relative, content="invented source")
        submit_ready(worker, summary="Unexpected execution.")

    agent.multi_agent.runner_factory = run
    try:
        agent.multi_agent.submit({"plan_id": "missing", "tasks": [{
            "id": "author", "instruction": "Revise the existing input.",
            "inputs": [relative], "outputs": [relative] if declare_output else []}]})
        result = finish(agent.multi_agent, "missing")
        assert result["plans"]["missing"]["state"] == "failed", result
        assert not started
        assert not (tmp_path / relative).exists()
    finally:
        agent._startup_cleanup.close()


@pytest.mark.parametrize("scope", ["stage", "task"])
def test_declared_in_place_output_cannot_override_workflow_read_only_policy(tmp_path, scope):
    """Declaring a file as an output never grants authority over protected workflow inputs."""
    relative = "out/protected.txt"
    path = tmp_path / relative
    path.parent.mkdir()
    path.write_text("protected source")
    path.chmod(0o640)
    agent = make_agent(tmp_path, config_overrides={"un_write_dirs": [relative]})
    try:
        with pytest.raises(PermissionError, match="no-write entry"):
            agent.multi_agent.submit({"plan_id": "protected", "scope": scope, "tasks": [{
                "id": "author", "instruction": "Attempt to modify a protected file.",
                "inputs": [relative], "outputs": [relative]}]})
        assert path.read_text() == "protected source"
        assert not agent.multi_agent.records
    finally:
        agent._startup_cleanup.close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


@pytest.mark.parametrize("scope", ["stage", "auto", "subtree"])
@pytest.mark.parametrize("backend", ["langchain", "codex"])
@pytest.mark.parametrize("declare_report", [False, True])
def test_stage_handoff_can_update_inputs_without_listing_them_as_outputs(
        tmp_path, scope, backend, declare_report):
    """Stage/subtree tools and final validation permit workflow-writable input updates."""
    api = "out/DUT_api.py"
    report = "out/review.txt"
    environment = (stage("environment", output_files=[api]) if scope == "stage" else
                   stage("environment", stage=[stage("bundle", output_files=[api]),
                                               stage("fixture", output_files=[api])]))
    agent = make_agent(tmp_path, stages=[stage("create_dut", output_files=[api]), environment],
                       config_overrides={"backend.key_name": backend})
    observed = []

    def run(worker):
        """Create the API in one session and extend it in a later stage-owned session."""
        observed.append(worker.session_id)
        if worker.stage_manager.get_current_stage().name == "create_dut":
            tool(worker, "EditTextFile", path=api, content="dut_ready = True\n")
            tool(worker, "SetCurrentStageJournal", journal="Created DUT construction.")
        else:
            assert api in worker.record.spec.inputs
            assert api not in worker.record.spec.outputs
            assert api not in tool(worker, "CurrentTips")["file_access"]["un_write_dirs"]
            if declare_report:
                tool(worker, "EditTextFile", path=report, content="Environment implementation review")
            old = "dut_ready = True"
            for addition in ("bundle_ready = True", "env_ready = True"):
                new = old + "\n" + addition
                result = tool(worker, "ReplaceStringInFile", path=api,
                              old_string=old, new_string=new)
                assert addition in (tmp_path / api).read_text(), result
                tool(worker, "SetCurrentStageJournal", journal="Implemented " + addition)
                if worker.record.lease.steps:
                    tips = tool(worker, "CurrentTips")
                    result = tool(worker, "CompleteSubStage", step_token=tips["step_token"])
                    assert result["validation"]["complete"], result
                old = new
        submit_ready(worker, summary="Completed the assigned API implementation.")

    agent.multi_agent.runner_factory = run
    try:
        agent.multi_agent.submit({"plan_id": "create", "scope": "stage", "tasks": [{
            "id": "author", "instruction": "Create the API.", "outputs": [api]}]})
        result = finish(agent.multi_agent, "create")
        assert result["plans"]["create"]["state"] == "completed", result
        (tmp_path / api).chmod(0o640)
        task = {"id": "author", "instruction": "Implement the Bundle and environment.", "inputs": [api]}
        if declare_report:
            task["outputs"] = [report]
        agent.multi_agent.submit({"plan_id": "environment", "scope": scope, "tasks": [task]})
        result = finish(agent.multi_agent, "environment")
        assert result["plans"]["environment"]["state"] == "completed", result
        assert "env_ready = True" in (tmp_path / api).read_text()
        assert stat.S_IMODE((tmp_path / api).stat().st_mode) == 0o640
        assert len(set(observed)) == 2
        assert agent.cfg.un_write_dirs == []
    finally:
        agent._startup_cleanup.close()


@pytest.mark.parametrize("scope", ["stage", "auto", "subtree", "task"])
def test_workflow_read_only_input_stays_protected_without_explicit_outputs(tmp_path, scope):
    """Stage input semantics never grant writes denied by the workflow policy."""
    source, output = "out/protected.txt", "out/result.md"
    (tmp_path / "out").mkdir()
    (tmp_path / source).write_text("protected evidence")
    stages = [stage("root", stage=[stage("child", output_files=[output])])] if scope == "subtree" else None
    agent = make_agent(tmp_path, stages=stages, config_overrides={"un_write_dirs": [source]})

    def run(worker):
        """Reject a protected input and allow only a legitimate output."""
        assert source in tool(worker, "CurrentTips")["file_access"]["un_write_dirs"]
        with pytest.raises(PermissionError, match="read-only input|no-write entry"):
            tool(worker, "EditTextFile", path=source, content="unauthorized change")
        assert (tmp_path / source).read_text() == "protected evidence"
        tool(worker, "EditTextFile", path=output, content="valid output")
        if not worker.record.split:
            tool(worker, "SetCurrentStageJournal", journal="Preserved the protected input.")
            if worker.record.lease.steps:
                result = tool(worker, "CompleteSubStage", step_token=tool(worker, "CurrentTips")["step_token"])
                assert result["validation"]["complete"], result
        submit_ready(worker, summary="Wrote the authorized output.")

    agent.multi_agent.runner_factory = run
    try:
        task = {"id": "author", "instruction": "Use the protected input.", "inputs": [source]}
        if scope == "task":
            task["outputs"] = [output]
        agent.multi_agent.submit({"plan_id": "protected-input", "scope": scope, "tasks": [task]})
        result = finish(agent.multi_agent, "protected-input")
        assert result["plans"]["protected-input"]["state"] == "completed", result
        assert (tmp_path / source).read_text() == "protected evidence"
    finally:
        agent._startup_cleanup.close()


@pytest.mark.parametrize("scope", ["stage", "task"])
def test_immutable_input_changes_still_fail_final_validation(tmp_path, scope):
    """Final validation detects external changes to workflow-protected or split-only inputs."""
    source, output = "out/source.txt", "out/result.md"
    (tmp_path / "out").mkdir()
    path = tmp_path / source
    path.write_text("original evidence")
    agent = make_agent(tmp_path, config_overrides={"un_write_dirs": [source] if scope == "stage" else []},
                       limits={"task_max_attempts": 1})

    def run(worker):
        """Simulate an external writer bypassing tools in this temporary test workspace."""
        tool(worker, "EditTextFile", path=output, content="derived evidence")
        path.chmod(0o600)
        path.write_text("changed by external writer")
        if not worker.record.split:
            tool(worker, "SetCurrentStageJournal", journal="Output ready for validation.")
        submit_ready(worker, summary="Output ready for validation.")

    agent.multi_agent.runner_factory = run
    try:
        agent.multi_agent.submit({"plan_id": "input-change", "scope": scope, "tasks": [{
            "id": "author", "instruction": "Preserve the source.", "inputs": [source], "outputs": [output]}]})
        result = finish(agent.multi_agent, "input-change")
        assert result["plans"]["input-change"]["state"] == "failed", result
        assert "Input artifact changed" in result["tasks"][0]["error"]
    finally:
        agent._startup_cleanup.close()
