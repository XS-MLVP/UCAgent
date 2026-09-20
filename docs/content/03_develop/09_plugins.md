
# 插件开发与发布

UCAgent 插件用于独立交付领域能力。一个插件可以按需提供 Tool、Checker、Skill、
Guide_Doc 和工作流中的任意一种或多种能力；这些贡献都是一级可选项，互不依赖，也不
要求插件提供完整工作流。插件是普通 Python 发行包：安装后通过标准 entry point 自动
发现；源码开发时也可以通过显式配置的搜索路径发现。插件必须由用户选择后才会导入和
激活，UCAgent 不会扫描或执行任意 workspace Python 文件。

`plugins/SpecGenerator/` 提供文档生成插件；`plugins/DesignWithPPA/` 展示自定义
Tool、Checker、模板、Skill 与工作流的组合。旧版 `plugins/GenSpec/` 保留为
YAML 工作流示例，已弃用（deprecated），后续文档生成使用 SpecGenerator。

## 同仓维护的可选插件

`plugins/` 用于维护随 UCAgent 一同开发、独立打包的插件。安装核心包不会安装或启用
这些插件。插件的日常开发应限定在自己的目录中：依赖、入口、配置、资源、测试和维护
命令均由插件管理，不向核心的依赖清单、默认配置或 Tool/Checker 导出表添加插件内容。

| 内容 | 维护位置 |
| :--- | :--- |
| 插件 API、加载机制、通用贡献流程和漏洞报告渠道 | UCAgent 核心及仓库根目录 |
| 清单、打包配置、依赖、实现、工作流、资源和测试 | 各插件目录 |
| 插件专用忽略规则、编辑规范、文件属性、使用与维护说明 | 各插件目录，可继承仓库通用规则 |
| GitHub Actions 触发、运行环境和当前核心安装 | 根目录 `.github/workflows/` |
| 插件安装、验证、打包和安装态测试步骤 | 插件目录中的脚本、Makefile 或本地 Action |

子目录的 `.gitignore`、`.editorconfig` 和 `.gitattributes` 不代表独立仓库，也不是插件
运行的必需文件；按实际维护需求保留，避免将插件专用规则扩散到整个仓库。CI 入口调用
插件内的验证步骤，并使用同一提交的 UCAgent 检查兼容性。只有公共插件接口或仓库级
基础设施发生变化时，才需要同步修改对应核心文件。

当前同仓插件如下。各插件的运行依赖、案例及维护命令见对应 README：

