---
name: formal-basic-info
description: 通过脚本把 DUT 基本信息写入 .formal_records.yaml 的 basic_info 字段，并由系统自动渲染 02 基本信息文档。
---

# Formal Basic Info

本技能用于维护 `.formal_records.yaml` 中的 `basic_info` 字段。

本阶段的唯一事实来源是 `.formal_records.yaml.basic_info`。

核心规则：
1. 禁止直接编辑 `02_{DUT}_basic_info.md`
2. 只能通过 `RunSkillScript` 调用 `update_basic_info.py` 修改 YAML
3. `02_{DUT}_basic_info.md` 是派生产物，Checker 通过后系统会自动重建
4. 必须在本阶段明确填写 DUT 实际时钟/复位定义；不要把时钟、复位信号留到 Stage 5 再猜测或补写

执行说明：
- 在本工作流中，请优先通过 `RunSkillScript` 调用技能脚本
- 不要假设宿主 `python3` 环境具备所有依赖

常用命令：

```bash
python3 .ucagent/skills/formal/basic-info/scripts/update_basic_info.py -action show
python3 .ucagent/skills/formal/basic-info/scripts/update_basic_info.py -action set -path module_type -value "加法器"
python3 .ucagent/skills/formal/basic-info/scripts/update_basic_info.py -action append -path ports.inputs -value '{"name":"clk","width":1,"signal_type":"clock","desc":"主时钟"}'
```

字段清单：

- `module_type`：模块类型，字符串
- `is_top`：是否顶层，布尔值
- `design_type`：组合/时序/流水线等设计类型，字符串
- `ports.inputs[]`：输入端口，每项包含 `name/width/signal_type/desc`
- `ports.outputs[]`：输出端口，每项包含 `name/width/signal_type/desc/potential_issue`
- `parameters[]`：参数列表，每项包含 `name/default/range/desc`
- `core_functions[]`：核心功能点
- `correctness_requirements[]`：正确性要求
- `clock_reset.clock_signal`：主时钟信号名；无时钟设计填空字符串
- `clock_reset.clock_count`：时钟个数
- `clock_reset.clock_type`：单时钟、多时钟等
- `clock_reset.cdc_note`：跨时钟说明
- `clock_reset.reset_signal`：复位信号名；无复位设计填空字符串
- `clock_reset.reset_type`：同步/异步
- `clock_reset.reset_init_state`：初始复位行为说明
- `architecture.ascii_diagram`：ASCII 结构图
- `architecture.datapath`：数据通路说明
- `architecture.control_logic`：控制逻辑说明
- `parameter_impact[]`：参数变化对设计行为的影响
- `special_units.arithmetic[]`：算术单元列表，每项包含 `unit_type/exists/note`
- `special_units.storage[]`：存储单元列表，每项包含 `unit_type/exists/note`
- `env_config_notes.clock_constraints[]`：时钟约束建议
- `env_config_notes.reset_sequence`：复位序列建议
- `env_config_notes.input_constraints[]`：输入约束建议
- `conclusion`：本阶段结论

最小骨架：

```yaml
basic_info:
  module_type: ""
  is_top: true
  design_type: ""
  ports:
    inputs: []
    outputs: []
  parameters: []
  core_functions: []
  correctness_requirements: []
  clock_reset:
    clock_signal: ""
    clock_count: ""
    clock_type: ""
    cdc_note: ""
    reset_signal: ""
    reset_type: ""
    reset_init_state: ""
  architecture:
    ascii_diagram: ""
    datapath: ""
    control_logic: ""
  parameter_impact: []
  special_units:
    arithmetic: []
    storage: []
  env_config_notes:
    clock_constraints: []
    reset_sequence: ""
    input_constraints: []
  conclusion: ""
```

推荐填写顺序：

1. 先写 `module_type/is_top/design_type` 和 `ports`，把 DUT 轮廓固定下来。
2. 再写 `parameters`、`core_functions`、`correctness_requirements`，把后续 SVA 目标对齐。
3. 补全 `clock_reset`、`architecture`、`special_units`，这些字段会直接影响环境建模。
4. `clock_reset.clock_signal` 与 `clock_reset.reset_signal` 必须写 DUT 实际端口名；如果 DUT 无时钟或无复位，就显式保留空字符串。
4. 最后写 `env_config_notes` 与 `conclusion`，给后续 `extra_config` 和脚本生成提供约束依据。

写入约束：

- `ports.inputs[]` 与 `ports.outputs[]` 必须是对象数组，`width` 建议写整数或可读位宽表达式。
- `clock_reset.clock_signal` 与 `clock_reset.reset_signal` 是 Stage 5 渲染时的直接输入，必须显式填写；不要依赖后续阶段自动猜测。
- 若某个输入端口是 DUT 主时钟或复位，应该同时在 `ports.inputs[].signal_type` 中标注为 `clock` 或 `reset`，并在 `clock_reset` 中写出对应信号名。
- `special_units.*[]` 的 `exists` 必须为布尔值，不要写 `"yes"` 或 `"no"`。
- `env_config_notes` 只写建议，不直接替代 `extra_config` 的最终配置。
- `02_{DUT}_basic_info.md` 是渲染结果，不要先改文档再回填 YAML。
