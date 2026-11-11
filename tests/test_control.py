"""Behavioral checks for controls using domain objects without agent startup."""

from copy import deepcopy
from functools import partial
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
from unittest.mock import Mock

from langchain_core.messages import AIMessage, HumanMessage
import pytest

from ucagent.core.checkers.base import Checker as BaseChecker
from ucagent.runtime.control.controller import Controller, ControlError, public_data
from ucagent.core.stage.vmanager import StageManager
from ucagent.core.stage.vstage import VerifyStage
from ucagent.core.tools.fileops import CopyFile
from ucagent.util.config import Config
from ucagent.util.diff_ops import get_latest_commit_hash


class Checker(BaseChecker):
    """Use real stage-description hooks with observable editable attributes."""

    def __init__(self):
        """Provide all supported scalar types and one unsupported type."""
        super().__init__()
        self.attrs = {"limit": 3, "ratio": 0.5, "enabled": False, "title": "original", "items": []}

    def get_attr(self):
        """Return the checker's current editable attributes."""
        return self.attrs

    def set_attr(self, values):
        """Apply edits through the public checker API."""
        self.attrs.update(values)


class Agent:
    """An assembled-domain test double with no model, terminal or service startup."""

    def __init__(self, workspace, cfg, manager, tool):
        """Expose only the agent interfaces used by ordinary controls."""
        self.workspace = str(workspace)
        self.output_dir = str(workspace / "out")
        self.cfg = cfg
        self.stage_manager = manager
        self.test_tools = [tool]
        self.messages = [HumanMessage(content="first"), AIMessage(content="second"), HumanMessage(content="last")]
        self.backend = SimpleNamespace(reset_chat=Mock(side_effect=self.reset_messages))
        self._system_message = "pending system"
        self._continue_msg = "pending continue"
        self.cwd_read_only_files = []
        self.message_manage_node = SimpleNamespace(force_summary=self.summarize)
        self.message_cfg = {"max_keep_msgs": 20}
        self.template_calls = []
        self.get_current_tips = Mock(side_effect=AssertionError("Agent tips consume pending messages"))

    def reset_messages(self, force=False):
        """Make backend reset observable in the message store."""
        self.messages.clear()

    def status_info(self):
        """Return a stable count without calling a model."""
        return {"MessageCount": len(self.messages), "IsBreak": True}

    def get_tool_by_name(self, name):
        """Resolve the actual file tool used in these tests."""
        return next((tool for tool in self.test_tools if tool.name == name), None)

    def list_tool_call_time_out(self):
        """Read actual tool timeout fields."""
        return {tool.name: tool.call_time_out for tool in self.test_tools}

    def set_tool_call_time_out(self, seconds):
        """Set all actual tool timeout fields."""
        for tool in self.test_tools:
            tool.set_call_time_out(seconds)

    def set_one_tool_call_time_out(self, name, seconds):
        """Set a selected actual tool timeout."""
        self.get_tool_by_name(name).set_call_time_out(seconds)

    def messages_get_raw(self):
        """Return actual message objects for structured projection."""
        return self.messages

    def message_info(self):
        """Count the current stored messages."""
        return {"count": len(self.messages)}

    def get_messages_cfg(self, keys):
        """Read the selected message configuration fields."""
        return {key: self.message_cfg[key] for key in keys if key in self.message_cfg}

    def set_messages_cfg(self, values):
        """Reject unsupported keys and invalid counts as the agent does."""
        accepted = {key: value for key, value in values.items()
                    if key in self.message_cfg and type(value) is int and value >= 0}
        self.message_cfg.update(accepted)
        return accepted

    def summarize(self, messages):
        """Replace history with a concrete summary without a real model."""
        messages[:] = [AIMessage(content="summary")]

    def message_summary(self):
        """Delegate summarization to the configured message manager."""
        self.message_manage_node.force_summary(self.messages)

    def get_system_message(self):
        """Read the pending system message."""
        return self._system_message

    def set_system_message(self, message):
        """Change only the pending system message."""
        self._system_message = message

    def protect_files_on(self, paths):
        """Record protection and change actual temporary-file mode bits."""
        for path in paths:
            full = Path(self.workspace) / path
            full.chmod(full.stat().st_mode & ~0o222)
            if str(full) not in self.cwd_read_only_files:
                self.cwd_read_only_files.append(str(full))

    def protect_files_off(self, paths):
        """Restore mode bits and remove selected entries."""
        for path in paths:
            full = Path(self.workspace) / path
            full.chmod(full.stat().st_mode | stat.S_IWUSR)
            self.cwd_read_only_files.remove(str(full))

    def render_template(self, tmp_overwrite=False):
        """Write a deterministic template to show the delegated side effect."""
        self.template_calls.append(tmp_overwrite)
        target = Path(self.output_dir) / "template.txt"
        if tmp_overwrite or not target.exists():
            target.write_text("template", encoding="utf-8")


