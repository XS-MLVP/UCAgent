# -*- coding: utf-8 -*-
"""Verification stage management for UCAgent."""

from ucagent.util.functions import import_class_from_str, find_files_by_pattern
import ucagent.util.functions as fc
import ucagent.util.diff_ops as diff_ops
from ucagent.util.log import info, warning
from ucagent.util.config import Config
import ucagent.checkers as checkers
from collections import OrderedDict
import copy
import time
import os
from typing import Dict, Any

def update_dict(d, u):
    d.update(u)
    return d


def convert_task_form_cfg(data):
    if isinstance(data, Config):
       return data.as_dict()
    if isinstance(data, list):
        return [convert_task_form_cfg(d) for d in data]
    if isinstance(data, (dict, OrderedDict)):
        for k in data.keys():
            assert not isinstance(k, Config), "Config cannot be used as dict key."
            data[k] = convert_task_form_cfg(data[k])
    return data


class VerifyStage(object):
    from typing import Self

    def __init__(self,
                 cfg,
                 workspace,
                 name,
                 description,
                 task,
                 checker,
                 reference_files,
                 skill_list,
                 output_files,
                 prefix = "",
                 skip=False,
                 tool_read_text=None,
                 need_fail_llm_suggestion=None,
                 need_pass_llm_suggestion=None,
                 need_human_check=False,
                 substages=None):
        """
        Initialize the VerifyStage.
        """
        self.cfg = cfg
        self.name = name
        self.prefix = prefix
        self.skip = skip
        self.need_fail_llm_suggestion = need_fail_llm_suggestion
        self.need_pass_llm_suggestion = need_pass_llm_suggestion
        self.need_human_check = need_human_check
        self._hum_check_passed = None
        self._hum_check_msg = ""
        self.desc = description
        self.task_list = convert_task_form_cfg(task)
        self._checker = checker
        self.workspace = workspace
        self.checker = [
            import_class_from_str(c.clss, checkers)(**update_dict(c.args.as_dict(),
                                                                  {"cfg": self.cfg})).set_extra(
                **c.extra_args.as_dict()
            ).set_workspace(workspace).set_stage(self) for c in self._checker
        ]
        if not self.need_human_check:
            for c in self.checker:
                if c.is_human_check_needed():
                    self.need_human_check = True
                    break
        # Configure LD_PRELOAD isolation for checkers that need it
        check_script_env = getattr(self.cfg, "check_script_env", None)
        if check_script_env:
            for c in self.checker:
                c.set_ld_preload(check_script_env)
        self.check_size = len(self.checker)
        self.check_info = [None] * self.check_size
        self.fail_count = 0
        self.succ_count = 0
        self.check_pass = False
        self.continue_fail_count = 0
        self.reference_files = {
            k:False for k in find_files_by_pattern(workspace, reference_files)
        }
        self.skill_list = {k:[False,False,False] for k in skill_list}
        self.output_files = output_files
        self.tool_read_text = tool_read_text
        if self.tool_read_text is not None:
            self.tool_read_text.append_callback(self.on_file_read)
        self._is_reached = False
        self.substages = substages if substages is not None else []
        for sub in self.substages:
            sub.parent = self
        self.parent = None
        self.time_start = None
        self.time_end = None
        self.time_prev_cost = 0.0
        self.llm_approved = True
        self.is_batch_success = False # set True when reset continue_fail_count due to batch success
        self.is_complete = False
        self.force_unactive = False
        self.vmanager = None
        self.meta_data = {}
        self._cached_stage_outcome = None
        self.last_do_check_info_fail = None
        self.last_do_check_info_pass = None
        # history version control
        self.hist_src_dir = cfg._temp_cfg["OUT"]
        self.hist_sav_dir = fc.get_abs_path_cwd_ucagent(workspace, "history")
        self.hist_tgt_dir = os.path.join(self.hist_sav_dir, self.hist_src_dir)
        self.hist_ign_list = cfg.hist_ignore_pattern

    def meta_set_journal(self, journal):
        self.meta_data['journal'] = copy.deepcopy(journal)

    def meta_get_journal(self):
        return self.meta_data.get('journal', None)

    def meta_set_llm_pass_suggestion(self, suggestion):
        self.meta_data['llm_pass_suggestion'] = copy.deepcopy(suggestion)

    def meta_set_llm_fail_suggestion(self, suggestion):
        self.meta_data['llm_fail_suggestion'] = copy.deepcopy(suggestion)

    def meta_get_llm_pass_suggestion(self):
        return self.meta_data.get('llm_pass_suggestion', None)

    def meta_get_llm_fail_suggestion(self):
        return self.meta_data.get('llm_fail_suggestion', None)

    def meta_set_skill_usage(self, skill_usage: Dict[str, Any]):
        self.meta_data['skill_usage'] = copy.deepcopy(skill_usage)

    def set_usage_skill_list(self,skill_name,listed=False, read=False, used=False):
        if skill_name in self.skill_list:
            [u,v,w] = self.skill_list[skill_name]
            self.skill_list[skill_name] = [listed or u, read or v, used or w]

    def hist_init(self):
        if not os.path.exists(self.hist_sav_dir):
            os.makedirs(self.hist_sav_dir, exist_ok=True)
        if diff_ops.is_git_repo(self.hist_sav_dir):
            info(f"[{self.__class__.__name__}] History init: git repo already exists in {self.hist_sav_dir}, skip init.")
            return
        diff_ops.init_git_repo(self.hist_sav_dir, ignore_existing=True)
        self.hist_sync()
        self.hist_commit(msg="Initial commit for history version control.")

    def hist_sync(self):
        src_path = os.path.abspath(self.workspace + os.path.sep + self.hist_src_dir)
        if not os.path.exists(src_path):
            info(f"[{self.__class__.__name__}] History sync: source dir {self.hist_src_dir} does not exist, skip sync.")
            return
        fc.sync_dir_to(src_path,
                       self.hist_tgt_dir,
                       self.hist_ign_list)

    def hist_commit(self, msg="Auto commit"):
        self.hist_sync()
        info(f"[{self.__class__.__name__}] History commit: {msg}")
        stage_commit_str = self.title_short() + ":\n\n" + msg
        self.meta_data['commit'] = {
           "hash": diff_ops.git_add_and_commit(self.hist_sav_dir, stage_commit_str),
           "message": stage_commit_str
        }

    def hist_diff(self, target_file=".", show_diff=False,
                  start_line=1, line_count=-1, max_line_limit=500):
        self.hist_sync()
        return diff_ops.get_diff_report(self.hist_sav_dir,
                                        target_file,
                                        show_diff=show_diff,
                                        start_line=start_line,
                                        line_count=line_count,
                                        max_line_limit=max_line_limit)

    def add_reference_files(self, files):
        for f in find_files_by_pattern(self.workspace, files):
            if f not in self.reference_files:
                self.reference_files[f] = False
                info(f"[{self.__class__.__name__}] Reference file {f} added.")

    def get_stage_outcome(self, use_cache=True):
        hash_id = self.meta_data.get('commit', {}).get('hash', None)
        if self._cached_stage_outcome is not None and use_cache:
            if hash_id == self._cached_stage_outcome.get("commit_hash", None):
                return self._cached_stage_outcome
        output_files = {p:find_files_by_pattern(self.workspace, p, ignore_warn=True) for p in self.output_files}
        changed_files = []
        if hash_id is not None:
            changed_files = diff_ops.get_commit_changed_files(self.hist_sav_dir, hash_id)
        self._cached_stage_outcome = {
            "output_files": output_files,
            "changed_files": changed_files,
            "commit_hash": hash_id,
            "commit_message": self.meta_data.get('commit', {}).get('message', None)
        }
        return self._cached_stage_outcome

    def get_stage_file_content(self, file_path):
        hash_id = self.meta_data.get('commit', {}).get('hash', None)
        if hash_id is None:
            return {"error": f"stage not commited, cannot get file ({file_path}) content."}
        try:
            return diff_ops.get_commit_file_content_and_diff(self.hist_sav_dir, hash_id, file_path)
        except Exception as e:
            return {"error": f"cannot get file content ({file_path}) from commit ({hash_id}): {e}"}

    def get_current_file_content_with_diff(self, file_path):
        hash_id = self.meta_data.get('commit', {}).get('hash', None)
        if hash_id is None:
            return {"error": f"stage not commited, cannot get file ({file_path}) content."}
        try:
            return diff_ops.get_current_file_content_and_diff_from_commit(self.hist_sav_dir, hash_id, file_path)
        except Exception as e:
            return {"error": f"cannot get file content ({file_path}) from commit ({hash_id}): {e}"}

    def on_init(self):
        for c in self.checker:
            c.on_init()

        # setup function of vstage by skill in skill_list
        if hasattr(self, 'skill_list') and self.skill_list:
            import importlib.util
            import sys
            def add_hook(method_name: str, hook_func):
                if not hasattr(self, method_name):
                    warning(f"[{self.__class__.__name__}] Cannot hook method '{method_name}', not found.")
                    return
                original_method = getattr(self, method_name)
                def hooked_method(*args, **kwargs):
                    return hook_func(original_method, *args, **kwargs)
                setattr(self, method_name, hooked_method)
            self.add_hook = add_hook
            skills_dir = fc.get_workspace_skill_root(self.workspace)
            for skill_name in self.skill_list.keys():
                script_dir = os.path.join(fc.find_skill_dir_by_name(skills_dir, skill_name), "scripts")
                init_file = os.path.join(script_dir, "__init__.py")
                if os.path.isdir(script_dir) and os.path.isfile(init_file) and os.path.getsize(init_file) > 0:
                    try:
                        safe_module_name = f"ucskill_{skill_name.replace('-', '_')}"
                        spec = importlib.util.spec_from_file_location(safe_module_name, init_file)
                        skill_mod = importlib.util.module_from_spec(spec)
                        sys.modules[safe_module_name] = skill_mod
                        spec.loader.exec_module(skill_mod)
                        if hasattr(skill_mod, "setup_vstage"):
                            skill_mod.setup_vstage(self)                
                    except Exception as e:
                        warning(f"Skill '{skill_name}' setup_vstage failed during init: {e}")

        if self.time_start is None:
            self.time_start = time.time()
        else:
            warning(f"Stage {self.name} is already inited, cannot recall on_init.")

    def on_complete(self):
        if self.time_end is not None:
            return
        self.time_end = time.time()
        self.is_complete = True
        self.hist_commit(msg="Stage completed.")
        if self.vmanager:
            self.vmanager.agent.backend.on_stage_complete(self)

    def is_completed(self):
        return self.is_complete

    def is_curent_active(self):
        return self.vmanager and self.vmanager.get_current_stage() == self

    def set_force_unactive(self, unactive: bool):
        self.force_unactive = unactive

    def set_approved(self, approved: bool):
        self.llm_approved = approved
        return approved

    def get_approved(self):
        return self.llm_approved

    def get_time_start_str(self):
        if self.time_start is None:
            return ""
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.time_start))

    def get_time_end_str(self):
        if self.time_end is None:
            return ""
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.time_end))

    def get_time_cost(self):
        if self.time_start is None:
            return self.time_prev_cost
        if self.time_end is None:
            return time.time() - self.time_start + self.time_prev_cost
        return self.time_end - self.time_start + self.time_prev_cost

    def get_time_cost_str(self):
        cost = self.get_time_cost()
        if cost < 1:
            return f""
        secs = int(cost)%60
        minu = int(cost/60)%60
        hour = int(cost/3600)
        ret = []
        if hour > 0:
            ret.append(f"{hour}h")
        if minu > 0:
            ret.append(f"{minu:02}m")
        if secs > 0:
            ret.append(f"{secs:02}s")
        return " ".join(ret)

    def set_skip(self, is_skip):
        self.skip = is_skip
        for sb in self.substages:
            sb.set_skip(is_skip)

    def set_llm_pass_suggestion(self, value):
        self.need_pass_llm_suggestion = value
        if value is None:
            return
        for sb in self.substages:
            sb.set_llm_pass_suggestion(value)

    def set_llm_fail_suggestion(self, value):
        self.need_fail_llm_suggestion = value
        if value is None:
            return
        for sb in self.substages:
            sb.set_llm_fail_suggestion(value)

    def is_skipped(self):
        return self.skip

    def set_stage_manager(self, manager):
        assert manager is not None, "Stage Manager cannot be None."
        for c in self.checker:
            c.set_stage_manager(manager)
        self.vmanager = manager

    def is_skill_path(self, file_path):
        skill_root = fc.get_workspace_skill_root(self.workspace)
        abs_file_path = os.path.abspath(self.workspace + os.path.sep + file_path)
        return abs_file_path.startswith(skill_root)
    
    def on_file_read(self, success, file_path, content):
        if not self.is_curent_active():
            return
        if self.force_unactive:
            return
        if not success:
            return
        if file_path in self.reference_files:
            self.reference_files[file_path] = True
            info(f"[{self.__class__.__name__}.{self.name}] Reference file {file_path} has been read by the LLM.")

        if self.is_skill_path(file_path):
            abs_path = os.path.abspath(self.workspace + os.path.sep + file_path)
            if os.path.basename(abs_path) == "SKILL.md":
                skill_name = os.path.basename(os.path.dirname(abs_path))
                if skill_name in self.skill_list:
                    self.set_usage_skill_list(skill_name, read=True)
                    info(f"[{self.__class__.__name__}.{self.name}] Skill {skill_name} has been read by the LLM.")

    def __repr__(self):
        return f"VerifyStage(name={self.name}, description={self.description()}, "+\
               f"checker={'.'.join([n.name for n in self._checker])}, checker_cls={'.'.join([n.clss for n in self._checker])})"

    def do_kill(self):
        """
        Kill the current check process.
        This is used when the tool 'Check' is long time running or get stuck.
        """
        ret = []
        empt = True
        for c in self.checker:
            if c.is_processing():
                ret.append(f"{c.__class__.__name__}: {c.kill()}")
                empt = False
        if empt:
            ret.append("No check process is running.")
        return "\n".join(ret)

    def do_std(self, lines=-1):
        """
        Get the standard output of the current check process.
        This tool is only used to get the output of the running tool 'Check'.
        You can specify the number of lines to read, -1 means read all lines.
        """
        ret = []
        for c in self.checker:
            ret.append(f"{c.__class__.__name__}:\n{c.check_std(lines)}")
        return "\n".join(ret)

    def is_wait_human_check(self):
        """
        Check whether this stage is waiting for human check.
        """
        if not self.need_human_check:
            return False
        return self._hum_check_passed is not True

    def do_hmcheck_pass(self, msg=""):
        """
        Call the hmcheck_pass method of all HumanChecker in this stage.
        """
        if not self.need_human_check:
            return f"This stage({self.name}) does not need human check."
        self._hum_check_passed = True
        self._hum_check_msg = msg
        return f"set stage '{self.name}' human check passed."

    def do_hmcheck_fail(self, msg=""):
        """
        Call the hmcheck_fail method of all HumanChecker in this stage.
        """
        if not self.need_human_check:
            return f"This stage({self.name}) does not need human check."
        self._hum_check_passed = False
        self._hum_check_msg = msg
        return f"set stage '{self.name}' human check failed."

    def do_get_hmcheck_result(self):
        """
        Get the human check result of all HumanChecker in this stage.
        """
        if not self.need_human_check:
            return f"This stage({self.name}) does not need human check."
        if self._hum_check_passed:
            return f"This stage({self.name}) human check passed."
        else:
            return f"This stage({self.name}) human check failed."

    def do_set_hmcheck_needed(self, need: bool):
        """
        Set whether human check is needed for all HumanChecker in this stage.
        """
        self.need_human_check = need
        if need:
            return f"set stage '{self.name}' need human check."
        else:
            return f"set stage '{self.name}' do not need human check."

    def is_hmcheck_needed(self) -> bool:
        """
        Check whether any HumanChecker in this stage needs human check.
        """
        return self.need_human_check

    def get_hmcheck_state(self) -> tuple[bool|None, str]:
        """
        Get the human check state of this stage.
        Returns a tuple of (bool|None, str), where bool indicates pass/fail/None for not checked,
        and str is the message associated with the human check.
        """
        return self._hum_check_passed, self._hum_check_msg

    def get_last_do_check_info(self):
        """
        Get the last check result info of this stage.
        """
        return {
            "pass": self.last_do_check_info_pass,
            "fail": self.last_do_check_info_fail,
        }

    def do_check(self, *a, **kwargs):
        ck_pass, ck_info = self._do_check(*a, **kwargs)
        ck_info_snapshot = copy.deepcopy(ck_info)
        if ck_pass:
            self.last_do_check_info_pass = ck_info_snapshot
        else:
            self.last_do_check_info_fail = ck_info_snapshot
        return ck_pass, ck_info

    def _do_check(self, *a, **kwargs):
        if self.cfg.skill.use_skill and self.skill_list:
            for k,[u,v,w] in self.skill_list.items():
                if u and v and w:
                    continue
                else:
                    return False, "Please use tool 'SetSkillUsage' to check and set the skill usage of this stage before completing it."
        self._is_reached = True
        if not all(c[1] for c in self.reference_files.items()):
            emsg = OrderedDict({"error": "You need use tool `ReadTextFile` to read and understand the reference files", "files_need_read": []})
            for k, v in self.reference_files.items():
                if not v:
                    emsg["files_need_read"].append(k + f" (Not readed, need ReadTextFile('{k}'))")
            self.fail_count += 1
            self.continue_fail_count += 1
            return False, emsg
        success_out_file = True
        success_out_msg = []
        for k, v in {p: len(find_files_by_pattern(self.workspace, p)) for p in self.output_files}.items():
            if v <= 0:
                success_out_file = False
                success_out_msg.append(k)
        if not success_out_file:
            self.fail_count += 1
            self.continue_fail_count += 1
            return False, OrderedDict({"error": f"Output file patterns not found in workspace. you need to generate those files.",
                                       "failed_patterns": success_out_msg})
        self.check_pass = True
        for i, c in enumerate(self.checker):
            self.is_batch_success = False
            ck_pass, ck_msg = c.check(*a, **kwargs)
            if self.check_info[i] is None:
                self.check_info[i] = {
                    "name": c.__class__.__name__,
                    "count_pass": 0,
                    "count_fail": 0,
                    "count_check": 0,
                    "last_msg": "",
                }
            count_pass, count_fail = (1, 0) if ck_pass else (0, 1)
            if self.is_batch_success:
                count_fail = 0
            self.check_info[i]["count_pass"] += count_pass
            self.check_info[i]["count_fail"] += count_fail
            self.check_info[i]["last_msg"] = ck_msg
            self.check_info[i]["count_check"] += 1
            if not ck_pass:
                self.check_pass = False
                if self.is_batch_success is False:
                    self.fail_count += 1
                break
        if self.check_pass:
            self.succ_count += 1
            self.continue_fail_count = 0
        else:
            self.continue_fail_count += 1
        return self.check_pass, self.check_info

    def reset_continue_fail_count_with_batch_pass(self):
        self.is_batch_success = True
        self.continue_fail_count = 0

    def is_reached(self):
        return self._is_reached

    def set_reached(self, reached: bool):
        self._is_reached = reached

    def set_fail_count(self, prev_fail_count: int):
        self.fail_count = prev_fail_count

    def set_time_prev_cost(self, prev_time_cost: float):
        self.time_prev_cost = prev_time_cost

    def clear(self):
        self.check_info = [None] * self.check_size

    def get_substages(self)-> list[Self]:
        ret = []
        for s in self.substages:
            ret.extend(s.get_substages())
        if not self.is_group():
            ret.append(self)
        return ret

    def is_group(self):
        return self.check_size == 0 and len(self.output_files) == 0 and len(self.reference_files) == 0 and len(self.substages) > 0

    def get_substage_count(self):
        ret = 0 if self.is_group() else 1
        return sum(s.get_substage_count() for s in self.substages) + ret

    def title(self):
        tname = f"{self.name}-{self.description()}"
        if self.prefix:
            tname = self.prefix + "-" + tname
        return tname

    def title_short(self):
        tshort = f"{self.name}"
        if self.prefix:
            tshort = self.prefix + "-" + tshort
        return tshort

    def detail(self):
        return OrderedDict({
                "task": self.task_info(),
                "section_index": self.prefix,
                "checker": [str(c) for c in self.checker],
                "reached": self.is_reached(),
                "is_completed": self.is_completed(),
                "check_pass": self.check_pass,
                "fail_count": self.fail_count,
                "is_skipped": self.is_skipped(),
                "needs_human_check": self.is_hmcheck_needed(),
                "last_human_check_result": self._hum_check_passed,
                "last_human_check_msg": self._hum_check_msg,
        })

    def description(self):
        desc = copy.deepcopy(self.desc)
        for c in self.checker:
            desc = c.filter_vstage_description(desc)
        return desc

    def task(self):
        assert isinstance(self.task_list, list), "Stage task must be a list of strings."
        task = copy.deepcopy(self.task_list)
        for c in self.checker:
            task = c.filter_vstage_task(task)
        return task

    def set_reference_file_status(self, status: dict):
        for k, v in status.items():
            if k in self.reference_files and "Readed" in v:
                self.reference_files[k] = True

    def task_info(self, with_parent=True):
        data = OrderedDict({
            "title": self.title(),
            "description": self.task(),
            "reference_files":  {k: ("Readed" if v else "Not Read") for k, v in self.reference_files.items()},
            "output_files":     self.output_files,
        })
        if self.cfg.skill.use_skill:
            data["skill_list"] = {k: ["Listed" if u else "Not Listed", "Read" if v else "Not Read", "Used" if w else "Not Used"] for k, [u,v,w] in self.skill_list.items()}
        if with_parent:
            if self.parent:
                data["upper_task"] = self.parent.task_info(with_parent=False)
            if self.substages:
                data["notes"] = f"You have complete this stage's submissions ({', '.join([s.title() for s in self.substages])}), " + \
                                 "now you need to check this stage is complete or not."
        if self.need_human_check and self._hum_check_msg:
            data["last_human_check_result"] = self._hum_check_passed
            data["last_human_check_msg"] = self._hum_check_msg
        return data


