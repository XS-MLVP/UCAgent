# LLM Check & Refinement

## 一、背景

### 1.1 传统验证流程的挑战

在 UCAgent 的自动化验证流程中，Checker 负责判断每个验证阶段（Stage）是否完成。传统的 Checker 通常基于规则或简单的模式匹配，虽然执行速度快，但存在以下局限：

1. **假阴性（False Negative）**：Checker 可能过于严格，将实际已完成的任务判定为失败，导致不必要的重试
2. **假阳性（False Positive）**：Checker 可能过于宽松，将未完全满足要求的结果判定为通过，导致验证质量下降
3. **缺乏语义理解**：基于规则的 Checker 难以理解复杂的语义关系，无法对失败原因进行深入分析
4. **建议不够精准**：当验证失败时，简单的错误信息往往无法帮助 Agent 快速定位问题根源

### 1.2 LLM Check & Refinement 的价值

为了解决上述问题，UCAgent 引入了 **LLM Check & Refinement** 功能，将"LLM 专家"作为二次评估和指导角色，提供更智能的验证决策：

- **失败优化（Fail Refinement）**：当 Checker 检查失败时，LLM 专家深入分析错误原因，提供具体的修复建议和优化方向
- **通过验收（Pass Check）**：当关键阶段初步通过时，LLM 专家进行二次确认，确保验证质量符合高标准，防止假阳性

这种机制相当于在验证流程中引入了一个经验丰富的专家顾问，能够：

- 理解复杂的错误信息和上下文关系
- 提供有针对性的修复建议而非简单的错误提示
- 在关键节点进行质量把关，提高验证的可靠性
- 减少因误判导致的重复工作，提升验证效率

---

## 二、使用配置

### 2.1 配置方式概览

LLM Check & Refinement 功能通过 `ucagent/setting.yaml` 中的 `vmanager.llm_suggestion` 部分进行配置，支持两种配置方式：

1. **YAML 配置文件**：在 `setting.yaml` 或项目特定配置文件中配置
2. **环境变量**：通过环境变量快速启用和配置

**前置要求**：该功能需要使用 API 模式的 LLM 后端（如 Claude Code、Qwen Code 等代码智能体），不支持纯本地模型。

### 2.2 Fail Refinement 配置

#### 2.2.1 功能说明

当 Checker 检查失败时，LLM 专家会分析错误原因并给出具体的修复建议。为避免频繁调用，**默认在连续失败 3 次后才触发**。

#### 2.2.2 YAML 配置

在 `ucagent/setting.yaml` 中添加以下配置：

```yaml
vmanager:
  llm_suggestion:
    check_fail_refinement:
      enable: $(ENABLE_LLM_FAIL_SUGGESTION: false)  # 默认不启用，将false改为true即可启用
      clss: ucagent.stage.llm_suggestion.OpenAILLMFailSuggestion  # 实现类
      args:
        model_name: $(PASS_SUGGESTION_MODEL: <your_chat_model_name>)  # 使用的模型名称
        openai_api_key: $(PASS_SUGGESTION_API_KEY: <your_api_key>)  # API 密钥
        openai_api_base: $(PASS_SUGGESTION_API_BASE: http://<your_chat_model_url>/v1)  # API 基础 URL
        ignore_labels: [("<think>", "</think>")]  # 忽略的标签，默认忽略思考过程
        min_fail_count: 3  # 触发失败建议的最小失败次数，默认为 3
        summary_trigger_tokens: 32768  # 触发对话摘要的 token 数，默认 32k
        summary_keep_messages: 10  # 摘要后保留的消息数，默认 10
      system_prompt: | #默认已经配置为英文且写好
        你是一个专业的硬件验证测试助手，负责分析测试失败原因并提供改进建议。
        你需要根据测试失败的信息，分析可能的原因，并给出具体的修复建议。
      suggestion_prompt: | #默认已经配置为英文且写好
        当前测试阶段失败，请分析失败原因并提供具体的修复建议：
        - 分析错误信息的含义
        - 指出可能的问题根源
        - 提供具体的修复步骤和建议
      bypass_stages: []  # 跳过 LLM 检查的阶段列表（阶段名称）
      target_stages: []  # 仅针对这些阶段启用（为空则根据 default_apply_all_stages 判断）
      default_apply_all_stages: true  # 是否默认应用到所有阶段
```

#### 2.2.3 环境变量配置

快速启用方式，适合临时测试：

