---
name: functions-and-checks
description: 功能规格分析与测试点定义阶段及其子阶段专属技能,用于指导{DUT}_functions_and_checks.md的写入工作
---

# 功能规格分析与测试点定义

本技能服务于 `functional_specification_analysis` 阶段以及其下的 3 个子阶段：
- `dut_function_grouping`
- `function_point_definition`
- `check_point_design`

本阶段对 `{OUT}/{DUT}_functions_and_checks.md` 的新增内容，统一通过 `scripts/update.py` 完成。
不要手工直接插入 FG/FC/CK 条目；先分析，再按当前子阶段批量写入对应层级。

## 分析原则

- 先看 DUT 的整体职责，再拆 FG；再看每个 FG 内部的职责边界，再拆 FC；最后把每个 FC 拆成可验证的 CK。
- FG 要按“独立功能域”分，不要按实现细节分。
- FC 要按“同一功能域内的具体子功能”分，要求比 FG 更具体。
- CK 要按“单个可测行为/条件”分，要求可直接转成测试输入输出检查。
- 一个 FG 至少要能覆盖一组相关 FC；一个 FC 至少要能落到一个或多个 CK。
- CK 必须具备可测性，不能只是抽象口号。

## 分析方法

### 1. 先提炼 DUT 的功能主线

先回答三个问题：
- DUT 做什么
- 输入输出怎么影响行为
- 哪些行为必须单独验证

例如：
- 浮点 ALU：可先分出 `FG-API`、`FG-ARITHMETIC`、`FG-SPECIAL`、`FG-BOUNDARY`
- FIFO：可先分出 `FG-API`、`FG-PUSH`、`FG-POP`、`FG-FULL_EMPTY`、`FG-BOUNDARY`
- 寄存器文件：可先分出 `FG-API`、`FG-READ`、`FG-WRITE`、`FG-CONFLICT`、`FG-RESET`

### 2. 再把 FG 拆成 FC

每个 FG 下的 FC 应该是“同一大功能下的不同子职责”：
- `FG-ARITHMETIC` 下面可有 `FC-ADD`、`FC-MUL`、`FC-DIV`
- `FG-SPECIAL` 下面可有 `FC-NAN`、`FC-INF`、`FC-ZERO`
- `FG-FIFO` 下面可有 `FC-PUSH`、`FC-POP`、`FC-STATUS`

不要把 FC 写成和 FG 同级的大杂烩，也不要把实现步骤直接当 FC。

### 3. 再把 FC 拆成 CK

CK 需要按“可验证场景”细分，通常可从以下维度拆：
- 正常路径
- 边界条件
- 特殊值
- 异常输入
- 状态切换
- 标志位/输出组合

例如：
- `FC-ADD` 可拆为 `CK-ADD-NORMAL`、`CK-ADD-OVERFLOW`、`CK-ADD-UNDERFLOW`、`CK-ADD-ZERO`
- `FC-POP` 可拆为 `CK-POP-NORMAL`、`CK-POP-EMPTY`、`CK-POP-UNDERFLOW`
- `FC-WRITE` 可拆为 `CK-WRITE-NORMAL`、`CK-WRITE-ADDR-BOUNDARY`、`CK-WRITE-CONFLICT`

## 质量标准

- FG 不能太碎：如果两个标签只是同一能力的不同角度，优先放到同一个 FG。
- FC 不能太泛：如果一个 FC 里已经出现多个明显不同的验证场景，就应该再拆 CK。
- CK 不能太空：例如“正确性验证”“基础功能验证”过于泛泛，不能直接作为 CK。
- CK 不能重复：同一个 FG/FC 下，不要用不同名字重复覆盖同一场景。
- CK 不能混场景：例如“正常值和异常值一起验证”通常应拆成两个 CK。

## 反例与正例

### FG 反例
- `FG-ADD-1`
- `FG-STEP1`
- `FG-TEST-CASE`

### FG 正例
- `FG-API`
- `FG-ARITHMETIC`
- `FG-SPECIAL`
- `FG-BOUNDARY`

### FC 反例
- `FC-ALL`
- `FC-LOGIC`
- `FC-DETAIL-1`

### FC 正例
- `FC-ADD`
- `FC-MUL`
- `FC-DIV`
- `FC-PUSH`

### CK 反例
- `CK-OK`
- `CK-CHECK`
- `CK-BASIC-FUNCTION`