def parse_vstage(root_cfg, cfg, workspace, tool_read_text, prefix=""):
    if cfg is None:
        return []
    assert isinstance(cfg, list), "cfg.stage must be a list of VerifyStage configurations."
    ret = []
    for i, stage in enumerate(cfg):
        assert hasattr(stage, 'name'), "Each stage configuration must have a 'name' attribute."
        assert hasattr(stage, 'desc'), "Each stage configuration must have a 'desc' attribute."
        assert hasattr(stage, 'task'), "Each stage configuration must have a 'task' attribute."
        checker = stage.get_value('checker', [])
        output_files = stage.get_value('output_files', [])
        reference_files = stage.get_value('reference_files', [])
        skill_list = stage.get_value('skill_list', [])
        skip = stage.get_value('skip', False)
        ignore = stage.get_value('ignore', False)
        need_fail_llm_suggestion=stage.get_value('need_fail_llm_suggestion', None)
        need_pass_llm_suggestion=stage.get_value('need_pass_llm_suggestion', None)

        if ignore:
            warning(f"Stage '{stage.name}' is set to be ignored, skipping its parsing.")
            continue
        index = i + 1
        substages = parse_vstage(root_cfg, stage.get_value('stage', None), workspace, tool_read_text, prefix + f"{index}.")
        if skip:
            warning(f"Stage '{stage.name}' is set to be skipped.")
            for sb in substages:
                sb.set_skip(True)
        if need_fail_llm_suggestion is not None:
            for sb in substages:
                sb.set_llm_fail_suggestion(need_fail_llm_suggestion)
        if need_pass_llm_suggestion is not None:
            for sb in substages:
                sb.set_llm_pass_suggestion(need_pass_llm_suggestion)
        ret.append(VerifyStage(
            cfg=root_cfg,
            workspace=workspace,
            name=stage.name,
            description=stage.desc,
            task=stage.task,
            checker=checker,
            reference_files=reference_files,
            skill_list=skill_list,
            output_files=output_files,
            tool_read_text=tool_read_text,
            substages=substages,
            prefix=prefix + f"{index}",
            skip=skip,
            need_fail_llm_suggestion=need_fail_llm_suggestion,
            need_pass_llm_suggestion=need_pass_llm_suggestion,
        ))
    return ret


def get_root_stage(cfg, workspace, tool_read_text):
    root = VerifyStage(
        cfg=cfg,
        workspace=workspace,
        name="root",
        description=cfg.mission.name,
        task=[],
        checker=[],
        reference_files=[],
        skill_list=[],
        output_files=[],
    )
    root.substages = parse_vstage(cfg, cfg.stage, workspace, tool_read_text)
    return root
