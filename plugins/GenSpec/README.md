
# GenSpec（Deprecated）

> **已弃用（deprecated）**：GenSpec 是旧版文档生成插件。后续文档生成请使用 [SpecGenerator](../SpecGenerator/README.md)。以下内容保留供旧工作流参考。

UCAgent 的通用规格文档生成插件：整合 Markdown、CSV 和 Verilog/SystemVerilog/Scala 源码，生成主规格、子组件规格及 FG/FC/CK 功能检测点，并可与已有检查点 CSV 对比。

插件只提供工作流和 Guide_Doc，复用 UCAgent 内置工具与 Checker，无需自定义 Python 工具或 Skill。安装 UCAgent 不会自动安装或启用它。

## 安装与运行

先按 UCAgent 安装说明安装核心、配置模型，再从 UCAgent 仓库根目录执行：

```bash
python -m pip install ./plugins/GenSpec
ucagent --validate-plugin gen-spec

mkdir -p output/genspec-adder
cp -R plugins/GenSpec/cases/Adder output/genspec-adder/
ucagent output/genspec-adder Adder \
  --plugin gen-spec --plugin-workflow gen-spec:generate-spec \
  --output spec --backend langchain --tui --loop
```

要求 Python 3.11+、UCAgent `>=26.9.2.dev14`。插件未必已发布到 PyPI，使用仓库路径或自行构建的 wheel 安装。源码开发时，可将 `--plugin gen-spec` 替换为 `--plugin ./plugins/GenSpec`；无需手动指定 YAML 或 Guide_Doc 路径。

也可在插件目录通过 Makefile 直接运行源码：

```bash
cd plugins/GenSpec
make run CASE=Adder
# 仅启动 MCP 服务，供外部 Agent 连接
make mcp CASE=DCache
```

`make run` 默认使用 LangChain，可设置 `BACKEND` 和 `ARGS`；默认工作区为 `output/workspace_<CASE>`，输出目录为 `spec/`。`make prepare` 只在输入目录不存在时复制案例，保留已有工作区。MCP 客户端连接方法见 UCAgent 的 MCP 使用文档。

## 输入、流程与产物

自有输入放入 `<workspace>/<DUT>/`，包括设计说明、`.v/.sv/.scala` 源码。默认还需 `<DUT>_functions_and_checks.csv`，用于最后的检查点差异分析。

`cases/Adder` 和 `cases/DCache` 包含参考 CSV；`cases/Sbuffer` 只有设计与源码资料。没有参考 CSV 时，显式关闭对比阶段：

```bash
GENSPEC_COMPARE_REFERENCE=false make run CASE=Sbuffer
```

关闭对比只省略最后的 CSV 映射与差异分析，规格编写、人工审核和新检查点生成仍会执行。设置 `HUMAN_CHECK_CK=true` 可额外启用检查点人工审核。

工作流依次执行：主规格初稿 → 子组件初稿 → 逐文件源码补全 → 子规格完善 → 人工审核 → FG/FC/CK 分析 → 参考 CSV 对比。人工审核阶段需在 UCAgent 控制台使用 `hmcheck_pass` 确认，再继续执行。

主要产物均位于 `<workspace>/<OUT>/`，上述命令中 `OUT=spec`：

| 文件 | 内容 |
| --- | --- |
| `<DUT>_spec.md` | 主规格文档 |
| `<DUT>_spec_<component>.md` | 按需生成的子组件规格 |
| `<DUT>_spec_summary.md` | 人工审核摘要 |
| `<DUT>_functions_and_checks.md` | FG/FC/CK 功能检测点 |
| `<DUT>_line_func_map.txt`、`<DUT>_line_map_analysis.md` | 参考 CSV 每行与新检查点的映射、差异分析；仅对比启用时生成 |

规格文档按 [Guide_Doc 模板](src/gen_spec/Guide_Doc/dut_spec_template.md) 保留二级标题，文件引用使用 `<ref_file>相对工作区路径[:起始行-结束行]</ref_file>`。源码阶段记录通过 `ReadTextFile` 读取文件的证据；结构检查不能代替对文档内容的人工确认。

## 维护

| 路径 | 用途 |
| --- | --- |
| `ucagent-plugin.toml`、`pyproject.toml` | 源码加载入口、发行包和 entry point |
| `src/gen_spec/plugin.py` | 声明工作流与指导文档路径 |
| `src/gen_spec/workflows/generate-spec.yaml` | 阶段任务、内置 Checker 和配置 |
| `src/gen_spec/Guide_Doc/` | 随包发布、启动时复制到工作区的规格指导模板 |
| `cases/` | 输入案例，包含在源码分发包中 |
| `tests/` | 工作流初始化、资源复制和文档验收回归 |

在插件目录执行 `python -m pip install -e '.[dev]'` 后，用 `make validate`、`make test`、`make package` 验证和打包。修改工作流或资源后重新启动任务，使工作区使用最新的运行资源。
