# PreDecoder 规格说明文档

> 本文档用于指导编写 `PreDecoder` 子模块的规格说明书。请按照每个小节的提示补充内容，保持技术语言准确、条理清晰、便于验证复用。若某项内容不存在，请显式写明"无"或"暂缺"，不要删除章节。

## 简介
- **设计背景**：`PreDecoder`（预译码模块）是IFU中负责对有效指令码进行预译码的子模块。预译码的目的是在指令送入后端之前，提前获取指令的关键信息，特别是控制流指令（CFI）的类型、分支类型、跳转偏移量等，用于后续的预测检查和分支预测。

  预译码模块还包含RvcExpander子模块，用于将16位的RVC指令扩展为32位的RVI指令，从而简化后续模块的处理逻辑。

- **版本信息**：规格版本 V3，基于文档 AS-IFU-V3.md 和源代码 PreDecode.scala

- **设计目标**：
  - 预译码信息生成：CFI指令类型、分支属性、RVC标记
  - 跳转偏移量计算：jal指令和br指令的jumpOffset
  - RVC指令扩展：将C指令转换为I指令
  - 时序优化：在S2级完成预译码，不增加额外周期

## 术语与缩写
| 缩写 | 全称 | 说明 |
| ---- | ---- | ---- |
| RVC | RISC-V Compressed | RISC-V压缩指令（16位） |
| RVI | RISC-V Integer | RISC-V整数指令（32位） |
| CFI | Control Flow Instruction | 控制流指令（分支、跳转等） |
| jal | Jump and Link | 直接跳转并链接指令 |
| jalr | Jump and Link Register | 间接跳转并链接指令 |
| br | Branch | 条件分支指令 |
| Call | Call Function | 函数调用指令 |
| Ret | Return | 函数返回指令 |
| jumpOffset | Jump Offset | 跳转偏移量（有符号立即数） |

## RTL源文件

对涉及文件进行简要说明。

文件列表：
- `bosc_IFU/chisel/PreDecode.scala` PreDecoder模块主文件
  - `class PreDecoder` - 预译码模块主类
  - `class PreDecodeIO` - 预译码模块接口
  - `class PreDecodeReq` - 请求Bundle
  - `class PreDecodeResp` - 响应Bundle

- `bosc_IFU/chisel/RvcExpander.scala` RVC扩展子模块
  - `class RvcExpander` - RVC指令扩展模块
  - 使用RocketChip的RVCDecoder进行解码

- `bosc_IFU/chisel/Helpers.scala` 辅助工具
  - `trait PreDecodeHelper` - 预译码辅助trait
  - `def isRVC(inst: UInt)` - 判断是否为RVC指令
  - `def getJalOffset(inst: UInt, isRvc: Bool)` - 获取jal指令偏移量
  - `def getBrOffset(inst: UInt, isRvc: Bool)` - 获取br指令偏移量

## 顶层接口概览
- **模块名称**：`PreDecoder`

- **端口列表**：

  | 信号名 | 方向 | 位宽/类型 | 复位值 | 描述 |
  | ------ | ---- | -------- | ------ | ---- |
  | req.valid | Input | Bool | - | 请求有效信号 |
  | req.bits.data | Input | Vec(IBufferEnqueueWidth, UInt(32.W)) | - | 指令数据（32位） |
  | req.bits.isRvc | Input | Vec(IBufferEnqueueWidth, Bool) | - | 是否为RVC指令标记 |
  | req.bits.instrValid | Input | Vec(IBufferEnqueueWidth, Bool) | - | 指令有效向量 |
  | resp.pd | Output | Vec(IBufferEnqueueWidth, PreDecodeInfo) | - | 预译码信息 |
  | resp.instr | Output | Vec(IBufferEnqueueWidth, UInt(32.W)) | - | 指令数据（透传） |
  | resp.jumpOffset | Output | Vec(IBufferEnqueueWidth, PrunedAddr(VAddrBits)) | - | 跳转偏移量 |

- **时钟与复位要求**：
  - 组合逻辑电路，无时钟和复位
  - 输入到输出的延迟为1个周期

- **外部依赖**：
  - 输入指令数据来自IFU S2级流水线寄存器
  - 输出预译码信息给PredChecker模块
  - 输出jumpOffset用于后续的预测检查

## 功能描述

### 预译码信息生成

- **概述**：对每条有效指令进行预译码，生成预译码信息（PreDecodeInfo），包括指令类型、分支属性、RVC标记等。

- **执行流程**：
  1. **指令有效性检查**：
     - 只对instrValid(i)为true的指令进行预译码
     - pd.valid := io.req.bits.instrValid(i)

  2. **RVC标记传递**：
     - 直接透传isRvc信号
     - pd.isRVC := io.req.bits.isRvc(i)

  3. **分支属性解码**：
     - 使用BranchAttribute.decode()解码指令
     - 生成分支类型、RAS动作等信息
     - pd.brAttribute := BranchAttribute.decode(inst, io.req.valid)
     - 用于差分测试目的

  4. **指令数据透传**：
     - 直接透传指令数据，不做修改
     - resp.instr(i) := inst

- **边界与异常**：
  - **非法指令处理**：
    - PreDecoder模块本身不处理非法指令
    - 非法RVC指令由RvcExpander子模块处理
    - 输出ill标记供后续模块使用

  - **指令长度假设**：
    - 假设所有指令都是32位（UInt(32.W)）
    - RVC指令通过isRvc标记区分
    - RVC扩展在后续的RvcExpander模块中完成

