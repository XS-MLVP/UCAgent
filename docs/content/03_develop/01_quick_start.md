
# 定制开发入门

定制一个工作流通常需要四类资源：

- **工作流配置**：定义阶段顺序、任务、参考文件、输出和 Checker；
- **工具**：让 Agent 能读取、计算、测试或调用领域服务；
- **Guide_Doc/模板**：规定输出结构、标签和证据格式；
- **Checker**：用确定性规则验收阶段产物。

建议先运行 [Mini 示例](08_mini_example.md)，再把示例中的 Calculator 换成自己的输入。

## 1. 最小目录

```text
MyWorkflow/
├── Guide_Doc/
├── mini.yaml
├── my_tools.py
├── my_checkers.py
├── __init__.py
└── README.md
```

`Makefile` 可选，只负责准备工作区和拼接启动命令。

## 2. 工作流配置

下面是与当前解析器一致的最小结构：

```yaml
ex_tools:
  - "my_tools.CountWords"

template_overwrite:
  PROJECT: "Calculator"

mission:
  name: "{PROJECT} 文档生成"
  prompt:
    system: "你是一位技术文档工程师。"

stage:
  - name: analyze_project
    desc: "分析项目"
    task:
      - "读取 {PROJECT}/README.md"
      - "写入 {OUT}/{PROJECT}_analysis.md"
    reference_files:
      - "Guide_Doc/project_analysis_guide.md"
    output_files:
      - "{OUT}/{PROJECT}_analysis.md"
    checker:
      - name: markdown_check
        clss: "UnityChipCheckerMarkdownFileFormat"
        args:
          markdown_file_list: "{OUT}/{PROJECT}_analysis.md"
          no_line_break: true
    skill_list: []
    force_use_skill: false
```

字段说明：

- `ex_tools` 注册外部工具类的完整导入路径；
- `template_overwrite` 提供 `{PROJECT}` 等自定义模板值，输出目录用 CLI 的 `--output` 指定；
- `mission.prompt.system` 是全局系统提示；
- `stage` 是按顺序执行的阶段列表，阶段可以嵌套 `stage` 子阶段；
- `reference_files` 和 `output_files` 使用工作区相对路径；
- `checker[].args` 传给 Checker 构造函数，`extra_args` 用于实例化后添加新属性，不能覆盖已有属性；
- `skill_list` 只有在技能启用且非空时才进入阶段技能门禁。技能默认强制使用；设置 `force_use_skill: false` 才变为可选。

配置加载和列表替换规则见[工作流配置](03_workflow.md)。

## 3. 提供工具

示例配置中的 `my_tools.CountWords` 需要是可导入、可零参实例化的工具类。推荐继承 `UCTool`，使用 Pydantic `BaseModel` 定义参数，实现真实的 `_run` 行为。

先参考[定制工具](05_customize.md)中的完整实现，验证本地调用和 MCP schema 转换，再在 `ex_tools` 中注册。只调整任务和文档规范时，可以使用已有工具，无需新建工具类。

## 4. 定义验收

上面的 Markdown Checker 检查格式；若任务还要求字数、指定章节或业务规则，需要加入对应 Checker。Mini 示例提供 `WordCountChecker` 和 `RequiredSectionsChecker`。

自定义 Checker 必须验证真实产物，在失败时说明位置、期望条件和修复动作。完整可用的文件存在性检查示例见[自定义 Checker](07_checkers.md)，不要用无条件返回 `True` 的占位实现验收阶段。

## 5. 编写 Guide_Doc 和技能

Guide_Doc 应描述 Agent 当前阶段必须产生的完整格式和示例，并使用运行时相对路径引用，例如 `Guide_Doc/project_analysis_guide.md`。如果使用技能：

- `SKILL.md` 第一行必须是 `---`，frontmatter 至少含 `name` 和 `description`；
- 脚本放在 `scripts/`，通过 `RunSkillScript` 执行；
- `RunSkillScript` 从运行时快照加载 `ucagent_python_path`，为 Python 脚本准备导入路径；脚本读取已解析的运行配置；
- 技能关闭或目录不存在时，阶段仍必须能用普通工具和 Checker 完成。

## 6. 启动自定义工作流

以 `examples/MiniWorkflow` 为例，启动命令是：

```bash
cd examples/MiniWorkflow
make test
make run ARGS="--loop"
```

等价的核心命令：

```bash
PYTHONPATH=. ucagent ./output/ Calculator \
  --config ./mini.yaml \
  --guid-doc-path ./Guide_Doc/ \
  -s -hm --tui --loop
```

先按[直接使用](../02_usage/01_direct.md#1-配置模型)配置模型。`PYTHONPATH=.` 使当前目录中的 `my_tools` 和 `my_checkers` 可导入；`--guid-doc-path` 指定自定义 Guide_Doc。Makefile 会清理并准备 `output/`，手动执行核心命令前也需将 `Calculator/` 复制到工作区。

需要通过外部 Code Agent 执行时，使用 `make run ARGS="--mcp-server --backend=codex"`，再按 [MCP 接入](../01_start/03_mcp_mode.md#33-手动双终端接入以-codex-为例)连接。此处启用完整文件工具，以满足 Mini 任务中对 `EditTextFile` 的要求。

启动后，使用 `status`、`current_tips` 和 `tool_list` 检查任务；阶段完成必须通过 `Check`/`Complete`。更多完整配置见 [Mini 示例](08_mini_example.md)。
