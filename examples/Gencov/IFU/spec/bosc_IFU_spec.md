# bosc_IFU 规格说明文档

> 本模板用于指导编写 `bosc_IFU` 芯片验证对象的规格说明书。请按照每个小节的提示补充内容，保持技术语言准确、条理清晰、便于验证复用。若某项内容不存在，请显式写明"无"或"暂缺"，不要删除章节。

## 简介
- **设计背景**：`bosc_IFU`（Instruction Fetch Unit）是处理器前端流水线中负责组织供指数据的关键模块，位于分支预测单元（FTQ）和指令缓存（ICache）之后。在预测路径和ICache命中结果确定后，IFU需要完成指令对齐、打包、简单的预译码等操作，并将处理好的指令送入后续模块（IBuffer）。

  IFU处于供指链路的下游，其处理延迟直接影响整个前端的取指响应能力，尤其在发生重定向（如分支预测错误）时，IFU的执行周期会成为恢复路径的关键延迟点。

- **版本信息**：规格版本 V3，基于文档 AS-IFU-V3.md

- **设计目标**：
  - 完整功能：指令切分、定界、预译码、预译码检查
  - 时序优化：平衡指令位置定界、IBuffer入队的时序紧张问题
  - 流水线效率：在保证功能完整和时序允许的前提下，尽量减少处理周期，提升供指效率和分支恢复速度
  - 最大取指宽度：64字节（32条指令）
  - 支持有限制的two Fetch机制

## 术语与缩写
| 缩写 | 全称 | 说明 |
| ---- | ---- | ---- |
| IFU | Instruction Fetch Unit | 指令取指单元 |
| FTQ | Fetch Target Queue | 取指目标队列，负责预测取指地址 |
| ICache | Instruction Cache | 指令缓存 |
| IBuffer | Instruction Buffer | 指令缓冲区 |
| MMIO | Memory-Mapped I/O | 内存映射I/O |
| RVC | RISC-V Compressed | RISC-V压缩指令（16位） |
| RVI | RISC-V Integer | RISC-V整数指令（32位） |
| CFI | Control Flow Instruction | 控制流指令（分支、跳转等） |
| PC | Program Counter | 程序计数器 |
| PBMT | Page-Based Memory Types | 基于页的内存类型 |
| PMP | Physical Memory Protection | 物理内存保护 |

## RTL源文件

对涉及文件进行简要说明。

文件列表：
- `bosc_IFU/chisel/Abstracts.scala` 基础抽象类定义
  - `abstract class IfuBundle` - IFU数据Bundle基类，继承自FrontendBundle和HasIfuParameters
  - `abstract class IfuModule` - IFU模块基类，继承自FrontendModule和HasIfuParameters

- `bosc_IFU/chisel/Bundles.scala` IFU核心数据结构定义
  - `PreDecodeFaultType` - 预译码错误类型枚举（7种错误类型）
  - `LastHalfEntry` - 跨预测块边界的半条RVI指令记录
  - `InstrIndexEntry` - 指令索引条目
  - `FetchBlockInfo` - 预测块信息（包含FTQ索引、地址、指令范围等）
  - `ICacheMeta` - ICache元数据（异常、PMP、PBMT、物理地址等）
  - `PredCheckRedirect` - 预译码检查重定向信息
  - `FetchToIBufferDB` - IFU到IBuffer的调试信息
  - `IfuWbToFtqDB` - IFU到FTQ的调试信息
  - `IfuRedirectInternal` - IFU内部重定向信息
  - `InstrCompactBundle` - 指令紧密排列数据结构

- `bosc_IFU/chisel/Ifu.scala` IFU主TOP模块
  - 3级流水线（S0-S3）
  - 包含所有子模块实例化和连接
  - 实现顶层状态控制和数据通路

- `bosc_IFU/chisel/InstrBoundary.scala` 指令定界模块
  - 确定每条指令的位置
  - 使用多路推断再合并拼接策略

- `bosc_IFU/chisel/InstrCompact.scala` 指令紧密排列模块
  - 将稀疏分布的有效指令信息进行紧密排列
  - 优化IBuffer入队时序

- `bosc_IFU/chisel/PreDecode.scala` 预译码模块
  - 对有效指令码进行预译码
  - 生成CFI指令类型、分支信息、jumpOffset

- `bosc_IFU/chisel/PredChecker.scala` 预译码检查模块
  - 检查预测错误，及时纠正
  - 包含两级流水（S1和S2）

- `bosc_IFU/chisel/IfuUncacheUnit.scala` Uncache处理单元
  - 从uncache总线提取指令
  - 判断并阻止MMIO指令的推测执行
  - 处理跨页情况

- `bosc_IFU/chisel/FrontendTrigger.scala` 触发器模块
  - 支持调试模式下的触发器设置
  - PC匹配（预译码和指令数据使用待补充）

- `bosc_IFU/chisel/RvcExpander.scala` RVC扩展模块
  - 将C指令转换为I指令
  - 检查C指令合法性

- `bosc_IFU/chisel/Helpers.scala` 辅助工具trait
  - PreDecodeHelper：预译码辅助函数
  - IfuHelper：IFU辅助函数

- `bosc_IFU/chisel/Parameters.scala` 参数定义
  - IfuParameters：IFU参数
  - HasIfuParameters：IFU参数trait

- `bosc_IFU/chisel/IfuPerfAnalysis.scala` 性能分析模块
  - 收集各种性能计数器
  - Top-Down性能分析
  - Debug数据库支持

- `bosc_IFU/chisel/F3PreDecode.scala` 预译码模块（未使用）
  - 注释说明似乎未使用，可能后续删除

## 顶层接口概览
- **模块名称**：`bosc_IFU` 顶层实体名/模块名（class Ifu）

