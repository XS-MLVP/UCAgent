# PredChecker 规格说明文档

> 本文档用于指导编写 `PredChecker` 子模块的规格说明书。PredChecker是IFU中负责预译码检查和预测纠正的关键模块，采用两级流水线结构。请按照每个小节的提示补充内容，保持技术语言准确、条理清晰、便于验证复用。

## 简介
- **设计背景**：`PredChecker`（预译码检查模块）是IFU中负责检查预测错误并及时纠正的子模块。越早发现预测错误，就能越早将指令流纠正回正确路径，从而提升处理器性能。

  PredChecker采用两级流水线结构：
  - **Stage 1**：检测remask fault（需要重新掩码的错误），调整预测块范围
  - **Stage 2**：准备重定向信息，为FTQ写回做准备

- **版本信息**：规格版本 V3，基于文档 AS-IFU-V3.md 和源代码 PredChecker.scala

- **设计目标**：
  - 预测方向检查：检测jal/jalr/ret指令的预测错误
  - 目的地址检查：检测分支指令的目标地址预测错误
  - 及时纠正：通过裁剪预测块大小或发送重定向来纠正错误
  - 性能优化：尽量减少对流水线的影响

## 术语与缩写
| 缩写 | 全称 | 说明 |
| ---- | ---- | ---- |
| remask | Remask | 重新掩码，调整预测块有效范围 |
| jalFault | JAL Fault | jal指令一定跳转但预测不跳转的错误 |
| jalrFault | JALR Fault | jalr指令一定跳转但预测不跳转的错误 |
| retFault | Ret Fault | ret指令一定跳转但预测不跳转的错误 |
| notCfiFault | Not CFI Fault | 非控制流指令预测跳转的错误 |
| invalidTaken | Invalid Taken | 非法跳转（预测跳转但指令末尾不在边界内） |
| targetFault | Target Fault | 目标地址预测错误 |
| misIdx | Misprediction Index | 预测错误的指令索引 |

## RTL源文件

对涉及文件进行简要说明。

文件列表：
- `bosc_IFU/chisel/PredChecker.scala` PredChecker模块主文件
  - `class PredChecker` - 预译码检查模块主类
  - `class PredCheckerIO` - 预译码检查模块接口
  - `class PredCheckerReq` - 请求Bundle
  - `class PredCheckerResp` - 响应Bundle（包含S1Out和S2Out）

- `bosc_IFU/chisel/Bundles.scala` 相关数据结构定义
  - `PreDecodeFaultType` - 预译码错误类型枚举
  - `PredCheckRedirect` - 预译码检查重定向信息

## 顶层接口概览
- **模块名称**：`PredChecker`

- **端口列表**：

  | 信号名 | 方向 | 位宽/类型 | 复位值 | 描述 |
  | ------ | ---- | -------- | ------ | ---- |
  | req.valid | Input | Bool | - | 请求有效信号 |
  | req.bits.instrJumpOffset | Input | Vec(..., PrunedAddr) | - | 指令跳转偏移量 |
  | req.bits.instrValid | Input | Vec(..., Bool) | - | 指令有效向量 |
  | req.bits.instrPds | Input | Vec(..., PreDecodeInfo) | - | 预译码信息 |
  | req.bits.instrPc | Input | Vec(..., PrunedAddr) | - | 指令PC |
  | req.bits.isPredTaken | Input | Vec(..., Bool) | - | 是否预测跳转 |
  | req.bits.ignore | Input | Vec(IfuAlignWidth, Bool) | - | 忽略标记（offset调整导致） |
  | req.bits.shiftNum | Input | UInt(log2Ceil(IfuAlignWidth).W) | - | 移位数（IBuffer对齐） |
  | req.bits.firstPredTakenIdx | Input | Valid(UInt) | - | 第一个预测跳转索引 |
  | req.bits.secondPredTakenIdx | Input | Valid(UInt) | - | 第二个预测跳转索引 |
  | req.bits.firstTarget | Input | PrunedAddr | - | 第一个目标地址 |
  | req.bits.secondTarget | Input | PrunedAddr | - | 第二个目标地址 |
  | req.bits.selectFetchBlock | Input | Vec(..., Bool) | - | 选择哪个fetch块 |
  | req.bits.invalidTaken | Input | Vec(..., Bool) | - | 非法跳转标记 |
  | req.bits.instrEndOffset | Input | Vec(..., UInt) | - | 指令结束偏移 |
  | resp.stage1Out.fixedTwoFetchRange | Output | Vec(..., Bool) | - | 固定后的two fetch范围 |
  | resp.stage1Out.fixedTwoFetchTaken | Output | Vec(..., Bool) | - | 固定后的two fetch跳转 |
  | resp.stage2Out.checkerRedirect | Output | Valid(PredCheckRedirect) | - | 检查器重定向信息 |
  | resp.stage2Out.perfFaultType | Output | Vec(FetchPorts, UInt) | - | 性能错误类型 |

