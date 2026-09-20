# Workflow Config Generator

## 作用

该组件把结构化 `.workflow/config_spec.yaml` 转换为最终供 UCAgent 运行的 `config.yaml`。它解决的是“业务阶段如何进入可执行配置”的问题，不负责生成工具代码或 Checker 代码；阶段引用、输出和 Checker 注册从 `.workflow/workflow_spec.yaml` 权威注入。

## 原理

生成器先校验 spec 中的 `workflow`、`mission` 和 `stages`，保证阶段名称唯一。`default` 与 `inc` 的每个阶段 task 必须至少有 100 个有效 CJK/英文字母/数字字符；`empty` 豁免。随后按阶段名加载 workflow_spec，注入 `reference_files`、`output_files` 和 `checker`，任何显式冲突都会被拒绝。已有配置中的工具、路径、权限和 GuideDoc 注册仍可保留。

## Spec 关键字段

- `workflow`：工作流名称、版本和说明。
- `mission`：运行 Agent 的总体任务与 system prompt。
- `mode`：主配置使用 `default`，增量配置使用 `inc`，可选独立评估配置使用 `eval`；兼容的 `empty` 模式只能有一个阶段，但工作流构建交付不再生成 empty 配置。
- `stages`：最终执行阶段；每项可包含 `task`、`reference_files`、`output_files`、`checker`。
- `template_overwrite`：运行时附加变量。生成器固定写入 `INPUT_ROOT: input/{DUT}` 和 `OUTPUT_ROOT: {OUT}/{DUT}`。
- `model`、`loop_settings`：模型和循环策略。
- `guide_docs`：运行时提供给 Agent 的文档。
- `write_dirs`、`un_write_dirs`：工作区写权限边界。`write_dirs` 必须且只能为 `{OUT}/{DUT}`。

UCAgent 运行配置中的变量必须使用单层花括号，例如 `{DUT}`、`{OUT}`。生成器会拒绝
`{{DUT}}` 这类双层花括号以及未定义的 `{TARGET}`。阶段路径应使用
`input/{DUT}/...` 与 `{OUT}/{DUT}/...`，保证任务描述、文件声明和 checker 参数在运行时一致展开。
每个阶段声明的输出文件也必须位于 `{OUT}/{DUT}/`；工作流输入统一放在
`input/<DUT>/`，生成工作流必须自带 `input/example/`。
`reference_files` 只允许声明能被 `ReadTextFile` 读取的文本、YAML、JSON 或源码文件。
目录应在任务中通过 `PathList` 浏览，图片、PPTX、PDF 等二进制文件应通过业务工具或 checker 检查，
不能放进 `reference_files`。

## CLI

```bash
python -m examples.workflow_builder.tools.workflow_config_generator.cli <workflow_root> \
  --spec .workflow/config_spec.yaml \
  --workflow-spec .workflow/workflow_spec.yaml \
  --output config.yaml
```

默认保留工具等已有注册。阶段 Checker 注册始终服从 workflow_spec，不受该开关影响。

## UCAgent 工具

在上层 config 的 `ex_tools` 中加入：

```yaml
- examples.workflow_builder.tools.workflow_config_generator.uc_tools.WorkflowConfigGenerator
```

调用参数：`workflow_root`、`spec_path`、`output_path`、`preserve_registrations`。

## 验证

生成后至少执行：

```bash
python .workflow/checkers/config_syntax_checker.py config.yaml
make check
```

之后应实际启动一次 UCAgent，确认阶段、工具和 checker 都能加载。
