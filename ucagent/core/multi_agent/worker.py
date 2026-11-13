"""Independent worker sessions with task-bound tools and replaceable execution runners."""

import json
import hashlib
import shutil
import os
from pathlib import Path
import time
import asyncio
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

from ucagent.core.tools.uctool import UCTool, EmptyArgs
from ucagent.util.config import Config
from ucagent.util.functions import get_tools_from_cfg
from .contracts import StrictModel


class SubmitArgs(StrictModel):
    """Submit a substantive result without claiming that the stage has passed."""

    status: Literal["ready", "blocked"] = "ready"
    stage_args: dict | str | None = None
    timeout: int = Field(default=0, ge=0, description="Final Checker timeout in seconds")
    summary: str = Field(min_length=1, max_length=16000, description="Actual work and remaining issues")


class SubstageArgs(StrictModel):
    """Bind advancement to the current server-issued step token."""

    step_token: str = Field(description="Exact current step_token returned by CurrentTips")
    timeout: int = Field(default=0, ge=0, description="Checker timeout in seconds")
    stage_args: dict | str | None = Field(default=None, description="Current checker arguments")


class ScopedCompleteArgs(SubstageArgs):
    """Accept familiar completion calls without granting global stage control."""

    step_token: str | None = Field(default=None, description=
        "For a subtree, supply the latest CurrentTips.step_token to complete its current child. "
        "For a single stage, Complete submits its journal for final validation after this worker stops.")


class BoundTool(UCTool):
    """Expose the delegate schema while enforcing a non-forgeable task identity."""

    worker: Any = Field(exclude=True)
    delegate: Any = Field(default=None, exclude=True)
    action: str = Field(default="", exclude=True)

    def display_result(self, content):
        """Project task-control replies without filtering delegated file or Checker text."""
        from .display import control_result
        return control_result(self.action, content)

    def _run(self, **kwargs):
        """Check ownership on every invocation, including calls after submission."""
        with self.worker.record.lock:
            self.worker.record.activity = "tool:" + self.name
            try:
                return self.worker.invoke(self.action, self.delegate, kwargs)
            finally:
                self.worker.record.activity = None

    async def ainvoke(self, input, config=None, **kwargs):
        """Preserve capability errors across MCP and retain synchronous task locking."""
        arguments = dict(input)
        arguments.pop("ctx", None)
        return await asyncio.to_thread(self.invoke, arguments, config, **kwargs)


