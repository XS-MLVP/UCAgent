"""Protect agent runtime state while retaining read access and managed updates."""

from pathlib import Path

import pytest

from ucagent.tools.fileops import (
    CopyFile,
    CreateDirectory,
    DeleteFile,
    DeleteTextLines,
    EditTextFile,
    MoveFile,
    ReadTextFile,
    ReplaceStringInFile,
    is_file_writeable,
)
from ucagent.util.config import Config, save_runtime_config
from ucagent.verify_agent import VerifyAgent


@pytest.mark.parametrize("path", [".ucagent", ".ucagent/setting.yaml", ".UCAgent/skills/new.py"])
@pytest.mark.parametrize("policy", [{}, {"write_dirs": [".ucagent", ".ucagent/skills"]},
                                   {"un_write_dirs": [], "write_dirs": None}])
def test_runtime_tree_is_protected_independently_of_write_policy(path, policy):
    """No writable-directory override can grant an agent access to runtime state."""
    allowed, diagnostic = is_file_writeable(path, **policy)

    assert allowed is False
    assert ".ucagent/" in diagnostic
    assert "read-only" in diagnostic
    assert is_file_writeable(".ucagent-not-state/file.txt")[0] is True


@pytest.mark.parametrize("tool_class,arguments", [
    (EditTextFile, {"path": ".ucagent/state.txt", "content": "modified"}),
    (EditTextFile, {"path": ".ucagent/new.txt", "content": "created"}),
    (ReplaceStringInFile, {"path": ".ucagent/state.txt", "old_string": "state", "new_string": "changed"}),
    (DeleteTextLines, {"path": ".ucagent/state.txt", "line_blocks": [[1, 1]]}),
    (CopyFile, {"source_path": "input.txt", "dest_path": ".ucagent/state.txt", "overwrite": True}),
    (MoveFile, {"source_path": ".ucagent/state.txt", "dest_path": "moved.txt"}),
    (MoveFile, {"source_path": "input.txt", "dest_path": ".ucagent/state.txt", "overwrite": True}),
    (DeleteFile, {"path": ".ucagent/state.txt"}),
    (DeleteFile, {"path": ".ucagent", "is_dir": True, "recursive": True}),
    (CreateDirectory, {"path": ".ucagent/new-directory"}),
])
def test_file_mutations_cannot_change_runtime_state(tmp_path, tool_class, arguments):
    """Every public file mutation rejects runtime paths before touching any bytes."""
    state = tmp_path / ".ucagent" / "state.txt"
    state.parent.mkdir()
    state.write_text("state\n", encoding="utf-8")
    source = tmp_path / "input.txt"
    source.write_text("input\n", encoding="utf-8")
    tool = tool_class(str(tmp_path))

    result = tool.invoke(arguments)

    assert "read-only" in result
    assert state.read_text(encoding="utf-8") == "state\n"
    assert source.read_text(encoding="utf-8") == "input\n"
    assert sorted(path.name for path in state.parent.iterdir()) == ["state.txt"]
    assert not (tmp_path / "moved.txt").exists()


def test_runtime_files_remain_readable_and_framework_writable(tmp_path):
    """Agent read access remains available while trusted snapshot writes still work."""
    cfg = Config({
        "runtime_options": {"need_ref_model": False, "mock_components_enabled": False},
        "tools": {"RunTestCases": {"test_dir": "output/tests"}},
    })
    cfg._temp_cfg = {"DUT": "Demo", "OUT": "output"}
    save_runtime_config(str(tmp_path), cfg)
    snapshot = tmp_path / ".ucagent" / "runtime_config.json"
    original = snapshot.read_bytes()

    result = EditTextFile(str(tmp_path)).invoke({
        "path": ".ucagent/runtime_config.json", "content": "{}",
    })
    assert "read-only" in result
    assert snapshot.read_bytes() == original
    assert "need_ref_model" in ReadTextFile(str(tmp_path)).invoke({
        "path": ".ucagent/runtime_config.json",
    })
    CopyFile(str(tmp_path)).invoke({
        "source_path": ".ucagent/runtime_config.json", "dest_path": "snapshot-copy.json",
    })
    assert (tmp_path / "snapshot-copy.json").read_bytes() == original

    cfg.set_value("runtime_options.need_ref_model", True)
    save_runtime_config(str(tmp_path), cfg)
    assert snapshot.read_bytes() != original


@pytest.mark.parametrize("use_skill", [False, True])
@pytest.mark.parametrize("custom_tips", [None, "Custom mission. {skill_system}"])
def test_system_prompt_always_declares_runtime_tree_read_only(tmp_path, use_skill, custom_tips):
    """All mission prompts keep the runtime boundary with or without copied Skills."""
    agent = VerifyAgent.__new__(VerifyAgent)
    agent.workspace = str(tmp_path)
    agent.cfg = Config({
        "mission": {"prompt": {"system": "Configured mission. {skill_system}",
                               "skill_system": "Available Skills: {general_skill_list}"}},
        "skill": {"use_skill": use_skill, "general_skill_list": []},
    })

    prompt = agent.get_default_system_prompt(custom_tips)

    assert prompt.startswith("Custom mission." if custom_tips else "Configured mission.")
    assert "workspace `.ucagent/`" in prompt
    assert "read-only to you" in prompt
    assert "may read" in prompt
    assert "backend-native tools, shell commands, or scripts" in prompt
    assert "managed state updates are allowed" in prompt
    assert "restart UCAgent" in prompt
    assert "{skill_system}" not in prompt
    assert ("Available Skills:" in prompt) is use_skill
    assert not (Path(agent.workspace) / ".ucagent" / "skills").exists()

    agent.dut_name = "Demo"
    agent._default_system_prompt = prompt
    agent.generate_instruction_file("AGENTS.md")
    instruction = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert prompt in instruction
