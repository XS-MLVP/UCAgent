# IfuUncacheUnit 规格说明文档

> 本文档用于指导编写 `IfuUncacheUnit` 子模块的规格说明书。IfuUncacheUnit是IFU中负责处理uncache指令取指的子模块，包含一个4状态的状态机，用于判断并阻止MMIO指令的推测执行。

## 简介
- **设计背景**：`IfuUncacheUnit`（Uncache处理单元）是IFU中负责从uncache总线提取指令的子模块。受PBMT属性影响，部分非缓存的指令数据是允许推测执行的，因此需要对MMIO指令进行特殊区分和阻止。

  Uncache指令的特点是每次总是返回64字节对齐的数据，这意味着如果指令跨越了64字节的边界，将会发送两次请求。对于跨页情况，前端uncache通路会返回crossPage状态标志，需要IFU做额外的拼接处理。

  Uncache单元采用有限状态机（FSM）实现，包含4个状态，用于处理MMIO指令的推测阻塞逻辑。

- **版本信息**：规格版本 V3，基于文档 AS-IFU-V3.md 和源代码 IfuUncacheUnit.scala

- **设计目标**：
  - 从uncache总线提取指令
  - 判断并阻止MMIO指令的推测执行
  - 处理跨页情况（crossPage）
  - 支持处理器第一条指令的特殊处理

## 术语与缩写
| 缩写 | 全称 | 说明 |
| ---- | ---- | ---- |
| MMIO | Memory-Mapped I/O | 内存映射I/O |
| PBMT | Page-Based Memory Types | 基于页的内存类型 |
| PMP | Physical Memory Protection | 物理内存保护 |
| FTQ | Fetch Target Queue | 取指目标队列 |
| uncache | Uncache | 非缓存，指不从ICache取指 |
| crossPage | Cross Page | 跨页边界 |
| FSM | Finite State Machine | 有限状态机 |

## RTL源文件

对涉及文件进行简要说明。

文件列表：
- `bosc_IFU/chisel/IfuUncacheUnit.scala` IfuUncacheUnit模块主文件
  - `class IfuUncacheUnit` - Uncache处理单元主类
  - `class IfuUncacheIO` - Uncache处理单元接口
  - `class IfuUncacheReq` - 请求Bundle
  - `class IfuUncacheResp` - 响应Bundle
  - `object UncacheFsmState` - Uncache状态机枚举

## 顶层接口概览
- **模块名称**：`IfuUncacheUnit`

- **端口列表**：

  | 信号名 | 方向 | 位宽/类型 | 复位值 | 描述 |
  | ------ | ---- | -------- | ------ | ---- |
  | req.valid | Input | Bool | - | 请求有效信号 |
  | req.ready | Output | Bool | - | 请求就绪信号 |
  | req.bits.ftqIdx | Input | FtqPtr | - | FTQ索引 |
  | req.bits.pbmt | Input | UInt(Pbmt.width.W) | - | PBMT属性 |
  | req.bits.isMmio | Input | Bool | - | 是否为MMIO |
  | req.bits.paddr | Input | PrunedAddr(PAddrBits) | - | 物理地址 |
  | resp.valid | Output | Bool | - | 响应有效信号 |
  | resp.bits.uncacheData | Output | UInt(32.W) | - | uncache指令数据 |
  | resp.bits.exception | Output | ExceptionType | - | 异常类型 |
  | resp.bits.crossPage | Output | Bool | - | 跨页标志 |
  | isFirstInstr | Input | Bool | - | 是否为处理器执行的第一条指令 |
  | ifuStall | Input | Bool | - | IFU暂停信号 |
  | flush | Input | Bool | - | 冲刷信号 |
  | mmioCommitRead | Output | MmioCommitRead | - | MMIO提交读取接口 |
  | toUncache | Output | IfuToInstrUncacheIO | - | 到uncache通路的接口 |
  | fromUncache | Input | InstrUncacheToIfuIO | - | 从uncache通路的接口 |

- **时钟与复位要求**：
  - 单时钟域
  - 复位信号：flush或系统复位

