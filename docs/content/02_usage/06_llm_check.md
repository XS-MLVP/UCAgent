
# LLM Check 与 Refinement

UCAgent 的 Checker 先用确定性规则检查阶段产物。可选的 LLM Check 在此基础上提供两类辅助：

- **Fail Refinement**：阶段 `Check` 失败后，分析当前诊断并给出修复建议。
- **Pass Check**：阶段完成前的 Checker 通过后，再让一个独立的模型评审结果；评审模型必须调用 `ApproveStagePass` 才会批准阶段。

两项功能默认关闭。它们不会替代 Checker，也不会把测试基础设施失败自动变成 DUT Bug。

## 1. 最小配置

Fail Refinement：

```bash
export ENABLE_LLM_FAIL_SUGGESTION=true
export FAIL_SUGGESTION_MODEL="<model_name>"
export FAIL_SUGGESTION_API_KEY="<api_key>"
export FAIL_SUGGESTION_API_BASE="https://<provider>/v1"
```

Pass Check：

```bash
export ENABLE_LLM_PASS_SUGGESTION=true
export PASS_SUGGESTION_MODEL="<model_name>"
export PASS_SUGGESTION_API_KEY="<api_key>"
export PASS_SUGGESTION_API_BASE="https://<provider>/v1"
```

建议使用与主模型不同的模型或 API 配额，以便区分验证执行和结果评审。Fail 和 Pass 的 API 参数分别独立配置；如果使用 `ucagent/setting.yaml` 中的 `launch.default_env`，也可以让子 Agent 继承这些变量。

同样的配置可以写入项目 YAML：

```yaml
vmanager:
  llm_suggestion:
    check_fail_refinement:
      enable: true
      clss: ucagent.stage.llm_suggestion.OpenAILLMFailSuggestion
      args:
        model_name: "<model_name>"
        openai_api_key: "<api_key>"
        openai_api_base: "https://<provider>/v1"
        min_fail_count: 3
      bypass_stages: []
      target_stages: []
      default_apply_all_stages: true
    check_pass_refinement:
      enable: true
      clss: ucagent.stage.llm_suggestion.OpenAILLMPassSuggestion
      args:
        model_name: "<model_name>"
        openai_api_key: "<api_key>"
        openai_api_base: "https://<provider>/v1"
      bypass_stages: []
      target_stages: []
      default_apply_all_stages: true
```

配置文件中的 `enable` 也可以用环境变量占位，例如 `enable: $(ENABLE_LLM_FAIL_SUGGESTION: false)`。密钥不要写入文档、日志或运行时快照。

## 2. 什么时候触发

### Fail Refinement

当当前阶段的 Checker 返回结构化失败诊断，并且该阶段启用了 Fail Refinement 时，UCAgent 会累计连续失败次数。默认连续失败 3 次后才调用建议模型；在达到阈值前保留普通 Checker 结果。一次成功的 Check 会清零连续失败计数。

建议模型收到当前阶段任务和失败报告，可以使用只读检查工具读取相关文件。它返回的是 `action` 建议，Agent 仍需要按建议修复并重新 `Check`。

### Pass Check

当 `Complete` 路径中的 Checker 通过，且当前阶段启用了 Pass Check 时，UCAgent 把阶段任务、检查结果和阶段 Diff 交给评审模型。评审模型需要：

- 发现问题时返回具体修复建议，并拒绝批准；
- 没有问题时调用 `ApproveStagePass(pass_or_not=true)`。

未获得批准时，阶段不会推进。Pass Check 每次触发都会产生一次模型调用，因此只建议用于规格、覆盖率、测试实现或 Bug 报告等关键阶段。

## 3. 阶段过滤

每一项建议配置都支持：

| 字段 | 作用 |
| --- | --- |
| `bypass_stages` | 始终跳过列出的阶段，优先级最高 |
| `target_stages` | 非空时只在列出的阶段启用 |
| `default_apply_all_stages` | `target_stages` 为空时，是否应用于所有阶段；默认 `true` |

判断顺序是：先看 `bypass_stages`，再看 `target_stages`，最后看 `default_apply_all_stages`。也可以在运行中的 Agent 页面按阶段切换 LFail/LPass，阶段级设置会覆盖全局过滤结果。

示例：

```yaml
check_pass_refinement:
  enable: true
  target_stages: [functional_specification_analysis, comprehensive_verification_and_bug_analysis]
  default_apply_all_stages: false
```

阶段名称必须使用当前配置中的 `name`，不是页面标题或阶段索引。

## 4. 常用参数

| 参数 | 适用项 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `model_name` | Fail/Pass | 无 | 评审模型名称 |
| `openai_api_key` | Fail/Pass | 无 | API Key |
| `openai_api_base` | Fail/Pass | 无 | OpenAI 兼容 API 地址 |
| `min_fail_count` | Fail | `3` | 连续失败多少次后调用模型 |
| `summary_trigger_tokens` | Fail/Pass | Fail `32768`、Pass `65536` | 建议模型对话摘要触发阈值 |
| `summary_keep_messages` | Fail/Pass | `10` | 摘要后保留的消息数 |
| `ignore_labels` | Fail/Pass | `<think>...</think>` | 从建议文本中过滤的标签对 |
| `temperature`、`top_p` | Fail/Pass | 未设置 | 传给建议模型的采样参数 |

## 5. 排障和成本

- 没有建议输出：先检查 `ENABLE_LLM_*_SUGGESTION`、对应的模型变量和 API 地址，再确认当前阶段没有被过滤。
- Fail 建议没有立即出现：默认要连续失败 3 次；可调整 `min_fail_count`，但不要用它掩盖未修复的 Checker 失败。
- Pass Check 不推进：查看评审模型返回，确认它在没有问题时调用了 `ApproveStagePass(true)`；修复问题后重新 `Complete`。
- 建议模型调用会增加延迟和费用。优先对关键阶段启用，并设置合理的 API 超时和上下文摘要阈值。
- 普通 Checker 结果始终是事实来源。LLM 建议只能帮助定位，不能替代测试、源码、报告和波形证据。

配置字段和默认值以 `ucagent/setting.yaml` 当前版本为准；需要修改实现或增加新的评审策略时，参见 `ucagent/stage/llm_suggestion/` 及[工作流配置](../03_develop/03_workflow.md)。