- **时钟与复位要求**：
  - 两级流水线（Stage 1 和 Stage 2）
  - Stage 1：组合逻辑
  - Stage 2：包含一级寄存器（RegEnable、RegNext）

- **外部依赖**：
  - 输入来自IFU S3级流水线
  - 输出stage1Out给IFU S3级IBuffer入队逻辑
  - 输出stage2Out给IFU WB阶段FTQ写回

## 功能描述

### Stage 1：检测Remask Fault

- **概述**：检测需要重新掩码的错误（remask fault），并根据检测结果调整预测块的有效范围。remask fault是指那些可以通过调整预测块范围来纠正的预测错误。

- **执行流程**：
  1. **jalFault检测**：
     ```
     jalFaultVec(i) = pd.brAttribute.isDirect && instrValid(i) && !isPredTaken(i) && !ignore(i)
     ```
     - jal/jalr指令：一定跳转（isDirect = true）
     - 但预测不跳转（!isPredTaken）
     - 触发条件：预测方向错误

  2. **jalrFault检测**：
     ```
     jalrFaultVec(i) = pd.brAttribute.isIndirect && !pd.brAttribute.hasPop && instrValid(i) && !isPredTaken(i) && !ignore(i)
     ```
     - jalr指令（非ret）：一定跳转（isIndirect = true）
     - 但预测不跳转
     - 排除ret指令（hasPop）

  3. **retFault检测**：
     ```
     retFaultVec(i) = pd.brAttribute.hasPop && instrValid(i) && !isPredTaken(i) && !ignore(i)
     ```
     - ret指令：一定跳转（hasPop = true）
     - 但预测不跳转

  4. **notCfiTaken检测**：
     ```
     notCfiTaken(i) = instrValid(i) && pd.notCFI && isPredTaken(i) && !ignore(i)
     ```
     - 非控制流指令（notCFI = true）
     - 但预测跳转
     - 触发条件：预测方向错误

  5. **invalidTaken**：
     - 来自输入，标记非法跳转（预测跳转但指令末尾不在边界内）

  6. **计算remaskFault**：
     ```
     remaskFault(i) = jalFaultVec(i) || jalrFaultVec(i) || retFaultVec(i) || invalidTaken(i) || notCfiTaken(i)
     ```
     - 所有需要重新掩码的错误

  7. **调整预测块范围**：
     - 如果没有remask fault，保持原范围
     - 如果有remask fault，调整范围：只保留remaskIdx之前的指令
     ```
     fixedRange = instrValid & (Fill(IBufferEnqueueWidth, !needRemask) | (Fill(pow(2, log2Up(IBufferEnqueueWidth)), 1.U(1.W)) >> (~remaskIdx).asUInt).asUInt)
     ```

  8. **fixedTwoFetchTaken计算**：
     - 第一个预测块：fixedTwoFetchFirstTaken
     - 第二个预测块：fixedTwoFetchSecondTaken
     - 合并：fixedTwoFetchTaken = fixedTwoFetchFirstTaken || fixedTwoFetchSecondTaken

- **边界与异常**：
  - **ignore标记**：
    - 由offset调整导致的无效条目
    - 这些条目不参与错误检测

  - **多个错误**：
    - 可能同时存在多个remask fault
    - 只处理第一个（优先编码器）
    - 使用ParallelPriorityEncoder选择第一个错误

- **性能与约束**：
  - **关键路径**：错误检测逻辑 → 优先编码器 → 范围调整
  - **并行检测**：IBufferEnqueueWidth条指令并行检测
  - **资源优化**：使用ParallelOR和ParallelPriorityEncoder优化

### Stage 2：准备重定向信息

- **概述**：基于Stage 1的检测结果，准备详细的重定向信息，用于FTQ写回。

