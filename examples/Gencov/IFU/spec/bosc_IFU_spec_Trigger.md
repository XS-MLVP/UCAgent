# FrontendTrigger 规格说明文档

> 本文档用于指导编写 `FrontendTrigger` 子模块的规格说明书。FrontendTrigger是IFU中负责调试模式下触发器设置的子模块，配合后端Trigger模块实现断点调试功能。

## 简介
- **设计背景**：`FrontendTrigger`（前端触发器模块）是IFU中负责调试模式下触发器设置的子模块。触发器可以用于本地调试，即不依赖外部调试器（JTAG），而是通过异常机制来进行调试。

  触发器通常由用户态或监督态设置，但也支持机器态进行设置（M模式下，开发人员必须清晰的知道自己在干什么）。触发器仅在机器模式和调试模式下可设置。

  当同时分别触发进入调试模式和断点异常时，优先保证进入调试模式的发生。推荐是进入调试模式和生成断点异常都要发生。

- **版本信息**：规格版本 V3，基于文档 AS-IFU-V3.md 和源代码 FrontendTrigger.scala

- **设计目标**：
  - PC匹配：支持基于PC的触发器匹配
  - 触发控制：支持timing、chain、action等触发控制
  - 多触发器：支持4个tdata寄存器
  - 调试模式：仅在非debug模式下工作
  - 预留扩展：预译码和指令数据使用待补充

## 术语与缩写
| 缩写 | 全称 | 说明 |
| ---- | ---- | ---- |
| tdata | Trigger Data | 触发器数据寄存器 |
| matchType | Match Type | 匹配类型 |
| timing | Timing | 触发时机 |
| chain | Chain | 链式匹配 |
| action | Action | 触发动作 |
| debugMode | Debug Mode | 调试模式 |
| TriggerAction | Trigger Action | 触发动作类型 |

## RTL源文件

对涉及文件进行简要说明。

文件列表：
- `bosc_IFU/chisel/FrontendTrigger.scala` FrontendTrigger模块主文件
  - `class FrontendTrigger` - 前端触发器模块主类
  - `class FrontendTriggerIO` - 前端触发器模块接口

- 相关trait和工具：
  - `trait SdtrigExt` - Sdtrig扩展trait，包含Trigger相关的工具函数
  - `TriggerCmpConsecutive` - 触发器比较函数
  - `TriggerCheckCanFire` - 触发器可触发检查函数
  - `TriggerUtil.triggerActionGen` - 触发器动作生成函数

## 顶层接口概览
- **模块名称**：`FrontendTrigger`

- **端口列表**：

  | 信号名 | 方向 | 位宽/类型 | 复位值 | 描述 |
  | ------ | ---- | -------- | ------ | ---- |
  | frontendTrigger | Input | FrontendTdataDistributeIO | - | 前端触发器配置接口 |
  | pds | Input | Vec(IBufferEnqueueWidth, PreDecodeInfo) | - | 预译码信息（预留，当前未使用） |
  | pc | Input | Vec(IBufferEnqueueWidth, PrunedAddr(VAddrBits)) | - | 指令PC |
  | data | Input | Vec(IBufferEnqueueWidth+1, UInt(16.W)) | - | 指令数据（预留，当前为0） |
  | triggered | Output | Vec(IBufferEnqueueWidth, TriggerAction()) | - | 触发动作输出 |

- **时钟与复位要求**：
  - 单时钟域
  - 复位信号：系统复位

- **外部依赖**：
  - 后端Trigger模块：提供tdata寄存器配置
  - 调试模式：控制触发器是否工作
  - IBuffer：接收triggered信号

## 功能描述

### 触发器数据寄存器（tdata）

- **概述**：IFU中的Trigger模块有4个tdata寄存器，值由后端设置。每个tdata寄存器包含触发器的配置信息。

- **tdata更新**：
  ```
  when(io.frontendTrigger.tUpdate.valid) {
    tdataVec(io.frontendTrigger.tUpdate.bits.addr) := io.frontendTrigger.tUpdate.bits.tdata
  }
  ```
  - 通过tUpdate接口更新tdata
  - tUpdate.bits.addr：指定更新哪个tdata寄存器（0-3）
  - tUpdate.bits.tdata：新的tdata值

- **tdata结构**（MatchTriggerIO）：
  - tdata1：比较值1（PC低位的部分）
  - tdata2：比较值2（PC高位的部分）
  - tdata3：控制寄存器
    - select：是否选择地址匹配
    - matchType：匹配类型
    - timing：触发时机
    - chain：链式匹配
    - action：触发动作
  - tdata6：执行寄存器（当前未使用）

### 触发器使能控制

- **概述**：每个tdata寄存器都有一个独立的使能标志，控制该触发器是否工作。

