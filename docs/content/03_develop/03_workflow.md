
# 工作流配置

工作流由一组按顺序执行的阶段组成。每个阶段描述任务、参考文件、预期产物和 Checker；Agent 可调用 `Check` 查看反馈，再用 `Complete` 执行最终验收并推进。阶段失败时应先按 Checker 的诊断修复，再重试。

## 1. 默认工作流

中文默认配置位于 `ucagent/lang/zh/config/default.yaml`，当前有 20 个顶层阶段；带缩进的条目是子阶段。运行时 Stage Manager 会把父阶段和子阶段展平，因此 `--skip`、`hmcheck_set` 和 `GoToStage` 使用的索引必须以当前运行中的 `status` 或 `hmcheck_list` 为准。

| 顶层索引 | 阶段 | 默认状态 |
| ---: | --- | --- |
| 0 | `requirement_analysis_and_planning` | 执行 |
| 1 | `dut_function_understanding` | 执行 |
| 2 | `functional_specification_analysis`：FG、FC、CK、逐行映射子阶段 | 执行 |
| 3 | `functional_specification_refine` | 执行 |
| 4 | `static_bug_analysis` | 执行 |
| 5 | `dut_wrapper_implementation`：DUT 创建、pytest fixture | 执行 |
| 6 | `coverage_model_implementation`：覆盖组、覆盖点和批量实现 | 执行 |
| 7 | `test_environment_implementation`：env、Bundle、Mock 和 fixture | 部分人工检查默认跳过 |
| 8 | `basic_api_implementation` | 执行 |
| 9 | `reference_model_implementation` | `NEED_REF_MODEL=true` 时执行 |
| 10 | `reference_model_fixture_imp` | `NEED_REF_MODEL=true` 时执行 |
| 11 | `basic_api_functional_test` | 执行 |
| 12 | `create_test_case_templates` | 执行 |
| 13 | `comprehensive_verification_and_bug_analysis`：批量实现测试用例 | 执行 |
| 14 | `refine_test_cases_based_on_functional_points` | 执行 |
| 15 | `static_bug_validation` | 执行 |
| 16 | `line_coverage_analysis_and_improvement` | 默认跳过 |
| 17 | `generate_random_test_cases` | 执行 |
| 18 | `verification_review_and_summary` | 执行 |
| 19 | `record_and_report_bugs` | 执行 |

默认配置中 `human_check_env_specification`、`human_check_env_implementation` 和 `line_coverage_analysis_and_improvement` 使用 `skip: true`；具体是否执行还会受环境变量和项目覆盖配置影响。Formal、Vibe、Increment 是独立配置，阶段数量和名称不同，不能套用上表。

## 2. 阶段字段

最小阶段结构如下：

```yaml
stage:
  - name: analyze_project
    desc: "分析项目并生成报告"
    task:
      - "读取 {DUT}/README.md"
      - "将结果写入 {OUT}/{DUT}_analysis.md"
    reference_files:
      - "Guide_Doc/project_analysis_guide.md"
    output_files:
      - "{OUT}/{DUT}_analysis.md"
    checker:
      - name: markdown_check
        clss: "UnityChipCheckerMarkdownFileFormat"
        args:
          markdown_file_list: "{OUT}/{DUT}_analysis.md"
          no_line_break: true
    skill_list: []
    force_use_skill: false
    skip: false
```

- `name`：稳定的阶段标识。LLM 建议过滤、历史记录和日志都使用它。
- `desc`：阶段标题；可以包含由 Checker 提供的模板变量。
- `task`：给 Agent 的任务列表。应写清输入、动作、输出格式和完成标准。
- `reference_files`：阶段需要阅读的工作区相对路径或 glob。运行时找不到必需参考文件应修复配置或输入。
- `output_files`：阶段必须存在的产物路径或 glob，每个模式都要匹配到路径；内容正确性仍由 Checker 验证。
- `checker`：按顺序执行的验证门。所有门通过后，`Complete` 才能推进。
- `stage`：子阶段列表。父阶段只有在子阶段完成后才进入父阶段验收。
- `skip`：是否默认跳过；只适合明确不适用的阶段。
- `need_human_check`：通过 Checker 后等待人工审核。
- `skill_list`：当前阶段的专用技能。技能启用且列表非空时，默认需要真实的 list/read/use 证据；`force_use_skill: false` 才是可选技能。

## 3. 配置加载和模板变量

配置按以下顺序加载，后面的层覆盖前面的层：

1. `ucagent/setting.yaml`
2. `~/.ucagent/setting.yaml`
3. `ucagent/lang/<lang>/config/default.yaml`
4. 工作区 `./.ucagent/setting.yaml`
5. `--config` 指定的文件（未指定时会查找 `config.yaml`）
6. CLI 参数和 `--override`

选择插件工作流时，其配置基线插在语言默认配置之后、工作区配置之前，详见[插件开发与发布](09_plugins.md)。项目配置的查找范围包括当前启动目录、`~/.ucagent/` 和语言配置目录；相对 `--config` 路径并非默认相对于 workspace。

