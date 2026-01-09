# InstrBoundary 规格说明文档

> 本文档用于指导编写 `InstrBoundary` 子模块的规格说明书。请按照每个小节的提示补充内容，保持技术语言准确、条理清晰、便于验证复用。若某项内容不存在，请显式写明"无"或"暂缺"，不要删除章节。

## 简介
- **设计背景**：`InstrBoundary`（指令定界模块）是IFU中负责确定每条指令位置的子模块。对于64字节的预测块，以2字节为单位划分，最多可以分为32个位置。InstrBoundary需要标记每个位置是否为指令的开头或末尾，从而确定指令的边界。

  该模块采用多路推断再合并拼接的优化策略来平衡时序压力。先计算0~15号指令位置，按两路假设计算16~31号位置，根据15号位置的实际结果选择一路。

- **版本信息**：规格版本 V3，基于文档 AS-IFU-V3.md

- **设计目标**：
  - 准确确定指令边界：标记指令开头（instrValid）和末尾（instrEndVec）
  - 判断指令类型：区分16位RVC指令和32位RVI指令
  - 时序优化：采用并行推断策略，优化关键路径时序
  - 支持跨预测块拼接：处理第一个预测块末尾为半条RVI指令的情况

## 术语与缩写
| 缩写 | 全称 | 说明 |
| ---- | ---- | ---- |
| RVC | RISC-V Compressed | RISC-V压缩指令（16位） |
| RVI | RISC-V Integer | RISC-V整数指令（32位） |
| instrValid | Instruction Valid | 指令有效向量，标记指令开头 |
| instrEndVec | Instruction End Vector | 指令结束向量，标记指令末尾 |
| FetchBlock | Fetch Block | 预测块，最大64字节 |

## RTL源文件

对涉及文件进行简要说明。

文件列表：
- `bosc_IFU/chisel/InstrBoundary.scala` InstrBoundary模块主文件
  - `class InstrBoundary` - 指令定界模块主类
  - `class InstrBoundaryIO` - 指令定界模块接口
  - `class InstrBoundaryReq` - 请求Bundle
  - `class InstrBoundaryResp` - 响应Bundle

## 顶层接口概览
- **模块名称**：`InstrBoundary`

- **端口列表**：

  | 信号名 | 方向 | 位宽/类型 | 复位值 | 描述 |
  | ------ | ---- | -------- | ------ | ---- |
  | req.valid | Input | Bool | - | 请求有效信号 |
  | req.instrRange | Input | Vec(FetchBlockInstNum, Bool) | - | 指令范围，初步缩减有效范围 |
  | req.maybeRvc | Input | Vec(FetchBlockInstNum, Bool) | - | 可能是RVC指令的标记 |
  | req.firstInstrIsHalfRvi | Input | Bool | - | 第一条指令是否是半条RVI指令 |
  | req.firstFetchBlockEndPos | Input | UInt(log2Ceil(FetchBlockInstNum).W) | - | 第一个预测块的结束位置 |
  | req.endPos | Input | UInt(log2Ceil(FetchBlockInstNum).W) | - | 整体结束位置 |
  | resp.instrValid | Output | Vec(FetchBlockInstNum, Bool) | - | 指令有效向量（指令开头） |
  | resp.instrEndVec | Output | Vec(FetchBlockInstNum, Bool) | - | 指令结束向量 |
  | resp.isRvc | Output | Vec(FetchBlockInstNum, Bool) | - | 是否为RVC指令 |
  | resp.firstFetchBlockLastInstrIsHalfRvi | Output | Bool | - | 第一个预测块最后一条指令是否为半条RVI |
  | resp.lastInstrIsHalfRvi | Output | Bool | - | 最后一条指令是否为半条RVI |

- **时钟与复位要求**：
  - 组合逻辑电路，无时钟和复位
  - 输入到输出的延迟为1个周期

- **外部依赖**：
  - 无直接外部依赖
  - 输入信号来自IFU S1级流水线寄存器

## 功能描述

### 指令定界算法

- **概述**：通过标记指令的开头和末尾确定指令边界。由于RVC指令是16位，RVI指令是32位，需要根据前一条指令的类型来确定当前指令的位置。

- **执行流程**：
  1. **前半部分定界**（0~15号位置）：
     - 直接根据firstInstrIsHalfRvi和maybeRvc计算
     - 对于位置0，如果是第一条指令且不是半条RVI，则有效
     - 对于位置i（i>0），如果位置i-1不是指令开头或者位置i-1是RVC指令，则位置i是指令开头

  2. **后半部分定界**（16~31号位置）：
     - 采用两路假设并行计算：
       * 假设1：位置15是RVC指令（firstFetchBlockLastInstrIsHalfRvi = false）
       * 假设2：位置15是RVI指令（firstFetchBlockLastInstrIsHalfRvi = true）
     - 根据位置15的实际类型（boundary(15) && !isRvc(15)）选择正确的假设

  3. **合并结果**：
     - 根据位置15是否为指令开头以及是否为RVC指令，选择latterHalfBoundary1或latterHalfBoundary2

