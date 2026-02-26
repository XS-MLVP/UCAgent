# Adder 功能点与检测点描述

## DUT 整体功能描述

Adder 模块是一个参数化的 64 位全加器，实现基础的算术加法功能。

### 端口接口说明
- 输入端口：
  - `a`: [WIDTH-1:0] 加数 A
  - `b`: [WIDTH-1:0] 加数 B
  - `cin`: 1-bit 进位输入
- 输出端口：
  - `sum`: [WIDTH-2:0] 和输出（注意：此处位宽定义疑似存在 Bug，应为 [WIDTH-1:0]）
  - `cout`: 1-bit 进位输出

### 工作原理概述
该模块采用组合逻辑实现：`{cout, sum} = a + b + cin`。

## 功能分组与检测点

### 1. 验证环境约束 (API)

<FG-API>

在该分组中定义形式化验证所需的环境假设，确保输入信号的合法性。

#### 输入合法性约束

<FC-INPUT-ASSUME>

**检测点：**
- <CK_API_INPUT_KNOWN> **(Style: Assume)** 假设输入信号 `a`, `b`, `cin` 在有效时间内不为 X 态。

### 2. 算术逻辑功能

<FG-DATAPATH>

验证加法器的核心算术功能是否正确。

#### 加法算术正确性

<FC-ADDER-FUNC>

**检测点：**
- <CK_ADDER_RESULT_CORRECT> **(Style: Comb)** 验证 RTL 输出 `{cout, sum}` 与参考模型 `a + b + cin` 的算术结果一致。

### 3. 覆盖率证明

<FG-COVERAGE>

确保验证环境没有过度约束，且关键场景可达。

#### 关键场景覆盖

<FC-COVER-POINTS>

**检测点：**
- <CK_COVER_COUT_SET> **(Style: Cover)** 证明进位输出 `cout` 为 1 的状态是可达的。
- <CK_COVER_SUM_ZERO> **(Style: Cover)** 证明和输出 `sum` 为全 0 的状态是可达的。
- <CK_COVER_MAX_VAL> **(Style: Cover)** 证明当 `a`, `b` 均为最大值且 `cin` 为 1 时，算术逻辑仍能正常工作（全 1 加法覆盖）。