```bash
export ENABLE_LLM_FAIL_SUGGESTION=true
export FAIL_SUGGESTION_MODEL=<your_chat_model_name>
export FAIL_SUGGESTION_API_KEY=<your_api_key>
export FAIL_SUGGESTION_API_BASE=<your_api_key_base>
```

### 2.3 Pass Check 配置

#### 2.3.1 功能说明

当 Checker 判定某个关键阶段通过时，LLM 专家会再次审查任务完成质量。只有经过 LLM 显式批准后，阶段才算最终完成。这个机制能有效防止假阳性问题。

#### 2.3.2 YAML 配置

```yaml
vmanager:
  llm_suggestion:
    check_pass_refinement:
      enable: $(ENABLE_LLM_PASS_SUGGESTION: false) # 默认不启用，将false改为true即可启用
      clss: ucagent.stage.llm_suggestion.OpenAILLMPassSuggestion  # 实现类，默认已配置
      args:
        model_name: $(PASS_SUGGESTION_MODEL: <your_chat_model_name>)
        openai_api_key: $(PASS_SUGGESTION_API_KEY: <your_api_key>)
        openai_api_base: $(PASS_SUGGESTION_API_BASE: http://<your_chat_model_url>/v1)
        ignore_labels: [("<think>", "</think>")]
        summary_trigger_tokens: 65536  # Pass Check 使用更大的 token 阈值（64k）
        summary_keep_messages: 10
      system_prompt: | #默认已经配置为英文且写好
        你是一个专业的验证专家，负责对已通过初步检查的任务进行二次审核。
        你需要评估任务完成的质量，确保其符合高标准要求。
        如果发现问题，需要明确指出；如果质量合格，需要显式批准。
      suggestion_prompt: | #默认已经配置为英文且写好
        当前测试阶段已通过初步检查，请进行二次审核：
        - 评估任务完成的完整性和准确性
        - 检查是否存在遗漏或潜在问题
        - 如果质量合格，请使用 ApproveStagePass 工具批准
        - 如果存在问题，请明确指出需要改进的地方
      bypass_stages: []
      target_stages: []  # 建议针对关键阶段（如 Complete）启用
      default_apply_all_stages: true
```

#### 2.3.3 环境变量配置

```bash
export ENABLE_LLM_PASS_SUGGESTION=true
export PASS_SUGGESTION_MODEL=<your_chat_model_name>
export PASS_SUGGESTION_API_KEY=<your_api_key>
export PASS_SUGGESTION_API_BASE=<your_api_key_base>
```

### 2.4 阶段过滤配置

通过以下参数可以精确控制 LLM Check 应用于哪些验证阶段：

| 参数                       | 说明                                          | 默认值 | 优先级 |
| -------------------------- | --------------------------------------------- | ------ | ------ |
| `bypass_stages`            | 跳过的阶段列表，这些阶段不会触发 LLM 检查     | `[]`   | 最高   |
| `target_stages`            | 仅针对这些阶段启用 LLM 检查                   | `[]`   | 中     |
| `default_apply_all_stages` | 当 `target_stages` 为空时，是否应用到所有阶段 | `true` | 最低   |

**过滤逻辑**：

1. 如果阶段在 `bypass_stages` 中 → **跳过**
2. 如果 `target_stages` 非空且阶段不在其中 → **跳过**
3. 如果 `target_stages` 为空且 `default_apply_all_stages` 为 `false` → **跳过**
4. 其他情况 → **应用 LLM 检查**

**配置示例**：

```yaml
# 仅对 Complete 阶段启用 Pass Check
check_pass_refinement:
  enable: true
  target_stages: ["Complete"]
  default_apply_all_stages: false

# 对所有阶段启用 Fail Refinement，但跳过 Parse 阶段
check_fail_refinement:
  enable: true
  bypass_stages: ["Parse"]
  default_apply_all_stages: true
```

### 2.5 配置参数详解

#### 通用参数

| 参数                     | 说明                           | 默认值                      | 是否必需 |
| ------------------------ | ------------------------------ | --------------------------- | -------- |
| `enable`                 | 是否启用该功能                 | `false`                     | 是       |
| `clss`                   | 实现类的完整路径               | -                           | 是       |
| `model_name`             | LLM 模型名称                   | -                           | 是       |
| `openai_api_key`         | API 密钥                       | -                           | 是       |
| `openai_api_base`        | API 基础 URL                   | -                           | 是       |
| `ignore_labels`          | 忽略的标签对（如思考过程标签） | `[("<think>", "</think>")]` | 否       |
| `summary_trigger_tokens` | 触发对话摘要的 token 阈值      | Fail: 32768, Pass: 65536    | 否       |
| `summary_keep_messages`  | 摘要后保留的消息数             | `10`                        | 否       |

