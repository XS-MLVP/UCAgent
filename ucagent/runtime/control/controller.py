"""Structured verification controls shared by command and HTTP frontends.

Domain objects retain validation, history, tool invocation and file-policy
ownership. This module never constructs an agent or starts an input loop.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from ucagent.core.tools.fileops import BaseReadWrite
from ucagent.util.file_policy import write_entry_has_wildcards
from ucagent.util.config import Config
from ucagent.util.functions import list_files_by_mtime
from ucagent.version import __version__
from ucagent.runtime.workspace.access import WorkspaceAccess
from ucagent.runtime.workspace.queries import WorkspaceQueries


class ControlError(Exception):
    """A business failure with a stable code and transport-independent details."""

    def __init__(self, code: str, message: str, **details: Any):
        """Keep diagnostic fields separate from the human-readable message."""
        super().__init__(message)
        self.code = code
        self.details = details

    def as_dict(self) -> dict:
        """Return a serializable error for any frontend."""
        return {"code": self.code, "message": str(self), "details": public_data(self.details)}


def public_data(value: Any) -> Any:
    """Detach JSON data from mutable domain state without exposing live objects."""
    if isinstance(value, Config):
        value = value.as_dict()
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {str(key): public_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [public_data(item) for item in value]
    raise ControlError("unsupported_result", f"Cannot expose {type(value).__name__} as control data.")


class Controller:
    """Expose ordinary business operations against an already assembled agent."""

    def __init__(self, agent):
        """Reference domain owners without starting services, models or terminals."""
        self.agent = agent
        self.workspace = Path(agent.workspace).resolve()
        self.workspace_access = WorkspaceAccess(str(self.workspace))
        self.workspace_queries = WorkspaceQueries(self.workspace_access)
        self.operations = None

    def _operation_owner(self):
        """Require the injected executor before accepting long-operation requests."""
        if self.operations is None:
            raise ControlError("unavailable", "No operation executor is attached.")
        return self.operations

    def start_operation(self, command, arguments, session):
        """Submit a structured command to the same owner used by text frontends."""
        from ucagent.runtime.control.commands import COMMAND_ORIGIN

        origin = COMMAND_ORIGIN.get()
        token = COMMAND_ORIGIN.set(origin if origin is not None and origin[0] == session.id
                                   else (session.id, command, session.foreground))
        try:
            return self._operation_owner().execute(command, arguments, session)
        finally:
            COMMAND_ORIGIN.reset(token)

    def operation_status(self, operation_id):
        """Read a detached long-operation snapshot without waiting for its worker."""
        return self._operation_owner().get(operation_id)

    def operation_list(self):
        """List this instance's operations without exposing worker objects."""
        return self._operation_owner().list()

    def cancel_operation(self, operation_id):
        """Cancel one owned operation without affecting another session's work."""
        return self._operation_owner().cancel(operation_id)

    def _stage_coordinator(self):
        """Require the shared stage owner for revision-checked human controls."""
        stages = self._operation_owner().stages
        if stages is None:
            raise ControlError("unavailable", "No stage coordinator is attached.")
        return stages

    def stage_state(self):
        """Read stage targets, review state and the independent control revision."""
        return self._stage_coordinator().snapshot()

    def review_stage(self, index, expected_revision, approved, message="", *, resume=False, session=None):
        """Persist human approval for the observed current stage before optional resume."""
        if type(index) is not int or type(expected_revision) is not int or expected_revision < 0:
            raise ControlError("invalid_argument", "Stage index and control revision must be integers.")
        if type(approved) is not bool or not isinstance(message, str) or type(resume) is not bool:
            raise ControlError("invalid_argument", "Review requires a boolean decision and text message.")
        if resume and (not approved or session is None):
            raise ControlError("invalid_argument", "Resuming requires approval and a command session.")
        stages = self._stage_coordinator()
        after = (lambda: self.start_operation("continue", {}, session)) if resume else None
        with stages.mutation("human", expected_revision=expected_revision, target_index=index, after=after) as ticket:
            stage = self._stage(index)
            if stage.is_completed() or stage.is_skipped():
                raise ControlError("invalid_stage", "Completed or skipped stages cannot be reviewed.")
            if not stage.is_hmcheck_needed():
                raise ControlError("review_not_required", "This stage does not require human review.")
            if approved:
                stage.do_hmcheck_pass(message)
            else:
                stage.do_hmcheck_fail(message)
            self.agent._need_human = not approved
        result = {"stage_index": index, "approved": approved, "message": message,
                  "control_revision": ticket["control_revision"]}
        if "operation" in ticket:
            result["operation"] = ticket["operation"]
        return result

    def update_stage_flags(self, indices, expected_revision, **changes):
        """Validate all requested targets before changing any review, skip or LLM flags."""
        setters = {"hmcheck_needed": "do_set_hmcheck_needed", "skip": "set_skip",
                   "llm_fail_suggestion": "set_llm_fail_suggestion",
                   "llm_pass_suggestion": "set_llm_pass_suggestion"}
        if type(expected_revision) is not int or expected_revision < 0:
            raise ControlError("invalid_argument", "A non-negative control revision is required.")
        if (not isinstance(indices, (list, tuple)) or not indices
                or any(type(index) is not int for index in indices) or len(set(indices)) != len(indices)):
            raise ControlError("invalid_argument", "Provide distinct stage indices.")
        if not changes or changes.keys() - setters.keys():
            raise ControlError("invalid_argument", "Provide supported stage flags.")
        for key, value in changes.items():
            if type(value) is not bool and not (key.startswith("llm_") and value is None):
                raise ControlError("invalid_argument", f"Invalid flag value for {key}.")
        stages = self._stage_coordinator()
        with stages.mutation("human", expected_revision=expected_revision) as ticket:
            targets = [self._stage(index) for index in indices]
            for index, stage in zip(indices, targets):
                if stage.is_completed() or index < stages.manager.stage_index:
                    raise ControlError("invalid_stage", "Completed stages cannot be modified.", index=index)
                if "skip" in changes and index == stages.manager.stage_index:
                    raise ControlError("invalid_stage", "The current stage cannot be skipped or unskipped.", index=index)
            for stage in targets:
                for key, value in changes.items():
                    getattr(stage, setters[key])(value)
            updated = [row for row in stages.snapshot()["stages"] if row["index"] in indices]
        return {"updated": updated, "control_revision": ticket["control_revision"]}

    def go_to_stage(self, index, expected_revision):
        """Request a human stage jump through the domain's reached-stage rules."""
        if type(index) is not int or type(expected_revision) is not int or expected_revision < 0:
            raise ControlError("invalid_argument", "Stage index and control revision must be integers.")
        stages = self._stage_coordinator()
        with stages.mutation("human", expected_revision=expected_revision) as ticket:
            result = public_data(stages.manager.go_to_stage(index))
        return {**result, "control_revision": ticket["control_revision"]}

    def _stage(self, index=None):
        """Resolve a stage and reject negative indexes and completed-mission gaps."""
        manager = self.agent.stage_manager
        if index is None:
            stage = manager.get_current_stage()
            if stage is None:
                raise ControlError("no_current_stage", "No current stage available.")
            return stage
        if type(index) is not int or not 0 <= index < len(manager.stages):
            raise ControlError("invalid_stage", "Stage index is out of range.", index=index)
        return manager.stages[index]

    def _tool(self, name):
        """Resolve a tool by its public name without bypassing its invocation API."""
        tool = self.agent.get_tool_by_name(name)
        if tool is None:
            raise ControlError("unknown_tool", f"Tool '{name}' not found.")
        return tool

    def workspace_path(self, path: str, *, pattern=False, must_exist=True) -> str:
        """Validate a workspace-relative path, including symlink and glob prefixes."""
        if not isinstance(path, str) or not path.strip():
            raise ControlError("invalid_path", "Path cannot be empty.")
        # File policy uses '/name' as a workspace-root-relative path.
        relative = path.strip().lstrip("/")
        resolved = (self.workspace / relative).resolve()
        if not resolved.is_relative_to(self.workspace):
            raise ControlError("invalid_path", "Path is outside the workspace.", path=path)
        wildcard = write_entry_has_wildcards(relative)
        if wildcard and not pattern:
            raise ControlError("invalid_path", "A concrete file path is required.", path=path)
        if must_exist and not wildcard and not resolved.exists():
            raise ControlError("invalid_path", "Path does not exist.", path=path)
        return resolved.relative_to(self.workspace).as_posix()

    def status(self):
        """Read agent statistics without consuming prompts or executing the model."""
        return public_data(self.agent.status_info())

    def tool_list(self, name=None):
        """Return tool metadata, including schemas, without exposing tool objects."""
        tools = [self._tool(name)] if name else self.agent.test_tools
        return [{"name": tool.name, "description": tool.description,
                 "call_count": tool.call_count, "args": public_data(tool.args),
                 "is_hot": tool.is_hot()} for tool in tools]

    def tool_timeout_list(self):
        """Read the domain owner's tool timeout settings."""
        return public_data(self.agent.list_tool_call_time_out())

    def tool_timeout_set(self, name, seconds):
        """Set positive integral timeouts through the agent's supported methods."""
        if type(seconds) is not int or seconds <= 0:
            raise ControlError("invalid_argument", "Tool timeout must be a positive integer.")
        if name == "*":
            self.agent.set_tool_call_time_out(seconds)
        else:
            self._tool(name)
            self.agent.set_one_tool_call_time_out(name, seconds)
        return self.tool_timeout_list()

    def tool_invoke(self, name, arguments=None):
        """Validate a JSON object against the tool schema, then use normal invoke."""
        tool = self._tool(name)
        arguments = {} if arguments is None else arguments
        if not isinstance(arguments, dict):
            raise ControlError("invalid_argument", "Tool arguments must be a JSON object.")
        try:
            validated = tool.tool_call_schema(**arguments)
        except ValueError as exc:
            raise ControlError("invalid_argument", str(exc), tool=name) from exc
        return public_data(tool.invoke(validated.model_dump()))

    def task_status(self):
        """Read the mission and current stage status as detached data."""
        manager = self.agent.stage_manager
        return {"mission_name": self.agent.cfg.get_value("mission.name", "None"),
                "task_index": manager.stage_index, "task_list": public_data(manager.status())}

    def task_detail(self, index=None):
        """Read mission details or a selected stage without modifying its state."""
        if index is None:
            return public_data(self.agent.stage_manager.detail())
        stage = self._stage(index)
        detail = public_data(stage.public_detail())
        extra = {"journal": stage.meta_get_journal(), "StageJournal": stage.meta_get_journal(),
                 "last_do_check_info": stage.get_last_do_check_info(),
                 "llm_suggestions": {"pass": stage.meta_get_llm_pass_suggestion(),
                                     "fail": stage.meta_get_llm_fail_suggestion()}}
        detail.update(public_data(extra))
        return {"is_current": stage is self.agent.stage_manager.get_current_stage(),
                "detail": detail, **public_data(extra)}

    def current_tips(self):
        """Read stage tips; never call the agent's prompt-consuming tips method."""
        return {"tips": self.agent.stage_manager.get_current_tips()}

    def mission_info(self, format=None):
        """Describe stage flags and outcomes without terminal color or layout."""
        manager = self.agent.stage_manager
        result = self.task_status()
        stages = result["task_list"]["stage_list"]
        current = manager.get_current_stage()
        for row, stage in zip(stages, manager.stages):
            index = row["index"]
            row["is_current"] = stage is current
            row["can_edit_flags"] = index > manager.stage_index and not stage.is_completed()
            row["outcome"] = public_data(stage.get_stage_outcome()) if index <= manager.stage_index else None
        return {"mission_name": result["mission_name"], "current_index": manager.stage_index,
                "all_completed": result["task_list"]["all_completed"],
                "is_waiting_for_review": result["task_list"].get("is_waiting_for_review", False),
                "enable_llm_fail_suggestion": manager.llm_fail_suggestion is not None,
                "enable_llm_pass_suggestion": manager.llm_pass_suggestion is not None,
                "stages": stages}

    def stage_outcome(self, index=None):
        """Read domain-owned history/output metadata for a selected stage."""
        return public_data(self._stage(index).get_stage_outcome())

    def stage_file_content(self, path, index=None):
        """Read a historical file, allowing a file deleted from the live workspace."""
        path = self.workspace_path(path, must_exist=False)
        return public_data(self._stage(index).get_stage_file_content(path))

    def stage_cfile_content(self, path, index=None, sync_history=False):
        """Read current content; explicit history sync is limited to the active stage."""
        stage = self._stage(index)
        if sync_history and stage is not self.agent.stage_manager.get_current_stage():
            raise ControlError("invalid_stage", "Manual history sync requires the current stage.")
        path = self.workspace_path(path, must_exist=False)
        return public_data(stage.get_current_file_content_with_diff(path, sync_history=sync_history))

    def stage_diff(self, path=".", show_diff=False):
        """Ask the active stage to synchronize history and report its diff."""
        path = self.workspace_path(path, must_exist=False)
        return public_data(self._stage().hist_diff(target_file=path, show_diff=show_diff))

    def stage_commit(self, message):
        """Commit via the stage history owner and return the actual commit metadata."""
        if not message.strip():
            raise ControlError("invalid_argument", "Commit message cannot be empty.")
        stage = self._stage()
        stage.hist_commit(message)
        return public_data(stage.meta_data["commit"])

    def changed_files(self, count=10):
        """Return the requested number of recent output files, without display markup."""
        if type(count) is not int or count < 0:
            raise ControlError("invalid_argument", "Count must be a non-negative integer.")
        return [{"age_seconds": age, "mtime": mtime, "path": path}
                for age, mtime, path in list_files_by_mtime(self.agent.output_dir, count)]

    def list_checkers(self):
        """Return checker identities and stage ownership, never checker instances."""
        return [{"index": index, "class": checker.__class__.__name__, "stage": stage.title()}
                for index, (stage, checker) in enumerate(
                    (stage, checker) for stage in self.agent.stage_manager.stages for checker in stage.checker)]

    def checker_attr(self, index, key=None, value=None):
        """Read or edit supported scalar attributes through get_attr/set_attr only."""
        checkers = [checker for stage in self.agent.stage_manager.stages for checker in stage.checker]
        if type(index) is not int or not 0 <= index < len(checkers):
            raise ControlError("invalid_checker", "Checker index is out of range.")
        checker = checkers[index]
        attrs = checker.get_attr()
        if key is not None:
            if key not in attrs:
                raise ControlError("invalid_argument", f"Unknown checker attribute '{key}'.")
            expected = type(attrs[key])
            if expected not in (str, bool, int, float) or type(value) is not expected:
                raise ControlError("invalid_argument", f"Attribute '{key}' requires {expected.__name__}.")
            guard = getattr(self.agent.stage_manager, "control_guard", None)
            with guard("human") if guard is not None else nullcontext():
                checker.set_attr({key: value})
        return public_data(checker.get_attr())

    def messages_info(self):
        """Read message counts and backend statistics."""
        return public_data(self.agent.message_info())

    def messages_print(self, start=-10, size=10):
        """Return raw message data with the existing relative-index slice semantics."""
        if type(start) is not int or type(size) is not int or size < 0:
            raise ControlError("invalid_argument", "Message start must be integral and size non-negative.")
        messages = self.agent.messages_get_raw()
        if not messages:
            return []
        start %= len(messages)
        return [public_data(message.model_dump(mode="json")) for message in messages[start:start + size]]

    def messages_reset(self, force=False):
        """Delegate history reset to the backend and return its resulting statistics."""
        self.agent.backend.reset_chat(force=force)
        return self.messages_info()

    def messages_config(self, key=None, value=None):
        """Read or update message management using the agent's validation contract."""
        keys = self.agent.cfg.get_value("conversation_summary").as_dict().keys()
        if key is None:
            return public_data(self.agent.get_messages_cfg(keys))
        updated = self.agent.set_messages_cfg({key: value})
        if key not in updated:
            raise ControlError("invalid_argument", f"Message configuration '{key}' was rejected.")
        return public_data(updated)

    def messages_summary(self):
        """Request supported message summarization and return actual resulting counts."""
        node = self.agent.message_manage_node
        if node is None or not callable(getattr(node, "force_summary", None)):
            raise ControlError("unavailable", "Message summarization is unavailable.")
        self.agent.message_summary()
        return self.messages_info()

    def get_sys_tips(self):
        """Read the pending system message without consuming it."""
        return {"message": self.agent.get_system_message()}

    def set_sys_tips(self, message):
        """Replace the pending system message, including explicit clearing."""
        self.agent.set_system_message(message)
        return self.get_sys_tips()

    def short_prompt_list(self):
        """Read configured named prompts as independent data."""
        return public_data(self.agent.cfg.as_dict().get("vibe_coding", {}).get("short_prompts", {}))

    def short_prompt_set(self, name, message):
        """Set a named prompt while restoring the original configuration freeze state."""
        if not name.strip() or not message.strip():
            raise ControlError("invalid_argument", "Prompt name and message cannot be empty.")
        prompts = self.short_prompt_list()
        prompts[name] = message
        self._save_prompts(prompts)
        return prompts

    def short_prompt_del(self, name):
        """Remove a known prompt and preserve the configuration freeze state."""
        prompts = self.short_prompt_list()
        if name not in prompts:
            raise ControlError("not_found", f"Short prompt '{name}' not found.")
        del prompts[name]
        self._save_prompts(prompts)
        return prompts

    def _save_prompts(self, prompts):
        """Update the Config mapping without decoding user prompt text as an override."""
        cfg = self.agent.cfg
        was_frozen = cfg._freeze
        cfg.un_freeze()
        try:
            if not cfg.has_attr("vibe_coding"):
                cfg.vibe_coding = Config()
            if not isinstance(cfg.vibe_coding, Config):
                raise ControlError("invalid_config", "vibe_coding must be a configuration mapping.")
            cfg.vibe_coding.short_prompts = Config(prompts)
        finally:
            if was_frozen:
                cfg.freeze()

    def list_rw_paths(self):
        """Read the configured file policy lists."""
        return {"write_dirs": public_data(self.agent.cfg.write_dirs),
                "un_write_dirs": public_data(self.agent.cfg.un_write_dirs)}

    def update_path_policy(self, path, *, writable, remove=False):
        """Update configuration and the normalized policy copies held by live tools."""
        entries = self.agent.cfg.write_dirs if writable else self.agent.cfg.un_write_dirs
        candidate = list(entries)
        if remove:
            if path not in candidate:
                raise ControlError("not_found", "Path is not in the policy list.", path=path)
            candidate.remove(path)
        else:
            path = self.workspace_path(path, pattern=True)
            if path == ".":
                raise ControlError("invalid_path", "The workspace root cannot be a policy entry.")
            if path in candidate:
                raise ControlError("already_exists", "Path is already in the policy list.", path=path)
            candidate.append(path)
        # BaseReadWrite normalizes nonempty lists into copies at construction.
        # Prepare every tool update before changing the authoritative config.
        updates = [(tool, tool.refine_dirs(str(self.workspace), candidate))
                   for tool in self.agent.test_tools if isinstance(tool, BaseReadWrite)]
        entries[:] = candidate
        attribute = "write_able_dirs" if writable else "un_write_able_dirs"
        for tool, policy in updates:
            setattr(tool, attribute, policy)
        return self.list_rw_paths()

    def protect_files(self, files, *, enabled):
        """Validate all paths before invoking the agent's filesystem protection API."""
        paths = [self.workspace_path(path) for path in files]
        if enabled:
            self.agent.protect_files_on(paths)
        else:
            # Passing the actual set also lets the domain owner clear its list.
            if not paths:
                paths = [Path(path).relative_to(self.workspace).as_posix()
                         for path in self.agent.cwd_read_only_files]
            self.agent.protect_files_off(paths)
        return {"protected_files": public_data(self.agent.cwd_read_only_files)}

    def render_template(self, force=False):
        """Render via the agent's policy-aware template owner."""
        self.agent.render_template(tmp_overwrite=force)
        return {"overwrite": force}

    def config_detail(self, key=None):
        """Read a configuration subtree without leaking Config instances."""
        data = self.agent.cfg.as_dict()
        if key:
            for part in key.split("."):
                if not isinstance(data, dict) or part not in data:
                    raise ControlError("not_found", f"Configuration '{key}' not found.")
                data = data[part]
        return public_data(data)

    def show_web_session(self):
        """Read launch metadata only when a web session was supplied by the launcher."""
        session = getattr(self.agent, "web_console_session_info", None)
        if session is None:
            raise ControlError("unavailable", "No web console session is configured.")
        return public_data(session)

    def logo_and_version(self):
        """Return product identity for frontend-specific rendering."""
        return {"name": "UCAgent", "version": __version__}
