---
name: functions-and-checks
description: 功能规格分析与测试点定义阶段及其子阶段专属技能,用于指导{DUT}_functions_and_checks.md的写入工作
---

# 功能规格分析与测试点定义

本技能服务于 `functional_specification_analysis` 阶段以及其下的 4 个子阶段：
- `dut_function_grouping`
- `function_point_definition`
- `check_point_design`
- `functional_line_mapping_gap_analysis`

前三个子阶段直接维护`{OUT}/{DUT}_functions_and_checks.md`；逐行查漏补缺子阶段还会维护当前行块返回的`map_file`，并且只在规格证明CK需要修正时更新功能检查点文档。首次创建完整文档使用`EditTextFile(path, content)`；后续按当前子阶段局部加入或修正FG/FC/CK时使用`ReplaceStringInFile(path, old_string, new_string)`。`scripts/update.py`只是可选的批量助手，不是完成任务的前置条件。两种写入方式必须产生相同的规范层级。

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
先完成当前批次分析，再整理当前层级要写入的内容：
- FG 子阶段：只整理多个 `FG` 与各自描述
- FC 子阶段：只在已存在的同一个 `FG` 下整理多个 `FC` 与各自描述
- CK 子阶段：只在已存在的同一个 `FG/FC` 下整理多个 `CK` 与各自详细描述

### 步骤3
有`RunSkillScript`时可以执行`update.py`批量插入；没有时直接使用文本编辑工具在唯一父节点下插入同样内容。修改后必须重新读取目标段，确认父子层级、标签唯一性和正式描述均正确。

### 步骤4：逐行查漏补缺

在 `functional_line_mapping_gap_analysis` 子阶段，按 `Check`/`Complete` 返回的当前行块逐条判断语义，并严格使用返回的 `map_file`。完整格式和执行契约见 `Guide_Doc/dut_line_func_map.md`。

- 功能内容映射到语义准确且已声明的 `FG/FC/CK`；非功能内容才使用带具体理由的 `IGNORE`；空白行不映射；不得使用 `MISSMT`。
- Checker 只能证明语法、CK 存在性、范围、IGNORE 理由和逐行覆盖，不能证明 CK 选择或 IGNORE 理由在语义上正确。
- 只有规格上下文证明 CK 确实缺失、含糊或粒度错误时才修改功能检查点文档；映射语法、路径或理由错误只按 `failure_summary.next_action` 修复对应映射项。
- CK 标签发生变化时，同步迁移已有行映射以及工作区中已存在的覆盖率、测试用例和 Bug 证据引用。
- 每批写完后调用 `Check`；失败时先按 `error_code`、`artifact/location`、`expected` 和 `next_action` 修复，不能在文件未变化时重复检查。

## 可选脚本调用规范

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
- 发现标签已存在时，只修正或补充目标条目，不要重复创建标签或改坏层级结构
- 尽量在对应的子阶段使用对应的MODE,不要在插入`FG`的阶段额外插入了`FC`甚至`CK`

## 可选RunSkillScript使用说明

- `script` 替换为 `update.py` 的路径
- `-ITEMS` 参数值必须整体使用单引号包裹
- 若一次批量调用中前几项成功、后续失败，应根据报错修正后重新执行失败那一批，不需要重复已经成功的工作
- 完成当前子阶段写入后，继续执行阶段检查或推进下一子阶段

没有`RunSkillScript`时，按`Guide_Doc/dut_functions_and_checks.md`中的完整Markdown结构直接编辑即可，不得停在分析阶段或等待脚本环境。
