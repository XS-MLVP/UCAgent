"""Construct Agent-owned stages, tools and backends without depending on application startup."""

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import copy
import os
import random
import time

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

import ucagent.core.tools
import ucagent.util.functions as fc
from ucagent.core.backends import get_backend
from ucagent.core.agent.configuration import resolve_task_configuration
from ucagent.core.workspace.assets import prepare_resources
from ucagent.core.workspace.permissions import apply_file_protection
from ucagent.core.interaction import EnhancedInteractionLogic, AdvancedInteractionLogic
from ucagent.core.plugins import (
    PluginContext, create_plugin_checker_registry, create_plugin_manager_tools_registry,
    create_plugin_runtime_hooks, create_plugin_tools,
)
from ucagent.core.stage import StageManager
from ucagent.core.tools import (
    ReadTextFile, PathList, SearchText, RoleInfo, SemanticSearchInGuidDoc,
    MemoryPut, MemoryGet, GetFileInfo, FindFiles, DeleteFile, EditTextFile,
    DeleteTextLines, ReplaceStringInFile, CopyFile, MoveFile, CreateDirectory,
    WorkDiff, WorkCommit, RunBashCommand, RunSkillScript,
)
from ucagent.core.tools.context import ArbitContextSummary
from ucagent.core.tools.planning import (
    ToDoPanel, CreateToDo, CompleteToDoSteps, UndoToDoSteps, ResetToDo,
    GetToDoSummary, ToDoState,
)
from ucagent.core.tools.skill import ListSkill
from ucagent.util.functions import import_and_instance_tools
from ucagent.util.log import info, warning
from ucagent.version import __version__



def initialize_agent(agent, parameters):
    """Use the same task preparation for CLI and direct construction, cleaning failures."""
    options = SimpleNamespace(**parameters)
    agent._startup_cleanup = ExitStack()
    try:
        history = prepare_task(agent, options)
        assemble_stage_tools(agent, options, history)
        assemble_tools(agent, options)
        initialize_execution(agent, options)
        agent.generate_instruction_file(options.gen_instruct_file)
        assemble_backend(agent, options)
    except BaseException:
        agent._startup_cleanup.close()
        raise


def prepare_task(agent, options):
    """Resolve task resources and history before constructing stage or tool instances."""
    saved_info = {}
    if not options.no_history:
        saved_info = fc.load_ucagent_info(options.workspace)
    force_stage_index_explicit = options.force_stage_index != 0
    if options.force_stage_index == 0:
        options.force_stage_index = saved_info.get('stage_index', options.force_stage_index)
        if options.force_stage_index > 0:
            warning(f'Resuming from saved stage index: {options.force_stage_index}')
    agent.workspace = os.path.abspath(options.workspace)
    agent.__version__ = __version__
    agent.config_file = '' if options.config_file is None else str(options.config_file)
    agent.workflow_config_file = '' if options.workflow_config_file is None else str(options.workflow_config_file)
    agent.plugin_workflow = '' if options.plugin_workflow is None else str(options.plugin_workflow)
    agent.template_target = options.template_target
    saved_meta = saved_info.get('meta') if isinstance(saved_info.get('meta'), dict) else {}
    agent.meta = copy.deepcopy(saved_meta)
    if options.meta:
        agent.meta.update(copy.deepcopy(options.meta))
        updated_info = copy.deepcopy(saved_info)
        updated_info['meta'] = copy.deepcopy(agent.meta)
        fc.save_ucagent_info(agent.workspace, updated_info)
    prepared = options._task_configuration or resolve_task_configuration(
        options.workspace, options.dut_name, options.output, options.config_file,
        options.cfg_override, plugins=options.plugins,
        workflow_config_file=options.workflow_config_file, plugin_workflow=options.plugin_workflow,
        plugin_guide_doc_paths=options.plugin_guide_doc_paths, plugin_skill_paths=options.plugin_skill_paths,
        template_dir=options.template_dir, template_target=options.template_target,
        template_context_factory=options.template_context_factory,
        plugin_runtime_config_keys=options.plugin_runtime_config_keys, seed=options.seed,
    )
    agent.cfg = prepared.cfg
    agent.plugins = list(prepared.plugins)
    agent.workflow_config_file = prepared.workflow_config_file or ''
    agent.plugin_workflow = prepared.plugin_workflow or ''
    agent.template_target = prepared.template_target
    agent.workflow_template_context = prepared.template_context
    agent.plugin_checker_registry = create_plugin_checker_registry(agent.plugins)
    agent.plugin_manager_tool_registry = create_plugin_manager_tools_registry(agent.plugins)
    agent.plugin_runtime_hooks = create_plugin_runtime_hooks(agent.plugins)
    plugin_python_import_roots = [
        str(import_root)
        for loaded in agent.plugins
        for import_root in (
            (loaded.python_import_root, *loaded.extra_python_import_roots)
            if loaded.python_import_root is not None else loaded.extra_python_import_roots
        )
    ]
    resources = prepare_resources(
        prepared, runtime_hooks=agent.plugin_runtime_hooks,
        plugin_python_import_roots=plugin_python_import_roots, config_file=agent.config_file,
        guid_doc_path=options.guid_doc_path, template_cfg=options.template_cfg,
        tmp_overwrite=options.tmp_overwrite,
    )
    agent.prepared_resources = resources
    agent._startup_cleanup.callback(resources.permissions.restore)
    agent.runtime_config_path = resources.runtime_config_path
    agent.output_dir = resources.output_dir
    agent.template = resources.template
    return (saved_info, force_stage_index_explicit, plugin_python_import_roots)


