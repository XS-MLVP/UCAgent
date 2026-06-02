---
name: fm-func-spec
description: 提取和分析被测模块(DUT)的功能规格和形式化检测点
---

# 功能规格与检测点分析工作流 (Functional Spec)

本技能指导如何基于给定的基础信息，细化出该 DUT 应该包含的具体功能检测点，通过 **`update_spec.py` 脚本** 写入 `.formal_records.yaml`。

> **功能点标签规范、Style 标注规则与高级模式示例参见 `Guide_Doc/functions_and_checks.md`**

## 步骤

### 1. 读取基础信息
阅读输入说明、RTL 源码或预生成的文档骨架，理解 DUT 的核心功能。

### 2. 规划三级标签结构
按照 `Guide_Doc/functions_and_checks.md` 中的规范，使用 `FG-XXX` (功能组)、`FC-XXX` (功能点)、`CK-XXX` (检测点) 组织层级。

### 3. 通过脚本写入 YAML

**禁止直接编辑 `.formal_records.yaml`**，必须通过 `RunSkillScript` 调用 `update_spec.py`：

#### 添加功能组 (FG)
```
python3 .ucagent/skills/formal/fm-func-spec/scripts/update_spec.py \
  -action add_fg -id FG-API -name "验证环境约束"
```

#### 添加功能点 (FC)
```
python3 .ucagent/skills/formal/fm-func-spec/scripts/update_spec.py \
  -action add_fc -fg FG-API -id FC-API-INPUT-CONSTRAINT -desc "定义输入信号的合法约束条件"
```

#### 添加检测点 (CK)
```
python3 .ucagent/skills/formal/fm-func-spec/scripts/update_spec.py \
  -action add_ck -fc FC-API-INPUT-CONSTRAINT -id CK-API-INPUT-NO-X -style Assume -desc "输入信号不能为 X 态"
```

#### 修改条目
```
python3 .ucagent/skills/formal/fm-func-spec/scripts/update_spec.py \
  -action update -id CK-API-INPUT-NO-X -style Comb -desc "新的描述"
```

#### 删除条目
```
python3 .ucagent/skills/formal/fm-func-spec/scripts/update_spec.py \
  -action delete -id CK-API-INPUT-NO-X
```

#### 管理全局参数 (Parameters)
用于定义 `WIDTH` 等硬件常量，会自动同步到 SV 模块头和实例化语句中。
```
python3 .ucagent/skills/formal/fm-func-spec/scripts/update_spec.py \
  -action set_param -id WIDTH -value 64
```
删除参数：
```
python3 .ucagent/skills/formal/fm-func-spec/scripts/update_spec.py \
  -action delete_param -id WIDTH
```

#### 管理白盒观察信号 (Whitebox Signals)
用于在 `wrapper.sv` 中手动声明一些用于观察内部逻辑的信号。
```
python3 .ucagent/skills/formal/fm-func-spec/scripts/update_spec.py \
  -action add_signal -desc "logic [WIDTH-1:0] internal_state"
```
删除信号（需提供完全匹配的声明字符串）：
```
python3 .ucagent/skills/formal/fm-func-spec/scripts/update_spec.py \
  -action delete_signal -desc "logic [WIDTH-1:0] internal_state"
```

#### 查看当前结构 (Show)
```
python3 .ucagent/skills/formal/fm-func-spec/scripts/update_spec.py -action show
```


### 4. 完成后调用 Check

Checker 会验证 YAML 结构完整性，通过后自动生成 `03_{DUT}_functions_and_checks.md` 文档。

## 核心规则
1. 对于每一个状态转移或者核心功能 Seq 检测点，尽最大可能配对提供一个 Cover 检查（证明其可达性）。
2. 在规划阶段严禁编写真实的 SystemVerilog 代码，只写逻辑描述。
3. 必须包含 `FG-API`（环境约束）和 `FG-COVERAGE`（可达性覆盖）两个功能组。
4. `id` 必须以 `CK-` 开头，使用大写字母和横杠（如 `CK-CORE-ARITH-RESULT`）。
5. `style` 必须是 `Assume` / `Comb` / `Seq` / `Cover` 之一。
