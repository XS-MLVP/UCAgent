#coding=utf-8


import inspect
from vagent.util.functions import yam_str
from vagent.util.log import info
from collections import OrderedDict
import json


from langchain_core.callbacks import (
    CallbackManagerForToolRun,
)
from vagent.tools.uctool import UCTool, EmptyArgs
from langchain_core.tools.base import ArgsSchema
from typing import Optional, Callable
from pydantic import BaseModel, Field
from vagent.stage.vstage import get_root_stage


class ManagerTool(UCTool):
    # custom vars
    function: Callable = None
    args_schema: Optional[ArgsSchema] = EmptyArgs
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


class ToolCurrentTips(ManagerTool):
    """Get tips for the current task."""
    name: str = "CurrentTips"
    description: str = (
        "Returns the tips for the current task."
    )


class ToolDetail(ManagerTool):
    """Get current missoin detials."""
    name: str = "Detail"
    description: str = (
        "Returns the detail info of your mission, including all stages and their details. \n"
    )


class ToolKillCheck(ManagerTool):
    """Kill the current check process."""
    name: str = "KillCheck"
    description: str = (
        "Kill the current check process. \n"
        "This tool is only used when the tool 'Check' is long time running or get stuck. \n"
    )


class ArgStdCheck(BaseModel):
    lines: int = Field(
        default=-1,
        description="lines to read, -1 means read all"
    )