#### Fail Refinement 特有参数

| 参数             | 说明                           | 默认值 |
| ---------------- | ------------------------------ | ------ |
| `min_fail_count` | 触发失败建议的最小连续失败次数 | `3`    |

#### Pass Check 特有参数

Pass Check 会为 LLM 专家提供 `ApproveStagePass` 工具，LLM 必须调用此工具来批准或拒绝阶段完成。

---

## 三、原理

### 3.1 架构概览

LLM Check & Refinement 功能基于 LangChain 框架实现，主要涉及以下模块：

```
验证流程 (verify_agent.py)
    ↓
阶段管理器 (StageManager in vmanager.py)
    ↓
验证阶段 (VerifyStage in vstage.py)
    ↓
LLM 建议系统
    ├── Fail Refinement (OpenAILLMFailSuggestion)
    └── Pass Check (OpenAILLMPassSuggestion)
```

核心实现文件：

- **基类定义**：`ucagent/stage/llm_suggestion.py` - `BaseLLMSuggestion` 基类和工厂函数
- **LangChain 实现**：`ucagent/stage/langchain_suggestion.py` - 两种建议类的具体实现
- **集成管理**：`ucagent/stage/vmanager.py` - `StageManager` 类中的集成逻辑
- **阶段管理**：`ucagent/stage/vstage.py` - `VerifyStage` 类中的状态管理

### 3.2 初始化流程

#### 3.2.1 系统启动时的初始化

在 `verify_agent.py` 第 152 行，验证流程启动时会创建 `StageManager` 实例：

```python
# verify_agent.py
vmanager = StageManager(
    agent=agent,
    setting=setting,
    # ...
)
```

`StageManager.__init__()` 在 `vmanager.py` 第 260 行初始化，会调用 `init_stage()` 方法（第 332 行）为每个验证阶段创建 LLM 建议实例。

#### 3.2.2 LLM 建议实例的创建

在 `vmanager.py` 的 `init_stage()` 方法中（第 332 行附近）：

```python
def init_stage(self, vstage: VerifyStage):
    """初始化阶段，创建 LLM 建议实例"""

    # 创建 Fail Refinement 实例
    if self.need_fail_llm_suggestion:
        vstage.llm_fail_suggestion = get_llm_check_instance(
            vstage=vstage,
            setting=self.setting['llm_suggestion']['check_fail_refinement'],
            agent_tools=self.tool_inspect_file  # 提供文件检查工具
        )

    # 创建 Pass Check 实例
    if self.need_pass_llm_suggestion:
        vstage.llm_pass_suggestion = get_llm_check_instance(
            vstage=vstage,
            setting=self.setting['llm_suggestion']['check_pass_refinement'],
            agent_tools=self.tool_inspect_file + [self.tool_approve_stage]  # 额外提供批准工具
        )
```

**关键点**：

- `tool_inspect_file`：包含 `ReadTextFile`、`ListDir`、`SearchText` 等文件操作工具
- `tool_approve_stage`：`ApproveStagePass` 工具，仅提供给 Pass Check 使用
- 工厂函数 `get_llm_check_instance()` 根据配置中的 `clss` 参数动态创建实例

#### 3.2.3 VerifyStage 的状态属性

每个 `VerifyStage` 实例维护以下状态（`vstage.py`）：

```python
class VerifyStage:
    def __init__(self, ...):
        # LLM 建议相关属性
        self.need_fail_llm_suggestion: bool  # 是否需要失败建议
        self.need_pass_llm_suggestion: bool  # 是否需要通过验收
        self.continue_fail_count: int = 0    # 连续失败计数器（第 79 行）
        self._approved: bool = False          # LLM 批准状态（第 93 行）

        # LLM 建议实例
        self.llm_fail_suggestion = None
        self.llm_pass_suggestion = None
```

### 3.3 Fail Refinement 流程

#### 3.3.1 触发条件

当 Agent 调用 `Check` 工具检查阶段完成情况时，触发以下流程：

