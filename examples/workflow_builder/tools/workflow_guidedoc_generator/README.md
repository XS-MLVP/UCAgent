# Workflow GuideDoc Generator

## 作用

该组件把 `.workflow/guidedoc_specs/*.yaml` 转换为 Agent 使用的 `Guide_Doc/*.md`
或用户使用的 `docs/*.md`。`guide_doc` 会加入 `config.yaml` 的 `guide_docs`，
`user_doc` 不会注册为运行时上下文。

## 原理

每份 spec 声明 `document_type`、文档标题、输出路径和有序章节。未声明
`document_type` 时默认为 `guide_doc`。技术类 GuideDoc 可以设置
`operation_contract: false`；面向用户的 `user_doc` 输出到 `docs/`。

## Spec 示例

```yaml
title: "Operation Guide"
output: "Guide_Doc/operation.md"
sections:
  - id: purpose
    heading: "目的"
    content: "说明工作流解决的问题。"
  - id: inputs
    heading: "输入"
    content: "说明 input/<TARGET>/ 的必需内容和 input/example/。"
  - id: outputs
    heading: "输出"
    content: "说明所有结果均写入 output/。"
  - id: usage
    heading: "使用方法"
    content: "给出 TARGET 选择方式和可直接执行的检查、运行命令。"
  - id: execution
    heading: "执行步骤"
    content: "说明运行和验证命令。"
  - id: checks
    heading: "检查"
    content: "说明成功判定和检查命令。"
  - id: failure_recovery
    heading: "失败恢复"
    content: "说明日志位置和修复流程。"
```

## CLI

```bash
python -m examples.workflow_builder.tools.workflow_guidedoc_generator.cli <workflow_root> \
  --from-spec .workflow/guidedoc_specs/operation.yaml
```

可重复传入 `--from-spec` 生成多份文档。使用 `--no-update-config` 可只生成文件而不注册。

## UCAgent 工具

在上层 config 的 `ex_tools` 中加入：

```yaml
- examples.workflow_builder.tools.workflow_guidedoc_generator.uc_tools.WorkflowGuideDocGenerator
```

## 内容设计建议

每份 GuideDoc 必须完整包含语义 ID `purpose`、`inputs`、`outputs`、`usage`、`execution`、
`checks` 和 `failure_recovery`，且每节内容非空；`heading` 可以使用中文展示标题。旧英文
heading 可兼容读取，但新 spec 必须显式写出 ID。尤其是 `usage` 必须给出可直接执行
的命令、目标选择方式、输入位置和输出位置。不要只复述功能名称；应让首次接触该
工作流的人和下层 Agent 都能据此完成任务、验证结果并定位失败。

生成器会强制检查操作契约：`Inputs` 必须说明 `input/<TARGET>/` 和
`input/example/`，`Outputs` 必须说明 `output/`，`Usage` 必须同时说明 `TARGET`、
上述目录、`make check_example` 和 `make run`。

## 验证

生成后检查文档存在、章节完整，并确认 `config.yaml` 的 `guide_docs` 包含该路径。最终应启动 UCAgent，确认文档可以被读取。

固定用户文档还必须满足格式契约：README 提供文档地图和快速入口，快速启动提供
`make configure`、`make check`、`make run`，输入输出文档覆盖
`input/<TARGET>/`、`output/<TARGET>/`、`metadata/` 和 `checksums.sha256`，步骤文档覆盖阶段、工具和
Checker，工具与 Checker 开发文档包含真实源码、关键代码分析和测试说明。固定用户文档禁止出现
TODO、TBD、待补充或空章节；生成器会在调用前拒绝不满足契约的 spec，生成后的
`.workflow/checkers/guidedoc_basic_checker.py` 会再次检查实际 Markdown。
