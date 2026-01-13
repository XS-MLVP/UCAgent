# bosc_IFU 功能点与检测点描述

## DUT 整体功能描述

bosc_IFU（Branch-oriented Out-of-order Superscalar Core - Instruction Fetch Unit）是处理器的指令取指单元，位于FTQ（Fetch Target Queue）和ICache之后，负责从ICache或uncache总线获取指令，进行指令定界、预译码和预测检查，最终将处理好的指令发送到IBuffer（指令缓冲区）。

### 主要功能
- **指令定界**：在64字节fetch块中识别RVC（16位）和RVI（32位）指令边界
- **指令紧密排列**：将稀疏的指令序列转换为紧密排列的形式
- **预译码**：提前生成分支属性、CFI类型、跳转偏移量等信息
- **预测检查**：检测分支预测错误并及时纠正
- **Uncache处理**：处理MMIO指令和不可缓存指令的取指
- **Two Fetch**：支持在一个周期内获取两个预测块
- **触发器**：支持调试模式下的PC匹配触发
- **流水线控制**：处理外部冲刷信号和反压信号

### 端口接口说明

**输入端口：**
- `fromFTQ`：FTQ取指请求，包含起始PC、预测信息等
- `fromICache`：ICache返回的指令数据，64字节对齐
- `backendRedirect`：后端重定向信号，最高优先级
- `s1_flushFromBpu`、`s0_flushFromBpu`：BPU冲刷信号
- `ifuUncacheResp`：uncache通路返回的数据和异常
- `fromIBuffer`：IBuffer状态（满载信号等）

**输出端口：**
- `toICache`：向ICache发送取指请求
- `toIBuffer`：向IBuffer发送处理好的指令
- `toIFUWB`：向FTQ写回预测块信息
- `ifuWBRedirect`、`uncacheRedirect`：内部重定向信号
- `toUncache`：向uncache总线发送请求

**控制信号：**
- `ifuBpu`：BPU接口
- `frontendTrigger`：触发器配置接口
- `perf`：性能分析接口

### 流水线结构
IFU采用3级流水线结构：
- **S0级**：计算指令范围，准备取指
- **S1级**：指令定界（InstrBoundary模块）
- **S2级**：提取指令数据、预译码（PreDecode模块）
- **S3级**：传输到IBuffer、RVC扩展（RvcExpander模块）

## 功能分组与检测点

### DUT测试API

<FG-API>

#### IFU基本操作功能

<FC-BASIC-OP>

提供IFU的基本操作接口，包括正常取指流程、复位、使能等核心功能。这些操作是IFU功能验证的基础。

**检测点：**
- <CK-NORMAL-FETCH> 正常取指：验证从ICache正常获取64字节指令块并处理的完整流程
- <CK-RESET> 复位功能：验证系统复位时IFU所有流水线级和状态机正确复位到初始状态
- <CK-FLUSH> 冲刷功能：验证接收到冲刷信号时IFU正确清空流水线并恢复到初始状态
- <CK-IDLE> 空闲状态：验证无取指请求时IFU保持空闲状态，不产生无效输出
- <CK-ENABLE> 使能控制：验证IFU使能信号控制功能生效情况


<FG-INSTR-BOUNDARY>

### 指令定界功能分组

包含指令边界识别、RVC/RVI指令区分、跨预测块处理等指令定界相关功能。

#### 基本指令定界功能

<FC-INSTR-BOUNDARY-BASIC>

在64字节fetch块中识别每条指令的起始位置和结束位置，区分RVC（16位）和RVI（32位）指令。使用多路推断策略优化关键路径。

**检测点：**
- <CK-RVC-ONLY> 纯RVC指令：验证fetch块中只包含16位RVC指令时的定界正确性
- <CK-RVI-ONLY> 纯RVI指令：验证fetch块中只包含32位RVI指令时的定界正确性
- <CK-MIXED> RVC/RVI混合：验证fetch块中RVC和RVI指令混合时的定界正确性
- <CK-BOUNDARY-CORRECT> 边界正确性：验证每条指令的起始和结束边界计算正确
- <CK-32-ENTRY> 32条目边界：验证fetch块中最多32条RVC指令（16×32=512位=64字节）时的边界计算

