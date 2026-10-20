
# 结果分析与流程总结

验证完成后，请同时查看阶段状态、测试报告和生成文件。某个阶段显示完成，只表示该阶段的 Checker 通过；DUT 是否存在缺陷仍要结合测试断言、失败日志和 Bug 证据判断。

## 工作区结构

以 `output/` 作为工作区、默认输出目录 `unity_test/` 为例：

```text
output/
├── Adder/                 # picker 导出的 DUT Python 包和输入文档
├── Guide_Doc/             # 运行时复制的指导文档
├── unity_test/            # 工作流生成的文档、测试和阶段产物
│   └── tests/
├── uc_test_report/        # toffee-test 报告（若已运行测试）
└── .ucagent/              # 配置快照、历史和运行状态
```

Makefile 示例会使用 `output/workspace_<DUT>/` 作为工作区，因此把上面的 `output/` 替换成该目录即可。

## 主要产物

- `Guide_Doc/`：运行时参考文档和格式示例。它指导 Agent 编写产物，不是测试结果，也不应作为验证证据。
- `unity_test/tests/`：DUT fixture、API、覆盖率模型和 pytest 用例。
- `unity_test/*.md`：验证计划、基础信息、功能点、行覆盖率、Bug 分析和总结等文档，具体文件由工作流决定。
- `uc_test_report/`：toffee-test 生成的 HTML/JSON 报告（若当前流程调用了 UnityChip 测试工具）。
- `.ucagent/runtime_config.json`：已解析的非敏感运行配置，供 Skill 和其他运行时脚本读取；不要把 API Key 写入其中。

详细的模板和产物契约见[模板文件与生成产物](../03_develop/04_template.md)。

## 推荐的复盘顺序

1. 查看 `status`，确认是否还有未完成或跳过的阶段。
2. 打开 `uc_test_report/` 中的测试报告，区分测试基础设施失败和可复现的 DUT 失败。
3. 对每个失败用例回到测试代码、RTL 和规格，检查输入、断言、日志以及必要的波形证据。
4. 阅读 `unity_test/{DUT}_bug_analysis.md` 和 `unity_test/{DUT}_test_summary.md`（如果当前工作流生成了这些文件）。
5. 修复后重新运行相关测试并调用 `Check`；需要回补时使用 `GoToStage` 回到已到达的阶段。

## 准备自己的任务

至少准备：

```text
<workspace>/
└── <DUT>/
    ├── <top>.v / .sv / .scala
    └── README.md
```

`<DUT>` 目录还可以包含 filelist、辅助 RTL、参考模型和其他需求文档。先用 picker 导出 `<workspace>/<DUT>` Python 包，再运行 `ucagent <workspace> <DUT>`；Master Launch 页面可以代为上传和编译。

工作流会根据这些输入生成 FG/FC/CK 功能模型、fixture、API、测试和报告。输出文件名以当前配置的 `stage` 和 Checker 为准，不要预先假设一定会生成某个 Bug、波形或覆盖率文件。
