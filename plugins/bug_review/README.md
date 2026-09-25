
# Bug Review 插件

复核已有 UnityTest 工作区中的 Bug 声明。插件在隔离副本中重跑现有测试，分析真实波形、规格和 RTL，保留每条原始声明的裁决，并把同根因的 Bug 关联起来。工作流为 `bug_review:analysis`。

需求和版本状态见 [分析工作流与优化需求](ANALYSIS_OVERVIEW.md)；运行中的阶段操作见 [分析指导](src/bug_review/Guide_Doc/analysis.md)。

## 运行

运行环境需满足插件声明的 `UCAgent>=26.9.2.dev6`。版本不足时，`plugin-check` 会在加载前拒绝插件。

在插件目录执行：

```bash
make plugin-check
make bug-review-analysis
```

默认读取 `inputs/workspace_*`，输出到 `output/results/index.html`。准备阶段只复制 Markdown/HDL/line-map 文本、UnityTest cases 目录及 DUT 运行包，不复制完整输入工作区、历史波形或报告产物。工作流按 JSON 选择性重跑 case，不运行无关的全量用例。每个工作区的 `bug_review.json` 是五阶段共用的权威数据，HTML 直接从它渲染。仅分析一个工作区：

```bash
make bug_review_raid_dec_top
```

可设置 `INPUT_ROOT`、`OUTPUT_ROOT`、`PYTHON`、`AGENT_ARGS` 和 `ARGS`。例如：

```bash
make bug-review-analysis OUTPUT_ROOT=/absolute/path/review-output
```

输出根目录必须与输入工作区分离。已有输出根目录若属于不同的输入任务，使用新的输出目录。

## 直接准备与启动

```bash
PYTHONPATH=src:../.. python -m bug_review prepare-analysis \
  --input-root /absolute/path/inputs \
  --output-root /absolute/path/review-output
PYTHONPATH=src:../.. python -m bug_review launch --workspace /absolute/path/review-output -- --tui
```

`prepare-analysis` 可重复传入 `--run workspace_NAME=/absolute/path/workspace_NAME`，仅选择指定工作区。启动 UCAgent 前，Makefile 调用准备步骤复制分析文本、UnityTest cases 目录和 DUT 运行包。阶段直接调用 `RunTestCases` 和默认 `WaveInfo`，仅重跑 `bug_review.json` 里选定的 case；五个阶段更新 `output/results/workspaces/workspace_NAME/bug_review.json`，报告 Skill 从这些 JSON 渲染 HTML。

更新插件 Skill 后重新启动工作流，以便把新 Skill 复制到运行工作区。

## 包内结构

`ucagent-plugin.toml` 是源码态发现清单，`pyproject.toml` 定义安装入口。包代码位于 `src/bug_review/`：`workflows/analysis.yaml` 声明五阶段，`checkers/` 校验各阶段直接生成的产物，`Guide_Doc/` 提供执行指导，`templates/` 初始化复核笔记，`skills/` 提供五个阶段 Skill 和可选笔记更新 Skill，`analysis_core/` 保存报告解析模块。插件不注册 Bug Review 阶段推进、任务队列或 WaveInfo 包装工具；阶段使用 UCAgent 原生工具与 Skill。
