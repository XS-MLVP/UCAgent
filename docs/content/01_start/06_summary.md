
**本文档是对“快速开始”各模式跑通后的生成内容的“结果分析”，以及对整体流程的“总结”。
如果需要验证自己的模块，可以参照流程总结中的[需要准备的文件](#需要准备的文件)**

---

## 结果分析

- 当前的目录结构如下：

  ```bash
  {工作区}
  ├── Adder
  │   ├── Adder.v
  │   └── README.md
  └── output
      ├── Adder # picker导出的Adder包
      │   ├── ...
      │   └── xspcomm
      ├── Guide_Doc # 各种模板文件
      ├── uc_test_report # 跑完的测试报告，包含可以直接网页运行的index.html
      └── unity_test # 各种生成的文档和测试用例文件
          └── tests # 测试用例及其依赖
  ```

  最终的结果都在`output`文件夹中，其中的内容如下：

- Guide_Doc：这些文件是“规范/示例/模板型”的参考文档，启动时会从`ucagent/lang/zh/doc/Guide_Doc`复制到工作区的 `Guide_Doc/`（当前以 output 作为 workspace 时即 `output/Guide_Doc/`）。它们不会被直接执行，供人和 AI 作为编写 unity_test 文档与测试的范式与规范，并被语义检索工具读取，在 UCAgent 初始化时复制过来。
  对文件的详细解读可参照[模板文件 Guide_Doc](../03_develop/04_template.md#guide_doc)

- uc_test_report：由 toffee-test 生成的 index.html 报告，可直接使用浏览器打开。
  - 这个报告包含了 Line Coverage 行覆盖率，Functional Coverage 功能覆盖率，测试用例的通过情况，功能点标记具体情况等内容。

- unity_test/tests：验证代码文件夹
  对文件的详细解读可参照[生成的代码](../03_develop/04_template.md#unity_testtests)

- unity_test/\*.md：验证相关文档
  对文件的详细解读可参照[生成的文档](../03_develop/04_template.md#unity_test.md)

## 流程总结

### 需要准备的文件

- 待验证的源码，`verilog`或`chisel`均可，将其放于`{工作区}/{模块名}`文件夹下
- 源码对应的 SPEC，`md`格式，将其放于`{工作区}/{模块名}`文件夹下

以`Adder`模块举例：

```bash
{工作区}
└── Adder
    ├── Adder.v
    └── README.md
```

### 做了什么

- 用 picker 将 RTL 导出为 Python 包（`output/Adder/`），准备最小 README 与文件清单
- 启动 `ucagent`（含 `--mcp-server`/`--mcp-server-no-file-tools`），在 TUI/MCP 下协作
- 在 Guide_Doc 规范约束下，生成/补全：
  - 功能清单与检测点：`unity_test/Adder_functions_and_checks.md`（FG/FC/CK）
  - 夹具/环境与 API：`tests/Adder_api.py`（`create_dut`、`AdderEnv`、`api_Adder_*`）
  - 功能覆盖定义：`tests/Adder_function_coverage_def.py`（绑定 `StepRis` 采样）
  - 行覆盖配置与忽略：`tests/Adder.ignore`，分析文档 `unity_test/Adder_line_coverage_analysis.md`
  - 用例实现：`tests/test_*.py`（标注 `mark_function` 与 FG/FC/CK）
  - 缺陷分析与总结：`unity_test/Adder_bug_analysis.md`、`unity_test/Adder_test_summary.md`
- 通过工具编排推进：`RunTestCases`/`Check`/`StdCheck`/`KillCheck`/`Complete`/`GoToStage`
- 权限控制仅允许写 `unity_test/` 与 `tests`（`add_un_write_path`/`del_un_write_path`）

### 实现的效果

- 自动/半自动地产出合规的文档与可回归的测试集，支持全量与定向回归
- 功能覆盖与行覆盖数据齐备，未命中点可定位与补测
- 缺陷根因、修复建议与验证方法有据可依，形成结构化报告（`uc_test_report/index.html`）
- 支持 MCP 集成与 TUI 协作，过程可暂停/检查/回补，易于迭代与复用

典型操作轨迹（卡住时）：

- `Check` → `StdCheck(lines=-1)` → `KillCheck` → 修复 → `Check` → `Complete`
