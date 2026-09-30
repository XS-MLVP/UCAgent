
# Bug Review 输入准备

本文说明如何准备一个可供 `bug_review:analysis` 复核的模块。默认输入根目录是插件内的 `inputs/`，可用 `INPUT_ROOT` 指向其他目录。一个 `workspace_<dut>` 对应一次独立的模块复核；根目录下可以放多个模块。

## 推荐目录结构

```text
inputs/
└── workspace_<dut>/
    ├── launch.yaml                      # 推荐：默认 UCAgent/Picker 启动清单
    ├── <dut>.v / <dut>.sv               # 可选：没有可用 filelist 时的顶层入口
    ├── filelist.txt                     # 推荐：存在时可省略同名顶层 .v/.sv
    ├── *.v / *.sv / *.vh / *.scala      # filelist 引用的 RTL
    ├── unity_test/
    │   ├── tests/                         # 必需：可由 pytest 收集和重跑的测试、fixture、模型及辅助代码
    │   │   ├── test_*.py
    │   │   └── ...
    │   ├── .pytest.ini                    # 可选：原验证使用的 pytest 配置
    │   ├── <dut>_bug_summary.md           # 建议提供：原 Bug 摘要表
    │   ├── <dut>_bug_analysis.md          # 建议提供：原 Bug 详情与 BG／TC 标签
    │   ├── <dut>_static_bug_analysis.md   # 可选：静态分析线索
    │   └── line_map/                      # 可选：CK 到规格行段的映射
    ├── <dut>/                             # 按测试需要提供：可导入的 DUT 运行包及规格文档
    │   ├── __init__.py                    # Python 包入口
    │   ├── libUT_<dut>.py                 # 若测试依赖：仿真绑定代码
    │   ├── _UT_<dut>.so                   # 若测试依赖：编译后的 DUT 模块；其他平台扩展名可能不同
    │   ├── libUT<dut>.dylib               # 若测试依赖：仿真共享库；其他平台扩展名可能不同
    │   ├── xspcomm/                       # 若测试依赖：通信库及其共享库
    │   ├── RAID_*.md                      # 示例：接口、功能和存储等规格文档
    │   └── ...                            # 测试所需的配置、数据和其他运行文件
    └── ...                                # 其他供复核引用的规格、接口和设计文档
```

例如 `workspace_raid_dec_top` 对应的报告文件名是 `unity_test/raid_dec_top_bug_summary.md` 和 `unity_test/raid_dec_top_bug_analysis.md`。`workspace_` 后的 DUT 名称决定这两个文件名，也决定准备阶段查找的 `<dut>/` 运行包目录；模块目录名、`launch.yaml` 中的 `dut/module` 和命令中的模块名必须一致。该目录同时是默认 UCAgent 的输入：`launch.yaml`、RTL、filelist 和 `unity_test/` 不再为 Bug Review 另建一套布局。仓库中的 `examples/Adder` 和 `examples/bosc_LoadUnit` 是这种组织方式的参考。

上面的 `.so`、`.dylib`、绑定代码和 `xspcomm/` 是现有 RAID 示例的运行文件，不要求其他 DUT 使用相同文件名或编译方式；以测试能在当前机器导入和执行为准。模块根目录的 RTL 是默认启动和 Bug Review 共用的设计源码。原运行包里已有的 `.fst` 波形和覆盖率数据不是本次重跑的替代品，也不是必备输入。

## 各类输入的要求

| 输入 | 要求与用途 |
| --- | --- |
| `unity_test/tests/` | **必需。** 包含本模块的 pytest 用例，以及收集、执行这些用例所需的 fixture、驱动、参考模型、辅助代码和相对路径数据文件。首次阶段会按当前 pytest 配置收集**全部**测试节点并重跑；收集报错或没有收集到节点时，不能建立完整基线。 |
| 原 Bug 文档 | 当前复核使用 `unity_test/<dut>_bug_summary.md` 和 `unity_test/<dut>_bug_analysis.md`。旧版 UnityTest 若缺少其中一份，先保留并阅读旧报告，再按本目录现有 `workspace_*` 报告示例和插件 `Guide_Doc/analysis.md` 重建缺失文件；不得凭空补 Bug、测试结果、置信度或波形。没有既有 Bug 时，依据可用原始材料生成无 Bug 条目的规范报告；原始材料不足时明确记录缺口后再启动复核。 |
| `.pytest.ini` | 可选；存在时会随测试复制，并用于 pytest 收集和重跑。保留原测试实际需要的插件与参数，但检查其中的 `pythonpath`、外部插件和平台依赖在新机器上是否可用。报告目录由本次运行区重定向，不必让输入目录可写。 |
| `<dut>/` | 若测试需要 `import <dut>` 或加载编译好的 DUT，则提供完整可运行包，包括 Python 包、共享库及其依赖。准备阶段将此目录复制到运行副本的测试目录。测试依赖的相对路径文件应位于 `unity_test/tests/` 或此运行包中；只放 RTL 源码而缺少测试所需运行包，通常无法全量重跑。 |
| `launch.yaml` | 推荐。使用相对当前 YAML 的路径声明 `dut`、`module`、`files.filelist`、`files.main_rtl`、额外 RTL 和 Verification Needs。`files.filelist` 可单独作为 Picker 输入；此时不需要 `files.main_rtl` 或同名顶层 `.v/.sv`，但 filelist 中的 RTL 路径必须在当前机器上可解析。 |
| Spec 与 RTL | 建议提供与当前 DUT 版本一致的规格 Markdown 和 RTL 源文件。确认 DUT Bug 需要核实真实规格要求、RTL 首错位置与因果链；仅有原报告的结论不足以确认。文件可以按项目原有目录组织，引用时使用输入镜像内的相对路径和准确行号。若提供 `filelist.txt`，它是默认 Picker 和 Bug Review 共享的 RTL 文件集合。 |
| `unity_test/line_map/*_line_func_map.txt` | 可选。已有 CK 到规格行段的映射可帮助定位候选 Spec 引用；没有时仍可由复核者阅读规格后填写。映射只是线索，不能代替语义核实。 |
| 测试总结、覆盖率文档、静态 Bug 分析 | 相关 Markdown 可作为参考文本保留，用于对账或定位。旧 `uc_test_report/` 不会复制到本次运行区；测试结果以新运行的 pytest 报告为准。覆盖率只有在本次记录中填写了可核实来源和统计口径后才会显示为可用。 |

