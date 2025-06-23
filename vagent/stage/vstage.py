#coding=utf-8


from vagent.util.functions import import_class_from_str, find_files_by_pattern, dump_as_json
from vagent.util.log import info
import vagent.stage.checkers as checkers


class VerifyStage(object):

    def __init__(self, workspace, name, description, task, checker, reference_files, tool_read_text):
        """
        Initialize the VerifyStage with a name, description, task, checker, and checker arguments.
        Args:
            name (str): The name of the stage.
            description (str): A brief description of the stage.
            task (str): The task to be performed in this stage.
            checker (cfg): An Checker CFG to instance checks.
        """
        self.name = name
        self.description = description
        self.task = task
        self._checker = checker
        self.checker = [
            import_class_from_str(c.clss, checkers)(**c.args.as_dict()).set_extra(
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
        self.tool_read_text = tool_read_text
        self.tool_read_text.append_callback(self.on_file_read)

    def on_file_read(self, success, file_path, content):
        if not success:
            return
        if file_path in self.reference_files:
            self.reference_files[file_path] = True
            info(f"[{self.__class__.__name__}] Reference file {file_path} has been read by the LLM.")

    def __repr__(self):
        return f"VerifyStage(name={self.name}, description={self.description}, "+\
               f"checker={'.'.join([n.name for n in self._checker])}, checker_cls={'.'.join([n.clss for n in self._checker])})"

    def do_check(self):
        if not all(c[1] for c in self.reference_files.items()):
            emsg = "You need read and understand all the reference files:\n"
            for k, v in self.reference_files.items():
                emsg += f"  - {k} ({'Read Pass'if v else 'Not Read'})\n"
            return False, emsg
        self.check_pass = True
        for i, c in enumerate(self.checker):
            ck_pass, ck_msg = c.check()
            if self.check_info[i] is None:
                self.check_info[i] = {
                    "name": c.__class__.__name__,
                    "count_pass": 0,
                    "count_fail": 0,
                    "count_check": 0,
                    "last_msg": "",
                }
            count_pass, count_fail = (1, 0) if ck_pass else (0, 1)
            self.check_info[i]["count_pass"] += count_pass
            self.check_info[i]["count_fail"] += count_fail
            self.check_info[i]["last_msg"] = ck_msg
            self.check_info[i]["count_check"] += 1
            if not ck_pass:
                self.check_pass = False
                self.fail_count += 1
            else:
                self.succ_count += 1
        return self.check_pass, self.check_info

    def is_reached(self):
        """
        Check if the stage is reached.
        This can be implemented based on specific conditions or checks.
        """
        # Placeholder for actual implementation
        reached = True
        for c in self.checker:
            if c is None:
                reached = False
                break
        return reached

    def clear(self):
        """
        Clear the stage's checker information.
        This can be useful for resetting the stage state.
        """
        self.check_info = [None] * self.check_size


from langchain_core.callbacks import (
    CallbackManagerForToolRun,
)
from vagent.tools.uctool import UCTool
from langchain_core.tools.base import ArgsSchema
from typing import Optional, Callable
from collections import OrderedDict
from pydantic import BaseModel, Field
import json


class ManagerTool(UCTool):
    # custom vars
    function: Callable = None
    def _run(self, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        return self.function()

    def set_function(self, func):
        self.function = func
        return self


class ToolStatus(ManagerTool):
    """List current missoin status."""
    name: str = "Status"
    description: str = (
        "Returns the current status of your mission."
    )

class ToolDetail(ManagerTool):
    """Get current missoin detials."""
    name: str = "Detail"
    description: str = (
        "Returns the detail info of your mission, including all stages and their details. \n"
    )


class ToolDoCheck(ManagerTool):
    """Check your stage's mertrics are matched with the requirements or not."""
    name: str = "Check"
    description: str = (
        "Check your stage's metrics are matched with the requirements or not. \n"
        "When each you have do some work, you should call this tool to check your work is correct. \n"
        "Returns the result of the check."
    )


class ToolDoComplete(ManagerTool):
    """Tell the manager that you have completed the current stage."""
    name: str = "Complete"
    description: str = (
        "Tell the manager that you have completed the current stage. \n"
        "When you complete a stage, your should have passed all checks in the stage. \n"
        "You should double check your work before calling this tool. \n"
        "Returns the result of the completion."
    )


class ArgToolGoToStage(BaseModel):
    index: int = Field(
        default=-1,
        description="Stage index to go to. "
    )


class ToolGoToStage(ManagerTool):
    """Go to a specific stage by index."""
    name: str = "GoToStage"
    description: str = (
        "Go to a specific stage by index. Only those stages that have been reached can be selected. \n"
        "Stage is reached means that all checks in the stage have been passed. \n"
        "This tool is used when you want refine your previous work, or want to go back to a previous stage. \n"
        "Returns the result of the operation."
    )
    args_schema: Optional[ArgsSchema] = ArgToolGoToStage

    def _run(self, index:int=-1, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        return self.function(index)


class StageManager(object):
    def __init__(self, workspace, cfg, agent, tool_read_text):
        """
        Initialize the StageManager with an empty list of stages.
        """
        self.workspace = workspace
        self.stages = [
            VerifyStage(
                workspace=workspace,
                name=f.name,
                description=f.desc,
                task=f.task,
                checker=f.checker,
                reference_files=f.get_value("reference_files", []),
                tool_read_text = tool_read_text,
            ) for f in cfg.stage
        ]
        assert len(cfg.stage) == len(set([f.name for f in cfg.stage])), "Stage names must be unique."
        self.mission = cfg.mission
        self.agent = agent
        info(f"Initialized StageManager with {len(self.stages)} stages.")
        info("Stages:")
        for stage in self.stages:
            info(f"  - {stage.name}: {stage.description}")
        self.stage_index = 0
        self.last_check_info = None
        self.tool_read_text = tool_read_text

    def new_tools(self):
        """
        Create and return a list of tools for the current stage.
        """
        tools = [
            ToolDetail().set_function(self.tool_detail),
            ToolStatus().set_function(self.tool_status),
            ToolDoCheck().set_function(self.tool_check),
            ToolDoComplete().set_function(self.tool_complete),
            ToolGoToStage().set_function(self.tool_go_to_stage)
        ]
        return tools

    def get_current_tips(self):
        cstage = self.stages[self.stage_index]
        task = '\n - '.join(cstage.task)
        ret = str(f"You mission: {self.mission.name}\n"
                  f"Current stage: {cstage.name} - "
                  f"{cstage.description}\n"
                  f"Passed/Total stages: {self.stage_index}/{len(self.stages)}\n"
                  f"Your task detail: \n{task}\n"
                  )
        ref_files = []
        for k, v in cstage.reference_files.items():
            if v:
                continue
            ref_files.append(k)
        if ref_files:
            ret += f"\nYou need read (use tool: {self.tool_read_text.name}) and understand the following reference files:\n"
            for f in ref_files:
                ret += f"  - {f}\n"
        return ret

    def detail(self):
        """
        Get the details of the current mission, including all stages and their details.
        """
        ret = OrderedDict()
        ret["mission"] = self.mission.name
        ret["stage_list"] = OrderedDict()
        for i, stage in enumerate(self.stages):
            ret["stage_list"][stage.name] = {
                "index": i,
                "desc": stage.description,
                "task": stage.task,
                "checker": [str(c) for c in stage.checker],
                "reached": stage.is_reached(),
                "check_pass": stage.check_pass,
                "fail_count": stage.fail_count,
            }
        return ret

    def tool_detail(self):
        """
        Get the details of the current mission, including all stages and their details.
        """
        return dump_as_json(self.detail())

    def status(self):
        ret = OrderedDict()
        ret["stage_list"] = []
        for i, stage in enumerate(self.stages):
            ret["stage_list"].append((stage.name, {
                "index": i,
                "desc":stage.description,
                "reached": stage.is_reached(),
                "check_pass": stage.check_pass,
                "fail_count": stage.fail_count,
            }))
        ret["current_stage_index"] = self.stage_index
        ret["current_task"] = self.stages[self.stage_index].task if self.stages else "No stages available"
        cstage = self.stages[self.stage_index] if self.stage_index < len(self.stages) else None
        if cstage:
            ret["reference_files_to_read"] = [f for f, v in cstage.reference_files.items() if not v]
        if self.last_check_info:
            ret["last_check_info"] = self.last_check_info
        return ret

    def tool_status(self):
        return dump_as_json(self.status())

    def tool_go_to_stage(self, index):
        return self.go_to_stage(index)

    def go_to_stage(self, index):
        """
        Go to a specific stage by index.
        """
        if 0 <= index < len(self.stages):
            if index == self.stage_index:
                return f"Already at stage {index}: {self.stages[index].name}."
            if self.stages[index].is_reached():
                self.stage_index = index
                return f"Changed to stage {index}: {self.stages[index].name} success."
            return f"Stage {index} is not reached yet. Can only go to stages that have been reached."
        else:
            return f"Invalid stage index: {index}. No change made."

    def check(self):
        ck_pass, ck_info = self.stages[self.stage_index].do_check()
        self.last_check_info = {
            "check_info": ck_info,
            "check_pass": ck_pass,
        }
        return {
            "check_pass": ck_pass,
            "check_info": ck_info,
        }

    def tool_check(self):
        return dump_as_json(self.check())

    def complete(self):
        if self.stage_index >= len(self.stages):
            return dump_as_json({
                "do_complete": False,
                "message": "No more stages to complete.",
            })
        ck_pass, ck_info = self.stages[self.stage_index].do_check()
        self.last_check_info = {
            "check_info": ck_info,
            "check_pass": ck_pass,
        }
        if ck_pass:
            self.stage_index += 1
            message = f"Stage {self.stage_index - 1} completed successfully."
            if self.stage_index >= len(self.stages):
                message = "All stages completed successfully."
                self.agent.exit()  # Exit the agent if all stages are completed
            message += f"\nCurrent stage index is now {self.stage_index}."
            message += f"\nNext task:\n {self.get_current_tips()}"
        else:
            message = f"Stage {self.stage_index} not completed. Please check the requirements.\n" + \
                      f"Last check info: \n {json.dumps(ck_info, indent=2, ensure_ascii=False)}"
        return {
            "do_complete": ck_pass,
            "message": message,
        }

    def tool_complete(self):
        return dump_as_json(self.complete())