- **端口列表**：

  | 信号组 | 方向 | 描述 |
  | ------ | ---- | ---- |
  | fromFtq | Input | FTQ到IFU接口（取指请求、重定向、刷新等） |
  | toFtq | Output | IFU到FTQ接口（写回、重定向、MMIO提交等） |
  | fromICache | Input | ICache到IFU接口（取指响应、性能信息等） |
  | toICache | Output | IFU到ICache接口（取指请求、暂停等） |
  | toUncache | Output | IFU到Uncache接口（MMIO请求） |
  | fromUncache | Input | Uncache到IFU接口（MMIO响应） |
  | toIBuffer | Output | IFU到IBuffer接口（指令入队） |
  | toBackend | Output | IFU到后端接口（gpaMem） |
  | frontendTrigger | Input | 前端触发器配置接口 |
  | csrFsIsOff | Input | CSR控制信号（F扩展是否关闭） |

- **时钟与复位要求**：
  - 3级流水线结构（S0-S3，不包括WB阶段）
  - 时钟域：单时钟域
  - 复位类型：待补充
  - 频率范围：待补充

- **外部依赖**：
  - FTQ：接收取指请求和重定向信号，当发现预译码与预测结果不符时也向FTQ发送重定向信号
  - ICache：获取指令数据，理论下一拍返回，但内部需要再打一拍
  - IBuffer：传递处理后的指令数据
  - uncache通路：处理非缓存指令取指（MMIO等）
  - 后端：接收后端重定向信号，gpaMem写接口

## 功能描述
> 将整体功能拆解为若干子模块或功能组，每组建议以二级标题呈现，包含正常流程、边界条件、异常处理。

### 流水线结构概述
IFU采用3级流水线结构（S0-S3），各级功能划分如下：

- **S0级**：计算预测块的指令范围和指令大小，计算PC序列低位信息（第二个预测块拼接在第一个预测块后面，需要偏移）
- **S1级**：进行指令定界，计算指令密集排布需要的指令索引，承担部分移位操作
- **S2级**：提取指令数据（32个读口，采用dup备份分散读口压力），进行预译码和预译码检查
- **S3级**：将整理的指令数据传输给IBuffer

### 指令定界与切分功能

- **概述**：负责将ICache传输过来的指令数据进行切分，确定预测块中每一条指令的位置，获得对应的有效指令数据

- **执行流程**：
  1. 接收来自ICache的指令数据（最大64字节，对应32条16位指令）
  2. 根据预测块的首地址（startAddr）和指令数据进行指令定界
  3. 标记指令的开头（instrValid序列）和末尾（instrEndVec序列）
  4. 生成isRVC标记，区分16位RVC指令和32位RVI指令
  5. 处理两个预测块的拼接情况（第二个预测块的PC信息需要偏移）

- **边界与异常**：
  - 跨页边界处理：cache指令跨页时分为两个预测块处理
  - 跨预测块边界：第一个预测块末尾可能是半条RVI指令，需要与第二个预测块拼接
  - 待确认：设计未明确当第一个预测块末尾为半条指令，第二个预测块末尾也为半条指令时的处理方式

- **性能与约束**：
  - 最大处理宽度：64字节（32条16位指令）
  - 指令定界采用多路推断再合并拼接的方式优化时序
  - 先计算0~15号指令位置，按两路假设计算16~31号位置，根据15号实际结果选择一路

#### 指令定界详细描述

InstrBoundary模块负责确定每条指令的位置，输入输出信号包括：

- **InstrRange信号**：初步缩减指令块的有效范围，指令数据可能由两个预测块拼接而成
- **isRVC序列**：在指令定界过程中自然产生，标记每条指令是否为RVC指令

**技术细节**：
- 以两字节为单位进行划分（指令最小单位为2字节）
- 对于64字节预测块，最多划分为长为32的序列
- 使用instrValid序列标记指令开头
- 使用instrEndVec序列标记指令末尾
- 序列中任何位置都可能标记为指令的开头和末尾

### 指令紧密排列计算

- **概述**：将稀疏分布的有效指令信息进行紧密排列，优化IBuffer入队时序

- **执行流程**：
  1. 根据instrValid序列计算instrCount序列（instrCount(i)代表instrValid(0)~instrValid(i-1)的sum）
  2. 将需要紧密排列的信号进行重新组织：
     - instrIndex：指令索引，用于从ICacheData中截取对应指令
     - selectBlock：选择信号，指示指令数据来自1号预测块还是2号预测块
     - isRVC：标记是否为RVC指令
     - pcLowerResult：PC低位信息
     - instrEndOffset：指令末尾地址相对于预测块的偏移值
  3. 根据instrCount进行紧密排列写入

- **边界与异常**：
  - 原始指令信息是稀疏分布的，需要筛选出真实有效的指令
  - 优化假设：有效指令之间不存在连续的无效指令

- **性能与约束**：
  - 原始instrIndex(i) = (startAddr + 2*i)(5,1)
  - 原始selectBlock(i) = i > 0号预测块的Size
  - instrEndOffset(i) = i + !isRVC（对于RVC指令，偏移就是i；对于RVI指令，偏移是i+1）

### 预译码功能

- **概述**：对有效指令码进行预译码，生成CFI指令类型、分支信息

- **执行流程**：
  1. PreDecoder接受有效指令码，每个指令查询预译码表产生预译码信息
  2. 生成预译码信息：
     - CFI指令类型（控制流指令类型）
     - 是否是RVC指令
     - 是否是Call指令
     - 是否是Ret指令
     - 分支指令的立即数Offset（jumpOffset）
  3. 对RVC指令进行扩展（RvcExpander模块）：
     - 将C指令转换为I指令
     - 检查C指令合法性，非法C指令输出ill标记
     - 非法C指令保持原数据，有效C指令输出扩展后的I指令

- **边界与异常**：
  - 非法C指令处理：保持原数据，记录异常原因
  - RVC指令转换：理论上所有C指令都可以转换为I指令，提前转换降低后续模块复杂度

- **性能与约束**：
  - 将C指令转换为I指令后，后续只需处理I指令
  - 预译码信息用于后续的预译码检查和分支预测

### 预译码检查功能

- **概述**：检查容易被发现的预测错误，及时纠正以提升性能