- **外部依赖**：
  - uncache通路：发送MMIO请求和接收数据
  - FTQ：查询预测块的提交状态（mmioCommitRead）
  - IFU主体：接收uncache请求和返回响应

## 功能描述

### Uncache状态机

- **概述**：Uncache单元采用4状态FSM实现，处理MMIO指令的推测阻塞逻辑。状态转换由请求有效性、是否为MMIO、是否为第一条指令、uncache通道就绪等条件控制。

- **状态定义**：
  1. **Idle（空闲状态）**：初始状态，等待uncache请求
  2. **WaitLastCommit（等待上一条指令提交）**：等待MMIO指令成为最旧指令
  3. **SendReq（发送请求）**：向uncache通路发送取指请求
  4. **WaitResp（等待响应）**：等待uncache通路返回数据

- **状态转换图**：
  ```
                           ┌───────────────────────┐
                           │         Idle          │
                           └───────────┬───────────┘
                                       │
                                       │ io.req.valid
                                       ▼
                           ┌───────────────────────┐
                      ┌────▶│   WaitLastCommit      │────┐
                      │     └───────────────────────┘    │
                      │                                     │
                      │ isFirstInstr                        │
                      │                                     │
                      │                                     │
  ┌───────────────┐  │     ┌───────────────────────┐    │
  │   WaitResp     │◀┴─────│       SendReq          │────┘
  └───────────────┘        └───────────────────────┘
         │                           │
         │                           │
         │ toUncache.fire            │
         │                           │
         └──────────(return to Idle)──┘
  ```

- **执行流程**：
  1. **Idle状态**：
     - 等待uncache请求（io.req.valid）
     - 如果收到请求：
       - 判断是否为MMIO（reqIsMmio = io.req.bits.isMmio）
       - 如果是MMIO，转WaitLastCommit状态
       - 如果非MMIO，转SendReq状态
     - 保存请求信息：uncachePAddr、isMmio、itlbPbmt

  2. **WaitLastCommit状态**：
     - 如果isFirstInstr为true，转SendReq状态（处理器执行的第一条指令不需要等待）
     - 否则，需要等待MMIO指令成为最旧指令
     - **注意**：当前实现中，MMIO阻塞功能被禁用（硬编码为true.B）
       - 注释说明："MMIO blocking will be enabled once FTQ commit support is in place"
       - 代码：`uncacheState := Mux(true.B, UncacheFsmState.SendReq, ...)`

  3. **SendReq状态**：
     - 向uncache通路发送请求（toUncache）
     - 如果ifuStall为true，暂停发送
     - 如果toUncache.fire为true，转WaitResp状态
     - 否则，保持在SendReq状态

  4. **WaitResp状态**：
     - 等待uncache通路返回数据（fromUncache.fire）
     - 如果收到数据：
       - 提取数据：fromUncache.bits.data
       - 检查异常：exception = ExceptionType.fromTileLink(corrupt, denied)
       - 检查跨页：crossPage = fromUncache.bits.incomplete
       - 保存信息：uncacheData、uncacheException、uncacheCrossPage
       - 转Idle状态
     - 设置uncacheFinish标志

- **边界与异常**：
  - **处理器第一条指令**：
    - 不存在更旧指令，越过阻塞机制直接发送请求
    - 通过isFirstInstr信号判断

  - **冲刷处理**：
    - 接收Flush信号后，无条件复位所有状态和寄存器
    - 调用uncacheReset()函数：
      - uncacheState := Idle
      - 清空所有寄存器

  - **MMIO阻塞禁用**：
    - 当前实现中，MMIO阻塞功能被禁用（硬编码）
    - WaitLastCommit状态会立即转SendReq状态
    - 这是待完善的功能（需要FTQ commit支持）

- **性能与约束**：
  - **时序优化**：状态机尽量简单，减少状态转换延迟
  - **资源优化**：使用寄存器缓存请求信息，避免重复计算
  - **推测执行优化**：MMIO阻塞可以阻止错误的推测执行

