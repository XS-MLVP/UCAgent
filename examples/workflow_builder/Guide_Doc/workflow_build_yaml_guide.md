# workflow_build.yaml 生成规范

## 目的

`workflow_build.yaml` 是第 2 阶段 `WorkflowBuilder` 的输入施工图。它不直接运行工作流，而是声明要创建哪些目录、文件、运行时输入契约、基础配置和验收规则。

第 1 阶段生成该文件时，必须保证所有 `files.public` 和 `files.internal` 中的 `template` 都是 `WorkflowBuilder` 支持的模板名。禁止编造模板名；未知模板会导致 Builder 生成空文件，使后续阶段延迟失败。

`workflow_spec` 不是简略阶段目录，而是后续配置和 Checker 的权威施工契约。旧格式若只写
`stages[].name/description` 会被 Builder 直接拒绝；不得依赖后续阶段猜测 Checker、
引用文件或注册参数。

## 必需根级字段

必须保留这些根级字段：

```yaml
workflow:
root:
runtime_contract:
directories:
files:
makefile:
config:
workflow_spec:
acceptance:
```

`root.path` 必须精确使用配置给出的 `{TEST_WORKFLOW_ROOT}`（当前最小版本为
`root: {path: workflow, overwrite: false}`），不要添加 `./`，不要写成
`output/...`，也绝对不能根据 `workflow.name` 推导目录名。`workflow.name` 是产品名称，
`root.path` 是当前 Builder 的固定交付目录，两者没有相等关系。外层工作流调用
`WorkflowBuilder` 时会传 `base_dir="{OUT}"`，最终工程目录自然落在
`{OUT}/{TEST_WORKFLOW_ROOT}`。`WorkflowBuildConfigChecker.expected_root` 会在实际构建前
比较规范化路径；不一致时必须修改构建配置，禁止先生成到错误目录再重新构建。

`acceptance` 是必需根级字段，不能省略。它会被 Builder 转换为 `.workflow/acceptance_rules.yaml`，供生成工作流的 `make check` 做目录和文件验收。最小格式如下：

```yaml
acceptance:
  required_public_files:
    - setup.py
    - config/environment.schema.yaml
    - requirements.txt
    - docs/README.md
    - docs/01快速启动.md
    - docs/02输入输出.md
    - docs/03步骤及检查.md
    - docs/04开发者文档-tools.md
    - docs/05开发者文档-checkers.md
    - config.yaml
    - config/inc.yaml
    - input/example/README.md
  required_public_dirs:
    - input
    - input/example
    - output
    - docs
    - Guide_Doc
```

如果 `runtime_contract.required_input` 声明了必需输入文件，必须把对应的 `input/example/<path>` 加入 `acceptance.required_public_files`；如果声明了必需输入目录，必须把对应的 `input/example/<path>` 加入 `acceptance.required_public_dirs`。

## 运行时输入契约

`runtime_contract.required_input` 是生成工作流 `input/<TARGET>/` 的唯一事实源。
Makefile 的 `prepare_input`、README 输入契约和 acceptance_rules 必须从同一列表推导；
禁止 Makefile 额外强制检查未出现在 `required_input` 中的路径，也禁止把 required_input
中的条目遗漏到 bundled example 或 acceptance 的必需文件/目录中。若文档把
`metadata/` 或校验清单描述为必需，它们必须以正确的 `type` 写入 runtime_contract，
而不是只在 README 中声明。

```yaml
runtime_contract:
  target_variable: TARGET
  input_root: input
  output_root: output
  example_target: example
  required_input:
    - path: resource.json
      type: file
      example_content: |
        {"resources": []}
    - path: suggestion.md
      type: file
      example_content: |
        # Suggestions
```

规则：

- 只声明用户必须提供的原始输入。
- 不要加入工作流应当自己生成的章节结构、样式配置、分析结果、资源选择、页数或版式。
- 文件用 `type: file`，目录用 `type: directory`。
- 必须让 `input/example/` 可直接运行；如果需求提供 `test_input/`，应在第 2 阶段复制它来替换占位示例。

## 支持的模板名

## workflow_spec 完整规划

`workflow_spec.checkers` 必须一次列全 `requirements_manifest.required_checkers`，使用
中心化定义避免同一 Checker 在多个阶段重复源码。每项至少包含：