- **执行流程**：
  1. **预测方向检查**：
     - jal/jalr指令：一定跳转
     - 普通指令：一定不跳转（异常情况）
     - 发现预测错误时，裁剪预测块大小
  2. **目的地址检查**（可选）：
     - 普通指令：一定是顺序执行
     - jal指令和br指令：可以计算出目的地址
     - jalr函数返回指令：大概率知道目的地址
  3. **纠正策略**：
     - 对于预测块范围上的错误：能修正就修正
     - 对于目的地址错误：不修正，相信预测器
     - 如果发现预测块范围错误，提供计算出的目的地址

- **边界与异常**：
  - IFU无法获取正确的寄存器信息，因此jalr指令的目的地址无法完全确定

- **性能与约束**：
  - 越早发现预测错误，越早将指令流纠正回正确路径
  - 目的地址检查逻辑较长（PC+Offset计算+比较），可能需要打一拍
  - 待优化：将predChecker的计算提前一拍（如果时序允许）

### Uncache指令处理功能

- **概述**：从uncache总线提取指令，判断并阻止MMIO指令的推测执行

- **地址检查机制**：

  **概述**：uncache指令的地址检查分两个阶段进行，确保正确性和安全性。

  **第一阶段：ICache返回阶段**（S1级）
  ```
  s1_icacheMeta = VecInit.tabulate(FetchPorts)(i => Wire(new ICacheMeta).fromICacheResp(fromICache.bits))
  s1_icacheMeta(0).isUncache = pmpMmio || Pbmt.isUncache(itlbPbmt)
  ```
  - 检查内容：
    - pmpMmio：PMP检查，是否为物理内存映射的I/O
    - itlbPbmt：ITLB页表属性，检查页类型（NC、IO等）
    - isUncache = pmpMmio || Pbmt.isUncache(itlbPbmt)
  - 异常信息：
    - exception：页面异常（缺页、权限错误等）
    - pAddr：物理地址
    - gpAddr：Guest物理地址（虚拟化场景）

  **第二阶段：Uncache总线返回阶段**（S3级）
  ```
  uncacheException = ExceptionType.fromTileLink(fromUncache.bits.corrupt, fromUncache.bits.denied)
  ```
  - 检查内容：
    - corrupt：数据损坏标志
    - denied：访问被拒绝标志
  - 异常类型：TileLink总线协议异常

  **两次检查的关系**：
  - 第一次检查（ICache）：快速过滤，判断是否需要走uncache通路
  - 第二次检查（Uncache总线）：实际访问时的权限和异常检查
  - 两次检查可能产生不同的异常，需要分别处理

- **异常混合处理场景**：

  **场景1：ICache返回页面异常，uncache总线返回成功**
  - 处理：优先处理ICache异常
  - 结果：指令标记为ICache异常，不执行uncache总线请求
  - 代码：`s2_reqIsUncache = s2_valid && s2_icacheMeta(0).isUncache && s2_icacheMeta(0).exception.isNone`

  **场景2：ICache返回正常，uncache总线返回访问拒绝**
  - 处理：uncacheException传递给IBuffer
  - 结果：指令标记为异常，异常类型为TileLink异常
  - 代码：`io.toIBuffer.bits.exceptionType := uncacheException || uncacheRvcException`

  **场景3：ICache和uncache总线都返回异常**
  - 处理：uncache通路异常优先
  - 结果：指令标记为uncache异常
  - 原因：uncache通路是实际访问，异常更准确

  **场景4：ICache返回crossPage标志，uncache总线返回成功**
  - 处理：标记crossPage，进行数据拼接
  - 结果：指令数据拼接后传递给IBuffer
  - 代码：`s3_uncacheCrossPageMask = s3_valid && uncacheUnit.io.resp.valid && uncacheUnit.io.resp.bits.crossPage`

  **场景5：ICache返回crossPage标志，uncache总线返回异常**
  - 处理：异常优先，不进行数据拼接
  - 结果：指令标记为异常，crossPage被忽略
  - 检查：`uncacheCheckFault = uncacheCrossPage && !uncacheCrossPageCheck && uncacheUnit.io.resp.valid`

- **执行流程**：
  1. uncache状态机接收IFU的uncache请求
  2. **第一步**：判断是否为非MMIO
     - 非MMIO：直接向uncache通路发送请求并转第三步
     - MMIO：等待MMIO指令成为最旧指令并转第二步
  3. **第二步**：判断MMIO指令是否可以执行
     - 如果是处理器执行的第一条指令或最旧指令，转第三步
     - 否则继续等待
  4. **第三步**：等待uncache通道接收请求
     - 如果已接收，转第四步
     - 否则继续等待
  5. **第四步**：等待uncache通道返回数据
     - 如果收到数据，将数据回传到IFU主体进行处理
     - 否则继续等待
  6. **无条件冲刷**：接收Flush信号后，复位所有控制寄存器

- **边界与异常**：
  - **跨页处理**：
    - uncache总线总是返回64字节对齐的数据
    - 当指令跨64字节边界时，前端uncache通路发送两次请求
    - 当指令跨页时，两个页的物理地址可能不连续，前端返回crossPage标志
    - IFU需要做额外的拼接处理
  - **跨页情况下IFU主体处理**：
    - 如果预测器给出顺序取指：暂存半截指令数据，等待下一个预测块走完uncache流程，拼接两个预测块
    - 如果预测器给出跳转：暂存半截指令数据，发送重定向
  - **非跨页情况下**：一条指令在一个预测块中取完

- **性能与约束**：
  - uncache指令数据来自S3级，任何在S1、S2级依赖指令数据计算的结果都需重新审视
  - uncache需要的输入：
    - 物理地址：向uncache总线发出取指请求
    - ftqIdx：向FTQ查询预测块的提交状态
    - PMP结果：确认物理内存保护
    - PBMT结果：确认是否为需要推测阻塞的MMIO请求
  - 处理器执行的第一条指令不存在更旧指令，越过阻塞机制直接发送取指请求
  - 完成一条uncache取指后，不管预测器是否给出顺序执行都会发送重定向要求顺序执行（可能的优化点）

### Two Fetch支持功能

- **概述**：支持有限制的two Fetch机制，提升取指效率

- **限制条件**：
  1. 限制two Fetch的两个预测块的最大支持宽度为64字节（原因：最大取指宽度为64字节，复用一条IFU通路）
  2. 不同时处理包含uncache数据的two Fetch操作，至少间隔一拍
  3. 不同时处理第一个预测块存在LastHalfRVI情况