#### 跨预测块定界功能

<FC-INSTR-BOUNDARY-CROSS>

处理跨越预测块边界的指令识别，包括半条指令的处理和两个预测块的拼接。

**检测点：**
- <CK-HALF-INSTR-FIRST> 第一个预测块半条：验证第一个预测块最后一条指令跨越边界到第二个预测块的情况
- <CK-HALF-INSTR-SECOND> 第二个预测块半条：验证第二个预测块最后一条指令跨越边界的情况
- <CK-TWO-HALF> 两个半条指令：验证两个预测块都存在半条指令的复杂情况
- <CK-CROSS-PAGE> 跨页处理：验证指令跨越页边界（4KB）时的定界和拼接
- <CK-ALIGN-MENT> 对齐处理：验证跨预测块时指令对齐的正确性


<FG-INSTR-COMPACT>

### 指令紧密排列功能分组

将稀疏的指令序列（包含半条指令、无效指令等）转换为紧密排列的形式，优化IBuffer存储空间。

#### 指令序列紧密化功能

<FC-INSTR-COMPACT>

将InstrBoundary模块输出的稀疏指令序列转换为紧密排列的指令序列，去除无效条目，保留有效指令。

**检测点：**
- <CK-NORMAL-COMPACT> 正常紧密化：验证无跨预测块时的指令紧密排列功能
- <CK-CROSS-COMPACT> 跨预测块紧密化：验证跨预测块时两个预测块的指令拼接和紧密排列
- <CK-HALF-HANDLE> 半条指令处理：验证半条指令在紧密排列过程中的正确处理
- <CK-VALID-MASK> 有效掩码：验证有效掩码的正确计算和应用
- <CK-8-ENTRY> 8条目输出：验证输出8条紧密排列指令的正确性（IBufferEnqueueWidth=8）


<FG-PREDECODE>

### 预译码功能分组

在指令发送到后端之前提前生成控制流信息，包括CFI类型、分支属性、跳转偏移量等，用于前端预测检查。

#### CFI类型识别功能

<FC-PREDECODE-CFI>

识别指令是否为控制流指令（CFI），包括jal、jalr、br、ret等指令类型。

**检测点：**
- <CK-JAL> jal指令：验证识别jal指令（无条件跳转并链接）的正确性
- <CK-JALR> jalr指令：验证识别jalr指令（寄存器跳转并链接）的正确性
- <CK-BRANCH> br指令：验证识别条件分支指令的正确性
- <CK-RET> ret指令：验证识别ret指令（函数返回）的正确性
- <CK-NON-CFI> 非CFI指令：验证识别普通非控制流指令的正确性

#### 分支属性计算功能

<FC-PREDECODE-ATTR>

计算分支指令的属性信息，包括是否直接跳转、是否包含返回指令等。

**检测点：**
- <CK-IS-DIRECT> 直接跳转：验证jal和br指令的isDirect属性正确设置
- <CK-IS-INDIRECT> 间接跳转：验证jalr指令的isIndirect属性正确设置
- <CK-HAS-POP> 包含返回：验证ret指令（包含pop操作）的hasPop属性正确设置
- <CK-NOT-CFI> 非CFI属性：验证非CFI指令的notCFI属性正确设置

#### 跳转偏移量计算功能

<FC-PREDECODE-OFFSET>

计算jal和br指令的跳转偏移量，用于后续目的地址检查和预测纠正。

**检测点：**
- <CK-JAL-OFFSET> jal偏移：验证jal指令的跳转偏移量计算（imm[20:1] | imm[31:21]）
- <CK-BR-OFFSET> br偏移：验证br指令的跳转偏移量计算（imm[12|10:5|4:1|11]）
- <CK-SIGNEXT> 符号扩展：验证偏移量的符号扩展正确性
- <CK-TARGET-ADDR> 目的地址：验证PC+offset计算目的地址的正确性


