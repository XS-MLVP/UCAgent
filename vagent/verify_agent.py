# -*- coding: utf-8 -*-

from .util.config import get_config
from .util.log import info, message, warning, error, msg_msg
from .util.functions import fmt_time_deta, get_template_path, render_template_dir, import_and_instance_tools
from .util.functions import fill_dlist_none, dump_as_json, get_ai_message_tool_call, yam_str
from .util.functions import start_verify_mcps, create_verify_mcps, stop_verify_mcps, rm_workspace_prefix
from .util.models import get_chat_model

import vagent.tools
from .tools import *
from .tools.planning import CreatePlan, UpdatePlan, GetPlan, ListPlans
from .stage import StageManager
from .verify_pdb import VerifyPDB
from .interaction import EnhancedInteractionLogic, AdvancedInteractionLogic
from .version import __version__

import time
import random
import signal
import copy

from langchain.globals import set_debug
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langmem.short_term import SummarizationNode
from langgraph.prebuilt.chat_agent_executor import AgentState
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel
import traceback


class SummarizationAndFixToolCall(SummarizationNode):
    """Custom summarization node that fixes tool call arguments."""

    def _func(self, input: Union[Dict[str, Any], BaseModel]) -> Dict[str, Any]:
        for msg in input["messages"][-4:]:
            if not isinstance(msg, AIMessage):
                continue
            if hasattr(msg, "additional_kwargs"):
                msg.additional_kwargs = fill_dlist_none(msg.additional_kwargs, '{}', "arguments", ["arguments"])
            if hasattr(msg, "invalid_tool_calls"):
                msg.invalid_tool_calls = fill_dlist_none(msg.invalid_tool_calls, '{}', "args", ["args"])
        return super()._func(input)


class State(AgentState):
    """Agent state with additional context information."""
    # NOTE: we're adding this key to keep track of previous summary information
    # to make sure we're not summarizing on every LLM call
    context: Dict[str, Any]