### CK 正例
- `CK-ADD-NORMAL`
- `CK-ADD-OVERFLOW`
- `CK-POP-EMPTY`
- `CK-ZERO-SIGN`

## 执行步骤

### 步骤1
阅读 `reference_files` 中列出的文档，明确当前子阶段需要补充的是 FG、FC 还是 CK。

### 步骤2
先完成当前批次分析，再一次性整理成脚本入参：
- FG 子阶段：只整理多个 `FG` 与各自描述
- FC 子阶段：只在已存在的同一个 `FG` 下整理多个 `FC` 与各自描述
- CK 子阶段：只在已存在的同一个 `FG/FC` 下整理多个 `CK` 与各自详细描述

### 步骤3
使用 `RunSkillScript` 执行 `update.py`，一次调用完成同层级批量插入。

## 脚本调用规范

均适用于阶段：`functional_specification_analysis`

### 1. 插入多个 FG

适用子阶段：`dut_function_grouping`

```bash
python3 script -MODE FG -ITEMS '[{"fg":"FG-API","title":"DUT测试API","desc":"提供DUT对外测试时需要使用的标准操作接口。"},{"fg":"FG-ARITHMETIC","title":"算术运算功能分组","desc":"包含加法、乘法、除法等核心算术运算能力。"}]'
```

要求：
- `-ITEMS` 必须是 JSON 数组
- 每个元素至少包含 `fg` 和 `desc`
- `title` 可选；若省略，脚本自动按标签生成标题
- 可在一次调用中同时插入多个 FG

### 2. 在一个 FG 下插入多个 FC

适用子阶段：`function_point_definition`

```bash
python3 script -MODE FC -FG 'FG-ARITHMETIC' -ITEMS '[{"fc":"FC-ADD","title":"加法运算","desc":"实现 IEEE 754 单精度浮点加法，覆盖正常值、特殊值以及异常边界。"},{"fc":"FC-MUL","title":"乘法运算","desc":"实现 IEEE 754 单精度浮点乘法，并检测溢出与下溢。"}]'
```

要求：
- `-FG` 指定父功能组，必须已存在
- `-ITEMS` 中每个元素至少包含 `fc` 和 `desc`
- 支持在同一个 FG 下，一次性插入多个 FC
- 该步骤只插入 FC 与功能描述，不要新增 FG，也不要提前手工写 CK

### 3. 在一个 FG/FC 下插入多个 CK

适用子阶段：`check_point_design`

```bash
python3 script -MODE CK -FG 'FG-ARITHMETIC' -FC 'FC-ADD' -ITEMS '[{"ck":"CK-ADD-NORMAL","desc":"规格化数加法：验证正数、负数以及异号数相加的结果正确性。"},{"ck":"CK-ADD-OVERFLOW","desc":"加法溢出：验证结果超出最大规格化数范围时 overflow 标志正确。"}]'
```

要求：
- `-FG` 与 `-FC` 必须共同定位到已存在的父节点
- `-ITEMS` 中每个元素至少包含 `ck` 和 `desc`
- 支持一次性插入多个 CK
- 若目标 FC 下还没有 `**检测点：**` 小节，脚本会自动补上
- 该步骤只插入 CK 与检测点描述，不要新增 FG 或 FC

## 核心规则

- 所有标签必须严格使用 `FG-*`、`FC-*`、`CK-*` 格式，且同一父节点下不能重名
- `FG`、`FC`、`CK` 的插入顺序必须遵守层级：先有 FG，再有 FC，最后有 CK
- 当前调用只处理当前层级，不要在一次调用中混插 FG/FC/CK，也不要跨层级补写
- `desc` 必须是最终要写入文档的正式描述，不要传占位文本
- 发现标签已存在时，应修改参数或补充遗漏内容，不要手工改坏层级结构
- 尽量在对应的子阶段使用对应的MODE,不要在插入`FG`的阶段额外插入了`FC`甚至`CK`

## RunSkillScript 使用说明

- `script` 替换为 `update.py` 的路径
- `-ITEMS` 参数值必须整体使用单引号包裹
- 若一次批量调用中前几项成功、后续失败，应根据报错修正后重新执行失败那一批，不需要重复已经成功的工作
- 完成当前子阶段写入后，继续执行阶段检查或推进下一子阶段