- **执行流程**：
  1. 将第二个预测块的指令数据拼接到第一个预测块的末尾
  2. 按照2字节划分，第二个预测块的指令数据和ICache返回的指令信息需要进行偏移操作

- **边界与异常**：
  - **待确认**：IFU的V3代码未更正第二个预测块的偏移操作，这是后续考虑点
  - IFU的two Fetch有待继续完善，更多问题有待进一步思考暴露

- **性能与约束**：
  - 融合操作：第二个预测块拼接到第一个预测块末尾
  - 偏移计算：需要考虑预测块边界对齐

### 触发器功能（Trigger）

- **概述**：支持调试模式下的触发器设置，配合后端Trigger模块实现断点调试

- **执行流程**：
  1. 遍历送入IBuffer的所有PC
  2. 根据matchType的匹配规则进行匹配
  3. 判断tdata.select是否为地址匹配目标
  4. 判断是否处于非debug模式
  5. 综合判断tdata.timing（触发时机）、tdata.chain（链式匹配）、tdata.action（触发动作）

- **边界与异常**：
  - 触发器不在调试模式下工作
  - 当同时触发进入调试模式和断点异常时，优先保证进入调试模式
  - 推荐：进入调试模式和生成断点异常都要发生

- **性能与约束**：
  - 触发寄存器仅在机器模式和调试模式下可设置
  - IFU中的trigger逻辑涉及送往IBuffer的PC对比
  - 待补充：预译码和指令数据使用目前在IFU中的Trigger还未支持
  - IFU的Trigger中有4个tdata寄存器，值由后端设置
  - 支持本地调试：不依赖外部调试器（JTAG），通过异常机制进行调试
  - 触发器可由用户态、监督态或机器态设置（M模式下需开发人员清晰知道操作）

### 外部信号处理与流水线控制

- **概述**：IFU需要处理多种外部控制信号，包括BPU冲刷、后端重定向、ICache反压、IBuffer反压等。这些信号直接影响流水线的执行和数据的正确性。

- **外部信号类型**：
  1. **BPU冲刷信号**（fromFtq.flushFromBpu）：
     - 来源：BPU（分支预测单元）
     - 作用：当BPU发现预测错误时，冲刷流水线
     - 影响：在S0级和S1级都可以触发冲刷

  2. **后端重定向信号**（fromFtq.redirect）：
     - 来源：后端（ROB、执行单元等）
     - 作用：当后端发现异常、分支预测错误等需要重定向时
     - 影响：可以冲刷S0-S3任意一级

  3. **内部重定向信号**：
     - wbRedirect：预译码检查发现预测错误产生的重定向
     - uncacheRedirect：uncache处理完成后产生的重定向
     - 影响：主要用于S3级和WB阶段

- **冲刷逻辑**：

  **各级冲刷信号计算**（优先级从高到低）：
  ```
  s3_flush := backendRedirect || (wbRedirect.valid && !s3_wbNotFlush)
  s2_flush := backendRedirect || uncacheRedirect.valid || wbRedirect.valid
  s1_flush := s2_flush || s1_flushFromBpu(0)
  s0_flush := s1_flush || s0_flushFromBpu(0)
  ```

  **冲刷传播规则**：
  - 后端重定向（backendRedirect）：最高优先级，可以冲刷所有级
  - wbRedirect：次高优先级，可以冲刷S2和S3
  - uncacheRedirect：可以冲刷S2和S3
  - BPU冲刷（s1_flushFromBpu, s0_flushFromBpu）：最低优先级，只影响S0和S1

- **冲刷后的行为**：

  1. **流水线寄存器复位**：
     - Valid信号清零：ValidHold逻辑在flush时清零valid
     - s1_valid、s2_valid、s3_valid都会被清零

  2. **状态寄存器处理**：
     ```
     when(backendRedirect) {
       s1_prevLastIsHalfRvi := false.B
     }.elsewhen(wbRedirect.valid) {
       s1_prevLastIsHalfRvi := wbRedirect.isHalfInstr
     }.elsewhen(uncacheRedirect.valid) {
       s1_prevLastIsHalfRvi := false.B
     }
     ```
     - 跨预测块半条指令状态（s1_prevLastIsHalfRvi）根据重定向类型更新
     - wbRedirect：保存半条指令信息
     - backendRedirect/uncacheRedirect：清零

  3. **IBuffer指针复位**：
     ```
     when(backendRedirect) {
       s2_prevIBufEnqPtr := 0.U.asTypeOf(new IBufPtr)
     }
     ```
     - 后端重定向时，IBuffer入队指针复位为0

  4. **Uncache状态机复位**：
     - 所有uncache状态机接收flush信号后无条件复位
     - uncacheUnit.io.flush := s3_flush

- **冲刷与时序的关系**：
  - BPU冲刷：S0级和S1级分别判断，使用shouldFlushByStage3
  - 后端重定向：影响整个流水线，包括uncache状态
  - 内部重定向：主要用于数据和指令流的纠正

### 反压处理与流控

- **概述**：IFU需要处理来自下游模块的反压信号，包括ICache响应延迟和IBuffer满载等情况。

- **ICache反压**：

  **问题描述**：
  - ICache响应时间不确定，可能需要多个周期
  - 理论下一拍返回，但时序不好，IFU内部需要再打一拍
  - 当ICache多拍未响应时，IFU需要暂停取指

  **处理逻辑**：
  ```
  s1_fire := s1_valid && s2_ready && s1_iCacheRespValid
  io.toICache.stall := !s2_ready
  fromFtq.req.ready := s1_ready && io.fromICache.fetchReady
  ```
  - s1_iCacheRespValid：ICache响应有效标志
  - s1_ready：S1级就绪（s1_fire || !s1_valid）
  - 当ICache未响应时（!s1_iCacheRespValid），s1_fire为false，s1_ready为true
  - 向ICache发送stall信号（!s2_ready）
  - 暂停接收新的FTQ请求（fromFtq.req.ready = false）

  **ICache断言检查**：
  ```
  iCacheMatchAssert(fromICache, s1_fetchBlock)
  ```
  - 确保ICache响应的地址与IFU请求的地址匹配

