"""Independent worker sessions with task-bound tools and replaceable execution runners."""

import json
import copy
import hashlib
import shutil
import os
from pathlib import Path
import time
import asyncio
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from ucagent import UCTool, EmptyArgs
from ucagent import Config
from ucagent import get_tools_from_cfg
from .contracts import StrictModel
from .recovery import IssueReport, ISSUE_POLICIES, ExecutionCircuitOpen


class SubmitArgs(StrictModel):
    """Submit a substantive result without claiming that the stage has passed."""

    status: Literal["ready", "needs_attention"] = "ready"
    issue: IssueReport | None = None
    stage_args: dict | str | None = None
    timeout: int = Field(default=0, ge=0, description="Final Checker timeout in seconds")
    summary: str = Field(min_length=1, max_length=16000, description="Actual work and remaining issues")


    @model_validator(mode="after")
    def issue_required(self):
        """Unfinished work requires a structured reason; completed work carries no issue."""
        if (self.status == "needs_attention") != (self.issue is not None):
            raise ValueError("needs_attention requires issue; ready must not include issue")
        return self


class SubstageArgs(StrictModel):
    """Bind advancement to the current server-issued step token."""

    step_token: str = Field(description="Exact current step_token returned by CurrentTips")
    timeout: int = Field(default=0, ge=0, description="Checker timeout in seconds")
    stage_args: dict | str | None = Field(default=None, description="Current checker arguments")