### Uncache请求与响应

- **请求生成**：
  ```
  toUncache.valid := (uncacheState === UncacheFsmState.SendReq) && !ifuStall
  toUncache.bits.addr := uncachePAddr
  toUncache.bits.memBackTypeMM := !isMmio
  toUncache.bits.memPageTypeNC := itlbPbmt === Pbmt.nc
  ```
  - 只在SendReq状态且IFU未暂停时发送请求
  - memBackTypeMM：如果不是MMIO，则请求发送到主存
  - memPageTypeNC：标记是否为Normal Cacheable（NC属性）

- **响应处理**：
  ```
  io.resp.valid := uncacheFinish
  io.resp.bits.exception := uncacheException
  io.resp.bits.uncacheData := uncacheData
  io.resp.bits.crossPage := uncacheCrossPage
  ```
  - 只在uncacheFinish为true时输出响应
  - 包含指令数据、异常类型、跨页标志

### 跨页处理

- **概述**：uncache总线总是返回64字节对齐的数据。当指令跨越64字节边界或页边界时，需要特殊处理。

- **跨页标志**：
  - crossPage = fromUncache.bits.incomplete
  - 表示指令跨越了页边界，两个页的物理地址不连续

- **跨页处理逻辑**（在IFU主体中）：
  1. **跨页情况下**：
     - 如果预测器给出顺序取指：暂存半截指令数据，等待下一个预测块走完uncache流程，拼接两个预测块
     - 如果预测器给出跳转：暂存半截指令数据，发送重定向

  2. **非跨页情况下**：
     - 一条指令在一个预测块中取完

- **IFU主体中的跨页状态**：
  - `prevUncacheCrossPage`：寄存器，保存上一次uncache是否跨页
  - `prevUncacheData`：寄存器，保存上一次uncache的半截数据（16位）
  - `uncachePc`：寄存器，保存uncache指令的PC

- **跨页数据拼接**：
  ```
  s3_uncacheData = Mux(prevUncacheCrossPage, Cat(uncacheData(15,0), prevUncacheData), uncacheData)
  ```
  - 如果之前跨页，拼接新的低16位和之前的高16位
  - 否则，直接使用uncacheData

### MMIO提交读取

- **概述**：mmioCommitRead接口用于向FTQ查询MMIO指令是否已提交（成为最旧指令）。

- **接口定义**：
  ```
  io.mmioCommitRead.valid := uncacheValid && isMmio
  io.mmioCommitRead.mmioFtqPtr := RegEnable(io.req.bits.ftqIdx - 1.U, io.req.valid)
  ```
  - 当uncache有效且为MMIO时，发送查询请求
  - 查询的ftqIdx为当前请求的ftqIdx减1

- **当前状态**：
  - mmioCommitRead接口已定义，但当前未真正使用
  - WaitLastCommit状态被硬编码为立即转SendReq状态
  - 这是待完善的功能

### 状态机与时序
- **状态机列表**：
  - UncacheFSM：4个状态（Idle、WaitLastCommit、SendReq、WaitResp）

- **关键时序**：
  - Idle → SendReq/WatiLastCommit：1个周期
  - WaitLastCommit → SendReq：0个周期（当前硬编码）或多个周期（等待commit）
  - SendReq → WaitResp：取决于uncache通道延迟
  - WaitResp → Idle：1个周期

### 复位与错误处理
- **复位行为**：
  - 接收Flush信号后，无条件调用uncacheReset()
  - 复位所有状态寄存器：
    - uncacheState := Idle
    - 清空uncacheData、uncacheException、uncacheCrossPage、uncachePAddr、uncacheFinish

- **错误上报**：
  - **异常类型**：
    - 使用ExceptionType.fromTileLink()生成
    - 基于corrupt和denied信号
    - 包含在resp.bits.exception中

  - **异常处理**：
    - 异常信息传递给IFU主体
    - IFU主体将异常信息传递给IBuffer

- **自恢复策略**：
  - Flush后自动复位到Idle状态
  - 不需要额外的自恢复逻辑

