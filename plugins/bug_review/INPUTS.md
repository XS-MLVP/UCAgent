
# Bug Review 输入准备

本文说明如何准备一个可供 `bug_review:analysis` 复核的模块。默认输入根目录是插件内的 `inputs/`，可用 `INPUT_ROOT` 指向其他目录。一个 `workspace_<dut>` 对应一次独立的模块复核；根目录下可以放多个模块。

输入已完整时直接启动。缺少 RTL、根目录 filelist 或启动清单时，可使用 [input-preparation Skill](src/bug_review/skills/input-preparation/SKILL.md) 明确选择来源并补齐；它不推断缺失依赖或原 Bug 结论。

## 推荐目录结构

```text
inputs/
└── workspace_<dut>/
    ├── launch.yaml                       # 必需：dut、module、files.filelist
    ├── filelist.f                        # 必需：本次可访问的 RTL 文件路径
    ├── rtl/                              # 可选：filelist 中的工作区内 RTL
    ├── <dut>.sv                           # 可选：顶层 RTL
    ├── unity_test/
    │   ├── tests/                         # 必需：可由 pytest 收集和重跑的测试、fixture、模型及辅助代码
    │   │   ├── test_*.py
    │   │   └── ...
    │   ├── .pytest.ini                    # 可选：原验证使用的 pytest 配置
    │   ├── <dut>_bug_summary.md           # 与下项至少提供一份
    │   ├── <dut>_bug_analysis.md          # 与上项至少提供一份
    │   ├── <dut>_static_bug_analysis.md   # 可选：静态分析线索
    │   └── line_map/                      # 可选：CK 到规格行段的映射
    ├── <dut>/                             # 可选：与本次 Python 兼容的 DUT 包及规格文档
    │   ├── __init__.py                    # Python 包入口
    │   ├── libUT_<dut>.py                 # 若测试依赖：仿真绑定代码
    │   ├── _UT_<dut>.so                   # 若测试依赖：编译后的 DUT 模块；其他平台扩展名可能不同
    │   ├── libUT<dut>.dylib               # 若测试依赖：仿真共享库；其他平台扩展名可能不同
    │   ├── xspcomm/                       # 若测试依赖：通信库及其共享库
    │   ├── RAID_*.md                      # 示例：接口、功能和存储等规格文档
    │   └── ...                            # 测试所需的配置、数据和其他运行文件
    └── 其他 Spec/接口文档                 # 也可位于模块根目录
```

例如 `workspace_raid_dec_top` 对应的报告文件名是 `unity_test/raid_dec_top_bug_summary.md` 和 `unity_test/raid_dec_top_bug_analysis.md`。`workspace_` 后的 DUT 名称决定这两个文件名，也决定准备阶段查找的 `<dut>/` 运行包目录；模块目录名、命令中的模块名必须一致。

上面的 `.so`、`.dylib`、绑定代码和 `xspcomm/` 是现有 RAID 示例的运行文件，不要求其他 DUT 使用相同文件名。`filelist.f` 可以引用模块目录内的 RTL，也可以引用运行节点已挂载的外部绝对路径；每项必须实际可访问。Spec 常见于 `<dut>/README.md` 或模块根目录。旧波形、覆盖率、`.ucagent/` 和 `uc_test_report/` 不是输入。

## 各类输入的要求

| 输入 | 要求与用途 |
| --- | --- |
| `unity_test/tests/` | **必需。** 包含本模块的 pytest 用例，以及收集、执行这些用例所需的 fixture、驱动、参考模型、辅助代码和相对路径数据文件。首次阶段会按当前 pytest 配置收集**全部**测试节点并重跑；收集报错或没有收集到节点时，不能建立完整基线。 |
| 原 Bug 文档 | `unity_test/<dut>_bug_summary.md` 和 `unity_test/<dut>_bug_analysis.md` **至少存在一份**；建议两份都提供。摘要给出原 Bug 身份和声明，分析文档提供原 BG 块、TC 关联及可追溯原文。两份都缺失时，输入骨架无法建立；没有既有 Bug 时，可提供一份无 Bug 条目的报告，工作流仍会分析新失败。 |
| `.pytest.ini` | 可选；存在时会随测试复制，并用于 pytest 收集和重跑。保留原测试实际需要的插件与参数，但检查其中的 `pythonpath`、外部插件和平台依赖在新机器上是否可用。报告目录由本次运行区重定向，不必让输入目录可写。 |
| `launch.yaml` 与 `filelist.f` | 均必需。启动清单的 `dut` 对应 `<dut>` 包名，`module` 指定 RTL 顶层，`files.filelist` 为根目录 `filelist.f`；每条 RTL 路径在运行节点可解析。默认工作流与 Bug Review 的启动参数不同时可分别准备清单。 |
| `<dut>/` | 可选的已编译运行包；必须能由本次 Python 导入。运行时只在 run 根目录保存一份供 pytest 共用；缺少包时按 RTL 清单编译。 |
| Spec 与 RTL | 提供与 DUT 版本一致的规格 Markdown 和可核实的 RTL。原报告结论不能代替独立 Spec 与 RTL 证据；引用使用输入相对路径及精确行号。 |
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

每次运行在 `output/workspace_<dut>/runs/run-<id>/` 保存只读 `source/` 原文快照、`results/tests/` 执行副本和根目录的一份 DUT 包；不生成 `results/inputs/`。外部 RTL 也会复制到 `source/rtl_external/`，`source/rtl_sources.json` 记录原路径与快照路径。模块级实体 `report/` 可独立分享，签名收据与运行记录仍留在对应 run。输入目录与已有生成状态不被改写。

### 从 Web Master 启动

在 Master 页选择 Bug Review preset 后按默认工作流操作：导入输入目录的 `launch.yaml`，先编译 DUT（编译清单用 `.f` 或标注 Main RTL），再从 Launch 启动。preset 固定 `--config bug_review --plugin plugins/bug_review --plugin-workflow bug_review:analysis --output results`，插件配置由工作流基线提供，无需单独的 config 文件。Agent 启动后由 input-preparation 按上文标准检查并补齐输入；模块报告由插件工作流在运行目录内发布。