def assemble_stage_tools(agent, options, history):
    """Bind stage history and inspection tools after workflow resources are available."""
    saved_info, force_stage_index_explicit, plugin_python_import_roots = history
    agent.tool_skill = []
    if agent.cfg.skill.use_skill:
        agent.tool_skill = [ListSkill(agent.workspace).bind(agent), RunSkillScript(agent.workspace).bind(agent)]
    agent.thread_id = options.thread_id if options.thread_id is not None else random.randint(100000, 999999)
    agent.dut_name = options.dut_name
    agent.seed = agent.cfg.seed
    agent.tool_read_text = ReadTextFile(agent.workspace)
    agent.tool_list_dir = PathList(agent.workspace)
    agent.tool_search_text = SearchText(agent.workspace)
    agent.todo_panel = ToDoPanel()
    agent.stage_manager = StageManager(
        agent.workspace,
        agent.cfg,
        agent,
        agent.tool_read_text,
        saved_info,
        options.force_stage_index,
        force_stage_index_explicit=force_stage_index_explicit,
        force_todo=options.force_todo,
        todo_panel=agent.todo_panel,
        stage_skip_list=options.stage_skip_list,
        stage_unskip_list=options.stage_unskip_list,
        tool_inspect_file=[
            agent.tool_read_text,
            agent.tool_list_dir,
            agent.tool_search_text,
        ],
        reference_files=options.reference_files,
        checker_registry=agent.plugin_checker_registry,
        test_python_import_roots=plugin_python_import_roots,
        manager_tool_registry=agent.plugin_manager_tool_registry,
        runtime_hooks=agent.plugin_runtime_hooks,
    )
    agent._default_system_prompt = options.sys_tips if options.sys_tips else agent.get_default_system_prompt()
    agent.tool_list_base = [agent.tool_read_text, RoleInfo(agent._default_system_prompt)]
    if not options.no_embed_tools:
        agent.tool_reference = SemanticSearchInGuidDoc(agent.cfg.embed, workspace=agent.workspace, doc_path='Guide_Doc')
        agent.tool_memory_put = MemoryPut().set_store(agent.cfg.embed)
        agent.tool_memory_get = MemoryGet().set_store(store=agent.tool_memory_put.get_store())
        agent.tool_list_base += [agent.tool_reference, agent.tool_memory_put, agent.tool_memory_get]
    agent.cwd_read_only_files = apply_file_protection(agent.cfg, agent.workspace, options.no_write_targets, agent.prepared_resources.permissions)


