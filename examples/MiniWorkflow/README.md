
# MiniWorkflow：项目文档生成示例

本示例读取 `Calculator/README.md`，分两阶段生成项目分析和使用文档，用来学习 UCAgent 的配置、工具、Guide_Doc 和 Checker。它不运行 RTL 仿真，不需要 picker。

## 运行

先安装 UCAgent、激活对应 Python 环境，并配置 `OPENAI_MODEL`、`OPENAI_API_KEY` 和 `OPENAI_API_BASE`。在本目录执行：

```bash
make test
make run ARGS="--loop"
```

`make test` 检查自定义工具和 Checker 是否可导入。`make run` 会清理本示例的 `output/`，复制 Calculator 并启动 TUI；`--loop` 使模型立即执行，省略时需在 TUI 中输入 `loop`。

Makefile 优先使用仓库内的 `ucagent.py`，独立复制本目录后则使用已安装的 `ucagent` 命令。它会把本目录加入 `PYTHONPATH`，供配置导入 `my_tools` 和 `my_checkers`。

需要手动连接外部 Code Agent 时使用：

```bash
make run ARGS="--mcp-server --backend=codex"
```

然后在另一个终端进入 `output/`，配置客户端连接 `http://127.0.0.1:5000/mcp`。完整连接步骤见 [MCP 接入](../../docs/content/01_start/03_mcp_mode.md)。

## 阶段和结果

| 阶段 | 产物（相对于工作区 `output/`） | 验收 |
| --- | --- | --- |
| `analyze_project` | `unity_test/Calculator_analysis.md` | 500–2000 字、Markdown 格式 |
| `generate_documentation` | `unity_test/Calculator_documentation.md` | 800–3000 字、四个必需章节、Markdown 格式 |

字数按中文字符和英文单词统计。所有内容须基于 Calculator README；通过 `Check` 后记录阶段日志，再调用 `Complete` 推进。

```bash
cat output/unity_test/Calculator_analysis.md
cat output/unity_test/Calculator_documentation.md
```

## 修改入口

- `mini.yaml`：`stage` 定义阶段，`checker` 定义验收；构造参数放在 `checker[].args` 中。
- `my_tools.py`：`CountWords` 统计字数，`ExtractSections` 提取标题。
- `my_checkers.py`：`WordCountChecker` 检查字数，`RequiredSectionsChecker` 检查必需章节。
- `Guide_Doc/`：阶段输出格式和文档模板。
- `Calculator/README.md`：输入项目说明。

完整教程及配置字段见 [Mini 示例](../../docs/content/03_develop/08_mini_example.md)。
