
# Bug Review 插件

复核已有 UnityTest 工作区中的 Bug 声明。插件在隔离副本中重跑现有测试，分析真实波形、规格和 RTL，保留每条原始声明的裁决，并把同根因的 Bug 关联起来。工作流为 `bug_review:analysis`。

当前运行契约是 [CHANGELOG.md 的 v1.0 基线](CHANGELOG.md#当前基线v10)，其中说明两种启动入口、核心代码、输入、工作区、输出和记录模型。输入目录、必需材料与原报告格式见 [输入准备](INPUTS.md)；需求和设计记录见 [分析工作流与优化需求](ANALYSIS_OVERVIEW.md)；运行中的阶段操作见 [分析指导](src/bug_review/Guide_Doc/analysis.md)。

需要同时复核多个模块时，可由监管 Agent 使用 [多模块复核监管 Skill](src/bug_review/skills/multi-review-supervisor/SKILL.md) 分配独立子 Agent、监控各模块运行，并在全部结束后更新总门户。

## 运行

运行环境需满足插件声明的 `UCAgent>=26.9.2.dev6`。版本不足时，`plugin-check` 会在加载前拒绝插件。

插件是纯 UCAgent 插件：准备运行区用插件 Makefile，启动复核用 UCAgent 自身。在插件目录执行：

```bash
make bug_review_raid_enc_top            # 一键复核：init 准备后启动 UCAgent（默认无人值守）
make mcp_bug_review_raid_enc_top        # 交互复核：启动 TUI 和 MCP 服务
make bug_review_all                     # 依次复核 inputs/ 下全部模块
make init_raid_enc_top                  # 只准备：编译 DUT 包（如缺失）并建立新运行区
make status_raid_enc_top                # 查看该模块工作区的阶段状态
make publish_raid_enc_top               # 校验报告并重建总门户
make plugin-check                       # 校验插件
```

`init_<module>` 只用于首次准备：校验模块存在、picker 编译 DUT 包（仅包目录缺失时）并建立模块工作区 `output/<module>/`，已有目录时拒绝覆盖。`bug_review_<module>` 和 `mcp_bug_review_<module>` 在工作区不存在时自动准备，存在时直接继续当前阶段；后者对齐仓库根 Makefile 的 MCP 模式，使用 `-s -hm --tui --mcp-server-no-file-tools`。`INPUT_ROOT`／`OUTPUT_ROOT`／`PYTHON`／`PICKER_ARGS` 可覆盖默认值，追加启动参数用 `ARGS="..."`。上级虚拟环境可通过 `PYTHON=/Users/fy/work/XSV/.venv/bin/python` 选用。分步执行时用 UCAgent 在模块工作区启动 `bug_review:analysis` 工作流：

```bash
PYTHONPATH=src:../.. ../../.venv/bin/python ../../ucagent.py \
  output/raid_enc_top BugReview \
  --plugin $(pwd) --plugin-workflow bug_review:analysis --output verification_review/analysis \
  -s -hm --tui --mcp-server-no-file-tools
```

无人值守用后端参数，例如 `--backend claude --mcp-server --mcp-server-port -1 --loop --exit-on-completion`。六阶段依次收集并全量重跑、独立分析失败、取得 DUT 波形证据、对照原报告、合并根因和发布。每个模块的最终报告位于 `output/<module>/verification_review/report/index.html`；分析记录位于 `verification_review/analysis/`，唯一测试执行副本位于 `verification_review/run/unity_test/`，Master 提供的 DUT 和 pytest 报告分别位于工作区根目录与 `verification_review/run/test_report/`。报告直接渲染到 `verification_review/report/`；Complete 回调只重建 `output/index.html` 和独立报告服务。若门户缺失，执行 `make publish_<module>` 即可重建。中断后重新执行同一个启动目标即可继续；显式执行 `init_<module>` 仍会保护已有目录。

完整波形预览使用报告内的静态 Surfer 和发布时保存的波形快照，无需启动 UCAgent 波形接口。发布会在 `output/` 根目录生成独立的 `serve.py`。只分享整个 `output/` 文件夹时，接收方可直接运行：

```bash
cd output
python3 serve.py
```

然后在浏览器打开 `http://127.0.0.1:8765/index.html`。`serve.py` 只用 Python 标准库，仅提供门户和已发布的模块报告；不需要插件源码、UCAgent 或私有 `analysis/`。直接用 `file://` 打开 HTML 时，Surfer 的模块与 WebAssembly 无法正常加载。若签名收据对应的原波形在发布前已轮换，详情页仍显示波形分析与收据，但不提供完整预览按钮。插件开发环境中仍可用 `make serve` 启动同一个服务。

更新插件 Skill 后重新启动工作流，以便把新 Skill 复制到运行工作区。

## 包内结构

`ucagent-plugin.toml` 是源码态发现清单，`pyproject.toml` 定义安装入口。包代码位于 `src/bug_review/`：`workflows/analysis.yaml` 声明六阶段，`checkers/` 校验阶段产物，`Guide_Doc/` 提供执行指导，`templates/` 初始化复核笔记，`skills/` 提供阶段 Skill、按阶段使用说明。插件提供全量收集、回归报告导入、索引查询、Schema、引用核实、收据附着、case lint、一次性归因提交、裁决草稿/提交、修订查询和渲染工具；波形分析与 receipt 查询仍使用 UCAgent 原生工具。