```yaml
workflow_spec:
  checkers:
    - name: ResultChecker
      description: "详细说明检查对象、字段语义、通过证据和失败证据。"
      entry:
        file: checkers/result_checker.py
        class_name: ResultChecker
        method: do_check
      source: |
        from pathlib import Path
        from ucagent.checkers.base import Checker

        class ResultChecker(Checker):
            """Validate a generated result."""

            def __init__(self, path: str, **kwargs):
                super().__init__()
                self.path = path

            def do_check(self, **kwargs):
                """Pass only when the expected result file is present and non-empty."""
                target = Path(self.path)
                if not target.is_file() or target.stat().st_size == 0:
                    return False, {"error": "result missing or empty", "path": self.path}
                return True, {"path": self.path, "size": target.stat().st_size}
      fixtures:
        - path: .workflow/checker_tests/cases/ResultChecker/valid.txt
          content: |
            valid result
      tests:
        - name: valid_result
          args:
            path: .workflow/checker_tests/cases/ResultChecker/valid.txt
          expected_pass: true
        - name: missing_result
          args:
            path: .workflow/checker_tests/cases/ResultChecker/missing.txt
          expected_pass: false
```

`source` 是受信任的完整 Python 源码，不限于少数声明式规则。入口类必须继承
`ucagent.checkers.base.Checker`，`entry.method` 固定为 `do_check`，而且
`do_check` 函数体第一条语句必须是非空 docstring；类 docstring 或 description
不能替代方法 docstring。每个 Checker 必须显式声明 fixture，路径只能位于
`.workflow/checker_tests/cases/<CheckerName>/`，tests 至少有一个
`expected_pass: true` 和一个 `expected_pass: false`。失败用例引用的缺失文件无需创建。

`workflow_spec.stages` 必须一次列全业务阶段，并把引用、输出和 Checker 绑定前置：

```yaml
  stages:
    - name: analyze_input
      label: "输入分析"
      description: "说明本阶段的派生职责、输出和失败边界。"
      reference_files:
        - .workflow/workflow_spec.yaml
        - input/{DUT}/request.md
      output_files:
        - "{OUT}/{DUT}/analysis.json"
      checker:
        - name: ResultChecker
          args:
            path: "{OUT}/{DUT}/analysis.json"
```

每个阶段必须显式给出 `reference_files`、`output_files` 和非空 `checker`；
确实没有引用或输出时对应列表写 `[]`，不得省略字段。Checker 名称必须来自中心定义，所有中心 Checker 至少被
一个阶段绑定。`name` 是供配置、增量执行和工具引用使用的稳定标识；当需求清单中的
`required_stages` 使用与 `name` 不同的业务显示名称时，必须用 `label` 原样保存该名称。
阶段覆盖检查同时匹配 `name` 与 `label`，因此无需破坏稳定标识来迁就显示文本。所有路径必须是
子工作流根目录相对路径或合法 UCAgent 运行时路径，禁止
绝对路径、`..`、`.//workflow/`、`./workflow/` 和 `workflow/` 父工作流前缀。
每个 Checker 的 `args` 中以 `path`、`file`、`dir` 或 `root` 命名的路径参数，只能引用
当前阶段或更早阶段已经声明的输出，或者引用静态输入。禁止为了满足“checker 非空”而绑定一个检查未来
产物的 Checker；例如 `smoke_reset_gate` 不能检查到后续 `failure_triage` 才生成的
`reports/simulation.json`。若当前阶段需要仿真检查，就必须把本阶段实际生成的仿真证据列入
`output_files`，并让 Checker 检查该证据。
Builder 会在初次构建时直接生成 `.workflow/checker_specs/*.yaml`、`checkers/*.py`
和全部 fixture；后续初次构建阶段立即运行 `make check_checker_specs`、`make check_checkers`
及 `make test_checkers`，不再设置后置的 Checker 设计与生成阶段。

### Checker fixture 必须与参数类型一致

Stage 1 的 `WorkflowBuildConfigChecker` 会在临时目录物化全部中心 Checker，并实际运行
`check_checker_specs`、`check_checkers` 和 `test_checkers`。正向测试不能只让 YAML
结构看起来完整；fixture 必须满足 Checker 源码真正读取的文件类型和目录结构。

当 Checker 参数要求目录时，测试参数应指向目录，`fixtures` 则列出构成该目录的实际文件。
例如输入契约 Checker 要求目录内包含 `requirements.md` 和非空 `rtl/`，最小写法是：