列表字段（尤其是 `stage`、`checker`、`reference_files`）整体替换，不会按项目名逐项合并。修改默认阶段时，应复制完整列表再编辑。

常用模板变量：

| 变量 | 含义 |
| --- | --- |
| `{DUT}` | DUT 子目录名 |
| `{OUT}` | 工作区下的输出目录，默认 `unity_test` |
| `{WORKSPACE}` | 当前工作区绝对路径 |
| `{GUIDE_DOC}` | 工作区运行时 `Guide_Doc` 路径 |
| `{DOC_GEN_LANG}` | 文档语言，来自模板配置 |

`{OUT}` 在首轮配置渲染时由 `--output`（默认 `unity_test`）决定。更改输出路径请使用该选项，不要仅修改 `template_overwrite.OUT`。

环境变量替换发生在 YAML 加载时，例如 `$(NEED_REF_MODEL: false)`；`{DUT}` 和 `{OUT}` 等模板变量在配置解析后渲染。不要在运行时重新读取原始环境变量来推断已解析配置。

## 4. 跳过、回退和人工审核

临时跳过阶段：

```bash
ucagent <workspace> <DUT> --skip <runtime_stage_index>
ucagent <workspace> <DUT> --unskip <runtime_stage_index>
```

运行中使用：

```text
skip_stage <runtime_stage_index>
unskip_stage <runtime_stage_index>
tool_invoke GoToStage index=<runtime_stage_index>
hmcheck_set <runtime_stage_index> true
```

索引是展平后的运行时索引；修改工作流后不要继续使用旧编号。`GoToStage` 只能回到已经到达的阶段。跳过阶段不会生成它本应产出的文件，后续 Checker 可能因此失败；只有确认阶段不适用时才跳过。

## 5. Checker 配置

Checker 类通过 `clss` 指定，短名从 `ucagent.checkers` 导入，完整路径可指向自定义模块：

```yaml
checker:
  - name: word_count
    clss: "my_workflow.checkers.WordCountChecker"
    args:
      file_path: "{OUT}/{DUT}_analysis.md"
      word_min: 200
      need_human_check: false
```

`args` 传给构造函数并自动注入 `cfg`；`extra_args` 在实例化后通过 `set_extra` 设置新属性，不能覆盖已有属性，也不能替代构造参数或专用 setter。`need_human_check` 是否生效取决于该 Checker 的构造函数是否处理它；也可以直接在阶段上设置 `need_human_check: true`。

自定义 Checker 的完整实现、生命周期和结构化诊断见[自定义 Checker](07_checkers.md)。

## 6. 批量阶段

功能覆盖、测试模板、测试用例和行映射等阶段使用 `UnityChipBatchTask` 管理进度。配置批任务时：

- 在构造 `UnityChipBatchTask` 前设置 `batch_size`；
- 以当前源文档和测试文件为事实来源，checkpoint 只用于恢复；
- 源文件变化后重新同步 source/generated task，删除或标记过期任务；
- 用 `Check` 完成当前批次并暴露下一批，所有批次通过后才用 `Complete`；
- 失败诊断只返回有界的缺失范围和下一步，不要把整个源码或日志塞入提示。

功能行映射阶段另有约束：`file_list` 是唯一权威输入；不把 `Guide_Doc` 当作映射目标；每个非空物理行都要有 FG/FC/CK 或有理由的 `IGNORE`；一个区间最多 100 行。详见 `Guide_Doc/dut_line_func_map.md` 及默认配置中的 `functional_line_mapping_gap_analysis`。

## 7. 自定义工作流

不要直接修改包内的 `default.yaml`。在项目配置中复制需要改动的完整 `stage` 列表，或使用 `--override` 做小范围临时覆盖：

```bash
ucagent <workspace> <DUT> \
  --config config.yaml \
  --override 'runtime_options.need_ref_model=True'
```

新增阶段时同时提供任务、参考文档、输出和 Checker；如果阶段需要技能，确保禁用技能时仍能用普通工具和 Checker 完成同一目标。阶段专属技能、Guide_Doc、模板和脚本共同构成运行时契约，任何一层改动后都应同步测试。

## 8. 运行时快照

配置解析后，UCAgent 在工作区写入 `.ucagent/runtime_config.json`。它只包含已解析的非敏感字段，例如 `DUT`、`OUT`、`runtime_options`、`current_test_report` 和 `ucagent_python_path`。Skill 脚本应读取该快照，不要从脚本位置猜测源码路径或重新解释环境变量；快照中的 `ucagent_python_path` 必须是包含当前 `ucagent/__init__.py` 的绝对路径。

下一步：先运行 [Mini 示例](08_mini_example.md)，再根据需要学习[定制工具](05_customize.md)、[模板文件](04_template.md)和[插件](09_plugins.md)。