- **使能信号**：
  ```
  triggerEnableVec := io.frontendTrigger.tEnableVec
  ```
  - tEnableVec：4个Bool值，对应4个tdata寄存器
  - 从CSR控制，由机器模式和调试模式设置

- **调试模式检测**：
  ```
  XSDebug(triggerEnableVec.asUInt.orR, "Debug Mode: At least one frontend trigger is enabled\n")
  ```
  - 至少有一个触发器使能时，打印调试信息

### PC匹配逻辑

- **概述**：遍历送入IBuffer的所有PC，根据matchType的匹配规则进行匹配。当前只支持PC匹配，预译码和指令数据使用待补充。

- **匹配过程**：
  1. **PC拆分**：
     - PC的高位部分和低位部分分别匹配
     - 使用PrunedAddr类型，PC被拆分为多个部分

  2. **匹配函数**（TriggerCmpConsecutive）：
     ```
     triggerHitVec(i) = TriggerCmpConsecutive(
       VecInit(io.pc.map(_.toUInt)),
       tdataVec(j).tdata2,
       tdataVec(j).matchType,
       triggerEnableVec(j)
     ).map(hit => hit && !tdataVec(j).select && !debugMode)
     ```
     - 对每个tdata寄存器j
     - 对每个指令i
     - 检查PC是否匹配tdata2
     - 检查select标志
     - 检查是否在调试模式

  3. **匹配条件**：
     - `!tdataVec(j).select`：select标志为false时才匹配（根据文档）
     - `!debugMode`：不在调试模式下才匹配

  4. **匹配结果**：
     - triggerHitVec：TriggerNum × IBufferEnqueueWidth的二维Bool矩阵
     - triggerHitVec(j)(i) = true：tdata寄存器j在指令i处匹配

### 触发检查逻辑

- **概述**：对每个指令位置，检查是否可以触发触发器。综合考虑timing、chain、action等控制信号。

- **执行流程**：
  1. **对每个指令位置i**：
     ```
     val triggerCanFireVec = Wire(Vec(TriggerNum, Bool()))
     TriggerCheckCanFire(TriggerNum, triggerCanFireVec, VecInit(triggerHitVec(i)), triggerTimingVec, triggerChainVec)
     ```
     - triggerCanFireVec：4个Bool值，对应4个tdata寄存器
     - 输入：该位置的所有triggerHitVec(i)
     - 输出：该位置每个触发器是否可以触发

  2. **生成触发动作**：
     ```
     val triggerAction = Wire(TriggerAction())
     TriggerUtil.triggerActionGen(triggerAction, triggerCanFireVec, actionVec, triggerCanRaiseBpExp)
     ```
     - triggerCanFireVec：可以触发的触发器列表
     - actionVec：触发动作配置
     - triggerCanRaiseBpExp：是否可以触发断点异常
     - 输出：triggerAction（最终的触发动作）

  3. **输出triggered信号**：
     ```
     io.triggered(i) := triggerAction
     ```
     - 每个指令位置输出一个triggerAction
     - 传递给IBuffer，用于后续处理

- **调试输出**：
  ```
  XSDebug(
    triggerCanFireVec.asUInt.orR,
    p"Debug Mode: Predecode Inst No. $i has trigger action vec ${triggerCanFireVec.asUInt.orR}\n"
  )
  ```
  - 当至少一个触发器可以触发时，打印调试信息

### 触发控制信号

- **timing（触发时机）**：
  - 控制触发器在指令执行的哪个阶段触发
  - 从tdata3中提取
  - `triggerTimingVec = VecInit(tdataVec.map(_.timing))`

- **chain（链式匹配）**：
  - 控制多个触发器的链式匹配
  - 从tdata3中提取
  - `triggerChainVec = VecInit(tdataVec.map(_.chain))`

- **action（触发动作）**：
  - 控制触发后执行的动作
  - 从tdata3中提取
  - `actionVec = VecInit(tdataVec.map(_.action))`

- **select（选择标志）**：
  - 控制是否选择地址匹配
  - 从tdata3中提取
  - 匹配条件：`!tdataVec(j).select`

### 调试模式控制

- **概述**：触发器不在调试模式下工作。当进入调试模式后，触发器应该停止匹配。

- **debugMode信号**：
  ```
  private val debugMode = io.frontendTrigger.debugMode
  ```
  - 从frontendTrigger接口获取
  - 控制触发器是否工作

- **调试模式下的行为**：
  - 在debugMode下，`triggerHitVec`的所有值都为false
  - 因为匹配条件中包含`!debugMode`
  - 这确保了调试模式下不会触发新的断点

### 预留扩展功能

- **预译码信息使用**：
  - 当前未使用
  - 输入信号：pds（预译码信息）
  - 预留：未来可以基于预译码信息进行触发

- **指令数据使用**：
  - 当前未使用
  - 输入信号：data（指令数据）
  - 当前值：全0（`0.U.asTypeOf(Vec(IBufferEnqueueWidth + 1, UInt(16.W)))`）
  - 预留：未来可以基于指令数据进行触发