class ToolStdCheck(ManagerTool):
    """get the standard output of the current check process."""
    name: str = "StdCheck"
    description: str = (
        "Get the standard output of the current check process. \n"
        "This tool is only used to get the output of the runnig tool 'Check'. \n"
        "You can specify the number of lines to read, -1 means read all lines. \n"
    )
    args_schema: Optional[ArgsSchema] = ArgStdCheck
    def _run(self, lines: int = -1, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        return self.function(lines)


class ArgCheck(BaseModel):
    target: str = Field(
        default="",
        description=(
            "Target test cases to run, supports pytest-style arguments for precise test selection. "
            "Examples:\n"
            "• '' (empty): Run all test cases in the test directory\n"
            "• 'test_file.py': Run all tests in a specific file\n"
            "• 'test_file.py::test_function': Run a specific test function\n"
            "• 'test_file.py::TestClass::test_method': Run a specific test method in a class\n"
            "• '-k pattern': Run tests matching the given pattern\n"
            "• '-m marker': Run tests with specific markers\n"
            "Only applicable in stage 'comprehensive_verification_execution' for focused testing. "
            "In other stages, this parameter is ignored and all configured checks are performed."
        )
    )

    class Config:
        """Pydantic model configuration."""
        # Add validation examples for better documentation
        schema_extra = {
            "examples": [
                {"target": ""},
                {"target": "test_adder.py"},
                {"target": "test_adder.py::test_basic_addition"},
                {"target": "test_adder.py::TestAdder::test_overflow"},
                {"target": "-k overflow"},
                {"target": "-m slow"}
            ]
        }


class ToolDoCheck(ManagerTool):
    """Advanced validation tool for stage requirements and implementation quality."""
    name: str = "Check"
    description: str = (
        "Perform comprehensive validation of your current stage's implementation against requirements.\n"
        "The tool provides detailed feedback. Call this tool frequently during development to ensure continuous quality validation."
    )
    args_schema: Optional[ArgsSchema] = ArgCheck

    def _run(self, target: str = "", run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """
        Execute stage validation with enhanced error handling and reporting.
        
        Args:
            target: Test target specification (pytest format)
            run_manager: Callback manager for tool execution
            
        Returns:
            str: Comprehensive validation report in JSON format
        """
        try:
            return self.function(target)
        except Exception as e:
            error_msg = f"Validation failed: {str(e)}"
            info(error_msg)
            return yam_str({
                "check_pass": False,
                "check_info": error_msg
            })


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


class ToolDoExit(ManagerTool):
    """Exit the agent and end the mission after all stages are completed."""
    name: str = "Exit"
    description: str = (
        "Exit the agent and end the mission after all stages are completed. \n"
        "This tool is used when you have completed all stages and want to exit the agent. \n"
        "Returns a message indicating the exit status."
    )


class StageManager(object):
    def __init__(self, workspace, cfg, agent, tool_read_text, force_stage_index=0):
        """
        Initialize the StageManager with an empty list of stages.
        """
        self.workspace = workspace
        self.root_stage = get_root_stage(cfg, workspace, tool_read_text)
        self.stages = self.root_stage.get_substages()
        self.mission = cfg.mission
        self.agent = agent
        info(f"Initialized StageManager with {len(self.stages)} stages.")
        info("Stages:\n" + "\n".join([f"{i:2d}:   {stage.title()}" for i, stage in enumerate(self.stages)]))
        self.stage_index = min(max(0, force_stage_index), len(self.stages) - 1)
        for i in range(self.stage_index):
            self.stages[i].set_reached(True)
        self.last_check_info = None
        self.tool_read_text = tool_read_text
        self.all_completed = False

    def new_tools(self):
        """
        Create and return a list of tools for the current stage.
        """
        tools = [
            ToolCurrentTips().set_function(self.tool_current_tips),
            ToolDetail().set_function(self.tool_detail),
            ToolStatus().set_function(self.tool_status),
            ToolDoCheck().set_function(self.tool_check),
            ToolKillCheck().set_function(self.tool_kill_check),
            ToolStdCheck().set_function(self.tool_std_check),
            ToolDoComplete().set_function(self.tool_complete),
            ToolGoToStage().set_function(self.tool_go_to_stage),
            ToolDoExit().set_function(self.tool_exit),
        ]
        return tools

    def get_current_tips(self):
        if self.stage_index >= len(self.stages):
            return "Your mission is completed. No more stages available. Or you can use `GoToStage` tool to go to a specific stage."
        cstage = self.stages[self.stage_index]
        tips = OrderedDict()
        tips["mission"]       = self.mission.name
        tips["stage_title"]   = cstage.title()
        tips["stage_index"]   = self.stage_index
        tips["current_task"]  = cstage.task_info()
        ref_files = []
        for k, v in cstage.reference_files.items():
            if v:
                continue
            ref_files.append(k)
        if ref_files:
            tips["notes"] = f"You need use tool: {self.tool_read_text.name} to read the reference files."
        tips["process"] = f"{self.stage_index}/{len(self.stages)}"
        return tips

    def detail(self):
        """
        Get the details of the current mission, including all stages and their details.
        """
        ret = OrderedDict()
        ret["mission"] = self.mission.name
        ret["stage_list"] = OrderedDict()
        for i, stage in enumerate(self.stages):
            ret["stage_list"][stage.name] = stage.detail()
            ret["stage_list"][stage.name]["index"] = i
        ret["current_stage_index"] = self.stage_index
        ret["current_stage_name"] = self.stages[self.stage_index].name if self.stage_index < len(self.stages) else None
        return ret

    def status(self):
        ret = OrderedDict()
        ret["mission"] = self.mission.name
        ret["stage_list"] = []
        for i, stage in enumerate(self.stages):
            ret["stage_list"].append({
                "index": i, 
                "title": stage.title() + ("<Your are working here>" if i == self.stage_index else ""),
                "reached": stage.is_reached(),
            })
        ret["process"] = f"{self.stage_index}/{len(self.stages)}"
        cstage = self.stages[self.stage_index] if self.stage_index < len(self.stages) else None
        ret["current_task"] = "No stages available (Maybe mission is completed, you can use the `GoToStage` tool to go back to a previous stage if needed)"
        if cstage:
            ret["current_stage_index"] = self.stage_index
            ret["current_stage_name"] = cstage.name
            ret["current_task"] = cstage.task_info()
        ret["last_check_result"] = self.last_check_info
        return ret

    def go_to_stage(self, index):
        """
        Go to a specific stage by index.
        """
        success = False
        if 0 <= index < len(self.stages):
            if index == self.stage_index:
                msg = f"Already at stage {index}: {self.stages[index].name}."
                success = True
            elif self.stages[index].is_reached():
                self.stage_index = index
                msg = f"Changed to stage {index}: {self.stages[index].name} success."
                success = True
            else:
                msg = f"Stage {index} is not reached yet. Can only go to stages that have been reached. You can use tool `ToolStaus` to find all reached stages."
        else:
            msg = f"Invalid stage index: {index}. No change made."
        return {"message": msg, "success": success}

    def check(self, target: str):
        if not self.stage_index < len(self.stages):
            return OrderedDict({
                "check_pass": False,
                "check_info": f"Stage index{self.stage_index} out of range. (Mission maybe completed, you can use the `GoToStage` tool to go back to a previous stage if needed)",
            })
        func_check = self.stages[self.stage_index].do_check
        args = []
        if len(inspect.signature(func_check).parameters) > 1:
            args = [target]
        info(f"Running check for stage {self.stage_index} with args: {args}")
        ck_pass, ck_info = func_check(*args)
        self.last_check_info = {
            "check_info": ck_info,
            "check_pass": ck_pass,
        }
        return OrderedDict({
            "check_pass": ck_pass,
            "check_info": ck_info,
        })


    def complete(self):
        if self.stage_index >= len(self.stages):
            return {
                "complete": False,
                "message": ("No more stages to complete. You can review your work and use the `GoToStage` tool to go back to a previous stage if needed."
                            "Or you can use the `Exit` tool to exit the mission."),
                "last_check_result": self.last_check_info,
            }
        ck_pass, ck_info = self.stages[self.stage_index].do_check()
        self.last_check_info = {
            "check_info": ck_info,
            "check_pass": ck_pass,
        }
        if ck_pass:
            self.stage_index += 1
            message = f"Stage {self.stage_index - 1} completed successfully."
            if self.stage_index >= len(self.stages):
                message = ("All stages completed successfully."
                           "Now you should review your work to check if everything is correct and all the users needs are matched."
                           "When you are confident that everything is fine, you can use the `Exit` tool to exit the mission."
                           )
                self.all_completed = True
            else:
                message += f"Current stage index is now {self.stage_index}. Use `CurrentTips` tool to get your new task."
        else:
            message = f"Stage {self.stage_index} not completed. Please check the task requirements."
        return {
            "complete": ck_pass,
            "message": message,
            "last_check_result": self.last_check_info,
        }

    def exit(self):
        """
        Exit the agent and end the mission after all stages are completed.
        """
        if self.all_completed:
            self.agent.exit()  # Exit the agent if all stages are completed
            return {
                "exit": True,
                "message": "All stages completed. Exiting the mission."
            }
        return {
            "exit": False,
            "message": "Not all stages are completed yet. Please complete all stages before exiting."
        }

    def tool_detail(self):
        """
        Get the details of the current mission, including all stages and their details.
        """
        detail = yam_str(self.detail())
        info("ToolDetail:\n" + detail)
        return detail

    def tool_status(self):
        stat = yam_str(self.status())
        info("ToolStaus:\n" + stat)
        return stat

    def tool_go_to_stage(self, index):
        ret = yam_str(self.go_to_stage(index))
        info("ToolGoToStage:\n" + ret)
        return ret

    def tool_check(self, target):
        ret = yam_str(self.check(target))
        info("ToolCheck:\n" + ret)
        return ret

    def tool_exit(self):
        ret = yam_str(self.exit())
        info("ToolExit:\n" + ret)
        return ret

    def tool_complete(self):
        ret = yam_str(self.complete())
        info("ToolComplete:\n" + ret)
        return ret

    def tool_kill_check(self):
        """
        Kill the current check process.
        This is used when the tool 'Check' is long time running or get stuck.
        """
        if not self.stage_index < len(self.stages):
            return f"Stage index({self.stage_index}) out of range. (Maybe mission is completed, you can use the `GoToStage` tool to go back to a previous stage if needed)"
        stage = self.stages[self.stage_index]
        ret = stage.do_kill()
        info("KillCheck:\n" + ret)
        return ret

    def tool_std_check(self, lines=-1):
        """
        Get the standard output of the current check process.
        This tool is only used to get the output of the running tool 'Check'.
        You can specify the number of lines to read, -1 means read all lines.
        """
        if not self.stage_index < len(self.stages):
            return f"Stage index({self.stage_index}) out of range. (Maybe mission is completed, you can use the `GoToStage` tool to go back to a previous stage if needed)"
        stage = self.stages[self.stage_index]
        ret = stage.do_std(lines)
        info("StdCheck:\n" + ret)
        return ret

    def tool_current_tips(self):
        """
        Get the tips for the current task.
        This is used to provide guidance to the user on what to do next.
        """
        tips = yam_str(self.get_current_tips())
        info("Tips:\n" + tips)
        return tips