<FG-PREDCHECKER>

### 预测检查功能分组

采用两级流水线结构检测分支预测错误，及时纠正预测方向和目的地址错误。

#### Stage 1：Remask Fault检测功能

<FC-PREDCHECK-REMASK>

检测需要重新掩码的错误，通过调整预测块范围来纠正预测方向错误。

**检测点：**
- <CK-JAL-FAULT> jal方向错误：验证jal指令预测不跳转但实际应该跳转的错误检测
- <CK-JALR-FAULT> jalr方向错误：验证jalr指令预测不跳转但实际应该跳转的错误检测
- <CK-RET-FAULT> ret方向错误：验证ret指令预测不跳转但实际应该跳转的错误检测
- <CK-NOT-CFI-FAULT> 非CFI跳转错误：验证非控制流指令预测跳转的错误检测
- <CK-INVALID-TAKEN> 非法跳转：验证预测跳转但指令末尾不在预测块边界内的错误检测
- <CK-FIXED-RANGE> 范围修正：验证根据remask fault调整预测块有效范围的正确性
- <CK-PRIORITY-ENC> 优先编码：验证多个fault同时存在时优先处理第一个fault

#### Stage 2：重定向准备功能

<FC-PREDCHECK-REDIRECT>

基于Stage 1检测结果，准备详细的重定向信息用于FTQ写回。

**检测点：**
- <CK-TARGET-FIX> 目的地址修正：验证预测错误时计算正确目的地址（PC+jumpOffset或顺序目标）
- <CK-TAKEN-FIX> 跳转标志修正：验证根据actual target和invalid taken修正taken标志
- <CK-REDIRECT-INFO> 重定向信息：验证checkerRedirect信息的完整性（target、misIdx、taken、isRVC、attribute等）
- <CK-FAULT-TYPE> 错误类型：验证perfFaultType统计的7种错误类型正确性
- <CK-WBVALID> 写回有效：验证wbValid控制信号的正确性

#### 目的地址检查功能

<FC-PREDCHECK-TARGET>

检查分支指令的目的地址预测是否正确。

**检测点：**
- <CK-FIRST-TARGET> 第一个目标：验证第一个预测块的目的地址预测检查
- <CK-SECOND-TARGET> 第二个目标：验证第二个预测块的目的地址预测检查
- <CK-TARGET-MATCH> 地址匹配：验证实际计算的目标地址与预测目标地址的比较
- <CK-TARGET-FAULT> 目的地址错误：验证目的地址预测错误的检测和记录


<FG-UNCACHE>

### Uncache指令处理功能分组

处理MMIO指令和不可缓存指令的取指，包含4状态FSM用于阻止MMIO指令的推测执行。

#### Uncache状态机功能

<FC-UNCACHE-FSM>

实现4状态有限状态机（Idle、WaitLastCommit、SendReq、WaitResp），控制uncache指令取指流程。

**检测点：**
- <CK-IDLE> 空闲状态：验证Idle状态等待请求的正确性
- <CK-WAIT-COMMIT> 等待提交：验证WaitLastCommit状态等待MMIO指令成为最旧指令的功能
- <CK-SEND-REQ> 发送请求：验证SendReq状态向uncache总线发送取指请求的正确性
- <CK-WAIT-RESP> 等待响应：验证WaitResp状态接收uncache总线返回数据的正确性
- <CK-STATE-TRANS> 状态转换：验证FSM各状态之间的转换条件正确性
- <CK-FIRST-INSTR> 第一条指令：验证处理器执行的第一条指令绕过WaitLastCommit状态

#### MMIO推测阻塞功能

<FC-UNCACHE-MMIO-BLOCK>

阻止MMIO指令的推测执行，确保MMIO指令成为最旧指令后才发送uncache请求。