- **触发器打印**：
  ```
  for (i <- 0 until TriggerNum) { PrintTriggerInfo(triggerEnableVec(i), tdataVec(i)) }
  ```
  - 打印每个触发器的配置信息
  - 用于调试和验证

### 状态机与时序
- **状态机列表**：无（纯组合逻辑 + 寄存器）

- **关键时序**：
  - tdata更新：寄存器更新，1个周期
  - PC匹配：组合逻辑
  - 触发检查：组合逻辑
  - triggered输出：组合逻辑

### 复位与错误处理
- **复位行为**：
  - tdataVec：RegInit，复位时为0
  - triggerEnableVec：不是寄存器，直接从输入获取
  - 无错误处理逻辑

## 验证需求与覆盖建议
- **功能覆盖点**：
  - **PC匹配**：
    * 单个触发器PC匹配
    * 多个触发器PC匹配
    * 不同matchType的匹配
    * select标志的影响

  - **触发控制**：
    * timing控制
    * chain控制
    * action控制
    * debugMode控制

  - **边界情况**：
    * 无触发器使能
    * 所有PC都不匹配
    * 多个PC同时匹配
    * 调试模式下的行为

  - **预留功能**：
    * 预译码信息使用（待实现）
    * 指令数据使用（待实现）

- **约束与假设**：
  - 触发器数量：4个（TriggerNum）
  - 只支持PC匹配（当前）
  - 不在调试模式下工作
  - 预译码和指令数据使用待补充

- **测试接口**：
  - 输入：各种tdata配置、PC序列
  - 监视点：triggerHitVec、triggerCanFireVec、triggered
  - 参考模型：RISC-V调试规范

## 潜在 bug 分析

### 预译码和指令数据未实现（置信度 90%）
- **触发条件**：使用预译码信息或指令数据进行触发
- **影响范围**：功能不完整，无法支持基于指令内容的触发
- **关联位置**：FrontendTrigger.scala:46，data信号赋值为0
- **代码证据**：
  ```
  // Currently, FrontendTrigger supports pc match only, data/pds is reserved for future use
  frontendTrigger.io.data := 0.U.asTypeOf(Vec(IBufferEnqueueWidth + 1, UInt(16.W))) // s3_alignInstrData
  ```
- **验证建议**：
  1. 明确基于预译码和指令数据的触发需求
  2. 实现data和pds信号的连接
  3. 扩展匹配逻辑，支持指令内容匹配
  4. 测试各种指令类型的触发

### select标志语义不明确（置信度 60%）
- **触发条件**：select标志的设置和使用
- **影响范围**：可能导致触发器匹配逻辑错误
- **关联位置**：FrontendTrigger.scala:75，匹配条件`!tdataVec(j).select`
- **验证建议**：
  1. 明确select标志的确切语义
  2. 验证select=true和select=false时的行为
  3. 测试select标志与匹配类型的组合
  4. 参考RISC-V调试规范确认实现

### 调试模式切换时序（置信度 40%）
- **触发条件**：debugMode信号切换
- **影响范围**：可能导致调试模式下错误触发或非调试模式下无法触发
- **关联位置**：FrontendTrigger.scala:76，`!debugMode`条件
- **验证建议**：
  1. 测试debugMode从false切换到true
  2. 测试debugMode从true切换到false
  3. 验证切换过程中的triggered输出
  4. 确认无毛刺或意外触发

### chain匹配逻辑未验证（置信度 30%）
- **触发条件**：使用chain功能进行链式匹配
- **影响范围**：链式匹配可能不正确
- **关联位置**：FrontendTrigger.scala:80，TriggerCheckCanFire调用
- **验证建议**：
  1. 了解chain匹配的详细需求
  2. 测试多个触发器的chain组合
  3. 验证chain匹配的时序
  4. 确认TriggerCheckCanFire的实现正确性

### timing控制未详细说明（置信度 30%）
- **触发条件**：使用timing控制触发时机
- **影响范围**：触发时机可能不符合预期
- **关联位置**：FrontendTrigger.scala:61-62，triggerTimingVec
- **验证建议**：
  1. 明确timing的各种取值和含义
  2. 测试不同timing下的触发行为
  3. 验证timing与流水线阶段的对应关系
  4. 确认TriggerCheckCanFire中timing的使用

### tdata更新时序（置信度 20%）
- **触发条件**：tdata寄存器在匹配过程中更新
- **影响范围**：可能导致匹配结果不一致
- **关联位置**：FrontendTrigger.scala:53-55，tdata更新逻辑
- **验证建议**：
  1. 测试tdata更新期间的匹配
  2. 验证RegInit的正确使用
  3. 确认更新后的tdata何时生效
  4. 测试连续更新多个tdata寄存器
