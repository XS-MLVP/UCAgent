# Workflow Builder

## 作用

`workflow_builder` 根据 `workflow_build.yaml` 创建一个可继续扩展的工作流工程骨架。它负责目录、Makefile、初始 config、基础 Guide_Doc、内部质量检查器和验收元信息，并根据 `workflow_spec.checkers` 在初次构建时直接生成全部业务 Checker、规格与正反 fixture；业务工具和其他最终业务逻辑仍由后续阶段完成。

## 输入与输出

输入 `workflow_build.yaml` 描述：

- 工作流名称、版本和目标。
- 输出根目录与覆盖策略。
- 公开目录、内部 `.workflow/` 目录和文件模板。
- Makefile 目标。
- 初始运行配置、输入输出规格和验收规则。
- `runtime_contract`：运行目标变量、必需输入和运行模式。`required_input` 逐项声明
  `path`、`type=file|directory` 和可选 `example_content`。Builder 会生成
  `docs/01快速启动.md`、完整用户文档、`requirements.txt`、结构匹配的
  `input/example/` 和 Makefile 输入检查，不再假设用户输入是 DUT/Python 包。

输出包括 `Makefile`、`config.yaml`、`Guide_Doc/`、`tools/`、`checkers/`、`.workflow/`、`install.py` 和 `.install/`。

## 原理

Builder 首先严格验证完整 `workflow_spec`：中心 Checker 定义必须包含内联源码、入口、fixture 和正反测试，每个阶段必须预先声明引用文件、输出文件及 Checker 绑定。随后按模板生成文件并直接物化业务 Checker。`.workflow/checkers/` 中的检查器验证配置语法、目录布局、GuideDoc、工具和 Checker。Builder 会强制生成迁移安装器。生成后的工程必须能够执行 `make check_checker_specs`、`make check_checkers`、`make test_checkers` 和 `make check`。

## CLI

```bash
python -m examples.workflow_builder.tools.workflow_builder.cli workflow_build.yaml --base-dir output
```

`root.path` 相对于 `--base-dir` 解析，因此最终产物会稳定位于指定输出目录。

## UCAgent 工具

```yaml
ex_tools:
  - examples.workflow_builder.tools.workflow_builder.uc_tools.WorkflowBuilder
  - examples.workflow_builder.tools.workflow_builder.uc_tools.WorkflowCommandRunner
  - examples.workflow_builder.tools.workflow_builder.uc_tools.WorkflowPlanAppender
```

存在 `copy_mode=copy_tree` 的示例清单时调用
`WorkflowBuilder(build_config_path="wfgen/workflow_build.yaml", base_dir="output", input_example_manifest_path="wfgen/input_example_manifest.yaml")`。

构建阶段需要执行子工作流确定性检查时，使用
`WorkflowCommandRunner(workflow_root="workflow", command="make check_docs")`。
该工具只接受白名单 Make 目标、受限 pytest 路径以及工作流根级 `tmp/` 中的单个
Python/Shell 脚本，不使用 shell 拼接。
Builder 会用二进制复制覆盖骨架占位文件，保持源文件字节不变；未提供该参数时只生成示例骨架。

## 验证与使用

```bash
cd <generated-workflow>
make check
make smoke
make package
```

`make package` 会准备 `.install/packages/full` 和 `.install/packages/partial`。全量包包含工具与 checker；部分包排除 `tools/`、`checkers/` 以及 `.workflow` 下对应的规格、测试与内部 checker。迁移命令见生成工程中的 `.install/README.md`。

Builder 是后续生成器的基础。工具、最终 config 和 Guide_Doc 在骨架创建后分别生成和验证；Checker 不再延迟设计或二次生成，后续配置仅从 `.workflow/workflow_spec.yaml` 注入其注册。

在完整工作流生成流程中，Builder 输入必须覆盖 `requirements_manifest.yaml` 声明的全部阶段、Guide_Doc、模板和配置。初步骨架通过 smoke 测试后，还需要补齐全部组件并通过最终需求覆盖检查，不能把可运行骨架当作最终交付。

最终运行配置必须使用 UCAgent 的单层占位符 `{DUT}`、`{OUT}`，不得使用
`{{DUT}}`。根级 `config.yaml` 是主流程入口，`config/inc.yaml` 是增量入口；只有业务
确实需要独立评估时才增加 `eval.yaml`，禁止复制出 `config/default.yaml` 或
`config/empty.yaml`。