**检测点：**
- <CK-MMIO-DETECT> MMIO检测：验证正确识别MMIO指令（isMmio信号）
- <CK-BLOCK-EFFECT> 阻塞生效：验证MMIO指令被阻塞在WaitLastCommit状态
- <CK-COMMIT-QUERY> 提交查询：验证mmioCommitRead接口向FTQ查询提交状态的功能
- <CK-NON-MMIO> 非MMIO：验证非MMIO的uncache指令不经过阻塞直接发送请求

#### Uncache地址检查功能

<FC-UNCACHE-ADDR-CHECK>

对uncache指令进行两次地址检查：ICache返回阶段的PMP/PBMT检查，uncache总线返回阶段的TileLink异常检查。

**检测点：**
- <CK-STAGE1-PMP> 第一阶段PMP：验证ICache返回时的PMP物理内存保护检查
- <CK-STAGE1-PBMT> 第一阶段PBMT：验证ICache返回时的PBMT页内存类型检查
- <CK-STAGE2-TILELINK> 第二阶段TileLink：验证uncache总线返回时的TileLink异常检查
- <CK-EXCEPTION-MIX> 异常混合：验证两次检查的异常混合处理（5种场景）
- <CK-CORRUPT> corrupt异常：验证总线返回corrupt信号时的异常处理
- <CK-DENIED> denied异常：验证总线返回denied信号时的异常处理

#### 跨页处理功能

<FC-UNCACHE-CROSSPAGE>

处理uncache指令跨越页边界的情况，包括数据拼接和重定向处理。

**检测点：**
- <CK-CROSSPAGE-FLAG> 跨页标志：验证crossPage标志的正确识别
- <CK-DATA-SPLIT> 数据拆分：验证跨页时指令数据拆分为高16位和低16位的正确性
- <CK-DATA-MERGE> 数据拼接：验证顺序取指时两个预测块数据拼接的正确性
- <CK-REDIRECT-HANDLER> 重定向处理：验证跨页时发生重定向的数据暂存和重定向发送


<FG-TWO-FETCH>

### Two Fetch功能分组

支持在一个周期内获取两个预测块，提高指令取指带宽。

#### 双预测块请求功能

<FC-TWO-FETCH-REQ>

在满足条件时，向ICache请求两个连续的预测块。

**检测点：**
- <CK-TWO-FETCH-COND> 双取条件：验证满足Two Fetch条件时的双预测块请求
- <CK-FIRST-BLOCK> 第一个块：验证第一个预测块的正常取指
- <CK-SECOND-BLOCK> 第二个块：验证第二个预测块的正常取指
- <CK-CONTIGUOUS> 连续地址：验证两个预测块的地址连续性（startPC + 32字节）
- <CK-NON-TWO-FETCH> 非双取：验证不满足条件时的单预测块取指

#### 双预测块拼接功能

<FC-TWO-FETCH-MERGE>

将两个预测块的数据拼接成一个完整的fetch块进行处理。

**检测点：**
- <CK-NORMAL-MERGE> 正常拼接：验证两个预测块的正常拼接（32字节 + 32字节 = 64字节）
- <CK-CROSS-BLOCK> 跨预测块指令：验证指令跨越两个预测块边界时的拼接处理
- <CK-VALID-MERGE> 有效拼接：验证valid信号在两个预测块拼接时的正确性
- <CK-ALIGNMENT> 对齐处理：验证双预测块时的指令对齐处理


<FG-TRIGGER>

### 触发器功能分组

支持调试模式下的PC匹配触发，可以设置4个独立的触发器。

#### 触发器配置功能

<FC-TRIGGER-CONFIG>

配置4个tdata寄存器，包括比较值、匹配类型、触发时机等。

**检测点：**
- <CK-TDATA-UPDATE> tdata更新：验证通过tUpdate接口更新tdata寄存器的功能
- <CK-ENABLE> 使能控制：验证triggerEnableVec控制触发器使能的功能
- <CK-TDATA1> tdata1配置：验证比较值1（PC低位）的配置
- <CK-TDATA2> tdata2配置：验证比较值2（PC高位）的配置
- <CK-TDATA3> tdata3配置：验证控制寄存器（select、matchType、timing、chain、action）的配置

