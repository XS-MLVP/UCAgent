
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

完整波形预览使用报告内的静态 Surfer 和发布时保存的波形快照，无需启动 UCAgent 波形接口。发布会在 `output/` 根目录生成独立的 `serve.py`。只分享整个 `output/` 文件夹时，接收方可直接运行：

```bash
cd output
python3 serve.py
```

然后在浏览器打开 `http://127.0.0.1:8765/index.html`。`serve.py` 只用 Python 标准库，仅提供门户和已发布的模块报告；不需要插件源码或 UCAgent。复制或压缩整个 `output/` 时，要保留 `workspace_*/report` 与同目录 `runs/` 的相对链接关系。直接用 `file://` 打开 HTML 时，Surfer 的模块与 WebAssembly 无法正常加载。若签名收据对应的原波形在发布前已轮换，详情页仍显示波形分析与收据，但不提供完整预览按钮。插件开发环境中仍可用 `make bug-review-serve` 启动同一个服务。

## 启动前准备输入

输入目录沿用默认 UCAgent 的模块布局，而不是另建 Bug Review 专用 RTL 目录。模块根目录应包含 `launch.yaml`、`unity_test/` 和 RTL；可用的 `filelist.txt` 可以独立作为 Picker 输入，不需要同名顶层 `.v/.sv`。

`prepare-input` 是启动前由 LLM 或操作者执行的独立 Skill。先运行它并根据 `prepare_manifest.json` 完成旧报告的重分析，确认 `bug_reports.reanalysis_required` 为空，再通过 UCAgent Master 的 Launch 页面选择生成目录中的 `workspace_<dut>/launch.yaml`。Master 不调用 `prepare_inputs.py`，也不替缺失报告生成 canonical 文件；它只对已经准备好的输入建立本次运行的隔离快照。

```bash
python3 ../../skills/bug-review-orchestrator/scripts/prepare_inputs.py \
  --source ../../examples/bosc_LoadUnit \
  --input-root inputs
```

随后从 Master 启动任务；默认工作流和 Bug Review 都使用生成的 `inputs/workspace_bosc_LoadUnit`，只在运行区增加不可变快照和复核结果。下面的 `bug_review.workflow` 命令仅用于不经过 Master 的直接插件运行。

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