@pytest.fixture
def control(tmp_path):
    """Assemble real stages and a file tool in an isolated temporary workspace."""
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "source.txt").write_text("source content", encoding="utf-8")
    cfg = Config({"mission": {"name": "test mission", "prompt": {"tips": {
        "always": ["always one", "always two"], "random": ["random one"]}}},
        "skill": {"use_skill": False}, "hist_ignore_pattern": [],
        "write_dirs": ["out"], "un_write_dirs": [],
        "conversation_summary": {"max_keep_msgs": 20},
        "vibe_coding": {"short_prompts": {"inspect": "inspect the result"}}})
    cfg._temp_cfg = {"OUT": "out"}
    stages = [VerifyStage(cfg, str(tmp_path), f"stage-{i}", "description", ["task"], [], [], [], ["out/*.txt"])
              for i in range(2)]
    manager = SimpleNamespace(stages=stages, stage_index=0, mission=cfg.mission,
                              llm_fail_suggestion=None, llm_pass_suggestion=None, force_todo=False)
    manager.get_current_stage = lambda: stages[manager.stage_index] if manager.stage_index < len(stages) else None
    manager._previous_stage_journal = partial(StageManager._previous_stage_journal, manager)
    manager.attach_todo_summary = partial(StageManager.attach_todo_summary, manager)
    manager.get_current_tips = partial(StageManager.get_current_tips, manager)
    manager.detail = partial(StageManager.detail, manager)
    manager.status = Mock(return_value={"all_completed": False, "stage_list": [
        {"index": i, "title": stage.title(), "is_completed": False,
         "needs_human_check": False, "need_fail_llm_suggestion": False,
         "need_pass_llm_suggestion": False} for i, stage in enumerate(stages)]})
    for stage in stages:
        stage.vmanager = manager
    tool = CopyFile(workspace=str(tmp_path), write_dirs=cfg.write_dirs, un_write_dirs=cfg.un_write_dirs)
    return Controller(Agent(tmp_path, cfg, manager, tool))


def test_repeated_queries_preserve_pending_messages_and_stage_state(control):
    """Queries must neither consume pending prompts nor persist stage changes."""
    agent = control.agent
    before_tips = deepcopy(agent.cfg.mission.prompt.tips.as_dict())
    before_meta = [deepcopy(stage.meta_data) for stage in agent.stage_manager.stages]
    for _ in range(3):
        assert control.status()["MessageCount"] == 3
        assert control.task_status()["task_index"] == 0
        assert control.task_detail(0)["is_current"] is True
        assert len(control.task_detail()["stage_list"]) == 2
        assert "always one" in control.current_tips()["tips"]
        assert control.get_sys_tips() == {"message": "pending system"}
        info = control.mission_info()
        assert info["stages"][0]["is_current"] is True
        assert info["stages"][1]["can_edit_flags"] is True
        assert "\x1b" not in json.dumps(info)
    assert agent.cfg.mission.prompt.tips.as_dict() == before_tips
    assert [stage.meta_data for stage in agent.stage_manager.stages] == before_meta
    assert agent.stage_manager.stage_index == 0
    assert agent._continue_msg == "pending continue"
    assert agent._system_message == "pending system"
    agent.get_current_tips.assert_not_called()
    assert not (control.workspace / ".ucagent/history").exists()