#### PC匹配功能

<FC-TRIGGER-MATCH>

遍历送入IBuffer的所有PC，根据matchType进行匹配，判断是否触发触发器。

**检测点：**
- <CK-SINGLE-MATCH> 单触发器匹配：验证单个触发器PC匹配的正确性
- <CK-MULTI-MATCH> 多触发器匹配：验证多个触发器同时匹配的情况
- <CK-MATCHTYPE> 匹配类型：验证不同matchType（=、!=、<、>等）的匹配规则
- <CK-SELECT> select标志：验证select标志对匹配的影响
- <CK-PC-PARTS> PC拆分：验证PC拆分为高位和低位进行匹配的正确性

#### 触发检查功能

<FC-TRIGGER-CHECK>

综合考虑timing、chain、action等控制信号，检查触发器是否可以触发。

**检测点：**
- <CK-CAN-FIRE> 可触发检查：验证TriggerCheckCanFire检查触发器是否可触发的功能
- <CK-TIMING> timing控制：验证触发时机控制的正确性
- <CK-CHAIN> chain链式：验证多个触发器链式匹配的功能
- <CK-ACTION> action动作：验证触发后动作类型的正确性
- <CK-BP-EXP> 断点异常：验证triggerCanRaiseBpExp断点异常触发的正确性

#### 调试模式控制功能

<FC-TRIGGER-DEBUG>

控制触发器在调试模式和非调试模式下的行为。

**检测点：**
- <CK-DEBUG-MODE> 调试模式：验证进入调试模式后触发器停止匹配的功能
- <CK-NON-DEBUG> 非调试模式：验证非调试模式下触发器正常工作的功能
- <CK-MODE-SWITCH> 模式切换：验证调试模式切换时的触发器行为


<FG-FLUSH-CTRL>

### 冲刷控制功能分组

处理外部冲刷信号，包括BPU冲刷、后端重定向、内部重定向等，控制流水线清空和状态恢复。

#### BPU冲刷处理功能

<FC-FLUSH-BPU>

处理来自BPU的冲刷信号，包括S0级和S1级的BPU冲刷。

**检测点：**
- <CK-S0-FLUSH> S0级BPU冲刷：验证S0级接收s0_flushFromBpu信号的冲刷功能
- <CK-S1-FLUSH> S1级BPU冲刷：验证S1级接收s1_flushFromBpu信号的冲刷功能
- <CK-BPU-PROPAGATE> BPU传播：验证BPU冲刷信号向S2、S3级传播的正确性

#### 后端重定向处理功能

<FC-FLUSH-BACKEND>

处理来自后端的重定向信号，具有最高优先级，可冲刷所有流水线级。

**检测点：**
- <CK-BACKEND-VALID> 后端重定向有效：验证backendRedirect信号有效时的冲刷功能
- <CK-HIGHEST-PRIORITY> 最高优先级：验证backendRedirect的最高优先级（冲刷所有级）
- <CK-ENQ-PTR-RESET> 指针复位：验证后端重定向时s2_prevIBufEnqPtr复位为0
- <CK-PIPE-RESET> 流水线复位：验证后端重定向时S0、S1、S2、S3所有级的寄存器复位

#### 内部重定向处理功能

<FC-FLUSH-INTERNAL>

处理IFU内部产生的重定向信号，包括wbRedirect和uncacheRedirect。

**检测点：**
- <CK-WB-VALID> wbRedirect有效：验证预译码检查器产生的wbRedirect信号处理
- <CK-WB-PTR> wbRedirect指针：验证wbRedirect携带的prevIBufEnqPtr指针更新的正确性
- <CK-WB-COUNT> wbRedirect计数：验证wbRedirect携带的instrCount指令计数的正确性
- <CK-UNCACHE-VALID> uncacheRedirect有效：验证uncache完成产生的uncacheRedirect信号处理
- <CK-UNCACHE-PTR> uncacheRedirect指针：验证uncacheRedirect携带的prevIBufEnqPtr指针更新的正确性
- <CK-INTERNAL-PROPAGATE> 内部传播：验证内部重定向信号向各级传播的正确性

