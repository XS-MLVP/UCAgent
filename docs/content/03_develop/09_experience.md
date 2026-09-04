# 经验系统 (Experience System)

在硬件验证中，AI Agent 在面对检查器（Checker）失败时，虽然能获取结构化的 Checker 诊断报告，但有时仍会在一些**流程性、格式性或配置对齐**问题上反复试错（例如把分批剩余测试提示误判为 DUT 缺陷、反复修改标签导致文档层级摇摆、混淆 Python 与硬件算术取整语义等）。

UCAgent **经验系统**为验证工作流提供了一套**轻量级、可配置、可审计且严格防污染**的经验闭环机制。

---

## 1. 核心设计原则

经验系统的目标是**辅助 Agent 快速识别已知流程陷阱，加速验证收敛**，而不是替代 Agent 推导 DUT 逻辑。整体设计遵循以下铁律：

- **Checker 权威性不变**：不修改 Checker 逻辑，不放宽任何 Pass/Fail 判定，Checker 报告永远是第一事实来源。
- **候选提示为辅助（Triage Aid）**：仅在 `Check` 或 `Complete` 失败后按条件追加少量（默认最多 2 条）候选提示（`candidate_failure_hints`），提示不适用时模型必须回归 Checker 报告本身。
- **Stage 边界严格隔离**：经验收集与审计仅在标记了 `experience-hook: true` 的阶段生效，并通过日志字节切片（Byte Offset）严格限定在本阶段内，**零跨阶段污染**。
- **人工审查入库（Review-only）**：LLM 蒸馏提取的候选经验只输出到旁路产物目录，**绝不自动写回全局经验库**，必须经人工审查（Review）后方可纳入版本控制。

---

## 2. 总体架构与数据流

经验系统在 UCAgent 内部的完整工作链路如下图所示：

```mermaid
flowchart TD
    A["启动 UCAgent"] --> B["加载配置 (setting / default / general / DUT overlay)"]
    B --> C["解析经验规则至 agent.cfg"]
    C --> D["Stage 执行中"]
    D --> E{"Check 或 Complete 失败?"}
    E -- "是" --> F["StageManager 匹配 candidate_failure_hints"]
    F --> G["将候选排查提示追加至 Tool 返回结果"]
    G --> D
    E -- "否, Stage 成功通过" --> H{"配置了 experience-hook && 启用了审计/蒸馏?"}
    H -- "否" --> I["推进至下一 Stage"]
    H -- "是" --> J["按起始/结束 Offset 截取当前 Stage 日志切片"]
    J --> K{"--experience-audit?"}
    K -- "是" --> L["审计先验规则匹配覆盖情况 -> prior_rule_audit.yaml"]
    J --> M{"--experience-distill?"}
    M -- "是" --> N["提取 Failure->Recovery 轨迹并调用 LLM 蒸馏 -> llm_failure_hints.yaml"]
    L --> O["保存至 .ucagent/experience/ 产物目录"]
    N --> O
    O --> I
```

---

## 3. 经验规则配置

经验规则分为**通用经验库（DUT-neutral）**与 **DUT 专属经验 Overlay**。

### 3.1 通用经验库 (`general.yaml`)

通用经验库位于 `ucagent/lang/zh/experience/general.yaml`，收录不依赖特定 DUT 的通用排错规则（如标签层级解析、分批实现优先级、置信度格式等）：

```yaml
experience:
  max_candidate_failure_hints: 2  # 每次失败最多注入的提示数量

  candidate_failure_hints:
    - id: batch_progress_remaining_tests_prioritize_impl
      priority: 10
      enabled: true
      stages: ["test_case_implementation_in_batch"] # 优先使用稳定阶段名
      checkers:
        - "UnityChipCheckerBatchTestsImplementation"
      patterns:
        - "remaining to be implemented"
        - "remaining test cases"
      hint: "当 checker 报告提示 remaining test cases 时，当前任务目标是继续实现本批次未完成的测试用例。优先完成剩余测试并执行 Check，不要将进度提示误判为 DUT 缺陷或环境异常。"
```

### 3.2 规则字段规范

每条规则包含以下字段：

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| `id` | `string` | 规则唯一标识符（建议小写下划线命名） |
| `priority` | `int` | 优先级（数值越小越优先匹配，建议范围 10~90） |
| `enabled` | `bool` | 是否启用该规则（默认 `true`） |
| `stages` | `list[str]` | 生效的阶段名或运行时索引列表；内置规则优先使用稳定阶段名，避免工作流增删阶段后索引漂移 |
| `checkers` | `list[str]` | 触发匹配的 Checker 类名列表 |
| `patterns` | `list[str]` | 精确字符串匹配项（命中国中任意一项即可） |
| `regex` | `list[str]` | 正则表达式匹配项（支持复杂模式匹配） |
| `match_scope` | `list[str]` | 匹配文本范围：`["focused"]`（默认，仅检查 error/details 字段）或 `["full"]`（完整返回文本） |
| `hint` | `string` | 注入给大模型的行动纠偏提示词（需清晰指明排查步骤） |

### 3.3 DUT 专属配置与公平边界

针对特定模块，可在 `ucagent/lang/zh/experience/<DUT>.yaml` 中引入通用经验并补充安全的验证维度。DUT overlay 只允许描述从当前工作区资料可独立推导的检查范围、建模方法和失败分类，不得提供 oracle 答案。

禁止在已入库的 DUT overlay 中保存以下内容：