class VerifyAgent:
    """AI-powered hardware verification agent for chip design testing."""

    def __init__(self,
                 workspace: str,
                 dut_name: str,
                 output: str,
                 config_file: Optional[str] = None,
                 cfg_override: Optional[Dict[str, Any]] = None,
                 tmp_overwrite: bool = False,
                 template_dir: Optional[str] = None,
                 stream_output: bool = False,
                 init_cmd: Optional[List[str]] = None,
                 seed: Optional[int] = None,
                 sys_tips: str = "",
                 model = None,  # ChatOpenAI type from langchain_openai
                 ex_tools: Optional[List[str]] = None,
                 thread_id: Optional[int] = None,
                 debug: bool = False,
                 no_embed_tools: bool = False,
                 force_stage_index: int = 0,
                 no_write_targets: Optional[List[str]] = None,
                 interaction_mode: str = "standard",
                 gen_instruct_file: Optional[str] = None,
                 ):
        """Initialize the Verify Agent with configuration and an optional agent.

        Args:
            workspace (str): The workspace directory where the agent will operate.
            dut_name (str): The name of the device under test (DUT).
            output (str): The output directory for the agent's results.
            config_file (str, optional): Path to the configuration file. Defaults to None.
            cfg_override (dict, optional): Dictionary to override configuration settings. Defaults to None.
            tmp_overwrite (bool, optional): Whether to overwrite existing templates in the workspace. Defaults to False.
            template_dir (str, optional): Path to the template directory. Defaults to None.
            stream_output (bool, optional): Whether to stream output to the console. Defaults to False.
            init_cmd (list, optional): Initial commands to run in the agent. Defaults to None.
            seed (int, optional): Seed for random number generation. Defaults to None.
            sys_tips (str, optional): Set of system tips to be used in the agent.
                                      Defaults to an empty string.
            model (ChatOpenAI, optional): An instance of ChatOpenAI to use as the agent model.
                                          If None, a default model will be created using the configuration.
                                          Defaults to None.
            ex_tools (list, optional): List of external tools class to be used by the agent, e.g., `--ex-tools SqThink`.
                                       Defaults to None.
            thread_id (int, optional): Thread ID for the agent. If None, a random ID will be generated.
                                       Defaults to None.
            debug (bool, optional): Whether to enable debug mode. Defaults to False.
            no_embed_tools (bool, optional): Whether to disable embedded tools. Defaults to False.
            force_stage_index (int, optional): Force starting from a specific stage index. Defaults to 0.
            no_write_targets (list, optional): List of files/directories that cannot be written to. Defaults to None.
            interaction_mode (str, optional): Interaction mode - 'standard', 'enhanced', or 'advanced'. Defaults to 'standard'.
        """
        self.__version__ = __version__
        if debug:
            set_debug(True)
        self.cfg = get_config(config_file, cfg_override)
        temp_args = {
            "OUT": output,
            "DUT": dut_name
        }
        self.cfg.update_template(temp_args)
        template_overwrite = self.cfg.template_overwrite.as_dict()
        self.cfg.update_template(template_overwrite)
        self.cfg.un_freeze()
        self.cfg.seed = seed if seed is not None else random.randint(1, 999999)
        self.cfg._temp_cfg = temp_args
        self.cfg.freeze()
        self.workspace = os.path.abspath(workspace)
        self.output_dir = os.path.join(self.workspace, output)
        # copy doc/Guide_Doc to workspace
        guide_doc_path = os.path.join(self.workspace, "Guide_Doc")
        if not os.path.exists(guide_doc_path):
            doc_guide_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lang", self.cfg.lang, "doc", "Guide_Doc")
            shutil.copytree(doc_guide_path, guide_doc_path)
        self.thread_id = thread_id if thread_id is not None else random.randint(100000, 999999)
        self.dut_name = dut_name
        self.seed = seed if seed is not None else random.randint(1, 999999)
        if model is not None:
            self.model = model
        else:
            self.model = get_chat_model(self.cfg)
        self.template = get_template_path(self.cfg.template, self.cfg.lang, template_dir)
        self.render_template(tmp_overwrite=tmp_overwrite)
        self.tool_read_text = ReadTextFile(self.workspace)
        self.stage_manager = StageManager(self.workspace, self.cfg, self, self.tool_read_text, force_stage_index)
        self._default_system_prompt = sys_tips if sys_tips else self.get_default_system_prompt()
        self.tool_list_base = [
            self.tool_read_text,
            RoleInfo(self._default_system_prompt)
        ]
        if not no_embed_tools:
            self.tool_reference = SemanticSearchInGuidDoc(self.cfg.embed, workspace=self.workspace, doc_path="Guide_Doc")
            self.tool_memory_put = MemoryPut().set_store(self.cfg.embed)
            self.tool_memory_get = MemoryGet().set_store(store=self.tool_memory_put.get_store())
            self.tool_list_base += [
                self.tool_reference,
                self.tool_memory_put,
                self.tool_memory_get,
            ]
        if no_write_targets is not None:
            assert isinstance(no_write_targets, list), "no_write_targets must be a list of directories or files"
            for f in no_write_targets:
                abs_f = os.path.abspath(f)
                assert os.path.exists(abs_f), f"Specified no-write target {abs_f} does not exist"
                assert abs_f.startswith(os.path.abspath(self.workspace)), \
                    f"Specified no-write target {abs_f} must be under the workspace {self.workspace}"
                self.cfg.un_write_dirs.append(rm_workspace_prefix(self.workspace, abs_f))
        self.tool_list_file = [
                           # Directory and file listing tools
                           PathList(self.workspace),
                           GetFileInfo(self.workspace),
                           # File reading tools
                           ReadBinFile(self.workspace),
                           # File searching tools
                           SearchText(self.workspace),
                           FindFiles(self.workspace),
                           # File writing and editing tools (require permissions)
                           DeleteFile(self.workspace,               write_dirs=self.cfg.write_dirs, un_write_dirs=self.cfg.un_write_dirs),
                           EditTextFile(self.workspace,             write_dirs=self.cfg.write_dirs, un_write_dirs=self.cfg.un_write_dirs),
                           ReplaceStringInFile(self.workspace,      write_dirs=self.cfg.write_dirs, un_write_dirs=self.cfg.un_write_dirs),
                           # File management tools (require permissions)
                           CopyFile(self.workspace,                 write_dirs=self.cfg.write_dirs, un_write_dirs=self.cfg.un_write_dirs),
                           MoveFile(self.workspace,                 write_dirs=self.cfg.write_dirs, un_write_dirs=self.cfg.un_write_dirs),
                           CreateDirectory(self.workspace,          write_dirs=self.cfg.write_dirs, un_write_dirs=self.cfg.un_write_dirs),
        ]
        self.tool_list_task = self.stage_manager.new_tools()
        self.tool_list_ext = import_and_instance_tools(self.cfg.get_value("ex_tools", []), vagent.tools) \
                           + import_and_instance_tools(ex_tools, vagent.tools)
        
        # Initialize planning tools
        self.planning_tools = []
        if interaction_mode == "standard":
            info(f"There are no planning tools in standard mode")
        else:
            self.planning_tools = [
                CreatePlan(),
                UpdatePlan(),
                GetPlan(),
                ListPlans()
            ]
        # Share the same plan storage across all planning tools
        for i, tool in enumerate(self.planning_tools):
            if i > 0:  # Share storage from the first tool
                tool._plans = self.planning_tools[0]._plans
                tool._current_plan_id = self.planning_tools[0]._current_plan_id
        
        self.test_tools = self.tool_list_base + self.tool_list_file + self.tool_list_task + self.tool_list_ext + self.planning_tools

        summarization_node = SummarizationAndFixToolCall(
            token_counter=count_tokens_approximately,
            model=self.model,
            max_tokens=self.cfg.get_value("conversation_summary.max_tokens", 20*1024),
            max_summary_tokens=self.cfg.get_value("conversation_summary.max_summary_tokens", 1*1024),
        )

        self.agent = create_react_agent(
            model=self.model,
            tools=self.test_tools,
            checkpointer=MemorySaver(),
            pre_model_hook=summarization_node,
            state_schema=State,
        )
        self.message_echo_handler = None
        self.update_handler = None
        self._time_start = time.time()
        self._time_end = None
        # state
        self._msg_buffer = ""
        self._system_message = self._default_system_prompt
        self._stat_msg_count_ai = 0
        self._stat_msg_count_tool = 0
        self._stat_msg_count_system = 0
        # flags
        self.stream_output = stream_output
        self.invoke_round = 0
        self._tool__call_error = []
        self._is_exit = False
        self._tip_index = 0
        self._need_break = False
        self._force_trace = False
        self._continue_msg = None
        self._mcps = None
        self._mcps_logger = None
        self.original_sigint = signal.getsignal(signal.SIGINT)
        self._sigint_count = 0
        self.handle_sigint()
        
        # Initialize interaction logic based on mode
        self.interaction_mode = interaction_mode
        self.enhanced_logic = None
        self.advanced_logic = None
        
        if interaction_mode == "enhanced":
            self.enhanced_logic = EnhancedInteractionLogic(self)
            info("Using enhanced interaction mode with planning and memory management")
        elif interaction_mode == "advanced":
            self.advanced_logic = AdvancedInteractionLogic(self)
            info("Using advanced interaction mode with adaptive strategies")
        else:
            info("Using standard interaction mode")
        self.generate_instruction_file(gen_instruct_file)
        self.pdb = VerifyPDB(self, init_cmd=init_cmd)

    def generate_instruction_file(self, file_path):
        if not file_path:
            return
        if file_path.startswith(os.sep):
            file_path = file_path[1:]
        file_path = os.path.abspath(os.path.join(self.workspace, file_path))
        dut_readme = os.path.join(self.workspace, self.dut_name, "README.md")
        with open(file_path, "w", encoding="utf-8") as f:
            if os.path.exists(dut_readme):
                f.write("# Goal Description\n")
                with open(dut_readme, "r", encoding="utf-8") as df:
                    f.write(df.read() + "\n")
            f.write("# Verification Instruction\n")
            f.write(self._default_system_prompt + "\n")

    def render_template(self, tmp_overwrite=False):
        if self.template is not None:
            tmp_dir = os.path.join(self.workspace, os.path.basename(self.template))
            info(f"Rendering template from {self.template} to {tmp_dir}")
            if not os.path.exists(tmp_dir) or tmp_overwrite:
                try:
                    render_template_dir(self.workspace, self.template, {"DUT": self.dut_name})
                except Exception as e:
                    debug(traceback.format_exc())
                    error(f"Failed to render template from {self.template} to {tmp_dir}: {e}")
                    raise e

    def start_mcps(self, no_file_ops=False, host="127.0.0.1", port=5000):
        tools = self.tool_list_base + self.tool_list_task + self.tool_list_ext
        if not no_file_ops:
            tools += self.tool_list_file
        self.cfg.update_template({
            "TOOLS": ", ".join([t.name for t in tools]),
        })
        self._mcps, glogger = create_verify_mcps(tools, host=host, port=port, logger=self._mcps_logger)
        info("Init Prompt:\n" + self.cfg.mcp_server.init_prompt)
        start_verify_mcps(self._mcps, glogger)
        self._mcps = None

    def stop_mcps(self):
        """Stop the MCPs server if it is running."""
        stop_verify_mcps(self._mcps)

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
            self.message_echo_handler(msg, end)
            if msg:
                self._msg_buffer = self._msg_buffer + msg + end
            if end == "\n":
                msg_msg(self._msg_buffer)
                self._msg_buffer = ""
        else:
            message(msg, end=end)

    def handle_sigint(self):
        def _sigint_handler(s, f):
            self._sigint_count += 1
            if self._sigint_count > 4:
                return self.original_sigint(s, f)
            if self._sigint_count > 3:
                info("SIGINT received again, exiting...")
                self.exit()
                return
            if self._sigint_count > 1:
                #self.original_sigint(s, f)
                info("SIGINT received again, more times will exit directly")
                return
            info("SIGINT received")
            self.set_break(True)
        signal.signal(signal.SIGINT, _sigint_handler)

    def set_force_trace(self, value):
        self._force_trace = value

    def check_pdb_trace(self):
        if self._force_trace:
            self.pdb.set_trace()
        elif self.is_break():
            self.pdb.set_trace()

    def set_break(self, value=True):
        self._need_break = value
        if value and self._mcps is not None:
            self.stop_mcps()

    def is_break(self):
        return self._need_break

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
            msg.append(SystemMessage(content=copy.copy(self._system_message)))
            self._system_message = None
        msg.append(HumanMessage(content=tips))
        return {"messages": msg}

    def set_system_message(self, msg: str):
        self._system_message = msg

    def get_system_message(self):
        """Get the current system message for the agent."""
        return self._system_message

    def get_default_system_prompt(self):
        """Get the default system prompt for the agent."""
        return self.cfg.mission.prompt.get_value("system", "").strip()

    def set_continue_msg(self, msg: str):
        """Set the continue message for the agent."""
        if not isinstance(msg, str):
            raise ValueError("Continue message must be a string")
        try:
            msg.encode("utf-8").decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("Continue message must be a valid UTF-8 string")
        self._continue_msg = msg

    def is_exit(self):
        if self._is_exit:
            info("Verify Agent is exited.")
        return self._is_exit

    def exit(self):
        self._is_exit = True

    def get_work_config(self):
        return {"configurable": {"thread_id": f"{self.thread_id}"},
                "recursion_limit": self.cfg.get_value("recursion_limit", 100000),
                }

    def run(self):
        self.pre_run()
        self.run_loop()

    def pre_run(self):
        time_start = self._time_start = time.time()
        info("Verify Agent started at: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time_start)))
        info("Seed: " + str(self.seed))
        self.check_pdb_trace()
        return self

    def run_loop(self, with_break=False, msg=None):
        if msg:
            self.set_continue_msg(msg)
        # conversation loop
        while not self.is_exit():
            self.one_loop()
            if self.is_exit():
                break
            if with_break:
                if self.is_break():
                    info("Break at loop: " + str(self.invoke_round))
                    return
            self.check_pdb_trace()
        time_end = self._time_end = time.time()
        info("Verify Agent finished at: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time_end)))
        info(f"Total time taken: {fmt_time_deta(time_end - self._time_start)}")
        return self

    def one_loop(self, msg=None):
        """Enhanced one loop with intelligent interaction logic based on configured mode"""
        # Use the configured interaction mode
        if self.interaction_mode == "advanced" and self.advanced_logic:
            try:
                return self.advanced_logic.advanced_one_loop(msg)
            except Exception as e:
                warning(f"Advanced interaction logic failed, falling back to enhanced: {e}")
                # Fall back to enhanced logic if available
                if self.enhanced_logic:
                    try:
                        return self.enhanced_logic.enhanced_one_loop(msg)
                    except Exception as e2:
                        warning(f"Enhanced interaction logic also failed, using standard: {e2}")
                        # Fall back to standard logic
                        pass
        elif self.interaction_mode == "enhanced" and self.enhanced_logic:
            try:
                return self.enhanced_logic.enhanced_one_loop(msg)
            except Exception as e:
                warning(f"Enhanced interaction logic failed, falling back to standard: {e}")
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

    def get_interaction_status(self):
        """Get the status of the interaction logic"""
        # Try advanced logic first
        if hasattr(self, 'advanced_logic'):
            try:
                status = self.advanced_logic.get_interaction_status()
                status['logic_type'] = 'advanced'
                return status
            except:
                pass
        
        # Fall back to enhanced logic
        if hasattr(self, 'enhanced_logic'):
            try:
                status = self.enhanced_logic.get_interaction_status()
                status['logic_type'] = 'enhanced'
                return status
            except:
                pass
        
        return {"status": "No enhanced logic available", "logic_type": "standard"}
    
    def set_interaction_phase(self, phase: str, sub_phase: str = "initial"):
        """Manually set the interaction phase"""
        # Try advanced logic first
        if hasattr(self, 'advanced_logic'):
            try:
                self.advanced_logic.state.transition_to_phase(phase, sub_phase)
                info(f"Advanced interaction phase set to: {phase}.{sub_phase}")
                return
            except:
                pass
        
        # Fall back to enhanced logic
        if hasattr(self, 'enhanced_logic'):
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
        
        if hasattr(self, 'advanced_logic'):
            try:
                self.advanced_logic.state.last_reflection_round = 0
                success = True
                info("Advanced logic: Reflection will be triggered in next loop")
            except:
                pass
        
        if hasattr(self, 'enhanced_logic'):
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
        if hasattr(self, 'advanced_logic'):
            try:
                return self.advanced_logic._get_performance_summary()
            except:
                pass
        return "Performance tracking not available"
    
    def get_current_plan(self):
        """Get the current plan information"""
        if hasattr(self, 'planning_tools') and self.planning_tools:
            try:
                return self.planning_tools[2]._run()  # GetPlan tool
            except Exception as e:
                warning(f"Failed to get current plan: {e}")
        return "No planning tools available"

    def do_work(self, instructions, config):
        """Perform the work using the agent."""
        self._tool__call_error = []
        if self.stream_output:
            self.do_work_stream(instructions, config)
        else:
            self.do_work_values(instructions, config)

    def state_record_mesg(self, msg):
        if isinstance(msg, AIMessage):
            self._stat_msg_count_ai += 1
        elif isinstance(msg, ToolMessage):
            self._stat_msg_count_tool += 1
        elif isinstance(msg, SystemMessage):
            self._stat_msg_count_system += 1

    def messages_get_raw(self):
        """Get the messages from the agent's state."""
        values = self.agent.get_state(self.get_work_config()).values
        if "messages" not in values:
            warning("No messages found in agent state")
            return []
        return values["messages"]

    def message_info(self):
        """Get information about the messages in the agent's state."""
        messages = self.messages_get_raw()
        return {
            "count": len(messages),
            "size": sum([len(m.content) for m in messages]),
        }

    def message_get_str(self, index, count):
        values = self.agent.get_state(self.get_work_config()).values
        if "messages" not in values:
            warning(f"No messages found, cannot get message")
            return []
        index = index % len(values["messages"])
        return [m.pretty_repr() for m in values["messages"][index:index+count]]

    def message_keep_latest(self, latest_size):
        # FIXME: Unable to delete messages in langgraph agent state
        values = self.agent.get_state(self.get_work_config()).values
        if "messages" not in values:
            warning(f"No messages found, cannot keep latest messages")
            return
        info(f"Latest keeping messages with size {latest_size}, total messages before: {len(values['messages'])}")
        self.agent.get_state(self.get_work_config()).values["messages"][:] = values["messages"][-latest_size:]
        info(f"Messages after keeping: {len(values['messages'])}")

    def do_work_values(self, instructions, config):
        last_msg_index = None
        for _, step in self.agent.stream(instructions, config, stream_mode=["values"]):
            if self._need_break:
                break
            index = len(step["messages"])
            if index == last_msg_index:
                continue
            last_msg_index = index
            msg = step["messages"][-1]
            self.check_tool_call_error(msg)
            self.state_record_mesg(msg)
            self.message_echo(msg.pretty_repr())

    def do_work_stream(self, instructions, config):
        last_msg_index = None
        fist_ai_message = True
        for v, data in self.agent.stream(instructions, config, stream_mode=["values", "messages"]):
            if self._need_break:
                    break
            if v == "messages":
                if fist_ai_message:
                    fist_ai_message = False
                    self.message_echo("\n\n================================== AI Message ==================================")
                msg = data[0]
                self.message_echo(msg.content, end="")
            else:
                index = len(data["messages"])
                if index == last_msg_index:
                    continue
                last_msg_index = index
                msg = data["messages"][-1]
                self.state_record_mesg(msg)
                if isinstance(msg, AIMessage):
                    self.message_echo(get_ai_message_tool_call(msg))
                    self.check_tool_call_error(msg)
                    continue
                self.message_echo("\n"+msg.pretty_repr())

    def check_tool_call_error(self, msg):
        if not isinstance(msg, AIMessage):
            return
        if not hasattr(msg, "invalid_tool_calls"):
            return
        if len(msg.invalid_tool_calls) < 1:
            return
        for call in msg.invalid_tool_calls:
            name = call.get("name")
            tool = next((tool for tool in self.test_tools if tool.name == name), None)
            args = call.get("args") or {}
            status = "success"
            try:
                assert tool is not None, f"Tool {name} not found"
                result = tool._run(*(), **args)
            except Exception as e:
               error(f"Error executing tool {call}: {e}")
               result = str(e)
               status = "error"
            if not isinstance(result, str):
                result = dump_as_json(result)
            self._tool__call_error.append(ToolMessage(
                content=result,
                tool_call_id=call["id"],
                name=name,
                status=status
            ))
        warning(f"Tool call error: {msg.invalid_tool_calls}, have re-called them in custom way")