```
Agent.check(stage_name, timeout)
    ↓
StageManager.check(timeout)  [vmanager.py 第 554 行]
    ↓
VerifyStage.do_check()  [vstage.py 第 251 行]
    ↓
Checker.do_check()  [执行实际检查逻辑]
    ↓
如果检查失败 → continue_fail_count++  [第 300 行]
    ↓
返回失败结果
    ↓
StageManager.gen_fail_suggestion(error_msg)  [vmanager.py 第 352 行]
```

#### 3.3.2 失败建议生成逻辑

在 `vmanager.py` 的 `gen_fail_suggestion()` 方法（第 352 行）：

```python
def gen_fail_suggestion(self, error_msg: str) -> Optional[str]:
    """生成失败建议"""
    vstage = self.get_current_stage()

    # 调用通用建议生成器
    return self.gen_llm_suggestion(
        vstage=vstage,
        llm_suggestion=vstage.llm_fail_suggestion,
        need_llm_suggestion=self.need_fail_llm_suggestion,
        prompts=(error_msg, error_msg)  # (任务提示, 建议提示)
    )
```

通用建议生成器 `gen_llm_suggestion()` 位于第 394 行：

```python
def gen_llm_suggestion(
    self,
    vstage: VerifyStage,
    llm_suggestion: BaseLLMSuggestion,
    need_llm_suggestion: bool,
    prompts: tuple
) -> Optional[str]:
    """通用 LLM 建议生成逻辑"""

    # 1. 检查是否启用
    if not need_llm_suggestion:
        return prompts[1]

    # 2. 阶段过滤：检查 bypass_stages
    if vstage.name in llm_suggestion.bypass_stages:
        return prompts[1]

    # 3. 阶段过滤：检查 target_stages
    if llm_suggestion.target_stages and vstage.name not in llm_suggestion.target_stages:
        return prompts[1]

    # 4. 阶段过滤：检查 default_apply_all_stages
    if not llm_suggestion.target_stages and not llm_suggestion.default_apply_all_stages:
        return prompts[1]

    # 5. 调用 LLM 建议方法
    return llm_suggestion.suggest(prompts[0])
```

#### 3.3.3 OpenAILLMFailSuggestion 实现

在 `langchain_suggestion.py` 的 `OpenAILLMFailSuggestion.suggest()` 方法（第 100 行）：

```python
def suggest(self, task_prompt: str) -> str:
    """生成失败优化建议"""

    # 1. 检查连续失败次数
    if self.vstage.continue_fail_count < self.min_fail_count:
        return self.suggestion_prompt  # 不足 min_fail_count 次，直接返回原始错误

    # 2. 切换阶段时清理对话历史
    if self.current_vstage_name != self.vstage.name:
        self._clear_history()
        self.current_vstage_name = self.vstage.name

    # 3. 构造任务信息
    task_info = self._build_task_info()
    test_info = self._extract_error_info()

    # 4. 构造完整提示
    full_prompt = f"{task_prompt}\n\n任务信息：\n{task_info}\n\n测试信息：\n{test_info}"

    # 5. 调用 LangChain Agent
    result = self._invoke_agent(full_prompt)

    # 6. 清理忽略标签并返回
    return self._remove_ignore_labels(result)
```

**关键判断**：`continue_fail_count < min_fail_count` 时不调用 LLM，直接返回原始错误信息，避免频繁调用浪费资源。

#### 3.3.4 LangChain Agent 调用

`_invoke_agent()` 方法使用 LangChain 的 ReAct Agent 框架：

```python
def _invoke_agent(self, prompt: str) -> str:
    """调用 LangChain Agent"""

    # 创建 Agent（带工具和中间件）
    agent = create_agent(
        model=self.model,
        tools=self.tools,  # ReadTextFile, ListDir, SearchText
        system_prompt=self.system_prompt
    )

    # 添加摘要中间件（防止对话过长）
    agent_with_middleware = agent | first_message_summary_middleware(
        trigger_tokens=self.summary_trigger_tokens,  # 32k
        keep_messages=self.summary_keep_messages     # 10
    )

    # 流式调用 Agent
    result = stream_call_langchain_agent(
        agent=agent_with_middleware,
        prompt=prompt,
        thread_id=self.vstage.name,  # 每个阶段独立的对话线程
        checkpointer=self.checkpointer
    )

    return result
```

### 3.4 Pass Check 流程

#### 3.4.1 触发条件

当 Agent 调用 `Complete` 工具完成阶段时：