- **执行流程**：
  1. **寄存Stage 1结果**：
     - mispredIdx：预测错误索引
     - finalIsRVC：是否为RVC指令
     - finalAttribute：分支属性
     - invalidTaken：非法跳转标记
     - finalSelectBlock：选择哪个fetch块
     - finalPc：指令PC
     - jumpTargets：跳转目标地址（PC + jumpOffset）
     - seqTargets：顺序执行目标地址（PC + 2或4）
     - fixedIsJump：是否为跳转指令
     - endOffset：指令结束偏移

  2. **计算fixedTaken**：
     ```
     fixedTaken = !invalidTaken && Mux(finalSelectBlock, finalFirstTakenNext, finalSecondTakenNext)
     ```
     - 非法跳转不触发
     - 根据selectBlock选择第一个或第二个预测块的跳转

  3. **计算fixedTarget**：
     ```
     fixedTarget = Mux(fixedIsJump && !invalidTaken, jumpTargets(mispredIdx), seqTargets(mispredIdx))
     ```
     - 如果是跳转指令且非非法跳转，使用jumpTargets
     - 否则使用seqTargets（顺序执行）

  4. **准备checkerRedirect**：
     - valid：mispredIdx.valid && wbValid
     - target：fixedTarget
     - misIdx：mispredIdx
     - taken：fixedTaken
     - isRVC：finalIsRVC
     - attribute：Mux(invalidTaken, BranchAttribute.None, finalAttribute)
     - selectBlock：finalSelectBlock
     - invalidTaken：invalidTaken
     - mispredPc：finalPc
     - endOffset：endOffset

  5. **确定perfFaultType**：
     ```
     faultType = MuxCase(PreDecodeFaultType.NoFault, Seq(
       jalFaultVecNext(mispredIdx) -> PreDecodeFaultType.JalFault,
       jalrFaultVecNext(mispredIdx) -> PreDecodeFaultType.JalrFault,
       retFaultVecNext(mispredIdx) -> PreDecodeFaultType.RetFault,
       notCFITakenNext(mispredIdx) -> PreDecodeFaultType.NotCfiFault,
       targetFaultVecNext(mispredIdx) -> PreDecodeFaultType.TargetFault,
       invalidTakenNext(mispredIdx) -> PreDecodeFaultType.InvalidTaken
     ))
     ```
     - 根据错误类型设置perfFaultType
     - 用于性能统计和调试

- **边界与异常**：
  - **wbValid控制**：
    - 只有当wbValid为true时，才输出有效的checkerRedirect
    - wbValid = RegNext(io.req.valid, init = false.B)

  - **无效指令处理**：
    - 如果invalidTaken为true，attribute设置为BranchAttribute.None

- **性能与约束**：
  - **流水线延迟**：Stage 2增加1个周期延迟
  - **关键路径**：fixedTarget计算
  - **资源优化**：使用寄存器缓存Stage 1结果，减少组合逻辑深度

### 目的地址检查（targetFault）

- **概述**：检查分支指令的目标地址预测是否正确。

- **执行流程**：
  1. **计算实际目标地址**：
     ```
     actualTarget = pc(i) + jumpOffset(i)
     ```

  2. **与预测目标比较**：
     - 第一个预测块：actualTarget vs firstPredTarget
     - 第二个预测块：actualTarget vs secondPredTarget

  3. **targetFault检测**：
     ```
     targetFaultVec(i) = pd.brAttribute.isDirect && instrValid(i) && isPredTaken(i) && !ignore(i) &&
       ((firstPredTaken && (i.U === firstTakenIdx) && (firstPredTarget =/= actualTarget)) ||
        (secondPredTaken && (i.U === secondTakenIdx) && (secondPredTarget =/= actualTarget)))
     ```
     - 只检查直接跳转指令（jal、br）
     - 只检查预测跳转的指令
     - 目标地址不匹配时触发

- **边界与异常**：
  - **不纠正目的地址**：
    - 文档说明：对于目的地址错误，不修正，相信预测器
    - 只有在发现预测块范围错误时，才提供计算出的目的地址
    - 这是性能和成本的折中

  - **targetFault检测时机**：
    - 在Stage 1检测targetFault
    - 但不用于调整fixedRange
    - 只用于perfFaultType统计

- **性能与约束**：
  - **实现复杂度**：目的地址比较逻辑较长
  - **时序影响**：可能需要打一拍（文档提到待优化）

### 状态机与时序
- **状态机列表**：无（纯数据通路，两级流水线）

