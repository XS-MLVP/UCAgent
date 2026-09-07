# -*- coding: utf-8 -*-

from curses import echo
from .tools.context import ArbitContextSummary
from .util.config import get_config, save_runtime_config
from .util.log import echo_g, echo_r, info, message, warning, error, msg_msg
from .util.functions import (
    fmt_time_deta,
    fmt_time_stamp,
    get_template_path,
    render_template,
    render_template_dir,
    import_and_instance_tools,
    copy_skill_files,
)
from .util.functions import yam_str, make_llm_tool_ret
from .util.functions import (
    rm_workspace_prefix,
)
import ucagent.util.functions as fc
from .util.test_tools import ucagent_lib_path
from .util.markdown import ensure_markdown_heading_spacing

import ucagent.tools
from .tools import *
from .tools.skill import ListSkill, _list_skills, list_skills_in_format
from .tools.planning import *
from .stage import StageManager
from .verify_pdb import VerifyPDB
from .interaction import EnhancedInteractionLogic, AdvancedInteractionLogic
from .version import __version__, __email__
from .plugins import (
    PluginContext,
    collect_plugin_resources,
    create_plugin_checker_registry,
    create_plugin_tools,
)

import time
import math
import random
import signal
import copy
import threading
import shutil
import filecmp
import os
import hashlib
import json

from .abackend import get_backend
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from uuid import uuid4
from typing import Any, Callable, Dict, List, Mapping, Optional, OrderedDict
from pathlib import Path
import traceback