#### 冲刷优先级与传播功能

<FC-FLUSH-PRIORITY>

管理各种冲刷信号的优先级和传播规则。

**检测点：**
- <CK-PRIORITY-ORDER> 优先级顺序：验证冲刷优先级顺序（backendRedirect > wbRedirect/uncacheRedirect > BPU flush）
- <CK-S3-FLUSH> S3级冲刷：验证S3级冲刷信号计算（backendRedirect || wbRedirect）
- <CK-S2-FLUSH> S2级冲刷：验证S2级冲刷信号计算（backendRedirect || uncacheRedirect || wbRedirect）
- <CK-FLUSH-PROPAGATE> 冲刷传播：验证冲刷信号从上游到下游的传播（S0→S1→S2→S3）
- <CK-FLUSH-BLOCK> 冲刷阻塞：验证冲刷期间新请求被阻塞的正确性

#### 冲刷后状态恢复功能

<FC-FLUSH-RECOVERY>

执行冲刷后的状态恢复操作，包括寄存器复位、指针复位、状态机复位等。

**检测点：**
- <CK-REG-RESET> 寄存器复位：验证流水线寄存器（S0、S1、S2、S3）的复位
- <CK-STATE-RESET> 状态复位：验证state寄存器（如uncacheState）的复位
- <CK-PTR-RESET> 指针复位：验证IBuffer指针（prevIBufferEnqPtr）的复位
- <CK-UNCACHE-RESET> Uncache复位：验证Uncache状态机调用uncacheReset()复位的正确性


<FG-BACKPRESSURE>

### 反压处理功能分组

处理ICache、IBuffer和uncache通路的反压信号，控制流水线暂停和恢复。

#### ICache反压处理功能

<FC-BACKPRESSURE-ICACHE>

处理ICache多拍未响应时的反压情况。

**检测点：**
- <CK-ICACHE-STALL> ICache暂停：验证ICache多拍未响应时IFU暂停S1级的正确性
- <CK-ICACHE-RESUME> ICache恢复：验证ICache恢复响应后IFU恢复正常取指的正确性
- <CK-ICACHE-TIMEOUT> ICache超时：验证ICache长时间无响应的处理逻辑

#### IBuffer反压处理功能

<FC-BACKPRESSURE-IBUFFER>

处理IBuffer满载时的反压情况，控制指令发送到IBuffer的速率。

**检测点：**
- <CK-IBUF-FULL> IBuffer满载：验证IBuffer满载时S3级暂停发送指令的正确性
- <CK-IBUF-READY> IBuffer就绪：验证IBuffer由满变空闲后IFU恢复发送的正确性
- <CK-IBUF-PTR> IBuffer指针：验证IBuffer指针与满载检测的一致性

#### Uncache取指反压功能

<FC-BACKPRESSURE-UNCACHE>

处理uncache取指时的反压情况，通过uncacheReady信号控制。

**检测点：**
- <CK-UNCACHE-NOTREADY> uncache未就绪：验证uncacheReady为false时暂停发送请求的正确性
- <CK-UNCACHE-READY> uncache就绪：验证uncacheReady为true时恢复发送请求的正确性
- <CK-UNCACHE-STALL> uncache暂停：验证ifuStall信号控制uncache暂停的正确性

#### 反压传播功能

<FC-BACKPRESSURE-PROPAGATE>

管理反压信号在流水线中的传播链：S3→S2→S1→FTQ。

