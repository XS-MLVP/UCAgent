

# 模板文件与生成产物

模板和 Guide_Doc 是阶段任务的输入。它们告诉 Agent 要生成什么、使用什么格式，以及
Checker 会检查哪些条件；它们本身不是测试结果，也不能替代 Checker 或测试证据。

## 工作区中的相关目录

以 `output/` 为工作区、默认输出目录 `unity_test/` 为例：

```text
output/
├── <DUT>/                  # DUT 源码、README 和输入资料
├── Guide_Doc/              # 运行时复制的指导文档
├── unity_test/             # 工作流生成的文档、测试和覆盖率定义
│   └── tests/              # pytest/toffee 测试文件
├── uc_test_report/         # 测试工具生成的报告（如果运行了测试）
└── .ucagent/               # 运行配置快照、历史和状态
```

`--output` 可以改变 `unity_test/` 的目录名。具体文件由当前配置的阶段、模板和 Checker
决定，因此不要把某个示例中的完整文件树当作所有工作流的固定输出。

## Guide_Doc 和模板的区别

### Guide_Doc

`Guide_Doc/` 中的文件是运行时参考资料，通常来自
`ucagent/lang/<lang>/doc/Guide_Doc/` 或自定义的 `--guid-doc-path`。阶段可以通过
`reference_files` 声明需要阅读的文件；在 `Complete` 前，必须满足该阶段的引用文件和
输出文件门禁。自定义目录会替换内置 Guide_Doc 的来源（多次指定目录时最后一个生效）；文件参数则按文件名追加到复制集合。

Guide_Doc 应写清以下内容：

- 当前阶段要完成的目标、可使用的输入和允许写入的路径；
- 产物的完整格式、字段顺序、标签和证据要求；
- 一个从标题到结尾的完整参考示例；
- 失败时如何检查输入、修复产物并重新调用 `Check`。

运行时路径始终以工作区为根。例如在提示词中引用文件时写
`Guide_Doc/dut_test_case.md section 3`，不要写本仓库的绝对路径。

### 生成模板

模板是复制或渲染到工作区的初始文件。启动时可以用 `--template-dir` 指定模板目录，
用 `--template-overwrite` 覆盖已存在的目标。模板覆盖配置通过
`--template-cfg-override <yaml>` 传入；它只负责模板变量，不会改变阶段 Checker 的
判定规则。

## 常见产物

默认 UnityTest 工作流通常会在 `unity_test/` 生成以下几类内容，是否出现取决于当前
阶段是否启用：

- `*_basic_info.md`、`*_verification_needs_and_plan.md`：DUT 信息、验证需求和计划；
- `*_functions_and_checks.md`：FG/FC/CK 功能模型，供测试和覆盖率定义引用；
- `tests/*_api.py`、`tests/test_*.py`：测试接口、夹具和测试用例；
- `*_function_coverage_def.py`：功能覆盖组、覆盖点和采样定义；
- `*_line_coverage_analysis.md`：行覆盖结果和补测分析（需要配置对应阶段）；
- `*_bug_analysis.md`、`*_test_summary.md`：Bug 证据和测试总结（需要配置对应阶段）。

`uc_test_report/` 通常由 `RunUnityChipTest` 或项目自己的 Make 目标生成，可能包含
HTML 和 JSON 报告。只有实际运行测试后，才能把报告中的通过率和覆盖率当作结果。

## 如何添加一个自定义 Guide_Doc

在工作流目录中创建文件，例如：

```text
MyWorkflow/
├── Guide_Doc/
│   └── project_analysis_guide.md
└── config.yaml
```

在阶段中声明它：

```yaml
stage:
  - name: analyze_project
    desc: "分析项目"
    reference_files:
      - "Guide_Doc/project_analysis_guide.md"
    output_files:
      - "{OUT}/{DUT}_analysis.md"
    task:
      - "读取 Guide_Doc/project_analysis_guide.md"
      - "将分析结果写入 {OUT}/{DUT}_analysis.md"
```

阶段配置中的路径相对于工作区；`{DUT}`、`{OUT}` 等模板变量在配置解析后替换。引用文件
不存在、没有被读取或输出文件没有生成时，阶段检查会失败，并返回需要修复的路径。

## 编写模板的建议

1. 先定义机器需要检查的结构，再写解释性文字。字段名、标题级别和标签必须唯一且稳定。
2. 在完整示例中展示真实的结束状态；不要只给片段，让 Agent 自行猜测缺少的章节。
3. 对可选分支明确写出何时使用，避免把“没有 Bug”“没有覆盖数据”等正常结果误写成失败。
4. 模板只描述当前契约。格式变更时同步修改 Guide_Doc、任务提示、Checker、技能资产和测试。
5. 不要在模板中放 API Key、访问令牌或其他秘密；运行时快照也只保存非敏感配置。

## MiniWorkflow 示例

可运行的最小示例位于仓库的 [`examples/MiniWorkflow`](https://github.com/XS-MLVP/UCAgent/tree/main/examples/MiniWorkflow)。其中：

- `Guide_Doc/` 展示阶段参考文档；
- `mini.yaml` 定义两个阶段、工具和 Checker；
- `my_tools.py` 和 `my_checkers.py` 是扩展实现；
- `Makefile` 准备 `output/` 后启动 UCAgent。

先阅读 [定制开发入门](01_quick_start.md)，再运行 [Mini 示例](08_mini_example.md)。
如果需要修改工具或 Checker，分别参考[定制工具](05_customize.md)和[检查器](07_checkers.md)。