def _guide_doc_destination(root: str, relative_path: str) -> str:
    """Return one Guide_Doc destination after rejecting symlink components."""

    current = Path(root)
    if current.is_symlink():
        raise ValueError(
            f"Guide_Doc destination must not be a symbolic link: {current}"
        )
    for part in Path(relative_path).parts:
        current /= part
        if current.is_symlink():
            raise ValueError(
                "Guide_Doc destination path must not contain symbolic links: "
                f"{current}"
            )
    return str(current)


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
        init_cmd: Optional[List[str]] = None,
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
            plugins (list, optional): Validated UCAgent plugins selected for this run.
            plugin_guide_doc_paths (list, optional): Additional selected-workflow Guide_Doc resources.
            plugin_skill_paths (list, optional): Additional plugin-name and selected-workflow Skill roots.
            workflow_config_file (str, optional): Selected plugin workflow baseline configuration.
            plugin_workflow (str, optional): Qualified selected plugin workflow ID.
            template_target (str, optional): Workspace-relative template destination.
            template_context_factory (callable, optional): Selected workflow hook that derives template values from resolved config.
            plugin_runtime_config_keys (list, optional): Safe resolved config scalars exported for plugin consumers.
        """
        saved_info = {}
        if not no_history:
            saved_info = fc.load_ucagent_info(workspace)
        force_stage_index_explicit = force_stage_index != 0
        if force_stage_index == 0:
            force_stage_index = saved_info.get("stage_index", force_stage_index)
            if force_stage_index > 0:
                warning(f"Resuming from saved stage index: {force_stage_index}")
        self.workspace = os.path.abspath(workspace)
        self.__version__ = __version__
        self.config_file = "" if config_file is None else str(config_file)
        self.workflow_config_file = (
            "" if workflow_config_file is None else str(workflow_config_file)
        )
        self.plugin_workflow = "" if plugin_workflow is None else str(plugin_workflow)
        self.template_target = template_target
        saved_meta = saved_info.get("meta") if isinstance(saved_info.get("meta"), dict) else {}
        self.meta = copy.deepcopy(saved_meta)
        if meta:
            self.meta.update(copy.deepcopy(meta))
            updated_info = copy.deepcopy(saved_info)
            updated_info["meta"] = copy.deepcopy(self.meta)
            fc.save_ucagent_info(self.workspace, updated_info)
        self.cfg = get_config(
            config_file,
            cfg_override,
            self.workspace,
            workflow_config_file=workflow_config_file,
        )
        self.plugins = list(plugins or [])
        self.plugin_checker_registry = create_plugin_checker_registry(self.plugins)
        plugin_python_import_roots = [
            str(loaded.python_import_root)
            for loaded in self.plugins
            if getattr(loaded, "python_import_root", None) is not None
        ]
        plugin_docs, plugin_skills = collect_plugin_resources(self.plugins)
        resolved_plugin_docs = []
        seen_plugin_docs = set()
        for path in [*plugin_docs, *(plugin_guide_doc_paths or [])]:
            canonical = os.path.realpath(path)
            if canonical not in seen_plugin_docs:
                seen_plugin_docs.add(canonical)
                resolved_plugin_docs.append(canonical)
        resolved_plugin_skills = []
        seen_plugin_skills = set()
        for plugin_name, path in [*plugin_skills, *(plugin_skill_paths or [])]:
            item = (plugin_name, os.path.realpath(path))
            if item not in seen_plugin_skills:
                seen_plugin_skills.add(item)
                resolved_plugin_skills.append(item)
        temp_args = {
            "OUT": output,
            "DUT": dut_name,
            "Version": __version__,
            "WORKSPACE": self.workspace,
        }
        self.cfg.update_template(temp_args)
        from ucagent.plugins import (
            resolve_guide_doc_copy_policy,
            resolve_plugin_guide_doc_copy_policy,
            resolve_workflow_template_context,
        )

        self.workflow_template_context = resolve_workflow_template_context(
            template_context_factory,
            self.cfg,
            temp_args,
        )
        template_overwrite = self.cfg.template_overwrite.as_dict()
        resolved_template_values = dict(template_overwrite)
        resolved_template_values.update(self.workflow_template_context)
        self.cfg.update_template(resolved_template_values)
        self.cfg.un_freeze()
        self.cfg.seed = seed if seed is not None else random.randint(1, 999999)
        self.cfg._temp_cfg = temp_args
        self.cfg.freeze()
        guide_doc_copy_policy = resolve_guide_doc_copy_policy(self.cfg)
        plugin_guide_doc_copy_policy = resolve_plugin_guide_doc_copy_policy(
            self.cfg
        )
        self.runtime_config_path = save_runtime_config(
            self.workspace,
            self.cfg,
            runtime_config_keys=list(plugin_runtime_config_keys or []),
            launch_context={
                "config_file": (
                    os.path.abspath(self.config_file) if self.config_file else None
                ),
                "plugin_selectors": [item.selector for item in self.plugins],
                "plugin_workflow": self.plugin_workflow or None,
                "workflow_config_file": (
                    os.path.abspath(self.workflow_config_file)
                    if self.workflow_config_file
                    else None
                ),
            },
        )
        self.output_dir = os.path.join(self.workspace, output)
        # copy doc/Guide_Doc to workspace
        guide_doc_path = os.path.join(self.workspace, self.cfg.guide_doc.path)
        if resolved_plugin_docs and not self.cfg.guide_doc.enable:
            raise ValueError(
                "Plugin Guide_Doc contributions require guide_doc.enable to be true"
            )
        doc_guide_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "lang",
            self.cfg.lang,
            "doc",
            "Guide_Doc",
        )
        doc_files_to_append = []
        if self.cfg.guide_doc.enable and len(guid_doc_path) > 0:
            for gfile in guid_doc_path:
                if os.path.exists(gfile) is False:
                    warning(
                        f"Specified guid_doc_path {gfile} does not exist, ignore it"
                    )
                    continue
                if os.path.isfile(gfile):
                    doc_files_to_append.append(gfile)
                    continue
                if os.path.isdir(gfile):
                    doc_guide_path = gfile
                    continue
                assert False, (
                    f"Specified guid_doc_path {gfile} is not a valid file or directory"
                )
            assert os.path.exists(doc_guide_path), (
                f"Specified guid_doc_path {doc_guide_path} does not exist"
            )
        base_document_sources = {}
        if os.path.isdir(doc_guide_path):
            for source_root, _, source_files in os.walk(doc_guide_path):
                relative_root = os.path.relpath(source_root, doc_guide_path)
                for source_file in source_files:
                    relative_path = (
                        source_file
                        if relative_root == "."
                        else os.path.join(relative_root, source_file)
                    )
                    relative_path = Path(relative_path).as_posix()
                    base_document_sources[relative_path] = os.path.join(
                        source_root, source_file
                    )
        for source in doc_files_to_append:
            base_document_sources[os.path.basename(source)] = source

        plugin_document_sources = {}
        for plugin_guide_path in resolved_plugin_docs:
            source = os.path.realpath(plugin_guide_path)
            if os.path.isdir(source):
                for source_root, _, source_files in os.walk(source):
                    relative_root = os.path.relpath(source_root, source)
                    for source_file in source_files:
                        source_path = os.path.join(source_root, source_file)
                        relative_path = (
                            source_file
                            if relative_root == "."
                            else os.path.join(relative_root, source_file)
                        )
                        relative_path = Path(relative_path).as_posix()
                        previous = plugin_document_sources.get(relative_path)
                        if previous is not None and not filecmp.cmp(
                            source_path, previous, shallow=False
                        ):
                            raise ValueError(
                                "Plugin Guide_Doc sources conflict for runtime path "
                                f"{relative_path}: {previous} and {source_path}"
                            )
                        plugin_document_sources[relative_path] = source_path
            elif os.path.isfile(source):
                relative_path = os.path.basename(source)
                previous = plugin_document_sources.get(relative_path)
                if previous is not None and not filecmp.cmp(
                    source, previous, shallow=False
                ):
                    raise ValueError(
                        "Plugin Guide_Doc sources conflict for runtime path "
                        f"{relative_path}: {previous} and {source}"
                    )
                plugin_document_sources[relative_path] = source
            else:
                raise FileNotFoundError(f"Plugin Guide_Doc path was not found: {source}")

        configured_core_paths = set(
            guide_doc_copy_policy.retain
            + guide_doc_copy_policy.override
            + guide_doc_copy_policy.ignore
        )
        missing_core_paths = sorted(configured_core_paths - set(base_document_sources))
        if missing_core_paths:
            raise ValueError(
                "Guide_Doc core copy policy references files not provided by the "
                f"active language defaults: {missing_core_paths}"
            )
        configured_plugin_paths = set(
            plugin_guide_doc_copy_policy.retain
            + plugin_guide_doc_copy_policy.ignore
        )
        missing_plugin_paths = sorted(
            configured_plugin_paths - set(plugin_document_sources)
        )
        if missing_plugin_paths:
            raise ValueError(
                "Guide_Doc plugin copy policy references files not provided by "
                f"active plugins: {missing_plugin_paths}"
            )
        missing_overrides = sorted(
            set(guide_doc_copy_policy.override)
            - {
                path
                for path in plugin_document_sources
                if plugin_guide_doc_copy_policy.action_for(path) == "retain"
            }
        )
        if missing_overrides:
            raise ValueError(
                "Guide_Doc core copy policy requires plugin replacements for: "
                f"{missing_overrides}"
            )

        if os.path.lexists(guide_doc_path):
            runtime_doc_root = Path(guide_doc_path)
            runtime_doc_paths = [runtime_doc_root, *runtime_doc_root.rglob("*")]
            symbolic_paths = [
                str(path) for path in runtime_doc_paths if path.is_symlink()
            ]
            if symbolic_paths:
                raise ValueError(
                    "Guide_Doc destination tree must not contain symbolic links: "
                    f"{symbolic_paths[:20]}"
                )
            # An interrupted prior run may leave protected runtime documents
            # read-only. Current un_write_dirs are reapplied after initialization.
            fc.chmode_rw([str(path) for path in runtime_doc_paths])

        if self.cfg.guide_doc.enable:
            os.makedirs(guide_doc_path, exist_ok=True)
            for relative_path, source in base_document_sources.items():
                action = guide_doc_copy_policy.action_for(relative_path)
                destination = _guide_doc_destination(
                    guide_doc_path, relative_path
                )
                if action in {"ignore", "override"}:
                    if os.path.isfile(destination):
                        os.unlink(destination)
                    elif os.path.exists(destination):
                        raise ValueError(
                            "Guide_Doc file destination is not a regular file: "
                            f"{destination}"
                        )
                    continue
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                if not os.path.exists(destination):
                    shutil.copy2(source, destination)

        for relative_path, source in plugin_document_sources.items():
            base_source = base_document_sources.get(relative_path)
            if plugin_guide_doc_copy_policy.action_for(relative_path) == "ignore":
                if base_source is None:
                    destination = _guide_doc_destination(
                        guide_doc_path, relative_path
                    )
                    if os.path.isfile(destination):
                        os.unlink(destination)
                    elif os.path.exists(destination):
                        raise ValueError(
                            "Guide_Doc file destination is not a regular file: "
                            f"{destination}"
                        )
                continue
            if base_source is not None:
                action = guide_doc_copy_policy.action_for(relative_path)
                if action == "ignore":
                    raise ValueError(
                        "Plugin Guide_Doc provides a core runtime path configured as "
                        f"ignored: {relative_path}"
                    )
                if action == "retain" and filecmp.cmp(
                    source, base_source, shallow=False
                ):
                    continue
                if action == "retain":
                    raise ValueError(
                        "Plugin Guide_Doc conflicts with a retained base runtime "
                        f"document for path {relative_path}: {base_source} and {source}"
                    )
            destination = _guide_doc_destination(guide_doc_path, relative_path)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copy2(source, destination)

        # if use_skill is enabled, copy skills to workspace, and add skill tools
        self.tool_skill = []
        if self.cfg.skill.use_skill:
            copy_skill_files(
                self.cfg,
                self.workspace,
                root_dir=os.path.dirname(os.path.abspath(__file__)),
                plugin_skill_paths=resolved_plugin_skills,
            )
            self.tool_skill += [ListSkill(self.workspace).bind(self),RunSkillScript(self.workspace).bind(self)]

        self.thread_id = (
            thread_id if thread_id is not None else random.randint(100000, 999999)
        )
        self.dut_name = dut_name
        self.seed = seed if seed is not None else random.randint(1, 999999)
        self.template = get_template_path(
            self.cfg.template, self.cfg.lang, template_dir
        )
        self.render_template(template_cfg=template_cfg, tmp_overwrite=tmp_overwrite)
        self.tool_read_text = ReadTextFile(self.workspace)
        self.tool_list_dir = PathList(self.workspace)
        self.tool_search_text = SearchText(self.workspace)
        self.todo_panel = ToDoPanel()
        self.stage_manager = StageManager(
            self.workspace,
            self.cfg,
            self,
            self.tool_read_text,
            saved_info,
            force_stage_index,
            force_stage_index_explicit=force_stage_index_explicit,
            force_todo=force_todo,
            todo_panel=self.todo_panel,
            stage_skip_list=stage_skip_list,
            stage_unskip_list=stage_unskip_list,
            tool_inspect_file=[
                self.tool_read_text,
                self.tool_list_dir,
                self.tool_search_text,
            ],
            reference_files=reference_files,
            checker_registry=self.plugin_checker_registry,
            test_python_import_roots=plugin_python_import_roots,
        )
        self._default_system_prompt = (
            sys_tips if sys_tips else self.get_default_system_prompt()
        )
        self.tool_list_base = [
            self.tool_read_text,
            RoleInfo(self._default_system_prompt),
        ]
        if not no_embed_tools:
            self.tool_reference = SemanticSearchInGuidDoc(
                self.cfg.embed, workspace=self.workspace, doc_path="Guide_Doc"
            )
            self.tool_memory_put = MemoryPut().set_store(self.cfg.embed)
            self.tool_memory_get = MemoryGet().set_store(
                store=self.tool_memory_put.get_store()
            )
            self.tool_list_base += [
                self.tool_reference,
                self.tool_memory_put,
                self.tool_memory_get,
            ]
        if no_write_targets is not None:
            assert isinstance(no_write_targets, list), (
                "no_write_targets must be a list of directories or files"
            )
            for f in no_write_targets:
                abs_f = os.path.abspath(f)
                assert os.path.exists(abs_f), (
                    f"Specified no-write target {abs_f} does not exist"
                )
                assert abs_f.startswith(os.path.abspath(self.workspace)), (
                    f"Specified no-write target {abs_f} must be under the workspace {self.workspace}"
                )
                self.cfg.un_write_dirs.append(
                    rm_workspace_prefix(self.workspace, abs_f)
                )
        self.cwd_read_only_files = fc.chmode_ro_by_pattern(
            self.workspace, self.cfg.get_value("un_write_dirs", [])
        )
        self.tool_waveinfo = WaveInfo(
            workspace=self.workspace,
            test_dir=self.cfg.tools.RunTestCases.test_dir,
            dut_name=self.dut_name,
        )
        self.tool_apply_waveinfo_evidence = ApplyWaveInfoEvidence(
            waveinfo=self.tool_waveinfo,
            workspace=self.workspace,
            write_dirs=self.cfg.write_dirs,
            un_write_dirs=self.cfg.un_write_dirs,
        )
        self.tool_review_waveinfo_evidence_batch = ReviewWaveInfoEvidenceBatch(
            evidence_writer=self.tool_apply_waveinfo_evidence,
        )
        self.tool_list_waveform = [
            self.tool_waveinfo,
            self.tool_apply_waveinfo_evidence,
            self.tool_review_waveinfo_evidence_batch,
        ]
        self.tool_list_plugin = create_plugin_tools(
            self.plugins,
            PluginContext(
                workspace=Path(self.workspace),
                output_dir=os.path.relpath(self.output_dir, self.workspace),
                write_dirs=tuple(self.cfg.write_dirs),
                un_write_dirs=tuple(self.cfg.un_write_dirs),
                cfg=self.cfg,
                plugin_root=Path(self.workspace),
            ),
        )
        self.tool_list_file = [
            # Directory and file listing tools
            self.tool_list_dir,
            GetFileInfo(self.workspace),
            # File reading tools
            # ReadBinFile(self.workspace), # ignore Binary file read
            # File searching tools
            self.tool_search_text,
            FindFiles(self.workspace),
            # File writing and editing tools (require permissions)
            DeleteFile(
                self.workspace,
                write_dirs=self.cfg.write_dirs,
                un_write_dirs=self.cfg.un_write_dirs,
            ),
            EditTextFile(
                self.workspace,
                write_dirs=self.cfg.write_dirs,
                un_write_dirs=self.cfg.un_write_dirs,
            ),
            DeleteTextLines(
                self.workspace,
                write_dirs=self.cfg.write_dirs,
                un_write_dirs=self.cfg.un_write_dirs,
            ),
            ReplaceStringInFile(
                self.workspace,
                write_dirs=self.cfg.write_dirs,
                un_write_dirs=self.cfg.un_write_dirs,
            ),
            # File management tools (require permissions)
            CopyFile(
                self.workspace,
                write_dirs=self.cfg.write_dirs,
                un_write_dirs=self.cfg.un_write_dirs,
            ),
            MoveFile(
                self.workspace,
                write_dirs=self.cfg.write_dirs,
                un_write_dirs=self.cfg.un_write_dirs,
            ),
            CreateDirectory(
                self.workspace,
                write_dirs=self.cfg.write_dirs,
                un_write_dirs=self.cfg.un_write_dirs,
            ),
            # Workspace git management tools
            WorkDiff(self.workspace),
            WorkCommit(self.workspace),
            # bash tool
            RunBashCommand(self.workspace),
        ]
        self.tool_list_task = self.stage_manager.new_tools()
        self.tool_list_ext = import_and_instance_tools(
            self.cfg.get_value("ex_tools", []), ucagent.tools
        ) + import_and_instance_tools(ex_tools, ucagent.tools) + self.tool_skill

        non_plugin_tools = (
            self.tool_list_base
            + self.tool_list_waveform
            + self.tool_list_file
            + self.tool_list_task
            + self.tool_list_ext
        )
        non_plugin_names = {tool.name for tool in non_plugin_tools}
        conflicting_plugin_names = sorted(
            tool.name
            for tool in self.tool_list_plugin
            if tool.name in non_plugin_names
        )
        if conflicting_plugin_names:
            raise ValueError(
                "Plugin tool names conflict with registered UCAgent tools: "
                f"{conflicting_plugin_names}"
            )

        # Export workspace path via environment variable for ext tools
        os.environ["UCAGENT_WORKSPACE"] = self.workspace

        # Initialize planning tools
        self.planning_tools = []
        self.force_todo = force_todo
        if (interaction_mode == "standard" and force_todo) or use_todo_tools:
            self.planning_tools = [
                CreateToDo(self.todo_panel),
                CompleteToDoSteps(self.todo_panel),
                UndoToDoSteps(self.todo_panel),
                ResetToDo(self.todo_panel),
                GetToDoSummary(self.todo_panel),
                ToDoState(self.todo_panel),
            ]

        self.max_token = self.cfg.get_value(
            "conversation_summary.max_tokens", 20 * 1024
        )
        self.max_summary_tokens = self.cfg.get_value(
            "conversation_summary.max_summary_tokens", 8 * 1024
        )
        self.context_management_strategy = self.cfg.get_value(
            "conversation_summary.context_management_strategy",
            "TrimAndSummaryMiddleware",
        )
        self.max_keep_msgs = self.cfg.get_value(
            "conversation_summary.max_keep_msgs", 200
        )
        self.tail_keep_msgs = self.cfg.get_value(
            "conversation_summary.tail_keep_msgs", 20
        )
        self.message_echo_handler = None
        self.update_handler = None
        self._time_start = time.time()
        self._time_end = None
        # state
        self._msg_buffer = ""
        self._system_message = self._default_system_prompt
        # flags
        self.stream_output = stream_output
        self.invoke_round = 0
        self._tool__call_error = []
        self._is_exit = False
        self._sync_workspace_back_on_exit_done = False
        self._tip_index = 0
        self._need_break = False
        self._break_threads: set[int] = set()
        self._need_human = False
        self._max_stalled_rounds = self._validated_max_stalled_rounds(
            self.cfg.get_value("loop_settings.max_stalled_rounds", 3)
        )
        self._stalled_rounds = 0
        self._last_stall_signature = None
        self._force_trace = False
        self._continue_msg = None
        self._mcps = None               # set by PdbMcpServer for api_master heartbeat
        self._mcp_server_thread = None   # set by PdbMcpServer for api_master heartbeat
        self._mcps_logger = None
        self.original_sigint = signal.getsignal(signal.SIGINT)
        self._sigint_count = 0
        self._exit_on_completion = exit_on_completion
        self._exit_on_completion_pending = False
        self._exit_on_completion_queued = False
        self._is_work_busy = False
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
        cfg_icmds = self.cfg.get_value("init_cmds", [])
        if cfg_icmds:
            if init_cmd is None:
                init_cmd = []
            init_cmd = init_cmd + cfg_icmds
        # PDB and backend
        self.backend = get_backend(self, self.cfg)
        self.message_manage_node = self.backend.get_message_manage_node()
        self.context_tools = []
        if enable_context_manage_tools:
            if self.message_manage_node is not None:
                self.context_tools = [
                    ArbitContextSummary().bind(self.message_manage_node),
                ]
            else:
                warning(
                    "Context management tools are enabled but no message management node is available."
                )
        self.test_tools = fc.get_tools_from_cfg(
            self.tool_list_base
            + self.tool_list_waveform
            + self.tool_list_plugin
            + self.tool_list_file
            + self.tool_list_task
            + self.tool_list_ext
            + self.planning_tools
            + self.context_tools,
            self.cfg.tools.as_dict(),
        )
        self.pdb = VerifyPDB(
            self,
            init_cmd=init_cmd,
            max_loop_retry=self.cfg.loop_settings.max_loop_retry,
            retry_delay=(
                self.cfg.loop_settings.retry_delay_start,
                self.cfg.loop_settings.retry_delay_end,
            ),
            loop_alive_time=self.cfg.loop_settings.loop_alive_time,
        )
        self.backend.init()
        self.backend.set_debug(debug)
        self.set_tool_call_time_out(self.cfg.get_value("call_time_out", 300))
        self.stage_manager.init_stage()
        # Telemetry
        self.session_id = uuid4()
        langfuse_cfg = self.cfg.get_value("langfuse", {})
        self.langfuse_enable = langfuse_cfg.get_value("enable", False) is True
        if self.langfuse_enable:
            public_key = langfuse_cfg.get_value("public_key", "")
            secret_key = langfuse_cfg.get_value("secret_key", "")
            base_url = langfuse_cfg.get_value("base_url", "")
            self.langfuse = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                base_url=base_url,
            )
            assert self.langfuse.auth_check(), (
                "Can't connect to langfuse, please check your configuration"
            )
            self.langfuse_handler = CallbackHandler()

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
        if not file_path:
            return
        if file_path.startswith(os.sep):
            file_path = file_path[1:]
        file_path = os.path.abspath(os.path.join(self.workspace, file_path))
        dut_readme = os.path.join(self.workspace, self.dut_name, "README.md")
        sections = []
        if os.path.exists(dut_readme):
            sections.append("# Goal Description\n")
            with open(dut_readme, "r", encoding="utf-8") as df:
                sections.append(df.read() + "\n")
        sections.append("# Verification Instruction\n")
        sections.append(self._default_system_prompt + "\n")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(ensure_markdown_heading_spacing("".join(sections)))

    def render_template(self, template_cfg=None, tmp_overwrite=False):
        resolved_values = self.cfg.__dict__.get("_temp_cfg", {})
        template_context = {
            "DUT": self.dut_name,
            "OUT": resolved_values.get("OUT", ""),
            "Version": __version__,
            "Email": __email__,
            "CWD": self.workspace,
            "UC_LIB_PATH": ucagent_lib_path(),
        }
        configured_template_values = self.cfg.template_overwrite.as_dict()
        if any(not isinstance(key, str) for key in configured_template_values):
            raise ValueError("Template override names must be strings")
        template_context.update(configured_template_values)
        template_context.update(self.workflow_template_context)
        if template_cfg is not None:
            template_context.update(template_cfg)
        if self.template is not None:
            target = self.template_target or os.path.basename(self.template)
            target = render_template(target, resolved_values)
            if not isinstance(target, str) or not target.strip():
                raise ValueError("Template target must resolve to a non-empty string")
            target_path = Path(target)
            if target_path.is_absolute():
                raise ValueError("Template target must be workspace-relative")
            tmp_dir_path = (Path(self.workspace) / target_path).resolve()
            try:
                tmp_dir_path.relative_to(Path(self.workspace).resolve())
            except ValueError as exc:
                raise ValueError("Template target must remain inside the workspace") from exc
            if tmp_dir_path == Path(self.workspace).resolve():
                raise ValueError("Template target must not be the workspace root")
            for protected_value in self.cfg.get_value("un_write_dirs", []):
                if (
                    not isinstance(protected_value, str)
                    or not protected_value.strip()
                    or any(character in protected_value for character in "*?[]")
                ):
                    continue
                protected_path = Path(protected_value)
                if not protected_path.is_absolute():
                    protected_path = Path(self.workspace) / protected_path
                protected_path = protected_path.resolve()
                try:
                    protected_path.relative_to(Path(self.workspace).resolve())
                except ValueError:
                    continue
                if (
                    tmp_dir_path == protected_path
                    or tmp_dir_path.is_relative_to(protected_path)
                    or protected_path.is_relative_to(tmp_dir_path)
                ):
                    raise ValueError(
                        "Template target must not overlap a configured read-only path: "
                        f"{protected_value}"
                    )
            tmp_dir = str(tmp_dir_path)
            info(f"Rendering template from {self.template} to {tmp_dir}")
            if not os.path.exists(tmp_dir) or tmp_overwrite:
                try:
                    render_template_dir(
                        self.workspace,
                        self.template,
                        template_context,
                        target_dir=self.template_target,
                    )
                except Exception as e:
                    debug(traceback.format_exc())
                    error(
                        f"Failed to render template from {self.template} to {tmp_dir}: {e}"
                    )
                    raise e

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
                # self.original_sigint(s, f)
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

    def is_break(self):
        return self._need_break or threading.current_thread().ident in self._break_threads

    def set_break_thread(self, thread_id: int) -> None:
        self.set_break(True)
        self._break_threads.add(thread_id)

    def clear_break_thread(self, thread_id: int) -> None:
        self._break_threads.discard(thread_id)

    def clear_all_break_threads(self) -> None:
        self._break_threads.clear()

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
            formatted_skill_list = list_skills_in_format(_list_skills(self.workspace),self.workspace,self.cfg.skill.general_skill_list)
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

    def exit(self):
        """Persist runtime state, stop owned services, and restore input modes."""

        if self.is_exit():
            return
        try:
            self._is_exit = True
            try:
                if getattr(self, "stage_manager", None) is not None:
                    self.stage_manager.save_stage_info()
            except Exception as exc:
                warning(f"Failed to save stage information on exit: {exc}")
            self._sync_workspace_back_on_exit()
            pdb = getattr(self, "pdb", None)
            mcp_server = getattr(pdb, "_mcp_server", None)
            if mcp_server is not None and mcp_server.is_running:
                ok, msg = mcp_server.stop()
                if not ok:
                    warning(msg)
        finally:
            fc.chmode_rw(self.cwd_read_only_files)

    def exit_unset(self):
        if not self.is_exit():
            return False
        self._is_exit = False
        return True

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
        pdb = getattr(self, "pdb", None)
        master_clients = getattr(pdb, "_master_clients", {}) or {}
        if not master_clients:
            return
        for url, client in list(master_clients.items()):
            if not getattr(client, "is_running", False):
                continue
            ok, msg = client.sync_workspace_back(reason="exit")
            if ok:
                info(msg)
            else:
                info(f"Workspace sync-back skipped for {url}: {msg}")

    def protect_files_on(self, new_files: List[str]):
        for f in new_files:
            fpath = os.path.abspath(self.workspace + os.path.sep + f)
            if not os.path.exists(fpath):
                warning(
                    f"File to protect does not exist: {f} in workspace {self.workspace}"
                )
                continue
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

    def try_exit_on_completion(self):
        if self._exit_on_completion:
            self.set_break(False)
            if self.is_work_busy():
                self._exit_on_completion_pending = True
                return
            self._queue_exit_on_completion()

    def _queue_exit_on_completion(self):
        if self._exit_on_completion_queued:
            return
        self._exit_on_completion_pending = False
        self._exit_on_completion_queued = True
        self.pdb.add_cmds(["sleep 5"] + ["quit"] * 3)

    def get_work_config(self):
        return self.backend.get_work_config()

    def run(self):
        self.pre_run()
        self.run_loop()

    def pre_run(self):
        time_start = self._time_start = time.time()
        info(
            "Verify Agent started at: "
            + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time_start))
        )
        info("Seed: " + str(self.seed))
        self.check_pdb_trace()
        return self

    def run_loop(self, msg=None):
        if msg:
            self.set_continue_msg(msg)
        self._need_human = False
        # conversation loop
        while not self.is_exit():
            validation_revision = getattr(
                self.stage_manager, "validation_revision", 0
            )
            stage_index = getattr(self.stage_manager, "stage_index", None)
            self.one_loop()
            self._update_stalled_rounds(validation_revision, stage_index)
            if self.is_exit():
                break
            if self.is_break():
                info("Break at loop: " + str(self.invoke_round))
                return
            if self._need_human:
                info("Waiting for human input at loop: " + str(self.invoke_round))
                return
            self.check_pdb_trace()
        time_end = self._time_end = time.time()
        info(
            "Verify Agent finished at: "
            + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time_end))
        )
        info(f"Total time taken: {fmt_time_deta(time_end - self._time_start)}")
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
        """Custom chat message to the agent."""
        self.do_work(
            {"messages": [self.backend.get_human_message(msg)]}, self.get_work_config()
        )

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
            if self._exit_on_completion_pending:
                self._queue_exit_on_completion()

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
        self.message_manage_node.force_summary(self.messages_get_raw())

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
        return stats

    def message_get_str(self, index, count):
        messages = self.messages_get_raw()
        if len(messages) == 0:
            warning(f"No messages found, cannot get message. Please try later.")
            return []
        index = index % len(messages)
        return [m.pretty_repr() for m in messages[index : index + count]]

    def do_work_values(self, instructions, config):
        return self.backend.do_work_values(instructions, config)

    def do_work_stream(self, instructions, config):
        return self.backend.do_work_stream(instructions, config)

    def get_tool_by_name(self, tool_name: str):
        """Get a tool by its name."""
        tool = next((tool for tool in self.test_tools if tool.name == tool_name), None)
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