## 原 Bug 文档的可识别格式

摘要文件使用八列表格，列名依次为 `Name | Severity | Alias | CK | Analysis | Locations | Confidence | Ref`。插件从 `Name` 建立 Bug ID，从 `Confidence` 读取原置信度，并保留对应行作为来源；Bug ID 使用英文字母、数字、下划线或连字符，且不能重复。`Ref` 中的 `<dut>_bug_analysis.md:起始行-结束行` 可作为报告级用例清单的来源范围。

分析文件中的原 Bug 块使用六级标题和 `<BG-...>` 标签；用例引用使用 `<TC-unity_test/tests/...py::test_...>` 形式。插件只提取原文块、标签、行段和 TC 字样，不会根据 BG／FC／CK 名称自动判定真实归属。复核者会结合独立重跑结果、测试、Spec、RTL 和波形填写最终关联。保留原文标签与行号，便于逐条追溯；若只有分析文件，带 BG 标签的块仍可建立原 Bug 骨架。

## 准备与运行

在插件目录运行全部模块：

```bash
make bug-review-analysis
```

只运行一个模块：

```bash
make bug_review_raid_dec_top
```

使用其他输入根目录：

```bash
make bug-review-analysis INPUT_ROOT=/absolute/path/inputs
```

每次运行会把测试及 DUT 运行包复制到该模块新的 `output/workspace_<dut>/runs/run-<id>/`，把 Markdown、Python、RTL 等文本材料复制到其 `results/inputs/`。输入目录本身不会被工作流改写；已有的 `.ucagent/`、`Guide_Doc/`、`uc_test_report/`、缓存和旧 `output/` 不作为本次复核的权威输入，也无需为运行而复制。签名波形来自本次测试运行，不要求预先放入 `inputs/`。

## 从默认模块目录准备 Bug Review

`prepare-input` 是启动前独立执行的 Skill，由 LLM 或操作者先完成输入整理、旧报告重分析和 manifest 校验，再启动 UCAgent Master。Master 和 `bug_review` workflow 只消费已经准备好的目录，不调用 `prepare_inputs.py`，也不在启动时替旧报告补 canonical 文件。

`skills/bug-review-orchestrator/scripts/prepare_inputs.py` 接受与 `examples/Adder` 相同的模块目录。它会读取 `launch.yaml` 中的 DUT 名称，复制 `launch.yaml`、filelist、RTL、规格和 `unity_test/`，再生成 `workspace_<dut>/prepare_manifest.json`。当目录有可用 `filelist.txt` 或 `.f` 文件时，manifest 会标记 `main_rtl_required: false`，准备过程不会要求 `<dut>.v` 或 `<dut>.sv`：

```bash
python3 skills/bug-review-orchestrator/scripts/prepare_inputs.py \
  --source examples/bosc_LoadUnit \
  --input-root plugins/bug_review/inputs
```

完成准备并确认 `reanalysis_required` 为空后，再通过 UCAgent Master 的 Launch 页面选择生成目录中的 `workspace_<dut>/launch.yaml` 启动任务。默认工作流和 Bug Review 必须共享这份准备好的目录，不要让 Master 重新调用准备脚本。

例如，直接运行默认工作流时仍可使用同一份目录：

```bash
make mcp_bosc_LoadUnit CWD=output/workspace_bosc_LoadUnit
```

Bug Review 使用生成的 `plugins/bug_review/inputs/workspace_bosc_LoadUnit`，不重新定义 RTL 目录或另造一个顶层入口。filelist 中的相对路径以 filelist 所在工程目录为基准；跨工程路径应在准备前转换为当前节点可访问的绝对路径，或把引用的 RTL 按原相对路径复制进模块目录。
