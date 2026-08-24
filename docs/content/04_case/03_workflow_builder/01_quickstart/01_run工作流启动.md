# 启动 run 构建工作流

本节从零准备 DOCX 案例输入，并用监督模式运行 Workflow Builder。以下命令假设 UCAgent 仓库位于 `~/FDocB/UCAgent`，业务根目录为 `~/FDocB/UCAgent_t/workspace_docx`。

## 1. 准备业务需求

创建 `workspace_docx/input/guide.md`，至少写清目标、输入、输出、工具、Checker、文档和验收。可采用以下最小示例并继续补充业务细节：

```markdown
# DOCX 说明文档工作流需求

## 目标
生成一个工作流，读取某个目标目录中的 Markdown 正文、图片和文档要求，输出可交付的 DOCX、处理报告和结构化检查结果。

## 输入
- input/<TARGET>/content.md：正文和标题层级。
- input/<TARGET>/document_requirements.md：纸张、页边距、字体、页眉页脚、目录和图片要求。
- input/<TARGET>/assets/：正文引用的本地图片。

## 输出
- output/<TARGET>/document.docx
- output/<TARGET>/generation_report.json
- output/<TARGET>/validation_report.json

## 工具与检查
工具负责解析需求、规划文档结构、生成 DOCX 和读取生成结果。Checker 检查输入完整性、DOCX 可打开、必需章节、图片、样式及报告字段。工具失败时必须返回结构化错误，不能留下伪成功文件。

## 文档与环境
提供完整用户文档、开发者文档、requirements.txt、setup.py、Makefile、示例输入及 make check/check_example/run 入口。
```

这个版本只用于解释最低结构。正式需求应逐项说明工具输入输出、异常情况、Checker 证据和业务验收，否则 Agent 仍需要在首阶段补足大量设计决策。

## 2. 准备样例输入

在 `input/test_input/` 放入较小但完整的案例：

```text
test_input/
├── content.md
├── document_requirements.md
└── assets/
    └── architecture.png
```

正文应至少包含二级标题、段落、列表、表格和一个图片引用。要求文档应明确中文字体回退、页面大小、图片缺失时的行为和输出文件名。这样生成器才能规划有意义的工具测试与 Checker fixture。

## 3. 检查环境

```bash
cd ~/FDocB/UCAgent/examples/workflow_builder
python setup.py --check
test -f ~/FDocB/UCAgent_t/workspace_docx/input/guide.md
test -d ~/FDocB/UCAgent_t/workspace_docx/input/test_input
```

如果不使用本地配置，先在当前 shell 执行本机约定的 `ucagent_env` 和 `proxy_on`。代理是否必需取决于模型服务；不要把 Token 写进 `guide.md` 或 `.workflow_builder/local.mk`。

## 4. 启动监督模式

直接启动 TUI：

```bash
make WS=~/FDocB/UCAgent_t/workspace_docx/workspace run
```

`run` 默认附带 `--loop`，Agent 会自动获取并继续任务。希望在共享 tmux 中观察时，可以使用 Makefile 的 `session` 目标，或者自行创建 tmux 后在其中执行同一条命令。监督模式下不要替 Agent 生成业务文件；连续失败后应定位母工作流契约、指导文档或 Checker 是否存在问题。

![Workflow Builder 运行界面](../resource/workflow_builder实际运行图.png)

## 5. 观察进度

正常情况下，`workspace/wfgen/workflow_implementation_plan.md` 会先出现，随后生成 requirements manifest、输入示例 manifest、workflow build spec，最后物化 `workspace/workflow/`。计划文件中的阶段记录只能追加本阶段内容，不得覆盖前面阶段。

每隔一段时间检查：

```bash
find ~/FDocB/UCAgent_t/workspace_docx/workspace/wfgen -maxdepth 1 -type f -printf '%f\n'
find ~/FDocB/UCAgent_t/workspace_docx/workspace/workflow -maxdepth 2 -type f | head
```

不要因为单次长模型调用就立即终止。连续多次失败、同一检查反复执行且产物时间戳不变、上下文连续压缩或明确异常堆栈，才属于需要诊断的信号。

## 6. 构建结束后的检查

```bash
cd ~/FDocB/UCAgent_t/workspace_docx/workspace/workflow
python setup.py --check
make check
make check_example
```

生成工作流自己的 `setup.py` 和 Makefile 位于 `workspace/workflow/`，它们与 Workflow Builder 根目录中的环境配置程序不是同一个文件。失败时保留完整返回码和日志，不要只根据某个输出文件存在就宣称完成。

## 常见失败

- `missing guide file`：`WS` 应指向业务根目录下的 `workspace/`，而不是业务根目录。
- TUI 没有自动开始：确认使用 `make ... run`，并且没有清空 `RUN_LOOP_ARGS`。
- 恢复旧阶段：这是 `.ucagent` 历史行为；是否清历史应根据本次是否需要续跑决定。
- 引用文件不存在：检查 workflow build spec 是否把未来文件误写为当前 reference。
- 阶段反复失败：先看 TUI 中 Checker 的准确描述，再查 `workflow_implementation_plan.md` 的“问题与处理”。

## 可直接使用的样例正文

`input/test_input/content.md` 可以包含：

```markdown
# Workflow Builder 使用说明

## 目标
本文档向第一次使用 UCAgent 的工程师说明工作区、生成、评估和增量修复流程。

## 操作步骤
1. 准备需求和样例输入。
2. 启动构建工作流并观察阶段。
3. 运行静态评估并审批问题。

## 结果表
| 动作 | 主要结果 |
| --- | --- |
| 构建 | workflow/ |
| 评估 | eval/*.json |

![系统结构](assets/architecture.png)
```

`document_requirements.md` 应写明 A4、页边距、标题层级、中文字体回退、页码、目录、表格样式、图片最大宽度、缺图行为和输出文件名。图片可以使用本文档 `resource/` 中一张较小截图复制为样例，但不得只提供图片而没有替代文字。

## tmux 启动与查看

希望另一个终端只读观察时：

```bash
make WS=~/FDocB/UCAgent_t/workspace_docx/workspace session
tmux attach -t ucagent_workflow_builder -r
```

只读 attach 不会把按键传给 TUI。需要停止时进入可写会话，先 `Ctrl+C` 等待当前命令取消，再按 UCAgent 提示退出；不要直接删除 tmux session，让子进程和权限守护留在后台。

## 阶段观察表

| 观察结果 | 判断 | 下一步 |
| --- | --- | --- |
| 工具调用持续变化，文件增加 | 正常执行 | 继续监督 |
| 同一 Checker 失败 1–2 次且内容变化 | Agent 正在修复 | 暂不干预 |
| 同一错误连续多次，文件无变化 | 可能是契约或指导问题 | 检查阶段 GuideDoc 和 Checker |
| 出现模型流异常后自动 retry | 外部调用中断 | 观察重试是否恢复 |
| 压缩后立即再次全文读取 | 上下文策略问题 | 限制读取并修母指导 |

## 产物抽查顺序

构建完成后先检查 `workflow_implementation_plan.md` 是否覆盖全部阶段和问题记录，再检查 `workflow_build.yaml` 中工具/Checker是否比用户原始需求更具体。随后核对 `workflow/` 公开文件、config 注册、开发者文档源码分析和环境入口。最后才运行 Make 验收。这个顺序能避免在设计明显缺项时反复运行昂贵检查。
