---
name: formal-env-config
description: 基于 basic_info.clock_reset 与 extra_config.tcl 渲染 wrapper/checker/formal.tcl。
---

# Formal Environment Config

本技能用于维护 `.formal_records.yaml` 中与 Stage 5 渲染相关的配置。

本阶段的事实来源分为两部分：

- `.formal_records.yaml.basic_info.clock_reset`：DUT 的真实时钟/复位定义
- `.formal_records.yaml.extra_config.tcl`：FormalMC 运行参数

核心规则：
1. 禁止直接编辑 `tests/{DUT}_formal.tcl`
2. 禁止直接编辑 `tests/{DUT}_wrapper.sv`
3. 只能通过 `RunSkillScript` 调用 `update_extra_config.py` 修改 YAML
4. `formal.tcl`、`wrapper.sv`、`checker.sv` 都是派生产物，Checker 通过后系统会自动 full refresh 重建

执行说明：
- 在本工作流中，请优先通过 `RunSkillScript` 调用技能脚本
- 不要假设宿主 `python3` 环境具备所有依赖
- 当 YAML 或模板发生变化时，应以 full refresh 后的生成结果为准

常用命令：

```bash
python3 .ucagent/skills/formal/env-config/scripts/update_extra_config.py -action show
python3 .ucagent/skills/formal/env-config/scripts/update_extra_config.py -action set -path clock_reset.clock_signal -value "clk_i"
python3 .ucagent/skills/formal/env-config/scripts/update_extra_config.py -action set -path clock_reset.reset_signal -value "rst"
python3 .ucagent/skills/formal/env-config/scripts/update_extra_config.py -action append -path tcl.extra_commands -value '"set_prove_time_limit 3600"'
```

字段清单：

- `clock_reset.clock_signal`：DUT 实际时钟端口名；无时钟设计填空字符串
- `clock_reset.clock_count`：时钟个数；组合逻辑可填 `0`
- `clock_reset.clock_type`：单时钟、多时钟或无时钟
- `clock_reset.reset_signal`：DUT 实际复位端口名；无复位设计填空字符串
- `clock_reset.reset_type`：同步/异步 + 高/低有效描述
- `tcl.timeout`：TCL 运行超时设置
- `tcl.extra_commands[]`：附加 TCL 命令

最小骨架：

```yaml
basic_info:
  clock_reset:
    clock_signal: ""
    clock_count: ""
    clock_type: ""
    reset_signal: ""
    reset_type: ""
extra_config:
  tcl:
    timeout: ""
    extra_commands: []
```

推荐填写顺序：

1. 先确认 `basic_info.clock_reset` 已经完整填写 DUT 真实时钟/复位事实。
2. 再设置 `tcl.timeout`，保证运行预算与设计复杂度匹配。
3. 只有在默认模板不够时，才补 `tcl.extra_commands[]`。

写入约束：

- Stage 5 不再推断时钟/复位信号；`clock_reset.clock_signal` 与 `clock_reset.reset_signal` 必须来自 Stage 2 的明确填写。
- 若 DUT 无时钟或无复位，就保持对应字段为空；渲染器会自动省略 `def_clk`、`def_rst`、`default clocking` 或 `disable iff`。
- 渲染后对外统一使用 `clk` 和 `rst_n`；如果 DUT 实际端口不同，会在 wrapper/checker 内部自动生成别名映射。
- `tcl.extra_commands[]` 只放补充命令，不要重复模板默认已经生成的基础 setup。
- 修改 `clock_reset` 或 `extra_config.tcl` 后，应以 full refresh 生成出的 `formal.tcl`、`wrapper.sv`、`checker.sv` 为准。