```yaml
fixtures:
  - path: .workflow/checker_tests/cases/InputContractChecker/valid_input/requirements.md
    content: "# Requirements"
  - path: .workflow/checker_tests/cases/InputContractChecker/valid_input/rtl/dut.sv
    content: "module dut; endmodule"
tests:
  - name: valid_input
    args:
      path: .workflow/checker_tests/cases/InputContractChecker/valid_input
    expected_pass: true
  - name: missing_input
    args:
      path: .workflow/checker_tests/cases/InputContractChecker/missing
    expected_pass: false
```

禁止用 `valid_input.txt` 代替目录，也禁止在 Stage 2 只修生成后的
`.workflow/checker_specs` 或 fixture；权威修复位置始终是 `{BUILD_CONFIG}`。

### 根目录和运行入口

| 目标文件 | 推荐 template |
|---|---|
| `README.md` | `readme_basic` |
| `setup.py` | `workflow_environment_setup` |
| `requirements.txt` | `requirements_txt` |
| `config/environment.schema.yaml` | `environment_schema` |
| `Makefile` | `makefile_basic` |
| `ucagent_setup.sh` | `ucagent_setup` |
| `config.yaml` | `config_basic` |
| `config/inc.yaml` | `config_basic` |
| `install.py` | `workflow_installer` |
| `.install/README.md` | `workflow_install_readme` |
| `.install/manifest.json` | `workflow_install_manifest` |

兼容模板名 `config_inc_basic`、`config_empty_basic` 和 `install_basic` 可以被 Builder 识别，但新生成的 `workflow_build.yaml` 应优先使用上表的规范模板名。

`setup.py` 与 `config/environment.schema.yaml` 是固定的可移植环境配置入口。schema
可以增加当前业务需要的系统工具，但不得保存 Token、密码或带认证信息的代理地址。
`.workflow/local/` 必须声明为内部目录，其本机配置不得进入迁移包。

### 输入输出与文档

| 目标文件 | 推荐 template |
|---|---|
| `input/README.md` | `input_readme` |
| `input/example/README.md` | `input_example_readme` |
| `output/README.md` | `output_readme` |
| `docs/README.md` | `docs_readme` |
| `docs/01快速启动.md` | `docs_quickstart` |
| `docs/02输入输出.md` | `docs_input_output` |
| `docs/03步骤及检查.md` | `docs_stages_checks` |
| `docs/04开发者文档-tools.md` | `docs_developer_tools` |
| `docs/05开发者文档-checkers.md` | `docs_developer_checkers` |
| `Guide_Doc/overview.md` | `guidedoc_overview` |
| `Guide_Doc/operation.md` | `guidedoc_operation` |
| `Guide_Doc/environment_setup.md` | `guidedoc_environment_setup` |
| `templates/resource_template.json` | `resource_template` |
| `templates/suggestion_template.md` | `suggestion_template` |

文档目录统一使用 `Guide_Doc/`。禁止生成或引用旧目录 `GuideDocs/`。
参考资料目录统一使用 `docs/`。禁止为了输入示例创建根目录 `examples/`；可运行示例只能放在 `input/example/`。

`Guide_Doc/tool_generation.md` 和 `Guide_Doc/checker_generation.md` 属于 WFB 自身的生成工具链文档，不是子工作流的默认文档。
生成子工作流时，默认只写运行、输入输出、业务阶段和故障处理相关文档；只有需求明确要求最终使用者扩展工具或 checker 时，才允许创建对应的业务说明文档。

### 输入示例清单

WFB 第 1 阶段必须在 `wfgen/input_example_manifest.yaml` 写出 bundled example 的来源与复制规则。推荐格式：

```yaml
source_dir: input/test_input
target_dir: input/example
copy_mode: copy_tree
required_input:
  - path: resource.json
    type: file
  - path: suggestion.md
    type: file
resource_paths:
  - declared_path: input/example/text/example.md
    source_path: textsource/example.md
  - declared_path: input/example/images/example.png
    source_path: pngsource/example.png
notes:
  - Copy every file and subdirectory under source_dir into target_dir.
```

当只读的 `input/test_input/` 存在时，`copy_mode` 必须是 `copy_tree`，且后续初次构建阶段必须完整复制其内部内容到子工作流 `input/example/`。
`resource_paths` 必须列出输入文件中声明的全部资源。mapping 的 `declared_path` 表示子工作流运行时路径，
`source_path` 必须是相对于 `source_dir` 的内部路径；例如源文件实际为
`input/test_input/rtl/counter.v` 时只能写 `source_path: rtl/counter.v`，不得重复包含
`input/test_input/` 前缀。每个 `source_path` 都必须在 `source_dir` 下真实存在。
只有没有 `input/test_input/` 时，才允许使用 `copy_mode: self_contained` 创建自包含示例。