def assemble_tools(agent, options):
    """Assemble plugin, file, task and planning tools under the resolved file policy."""
    agent.tool_list_plugin = create_plugin_tools(agent.plugins, PluginContext(workspace=Path(agent.workspace), output_dir=os.path.relpath(agent.output_dir, agent.workspace), write_dirs=tuple(agent.cfg.write_dirs), un_write_dirs=tuple(agent.cfg.un_write_dirs), cfg=agent.cfg, plugin_root=Path(agent.workspace), dut_name=agent.dut_name))
    agent.tool_waveinfo = next((tool for tool in agent.tool_list_plugin if getattr(tool, 'name', '') == 'WaveInfo'), None)
    heading_companions = tuple(agent.cfg.get_value('markdown.heading_companions', []))
    agent.tool_list_file = [
        # Directory and file listing tools
        agent.tool_list_dir,
        GetFileInfo(agent.workspace),
        # File reading tools
        # ReadBinFile(agent.workspace), # ignore Binary file read
        # File searching tools
        agent.tool_search_text,
        FindFiles(agent.workspace),
        # File writing and editing tools (require permissions)
        DeleteFile(
            agent.workspace,
            write_dirs=agent.cfg.write_dirs,
            un_write_dirs=agent.cfg.un_write_dirs,
        ),
        EditTextFile(
            agent.workspace,
            write_dirs=agent.cfg.write_dirs,
            un_write_dirs=agent.cfg.un_write_dirs,
            heading_companions=heading_companions,
        ),
        DeleteTextLines(
            agent.workspace,
            write_dirs=agent.cfg.write_dirs,
            un_write_dirs=agent.cfg.un_write_dirs,
            heading_companions=heading_companions,
        ),
        ReplaceStringInFile(
            agent.workspace,
            write_dirs=agent.cfg.write_dirs,
            un_write_dirs=agent.cfg.un_write_dirs,
            heading_companions=heading_companions,
        ),
        # File management tools (require permissions)
        CopyFile(
            agent.workspace,
            write_dirs=agent.cfg.write_dirs,
            un_write_dirs=agent.cfg.un_write_dirs,
        ),
        MoveFile(
            agent.workspace,
            write_dirs=agent.cfg.write_dirs,
            un_write_dirs=agent.cfg.un_write_dirs,
        ),
        CreateDirectory(
            agent.workspace,
            write_dirs=agent.cfg.write_dirs,
            un_write_dirs=agent.cfg.un_write_dirs,
        ),
        # Workspace git management tools
        WorkDiff(agent.workspace),
        WorkCommit(agent.workspace),
        # bash tool
        RunBashCommand(agent.workspace),
    ]
    agent.tool_list_task = agent.stage_manager.new_tools()
    agent.tool_list_ext = import_and_instance_tools(agent.cfg.get_value('ex_tools', []), ucagent.core.tools) + import_and_instance_tools(options.ex_tools, ucagent.core.tools) + agent.tool_skill
    non_plugin_tools = agent.tool_list_base + agent.tool_list_file + agent.tool_list_task + agent.tool_list_ext
    non_plugin_names = {tool.name for tool in non_plugin_tools}
    conflicting_plugin_names = sorted((tool.name for tool in agent.tool_list_plugin if tool.name in non_plugin_names))
    if conflicting_plugin_names:
        raise ValueError(f'Plugin tool names conflict with registered UCAgent tools: {conflicting_plugin_names}')
    os.environ['UCAGENT_WORKSPACE'] = agent.workspace
    agent.planning_tools = []
    agent.force_todo = options.force_todo
    if options.interaction_mode == 'standard' and options.force_todo or options.use_todo_tools:
        agent.planning_tools = [CreateToDo(agent.todo_panel), CompleteToDoSteps(agent.todo_panel), UndoToDoSteps(agent.todo_panel), ResetToDo(agent.todo_panel), GetToDoSummary(agent.todo_panel), ToDoState(agent.todo_panel)]