**检测点：**
- <CK-S3-TO-S2> S3到S2传播：验证S3级反压向S2级传播的正确性
- <CK-S2-TO-S1> S2到S1传播：验证S2级反压向S1级传播的正确性
- <CK-S1-TO-FTQ> S1到FTQ传播：验证S1级反压向FTQ传播的正确性
- <CK-PROPAGATE-CHAIN> 传播链：验证完整反压传播链（S3→S2→S1→FTQ）的正确性

#### 反压与冲刷交互功能

<FC-BACKPRESSURE-FLUSH>

处理反压期间发生冲刷的复杂交互场景。

**检测点：**
- <CK-FLUSH-DURING-STALL> 暂停期间冲刷：验证反压期间收到冲刷信号的正确处理
- <CK-FLUSH-AFTER-STALL> 暂停后冲刷：验证反压解除后收到冲刷信号的正确处理
- <CK-STALL-AFTER-FLUSH> 冲刷后暂停：验证冲刷后发生反压的正确处理
- <CK-PRIORITY> 优先级处理：验证冲刷优先级高于反压的正确性


<FG-IBUF-IF>

### IBuffer接口功能分组

处理IFU与IBuffer之间的接口，包括指针管理、数据对齐、RVC扩展等。

#### prevIBufferEnqPtr指针管理功能

<FC-IBUF-PTR>

管理prevIBufferEnqPtr指针，跟踪IBuffer入队位置，确保与IBuffer协同工作的正确性。

**检测点：**
- <CK-PTR-INIT> 指针初始化：验证复位后prevIBufferEnqPtr初始化为0
- <CK-PTR-NORMAL> 指针正常递增：验证S2级正常取指时指针递增s2_instrCount的正确性
- <CK-PTR-BACKEND> 后端重定向指针：验证backendRedirect时指针复位为0的正确性
- <CK-PTR-WB> wbRedirect指针：验证wbRedirect时指针更新为wbRedirect.prevIBufEnqPtr + wbRedirect.instrCount的正确性
- <CK-PTR-UNCACHE> uncacheRedirect指针：验证uncacheRedirect时指针更新为uncacheRedirect.prevIBufEnqPtr + uncacheRedirect.instrCount的正确性
- <CK-PTR-MONOTONIC> 指针单调性：验证指针单调递增不回绕（除重定向外）的正确性

#### 指令数据对齐功能

<FC-IBUF-ALIGN>

处理指令数据与IBuffer bank对齐，确保写入正确的IBuffer bank。

**检测点：**
- <CK-ALIGN-CALC> 对齐计算：验证根据enqPtr计算bank对齐的正确性
- <CK-ALIGN-S2> S2级对齐：验证S2级预计算prevIBufferEnqPtr的对齐
- <CK-ALIGN-S3> S3级对齐：验证S3级使用对齐指针写入IBuffer的正确性
- <CK-MOD-4> mod 4计算：验证bank对齐使用mod 4计算的正确性

#### RVC扩展功能

<FC-IBUF-RVC>

将16位RVC指令扩展为32位RVI指令，保持指令格式统一。

**检测点：**
- <CK-RVC-EXPAND> RVC扩展：验证使用RocketChip RVCDecoder扩展RVC指令的正确性
- <CK-INVALID-RVC> 非法RVC：验证非法RVC指令保持原数据的正确性
- <CK-FSISOFF> fsIsOff控制：验证fsIsOff控制信号对RVC扩展的影响
- <CK-32BIT-OUTPUT> 32位输出：验证输出32位RVI指令格式的正确性

#### IBuffer入队优化功能

<FC-IBUF-ENQUEUE>

优化IBuffer入队过程，包括Valid序列和enqEnable序列分离、写分bank策略等。

**检测点：**
- <CK-VALID-SEQ> Valid序列：验证Valid序列与enqEnable序列分离的正确性
- <CK-ENABLE-SEQ> Enable序列：验证enqEnable序列控制写入使能的正确性
- <CK-WRITE-BANK> 写分bank：验证写分bank策略（mod 4）的正确性
- <CK-ENQ-EFFICIENCY> 入队效率：验证同时写入多条指令的效率优化