## 验证需求与覆盖建议
- **功能覆盖点**：
  - **正常流程**：
    * 非MMIO uncche指令取指
    * MMIO uncche指令取指
    * 处理器第一条指令取指

  - **边界情况**：
    * 跨页指令取指
    * IFU暂停时的uncache请求
    * Flush时的状态复位

  - **异常情况**：
    * uncache返回异常（corrupt、denied）
    * crossPage标志处理
    * 重复Flush

  - **待完善功能**：
    * MMIO阻塞功能（当前禁用）
    * mmioCommitRead接口使用

- **约束与假设**：
  - uncache总线总是返回64字节对齐的数据
  - 跨页时需要IFU主体做拼接处理
  - MMIO阻塞功能待完善（当前禁用）

- **测试接口**：
  - 输入：各种uncache请求场景
  - 监视点：uncacheState、toUncache、fromUncache、resp
  - 参考模型：uncache总线协议规范

## 潜在 bug 分析

### MMIO阻塞功能未实现（置信度 80%）
- **触发条件**：需要阻止MMIO指令的推测执行
- **影响范围**：可能导致MMIO指令的推测执行，影响正确性
- **关联位置**：IfuUncacheUnit.scala:102-108，WaitLastCommit状态
- **代码证据**：
  ```
  // FIXME: MMIO blocking will be enabled once FTQ commit support is in place.
  uncacheState := Mux(true.B, UncacheFsmState.SendReq, UncacheFsmState.WaitLastCommit)
  ```
- **验证建议**：
  1. 明确MMIO阻塞的完整需求
  2. 实现FTQ commit支持
  3. 修改硬编码的true.B，使用实际的mmioCommitRead信号
  4. 测试MMIO阻塞的各种场景

### 跨页处理逻辑复杂（置信度 60%）
- **触发条件**：uncache指令跨越页边界
- **影响范围**：需要IFU主体和uncache单元协同处理，容易出错
- **关联位置**：
  - IfuUncacheUnit.scala：uncacheCrossPage标志
  - Ifu.scala：prevUncacheCrossPage、prevUncacheData处理
- **验证建议**：
  1. 测试跨页指令取指的完整流程
  2. 验证数据拼接的正确性
  3. 检查顺序取指和跳转两种情况下的处理
  4. 验证crossPageCheck逻辑

### Flush时序问题（置信度 40%）
- **触发条件**：Flush信号在uncache请求处理过程中到达
- **影响范围**：可能导致状态不一致
- **关联位置**：IfuUncacheUnit.scala:152-154，Flush处理
- **验证建议**：
  1. 测试各个状态下的Flush
  2. 验证uncacheReset()的完整性
  3. 检查Flush与uncache通路Flush的同步

### 处理器第一条指令判断（置信度 30%）
- **触发条件**：isFirstInstr信号不准确或时序不匹配
- **影响范围**：可能导致错误地绕过MMIO阻塞
- **关联位置**：IfuUncacheUnit.scala:102，isFirstInstr判断
- **验证建议**：
  1. 验证isFirstInstr信号的来源和准确性
  2. 测试处理器启动时的第一条指令取指
  3. 确认isFirstInstr的复位逻辑

### ifuStall信号处理（置信度 30%）
- **触发条件**：IFU暂停时uncache请求的处理
- **影响范围**：可能导致uncache请求延迟或丢失
- **关联位置**：IfuUncacheUnit.scala:133，ifuStall使用
- **验证建议**：
  1. 测试IFU暂停时的uncache请求
  2. 验证toUncache.valid的正确性
  3. 检查暂停恢复后的请求处理

### uncacheFinish时序（置信度 20%）
- **触发条件**：uncacheFinish标志的设置和清除时序
- **影响范围**：可能导致resp.valid信号时序错误
- **关联位置**：IfuUncacheUnit.scala:127-131，uncacheFinish计算
- **验证建议**：
  1. 验证uncacheFinish的设置条件
  2. 检查resp.valid与uncacheFinish的一致性
  3. 测试连续uncache请求的处理