- **性能与约束**：
  - **并行处理**：IBufferEnqueueWidth条指令并行预译码
  - **关键路径**：BranchAttribute.decode()逻辑
  - **时序优化**：预译码信息简化，只包含必要信息

### 跳转偏移量计算

- **概述**：计算jal指令和br指令的跳转偏移量（jumpOffset），用于后续的目的地址计算和预测检查。

- **执行流程**：
  1. **jal指令偏移量计算**（getJalOffset）：
     ```
     RVC jal偏移格式：inst(12), inst(8), inst(10,9), inst(6), inst(7), inst(2), inst(11), inst(5,3), 0
     RVI jal偏移格式：inst(31), inst(19,12), inst(20), inst(30,21), 0
     ```
     - 根据isRvc选择RVC或RVI格式
     - 符号扩展到VAddrBits位
     - 返回PrunedAddr类型

  2. **br指令偏移量计算**（getBrOffset）：
     ```
     RVC br偏移格式：inst(12), inst(6,5), inst(2), inst(11,10), inst(4,3), 0
     RVI br偏移格式：inst(31), inst(7), inst(30,25), inst(11,8), 0
     ```
     - 根据isRvc选择RVC或RVI格式
     - 符号扩展到VAddrBits位
     - 返回PrunedAddr类型

  3. **偏移量选择**：
     ```
     jumpOffset(i) := Mux(io.resp.pd(i).isBr, brOffset, jalOffset)
     ```
     - 如果是分支指令，使用brOffset
     - 否则使用jalOffset（包括jal指令）

- **边界与异常**：
  - **非控制流指令**：
    - 对于非控制流指令，也会计算jumpOffset
    - 但这个值在后续逻辑中不会被使用

  - **符号扩展**：
    - 所有偏移量都进行符号扩展
    - 确保正确处理负偏移情况

- **性能与约束**：
  - **并行计算**：IBufferEnqueueWidth条指令的偏移量并行计算
  - **关键路径**：偏移量提取和符号扩展逻辑
  - **资源优化**：jalOffset和brOffset都计算，通过Mux选择

### PreDecodeInfo结构

PreDecodeInfo是预译码信息的Bundle，包含以下字段：

- **valid**：Bool - 指令是否有效
- **isRVC**：Bool - 是否为RVC指令
- **isJal**：Bool - 是否为jal指令
- **isJalr**：Bool - 是否为jalr指令
- **isBr**：Bool - 是否为分支指令
- **isCall**：Bool - 是否为函数调用指令
- **isRet**：Bool - 是否为函数返回指令
- **notCFI**：Bool - 是否为非控制流指令
- **brAttribute**：BranchAttribute - 分支属性详细信息

### 状态机与时序
- **状态机列表**：无（纯组合逻辑）

- **关键时序**：
  - 输入到输出延迟：约1个周期
  - 预译码和偏移量计算并行进行

### 复位与错误处理
- **复位行为**：无（纯组合逻辑）

- **错误上报**：
  - **非法指令检测**：在RvcExpander子模块中完成
  - **调试输出**：使用XSDebug打印预译码信息
    - 指令十六进制
    - isRVC标记
    - branchType
    - rasAction

## 子模块描述

### RvcExpander子模块

负责将RVC指令扩展为RVI指令。

**具体请参考文档**：`bosc_IFU_spec_RvcExpander.md`（待创建）

**主要功能**：
- 使用RocketChip的RVCDecoder进行解码
- 检查RVC指令合法性，输出ill标记
- 非法C指令保持原数据
- 有效C指令输出扩展后的32位指令

## 验证需求与覆盖建议
- **功能覆盖点**：
  - RVC指令预译码
  - RVI指令预译码
  - jal指令偏移量计算（RVC和RVI）
  - br指令偏移量计算（RVC和RVI）
  - 非控制流指令预译码
  - Call指令识别
  - Ret指令识别
  - 非法指令处理

- **约束与假设**：
  - 指令数据宽度：32位
  - 并行处理宽度：IBufferEnqueueWidth
  - C扩展必须支持（HasCExtension = true）

- **测试接口**：
  - 输入：各种指令类型组合
  - 监视点：pd、jumpOffset
  - 参考模型：RISC-V指令集规范

## 潜在 bug 分析

### 跳转偏移量计算未覆盖所有指令（置信度 40%）
- **触发条件**：非控制流指令的jumpOffset被使用
- **影响范围**：可能导致错误的地址计算
- **关联位置**：PreDecode.scala:60，jumpOffset选择逻辑
- **验证建议**：
  1. 确认后续逻辑对非控制流指令jumpOffset的处理
  2. 考虑只为控制流指令计算jumpOffset以优化资源
  3. 验证Mux选择逻辑的正确性

### BranchAttribute.decode准确性（置信度 30%）
- **触发条件**：指令解码错误或分支属性识别错误
- **影响范围**：影响后续的预测检查和分支预测
- **关联位置**：PreDecode.scala:57，BranchAttribute.decode()
- **验证建议**：
  1. 对比RISC-V指令集规范，验证解码逻辑
  2. 测试所有控制流指令类型
  3. 验证Call和Ret指令的识别准确性

### RVC标记依赖上游准确性（置信度 30%）
- **触发条件**：上游提供的isRvc标记不准确
- **影响范围**：导致偏移量计算错误
- **关联位置**：PreDecode.scala:50-51，getJalOffset和getBrOffset的isRvc参数
- **验证建议**：
  1. 验证isRvc信号的来源和准确性
  2. 测试isRvc标记错误的边界情况
  3. 考虑添加isRvc信号的合理性检查