```
Agent.complete(stage_name, timeout)
    ↓
StageManager.complete(timeout)  [vmanager.py 第 631 行]
    ↓
VerifyStage.do_check(is_complete=True)  [vstage.py 第 251 行]
    ↓
Checker.do_check()  [执行实际检查]
    ↓
如果检查通过 (ck_pass=True)
    ↓
StageManager.gen_pass_suggestion(ck_info)  [vmanager.py 第 641 行]
```

#### 3.4.2 通过建议生成逻辑

在 `vmanager.py` 的 `gen_pass_suggestion()` 方法（第 371 行）：

```python
def gen_pass_suggestion(self, ck_info: str) -> tuple:
    """生成通过验收建议"""
    vstage = self.get_current_stage()

    # 默认设置为未批准
    vstage.set_approved(False)

    # 调用通用建议生成器
    suggestion = self.gen_llm_suggestion(
        vstage=vstage,
        llm_suggestion=vstage.llm_pass_suggestion,
        need_llm_suggestion=self.need_pass_llm_suggestion,
        prompts=(ck_info, ck_info)
    )

    # 检查 LLM 是否批准
    if vstage.get_approved():
        return (True, suggestion)  # 批准，阶段完成
    else:
        return (False, f"LLM 未批准完成，建议：{suggestion}")  # 未批准，返回失败
```

**关键流程**：

1. 默认设置 `approved = False`
2. 调用 LLM 生成建议（LLM 内部会调用 `ApproveStagePass` 工具）
3. 检查 `approved` 状态，决定阶段是否真正完成

#### 3.4.3 OpenAILLMPassSuggestion 实现

在 `langchain_suggestion.py` 的 `OpenAILLMPassSuggestion.suggest()` 方法（第 204 行）：

```python
def suggest(self, task_prompt: str) -> str:
    """生成通过验收建议"""

    # 1. 切换阶段时清理对话历史
    if self.current_vstage_name != self.vstage.name:
        self._clear_history()
        self.current_vstage_name = self.vstage.name

    # 2. 构造任务信息和测试信息
    task_info = self._build_task_info()
    test_info = self._extract_error_info()

    full_prompt = f"{task_prompt}\n\n任务信息：\n{task_info}\n\n测试信息：\n{test_info}"

    # 3. 调用 LangChain Agent（带 ApproveStagePass 工具）
    result = self._invoke_agent(full_prompt)

    # 4. 返回建议（approved 状态由工具调用设置）
    return self._remove_ignore_labels(result)
```

与 Fail Refinement 的主要区别：

- **没有** `min_fail_count` 限制，每次都调用 LLM
- 提供 `ApproveStagePass` 工具，LLM 必须调用此工具来批准或拒绝
- 使用更大的 token 阈值（64k vs 32k），因为 Pass Check 需要更全面的上下文

#### 3.4.4 ApproveStagePass 工具

在 `vmanager.py` 第 45 行定义了 `LLMApprovalTool` 类：

```python
class LLMApprovalTool:
    """LLM 批准工具"""

    def __init__(self, vstage: VerifyStage):
        self.vstage = vstage

    def __call__(self, approved: bool) -> str:
        """设置批准状态"""
        self.vstage.set_approved(approved)
        if approved:
            return "已批准阶段完成"
        else:
            return "未批准，需要继续改进"
```

在 `StageManager` 的 `tool_approve_stage` 属性（第 345 行）中注册为 LangChain 工具：

```python
self.tool_approve_stage = StructuredTool.from_function(
    func=LLMApprovalTool(vstage),
    name="ApproveStagePass",
    description="批准或拒绝当前阶段的完成。参数 approved: true 表示批准，false 表示拒绝。"
)
```

**工作机制**：

1. LLM 调用 `ApproveStagePass(approved=True/False)`
2. 工具执行 `vstage.set_approved(approved)`
3. `StageManager.gen_pass_suggestion()` 检查 `vstage.get_approved()`
4. 根据批准状态决定阶段是否完成

### 3.5 对话历史管理

#### 3.5.1 线程隔离机制

每个验证阶段使用独立的对话线程（`thread_id = vstage.name`），确保不同阶段的对话历史不会相互干扰。

在 `langchain_suggestion.py` 中：

```python
# 切换阶段时清理历史
if self.current_vstage_name != self.vstage.name:
    self._clear_history()
    self.current_vstage_name = self.vstage.name
```

`_clear_history()` 方法会删除当前阶段的所有历史消息。

#### 3.5.2 摘要机制

为防止对话 token 数过多，使用 `first_message_summary_middleware` 中间件：

