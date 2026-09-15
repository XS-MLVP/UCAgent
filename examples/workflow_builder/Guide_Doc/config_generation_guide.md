# 配置文件生成规范

## 概述

`WorkflowConfigGenerator` 将结构化 `.workflow/config_spec.yaml` 转换为最终 UCAgent 可执行的 `config.yaml`。业务阶段的 `reference_files`、`output_files` 和 Checker 注册以 `.workflow/workflow_spec.yaml` 为唯一事实源，配置 spec 负责详细 task 和运行参数，不能重新设计这些契约。

## Config Spec 格式

`.workflow/config_spec.yaml` 必须包含以下根级字段：

```yaml
workflow:              # 工作流基本信息
  name: my_workflow
  version: "0.1.0"
  description: "工作流描述"
mode: default          # 主配置用 default；增量配置用 inc

mission:               # Agent 任务定义
  name: "任务名称"
  prompt:
    system: "system prompt 内容"
    tips:
      allways: []
      random: []

stages:                # 阶段列表
  - name: stage_name
    desc: "阶段描述"
    task:
      - "任务步骤1"
      - "任务步骤2"
```

生成主配置和 `inc` 时，生成器按阶段名从 `.workflow/workflow_spec.yaml` 注入
`reference_files`、`output_files` 和 `checker`。config spec 可以省略这三个字段；
若显式写出，则必须与权威规划完全一致，否则返回 `CONFIG-GEN-SPEC-018`。

## 关键约束

### 变量占位符

UCAgent 运行时变量必须使用**单层花括号**：

```yaml
# ✅ 正确
INPUT_ROOT: input/{DUT}

# ❌ 错误 — 生成器会拒绝
INPUT_ROOT: input/{{DUT}}
```

### write_dirs 必须为 ["{OUT}/{DUT}"]

所有阶段产出的文件必须收敛到当前运行目标目录下：

```yaml
write_dirs:
  - '{OUT}/{DUT}'
```

生成器会拒绝任何其他值。

### 禁止 MWF 运行时值泄漏

config spec 面向将来运行的 CWF，不能写入当前 WFB/MWF 的运行时值。下面都是错误：

```yaml
task:
  - "读取 input/workflow_build/resource.json"
  - "将一次性中间结果记录到根级 tmp/result.json"
template_overwrite:
  OUTPUT_ROOT: output/{DUT}
```

必须改为 CWF 运行时变量：

```yaml
task:
  - "读取 input/{DUT}/resource.json"
  - "将最终业务结果写入 {OUT}/{DUT}/result.json；一次性中间结果只能写入根级 tmp/"
template_overwrite:
  INPUT_ROOT: input/{DUT}
  OUTPUT_ROOT: '{OUT}/{DUT}'
```

### 子工作流根目录边界

Builder Agent 访问候选工作流时使用 `{TEST_WORKFLOW_ROOT}`，该变量必须直接展开为
`workflow/`。模板替换是单次展开，不能把 `TEST_WORKFLOW_ROOT` 写成
`"{TEST_WORKFLOW}"` 并期待二次替换；这种写法会把花括号原样带入 reference。
外层 `config.yaml`、`inc.yaml` 和 `eval.yaml` 应直接使用规范的 workspace 相对字面值
`workflow`。旧配置把它写成 `{OUT}/workflow`，当运行时 `OUT=./` 时会错误产生
`.//workflow/`。这个错误前缀既不应出现在父级 reference，也绝不能写入生成工作流自己的
config spec。子工作流运行时已经以自身目录作为 workspace，因此内部静态文件必须直接
相对子工作流根目录引用：

```yaml
# 正确
reference_files:
  - .workflow/workflow_spec.yaml
  - Guide_Doc/overview.md

# 错误：把父工作流访问路径复制进了子工作流
reference_files:
  - .//workflow/.workflow/workflow_spec.yaml
  - ./workflow/Guide_Doc/overview.md
```

`.//workflow/`、`./workflow/` 和 `workflow/` 都会在子工作流运行时被再次拼接到
workspace 后面，解析成 `<child-root>/workflow/...`，从而指向不存在的嵌套目录。
必须在 `.workflow/config_specs/*.yaml` 中消除该前缀，再调用
`WorkflowConfigGenerator` 重新生成；不得只修最终 `config.yaml`。

可观察到大量 `No files found ... {TEST_WORKFLOW}/...` 时，先检查
`template_overwrite.TEST_WORKFLOW_ROOT` 是否仍含 `{`；看到 `.//workflow/...` 时，再检查
Makefile 是否把 `OUT=./` 规范化为 `.`。修复后应重启父工作流并通过 `CurrentTips`
确认 reference 精确显示为 `workflow/...`，不能仅凭两个路径在文件系统上等价就认为问题消失，
因为引用追踪会按配置中的路径字符串记录读取证据。

### 运行模式与文件

| 模式 | 说明 | 约束 |
|------|------|------|
| `default` | 根级 `config.yaml` 主工作流 | 包含所有业务阶段，不生成 `config/default.yaml` |
| `inc` | 增量修改工作流 | 包含增量验证阶段 |