- **边界与异常**：
  - **跨预测块边界**：
    - 如果第一个预测块末尾是半条RVI指令，下一个预测块的第一条指令会自动成为指令开头
    - 通过firstInstrIsHalfRvi参数处理这种情况

  - **指令范围限制**：
    - instrRange信号用于初步缩减指令块的有效范围
    - 指令可能由两个预测块拼接而成

- **性能与约束**：
  - **关键路径**：从前半部分最后一条指令的类型判断到后半部分第一路的定界逻辑
  - **并行计算**：后半部分的两路假设完全并行，减少关键路径延迟
  - **时序优化**：通过多路推断再合并拼接的策略，优化时序紧张问题

### 输出信号生成

- **instrValid生成**：
  ```
  instrValid(i) = boundary(i) && instrRange(i)
  ```
  - boundary(i)：位置i是否为指令开头
  - instrRange(i)：位置i是否在指令范围内

- **instrEndVec生成**：
  ```
  instrEndVec(i) = (!boundary(i) || (boundary(i) && isRvc(i))) && instrRange(i)
  ```
  - 对于RVC指令：指令开头即为指令末尾（16位）
  - 对于RVI指令：指令末尾是下一个位置

- **isRvc生成**：
  ```
  isRvc(i) = boundary(i) && isRvc(i) && instrRange(i)
  ```
  - 只有当位置i是指令开头且为RVC指令时，才标记为RVC

- **特殊标记**：
  - firstFetchBlockLastInstrIsHalfRvi：boundary(firstFetchBlockEndPos) && !isRvc(firstFetchBlockEndPos)
  - lastInstrIsHalfRvi：boundary(endPos) && !isRvc(endPos)

### 状态机与时序
- **状态机列表**：无（纯组合逻辑）

- **关键时序**：
  - 输入到输出延迟：约1个周期（取决于布局布线）
  - 前半部分定界：0~15号位置，并行计算
  - 后半部分定界：16~31号位置，两路并行，然后选择

### 复位与错误处理
- **复位行为**：无（纯组合逻辑）

- **错误上报**：
  - **差分测试检查**：使用boundDiff进行差分测试
    - 生成完整的边界序列（不采用并行优化）
    - 与优化后的边界结果比较
    - 如果不一致，报告XSError

- **错误检测**：
  ```
  XSError(io.req.valid && (a =/= b), p"boundary different: $a vs $b\n")
  ```

## 验证需求与覆盖建议
- **功能覆盖点**：
  - 正常情况：纯RVC指令序列
  - 正常情况：纯RVI指令序列
  - 正常情况：RVC和RVI混合序列
  - 边界情况：第一个预测块末尾为半条RVI
  - 边界情况：两个预测块都存在半条RVI
  - 边界情况：指令范围小于32条
  - 边界情况：指令范围等于32条

- **约束与假设**：
  - 预测块大小：64字节（32个16位位置）
  - C扩展必须支持（HasCExtension = true）
  - maybeRvc信号准确性依赖于上游

- **测试接口**：
  - 输入：各种指令序列组合
  - 监视点：boundary、instrValid、instrEndVec、isRvc
  - 参考模型：简单的顺序定界算法

## 潜在 bug 分析

### 跨预测块双半条指令处理未明确（置信度 70%）
- **触发条件**：第一个预测块末尾为半条RVI指令，第二个预测块末尾也为半条RVI指令
- **影响范围**：可能导致第二个预测块的指令定界错误
- **关联位置**：InstrBoundary.scala:69-79，后半部分定界逻辑
- **验证建议**：
  1. 补充测试用例，覆盖两个预测块都存在半条指令的情况
  2. 验证boundary(15)对后半部分定界的影响
  3. 确认firstInstrIsHalfRvi在下一拍的正确传递

### maybeRvc信号准确性依赖（置信度 50%）
- **触发条件**：上游ICache提供的maybeRvc信号不准确
- **影响范围**：导致指令类型判断错误，影响指令定界
- **关联位置**：InstrBoundary.scala:46，isRvc = io.req.maybeRvc
- **验证建议**：
  1. 验证maybeRvc信号的来源和准确性
  2. 测试maybeRvc信号错误的边界情况
  3. 考虑添加maybeRvc信号的合理性检查

### 并行优化逻辑等价性（置信度 30%）
- **触发条件**：两路假设的逻辑与简单顺序计算结果不一致
- **影响范围**：导致指令定界错误
- **关联位置**：InstrBoundary.scala:69-79，latterHalfBoundary计算
- **验证建议**：
  1. 依赖现有的XSError差分测试
  2. 增加随机测试用例，覆盖各种指令组合
  3. 验证选择逻辑的正确性
