# -*- coding: utf-8 -*-
"""Task execution, interaction, messages and statistics for one verification Agent."""

from ucagent.util.log import echo_g, info, message, warning, msg_msg, MESSAGE_LOG_DEFERRED
from ucagent.util.functions import fmt_time_deta, fmt_time_stamp
from ucagent.util.functions import yam_str, make_llm_tool_ret
import ucagent.util.functions as fc

from ucagent.core.tools.skill import _list_skills, list_skills_in_format

import time
import math
import copy
import os
import hashlib
import json

from typing import Any, Callable, Dict, List, Mapping, Optional, OrderedDict

class VerifyAgent:
    """AI-powered hardware verification agent for chip design testing."""

    def __init__(
        self,
        workspace: str,
        dut_name: str,
        output: str,
        config_file: Optional[str] = None,
        cfg_override: Optional[Dict[str, Any]] = None,
        tmp_overwrite: bool = False,
        template_dir: Optional[str] = None,
        template_cfg: Optional[Dict[str, Any]] = None,
        guid_doc_path: List[str] = [],
        stream_output: bool = False,
        seed: Optional[int] = None,
        sys_tips: str = "",
        ex_tools: Optional[List[str]] = None,
        thread_id: Optional[int] = None,
        debug: bool = False,
        no_embed_tools: bool = False,
        force_stage_index: int = 0,
        force_todo: bool = False,
        no_write_targets: Optional[List[str]] = None,
        interaction_mode: str = "standard",
        gen_instruct_file: Optional[str] = None,
        stage_skip_list: Optional[List[int]] = None,
        stage_unskip_list: Optional[List[int]] = None,
        use_todo_tools: bool = False,
        reference_files: dict = None,
        no_history: bool = False,
        enable_context_manage_tools: bool = False,
        exit_on_completion: bool = False,
        meta: Optional[Dict[str, Any]] = None,
        plugins: Optional[List[Any]] = None,
        plugin_guide_doc_paths: Optional[List[str]] = None,
        plugin_skill_paths: Optional[List[tuple[str, str]]] = None,
        workflow_config_file: Optional[str] = None,
        plugin_workflow: Optional[str] = None,
        template_target: Optional[str] = None,
        template_context_factory: Optional[
            Callable[[Any, Mapping[str, Any]], Mapping[str, Any]]
        ] = None,
        plugin_runtime_config_keys: Optional[List[str]] = None,
        *,
        _task_configuration=None,
        _defer_workspace_activation=False,
    ):
        """Construct a task through the shared preparation and component assembly path."""
        parameters = locals().copy()
        from ucagent.core.agent.construction import initialize_agent
        del parameters["self"]
        initialize_agent(self, parameters)

    def get_messages_cfg(self, keys: Optional[List[str]] = None) -> Dict[str, Any]:
        if self.message_manage_node is None:
            return {}
        ret = {"__manage_class__": self.message_manage_node.__class__.__name__}
        for k in keys:
            if hasattr(self.message_manage_node, k):
                ret[k] = getattr(self.message_manage_node, k)
        return ret

    def set_messages_cfg(self, cfg: Dict[str, Any]):
        success = {}
        if self.message_manage_node is None:
            return success
        aliases = {"max_token": "max_tokens"}
        for requested_key, value in cfg.items():
            key = aliases.get(requested_key, requested_key)
            if not hasattr(self.message_manage_node, key):
                continue
            if key in {
                "max_tokens",
                "max_summary_tokens",
                "max_keep_msgs",
                "tail_keep_msgs",
            }:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
                if value < 0 or (key == "max_summary_tokens" and value == 0):
                    continue
                candidate_max_keep = (
                    value
                    if key == "max_keep_msgs"
                    else self.message_manage_node.max_keep_msgs
                )
                candidate_tail_keep = (
                    value
                    if key == "tail_keep_msgs"
                    else self.message_manage_node.tail_keep_msgs
                )
                if (
                    candidate_max_keep > 0
                    and candidate_tail_keep > candidate_max_keep
                ):
                    continue
            setattr(self.message_manage_node, key, value)
            if hasattr(self, key):
                setattr(self, key, value)
            if key == "max_tokens":
                self.max_token = value
            success[requested_key] = value
        return success

    def summary_mode(self):
        if self.message_manage_node is None:
            return "None"
        return self.message_manage_node.__class__.__name__

    def summary_max_tokens(self):
        return self.max_summary_tokens

    def generate_instruction_file(self, file_path):
        """Generate workspace instructions using the shared resource writer."""
        from ucagent.core.workspace.assets import generate_instruction_file
        return generate_instruction_file(self.workspace, self.dut_name, self._default_system_prompt, file_path)

    def render_template(self, template_cfg=None, tmp_overwrite=False):
        """Refresh workflow templates using the shared resource renderer."""
        from ucagent.core.workspace.assets import render_workspace_template
        return render_workspace_template(self.workspace, self.cfg, self.dut_name,
            self.template, self.template_target, self.workflow_template_context, template_cfg, tmp_overwrite)

    def set_message_echo_handler(self, handler):
        """Set a custom message echo handler to process messages."""
        if not callable(handler):
            raise ValueError("Message echo handler must be callable")
        self.message_echo_handler = handler

    def unset_message_echo_handler(self):
        """Unset the custom message echo handler."""
        self.message_echo_handler = None

    def message_echo(self, msg, end="\n"):
        """Echo a message using the custom message echo handler if set."""
        if self.message_echo_handler is not None:
            # Frontends may forward through message(), which also logs. The
            # outer Agent owns this record; context-local deferral isolates workers.
            token = MESSAGE_LOG_DEFERRED.set(True)
            try:
                self.message_echo_handler(msg, end)
            finally:
                MESSAGE_LOG_DEFERRED.reset(token)
                msg_msg(msg, end=end)
        else:
            message(msg, end=end)



    def set_break(self, value=True):
        self._need_break = value
        if value and callable(getattr(self.backend, "cancel", None)):
            self.backend.cancel()
        service = getattr(self, "multi_agent", None)
        if not value and service is not None:
            service._workflow_stop.clear()
        if value and service is not None:
            for name, plan in list(service.plans.items()):
                if plan["state"] == "running":
                    service.cancel(name)

    def is_break(self):
        service = getattr(self, "multi_agent", None)
        return self._need_break or bool(service and service.planning_interrupted())



    def get_current_tips(self):
        if self._tool__call_error:
            return {"messages": copy.deepcopy(self._tool__call_error)}
        tips = self._continue_msg
        if self._continue_msg is None:
            tips = yam_str(self.stage_manager.get_current_tips())
        else:
            self._continue_msg = None
        self._tip_index += 1
        assert isinstance(tips, str), "StageManager should return a str type tips"
        msg = []
        if self._system_message:
            msg.append(self.backend.get_system_message(copy.copy(self._system_message)))
            self._system_message = None
        msg.append(self.backend.get_human_message(tips))
        return {"messages": msg}

    def set_system_message(self, msg: str):
        self._system_message = msg

    def get_system_message(self):
        """Get the current system message for the agent."""
        return self._system_message

    def get_default_system_prompt(self):
        """Get the default system prompt for the agent. And if skill is enabled, include skill prompt and skill list."""
        system = self.cfg.mission.prompt.get_value("system", "").strip()
        if self.cfg.skill.use_skill:
            formatted_skill_list = list_skills_in_format(_list_skills(self.workspace),self.workspace,self.cfg.skill.get_value("general_skill_list", []))
            skill_prompt = self.cfg.mission.prompt.get_value("skill_system", "").replace("{general_skill_list}", formatted_skill_list)
            system = system.replace("{skill_system}", skill_prompt)
        else:
            system = system.replace("{skill_system}", "")
        warning(f"System prompt: {system}")
        return system

    def set_continue_msg(self, msg: str):
        """Set the continue message for the agent."""
        if not isinstance(msg, str):
            raise ValueError("Continue message must be a string")
        try:
            msg.encode("utf-8").decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("Continue message must be a valid UTF-8 string")
        self._continue_msg = msg

    def get_stat_info(self):
        return {
            "version": self.__version__,
            "seed": self.seed,
            "dut_name": self.dut_name,
            "DUT": self.dut_name,
            "config_file": self.config_file,
            "config_arg": self.config_file,
            "workflow_config_file": self.workflow_config_file,
            "plugin_workflow": self.plugin_workflow,
            "plugins": [item.selector for item in self.plugins],
            "mission_name": self.cfg.mission.name,
            "meta": copy.deepcopy(self.meta),
        }

    def is_exit(self):
        if self._is_exit:
            info("Verify Agent is exited.")
        return self._is_exit


    def _cfg_bool(self, key: str, default: bool = False) -> bool:
        value = self.cfg.get_value(key, default)
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        raw = str(value).strip().lower()
        if raw in {"1", "true", "yes", "y", "on"}:
            return True
        if raw in {"0", "false", "no", "n", "off"}:
            return False
        return default

    def _sync_workspace_back_on_exit(self):
        if self._sync_workspace_back_on_exit_done:
            return
        self._sync_workspace_back_on_exit_done = True
        if not self._cfg_bool("master_api.sync_workspace.on_exit", True):
            return
        services = getattr(self, "services", None)
        if services is not None:
            services.sync_workspace_back(reason="exit")

    def protect_files_on(self, new_files: List[str]):
        for f in new_files:
            fpath = os.path.abspath(self.workspace + os.path.sep + f)
            if not os.path.exists(fpath):
                warning(
                    f"File to protect does not exist: {f} in workspace {self.workspace}"
                )
                continue
            resources = getattr(self, "prepared_resources", None)
            if resources is not None:
                resources.permissions.remember([fpath])
            if fpath not in self.cwd_read_only_files:
                info(f"Set file to read-only: {fpath}")
                self.cwd_read_only_files.append(fpath)
        fc.chmode_ro(self.cwd_read_only_files)

    def protect_files_off(self, files: List[str]):
        off_files = []
        for f in files:
            fpath = os.path.abspath(self.workspace + os.path.sep + f)
            if fpath in self.cwd_read_only_files:
                info(f"Set file to read-write: {fpath}")
                off_files.append(fpath)
                self.cwd_read_only_files.remove(fpath)
            else:
                warning(
                    f"File to un-protect not in read-only list: {f} in workspace {self.workspace}"
                )
        if not files:
            info(
                "No files specified to un-protect, restoring all read-only files to read-write"
            )
            fc.chmode_rw(self.cwd_read_only_files)
        else:
            fc.chmode_rw(off_files)


    def get_work_config(self):
        return self.backend.get_work_config()

    def pre_run(self):
        time_start = self._time_start = time.time()
        info(
            "Verify Agent started at: "
            + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time_start))
        )
        info("Seed: " + str(self.seed))
        return self

    @staticmethod
    def _validated_max_stalled_rounds(value):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(
                "loop_settings.max_stalled_rounds must be a non-negative integer"
            )
        return value

    @staticmethod
    def _checker_failure_signature(check_result):
        if not isinstance(check_result, dict):
            return None
        summary = check_result.get("failure_summary")
        if not isinstance(summary, dict):
            return None
        required = (
            "stage_index",
            "stage_name",
            "failed_validation_gate_index",
            "error_code",
            "error",
        )
        if any(summary.get(key) in (None, "", [], {}) for key in required):
            return None
        diagnostic = {key: summary[key] for key in required}
        serialized = json.dumps(
            diagnostic,
            ensure_ascii=True,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _reset_stalled_rounds(self):
        self._stalled_rounds = 0
        self._last_stall_signature = None

    def _update_stalled_rounds(self, previous_revision, previous_stage_index):
        if self._max_stalled_rounds == 0:
            return
        current_revision = getattr(
            self.stage_manager, "validation_revision", previous_revision
        )
        if current_revision == previous_revision:
            return
        current_stage_index = getattr(
            self.stage_manager, "stage_index", previous_stage_index
        )
        check_result = getattr(self.stage_manager, "last_check_info", {})
        if (
            current_stage_index != previous_stage_index
            or check_result.get("check_pass") is True
            or check_result.get("progress_summary")
        ):
            self._reset_stalled_rounds()
            return
        signature = self._checker_failure_signature(check_result)
        if signature is None:
            self._reset_stalled_rounds()
            return
        if signature == self._last_stall_signature:
            self._stalled_rounds += 1
        else:
            self._last_stall_signature = signature
            self._stalled_rounds = 1
        if self._stalled_rounds >= self._max_stalled_rounds:
            summary = check_result["failure_summary"]
            warning(
                "Pausing the agent loop after "
                f"{self._stalled_rounds} rounds with unchanged Checker diagnostic "
                f"{summary['error_code']} in stage {summary['stage_index']} "
                f"({summary['stage_name']})."
            )
            self._need_human = True

    def one_loop(self, msg=None):
        """Enhanced one loop with intelligent interaction logic based on configured mode"""
        service = getattr(self, "multi_agent", None)
        if service is not None:
            instruction = msg if msg is not None else self._continue_msg
            self._continue_msg = None
            service.run_workflow(instruction)
            self.invoke_round += 1
            self._need_human = service.workflow_state == "waiting_human"
            return self
        # Use the configured interaction mode
        if self.interaction_mode == "advanced" and self.advanced_logic:
            try:
                return self.advanced_logic.advanced_one_loop(msg)
            except Exception as e:
                warning(
                    f"Advanced interaction logic failed, falling back to enhanced: {e}"
                )
                # Fall back to enhanced logic if available
                if self.enhanced_logic:
                    try:
                        return self.enhanced_logic.enhanced_one_loop(msg)
                    except Exception as e2:
                        warning(
                            f"Enhanced interaction logic also failed, using standard: {e2}"
                        )
                        # Fall back to standard logic
                        pass
        elif self.interaction_mode == "enhanced" and self.enhanced_logic:
            try:
                return self.enhanced_logic.enhanced_one_loop(msg)
            except Exception as e:
                warning(
                    f"Enhanced interaction logic failed, falling back to standard: {e}"
                )
                # Fall back to standard logic
                pass

        # Standard logic (fallback)
        if msg:
            self.set_continue_msg(msg)
        # one conversation round with retry on tool call error
        while True:
            tips = self.get_current_tips()
            if self.is_exit():
                return
            self.do_work(tips, self.get_work_config())
            if not self._tool__call_error:
                break
            if self.is_break():
                return
        self.invoke_round += 1
        return self

    def custom_chat(self, msg):
        """Run user instructions through the same multi-agent planning loop when enabled."""
        service = getattr(self, "multi_agent", None)
        if service is not None:
            if service.has_active():
                raise RuntimeError("Delegated work is active; pause it before changing the plan")
            service.run_workflow(msg)
            return
        self.do_work({"messages": [self.backend.get_human_message(msg)]}, self.get_work_config())

    def get_interaction_status(self):
        """Get the status of the interaction logic"""
        # Try advanced logic first
        if hasattr(self, "advanced_logic"):
            try:
                status = self.advanced_logic.get_interaction_status()
                status["logic_type"] = "advanced"
                return status
            except:
                pass

        # Fall back to enhanced logic
        if hasattr(self, "enhanced_logic"):
            try:
                status = self.enhanced_logic.get_interaction_status()
                status["logic_type"] = "enhanced"
                return status
            except:
                pass

        return {"status": "No enhanced logic available", "logic_type": "standard"}

    def set_interaction_phase(self, phase: str, sub_phase: str = "initial"):
        """Manually set the interaction phase"""
        # Try advanced logic first
        if hasattr(self, "advanced_logic"):
            try:
                self.advanced_logic.state.transition_to_phase(phase, sub_phase)
                info(f"Advanced interaction phase set to: {phase}.{sub_phase}")
                return
            except:
                pass

        # Fall back to enhanced logic
        if hasattr(self, "enhanced_logic"):
            try:
                self.enhanced_logic.state.transition_to_phase(phase)
                info(f"Enhanced interaction phase set to: {phase}")
                return
            except:
                pass

        warning("No enhanced logic available for phase setting")

    def force_reflection(self):
        """Force a reflection phase in the next loop"""
        # Try both logic systems
        success = False

        if hasattr(self, "advanced_logic"):
            try:
                self.advanced_logic.state.last_reflection_round = 0
                success = True
                info("Advanced logic: Reflection will be triggered in next loop")
            except:
                pass

        if hasattr(self, "enhanced_logic"):
            try:
                self.enhanced_logic.state.last_reflection_round = 0
                success = True
                info("Enhanced logic: Reflection will be triggered in next loop")
            except:
                pass

        if not success:
            warning("No enhanced logic available for reflection forcing")

    def use_advanced_logic(self, enable: bool = True):
        """Enable or disable advanced interaction logic for next loops"""
        self._use_advanced_logic = enable
        if enable:
            info("Advanced interaction logic will be used in subsequent loops")
        else:
            info("Advanced interaction logic disabled, will use enhanced logic")

    def get_performance_summary(self):
        """Get performance summary from advanced logic if available"""
        if hasattr(self, "advanced_logic"):
            try:
                return self.advanced_logic._get_performance_summary()
            except:
                pass
        return "Performance tracking not available"

    def do_work(self, instructions, config):
        """Perform the work using the agent."""
        self._is_work_busy = True
        self._tool__call_error = []
        try:
            if self.stream_output:
                self.do_work_stream(instructions, config)
            else:
                self.do_work_values(instructions, config)
        except Exception as work_error:
            try:
                self.backend.recover_pending_tool_calls(work_error)
            except Exception as recovery_error:
                warning(f"Failed to recover tool call state: {recovery_error}")
            raise
        finally:
            self._is_work_busy = False

    def is_work_busy(self):
        """Check if the agent is currently busy with work."""
        return self._is_work_busy

    def messages_get_raw(self):
        """Get the messages from the agent's state."""
        return self.backend.messages_get_raw()

    def messages_count(self):
        """Get the count of messages in the agent's state."""
        messages = self.messages_get_raw()
        return len(messages)

    def message_info(self):
        """Get information about the messages in the agent's state."""
        messages = self.messages_get_raw()
        return OrderedDict(
            {
                "count": len(messages),
                "size": sum(len(m.text) for m in messages),
                "last_20type": ">".join([m.type for m in messages[-20:]]),
                "to_llm": self.backend.get_statistics(),
            }
        )

    def message_summary(self):
        """Summarize all the messages"""
        if self.message_manage_node is None:
            warning("No message management node available for summarization")
            return
        if not hasattr(self.message_manage_node, "force_summary"):
            warning(
                f"{self.message_manage_node.__class__.__name__} has not function 'force_summary'"
            )
            return
        messages = self.messages_get_raw()
        if not messages:
            return
        self.backend.prepare()
        self.message_manage_node.force_summary(messages)

    def status_info(self):
        messages = self.backend.messages_get_status()
        msg_c = len(messages)
        msg_s = sum(len(message.text) for message in messages)
        msg_stat = self.backend.get_statistics()
        provider_usage_by_source = msg_stat.get("provider_usage", {})
        provider_usage = provider_usage_by_source.get("all", {})
        provider_usage_available = provider_usage.get("responses_with_usage", 0) > 0
        if provider_usage_available:
            usage_status = (
                "partial"
                if provider_usage.get("responses_without_usage", 0) > 0
                else "complete"
            )
            provider_tokens = (
                f"{usage_status} "
                f"{provider_usage.get('input_tokens', 0)}/"
                f"{provider_usage.get('output_tokens', 0)}/"
                f"{provider_usage.get('total_tokens', 0)}"
            )
        else:
            provider_tokens = "unavailable"

        def backend_metric(name):
            metric = getattr(self.backend, name, None)
            if not callable(metric):
                return -1.0
            value = metric()
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            ):
                return float(value)
            return -1.0

        token_speed = backend_metric("token_speed")
        idle = backend_metric("idle")

        context_status = "unavailable"
        compression_status = "none"
        message_node = self.message_manage_node
        if message_node is not None and hasattr(message_node, "get_context_metrics"):
            context_metrics = message_node.get_context_metrics(messages)
            context_status = (
                f"tok={context_metrics['context_tokens_estimated']}/"
                f"{context_metrics['max_tokens']},"
                f"msg={context_metrics['context_message_count']}/"
                f"{context_metrics['max_keep_msgs']}"
            )
            last_compression = context_metrics.get("last_compression")
            if last_compression:
                compression_status = (
                    f"{last_compression.get('reason', 'unknown')} "
                    f"tok={last_compression.get('before_tokens_estimated', '-')}>"
                    f"{last_compression.get('after_tokens_estimated', '-')},"
                    f"msg={last_compression.get('before_messages', '-')}>"
                    f"{last_compression.get('after_messages', '-')}"
                )

        stats = OrderedDict(
            {
                "UCAgent": self.__version__,
                "LLM": self.backend.model_name(),
                "Temperature": self.backend.temperature(),
                "IsBreak": self.is_break(),
                "Stream": self.stream_output,
                "Seed": self.seed,
                "SummaryMode": self.summary_mode(),
                "MessageCount": msg_c,
                "MessageSize": msg_s,
                "Interaction Mode": self.interaction_mode,
                "AI-Message": self.backend._stat_msg_count_ai,
                "Tool-Message": self.backend._stat_msg_count_tool,
                "Sys-Message": self.backend._stat_msg_count_system,
                "ProviderTokens": provider_tokens,
                "Context": context_status,
                "Compression": compression_status,
                "Start Time": fmt_time_stamp(self._time_start),
                "Run Time": fmt_time_deta(self.stage_manager.get_time_cost()),
            }
        )
        stats["Token Speed"] = f"{max(0.0, token_speed):.2f} tok/s"
        stats["Idle"] = f"{max(0.0, idle):.2f} s"
        service = getattr(self, "multi_agent", None)
        if service is not None:
            state = service.status()
            stats["Multi-Agent"] = (f"{state['workflow_state']} / "
                f"workers={state['running']}/{state['max_workers']} / "
                f"plans={state['metrics']['plans']} / starts={state['metrics']['worker_starts']}")
        return stats

    def message_get_str(self, index, count):
        """Render history through the same display policy as live backend messages."""
        messages = self.messages_get_raw()
        if len(messages) == 0:
            warning(f"No messages found, cannot get message. Please try later.")
            return []
        index = index % len(messages)
        formatter = getattr(self.backend, "format_message", lambda message: message.pretty_repr())
        return [formatter(m) for m in messages[index : index + count]]

    def do_work_values(self, instructions, config):
        """Use the managed session when present, retaining the single-Agent entry."""
        if getattr(self, "execution_session", None) is not None:
            return self.execution_session.run_turn(instructions, config)
        return self.backend.do_work_values(instructions, config)

    def do_work_stream(self, instructions, config):
        """Route managed streaming through the same backend lifecycle."""
        if getattr(self, "execution_session", None) is not None:
            return self.execution_session.run_turn(instructions, config, stream=True)
        return self.backend.do_work_stream(instructions, config)

    def get_tool_by_name(self, tool_name: str):
        """Get a tool by its name."""
        tools = self.test_tools
        if getattr(self, "multi_agent", None) is not None:
            from ucagent.core.multi_agent.supervisor import STAGE_OWNER
            if STAGE_OWNER.get() is self.multi_agent.driver:
                tools = self.multi_agent_business_tools
        tool = next((tool for tool in tools if tool.name == tool_name), None)
        return tool

    def set_tool_call_time_out(self, time_out: int):
        """Set the tool call timeout in seconds."""
        if not isinstance(time_out, int) or time_out <= 0:
            raise ValueError("Tool call timeout must be a positive integer")
        for tool in self.test_tools:
            if hasattr(tool, "set_call_time_out"):
                tool.set_call_time_out(time_out)
            else:
                warning(f"Tool {tool.name} does not support setting call timeout")
        info(f"Tool call timeout set to {time_out} seconds")

    def set_tool_block_log_count(self, count: int):
        """Set the maximum blocking-wait log lines spread over one tool call timeout."""
        if not isinstance(count, int) or count <= 0:
            raise ValueError("Tool block log count must be a positive integer")
        for tool in self.test_tools:
            if hasattr(tool, "set_block_log_count"):
                tool.set_block_log_count(count)
        info(f"Tool block log count set to {count}")

    def set_tool_block_log_intervals(self, min_interval: int, max_interval: int = 0):
        """Clamp the blocking-wait log interval, in seconds."""
        if (
            not isinstance(min_interval, int)
            or isinstance(min_interval, bool)
            or min_interval < 1
        ):
            raise ValueError("Tool block log min interval must be a positive integer")
        if (
            not isinstance(max_interval, int)
            or isinstance(max_interval, bool)
            or max_interval < 0
        ):
            raise ValueError("Tool block log max interval must be a non-negative integer")
        if max_interval and max_interval < min_interval:
            raise ValueError(
                "Tool block log max interval must not be below the min interval"
            )
        for tool in self.test_tools:
            if hasattr(tool, "set_block_log_intervals"):
                tool.set_block_log_intervals(min_interval, max_interval)
        info(
            f"Tool block log interval clamped to "
            f"[{min_interval}, {max_interval or 'unlimited'}] seconds"
        )

    def set_one_tool_call_time_out(self, tool_name: str, time_out: int):
        """Set the tool call timeout for a specific tool in seconds."""
        if not isinstance(time_out, int) or time_out <= 0:
            raise ValueError("Tool call timeout must be a positive integer")
        tool = next((tool for tool in self.test_tools if tool.name == tool_name), None)
        if tool is None:
            raise ValueError(f"Tool {tool_name} not found")
        if hasattr(tool, "set_call_time_out"):
            tool.set_call_time_out(time_out)
            info(f"Tool {tool_name} call timeout set to {time_out} seconds")
        else:
            raise ValueError(f"Tool {tool_name} does not support setting call timeout")

    def list_tool_call_time_out(self):
        """List the tool call timeouts for all tools."""
        timeouts = OrderedDict()
        for tool in self.test_tools:
            if hasattr(tool, "get_call_time_out"):
                timeouts[tool.name] = tool.get_call_time_out()
            else:
                timeouts[tool.name] = None
        return timeouts

    def emulate_config(self):
        """Emulate the configuration process.
        Process:
        1. Echo the system prompt.
        2. Echo mission details.
        3. Echo current_tips
        4. Walk through all the stages.
            a. Echo the stage prompt.
            b. Call the 'Complete' tool.
        """
        echo_g("\nStart emulate config:")
        echo_g("="*80)
        echo_g("                First Tips (System Prompt)")
        echo_g(make_llm_tool_ret(self.get_current_tips()))
        echo_g("="*80)
        echo_g(f"               Mission Details (Total stages: {len(self.stage_manager.stages)})")
        # Force reset the stage index to 0
        self.stage_manager.stage_index = 0
        #echo_g(make_llm_tool_ret(self.stage_manager.detail()))
        echo_g("="*80)
        echo_g("                Config walkthrough")
        current_stage = self.stage_manager.get_current_stage()
        while current_stage is not None:
            echo_g(f"   Check Stage: {current_stage.title()}")
            echo_g("    - check stage task desc")
            self.get_current_tips()
            echo_g("    - check stage complete")
            self.stage_manager.complete(self.cfg.get_value("call_time_out", 300))
            current_stage = self.stage_manager.next_stage()
        echo_g("\n" + "="*80)
        echo_g("                Config walkthrough completed successfully!")
        echo_g("="*80)