- **IBuffer反压**：

  **问题描述**：
  - IBuffer满载时无法接收新的指令
  - IFU需要在S3级暂停，等待IBuffer腾出空间

  **处理逻辑**：
  ```
  s3_fire := io.toIBuffer.fire
  s3_ready := (io.toIBuffer.ready && (s3_uncacheCanGo || !s3_reqIsUncache)) || !s3_valid
  ```
  - s3_fire：S3级发射（IBuffer接收数据）
  - s3_ready：S3级就绪
  - 当IBuffer未ready时，s3_ready为false，S3暂停发射

  **反压传播**：
  - S3暂停 → S2暂停（s2_ready = s2_fire || !s2_valid）
  - S2暂停 → S1暂停
  - S1暂停 → 暂停接收FTQ请求
  - 最终形成反压链

- **Uncache取指时的反压**：

  **问题描述**：
  - Uncache取指需要多个周期（MMIO阻塞、总线延迟）
  - 需要暂停正常的cache取指，等待uncache完成

  **处理逻辑**：
  ```
  io.toFtq.mmioCommitRead <> uncacheUnit.io.mmioCommitRead
  ```
  - 当uncache处理MMIO指令时，需要等待MMIO提交
  - 当前实现中MMIO阻塞被禁用（硬编码）
  - 待完善：需要与FTQ协调，确认MMIO指令是否为最旧指令

  **uncacheReady信号**：
  ```
  def uncacheReady: Bool = uncacheState === UncacheFsmState.Idle
  ```
  - 只有uncache状态机为Idle时，才能接收新的uncache请求
  - uncacheBusy时，暂停接收新的请求

- **反压与冲刷的交互**：

  **场景1：IBuffer反压时收到冲刷**
  - S3级暂停（IBuffer full）
  - 收到后端重定向（backendRedirect = true）
  - 处理：立即冲刷，s3_flush为true
  - S3级寄存器被清零或更新，但s3_fire为false（未向IBuffer写入）
  - 下一周期可以继续处理新的取指请求

  **场景2：ICache反压时收到冲刷**
  - S1级暂停（ICache未响应）
  - 收到BPU冲刷（s1_flushFromBpu = true）
  - 处理：s1_flush为true
  - S1级寄存器不被更新（RegEnable的enable为false）
  - 下一周期重新开始新的取指请求

  **场景3：Uncache处理时收到冲刷**
  - uncacheBusy为true
  - 收到flush信号（uncacheUnit.io.flush）
  - 处理：uncache状态机无条件复位
  - 丢弃当前的uncache请求
  - 重新接收新的取指请求

### IBuffer接口优化

- **概述**：通过IFU与IBuffer的特殊约定，缓解IBuffer入队时序压力

- **执行流程**：
  1. **Valid序列和enqEnable序列分离**：
     - Valid序列：直接提供给IBuffer的entry选择需要的有效指令
     - enqEnable序列：经过predChecker缩减了有效指令范围，用于最终确定是否写入IBuffer
  2. **IBuffer写分bank策略**：
     - IBuffer队列每项编号：ibuffer_mod_id = IBuffer编号 % 4
     - IFU入口指令编号：ifu_mod_id = IFU编号 % 4
     - IBuffer的entry只从对应的IBuffer_mod_id === ifu_mod_id项中选择
     - 从32选1优化为8选1
  3. **有效指令对齐**：
     - 将第一条指令偏移到当前IBuffer入队指针enqPtr % 4对应的位置
     - 最大偏移量是3
     - 提前计算prevIBufferEnqPtr

- **prevIBufferEnqPtr指针变化逻辑**：

  **概述**：prevIBufferEnqPtr是IFU维护的IBuffer入队指针预测值，用于指令对齐和enqEnable计算。该指针的正确性直接影响IBuffer的入队操作，必须与IBuffer的实际入队指针保持一致。

  **指针更新逻辑**（S2级）：
  ```
  when(backendRedirect) {
    s2_prevIBufEnqPtr := 0.U.asTypeOf(new IBufPtr)
  }.elsewhen(wbRedirect.valid) {
    s2_prevIBufEnqPtr := wbRedirect.prevIBufEnqPtr + wbRedirect.instrCount
  }.elsewhen(uncacheRedirect.valid) {
    s2_prevIBufEnqPtr := uncacheRedirect.prevIBufEnqPtr + uncacheRedirect.instrCount
  }.elsewhen(s2_fire) {
    s2_prevIBufEnqPtr := s2_prevIBufEnqPtr + s2_instrCount
  }
  ```

  **更新条件**：
  1. **backendRedirect**：后端重定向
     - 指针复位为0
     - 原因：后端重定向意味着之前的指令全部作废
     - 优先级：最高

  2. **wbRedirect.valid**：预译码检查发现预测错误
     - 指针 = wbRedirect.prevIBufEnqPtr + wbRedirect.instrCount
     - 恢复到预测错误之前的指针位置，加上已提交的指令数
     - wbRedirect.prevIBufEnqPtr：从WB阶段保存的指针值
     - wbRedirect.instrCount：WB阶段实际提交的指令数

  3. **uncacheRedirect.valid**：uncache处理完成
     - 指针 = uncacheRedirect.prevIBufEnqPtr + uncacheRedirect.instrCount
     - unacheRedirect.instrCount通常为1（单条uncache指令）
     - 恢复到uncache之前的指针位置，加上uncache指令数

  4. **s2_fire**：S2级正常发射
     - 指针 = s2_prevIBufEnqPtr + s2_instrCount
     - 正常累加当前周期入队的指令数
     - s2_instrCount = PopCount(rawInstrEndVec)

  **指针使用**：
  - **S2级**：计算对齐移位数
    ```
    s2_prevShiftSelect = UIntToMask(s2_prevIBufEnqPtr.value(1, 0), IfuAlignWidth)
    s2_alignShiftNum = s2_prevIBufEnqPtr.value(1, 0)
    ```
  - **S3级**：传递给IBuffer
    ```
    io.toIBuffer.bits.prevIBufEnqPtr := s3_prevIBufEnqPtr
    ```
  - **IBuffer**：用于计算实际入队位置和指针推进

  **关键约束**：
  - 指针单调递增（除了复位）
  - 必须与IBuffer的实际入队指针同步
  - 任何重定向都必须正确更新指针
  - **验证重点**：各种重定向场景下的指针恢复逻辑