- **关键时序**：
  - **Stage 1**：
    - 输入：req.valid、req.bits.*
    - 输出：stage1Out.fixedTwoFetchRange、stage1Out.fixedTwoFetchTaken
    - 延迟：组合逻辑

  - **Stage 2**：
    - 输入：Stage 1的寄存结果
    - 输出：stage2Out.checkerRedirect、stage2Out.perfFaultType
    - 延迟：1个周期（包含寄存器）

  - **流水线关系**：
    - Stage 1输出用于IFU S3级IBuffer入队（same cycle）
    - Stage 2输出用于IFU WB阶段FTQ写回（next cycle）

### 复位与错误处理
- **复位行为**：
  - 使用RegEnable和RegNext，复位时值为初始值
  - wbValid初始值为false.B

- **错误上报**：
  - **perfFaultType**：输出预译码错误类型，用于性能统计
  - **7种错误类型**：
    1. NoFault：无错误
    2. JalFault：jal指令预测错误
    3. JalrFault：jalr指令预测错误
    4. RetFault：ret指令预测错误
    5. NotCfiFault：非控制流指令预测跳转
    6. InvalidTaken：非法跳转
    7. TargetFault：目的地址预测错误

## 验证需求与覆盖建议
- **功能覆盖点**：
  - **预测方向检查**：
    * jal指令预测不跳转
    * jalr指令预测不跳转
    * ret指令预测不跳转
    * 非控制流指令预测跳转
    * 非法跳转

  - **目的地址检查**：
    * jal指令目的地址错误
    * br指令目的地址错误
    * 第一个预测块目的地址错误
    * 第二个预测块目的地址错误

  - **边界情况**：
    * 多个预测错误同时发生
    * ignore标记的影响
    * invalidTaken的影响
    * IBuffer对齐的影响

  - **性能统计**：
    * 各种错误类型的计数
    * 预测准确率统计

- **约束与假设**：
  - 预测器预测可能不准确
  - 目的地址检查不纠正预测，只统计
  - 第一个错误优先处理（优先编码器）

- **测试接口**：
  - 输入：各种预测错误场景
  - 监视点：fixedTwoFetchRange、fixedTwoFetchTaken、checkerRedirect
  - 参考模型：基于指令集规范的预测检查

## 潜在 bug 分析

### 目的地址检查未实现纠正（置信度 50%）
- **触发条件**：jal指令、br指令的目的地址预测错误
- **影响范围**：虽然不纠正目的地址，但可能存在性能损失
- **关联位置**：PredChecker.scala:118-127，targetFaultVec检测
- **验证建议**：
  1. 评估目的地址检查的时序影响
  2. 如果需要实现，补充目的地址纠正逻辑
  3. 验证PC+Offset计算的准确性

### 2-taken支持的问题（置信度 50%）
- **触发条件**：使用2-taken功能
- **影响范围**：InstrCompact.scala注释提到"This is wrong when 2-taken is enabled"
- **关联位置**：InstrCompact.scala:58，instrOffset计算
- **验证建议**：
  1. 测试2-taken场景下的PredChecker行为
  2. 验证fixedTwoFetchTaken的正确性
  3. 检查是否需要修复InstrCompact的问题

### 优先编码器选择逻辑（置信度 30%）
- **触发条件**：多个错误同时发生
- **影响范围**：只处理第一个错误，其他错误可能被忽略
- **关联位置**：PredChecker.scala:133-134，remaskIdx计算
- **验证建议**：
  1. 验证ParallelPriorityEncoder的正确性
  2. 测试多个错误的优先级
  3. 确认是否需要处理所有错误

### Stage 2 wbValid时序（置信度 30%）
- **触发条件**：wbValid与req.valid的时序不匹配
- **影响范围**：可能导致checkerRedirect输出错误
- **关联位置**：PredChecker.scala:217，wbValid = RegNext(io.req.valid)
- **验证建议**：
  1. 验证wbValid时序的正确性
  2. 检查流水线暂停和冲刷的影响
  3. 确认Stage 2寄存器更新的时序

### endOffset标记的可靠性（置信度 20%）
- **触发条件**：代码注释"Not a reliable block-end marker"
- **影响范围**：可能在特殊情况下（invalidTaken）无法正确标记块结束
- **关联位置**：PredChecker.scala:232，endOffset赋值
- **验证建议**：
  1. 测试invalidTaken场景下的endOffset
  2. 验证块结束标记的正确性
  3. 考虑使用更可靠的块结束标记方法