class WorkerSession:
    """Own only execution state; reuse prepared resources without initializing an Agent."""

    def __init__(self, service, record):
        """Create fresh mutable tools and backend state for one task attempt."""
        self.service, self.record = service, record
        self.parent = service.agent
        from .contracts import role_backend_config
        self.cfg = role_backend_config(self.parent.cfg, record.role)
        from ucagent.core.backends import get_backend_class
        self.backend_class = get_backend_class(self.cfg)
        record.model_rounds_available = self.backend_class.capabilities.model_rounds
        self.isolated = record.split and self.backend_class.requires_mcp
        self.session_dir = service.workspace / ".ucagent" / "multi_agent" / self.parent.session_id.hex / record.plan_id / record.spec.id / str(record.attempt)
        self.workspace = str(self.session_dir / "workspace" if self.isolated else service.workspace)
        self.output_baselines = {}
        if self.isolated:
            Path(self.workspace).mkdir(parents=True, exist_ok=True, mode=0o700)
            for name in set(record.spec.inputs + record.spec.outputs):
                source = service.path(name)
                if name in record.spec.outputs:
                    self.output_baselines[name] = hashlib.sha256(source.read_bytes()).hexdigest() if source.exists() else None
                if source.exists():
                    target = self.artifact_path(name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
        self.stage_manager = self.parent.stage_manager
        self.thread_id = uuid4().hex
        self.session_id = uuid4()
        record.session_id = self.session_id.hex
        langfuse_cfg = self.cfg.get_value("langfuse", Config({}))
        self.langfuse_enable = langfuse_cfg.get_value("enable", False) is True and self.backend_class.capabilities.model_rounds
        if self.langfuse_enable:
            from langfuse.langchain import CallbackHandler
            # Callbacks contain mutable run maps; only the parent-owned client is shared.
            self.langfuse_handler = CallbackHandler(public_key=self.cfg.get_value("langfuse.public_key", ""))
            self.langfuse_run_name = f"Sub-Agent:{record.key}:attempt-{record.attempt}"
            self.langfuse_metadata = {
                "langfuse_session_id": self.parent.session_id.hex,
                "langfuse_tags": ["sub-agent", record.spec.role],
                "ucagent_agent": "sub-agent", "ucagent_plan_id": record.plan_id,
                "ucagent_task_id": record.key, "ucagent_attempt": record.attempt,
                "ucagent_role": record.spec.role, "ucagent_worker_session_id": self.session_id.hex,
                "ucagent_scope_root": record.lease.root.name,
            }
        self.stream_output = False
        self.context_management_strategy = "TrimAndSummaryMiddleware"
        for key, default in [("max_tokens", 20480), ("max_summary_tokens", 8192),
                             ("max_keep_msgs", 200), ("tail_keep_msgs", 20)]:
            setattr(self, "max_token" if key == "max_tokens" else key,
                    self.cfg.get_value("conversation_summary." + key, default))
        self._tool__call_error = []
        self.backend = None
        self.closed = False
        self.test_tools = []

    def artifact_path(self, name):
        """Reject symlink outputs even when an external process wrote the private copy."""
        self.service.path(name)
        root = Path(self.workspace)
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Worker artifact escapes its workspace")
        if any(part.is_symlink() for part in [path, *path.parents] if part != root.parent):
            raise ValueError("Worker artifact cannot be a symlink")
        return path

    def ensure_active(self):
        """Reject cancelled, submitted, stale or exhausted task capabilities."""
        r = self.record
        if self.closed or r.cancel.is_set() or r.result is not None:
            raise PermissionError("Task execution has stopped or submitted its result")
        if r.deadline is not None and time.monotonic() >= r.deadline:
            self.timeout()
            raise TimeoutError("Task deadline exceeded")
        self.service.driver.validate(r.lease)

    def timeout(self):
        """Signal cancellation; the service retains the slot until run returns."""
        self.record.error = "Task absolute runtime budget exhausted"
        self.record.cancel.set()
        self.service.emit("task_timeout", task_id=self.record.key)

    def is_break(self):
        """Provide the existing backend cancellation contract."""
        return self.closed or self.record.cancel.is_set() or self.record.result is not None

    def message_echo(self, text, end="\n"):
        """Attribute worker output without exposing model or connection configuration."""
        leading = len(text) - len(text.lstrip("\n"))
        prefix = f"[{self.record.key}]\n" if text[leading:] else ""
        self.parent.message_echo(text[:leading] + prefix + text[leading:], end=end)

    def get_current_tips(self):
        """Expose the authorized step and cumulative budgets without changing ownership."""
        return {**self.service.driver.tips(self.record.lease),
                "handoff_inputs": self.service.handoff.run["input_manifest"] if self.service.handoff else [],
                "task": {"id": self.record.key, "role": self.record.spec.role,
                         "inputs": list(self.record.spec.inputs), "outputs": list(self.record.spec.outputs)},
                "budget": self.record.budget_status(self.service.settings.limits)}

    def build_tools(self):
        """Instantiate fresh business tools and attach only task-authorized lifecycle tools."""
        from ucagent.core.tools import fileops
        from ucagent.core.plugins import PluginContext, create_plugin_tools
        from ucagent.core.stage.vmanager import ArgsDoCheck
        r = self.record
        writes = r.spec.outputs if r.split else self.cfg.write_dirs
        readonly = self.cfg.get_value("un_write_dirs", [])
        tools = []
        file_names = {"ReadTextFile", "PathList", "FindFiles", "SearchText", "GetFileInfo",
                      "EditTextFile", "ReplaceStringInFile", "DeleteTextLines", "DeleteFile",
                      "CreateDirectory", "CopyFile", "MoveFile"}
        writable = {"EditTextFile", "ReplaceStringInFile", "DeleteTextLines", "DeleteFile",
                    "CreateDirectory", "CopyFile", "MoveFile"}
        allowed = set(r.role.allowed_tools)
        parent_names = {t.name for t in self.parent.test_tools}
        # The parent test_tools is the supervisor view after assembly; the original
        # workflow catalog supplies business-tool availability, never role authority.
        parent_names |= set(getattr(self.parent, "multi_agent_business_names", ()))
        for name in sorted(allowed & file_names & parent_names):
            cls = getattr(fileops, name)
            kwargs = {"write_dirs": writes, "un_write_dirs": readonly} if name in writable else {}
            if name in {"EditTextFile", "ReplaceStringInFile", "DeleteTextLines"}:
                kwargs["heading_companions"] = tuple(self.cfg.get_value("markdown.heading_companions", []))
            tool = cls(self.workspace, **kwargs)
            if name == "ReadTextFile":
                if not self.isolated:
                    for stage in self.stage_manager.stages:
                        tool.append_callback(stage.on_file_read)
                self.tool_read_text = tool
            tools.append(tool)
        if not r.split:
            if allowed - file_names:
                plugins = create_plugin_tools(getattr(self.parent, "plugins", []), PluginContext(
                    workspace=Path(self.workspace), output_dir=os.path.relpath(self.parent.output_dir, self.workspace),
                    write_dirs=tuple(writes), un_write_dirs=tuple(readonly), cfg=self.cfg,
                    plugin_root=Path(self.workspace), dut_name=self.parent.dut_name))
                tools.extend(t for t in plugins if t.name in allowed and t.name in parent_names)
                for name in self.cfg.get_value("manager_tools", []):
                    if name in allowed:
                        tools.append(self.stage_manager.manager_tool_registry[name]().bind(self.stage_manager))
            if self.cfg.get_value("skill.use_skill", False):
                from ucagent.core.tools.skill import ListSkill, RunSkillScript
                tools.append(ListSkill(self.workspace).bind(self))
                if "RunSkillScript" in allowed and "RunSkillScript" in parent_names:
                    tools.append(RunSkillScript(self.workspace).bind(self))
            for tool in self.stage_manager.new_tools():
                if tool.name in {"SetCurrentStageJournal", "SetSkillUsage", "StageJournal", "AllStageJournal"}:
                    tools.append(tool)
        tools = get_tools_from_cfg(tools, self.cfg.tools.as_dict())
        for delegate in tools:
            delegate.set_call_time_out(self.cfg.get_value("call_time_out", 300))
        self.test_tools = [BoundTool(name=t.name, description=t.description, args_schema=t.args_schema,
                                    worker=self, delegate=t) for t in tools]
        actions = [
            ("CurrentTips", "Read your current authorized task step and its step_token.", EmptyArgs, "tips"),
            ("SubmitTaskResult", "Submit actual work and stop this worker. ready is rejected while substages remain; continue using the returned tips. This does not declare the stage passed.", SubmitArgs, "submit"),
        ]
        if not r.split:
            actions.append(("Complete", "Scoped completion only: with step_token, validate the current authorized child. "
                            "For a single stage, submit its journal and stop for final Checker validation; "
                            "submitted is not stage acceptance.", ScopedCompleteArgs, "complete"))
            actions.append(("Check", "Validate the authorized current step; fix reported issues.", ArgsDoCheck, "check"))
            if r.lease.steps:
                actions.append(("CompleteSubStage", "Validate and complete only the authorized current descendant. Use the latest step_token.", SubstageArgs, "substage"))
        self.test_tools += [BoundTool(name=n, description=d, args_schema=a, worker=self, action=k)
                            for n, d, a, k in actions]
        return self.test_tools

    def invoke(self, action, tool, arguments):
        """Serialize each worker's tools and fence stage changes and result submission."""
        r = self.record
        with r.lock:
            self.ensure_active()
            r.calls += 1
            if r.calls > self.service.settings.limits.worker_tool_calls:
                r.cancel.set()
                raise RuntimeError("Logical task tool-call budget exhausted")
            driver = self.service.driver
            if action == "tips":
                return self.get_current_tips()
            scoped_submit = False
            if action == "complete":
                if r.lease.steps:
                    if arguments.get("step_token") is not None:
                        action = "substage"
                    else:
                        tips = self.get_current_tips()
                        if tips["scope_done"]:
                            return {"complete": False, **tips}
                        return {"complete": False, "error_code": "STEP_TOKEN_REQUIRED",
                                "error": "Use the current step_token to complete this authorized child",
                                "next_call": {"tool": "CompleteSubStage", "arguments": {
                                    **arguments, "step_token": tips["step_token"]}}, **tips}
                else:
                    journal = r.lease.root.meta_get_journal()
                    if not journal:
                        return {"complete": False, "error_code": "STAGE_JOURNAL_REQUIRED",
                                "error": "Record actual work with SetCurrentStageJournal before Complete",
                                "next_action": "SetCurrentStageJournal"}
                    # This adapter only submits. The original Complete gate runs after
                    # all worker tools have drained, just like SubmitTaskResult.
                    action, scoped_submit = "submit", True
                    arguments = {**arguments, "summary": journal, "status": "ready"}
            if action == "submit":
                status = arguments.get("status", "ready")
                if status == "ready" and r.lease.steps and self.stage_manager.get_current_stage() in r.lease.steps:
                    return {"submitted": False, "error_code": "SUBSTAGES_REMAIN",
                            "error": "Authorized substages remain unfinished",
                            "action": "Continue the current step with CompleteSubStage; submit only after scope_done. "
                                      "Use status=blocked only for an actual blocker.",
                            **self.get_current_tips()}
                r.result = {"summary": arguments["summary"], "status": status,
                            "stage_args": arguments.get("stage_args"), "timeout": arguments.get("timeout", 0)}
                r.state = "submitted"
                self.service.emit("task_submitted", task_id=r.key)
                result = {"submitted": True, "stop": True}
                if scoped_submit:
                    result.update(complete=False, validation_pending=True,
                                  message="Result submitted; final stage validation runs after this worker stops.")
                return result
            if getattr(self.parent, "_need_human", False):
                raise PermissionError("Human review is pending; submit status=blocked")
            if action == "check":
                return driver.check(r.lease, arguments.get("timeout") or self.cfg.get_value("call_time_out", 300),
                                    arguments.get("stage_args"))
            if action == "substage":
                result = driver.complete_substage(r.lease, arguments["step_token"],
                    arguments.get("timeout") or self.cfg.get_value("call_time_out", 300), arguments.get("stage_args"))
                return {**result, "budget": r.budget_status(self.service.settings.limits)}
            if r.lease.steps and self.stage_manager.get_current_stage() not in r.lease.steps:
                raise PermissionError("Subtree finished; only SubmitTaskResult is available")
            # Validate every write target against the run policy as well as the task
            # allowlist; tool-local write_dirs alone could widen a parent restriction.
            for key in ("path", "dest_path", "source_path"):
                if key in arguments and tool.name in {"EditTextFile", "ReplaceStringInFile", "DeleteTextLines",
                        "DeleteFile", "CopyFile", "MoveFile", "CreateDirectory"}:
                    if key == "source_path" and tool.name == "CopyFile":
                        continue
                    path = self.service.path(arguments[key], writing=True)
                    self.artifact_path(arguments[key])
                    if r.split and str(path.relative_to(self.service.workspace)) not in r.spec.outputs:
                        # Creating a parent directory is allowed only within the configured write policy.
                        if tool.name != "CreateDirectory" or not any(self.service.path(p).is_relative_to(path) for p in r.spec.outputs):
                            raise PermissionError("Write target is outside this task's outputs")
            with driver.ownership():
                # Stage evidence callbacks and manager tools share the original checker state.
                return tool.invoke(arguments)

    def run(self, runner_factory=None):
        """Execute through an injected test runner or a role-selected production backend."""
        self.ensure_active()
        self.build_tools()
        if runner_factory is not None:
            runner_factory(self)
        else:
            self.run_backend()

    def before_backend_turn(self):
        """Bound continuation turns across retries of the same logical task."""
        self.ensure_active()
        self.record.budget.backend_turns += 1
        if self.record.budget.backend_turns > self.service.settings.limits.worker_backend_turns:
            self.record.cancel.set()
            raise RuntimeError("Logical task backend-turn budget exhausted")

    def before_model(self):
        """Charge real model calls only for backends exposing a model boundary."""
        if self.record.result is not None:
            return {"jump_to": "end"}
        self.ensure_active()
        self.record.rounds += 1
        if self.record.rounds > self.service.settings.limits.worker_model_rounds:
            self.record.cancel.set()
            raise RuntimeError("Logical task model-round budget exhausted")
        return None

    def run_backend(self):
        """Run and continue one independent backend session until accepted submission or cancellation."""
        from ucagent.core.agent.session import AgentSession
        from .display import control_result
        self.cfg.set_value("backend.key_name", self.record.role.backend)
        session = AgentSession(self, directory=self.session_dir,
            before_turn=self.before_backend_turn, before_model=self.before_model,
            yielded=lambda: self.record.result is not None,
            endpoint_factory=lambda: self.service.endpoint_factory)
        self.ensure_active()
        prompt = self.cfg.get_value("multi_agent_prompts.worker", "")
        system = getattr(self.parent, "_business_system_prompt", "") + "\n" + self.record.role.system + "\n" + prompt
        display = self.record.spec.instruction
        instruction = display + "\n" + json.dumps(self.get_current_tips(), ensure_ascii=False)
        if self.record.feedback:
            instruction += "\nValidation feedback:\n" + str(self.record.feedback)
            display += "\n\nValidation feedback:\n" + control_result("status", self.record.feedback)
        messages = [self.backend.get_system_message(system),
                    self.backend.get_human_message(instruction, display_text=display)]
        while not self.is_break():
            session.run_turn({"messages": messages})
            if self.is_break():
                break
            continuation = ("Continue in this session. Follow the current authorized step and its next_action; "
                            "a completed substage or a text reply does not finish a subtree task.")
            messages = [self.backend.get_human_message(
                continuation + "\n" + json.dumps(self.get_current_tips(), ensure_ascii=False),
                display_text=continuation)]

    def close(self):
        """Revoke tools before releasing backend resources."""
        with self.record.lock:
            self.closed = True
        if self.backend is not None:
            self.backend.close()