def test_query_data_is_detached_and_does_not_export_objects(control):
    """Changing a result cannot change config, checker objects or domain metadata."""
    control.agent.stage_manager.stages[0].checker = [Checker()]
    data = control.config_detail("mission.prompt.tips")
    data["always"].clear()
    assert control.agent.cfg.mission.prompt.tips.always == ["always one", "always two"]
    result = control.list_checkers()
    assert result == [{"index": 0, "class": "Checker", "stage": "stage-0-description"}]
    task = control.task_detail(0)["detail"]["task"]
    assert task["title"] == "stage-0-description"
    assert task["description"] == ["task"]
    json.dumps(result)
    with pytest.raises(ControlError, match="Cannot expose"):
        public_data(control.agent)


@pytest.mark.parametrize("index", [-1, 2, True, "0"])
def test_invalid_stage_indexes_are_business_errors(control, index):
    """Invalid indexes must never select Python negative-index or bool slots."""
    with pytest.raises(ControlError) as caught:
        control.task_detail(index)
    assert caught.value.as_dict()["code"] == "invalid_stage"


def test_completed_mission_has_no_current_stage(control):
    """A completed mission still permits indexed history reads."""
    control.agent.stage_manager.stage_index = 2
    with pytest.raises(ControlError, match="No current stage"):
        control.stage_outcome()
    assert control.stage_outcome(0)["commit_hash"] is None


def test_history_reads_do_not_sync_and_commit_returns_real_git_metadata(control):
    """Use a real stage-owned Git history to distinguish reads, diffs and commits."""
    stage = control.agent.stage_manager.stages[0]
    stage.hist_init()
    initial_hash = get_latest_commit_hash(stage.hist_sav_dir)
    source = control.workspace / "out/source.txt"
    source.write_text("new content", encoding="utf-8")
    saved = Path(stage.hist_sav_dir) / "out/source.txt"
    assert control.stage_file_content("out/source.txt")["content"] == "source content"
    assert control.stage_cfile_content("out/source.txt")["content"] == "new content"
    assert saved.read_text() == "source content"
    assert get_latest_commit_hash(stage.hist_sav_dir) == initial_hash
    assert "source.txt" in control.stage_diff("out/source.txt", True)
    assert saved.read_text() == "new content"
    with pytest.raises(ControlError, match="current stage"):
        control.stage_cfile_content("out/source.txt", index=1, sync_history=True)
    result = control.stage_commit("operator review")
    assert result["hash"] != initial_hash
    assert result["hash"] == get_latest_commit_hash(stage.hist_sav_dir)
    assert "operator review" in result["message"]
    assert control.stage_file_content("out/source.txt")["content"] == "new content"
    result["message"] = "client mutation"
    assert stage.meta_data["commit"]["message"] != "client mutation"
    source.unlink()
    assert control.stage_file_content("out/source.txt")["content"] == "new content"
    with pytest.raises(ControlError, match="empty"):
        control.stage_commit(" ")


