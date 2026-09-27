
# Bug Review 插件

复核已有 UnityTest 工作区中的 Bug 声明。插件在隔离副本中重跑现有测试，分析真实波形、规格和 RTL，保留每条原始声明的裁决，并把同根因的 Bug 关联起来。工作流为 `bug_review:analysis`。

当前框架、输出目录与功能版本变化见 [工作流与版本记录](CHANGELOG.md)；需求和设计记录见 [分析工作流与优化需求](ANALYSIS_OVERVIEW.md)；运行中的阶段操作见 [分析指导](src/bug_review/Guide_Doc/analysis.md)。

## 运行

运行环境需满足插件声明的 `UCAgent>=26.9.2.dev6`。版本不足时，`plugin-check` 会在加载前拒绝插件。

在插件目录执行：

```bash
make plugin-check
make bug-review-analysis
```

默认读取 `inputs/workspace_*`，逐个重新复核所有模块，并更新 `output/index.html` 总索引。每个模块的最终概况在 `output/workspace_NAME/report/index.html`，可点进失败 case 与疑似 Bug 详情。运行中的 `review_index.json`、逐 case/Bug 记录和签名收据位于该模块的 `runs/<run-id>/results/`。准备阶段复制分析文本、测试源码、UnityTest cases 与 DUT 运行包。工作流收集并重跑本次模块的全部 pytest 用例，先独立分析失败，再对照原 Bug 报告。仅重跑一个模块：

```bash
make bug_review_raid_dec_top
```

可设置 `INPUT_ROOT`、`OUTPUT_ROOT`、`PYTHON`、`AGENT_ARGS` 和 `ARGS`。例如：

```bash
make bug-review-analysis OUTPUT_ROOT=/absolute/path/review-output
```

输出根目录必须与输入工作区分离。模块运行状态和签名 receipt 留在 `output/workspace_NAME/runs/`；对外 `report/` 只保存最终页面及页面清单。单模块命令不会改写其他模块的结果。已完成运行若缺少门户，可执行 `PYTHONPATH=src:../.. python -m bug_review.workflow publish --workspace /absolute/path/to/run` 恢复发布。

## 直接准备与启动

```bash
PYTHONPATH=src:../.. python -m bug_review run-analysis \
  --input-root /absolute/path/inputs \
  --output-root /absolute/path/review-output \
  --run workspace_raid_dec_top=/absolute/path/inputs/workspace_raid_dec_top \
  -- --tui
```

`--run workspace_NAME=/absolute/path/workspace_NAME` 只选择指定模块；不传时全部重跑。启动 UCAgent 前，命令复制分析文本、UnityTest cases 目录和 DUT 运行包到本次模块执行区。六阶段依次收集并全量重跑、独立分析失败、取得 DUT 波形证据、对照原报告、合并根因和发布。模块完成后，工作流发布模块 HTML 并更新总索引。

更新插件 Skill 后重新启动工作流，以便把新 Skill 复制到运行工作区。

## 包内结构

`ucagent-plugin.toml` 是源码态发现清单，`pyproject.toml` 定义安装入口。包代码位于 `src/bug_review/`：`workflows/analysis.yaml` 声明六阶段，`checkers/` 校验阶段产物，`Guide_Doc/` 提供执行指导，`templates/` 初始化复核笔记，`skills/` 提供阶段 Skill、按 Bug ID 查询及报告脚本。插件提供全量收集、回归报告导入、索引查询、Schema、引用核实、收据附着、case lint、一次性归因提交、裁决草稿/提交、修订查询和渲染工具；波形分析与 receipt 查询仍使用 UCAgent 原生工具。