def initialize_execution(agent, options):
    """Initialize task execution state and interaction strategy before backend binding."""
    agent.max_token = agent.cfg.get_value('conversation_summary.max_tokens', 20 * 1024)
    agent.max_summary_tokens = agent.cfg.get_value('conversation_summary.max_summary_tokens', 8 * 1024)
    agent.context_management_strategy = agent.cfg.get_value('conversation_summary.context_management_strategy', 'TrimAndSummaryMiddleware')
    agent.max_keep_msgs = agent.cfg.get_value('conversation_summary.max_keep_msgs', 200)
    agent.tail_keep_msgs = agent.cfg.get_value('conversation_summary.tail_keep_msgs', 20)
    agent.message_echo_handler = None
    agent.update_handler = None
    agent._time_start = time.time()
    agent._time_end = None
    agent._msg_buffer = ''
    agent._system_message = agent._default_system_prompt
    agent.stream_output = options.stream_output
    agent.invoke_round = 0
    agent._tool__call_error = []
    agent._is_exit = False
    agent._sync_workspace_back_on_exit_done = False
    agent._tip_index = 0
    agent._need_break = False
    agent._need_human = False
    agent._max_stalled_rounds = agent._validated_max_stalled_rounds(agent.cfg.get_value('loop_settings.max_stalled_rounds', 0))
    agent._stalled_rounds = 0
    agent._last_stall_signature = None
    agent._continue_msg = None
    agent._mcps_logger = None
    agent._exit_on_completion = options.exit_on_completion
    agent._is_work_busy = False
    agent.interaction_mode = options.interaction_mode
    agent.enhanced_logic = None
    agent.advanced_logic = None
    if options.interaction_mode == 'enhanced':
        agent.enhanced_logic = EnhancedInteractionLogic(agent)
        info('Using enhanced interaction mode with planning and memory management')
    elif options.interaction_mode == 'advanced':
        agent.advanced_logic = AdvancedInteractionLogic(agent)
        info('Using advanced interaction mode with adaptive strategies')
    else:
        info('Using standard interaction mode')


def assemble_backend(agent, options):
    """Bind the backend and context tools before initializing the active stage and telemetry."""
    agent.backend = get_backend(agent, agent.cfg)
    agent._startup_cleanup.callback(agent.backend.exit)
    agent.message_manage_node = agent.backend.get_message_manage_node()
    agent.context_tools = []
    if options.enable_context_manage_tools:
        if agent.message_manage_node is not None:
            agent.context_tools = [ArbitContextSummary().bind(agent.message_manage_node)]
        else:
            warning('Context management tools are enabled but no message management node is available.')
    agent.test_tools = fc.get_tools_from_cfg(agent.tool_list_base + agent.tool_list_plugin + agent.tool_list_file + agent.tool_list_task + agent.tool_list_ext + agent.planning_tools + agent.context_tools, agent.cfg.tools.as_dict())
    agent.backend.init()
    agent.backend.set_debug(options.debug)
    agent.set_tool_call_time_out(agent.cfg.get_value('call_time_out', 300))
    agent.set_tool_block_log_count(agent.cfg.get_value('tool_block_log_count', 100))
    agent.set_tool_block_log_intervals(agent.cfg.get_value('tool_block_log_min_interval', 10), agent.cfg.get_value('tool_block_log_max_interval', 0))
    agent.stage_manager.init_stage()
    agent.session_id = uuid4()
    langfuse_cfg = agent.cfg.get_value('langfuse', {})
    agent.langfuse_enable = langfuse_cfg.get_value('enable', False) is True
    if agent.langfuse_enable:
        public_key = langfuse_cfg.get_value('public_key', '')
        secret_key = langfuse_cfg.get_value('secret_key', '')
        base_url = langfuse_cfg.get_value('base_url', '')
        agent.langfuse = Langfuse(public_key=public_key, secret_key=secret_key, base_url=base_url)
        agent._startup_cleanup.callback(agent.langfuse.shutdown)
        assert agent.langfuse.auth_check(), "Can't connect to langfuse, please check your configuration"
        agent.langfuse_handler = CallbackHandler()

