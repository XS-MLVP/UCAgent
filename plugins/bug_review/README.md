
# Bug Review 插件

复核已有 UCAgent 验证产物中的失败用例和 Bug 声明，保留测试重跑、波形证据、根因审查、报告发布和独立评分。插件 ID 为 `bug_review`，提供 `bug_review:analysis` 与 `bug_review:scoring` 两套工作流。

## 从 UCAgent 仓库启动

需要 Python 3.11+、UCAgent 依赖以及输入 DUT 的测试运行环境。在 UCAgent 仓库根目录执行：

```bash
make bug-review-plugin-check
make bug_review_raid_dec_top
```

第二条命令读取 `examples/workspace_raid_dec_top/`，先复制输入并通过 UCAgent 测试工具重跑测试，然后准备分析工作区并启动 Agent。默认使用 `--backend blank --mcp-server --human --tui`，等待客户端驱动分析。

工作区为 `output/bug_review/workspace_raid_dec_top/`，分析报告入口为该目录的 `analysis/index.html`。分析发布完成后可单独评分：

```bash
make bug-review-scoring ANALYSIS_NAME=raid_dec_top
```

评分工作区为 `output/bug_review/workspace_raid_dec_top-scoring/`，报告入口为 `scores/index.html`。

可以覆盖 `PYTHON`、`INPUT_ROOT`、`OUTPUT_ROOT`、`CONFIG`、`AGENT_ARGS` 和 `ARGS`。例如：

```bash
make bug_review_raid_dec_top \
  PYTHON=/absolute/path/venv/bin/python \
  ARGS='--mcp-server-port 5001'
```

新插件使用独立的 Python 包、工具名和默认输出目录。原 `plugins/Benchmark/` 和 `make benchmark_<name>` 入口继续保留。

## 工作流与证据

分析依次执行输入发现、解析、失败用例回放与归因、波形复核、语义比较、失败模式审查、根因申诉、报告根因对齐和发布。使用 `BugReviewRunStage`、`BugReviewTasks`、`BugReviewSubmitResponse`、`BugReviewWaveInfo` 和 `BugReviewStatus` 推进，Check 通过后记录日志并 Complete。

必须重跑现有测试；历史报告不能替代本次执行。确认 DUT Bug 必须有真实的签名波形证据。没有发现 Bug 时不制造 Bug 或波形记录。评分只消费冻结的分析清单，不运行测试或调用模型。报告发布不修改随插件分发的 GT 库。

详细任务契约见 [分析指导](bug_review/Guide_Doc/analysis.md) 和 [评分指导](bug_review/Guide_Doc/scoring.md)。技能支持可以关闭，插件没有必需技能；回放辅助资源直接随包分发。

## 安装和直接调用

在本插件目录执行：

```bash
pip install .
ucagent --validate-plugin bug_review
python -m bug_review --help
```

源码态可在插件目录使用相同的 `python -m bug_review` 命令。直接准备工作区时传入显式输入：

```bash
python -m bug_review prepare-analysis \
  --config bug_review.toml \
  --workspace /tmp/bug-review-analysis \
  --run model=/absolute/path/prepared-inputs \
  --replay-enabled true
python -m bug_review launch --workspace /tmp/bug-review-analysis -- --tui
```

原生 UnityTest 输入必须先复制到分析工作区内部并重跑；通常直接使用 Make 入口即可。手动准备时使用 `python -m bug_review.input_preparation --source ... --destination /tmp/bug-review-analysis/input_runs --run-tests`，随后将这个副本作为 `--run` 的路径。

`--run LABEL=PATH` 相对路径以调用目录为基准；`[model_inputs]` 中的相对路径以配置文件目录为基准。没有显式输入时不会猜测历史模型目录。恢复时使用相同工作区；输入或已验收证据改变时准备新工作区。

报告中的本地波形查看服务可用以下命令启动，默认监听 `127.0.0.1:8765`：

```bash
python -m bug_review.report_server --root /absolute/path/to/UCAgent
```

## 目录和保留范围

```text
Makefile / bug_review.toml / ucagent-plugin.toml
pyproject.toml / requirements.txt
bug_review/
  plugin.py / adapter.py / workflow.py
  input_preparation.py / inputs.py
  benchmark_workflow/    实际依赖的解析、证据、回放、报告及评分核心
  workflows/            analysis、scoring 阶段配置
  Guide_Doc/            运行指导
  configs/              GT、评分策略与契约、规格及报告 profile
  resources/            波形转换脚本和 QEMU Python 启动器
tests/                  入口、资源、证据及发布回归
```

从 Benchmark 复制当前工作流依赖闭包，输入解析和报告发布单独提取，不携带旧 CLI、独立 MCP 服务、历史批处理和维护脚本、技能包装或缓存。保留真实 DUT 的参考数据及 revision 契约；不复制空 DUT GT 文件和 `demo/first/second/new` 通用评分数据。内部产物字段与评分公式沿用复制来源的契约。

## 开发验证

```bash
python -m pytest -q tests
python -m build
```

构建应先生成 sdist，再从 sdist 生成 wheel。测试使用临时工作区，不需要运行真实 DUT 或模型服务；实际 DUT 仿真仍需对应的生成代码、依赖及运行时。