def test_policy_edits_reach_existing_tool_and_enforce_write_restrictions(control):
    """A live file tool must observe policy updates and refuse forbidden writes."""
    tool = control.agent.test_tools[0]
    cfg = control.agent.cfg
    assert tool.write_able_dirs == cfg.write_dirs
    assert tool.write_able_dirs is not cfg.write_dirs
    assert tool.un_write_able_dirs == cfg.un_write_dirs
    control.update_path_policy("out", writable=False)
    result = control.tool_invoke("CopyFile", {"source_path": "out/source.txt", "dest_path": "out/copied.txt"})
    assert isinstance(result, str)
    assert not (control.workspace / "out/copied.txt").exists()
    control.update_path_policy("out", writable=False, remove=True)
    control.tool_invoke("CopyFile", {"source_path": "out/source.txt", "dest_path": "out/copied.txt"})
    assert (control.workspace / "out/copied.txt").read_text() == "source content"
    control.update_path_policy("out", writable=True, remove=True)
    control.tool_invoke("CopyFile", {"source_path": "out/source.txt", "dest_path": "out/blocked.txt"})
    assert not (control.workspace / "out/blocked.txt").exists()
    assert control.update_path_policy("/out/*.txt", writable=True)["write_dirs"] == ["out/*.txt"]
    with pytest.raises(ControlError) as duplicate:
        control.update_path_policy("out/*.txt", writable=True)
    assert duplicate.value.code == "already_exists"
    with pytest.raises(ControlError) as missing:
        control.update_path_policy("missing", writable=False, remove=True)
    assert missing.value.code == "not_found"


@pytest.mark.parametrize("path", ["", "../outside", "../../*.txt", "missing"])
def test_invalid_policy_paths_do_not_mutate_lists(control, path):
    """Validation errors leave live tool policy untouched."""
    before = control.list_rw_paths()
    with pytest.raises(ControlError):
        control.update_path_policy(path, writable=True)
    assert control.list_rw_paths() == before


def test_symlink_escape_is_rejected_for_files_and_globs(control, tmp_path):
    """Resolve existing symlink prefixes before accepting a workspace path."""
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    for path in ("escape/secret.txt", "escape/*.txt"):
        with pytest.raises(ControlError, match="outside"):
            control.update_path_policy(path, writable=True)
    with pytest.raises(ControlError, match="outside"):
        control.stage_file_content("escape/secret.txt")


def test_tool_schema_errors_timeouts_and_metadata(control):
    """Schema failures cannot invoke tools; successful timeout changes are observable."""
    tool = control.agent.test_tools[0]
    count = tool.call_count
    with pytest.raises(ControlError, match="required"):
        control.tool_invoke("CopyFile", {})
    assert tool.call_count == count
    with pytest.raises(ControlError, match="JSON object"):
        control.tool_invoke("CopyFile", [])
    with pytest.raises(ControlError) as missing:
        control.tool_list("missing")
    assert missing.value.code == "unknown_tool"
    assert control.tool_timeout_set("CopyFile", 17)["CopyFile"] == 17
    assert control.tool_timeout_set("*", 19)["CopyFile"] == 19
    for invalid in (0, -1, True, 1.5):
        with pytest.raises(ControlError):
            control.tool_timeout_set("CopyFile", invalid)
    assert control.tool_timeout_list()["CopyFile"] == 19
    metadata = control.tool_list("CopyFile")[0]
    assert metadata["name"] == "CopyFile" and "source_path" in metadata["args"]
    json.dumps(metadata)


@pytest.mark.parametrize("key,value", [("limit", 7), ("ratio", 0.7), ("enabled", True), ("title", "new title")])
def test_checker_edits_use_supported_attribute_api(control, key, value):
    """Each supported scalar type reaches the checker and returns updated data."""
    checker = Checker()
    control.agent.stage_manager.stages[0].checker = [checker]
    assert control.checker_attr(0, key, value)[key] == value
    assert checker.attrs[key] == value


@pytest.mark.parametrize("key,value", [("limit", True), ("limit", "2+3"), ("items", []), ("unknown", 1)])
def test_checker_invalid_edits_preserve_state(control, key, value):
    """Unsupported types and expression strings cannot become checker edits."""
    checker = Checker()
    control.agent.stage_manager.stages[0].checker = [checker]
    before = deepcopy(checker.attrs)
    with pytest.raises(ControlError):
        control.checker_attr(0, key, value)
    assert checker.attrs == before
    with pytest.raises(ControlError):
        control.checker_attr(-1)