独立 `eval.yaml` 是可选的，只有当前业务确实需要独立运行验收时才生成并登记。禁止生成
重复的 `config/default.yaml` 和无业务价值的 `config/empty.yaml`。

### 阶段约束

- 阶段名称必须唯一
- 每个阶段必须有 `task` 列表（非空）
- 生成 `config.yaml`、`config/inc.yaml` 和可选 `eval.yaml` 时，每个阶段的
  `task` 合计至少写出 100 个有效正文字符，具体说明输入、操作、工具、产物、Checker
  和失败处理。Config Generator 会统计 CJK 字符、英文字母和数字，忽略标点、空白、
  Markdown、YAML 和路径符号；不足 100 时以 `CONFIG-GEN-SPEC-019` 拒绝。
- `reference_files` 与 `output_files` 每项都必须是具体文件路径，禁止目录、通配符和目录形状路径。reference 还必须能证明来自固定交付文件、runtime_contract 明确要求的 type=file 用户输入或前序阶段的具体输出；无法确认一定存在的文件不得填写。目录型成果用 manifest、summary 或 report 文件表示。
- `output_files` 必须位于 `{OUT}/{DUT}/` 下

### 生成前后的引用自审

配置语法正确不代表引用契约正确。设计 config spec 前以及生成最终 YAML 后，都必须对每个
`reference_files` 做逐项来源审查，至少记录配置、阶段、原始路径、来源类别、声明位置或生产阶段和
审查结论。允许的来源只有三类：

1. 固定交付文件：路径与 manifest 的 `required_guidedocs`、`required_user_docs`、
   `required_templates`、`required_configs` 或 `required_deliverables` 中的具体文件一致，或者在
   审查时该静态文件已经真实存在。
2. 用户运行时输入文件：路径与 `runtime_contract.required_input` 中 `type=file` 的条目精确对应。
   `type=directory` 只能证明目录存在，不能推导目录内任意文件必然存在；目录内容必须在 task 中用
   `PathList` 枚举。
3. 派生文件：路径与 `.workflow/workflow_spec.yaml` 中严格早于当前阶段的某个
   `output_files` 完全一致。当前阶段或后续阶段才生成的文件属于前向引用。

只在 task、示例、工具描述或自然语言计划中出现的路径没有生产者证据。拼写相近、扩展名不同、
占位符展开后重复目录、父工作流前缀和“预计运行时会生成”也都必须判定失败。发现问题时应先修正
权威 workflow_spec 和相应 config spec，再重新调用 `WorkflowConfigGenerator`；不得只修最终
`config.yaml`。最后调用 `WorkflowRuntimeConfigAuditChecker`，以其
`static_audit_findings` 和 `unproven_reference_files` 为空作为通过条件。

## 注册与规划来源

默认 `preserve_registrations=true`，生成器从已有 `config.yaml` 保留：

- `tools`（包括 `RunTestCases` 和 `GeneratedTools`）
- `guide_docs`
- `paths`
- `template_overwrite`（写入时合并 `INPUT_ROOT` 和 `OUTPUT_ROOT`）

顶层 `checkers` 可继续保留，但阶段 Checker 注册不从旧 config 继承，而是始终由
workflow_spec 注入。这样不会因旧配置、阶段内手写注册或生成顺序产生实现名与注册名不一致。

## 完整 Config Spec 示例

```yaml
workflow:
  name: document_processor
  version: "0.1.0"
  description: "文档处理工作流：读取、分析、生成报告"

mode: default

template_overwrite:
  INPUT_ROOT: input/{DUT}
  OUTPUT_ROOT: '{OUT}/{DUT}'

mission:
  name: "文档处理任务"
  prompt:
    system: |
      你是一位文档处理助手。请按照阶段顺序完成文档分析和报告生成。

model:
  provider: openai-compatible
  name: default-model

loop_settings:
  max_loop_retry: 5
  retry_delay_start: 3

guide_docs:
  - Guide_Doc/overview.md

stages:
  - name: read_input
    desc: "读取输入文档"
    task:
      - "使用 ReadTextFile 读取 input/{DUT}/document.txt"
      - "记录文档基本信息"

  - name: analyze_content
    desc: "分析文档内容"
    task:
      - "统计文档行数、字数"
      - "提取关键段落"

  - name: generate_report
    desc: "生成处理报告"
    task:
      - "基于分析结果生成 Markdown 报告"
```

上述三个阶段必须已在 `.workflow/workflow_spec.yaml` 中存在，并在那里声明各自的
引用文件、输出文件和 Checker 绑定。

## 验证

生成后至少执行：

```bash
python .workflow/checkers/config_syntax_checker.py config.yaml
make check
```

CLI 调用应显式或默认使用
`--workflow-spec .workflow/workflow_spec.yaml`。确认阶段名一致、每个 main/inc task
有效长度至少 100，并确认引用、输出及 Checker 注册与 workflow_spec 完全一致，同时
确认不存在 `config/default.yaml` 或 `config/empty.yaml`。
