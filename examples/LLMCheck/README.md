# LLM Check & Refinement 功能示例

本示例展示了 UCAgent 的 **LLM 检查与优化 (LLM Check & Refinement)** 功能。该功能允许引入“LLM 专家”角色，对验证过程中的关键阶段进行二次评估和指导。

该机制包含两个主要部分：
1.  **Fail Refinement (失败优化)**: 当 Checker 检查未通过时，LLM 专家分析错误原因并给出具体的修复建议。
2.  **Complete Check Pass (通过验收)**: 当关键阶段初步通过（Checker 认为 OK）时，强制要求 LLM 专家进行二次确认，确保验证质量符合高标准，防止“假阳性”或遗漏。

## 1. 功能配置

要启用此功能，需要在 `setting.yaml` （ucagent/setting.yaml）或项目特定的配置文件中配置 `vmanager.llm_suggestion` 部分。

**需要使用API模式（支持把Backend切换到Claude Code 或者 Open Code等代码智能体）**

### 1.1 启用 Fail Refinement

当阶段检查失败时，LLM 会分析错误并给出建议。当`Check Fail`达到一定次数后调用（默认3次）

```yaml
vmanager:
  llm_suggestion:
    check_fail_refinement:
      enable: true
      ...
```

或者通过以下环境变量启用，例如：
```bash
export ENABLE_LLM_FAIL_SUGGESTION=true
export FAIL_SUGGESTION_MODEL=glm-4.6
export FAIL_SUGGESTION_API_KEY=<your_key>
export FAIL_SUGGESTION_API_BASE=https://apis.iflow.cn/v1
```

### 1.2 启用 Pass Check

当阶段Complete检查通过时，LLM 会再次审查。通过 LLM 显式批准后，阶段才算最终完成。

```yaml
vmanager:
  llm_suggestion:
    check_pass_refinement:
      enable: true
      ...
```

或者通过以下环境变量启用，例如：
```bash
export ENABLE_LLM_PASS_SUGGESTION=true
export PASS_SUGGESTION_MODEL=glm-4.6
export PASS_SUGGESTION_API_KEY=<your_key>
export PASS_SUGGESTION_API_BASE=https://apis.iflow.cn/v1
```

## 其他

### 在MCP模式下启用

如果要在纯MCP模式下启用 LLM 检查，需要在UCagent先执行命令：`agent_unbreak`，否则LLM check会被中断

### 建议

1. LLM 检查建议使用强的推理模型
2. 长时间运行建议用API模式（或者 backend=<your_code_agent>）
