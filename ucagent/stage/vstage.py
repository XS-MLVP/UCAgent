# -*- coding: utf-8 -*-
"""Verification stage management for UCAgent."""

from ucagent.util.functions import import_class_from_str, find_files_by_pattern
from ucagent.util.log import info, warning
from ucagent.util.config import Config
import ucagent.checkers as checkers
from collections import OrderedDict
import copy
import time

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
                 output_files,
                 prefix = "",
                 skip=False,
                 tool_read_text=None,
                 substages=None):
        """
        Initialize the VerifyStage.
        """
        self.cfg = cfg
        self.name = name
        self.prefix = prefix
        self.skip = skip
        self.desc = description
        self.task_list = convert_task_form_cfg(task)
        self._checker = checker
        self.workspace = workspace
        self.checker = [
            import_class_from_str(c.clss, checkers)(**update_dict(c.args.as_dict(),
                                                                  {"cfg": self.cfg})).set_extra(
                **c.extra_args.as_dict()
            ).set_workspace(workspace) for c in self._checker
        ]
        self.check_size = len(self.checker)
        self.check_info = [None] * self.check_size
        self.fail_count = 0
        self.succ_count = 0
        self.check_pass = False
        self.reference_files = {
            k:False for k in find_files_by_pattern(workspace, reference_files)
        }
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

    def add_reference_files(self, files):
        for f in find_files_by_pattern(self.workspace, files):
            if f not in self.reference_files:
                self.reference_files[f] = False
                info(f"[{self.__class__.__name__}] Reference file {f} added.")

    def on_init(self):
        for c in self.checker:
            c.on_init()
        self.time_start = time.time()

    def on_complete(self):
        if self.time_end is not None:
            return
        self.time_end = time.time()

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

    def is_skipped(self):
        return self.skip

    def set_stage_manager(self, manager):
        assert manager is not None, "Stage Manager cannot be None."
        for c in self.checker:
            c.set_stage_manager(manager)

    def on_file_read(self, success, file_path, content):
        if not success:
            return
        if file_path in self.reference_files:
            self.reference_files[file_path] = True
            info(f"[{self.__class__.__name__}] Reference file {file_path} has been read by the LLM.")

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
        for c in self.checker:
            if c.is_wait_human_check():
                return True
        return False

    def do_hmcheck_pass(self, msg=""):
        """
        Call the hmcheck_pass method of all HumanChecker in this stage.
        """
        ret = []
        for c in self.checker:
            if c.is_human_check_needed():
                ret.append(f"Set '{c.__class__.__name__}' Pass: '{c.human_set_pass_msg(msg)}'")
            else:
                ret.append(f"'{c.__class__.__name__}' does not need human check in stage '{self.name}'.")
        return "\n".join(ret)

    def do_hmcheck_fail(self, msg=""):
        """
        Call the hmcheck_fail method of all HumanChecker in this stage.
        """
        ret = []
        for c in self.checker:
            if c.is_human_check_needed():
                ret.append(f"Set '{c.__class__.__name__}' Fail: '{c.human_set_fail_msg(msg)}'")
            else:
                ret.append(f"'{c.__class__.__name__}' does not need human check in stage '{self.name}'.")
        return "\n".join(ret)

    def do_get_hmcheck_result(self):
        """
        Get the human check result of all HumanChecker in this stage.
        """
        ret = []
        for c in self.checker:
            if c.is_human_check_needed():
                p, m = c.get_last_human_check_result()
                ret.append(f"'{c.__class__.__name__}' Pass: {p}, message: '{m}'.")
            else:
                ret.append(f"'{c.__class__.__name__}' does not need human check.")
        return "\n".join(ret)

    def do_set_hmcheck_needed(self, need: bool):
        """
        Set whether human check is needed for all HumanChecker in this stage.
        """
        ret = []
        if len(self.checker) == 0:
            ret.append("No checker in this stage.")
            return "\n".join(ret)
        for c in self.checker:
            if need is None:
                ret.append(f"'{c.__class__.__name__}' human check needed is '{c.is_human_check_needed()}'.")
                continue
            if c.is_human_check_needed() != need:
                c.set_human_check_needed(need)
                ret.append(f"Set '{c.__class__.__name__}' human check needed to '{need}'.")
            else:
                ret.append(f"'{c.__class__.__name__}' human check needed is already '{need}'.")
        return "\n".join(ret)

    def is_hmcheck_needed(self) -> bool:
        """
        Check whether any HumanChecker in this stage needs human check.
        """
        for c in self.checker:
            if c.is_human_check_needed():
                return True
        return False

    def do_check(self, *a, **kwargs):
        self._is_reached = True
        if not all(c[1] for c in self.reference_files.items()):
            emsg = OrderedDict({"error": "You need use tool `ReadTextFile` to read and understand the reference files", "files_need_read": []})
            for k, v in self.reference_files.items():
                if not v:
                    emsg["files_need_read"].append(k + f" (Not readed, need ReadTextFile('{k}'))")
            self.fail_count += 1
            return False, emsg
        success_out_file = True
        success_out_msg = []
        for k, v in {p: len(find_files_by_pattern(self.workspace, p)) for p in self.output_files}.items():
            if v <= 0:
                success_out_file = False
                success_out_msg.append(k)
        if not success_out_file:
            self.fail_count += 1
            return False, OrderedDict({"error": f"Output file patterns not found in workspace. you need to generate those files.",
                                       "failed_patterns": success_out_msg})
        self.check_pass = True
        for i, c in enumerate(self.checker):
            ck_pass, ck_msg = c.check(*a, **kwargs)
            if self.check_info[i] is None:
                self.check_info[i] = {
                    "name": c.__class__.__name__,
                    "count_pass": 0,
                    "count_fail": 0,
                    "count_check": 0,
                    "last_msg": "",
                    "needs_human_check": c.is_human_check_needed(),
                }
            count_pass, count_fail = (1, 0) if ck_pass else (0, 1)
            self.check_info[i]["count_pass"] += count_pass
            self.check_info[i]["count_fail"] += count_fail
            self.check_info[i]["last_msg"] = ck_msg
            self.check_info[i]["count_check"] += 1
            if not ck_pass:
                self.check_pass = False
                self.fail_count += 1
        if self.check_pass:
            self.succ_count += 1
        return self.check_pass, self.check_info

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

    def detail(self):
        return OrderedDict({
                "task": self.task_info(),
                "section_index": self.prefix,
                "checker": [str(c) for c in self.checker],
                "reached": self.is_reached(),
                "check_pass": self.check_pass,
                "fail_count": self.fail_count,
                "is_skipped": self.is_skipped(),
                "needs_human_check": self.is_hmcheck_needed(),
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
        if with_parent:
            if self.parent:
                data["upper_task"] = self.parent.task_info(with_parent=False)
            if self.substages:
                data["notes"] = f"You have complete this stage's submissions ({', '.join([s.title() for s in self.substages])}), " + \
                                 "now you need to check this stage is complete or not."
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
        skip = stage.get_value('skip', False)
        ignore = stage.get_value('ignore', False)
        if ignore:
            warning(f"Stage '{stage.name}' is set to be ignored, skipping its parsing.")
            continue
        index = i + 1
        substages = parse_vstage(root_cfg, stage.get_value('stage', None), workspace, tool_read_text, prefix + f"{index}.")
        if skip:
            warning(f"Stage '{stage.name}' is set to be skipped.")
            for sb in substages:
                sb.set_skip(True)
        ret.append(VerifyStage(
            cfg=root_cfg,
            workspace=workspace,
            name=stage.name,
            description=stage.desc,
            task=stage.task,
            checker=checker,
            reference_files=reference_files,
            output_files=output_files,
            tool_read_text=tool_read_text,
            substages=substages,
            prefix=prefix + f"{index}",
            skip=skip,
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
        output_files=[],
    )
    root.substages = parse_vstage(cfg, cfg.stage, workspace, tool_read_text)
    return root
