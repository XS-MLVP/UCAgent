
# Mini 示例

`examples/MiniWorkflow/` 是一个可运行的两阶段工作流：第一阶段分析 Calculator 的 README，第二阶段生成项目文档。它展示了配置、外部工具、Guide_Doc 和自定义 Checker 的最小组合。

## 1. 目录和输入

```text
examples/MiniWorkflow/
├── Calculator/README.md
├── Guide_Doc/
│   ├── project_analysis_guide.md
│   └── documentation_template.md
├── mini.yaml
├── my_tools.py
├── my_checkers.py
└── Makefile
```

`mini.yaml` 使用当前工作流字段：`ex_tools`、`template_overwrite`、`mission`、`stage`、`reference_files`、`output_files` 和 `checker`。启动命令使用 `output/` 作为 workspace，未传 `--output`，阶段产物实际位于 `examples/MiniWorkflow/output/unity_test/`。更改输出目录时应传 `--output <name>`，并用当前阶段信息确认路径。

## 2. 运行

先完成[源码安装](../01_start/00_installation.md#12-安装-ucagent-主体)，激活虚拟环境，再按[直接使用](../02_usage/01_direct.md#1-配置模型)配置模型。在仓库根目录执行：

```bash
cd examples/MiniWorkflow
make test
make run ARGS="--loop"
```

`make test` 只检查自定义工具和 Checker 是否可以导入。`make run` 会清理并创建 `output/`，复制 Calculator，再启动 UCAgent：

```bash
PYTHONPATH=. ucagent ./output/ Calculator \
  --config ./mini.yaml \
  --guid-doc-path ./Guide_Doc/ \
  -s -hm --tui --loop
```

`--loop` 使普通模式立即执行；只运行 `make run` 时会停在 TUI，输入 `loop` 才开始。`PYTHONPATH=.` 用于导入当前目录的 `my_tools` 和 `my_checkers`，Makefile 会自动设置。

需要使用外部 Code Agent 时，改用：

```bash
make run ARGS="--mcp-server --backend=codex"
```

该命令不自动进入模型循环。另一个终端先进入 `examples/MiniWorkflow/output/`，再按 [MCP 接入](../01_start/03_mcp_mode.md#33-手动双终端接入以-codex-为例)配置并启动 Codex。Mini 的任务要求使用 `EditTextFile`，因此这里启用完整 MCP 文件工具。

也可以把整个 `MiniWorkflow/` 复制到其他目录后运行；已安装的 UCAgent 会通过 `ucagent` 命令启动，自定义工具和 Checker 从当前示例目录导入。

示例工作流默认不需要嵌入工具；当前 CLI 的 `--no-embed-tools` 默认已经是 `true`，无需重复添加该参数。

## 3. 工作流做了什么

阶段 `analyze_project`：

1. 读取 `Calculator/README.md` 和 `Guide_Doc/project_analysis_guide.md`；
2. 生成 `unity_test/Calculator_analysis.md`（相对于 workspace）；
3. 使用 `CountWords` 提供统计信息；
4. 用字数和 Markdown 格式 Checker 验收。

阶段 `generate_documentation`：

1. 读取分析文档和 `Guide_Doc/documentation_template.md`；
2. 生成 `unity_test/Calculator_documentation.md`（相对于 workspace）；
3. 使用 `ExtractSections` 检查章节；
4. 用字数、必需章节和 Markdown 格式 Checker 验收。

阶段完成都必须经过 `Check`/`Complete`。Checker 失败时，先按返回的文件和字段修复，再重试。

## 4. 查看结果

```bash
cat output/unity_test/Calculator_analysis.md
cat output/unity_test/Calculator_documentation.md
```

实际字数和内容由模型输出决定，不能把示例中的字数范围当作所有工作流的通用要求。

## 5. 修改示例

### 增加阶段

在 `mini.yaml` 的 `stage` 列表中追加完整阶段：

```yaml
- name: generate_api_docs
  desc: "生成 API 文档"
  task:
    - "读取已有分析和模板，生成 {OUT}/{PROJECT}_api.md"
  output_files:
    - "{OUT}/{PROJECT}_api.md"
```

需要可靠验收时，再为该阶段添加 Checker。

### 增加工具

在 `my_tools.py` 中定义继承 `UCTool` 的类，用 Pydantic `args_schema` 描述参数，然后在 `mini.yaml` 的 `ex_tools` 中注册完整导入路径。工具必须只访问工作区允许的路径。

### 增加 Checker

在 `my_checkers.py` 中继承 `Checker`，构造函数先调用 `super().__init__()`，在 `do_check` 中返回 `(bool, result)`。失败结果应包含稳定的 `error_code`、具体 `error` 和 `next_action`。

## 6. 进一步学习

- [定制开发入门](01_quick_start.md)：从零搭建配置、工具和 Checker。
- [工作流配置](03_workflow.md)：阶段、模板变量、批处理和阶段索引。
- [定制工具](05_customize.md)：本地工具和 MCP schema。
- [检查器](07_checkers.md)：生命周期、诊断和批任务约定。
- [插件开发与发布](09_plugins.md)：把工作流资源封装为可安装插件。