- **边界与异常**：
  - 要求：IFU送入的有效指令必须是连续的
  - 稀疏的指令排布会打破对应的默契

- **性能与约束**：
  - enqPtr值是有效指令数量的不停累加
  - 遇到后端重定向时，enqPtr的值复位为0
  - IFU能够确定送入IBuffer的有效指令数量
  - IFU也会接收来自后端的重定向
  - IFU可以提前计算prevIBufferEnqPtr

### 子组件描述

根据文档分析，IFU包含以下子组件，每个子组件都有独立的spec文档：

#### InstrBoundary组件

负责指令定界，确定每条指令的位置。通过标记指令的开头（instrValid序列）和末尾（instrEndVec序列），支持两路推断再合并拼接的优化策略。

具体请参考文档 `unity_test/bosc_IFU_spec_InstrBoundary.md`

#### PreDecoder组件

负责预译码，生成CFI指令类型、分支信息、jumpOffset等。包含RvcExpander子模块，将C指令转换为I指令。

具体请参考文档 `unity_test/bosc_IFU_spec_PreDecoder.md`

#### PredChecker组件

负责预译码检查，及时发现并纠正预测错误，包括预测方向检查和目的地址检查。采用两级流水线结构，Stage 1检测remask fault并调整预测块范围，Stage 2准备重定向信息。

具体请参考文档 `unity_test/bosc_IFU_spec_PredChecker.md`

#### Uncache组件

负责从uncache总线提取指令，判断并阻止MMIO指令的推测执行，处理跨页情况。采用4状态FSM实现（Idle、WaitLastCommit、SendReq、WaitResp）。

具体请参考文档 `unity_test/bosc_IFU_spec_Uncache.md`

#### Trigger组件

负责调试模式下的触发器设置，配合后端Trigger模块实现断点调试。支持4个tdata寄存器，基于PC匹配，支持timing、chain、action等触发控制。

具体请参考文档 `unity_test/bosc_IFU_spec_Trigger.md`

### 状态机与时序
- **状态机列表**：
  - **Uncache状态机**：包含4个状态
    - Step 1：接收请求并判断MMIO/非MMIO
    - Step 2：等待MMIO指令成为最旧指令（如果是MMIO）
    - Step 3：等待uncache通道接收请求
    - Step 4：等待uncache通道返回数据
    - 无条件冲刷：接收到Flush信号后复位所有控制寄存器

- **关键时序图**：
  - **取指流程时序**：
    - S0：接收取指请求 → 计算指令范围
    - S1：指令定界 → 计算指令索引
    - S2：提取指令数据 → 预译码 → 预译码检查
    - S3：传输到IBuffer
  - **ICache访问时序**：理论下一拍返回，内部需要再打一拍
  - **IBuffer入队时序**：通过Valid序列和enqEnable序列分离优化
  - **跨页处理时序**：可能需要两个预测块拼接

### 配置寄存器及存储
| 寄存器名/地址 | 访问属性 | 位段 | 缺省值 | 描述 | 读写副作用 |
| ------------- | -------- | ---- | ------ | ---- | ---------- |
| （待补充） | RW | [N:0] | 0x00 | 功能说明 | 无 |

- **寄存器映射基地址**：待补充（如有总线接口APB/AHB/AXI）

- **配置流程**：待补充

### 复位与错误处理
- **复位行为**：
  - 电源/逻辑复位：待补充
  - 软复位：待补充
  - 后端重定向：enqPtr复位为0

- **错误上报**：
  - 非法C指令：输出ill标记，保持原数据
  - 预测错误：发送重定向信号到FTQ
  - 待补充其他错误信号和状态寄存器

- **自恢复策略**：
  - Uncache状态机：接收Flush信号后无条件复位
  - 预测错误纠正：裁剪预测块大小或发送重定向

### 功耗、时钟与电源管理（如适用）
- **功耗模式**：待补充

- **时钟门控**：
  - 由于有效指令进行了紧密排列，虽然有32个指令信息存储位置，但可以进行较为精细的时钟门控操作
  - 待补充具体的时钟门控策略

- **电源域**：待补充

### 参数化与可配置特性
- **模块参数**：

  | 参数名 | 类型/取值范围 | 默认值 | 功能影响 |
  | ------ | ------------- | ------ | -------- |
  | PcCutPoint | Option[Int] | VAddrBits/4-1 | PC切割点，用于PC高位和低位的划分 |
  | ICacheLineBytes | Int | 从ICache参数获取 | ICache行字节数，决定取指块大小 |
  | IfuAlignWidth | Int | IBuffer写bank数量 | IFU对齐宽度，用于IBuffer入队对齐 |
  | IfuIdxWidth | Int | log2Ceil(IBufferEnqueueWidth) | IFU索引宽度 |
  | FetchPorts | Int | 待补充 | 取指端口数量，支持two Fetch |
  | IBufferEnqueueWidth | Int | 待补充 | IBuffer入队宽度 |
  | FetchBlockInstNum | Int | 待补充 | 预测块最大指令数 |
  | FetchBlockInstOffsetWidth | Int | log2Ceil(FetchBlockInstNum) | 预测块指令偏移宽度 |
  | TriggerNum | Int | 待补充 | 触发器数量 |
  | HasCExtension | Boolean | true | 是否支持C扩展 |

- **编译宏/生成选项**：
  - HasCExtension：必须为true（XiangShan中C扩展不能禁用）

## 测试场景与边界条件

> 本章节列出关键测试场景和边界条件，帮助验证人员设计测试用例。

### 跨页与跨预测块测试场景

- **场景1：单个预测块内无跨页**
  - 描述：指令都在同一个页内，预测块完整
  - 测试点：指令定界正确性、IBuffer入队正确性