| 项目 | 插件 ID / 工作流 | 主要用途 |
| :--- | :--- | :--- |
| [DesignWithPPA](https://github.com/XS-MLVP/UCAgent/blob/main/plugins/DesignWithPPA/README.md) | `design-with-ppa:unit-design-tdd` | 测试驱动 RTL 设计与 PPA 优化 |
| [SpecGenerator](https://github.com/XS-MLVP/UCAgent/blob/main/plugins/SpecGenerator/README.md) | `xiangshan-spec-generator:design-document` | 基于 XiangShan 源码和生成 RTL 的证据，交付版本化中文设计与功能检测点文档 |

先安装核心，再从 UCAgent 仓库根目录按需安装，例如：

```bash
python -m pip install ./plugins/SpecGenerator
ucagent --validate-plugin xiangshan-spec-generator
```

运行时显式选择 `--plugin xiangshan-spec-generator`
和 `--plugin-workflow xiangshan-spec-generator:design-document`。
源码开发时可将插件 ID 换成 `--plugin ./plugins/SpecGenerator`，无需先安装插件。
工作区独立于插件实现；随包指导文档和其他资源由选中的工作流自动定位和复制。

## 名称约定

一个插件通常有四种名称，分别服务于目录、Python 打包、插件选择和代码导入：

同仓插件的项目目录建议使用 PascalCase（大驼峰），如 `DesignWithPPA`、`SpecGenerator`。
这是目录风格约定，加载器不依赖目录名的大小写。

| 层级 | DesignWithPPA 示例 | Spec Generator 示例 | 用途 |
| :--- | :--- | :--- | :--- |
| 项目目录 | `DesignWithPPA` | `SpecGenerator` | 文件系统路径 |
| 发行包名 | `ucagent-design-with-ppa` | `ucagent-xiangshan-spec-generator` | pip 安装和发行包 metadata |
| 插件 ID | `design-with-ppa` | `xiangshan-spec-generator` | entry point、清单、CLI 选择器 |
| Python 包名 | `design_with_ppa` | `spec_generator_plugin` | Python `import` 路径 |

插件 ID 必须匹配 `^[a-z0-9]+(?:[._-][a-z0-9]+)*$`：使用小写字母、数字，分隔符
`-`、`_`、`.` 只能出现在非空片段之间。ID 在同一 Python 环境和同一次 UCAgent 运行中
保持唯一。插件不应保留已废弃名称的兼容入口，否则发现结果和
配置容易产生歧义。

必须完全一致的是清单 `name`、`ucagent.plugins` entry point 的键和 provider 返回的
`Plugin.name`；清单 `entry` 与 entry point 的值也应指向同一个 provider。项目目录和
Python 包名不必与插件 ID 字面一致，文档示例的大小写及 `ucagent-` 前缀不是额外的加载
规则。`--plugin` 使用插件 ID 或项目路径，不能用发行包名或 Python 包名代替插件 ID。
工作流名遵守同样的 ID 字符规则，在所属插件内唯一，以 `<插件 ID>:<工作流名>` 选择。

## 标准项目结构

```text
DesignWithPPA/
├── ucagent-plugin.toml
├── pyproject.toml
├── README.md
├── Makefile
├── cases/
├── src/
│   └── design_with_ppa/
│       ├── __init__.py
│       ├── plugin.py
│       ├── ppa.py
│       ├── assets/
│       ├── scripts/
│       ├── workflows/
│       ├── Guide_Doc/
│       ├── templates/
│       └── skills/
└── tests/
```

只创建实际发布的资源目录。纯 Tool、纯 Checker、纯 Skill、纯 Guide_Doc 或纯工作流
插件都是有效插件。后续可以在同一发行包中增加其他贡献，无需修改 UCAgent 核心包。
运行时脚本可放在包内的 `scripts/`；测试、CI 和维护配置放在插件项目根目录。
同仓插件遵守相同结构，项目根位于 `plugins/<项目目录>/`。加载器按清单定位项目，
不依赖父目录名称。标准结构不要求保留空目录。

## 本地引导清单

源码态项目根目录必须包含 `ucagent-plugin.toml`：

```toml
schema_version = 1
name = "design-with-ppa"
entry = "design_with_ppa.plugin:get_plugin"
python_path = "src"
```

清单只允许这四个字段：

- `schema_version`：当前必须为 `1`；
- `name`：稳定插件 ID，必须和 provider 返回的 `Plugin.name` 完全一致；
- `entry`：`module.path:provider` 形式的 provider；
- `python_path`：相对项目根目录的 Python 导入根。

清单和 `python_path` 仅用于本地源码加载。安装后的 wheel 使用发行包 entry point，
不依赖本地清单，但 wheel 中可以保留同一份项目清单用于源码开发和审查。

## 安装态自动发现

插件的 `pyproject.toml` 必须注册 `ucagent.plugins` entry point：

```toml
[project]
name = "ucagent-design-with-ppa"
version = "0.2.0"
requires-python = ">=3.11"
dependencies = [
  "UCAgent>=26.9.2.dev14",
  "vcdvcd>=2.3.5,<3.0.0",
]

[project.entry-points."ucagent.plugins"]
design-with-ppa = "design_with_ppa.plugin:get_plugin"
```

核心和插件必须安装到同一 Python 环境。先按 UCAgent 安装说明安装核心，再安装插件的
本地目录、wheel 或已经发布的发行包；不能假定示例包已在 PyPI 发布。`requires_ucagent`
和发行包的 UCAgent 依赖范围应一致，下限使用实际验证过的版本。

安装后，Python 的 distribution metadata 会提供发现信息，例如从 UCAgent 根目录运行：

```bash
python3 -m pip install ./plugins/DesignWithPPA
ucagent --list-plugins
ucagent --validate-plugin design-with-ppa
ucagent <workspace> <dut> --plugin design-with-ppa
```

`--list-plugins` 只读取 entry point 名称和本地清单，不导入 provider。
`--validate-plugin` 才会导入被选择的 provider，并校验插件 API、UCAgent 版本、Python
依赖、外部命令和资源。UCAgent 不会在运行时自动安装依赖；缺失项会作为可操作错误返回。

## 源码态配置搜索

不安装插件时，在任一正常配置层增加 `plugin.search_paths`：

```yaml
plugin:
  search_paths:
    - "/opt/ucagent-plugins"
    - "{WORKSPACE}/local-plugins"
```

该字段必须是字符串列表，经过正常配置分层与 `{WORKSPACE}` 模板解析。每个路径可以：

- 直接指向包含 `ucagent-plugin.toml` 的插件项目；
- 指向包含多个插件项目的集合目录，UCAgent 只检查其一级子目录。

路径必须存在；不会递归扫描整个目录树。发现时只读取严格清单，按 `name` 精确匹配后才
导入 provider。若安装态 entry point 和搜索路径存在同 ID，启动会列出安装 distribution
和本地清单路径并报歧义；不得依赖来源优先级静默选择。

相对搜索路径以启动 UCAgent 时的当前工作目录为基准。用户级或 workspace 配置需要跨
目录稳定运行时，应使用绝对路径或 `{WORKSPACE}` 模板。

需要强制调试某个源码副本时，直接传项目路径：

```bash
ucagent --validate-plugin /opt/ucagent-plugins/DesignWithPPA
ucagent <workspace> <dut> \
  --plugin /opt/ucagent-plugins/DesignWithPPA
```

使用稳定 ID 的配置示例：

```bash
ucagent --config config.yaml --list-plugins
ucagent <workspace> <dut> \
  --config config.yaml \
  --plugin design-with-ppa
```

配置列表按 UCAgent 的整体替换语义处理。工作区配置覆盖用户配置时，应写出完整的预期
搜索路径列表。

## Provider 与运行时上下文

Provider 返回 `ucagent.plugins.Plugin`：

```python
from pathlib import Path

from ucagent.plugins import CommandRequirement, Plugin, PluginContext

from .checkers import TimingBudgetChecker
from .my_tool import MyTool


def create_tools(context: PluginContext):
    return [
        MyTool(
            workspace=str(context.workspace),
            output_dir=context.output_dir,
            write_dirs=list(context.write_dirs),
            un_write_dirs=list(context.un_write_dirs),
        )
    ]


def get_plugin():
    root = Path(__file__).resolve().parent
    return Plugin(
        name="design-with-ppa",
        version="0.2.0",
        description="Pre-layout PPA analysis and design workflows.",
        root=root,
        tool_factories=(create_tools,),
        checkers=(TimingBudgetChecker,),
        guide_doc_paths=(root / "Guide_Doc",),
        skill_paths=(root / "skills",),
        requires_ucagent=">=26.9.2.dev14",
        python_requirements=("vcdvcd>=2.3.5,<3.0.0",),
        command_requirements=(
            CommandRequirement("Yosys", ("yosys",)),
            CommandRequirement("OpenSTA", ("sta", "opensta")),
        ),
        assets=(root / "assets" / "reference.lib",),
    )
```

`Plugin` 的能力字段均默认为空：

| 字段 | 独立贡献合同 |
| :--- | :--- |
| `tool_factories` | 创建一个或多个 `UCTool`；不依赖工作流 |
| `checkers` | 注册一个或多个 `Checker` 子类；不依赖 Tool 或工作流 |
| `guide_doc_paths` | 插件激活时合入 runtime `Guide_Doc` 的文件或目录 |
| `skill_paths` | 插件激活且 Skill 功能开启时复制的 Skill 集合目录 |
| `workflows` | 可选择的完整配置入口及该工作流专属资源 |

允许所有能力字段为空，便于先发布和验证插件的 metadata、依赖及资产合同，再逐步增加
能力。实际发行版本应至少提供一种对用户有用的能力或资产。

`PluginContext` 在配置解析完成后传给工具工厂，包含：

| 字段 | 合同 |
| :--- | :--- |
| `workspace` | 当前 workspace 的绝对 `Path` |
| `output_dir` | 相对 workspace 的输出目录 |
| `write_dirs` | 最终解析的可写目录元组 |
| `un_write_dirs` | 最终解析的禁止写目录元组 |
| `cfg` | 最终解析、已冻结的 UCAgent 配置；不得整体写入日志或报告 |
| `plugin_root` | 当前插件 provider 包目录的绝对 `Path` |

工具必须继承 `UCTool`，使用 Pydantic `BaseModel` 作为 `args_schema`，并遵守 workspace
路径和读写策略。一个工厂可以返回一个工具或工具列表。UCAgent 会拒绝非 `UCTool`、
插件间同名工具以及和核心/外部工具同名的工具。插件工具进入 Agent 与 MCP 的同一标准
过滤流程，因此 `tools.ignore_tools` 和 `tools.selected_tools` 都会生效。

## Checker

`checkers` 中的每一项必须是 `ucagent.checkers.base.Checker` 的子类。激活插件后，任意
正常配置文件都可以通过类的短名引用它，不要求配置属于该插件的工作流：

```yaml
stage:
  - name: timing_budget
    desc: Check the timing budget
    task: []
    checker:
      - name: timing_budget_check
        clss: TimingBudgetChecker
        args: {}
```

UCAgent 会显式地把插件 Checker 注册表传给阶段解析器，不会把类写入全局
`ucagent.checkers` 模块。Checker 类名在所有已激活插件之间必须唯一，也不能与核心
Checker 同名。完整 dotted path 仍可用于普通可导入类，但正式的 `checkers` 声明提供
启动时类型校验、短名引用、冲突检测和插件摘要。

### 隔离执行生成代码

Checker 不得在 UCAgent 主进程中导入或执行 workspace 生成的 Python 模块。需要验证
Python DUT、coverage definition、测试配置或其他生成代码时，应使用 `RunTestCases`；
若必须检查仅能通过执行获得的结构，则使用有超时、输出上限和副作用隔离的子进程。

使用 `python -I` 启动隔离子进程时，不能依赖 `PYTHONPATH`：isolated mode 会忽略该
环境变量。父进程必须显式传入并由子进程加入 `sys.path` 的受信任导入根至少包括：

- 从当前已加载 `ucagent` 包位置推导出的精确 UCAgent import root；
- 当前运行已激活的源码插件 import root；
- 目标生成模块目录和 workspace，仅在上述受信任运行时路径之后加入。

导入顺序是安全合同的一部分。当前 UCAgent 根必须先于 workspace，避免生成目录中的
同名 `ucagent` 包遮蔽正在运行的实现。不要从当前目录名、仓库名、环境变量或另一个已
安装 distribution 猜测 UCAgent 路径；源码运行、editable install 和 wheel 安装都必须
解析到同一份正在运行的包。

此类 Checker 的测试应同时证明：源码插件能够在隔离子进程中导入当前 UCAgent；目标
模块不会出现在父进程的 `sys.modules`；子进程对环境变量、模块全局状态和 bytecode 的
修改不会污染主进程或 workspace；导入失败、超时和超量输出会返回有界诊断。

## 独立 Guide_Doc 与 Skill

`guide_doc_paths` 和 `skill_paths` 是插件级贡献，选中插件后即可生效，不要求选择
`--plugin-workflow`。Guide_Doc 可以声明单个文件或目录；Skill 路径必须是包含至少一个
有效 `SKILL.md` 的集合目录。每个 Skill 的 YAML frontmatter 必须包含规范的 `name` 和
非空 `description`，且 `name` 必须与目录名一致。Guide_Doc 贡献要求最终配置的
`guide_doc.enable` 为 `true`；禁用 runtime Guide_Doc 的特殊运行模式会明确拒绝 Doc
插件，而不会把文件复制到一个不会被使用的位置。插件 Skill 被复制到：

```text
<workspace>/.ucagent/skills/ext/<plugin-id>/
```

Skill 始终是可选能力。最终配置 `skill.use_skill: false` 或 CLI `--no-use-skill` 会跳过
所有插件 Skill 的复制、工具和使用证据门禁，但不会禁用同一插件的 Tool、Checker、
Guide_Doc 或工作流。插件级 Guide_Doc 仍会正常加载。阶段配置通过
`ext/<plugin-id>/<skill-relative-path>` 引用已复制的插件 Skill。

### 组合核心 Guide_Doc

插件或插件工作流可以在自己的配置 YAML 中通过 `guide_doc.core_copy_policy` 精确选择如何
复用当前语言默认配置提供的 `Guide_Doc` 文件：

```yaml
guide_doc:
  core_copy_policy:
    default_action: ignore
    retain:
      - dut_fixture.md
      - dut_test_case.md
    override:
      - dut_api_instruction.md
    ignore:
      - dut_bug_analysis.md
```

四个字段必须同时存在，含义如下：

| 字段 | 行为 |
| :--- | :--- |
| `default_action` | 未在列表中出现的核心文档默认执行 `retain` 或 `ignore` |
| `retain` | 复制并保留核心文档；插件提供内容不同的同路径文件时启动失败 |
| `override` | 不复制该核心文档，改为复制插件提供的同路径文件；插件未提供时启动失败 |
| `ignore` | 不复制该核心文档；插件也不得提供同路径文件 |

列表项是相对于当前语言默认 `Guide_Doc` 根目录的精确 POSIX 文件路径。路径必须使用规范
形式，不能是绝对路径，不能含 `..`、反斜杠、前后空白或重复项；三个动作列表也不能
相交。显式列出的路径必须确实存在于当前语言默认文档中。插件新增且不与核心重名的文档
无需列入策略，会照常复制。

该配置跟随普通配置分层规则：插件工作流 YAML 可以声明默认组合，workspace 配置、显式
`--config` 和 CLI `--override` 可以继续覆盖它。列表采用完整替换语义，因此覆盖某个动作
列表时应给出该层需要的完整列表。未声明策略时，核心默认值等价于全部 `retain`，保持普通
工作流的原有行为。

插件自身贡献的文档可通过 `guide_doc.plugin_copy_policy` 选择。该策略适合按最终配置只公开
当前工作流需要的语言或目标文档；模板变量会在策略解析前完成替换：

```yaml
guide_doc:
  plugin_copy_policy:
    default_action: ignore
    retain:
      - "{RTL_CODING_GUIDE_FILE}"
      - shared_test_contract.md
    ignore: []
```

三个字段必须同时存在。`default_action` 及显式动作只能是 `retain` 或 `ignore`；路径规则与
核心策略相同，并且显式路径必须由当前已激活插件实际提供。`ignore` 还会删除 workspace 中
同路径的旧插件文档，防止切换配置后继续读取过期资源。插件与核心同路径文档是否替换仍由
`guide_doc.core_copy_policy` 的 `retain/override/ignore` 决定。

## 工作流及其专属资源

插件可以声明 `PluginWorkflow`，把未来工作流和发行包绑定：

```python
from ucagent.plugins import CommandRequirement, PluginWorkflow

workflow = PluginWorkflow(
    name="unit-design-tdd",
    config_file=root / "workflows" / "unit-design-tdd.yaml",
    guide_doc_paths=(root / "Guide_Doc",),
    template_dir=root / "templates" / "unit_design",
    template_target="{OUT}",
    template_context_factory=build_template_context,
    skill_paths=(root / "skills",),
    command_requirements=(CommandRequirement("Picker", ("picker",)),),
    runtime_config_keys=("design_with_ppa.max_optimization_iterations",),
)
```

调用时先激活插件，再选择工作流：

```bash
ucagent <workspace> <dut> \
  --plugin design-with-ppa \
  --plugin-workflow design-with-ppa:unit-design-tdd \
  --config config.yaml
```

`--plugin-workflow` 和 `--config` 可以同时使用。工作流配置是独立基线层，不会冒充用户
配置文件；最终优先级为：核心全局、用户全局、核心语言默认、插件工作流、workspace
设置、显式 `--config`、CLI `--override`。未限定插件 ID 的短工作流名只有在已激活插件
中唯一时才允许。运行元数据会分别保留显式配置、插件与工作流选择器和工作流配置来源。
同一信息也写入 `.ucagent/runtime_config.json` 的 `launch_context`；插件显式声明的非秘密
最终配置标量单独写入 `plugin_options`，不会把完整配置或凭据复制到运行时快照。

`PluginWorkflow` 的资源和依赖字段都可选：

| 字段 | 工作流选择后的合同 |
| :--- | :--- |
| `config_file` | 独立工作流配置层；必须是插件根内的 YAML 文件 |
| `guide_doc_paths` | 追加该工作流专属 runtime Guide_Doc |
| `template_dir` | 该工作流模板源目录 |
| `template_target` | workspace 相对目标模板，例如 `{OUT}`；不得解析为 workspace 根、逃逸路径或与只读路径重叠 |
| `template_context_factory` | 可选受信任函数；根据最终配置与核心模板上下文返回额外模板变量，不能覆盖 `DUT`、`OUT`、`WORKSPACE` 等核心值 |
| `skill_paths` | Skill 启用时追加的可选工作流 Skill 集合 |
| `python_requirements` | 仅选择该工作流时检查的 Python 依赖 |
| `command_requirements` | 仅选择该工作流时检查的外部命令能力 |
| `runtime_config_keys` | 明确允许写入 runtime snapshot `plugin_options` 的非秘密标量路径 |

插件级依赖在插件激活时检查；工作流依赖只在工作流被选择后检查。因此仅使用
`AnalyzePPA` 不要求 Picker，而选择 `unit-design-tdd` 后才要求 `picker` console command。
不要为未验证的工具声明推测的 PyPI 版本；应校验真实 console command、版本输出和工作流
所需子命令。

工作流的 `guide_doc_paths` 和 `skill_paths` 只在选择该工作流时，追加到插件级资源；重复
声明的同一路径会去重。`template_dir` 仍是工作流专属资源，因为模板渲染必须和该次运行
的完整配置入口保持一致。不同 Skill 根不能包含会复制到同一插件相对路径的 Skill；该类
目标冲突会在启动时失败，而不是静默覆盖。

所有声明的工作流配置、Guide_Doc、模板、Skill 和资产必须存在并位于 `Plugin.root`
内部；符号链接也不能逃逸。插件自身的多个 Guide_Doc 来源若向同一路径提供不同内容会
启动失败。插件与核心文档同名时按照 `guide_doc.core_copy_policy` 处理；未显式允许
`override` 时不会静默覆盖。完全相同的保留文件允许幂等复用。插件 Skill 是可选加速路径：
`--no-use-skill` 下不复制 Skill，工作流提示、工具和 Checker 仍必须提供完整的非 Skill
路径并保持同一验收标准。指定 `template_target` 时，渲染器只合入并渲染该模板源拥有的
文件，不会遍历或重写目标目录中的其他既有产物，也会在写入前拒绝目标与 `{DUT}` 等
最终 `un_write_dirs` 中的具体只读路径重叠。

`template_context_factory(cfg, base_context)` 在最终配置层合并后、阶段与模板渲染前调用。
它适合由已解析的语言、目标平台等配置同时选择提示变量、模板文件名和模板内容。返回值
必须是有限 JSON mapping，键必须是非空字符串；工厂不能覆盖核心上下文。动态值的优先级
高于工作流 YAML 的静态 `template_overwrite`，显式 `--template-cfg-override` 仍可覆盖最终
文件渲染值。

在 `pyproject.toml` 的 package data 中显式包含非 Python 资源，例如：

```toml
[tool.setuptools.package-data]
design_with_ppa = [
  "assets/*.lib",
  "assets/*.md",
  "workflows/*.yaml",
  "Guide_Doc/*.md",
  "templates/**/*",
  "skills/**/*",
]
```

sdist 还应通过 `MANIFEST.in` 递归包含同一资源集合以及本地 `ucagent-plugin.toml` 和测试；
不能只依赖源码树中恰好存在的文件。

## 校验、构建、安装与发布

先准备插件声明的外部工具。以下命令从 UCAgent 仓库根目录验证同一份核心和插件源码：

```bash
python3 -m pip install -e .
python3 -m pip install build pytest
python3 -m pip install -e ./plugins/DesignWithPPA
python3 -m py_compile plugins/DesignWithPPA/src/design_with_ppa/*.py
python3 -m pytest -q plugins/DesignWithPPA/tests
ucagent --validate-plugin ./plugins/DesignWithPPA
python3 -m build ./plugins/DesignWithPPA
```

其他插件将上述插件路径替换为自己的项目目录。`python3 -m build` 的默认流程先构建 sdist、再由
sdist 构建 wheel，可以隔离源码树中既有的 `build/` 缓存，避免陈旧文件进入发布包。
也可以使用等价的 `uv build` 默认流程。不要只对可能含旧缓存的源码树运行
`python3 -m build --wheel`。

对生成的 wheel 还必须做安装态验证，不能只从源码目录导入：

```bash
python3 -m venv /tmp/design-with-ppa-verify
/tmp/design-with-ppa-verify/bin/python -m pip install .
/tmp/design-with-ppa-verify/bin/python -m pip install plugins/DesignWithPPA/dist/ucagent_design_with_ppa-*.whl
/tmp/design-with-ppa-verify/bin/ucagent --list-plugins
/tmp/design-with-ppa-verify/bin/ucagent --validate-plugin design-with-ppa
/tmp/design-with-ppa-verify/bin/ucagent <workspace> <dut> \
  --plugin design-with-ppa \
  --plugin-workflow design-with-ppa:unit-design-tdd
```

发布检查清单：

1. 清单 `name`、entry point 名称和 `Plugin.name` 完全一致；
2. `Plugin.version` 与发行包版本一致，`requires_ucagent` 覆盖实际测试版本；
3. Python 依赖同时出现在发行包 metadata 和 `Plugin.python_requirements` 校验声明中；
4. 外部命令提供准确名称和可接受的可执行文件替代项；
5. wheel 中包含所有配置、文档、模板、Skill、脚本和资产；
6. sdist 中包含 `ucagent-plugin.toml`、测试和构建 wheel 所需的全部文件；
7. 本地路径、配置搜索路径和安装 entry point 三种发现方式经过测试；
8. 每个 Tool 通过直接调用、失败边界、MCP schema 转换和工具过滤测试；
9. 每个 Checker 通过类型校验、短名解析、生命周期及名称冲突测试；
10. 独立 Guide_Doc、Skill 和工作流分别在不提供其他能力时经过激活测试；
11. 每个工作流在 Skill 启用、显式禁用及 Skill 目录不存在时都能完成；
12. 安装态测试从 wheel 运行，不依赖仓库内的 `src` 路径；
13. 发布新版本后，用 `python3 -m pip install --upgrade <发行包或 wheel 路径>` 更新，
    再运行 `ucagent --validate-plugin <插件 ID>`。

## 常见失败

- `available=[]`：插件未安装，且最终配置的 `plugin.search_paths` 未包含项目或父目录；
- `manifest name ... does not match`：本地清单 ID 与 provider 的 `Plugin.name` 不一致；
- `requires Python package`：当前 UCAgent Python 环境缺少插件依赖或版本不满足；
- `requires command`：外部分析工具不在当前进程的 `PATH`；
- `resource must remain inside plugin root`：provider 声明了包外路径或逃逸符号链接；
- `selector is ambiguous`：多个 entry point、本地插件或工作流使用了冲突名称；错误会列出
  候选 distribution 或清单路径，应卸载、移除搜索路径或显式使用唯一源码项目路径；
- `Duplicate plugin Checker name`：两个已激活插件声明了同名 Checker；
- `conflicts with a core Checker`：插件 Checker 类名占用了核心 Checker 短名；
- 工具不在 Agent/MCP：确认已传 `--plugin`，再检查最终的 `tools.ignore_tools` 与
  `tools.selected_tools`。

## 运行工作流的开放契约

插件工作流必须把 LLM 实际需要遵守的规范文件列入当前阶段的 `reference_files`，不能
只依赖失败后的错误提示。例如使用行映射 Checker 时，阶段必须同时提供
`Guide_Doc/dut_line_func_map.md` 和当前生成的功能合同；任务提示还应明确单行物理范围也
使用完整的 `start-end`，例如 `10-10`，不能写成单个数字 `10`。规范文件缺失会让能力较弱
的模型反复试错，也会把本可避免的格式错误计入阶段失败。

阶段配置、模板上下文和能力依赖在 UCAgent 启动阶段一次性解析并复制到运行 workspace。
修改插件 YAML、Guide_Doc 或模板后，必须重新启动工作流并重新生成 workspace；运行中的
Agent 不会热加载这些文件。恢复或重试时要检查生成文件与当前解析配置的来源、哈希和
语言选择是否一致，不能把旧 workspace 的产物当作新配置的证据。

命令行 backend 可能自带 shell、文件浏览和外部目录读取能力，不能只靠系统提示要求模型
遵守 workspace 边界。工作流若要求测试、转换或分析只能由受信任 Tool/Checker 执行，
backend 配置必须同时禁用原生 shell 并拒绝 workspace 外路径；读写当前 workspace 仍使用
backend 的受限文件工具，测试与外部命令使用公开 MCP Tool。应通过真实 backend 会话验证
被禁用能力确实返回拒绝，而不是仅验证配置文件包含对应字段。

批处理 Checker 的阶段文档会被模型反复编辑。每次精化或补充说明后，必须在完整文档上
检查 FG/FC/CK ID 全局唯一、父子路径和行映射引用闭合；不能把同一个 CK 的新描述追加到
另一个 FC 下，也不能只检查当前 batch 而忽略已完成批次。提交 `refined` 进度时只允许
使用当前 `CurrentTips` 给出的完整 CK 路径，完成后重新获取下一批。

批处理模板还必须区分“覆盖模型已声明 CK”和“测试函数已关联 CK”两类证据。覆盖组通常在
模板阶段之前一次性声明全部 CK，但这不代表全部模板已经生成。当前 Check 只要求历史已完成
项和 `CurrentTips` 当前批次存在真实测试关联；未来批次可以暂未关联，也不得提前关联并跳过
批次。源文档或测试关联变化时，应从当前文件和测试报告重新同步进度，而不能把覆盖声明或
旧 checkpoint 当成完成证据。

coverage predicate 本身也是独立证据，不能用 bin 名称存在来代替“条件已实现”。需要分批
实现 predicate 的工作流应在结构阶段为完整 CK 集写入唯一的显式 false 占位；实现阶段通过
AST 或等价源码证据区分占位与非恒定 predicate，只允许替换 `CurrentTips` 当前批次。恒真
callable、提前实现未来批次、已完成项回退为占位都必须拒绝。源码门禁只能证明条件已编写；
predicate 是否可达以及是否与真实刺激匹配，仍要由随后隔离执行的 pytest coverage hit 证明。

复用核心批处理 Checker 时，先确认它的“报告通过”语义是否与插件工作流一致。验证工作流
可以保留由正确测试暴露的 DUT Bug，而设计生成工作流通常要求当前测试全部 Pass；两者不能
共用同一个最终报告判定。需要不同语义时，应继承
`UnityChipCheckerBatchTestsImplementation`，通过 `_validate_current_batch_report(report)`
只替换当前批次的报告门禁，并继续复用它的源码重同步、精确节点执行、checkpoint 和批次推进
状态机。若工作流不使用 Bug 文档，还应让 `_cached_document_preflight(target_tests)` 返回
`None`，不能让无关的 Bug 文档预检阻塞测试批次。报告门禁必须只检查本次精确节点的状态、
CK 关联和命中证据；完整覆盖模型中未由本批次执行的其他 CK 是局部报告中的正常未命中，
不能据此拒绝当前批次。门禁失败时不得调用批次完成或持久化进度，并应覆盖“拒绝后重建
Checker 仍从同一批开始”的回归测试。

批量实现 Python 测试时必须原位修改 `CurrentTips` 指定的已有模板函数，不能在文件前后追加
同名 `def`。每次写入后应对整个测试文件做 AST 级顶层函数名唯一性检查，并确认
`mark_function` 引用的正是该唯一函数；否则后定义会覆盖模块属性，pytest 收集、覆盖关联和
LLM 看到的实现可能指向不同函数，真实实现也可能被旧占位断言隐藏。

规范文档中的 fenced YAML 必须用真实 YAML 解析器预检。包含冒号、哈希、花括号模板或
其他 YAML 语法字符的自然语言值应显式使用引号；例如
`packing: "element k occupies bits [8*k+7:8*k+0]"`，不能让冒号被解析成新的 mapping。
不要把“看起来像 YAML”的 Markdown 文本当作有效证据；Check 失败时应修复具体字段并
重新解析整个 fenced block。

外部工具依赖应声明真实的 console command、版本参数和所需子命令，并在缺失、版本不符或
子命令不可用时返回明确的下一步。只使用 Tool 时不应加载工作流专属依赖；只有选择对应
工作流才检查其能力。测试、转换和分析产生的临时文件应由受信任的 Check/Complete 子进程
管理，阶段 LLM 只接触公开源码语言、Python 测试和结果摘要。

插件提供的清理入口属于开发便利功能，不能依赖 Git 状态来决定删除范围。清理目标必须是
插件根目录内列举的输出、构建和缓存目录，并拒绝通过可覆盖的 workspace 或 output 参数
扩大范围；已跟踪源文件和用户对源文件的修改必须保持不变。发布前应在临时目录验证“目标
缓存被删除、无关文件保留、插件根外路径不会被触碰”这三个边界。