def test_message_reads_and_actions_have_real_store_effects(control):
    """Read structured messages and validate reset, settings and summary results."""
    assert [row["content"] for row in control.messages_print(-2, 2)] == ["second", "last"]
    assert control.messages_print(0, 0) == []
    with pytest.raises(ControlError):
        control.messages_print(0, -1)
    assert control.messages_config() == {"max_keep_msgs": 20}
    assert control.messages_config("max_keep_msgs", 5) == {"max_keep_msgs": 5}
    with pytest.raises(ControlError):
        control.messages_config("max_keep_msgs", -1)
    assert control.messages_config()["max_keep_msgs"] == 5
    assert control.messages_summary() == {"count": 1}
    assert control.messages_print()[0]["content"] == "summary"
    assert control.messages_reset(force=True) == {"count": 0}
    control.agent.backend.reset_chat.assert_called_once_with(force=True)
    assert control.messages_print() == []
    control.agent.message_manage_node = None
    with pytest.raises(ControlError, match="unavailable"):
        control.messages_summary()
    assert control.set_sys_tips("new message") == {"message": "new message"}
    assert control.set_sys_tips("") == {"message": ""}
    assert control.agent._continue_msg == "pending continue"


@pytest.mark.parametrize("frozen", [True, False])
def test_prompt_edits_preserve_freeze_state_and_literal_text(control, frozen):
    """Prompts remain literal strings and edits preserve config mutability."""
    cfg = control.agent.cfg
    if frozen:
        cfg.freeze()
    text = '{"not": "a config override"}'
    assert control.short_prompt_set("new", text)["new"] == text
    assert cfg.vibe_coding.short_prompts.new == text
    assert cfg._freeze is frozen and cfg.vibe_coding._freeze is frozen
    assert "new" not in control.short_prompt_del("new")
    assert cfg._freeze is frozen
    with pytest.raises(ControlError):
        control.short_prompt_del("missing")
    with pytest.raises(ControlError):
        control.short_prompt_set("name", " ")


def test_config_missing_prompt_section_and_failed_edit_refreezes(control):
    """Missing optional prompts are supported; failed writes still refreeze config."""
    cfg = control.agent.cfg
    del cfg.vibe_coding
    assert control.short_prompt_list() == {}
    cfg.freeze()
    assert control.short_prompt_set("new", "hello") == {"new": "hello"}
    cfg.un_freeze()
    cfg.vibe_coding = "invalid config section"
    cfg.freeze()
    with pytest.raises(ControlError, match="configuration mapping"):
        control._save_prompts({"new": "hello"})
    assert cfg._freeze is True


def test_file_protection_validates_all_paths_before_delegation(control):
    """Invalid mixed input cannot partially protect files; restore-all clears state."""
    path = control.workspace / "out/source.txt"
    before = path.stat().st_mode
    with pytest.raises(ControlError):
        control.protect_files(["out/source.txt", "../outside"], enabled=True)
    assert path.stat().st_mode == before
    assert control.protect_files(["out/source.txt"], enabled=True)["protected_files"] == [str(path)]
    assert path.stat().st_mode & 0o222 == 0
    assert control.protect_files([], enabled=False) == {"protected_files": []}
    assert path.stat().st_mode & stat.S_IWUSR


def test_template_recent_files_config_and_session_queries(control):
    """Verify remaining ordinary actions through persisted files and actual data."""
    control.render_template()
    path = control.workspace / "out/template.txt"
    assert path.read_text() == "template"
    path.write_text("keep this")
    control.render_template()
    assert path.read_text() == "keep this"
    control.render_template(force=True)
    assert path.read_text() == "template"
    os.utime(path, (2_000_000_000, 2_000_000_000))
    assert control.changed_files(1)[0]["path"] == "template.txt"
    assert control.changed_files(0) == []
    with pytest.raises(ControlError):
        control.changed_files(-1)
    assert control.config_detail("mission.name") == "test mission"
    with pytest.raises(ControlError):
        control.config_detail("mission.missing.key")
    with pytest.raises(ControlError):
        control.show_web_session()
    control.agent.web_console_session_info = {"session_id": "test"}
    assert control.show_web_session() == {"session_id": "test"}
    assert control.logo_and_version()["name"] == "UCAgent"