- **场景2：单个预测块末尾跨页**
  - 描述：最后一个32位RVI指令跨越页边界
  - 测试点：
    - s1_prevLastIsHalfRvi设置正确
    - wbRedirect.isHalfInstr正确
    - 下一预测块的拼接逻辑
  - **注意**：这是难点，需要充分测试

- **场景3：两个预测块都跨页**
  - 描述：第一个预测块末尾和第二个预测块末尾都跨页
  - 测试点：
    - 连续两次跨页的处理
    - prevUncacheCrossPage和prevUncacheData的更新
    - 指针拼接的正确性
  - **注意**：设计未明确，需要RTL确认和重点测试

- **场景4：跨预测块边界非跨页**
  - 描述：第一个预测块末尾是半条RVI指令，但第二个预测块完整
  - 测试点：s1_prevLastIsHalfRvi和wbRedirect的交互

### Uncache与普通预测块混合测试场景

- **场景5：Cache取指 → Uncache取指 → Cache取指**
  - 描述：正常的cache取指后遇到uncache指令，然后继续cache取指
  - 测试点：
    - s2_reqIsUncache判断
    - uncacheRedirect处理
    - prevIBufEnqPtr恢复逻辑
  - **验证方法**：构造指令序列，第一条为cache指令，第二条为MMIO指令，第三条为cache指令

- **场景6：连续两条Uncache指令**
  - 描述：两条uncache指令连续出现
  - 测试点：
    - MMIO阻塞机制（虽然当前禁用）
    - uncacheReady控制
    - uncacheBusy状态
  - **验证方法**：构造两条MMIO指令，验证第二条等待第一条完成

- **场景7：Cache取指和Uncache取指交替（间隔）**
  - 描述：cache、uncache、cache、uncache交替出现
  - 测试点：
    - uncacheRedirect后的指针恢复
    - prevIBufEnqPtr的累加和恢复逻辑
  - **验证方法**：构造指令序列，验证每次切换后prevIBufEnqPtr的正确性

- **场景8：Uncache取指遇到BPU冲刷**
  - 描述：uncache处理中收到BPU冲刷信号
  - 测试点：
    - uncacheUnit.io.flush处理
    - uncache状态机复位
    - 重新开始cache取指
  - **验证方法**：在uncacheBusy时发送BPU冲刷，验证状态机复位

- **场景9：Uncache取指遇到后端重定向**
  - 描述：uncache处理中收到后端重定向
  - 测试点：
    - s3_flush处理
    - uncache结果被丢弃
    - prevIBufEnqPtr复位
  - **验证方法**：在uncache处理时发送后端重定向

### 外部信号交互测试场景

- **场景10：ICache多拍未响应（BUBBL）**
  - 描述：ICache响应慢，需要多个周期
  - 测试点：
    - s1_iCacheRespValid延迟
    - S1级暂停
    - 反压传播到FTQ
  - **验证方法**：模拟ICache延迟，验证s1_ready和fromFtq.req.ready

- **场景11：IBuffer满载时收到正常Cache指令**
  - 描述：IBuffer满，S3暂停
  - 测试点：
    - s3_ready = false
    - 反压传播（S3→S2→S1→FTQ）
    - S2级寄存器保持（RegEnable不更新）
  - **验证方法**：设置IBuffer.notReady，验证反压链

- **场景12：IBuffer满载时收到后端重定向**
  - 描述：IBuffer满，同时收到后端重定向
  - 测试点：
    - s3_flush = true（优先级高）
    - S3寄存器被清零或更新
    - prevIBufEnqPtr复位
  - **验证方法**：同时设置IBuffer.notReady和backendRedirect，验证flush优先级

- **场景13：BPU冲刷与后端重定向同时发生**
  - 描述：BPU发现预测错误，同时后端也发送重定向
  - 测试点：
    - backendRedirect优先级高于s1_flushFromBpu
    - s1_flush = s2_flush || s1_flushFromBpu
    - S1级寄存器不更新（被冲刷）
  - **验证方法**：同时触发BPU冲刷和backendRedirect，验证最终状态

- **场景14：多个重定向信号连续发生**
  - 描述：backendRedirect → wbRedirect → uncacheRedirect连续发生
  - 测试点：
    - 重定向优先级和覆盖规则
    - prevIBufEnqPtr的多次更新
    - s1_prevLastIsHalfRvi的更新逻辑
  - **验证方法**：连续发送多个重定向，验证最终的指针状态

### prevIBufEnqPtr指针测试场景

- **场景15：正常累加（无重定向）**
  - 描述：连续多个周期正常取指入队
  - 测试点：
    - s2_prevIBufEnqPtr每次累加s2_instrCount
    - s2_instrCount = PopCount(rawInstrEndVec)
    - 指针单调递增
  - **验证方法**：监控prevIBufEnqPtr.value，验证每次入队后的累加值

- **场景16：后端重定向后的指针恢复**
  - 描述：prevIBufEnqPtr在某个值时收到后端重定向
  - 测试点：
    - s2_prevIBufEnqPtr复位为0
    - 后续指令的指针从0开始累加
  - **验证方法**：在指针不为0时发送backendRedirect，验证指针复位

- **场景17：预测错误重定向后的指针恢复**
  - 描述：prevIBufEnqPtr在某个值时发现预测错误
  - 测试点：
    - 指针 = wbRedirect.prevIBufEnqPtr + wbRedirect.instrCount
    - 恢复到预测错误之前的指针位置
    - 加上WB阶段实际提交的指令数
  - **验证方法**：模拟预测错误，验证指针恢复的准确性

- **场景18：Uncache重定向后的指针恢复**
  - 描述：prevIBufEnqPtr在某个值时处理uncache指令
  - 测试点：
    - 指针 = uncacheRedirect.prevIBufEnqPtr + uncacheRedirect.instrCount
    - uncacheRedirect.instrCount通常为1
  - **验证方法**：处理uncache指令，验证指针恢复逻辑

- **场景19：指针对齐（mod 4）验证**
  - 描述：验证prevIBufEnqPtr.value(1,0)用于对齐
  - 测试点：
    - s2_alignShiftNum = s2_prevIBufEnqPtr.value(1,0)
    - 对齐偏移量正确（0-3）
    - 指令数据对齐正确
  - **验证方法**：测试指针为0,1,2,3时的对齐效果