### 内部规格、检查器和 MCP 测试

| 目标文件 | 推荐 template |
|---|---|
| `.workflow/workflow_spec.yaml` | `workflow_spec_basic` |
| `.workflow/acceptance_rules.yaml` | `acceptance_rules_basic` |
| `.workflow/build_report.md` | `empty` |
| `.workflow/checkers/tool_spec_checker.py` | `tool_spec_checker` |
| `.workflow/checkers/tool_static_checker.py` | `tool_static_checker` |
| `.workflow/checkers/tool_direct_runner.py` | `tool_direct_runner` |
| `.workflow/checkers/checker_spec_checker.py` | `checker_spec_checker` |
| `.workflow/checkers/checker_static_checker.py` | `checker_static_checker` |
| `.workflow/checkers/checker_direct_runner.py` | `checker_direct_runner` |
| `.workflow/tool_tests/run_mcp_tests.py` | `mcp_tool_test_runner` |
| `tools/mcp_adapters.py` | `mcp_tool_adapters` |

## 文件声明规则

1. `files.public` 必须声明最终用户会看到或运行的文件。
2. `files.internal` 必须声明 `.workflow/` 下的内部文件。
3. `required_configs` 中的每个 `path` 必须原样出现在 `files.public`。
4. `required_guidedocs` 中的每个 `path` 必须原样出现在 `files.public`，并且路径使用 `Guide_Doc/`。
5. `required_user_docs` 中的每个 `path` 必须原样出现在 `files.public`，并且路径使用 `docs/`。
6. `required_templates` 只保存最终用户可复用模板的文件路径（例如
   `templates/request.yaml`），每个路径必须能在文件声明中找到；它不保存
   `readme_basic`、`config_basic` 等 `files.*[].template` 渲染标识符。需求没有要求
   用户模板时使用空列表。
7. `required_deliverables` 和 `requirements.txt` 也必须能在文件声明中找到。
8. 不要为 `read_text_file_tool`、`write_text_file_tool` 或 `run_command_tool` 添加文件，除非需求明确把它们列为业务工具。

## 禁止事项

- 禁止使用未知模板名。
- 禁止让模板生成空的 `config/*.yaml`、GuideDoc 或模板文件。
- 禁止把 `root.path` 写到 `{OUT}` 之外。
- 禁止生成 `GuideDocs/`。
- 禁止生成根目录 `examples/`；测试夹具放在 `.workflow/tool_tests/cases/` 或 `.workflow/checker_tests/cases/`，用户可运行示例放在 `input/example/`。
- 禁止把运行输入绑定到 `data/__init__.py`、DUT、RTL 或其他固定领域结构。
- 禁止在第 1 阶段只覆盖 smoke 子集；`workflow_build.yaml` 必须覆盖完整 manifest。
- 禁止提交缺少中心 Checker 源码、显式正反 fixture、阶段 reference_files 或 Checker
  绑定的旧式 `workflow_spec`。

## 自检清单

生成 `workflow_build.yaml` 后，完成阶段前逐项检查：

- 所有根级字段都存在。
- `runtime_contract.required_input` 只包含真实必需输入。
- `files.public` 包含 `requirements.txt`、六份固定 `docs/*.md`、`config.yaml`、`config/inc.yaml`、`install.py` 和全部 `Guide_Doc/*.md`；`eval.yaml` 仅按需加入，禁止 `config/default.yaml` 与 `config/empty.yaml`。
- `files.internal` 包含工具、checker 和 MCP 直接测试基础设施。
- `directories.internal` 包含 `.workflow/tool_tests/logs`；不得依赖首个工具测试执行后才临时创建。
- `workflow_spec.checkers` 与 manifest 的 Checker 名称完全一致，且每项源码接口、
  fixture 和正反测试完整。
- `workflow_spec.stages` 中每个阶段都明确声明 reference_files、output_files 和
  Checker 绑定，所有 Checker 至少绑定一次；Checker 路径参数不引用未来阶段输出。
- 所有 `template` 都在本规范列出的支持集合内。
- `acceptance.required_public_files` 包含 `input/example/` 下每个必需输入文件。
- `acceptance.required_public_dirs` 包含 `input`、`input/example`、`output`、`docs` 和 `Guide_Doc`。