```python
def first_message_summary_middleware(trigger_tokens: int, keep_messages: int):
    """对话摘要中间件

    当 token 数超过 trigger_tokens 时，保留首条消息和最近 keep_messages 条消息，
    删除中间的历史消息。
    """
    # 实现逻辑：
    # 1. 计算当前对话的 token 数
    # 2. 如果超过阈值，保留首条消息（系统提示）和最近 N 条消息
    # 3. 删除中间的历史消息
```

**默认配置**：

- **Fail Refinement**：32k tokens 触发，保留 10 条消息
- **Pass Check**：64k tokens 触发，保留 10 条消息

### 3.6 连续失败计数器

在 `vstage.py` 中，`continue_fail_count` 用于跟踪连续失败次数（第 79 行初始化）：

```python
class VerifyStage:
    def do_check(self, timeout: int, is_complete: bool = False) -> tuple:
        """执行检查"""

        # 调用 Checker
        ck_pass, ck_info = self.checker.do_check(timeout, is_complete)

        # 更新连续失败计数器（第 300 行附近）
        if ck_pass:
            self.continue_fail_count = 0  # 成功时重置
        else:
            self.continue_fail_count += 1  # 失败时累加

        return (ck_pass, ck_info)
```

**作用**：

- 避免首次失败就调用 LLM（可能是暂时性错误）
- 只有在连续失败 `min_fail_count` 次（默认 3 次）后才触发 LLM 建议
- 一旦成功，计数器归零

### 3.7 错误信息提取

在 `langchain_suggestion.py` 中，`_extract_error_info()` 方法从阶段状态中提取结构化错误信息：

```python
def _extract_error_info(self) -> str:
    """提取错误信息"""

    # 从 vstage.check_info 中提取 last_msg.error 字段
    check_info = self.vstage.check_info
    if check_info and hasattr(check_info, 'last_msg'):
        error = check_info.last_msg.error
        return f"错误类型：{error.type}\n错误信息：{error.message}\n堆栈跟踪：{error.traceback}"

    return "无详细错误信息"
```

这个方法确保 LLM 能获得完整的错误上下文，包括错误类型、消息和堆栈跟踪。

### 3.8 忽略标签处理

某些 LLM 在推理时会输出思考过程（如 `<think>...</think>`），这些内容不应该展示给用户。`_remove_ignore_labels()` 方法会过滤这些标签：

```python
def _remove_ignore_labels(self, text: str) -> str:
    """移除忽略标签"""
    for start_label, end_label in self.ignore_labels:
        # 使用正则表达式移除 start_label 和 end_label 之间的内容
        text = re.sub(f"{re.escape(start_label)}.*?{re.escape(end_label)}", "", text, flags=re.DOTALL)
    return text
```

**默认配置**：`ignore_labels = [("<think>", "</think>")]`

---

## 四、总结

### 4.1 功能特点

1. **智能化**：引入 LLM 专家进行语义分析和质量把关
2. **可配置**：支持 YAML 和环境变量两种配置方式，灵活控制启用范围
3. **高效**：Fail Refinement 使用连续失败次数阈值避免频繁调用
4. **可靠**：Pass Check 提供二次确认机制，防止假阳性
5. **隔离**：每个阶段独立的对话线程，避免历史干扰
6. **优化**：摘要机制控制 token 消耗

### 4.2 使用建议

1. **Fail Refinement**：建议全局启用，`min_fail_count` 设置为 3-5 次
2. **Pass Check**：建议针对关键阶段（如 Complete）启用，避免过度调用
3. **模型选择**：建议使用支持工具调用的强大模型（如 GPT-5、GLM-4-Plus、Claude-Sonnet-4.5 等）
4. **阶段过滤**：根据项目特点配置 `target_stages` 和 `bypass_stages`
5. **提示词优化**：根据具体验证场景定制 `system_prompt` 和 `suggestion_prompt`

### 4.3 注意事项

1. 需要配置支持 API 调用的 LLM 后端
2. Pass Check 会增加阶段完成时间，仅在关键阶段使用
3. 建议监控 LLM 调用次数和成本
4. 定期检查和优化提示词，提高建议质量

---

## 五、参考资源

- **核心实现**：
  - `ucagent/stage/llm_suggestion.py` - 基类定义
  - `ucagent/stage/langchain_suggestion.py` - LangChain 实现
  - `ucagent/stage/vmanager.py` - 集成管理
  - `ucagent/stage/vstage.py` - 阶段管理
- **配置文件**：`ucagent/setting.yaml`