class BoundTool(UCTool):
    """Expose the delegate schema while enforcing a non-forgeable task identity."""

    worker: Any = Field(exclude=True)
    delegate: Any = Field(default=None, exclude=True)
    action: str = Field(default="", exclude=True)

    def display_result(self, content):
        """Project task-control replies without filtering delegated file or Checker text."""
        from .display import control_result, tool_body
        if self.action == "check":
            from ucagent import format_check_result
            return tool_body(format_check_result(content))
        return tool_body(control_result(self.action, content))

    def invoke(self, input, config=None, **kwargs):
        """Bind MCP calls to their Sub and expose CLI tool bodies only to its detail view."""
        from .view import worker_output
        from ucagent import format_message_value
        from ucagent import output_context
        external = not self.worker.backend_class.capabilities.model_rounds
        started = time.monotonic()
        with worker_output(self.worker.parent, self.worker.record):
            if external:
                arguments = self._tool_arguments(input)
                if isinstance(arguments, dict):
                    arguments = {key: value for key, value in arguments.items() if key != "ctx"}
                with output_context(source="tool", kind="detail"):
                    self.worker.message_echo(f"\nTool Call: {self.name}\n{format_message_value(arguments)}")
            try:
                result = super().invoke(input, config, **kwargs)
            except Exception as error:
                if external:
                    with output_context(source="tool", kind="detail"):
                        self.worker.message_echo(f"\nTool Error: {self.name}\n{error}")
                raise
            if external:
                with output_context(source="tool", kind="detail"):
                    self.worker.message_echo(f"\nTool Result: {self.name} ({time.monotonic() - started:.2f}s)\n"
                                             + self.display_result(result))
            return result

    def _run(self, **kwargs):
        """Check ownership on every invocation, including calls after submission."""
        with self.worker.record.lock:
            self.worker.record.activity = "tool:" + self.name
            try:
                result = self.worker.invoke(self.action, self.delegate, kwargs)
                if self.delegate is not None:
                    failed = (isinstance(result, dict) and (result.get("error") or result.get("success") is False))
                    failed = failed or (isinstance(result, str) and result.startswith("[ERROR]"))
                    self._record_evidence("error" if failed else "returned")
                    if failed:
                        if self.worker.service.observe_worker_failure(
                                self.worker.record, "tool_failure", subject=f"Tool {self.name}"):
                            raise ExecutionCircuitOpen("tool_failure", self.worker.record.key)
                    else:
                        self.worker.service.observe_worker_success(self.worker.record, "tool_failure")
                return result
            except Exception as error:
                if self.delegate is not None and not isinstance(error, ExecutionCircuitOpen):
                    self._record_evidence("error")
                    if self.worker.service.observe_worker_failure(
                            self.worker.record, "tool_failure", subject=f"Tool {self.name}", error=error):
                        raise ExecutionCircuitOpen("tool_failure", self.worker.record.key) from error
                raise
            finally:
                self.worker.record.activity = None

    def _record_evidence(self, outcome):
        """Record actual invocation identity without copying sensitive tool arguments or output."""
        record = self.worker.record
        entry = {"id": uuid4().hex, "tool": self.name, "outcome": outcome, "attempt": record.attempt}
        record.tool_evidence.append(entry)
        record.tool_evidence[:] = record.tool_evidence[-100:]
        self.worker.service.emit("tool_evidence", task_id=record.key, evidence=entry)

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
        super_name = getattr(self.parent, "message_sender", "Super:DUT").removeprefix("Super:")
        self.message_sender = f"Sub:{super_name}/{record.spec.id}"
        from .contracts import role_backend_config
        self.cfg = role_backend_config(self.parent.cfg, record.role)
        from ucagent import get_backend_class
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
        self._checked_stage = None
        self._checked_args = None
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
        self.suppress_tool_result_messages = False
        from .view import WorkerDisplay
        self.display = WorkerDisplay(self)

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
        """Signal an explicitly configured deadline; the service retains the slot until return."""
        limit = self.service.worker_limit(self.record, "worker_timeout_seconds")
        if limit > 0:
            self.record.budget_error = self.service.interrupt_budget(
                "worker_timeout_seconds", limit, limit, self.record.key)
            self.record.error = str(self.record.budget_error)
        else:
            self.record.execution_issue = {"kind": "execution", "category": "worker_timeout",
                "summary": "The worker was interrupted while its task was active.",
                "next_action": "Inspect the Sub status and resume after confirming the task can continue."}
            self.record.error = self.record.execution_issue["summary"]
        self.record.cancel.set()
        self.service.emit("task_timeout", task_id=self.record.key)

    def is_break(self):
        """Provide the existing backend cancellation contract."""
        return self.closed or self.record.cancel.is_set() or self.record.result is not None

    def message_echo(self, text, end="\n"):
        """Attribute worker output without exposing model or connection configuration."""
        rendered = str(text)
        sender = self.message_sender
        if (rendered and not rendered.isspace() and f"· {sender}" not in rendered
                and not rendered.lstrip().startswith(f"[{sender}]")):
            rendered = f"[{self.message_sender}] {rendered}"
        from .view import worker_output
        with worker_output(self.parent, self.record):
            self.parent.message_echo(rendered, end=end)

    def file_access_policy(self):
        """Describe task-local file authority independently of a backend native sandbox."""
        spec = self.record.spec
        readonly = list(self.cfg.get_value("un_write_dirs", []))
        if self.record.split:
            readonly.extend(name for name in spec.inputs if name not in spec.outputs)
        return {"write_dirs": list(spec.outputs if self.record.split else self.cfg.write_dirs),
                "un_write_dirs": list(dict.fromkeys(readonly))}

    def get_current_tips(self):
        """Expose the authorized step and cumulative budgets without changing ownership."""
        submission = self.submission_state()
        return {**self.service.driver.tips(self.record.lease),
                "submission": submission, "next_action": submission["next_action"],
                "handoff_inputs": self.service.handoff.run["input_manifest"] if self.service.handoff else [],
                "file_access": self.file_access_policy(),
                "available_tools": list(self.record.available_tools),
                "available_capabilities": dict(self.record.capabilities),
                "requirement_checks": list(self.service.requirement_checks.checks),
                "recent_tool_evidence": list(self.record.tool_evidence[-10:]),
                "task": {"id": self.record.key, "role": self.record.spec.role,
                         "inputs": list(self.record.spec.inputs), "outputs": list(self.record.spec.outputs)},
                "budget": self.record.budget_status(self.service.settings.limits)}

    def submission_state(self):
        """Keep unfinished batches and missing completion evidence in the current worker."""
        record = self.record
        if not record.split:
            current = self.stage_manager.get_current_stage()
            if record.lease.steps:
                if current in record.lease.steps:
                    return {"ready": False, "error_code": "SUBSTAGES_REMAIN",
                            "error": "Authorized substages remain unfinished.",
                            "next_action": "CompleteSubStage"}
            else:
                if self._checked_stage is not current or not current.check_pass:
                    return {"ready": False, "error_code": "STAGE_CHECK_REQUIRED",
                            "error": "Check must pass all current-stage batches after the latest work before submitting.",
                            "next_action": "Check"}
                diagnostic = current.skill_usage_diagnostic()
                if diagnostic is not None:
                    return {**diagnostic, "ready": False, "next_action": "SetSkillUsage",
                            "guidance": diagnostic["next_action"]}
                if not (current.meta_get_journal() or "").strip():
                    return {"ready": False, "error_code": "STAGE_JOURNAL_REQUIRED",
                            "error": "Record actual work and evidence with SetCurrentStageJournal before submitting.",
                            "next_action": "SetCurrentStageJournal"}
        return {"ready": True, "next_action": "SubmitTaskResult"}

    def build_tools(self):
        """Instantiate fresh business tools and attach only task-authorized lifecycle tools."""
        from ucagent import fileops
        from ucagent import PluginContext, create_plugin_tools
        from ucagent import ArgsDoCheck
        r = self.record
        policy = self.file_access_policy()
        writes, readonly = policy["write_dirs"], policy["un_write_dirs"]
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
            if name == "CreateDirectory" and r.split:
                # Permit scaffolding for exact output files; invoke still fences each directory.
                kwargs["write_dirs"] = sorted({str(parent) for output in writes
                    for parent in Path(output).parents if str(parent) != "."})
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
                from ucagent import ListSkill, RunSkillScript
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
            ("SubmitTaskResult", "Submit actual work and stop this worker. Stage tasks require all authorized substages "
             "or all stage batches checked, required Skill evidence and a journal. File-only tasks submit against their "
             "artifact contract without stage tools. Rejection keeps this worker active. This does not declare the stage passed.", SubmitArgs, "submit"),
        ]
        if not r.split:
            actions.append(("Check", "Validate the authorized current step and advance its batches without stopping this worker. "
                            "Continue after batch_advanced; after all checks pass, finish required Skill evidence and journal, "
                            "then follow next_action to complete the substage or submit the task.", ArgsDoCheck, "check"))
            if r.lease.steps:
                actions.append(("CompleteSubStage", "Validate and complete only the authorized current descendant. Use the latest step_token.", SubstageArgs, "substage"))
        self.test_tools += [BoundTool(name=n, description=d, args_schema=a, worker=self, action=k)
                            for n, d, a, k in actions]
        r.available_tools = [tool.name for tool in self.test_tools]
        r.capabilities = {}
        for tool in self.test_tools:
            for capability in getattr(tool.delegate, "capabilities", ()):
                r.capabilities.setdefault(capability, []).append(tool.name)
        return self.test_tools

    def invoke(self, action, tool, arguments):
        """Serialize each worker's tools and fence stage changes and result submission."""
        r = self.record
        with r.lock:
            self.ensure_active()
            r.calls += 1
            call_limit = self.service.worker_limit(r, "worker_tool_calls")
            if call_limit > 0 and r.calls > call_limit:
                r.cancel.set()
                raise self.service.interrupt_budget("worker_tool_calls", r.calls, call_limit, r.key)
            driver = self.service.driver
            if action == "tips":
                return self.get_current_tips()
            if action == "submit":
                status = arguments.get("status", "ready")
                if status == "ready":
                    submission = self.submission_state()
                    if not submission["ready"]:
                        return {**self.get_current_tips(), **submission, "submitted": False}
                if status == "needs_attention":
                    report = IssueReport.model_validate(arguments.get("issue"))
                    evidence_ids = {entry["id"] for entry in r.tool_evidence if entry["attempt"] == r.attempt}
                    if set(report.evidence_ids) - evidence_ids:
                        return {"submitted": False, "error_code": "UNKNOWN_EVIDENCE", "next_action": "Use evidence IDs returned by CurrentTips; do not invent tool evidence."}
                    checks = self.service.requirement_checks.evaluate(self.service, r, [c.model_dump() for c in report.conditions])
                    failures = [e for e in r.tool_evidence if e["id"] in report.evidence_ids and e["outcome"] == "error"]
                    if (ISSUE_POLICIES[report.kind]["handling"] == "check_prerequisites"
                            and checks and all(row["satisfied"] is True for row in checks) and not failures):
                        return {"submitted": False, "error_code": "REQUIREMENTS_SATISFIED", "checks": checks,
                                "available_capabilities": r.capabilities,
                                "next_action": "The reported prerequisites are available. Continue with the authorized tools, or report the actual unmet condition and invocation evidence."}
                    arguments["issue"] = {**report.model_dump(), "source": "sub_report",
                                          "evidence": [e for e in r.tool_evidence if e["id"] in report.evidence_ids], "checks": checks}
                r.result = {"summary": arguments["summary"], "status": status, "issue": arguments.get("issue"),
                            "stage_args": arguments.get("stage_args") if arguments.get("stage_args") is not None
                                else copy.deepcopy(self._checked_args), "timeout": arguments.get("timeout", 0)}
                r.state = "submitted"
                self.service.emit("task_submitted", task_id=r.key)
                return {"submitted": True, "stop": True, "validation_pending": True,
                        "message": "Result submitted; final validation runs after this worker stops."}
            if getattr(self.parent, "_need_human", False):
                raise PermissionError("Human review is pending; submit status=needs_attention with issue.kind=review")
            if action == "check":
                self._checked_stage = None
                self._checked_args = None
                result = driver.check(r.lease, arguments.get("timeout") or self.cfg.get_value("call_time_out", 300),
                                     arguments.get("stage_args"), actor=self.message_sender)
                self.service.observe_batch_progress(r, result)
                if self.service.observe_checker_result(r, result):
                    raise ExecutionCircuitOpen("checker_repeat", r.key)
                if result.get("check_pass") is True:
                    self._checked_stage = self.stage_manager.get_current_stage()
                    self._checked_args = copy.deepcopy(arguments.get("stage_args"))
                    result = {**result, "message": "All current-stage checks passed. Finish required Skill evidence and journal before completing the authorized task."}
                submission = self.submission_state()
                return {**result, "submission": submission,
                        "next_action": submission["next_action"] if result.get("check_pass") else "Check"}
            if action == "substage":
                self._checked_stage = None
                self._checked_args = None
                result = driver.complete_substage(r.lease, arguments["step_token"],
                    arguments.get("timeout") or self.cfg.get_value("call_time_out", 300), arguments.get("stage_args"),
                    actor=self.message_sender)
                self.service.observe_batch_progress(r, result)
                if self.service.observe_checker_result(r, result):
                    raise ExecutionCircuitOpen("checker_repeat", r.key)
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
                    if r.split and arguments[key] in r.inputs and arguments[key] not in r.spec.outputs:
                        raise PermissionError("Write target is a read-only input; declare it as an output to update it")
                    path = self.service.path(arguments[key], writing=True)
                    self.artifact_path(arguments[key])
                    if r.split and str(path.relative_to(self.service.workspace)) not in r.spec.outputs:
                        # Creating a parent directory is allowed only within the configured write policy.
                        if tool.name != "CreateDirectory" or not any(self.service.path(p).is_relative_to(path) for p in r.spec.outputs):
                            raise PermissionError("Write target is outside this task's outputs")
            with driver.ownership():
                if tool.name not in {"ReadTextFile", "PathList", "FindFiles", "GetFileInfo", "SearchText",
                                     "ListSkill", "StageJournal", "AllStageJournal", "SetSkillUsage", "SetCurrentStageJournal"}:
                    self._checked_stage = None
                    self._checked_args = None
                # Stage evidence callbacks and manager tools share the original checker state.
                return tool.invoke(arguments)

    def run(self, runner_factory=None):
        """Execute through an injected test runner or a role-selected production backend."""
        self.ensure_active()
        self.display.start()
        self.build_tools()
        if runner_factory is not None:
            runner_factory(self)
        else:
            self.run_backend()

    def observe_backend_failure(self, error, *, phase="model"):
        """Feed provider and managed-CLI failures into the shared Sub circuit."""
        opened = self.service.observe_worker_failure(self.record, "backend_failure",
            subject=f"Sub backend {phase}", error=error)
        return opened

    def observe_backend_success(self):
        """Clear a consecutive backend-error streak after a completed request."""
        self.service.observe_worker_success(self.record, "backend_failure")

    def before_backend_turn(self):
        """Count backend turns and enforce only an explicitly enabled fuse."""
        self.ensure_active()
        self.record.budget.backend_turns += 1
        limit = self.service.worker_limit(self.record, "worker_backend_turns")
        if limit > 0 and self.record.budget.backend_turns > limit:
            self.record.cancel.set()
            raise self.service.interrupt_budget("worker_backend_turns", self.record.budget.backend_turns, limit, self.record.key)

    def before_model(self):
        """Charge real model calls only for backends exposing a model boundary."""
        if self.record.result is not None:
            return {"jump_to": "end"}
        self.ensure_active()
        self.record.rounds += 1
        limit = self.service.worker_limit(self.record, "worker_model_rounds")
        if limit > 0 and self.record.rounds > limit:
            self.record.cancel.set()
            raise self.service.interrupt_budget("worker_model_rounds", self.record.rounds, limit, self.record.key)
        return None

    def run_backend(self):
        """Run and continue one independent backend session until accepted submission or cancellation."""
        from ucagent import AgentSession
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
