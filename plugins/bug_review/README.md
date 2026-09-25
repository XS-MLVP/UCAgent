
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

默认读取 `inputs/workspace_*`，输出到 `output/results/index.html`。仅分析一个工作区：

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

`prepare-analysis` 可重复传入 `--run workspace_NAME=/absolute/path/workspace_NAME`，仅选择指定工作区；`--batch-size` 控制每次返回的判断任务数，`--timeout` 控制 UnityTest 重跑时限。该准备步骤只记录输入，正式重跑发生在 `replay` 阶段。

## 包内结构

`ucagent-plugin.toml` 是源码态发现清单，`pyproject.toml` 定义安装入口。包代码位于 `src/bug_review/`：`workflows/analysis.yaml` 声明五阶段，`checkers/` 校验逐工作区产物，`Guide_Doc/` 提供执行指导，`templates/` 初始化可选复核笔记，`skills/review-notes/` 可从阶段产物刷新笔记摘要，`analysis_core/` 保存解析与持久化模块。技能支持可关闭；复核裁决和阶段完成不依赖笔记 Skill。