### 异常混合测试场景

- **场景20：ICache页面异常 + Uncache总线正常**
  - 描述：指令有页面异常，但走uncache通路时总线返回成功
  - 测试点：
    - s2_reqIsUncache检查（exception.isNone）
    - 不执行uncache请求
    - 标记为ICache异常
  - **验证方法**：配置ICache返回exception.isNone=false

- **场景21：ICache正常 + Uncache总线访问拒绝**
  - 描述：指令无页面异常，但uncache总线返回denied
  - 测试点：
    - uncacheException传递给IBuffer
    - 异常类型为TileLink异常
  - **验证方法**：配置uncache总线返回denied=true

- **场景22：ICache异常 + Uncache总线异常**
  - 描述：两次检查都返回异常
  - 测试点：
    - uncache异常优先（实际访问）
    - 异常类型为TileLink异常
  - **验证方法**：同时配置ICache和uncache异常

- **场景23：RVC扩展异常 + 其他异常**
  - 描述：RVC指令非法，同时有其他异常（如页面异常）
  - 测试点：
    - s3_rvcException计算
    - 异常优先级处理
    - exceptionOffset计算
  - **验证方法**：构造非法RVC指令，同时触发其他异常

## 验证需求与覆盖建议
- **功能覆盖点**：对应 FG/FC/CK 标签，说明应验证的场景和预期结果
  - 待补充：基于后续的功能分组和检测点设计

- **约束与假设**：
  - 最大取指宽度：64字节
  - 预测块最大宽度：64字节
  - 指令最小单位：2字节（16位）
  - two Fetch限制条件
  - 待补充其他约束

- **测试接口**：
  - FTQ接口：取指请求、重定向信号
  - ICache接口：指令数据
  - IBuffer接口：处理后的指令数据
  - uncache通路接口
  - MMIO总线接口
  - 待补充驱动接口、监视点、参考模型等依赖

## 潜在 bug 分析

> 汇总目前已知或推测存在风险的设计区域，方便后续验证重点聚焦。若暂无信息，请写明"暂缺"。

### 第二个预测块偏移操作未实现（置信度 80%）
- **触发条件**：使用two Fetch功能时，第二个预测块的指令数据拼接到第一个预测块末尾
- **影响范围**：可能导致第二个预测块的指令数据和ICache返回的指令信息不正确，影响指令提取和预译码
- **关联位置**：IFU主体，two Fetch融合操作部分（文档未提供具体代码位置）
- **验证建议**：
  1. 补充two Fetch功能的测试用例，验证第二个预测块的偏移操作
  2. 检查拼接后指令数据的正确性
  3. 验证指令索引和PC信息的正确计算

### 跨预测块边界半条指令处理未明确（置信度 70%）
- **触发条件**：第一个预测块末尾为半条RVI指令，第二个预测块末尾也为半条RVI指令
- **影响范围**：可能导致指令定界错误，影响后续指令提取和预译码
- **关联位置**：InstrBoundary模块，指令定界逻辑（文档未提供具体代码位置）
- **验证建议**：
  1. 补充边界测试用例，覆盖两个预测块都存在半条指令的情况
  2. 验证拼接后指令定界的正确性
  3. 检查instrValid和instrEndVec序列的正确性

### Uncache指令跨页处理逻辑复杂（置信度 60%）
- **触发条件**：uncache指令跨越页边界，两个页的物理地址不连续
- **影响范围**：可能导致指令数据拼接错误，影响指令提取
- **关联位置**：Uncache模块，跨页处理逻辑（文档未提供具体代码位置）
- **验证建议**：
  1. 补充uncache跨页测试用例，验证拼接逻辑
  2. 检查crossPage标志的正确处理
  3. 验证顺序取指和跳转两种情况下的拼接策略

### PredChecker目的地址检查未实现（置信度 50%）
- **触发条件**：jal指令、br指令、jalr函数返回指令的目的地址预测错误
- **影响范围**：虽然不纠正目的地址，但可能存在性能损失；如果时序允许可以实现
- **关联位置**：PredChecker模块，目的地址检查逻辑（文档未提供具体代码位置）
- **验证建议**：
  1. 评估目的地址检查的时序影响
  2. 如果实现，补充目的地址比较的测试用例
  3. 验证PC+Offset计算的准确性

### IBuffer入队对齐假设约束（置信度 50%）
- **触发条件**：IFU送入IBuffer的有效指令不连续
- **影响范围**：破坏IFU与IBuffer的特殊约定，导致IBuffer entry选择错误
- **关联位置**：指令紧密排列计算模块，IBuffer接口（文档未提供具体代码位置）
- **验证建议**：
  1. 验证所有情况下IFU输出的有效指令都是连续的
  2. 检查instrIndex、selectBlock等信号的紧密排列逻辑
  3. 验证IBuffer_mod_id与ifu_mod_id的对应关系

### 预译码C指令扩展后的时序问题（置信度 40%）
- **触发条件**：RVC指令转换为I指令后，后续流水线处理
- **影响范围**：可能存在时序压力，需要额外的流水线级
- **关联位置**：RvcExpander模块，PreDecoder模块（文档未提供具体代码位置）
- **验证建议**：
  1. 评估C指令扩展的时序影响
  2. 验证扩展后指令数据的正确性
  3. 检查非法C指令的处理逻辑

### Trigger功能未完全实现（置信度 30%）
- **触发条件**：使用预译码信息或指令数据进行触发匹配
- **影响范围**：当前IFU的Trigger只支持PC对比，预译码和指令数据使用还未支持
- **关联位置**：Trigger模块（文档未提供具体代码位置）
- **验证建议**：
  1. 明确Trigger功能的完整需求
  2. 如果需要扩展预译码和指令数据支持，补充相关测试
  3. 验证4个tdata寄存器的匹配逻辑

### 待补充项
- 面积和时钟门控未过多考虑（文档明确说明是代码稳定后的优化点）
- MMIO状态机处理细节待补充
- 寄存器配置和初始化流程待补充
- 错误上报和异常处理机制待补充
