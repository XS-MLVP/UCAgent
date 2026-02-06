from .uctool import UCTool
from langchain_core.tools.base import ArgsSchema
from typing import Optional, List
from pydantic import Field
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain.agents import create_agent
import random
from ..util.functions import get_ai_message_tool_call
from ucagent.util.models import get_chat_model

class SubAgentTool(UCTool):
    name: str = "SubAgentTool"
    description: str = ("Create a new agent to finish the sub-mission.")
    args_schema: Optional[ArgsSchema] = None
    tool_list : List[any] = Field(default=[], description="子 Agent 可用的工具列表")
    agent : any = Field(default=None, description="主 Agent 实例")

    def __init__(self,tool_list, agent):
        super().__init__()
        self.tool_list = tool_list
        self.agent = agent

    def _run(self,message:str) -> str:
        """Get the role prompt and message of the sub agent, then create and run the sub agent."""
        # 获取当前阶段的 sub_agent 配置
        current_stage = self.agent.stage_manager.get_current_stage()
        sub_agent = self.agent.cfg.agents[current_stage.sub_agent]

        # 获取子 Agent 的 model 配置
        model = get_chat_model(sub_agent.model, self.agent.cfg, [self.agent.backend.cb_token_speed] if self.agent.stream_output else None)

        # 获取子 Agent 的角色提示
        role_prompt = sub_agent.system

        messages = [
                SystemMessage(content=role_prompt),
                HumanMessage(content=message)
            ]
        sub_agent = create_agent(
            model=model,
            tools=self.tool_list,
            middleware=[self.agent.message_manage_node],
        )

        thread_id = random.randint(100000, 999999)
        work_config = {
            "configurable": {"thread_id": f"{thread_id}"},
            "recursion_limit": self.agent.cfg.get_value("recursion_limit", 100000),
        }
        if self.agent.langfuse_enable:
            work_config["callbacks"] = [self.agent.langfuse_handler]
            work_config["metadata"] = {
                "langfuse_session_id": self.agent.session_id.hex,
            }

        last_msg_index = None
        fist_ai_message = True
        last_msg = None
        for v, data in sub_agent.stream({"messages": messages}, work_config, stream_mode=["values", "messages"]):
            if v == "messages":
                if fist_ai_message:
                    fist_ai_message = False
                    self.agent.message_echo("\n\n================================== AI Message ==================================")
                msg = data[0]
                self.agent.message_echo(msg.content, end="")
            else:
                index = len(data["messages"])
                if index == last_msg_index:
                    continue
                last_msg_index = index
                msg = data["messages"][-1]
                last_msg = msg
                self.agent.backend.state_record_mesg(msg)
                if isinstance(msg, AIMessage):
                    self.agent.message_echo(get_ai_message_tool_call(msg))
                    self.agent.backend.check_tool_call_error(msg)
                    continue
                self.agent.message_echo("\n"+msg.pretty_repr())
        if last_msg:
            return f"阶段任务完成,使用`Complete`工具推进到下一阶段\n"
        return "子 Agent 执行完成但未返回结果"