- 精确 expected、固定输入输出向量、常数或可复制的 reference model 实现；
- 历史日志、已知失败序列、稳定失败的测试名、源码根因和修复结论；
- 精确的 FG/FC/CK 路径、Bug 标签，或依赖历史问题专属名称和结论的触发条件。

允许 DUT overlay 定义 `candidate_failure_hints`，但触发条件只能使用公开模块语义和稳定失败类别，hint 只能引导 Agent 回到当前工作区规格进行独立推导和重新验证。不得在入库规则中保留 `source.evidence`；历史运行证据只能保存在审计或蒸馏旁路产物中。

推荐同时使用阶段任务和安全候选提示：

```yaml
# ucagent/lang/zh/experience/<DUT>.yaml
include:
  - general.yaml

# 仅开启特定阶段的经验收集 Hook
stage[12].experience-hook: true
stage[13].stage[0].experience-hook: true
stage[13].experience-hook: true

stage[13].stage[0].task: "+模块专属验证维度：依据当前工作区中的规格、接口和实现，独立建立 reference model，覆盖该模块声明的正常、边界、异常和时序场景。不得复制 DUT 实现、已有断言或历史运行结论。"
stage[13].task: "+分析失败时，先核对规格预期、测试环境、模型、输入输出表示、握手和采样时机；只有验证链路正确后仍稳定违反规格，才记录为 DUT Bug。"

experience:
  candidate_failure_hints+:
    - id: current_contract_transaction_alignment
      priority: 76
      stages: ["test_case_implementation_in_batch", "comprehensive_verification_and_bug_analysis"]
      match_scope: ["focused", "full"]
      regex:
        - "(?i)(?:handshake|response).*(?:failed|error|timeout)"
      hint: "这类事务失败应先依据当前工作区接口契约独立列出请求、响应和完成条件，再核对环境与采样时机；不得把超时或历史归因直接当作 DUT Bug。"
```

阶段任务中的模块名称只用于选择配置，不代表该文件可以提供该模块的正确答案。若无法从当前工作区资料独立推导预期，应暂停归因并补充权威输入，而不是从经验文件猜测。

---

## 4. 命令行使用模式 (CLI)

UCAgent 提供了灵活的 CLI 参数来控制经验系统的运行模式：

| 模式 | CLI 参数 | 说明 | 产物输出 |
| :--- | :--- | :--- | :--- |
| **标准运行** | （不加经验参数） | 完全不加载经验覆盖层，默认关闭 | 无 |
| **仅经验注入** | `--experience-profile` | 仅加载通用与 DUT 经验规则注入提示，用于 A/B 效果对比 | 无旁路产物 |
| **先验规则审计** | `--experience-audit` | 注入经验，并在 Stage 完成后审计先验规则的命中与覆盖情况 | 生成 `prior_rule_audit.yaml` |
| **LLM 经验蒸馏** | `--experience-distill` | 注入经验，并在 Stage 完成后调用模型提炼 Review-only 候选规则 | 生成 `llm_failure_hints.yaml` |
| **完整模式** | `--experience` | 同时启用 Profile 加载、先验审计与 LLM 蒸馏 | 生成完整经验分析产物 |

当 `--experience-profile`、`--experience-audit`、`--experience-distill` 或 `--experience` 遇到没有已入库 profile 的安全 DUT 名称时，UCAgent 会在当前语言的 `experience/` 目录自动创建小写文件名的冷启动 profile：

```yaml
include:
  - general.yaml
```

该文件只启用通用经验，不携带 DUT 结论，也不自动生成专属候选规则。它不包含 `experience-hook`，因此 `--experience` 在这个新 profile 上不会产生阶段审计或蒸馏产物；需要这些产物时，应在人工审查后显式添加对应阶段 hook。

### 典型执行命令

```bash
# 1. 快速验证经验提示效果（仅注入，不产生额外文件）
python ucagent/cli.py --dut Adder --experience-profile

# 2. 运行并生成完整经验审计与蒸馏产物
python ucagent/cli.py --dut Adder --experience --log-file log/run.log --msg-file log/run-msg.log

# 3. 通过 Makefile 启动
make -i mcp_Adder ARGS="--loop --log --log-file log/exp.log --msg-file log/exp-msg.log --experience"
```

---

## 5. 产物目录结构

启用 `--experience` 运行后，各 Stage 的经验沉淀将输出在工作区 `.ucagent/experience/` 目录下：

```
<workspace>/
└── .ucagent/
    └── experience/
        ├── stage_23_create_test_case_templates/
        │   ├── adder_verification_experience.md # 已脱敏的阶段经验摘要
        │   ├── prior_rule_audit.yaml            # 先验规则命中审计报告
        │   ├── adder_llm_failure_hints.yaml     # 模型提炼的候选经验规则 (Review-only)
        │   └── index.json                        # 产物索引与日志范围元数据
        └── stage_24_test_case_implementation_in_batch/
            ├── adder_verification_experience.md
            ├── prior_rule_audit.yaml
            └── index.json
```

---

## 6. 开发者最佳实践

1. **规则编写要清晰、具体**：提示词应明确给出**“先核对什么”、“不要做什么”、“修完后做什么”**，避免模糊的主观判断。
2. **严防敏感信息与过拟合**：通用经验库（`general.yaml`）中禁止包含具体 DUT 的寄存器名字、临时十六进制常量或特定 RTL 路径。
3. **保持 Review 机制**：将 LLM 蒸馏出的候选规则纳入代码仓库前，必须由验证工程师人工确认其通用性与正确性，确保经验库的质量。
