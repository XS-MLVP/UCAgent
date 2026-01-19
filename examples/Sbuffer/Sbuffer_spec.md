# SBuffer 规格说明文档

> 本模板用于指导编写 `SBuffer` 芯片验证对象的规格说明书。请按照每个小节的提示补充内容，保持技术语言准确、条理清晰、便于验证复用。若某项内容不存在，请显式写明"无"或"暂缺"，不要删除章节。

## 简介
- **设计背景**：SBuffer（Store Buffer）是处理器中的存储提交缓冲模块，用于缓冲存储指令的数据，提高存储性能。主要功能包括合并存储请求、管理缓存行状态、提供前递数据给Load单元，以及将数据写回到DCache。上游模块为StoreQueue，下游模块为DCache。
- **版本信息**：当前规格版本v1.0，适配RTL版本基于XiangShan处理器实现。
- **设计目标**：提供高效的存储缓冲机制，支持存储合并、前递数据、有序写回，确保存储顺序正确性和数据一致性。

## 术语与缩写
| 缩写 | 全称 | 说明 |
| ---- | ---- | ---- |
| SBuffer | Store Buffer | 存储提交缓冲 |
| DCache | Data Cache | 数据缓存 |
| ptag | Physical Tag | 物理地址标签 |
| vtag | Virtual Tag | 虚拟地址标签 |
| vword | Vector Word | 向量字（16字节） |
| cacheline | Cache Line | 缓存行（64字节） |

## RTL源文件

对涉及文件进行简要说明。

文件列表：
- <ref_file>Sbuffer/Sbuffer.scala</ref_file> SBuffer主TOP文件，实现核心控制逻辑和状态管理
- <ref_file>Sbuffer/SbufferData.v</ref_file> SBuffer数据存储模块，管理数据和掩码存储
- <ref_file>Sbuffer/Sbuffer.v</ref_file> SBuffer Verilog实现文件
- <ref_file>Sbuffer/ValidPLRUWrapper.v</ref_file> 伪LRU替换策略包装器

## 顶层接口概览
- **模块名称**：`SBuffer` 顶层实体名/模块名。
- **端口列表**：

  | 信号名 | 方向 | 位宽/类型 | 复位值 | 描述 |
  | ------ | ---- | -------- | ------ | ---- |
  | io_hartId | input | UInt(hartIdLen.W) | 0 | 硬件线程ID |
  | io_in | input | Vec[EnsbufferWidth, Decoupled[DCacheWordReqWithVaddrAndPfFlag]] | 0 | 从StoreQueue接收的存储请求接口，支持EnsbufferWidth个并发请求 |
  | io_dcache | output | DCacheToSbufferIO | 0 | 与DCache的交互接口，包含请求和响应 |
  | io_forward | input | Vec[LoadPipelineWidth, LoadForwardQueryIO] | 0 | 来自Load单元的前递查询接口 |
  | io_sqempty | input | Bool() | 0 | StoreQueue空标志 |
  | io_sbempty | output | Bool() | 0 | SBuffer空标志 |
  | io_flush | input | SbufferFlushBundle | 0 | flush sbuffer控制接口 |
  | io_csrCtrl | input | CustomCSRCtrlIO | 0 | CSR控制接口 |
  | io_store_prefetch | output | Vec[StorePipelineWidth, DecoupledIO[StorePrefetchReq]] | 0 | 存储预取请求到DCache |
  | io_memSetPattenDetected | input | Bool() | 0 | 内存模式检测标志 |
  | io_force_write | input | Bool() | 0 | 强制写标志 |
  | io_diffStore | input | DiffStoreIO | 0 | 差分存储接口 |

- **时钟与复位要求**：单时钟域设计，支持同步复位。复位时所有状态寄存器清零，缓存行数据保持不变但掩码清零。
- **外部依赖**：依赖StoreQueue提供存储请求，DCache处理写回，Load单元进行前递查询，atomicsUnit和fenceUnit提供flush信号。

## 功能描述
> 将整体功能拆解为若干子模块或功能组，每组建议以二级标题呈现，包含正常流程、边界条件、异常处理。

### 入队管理功能组
- **概述**：处理来自StoreQueue的存储请求，执行合并检查和新项分配逻辑。支持3级流水线处理（S0/S1/S2）。
- **执行流程**：
  1. **S0阶段**：读取StoreQueue数据，存储到2-entry FIFO队列
  2. **S1阶段**：从FIFO读取数据，更新SBuffer元数据（vtag、ptag、标志），阻止该entry发送到DCache，准备缓存行级写使能信号
  3. **S2阶段**：使用缓存行级缓冲器更新SBuffer数据和掩码，移除DCache写阻塞
  4. 每周期最多处理EnsbufferWidth个存储请求
  5. 如果两个请求都需要分配且ptag相同，分配到同一个entry
  6. 如果已有相同cacheline的entry且非inflight状态，进行合并
  7. 设置entry状态为valid
- **边界与异常**：当相同cacheline的entry处于inflight状态时，需要分配新entry并设置依赖关系（w_sameblock_inflight=true）。
- **性能与约束**：支持EnsbufferWidth个并发请求处理，3级流水线延迟。

#### 入队请求处理

接收StoreQueue请求，执行地址比较和合并逻辑。支持sb、sh、sw、sd等不同宽度的存储操作。地址解析函数：<ref_file>Sbuffer/Sbuffer.scala:239-255</ref_file>

#### Entry分配策略

按照奇偶策略分配空闲entry，提高并行度和减少冲突。使用enbufferSelReg寄存器在奇偶之间交替选择：<ref_file>Sbuffer/Sbuffer.scala:363-377</ref_file>

#### 合并检查逻辑

通过mergeMask检查是否可以合并到已有entry：<ref_file>Sbuffer/Sbuffer.scala:325-335</ref_file>

#### 状态管理

每个entry包含完整的状态信息：<ref_file>Sbuffer/Sbuffer.scala:214-222</ref_file>
- ptag: 物理地址tag
- vtag: 虚拟地址tag  
- state: entry状态（valid/inflight/timeout/sameblock_inflight）
- waitInflightMask: 等待inflight的mask
- cohCount: 一致性计数器
- missqReplayCount: 重试计数器

### 出队管理功能组
- **概述**：管理SBuffer中entry的写出到DCache，支持被动和主动触发。使用伪LRU算法选择替换entry。
- **执行流程**：
  1. **被动触发**：当ActiveCount >= forceThreshold或ActiveCount === (StoreBufferSize-1)或ValidCount === StoreBufferSize时触发替换
  2. **主动触发**：atomicsUnit/fenceUnit flush信号、合并冲突、miss重发等
  3. 两拍操作：第一拍选择要写出的entry（sbuffer_out_s0），第二拍发送写请求（sbuffer_out_s1）
  4. 使用ValidPseudoLRU算法选择替换候选：<ref_file>Sbuffer/Sbuffer.scala:270-281</ref_file>
- **边界与异常**：处理DCache miss响应，支持重试机制，最多重试16次（SbufferReplayDelayCycles）。
- **性能与约束**：写回延迟2周期，支持并发处理多个写响应。阈值可配置：<ref_file>Sbuffer/Sbuffer.scala:537-544</ref_file>

#### 写回选择逻辑

根据状态、计数器和外部信号选择合适的entry进行写回。候选向量生成：<ref_file>Sbuffer/Sbuffer.scala:273</ref_file>

#### Miss重试机制

当DCache返回miss时，启动missqReplayCount计数器，延迟后重新发送请求：<ref_file>Sbuffer/Sbuffer.scala:290-293</ref_file>

#### DCache响应处理

处理hit响应和replay响应：<ref_file>Sbuffer/Sbuffer.scala:712-762</ref_file>
- hit响应：清除inflight和valid状态，清理掩码
- replay响应：设置w_timeout标志，重置missqReplayCount

#### 状态机管理

4个状态的状态机：<ref_file>Sbuffer/Sbuffer.scala:232-233</ref_file>
- x_idle：空闲状态
- x_replace：替换状态  
- x_drain_all：排空所有（StoreQueue+SBuffer）
- x_drain_sbuffer：仅排空SBuffer

状态转换逻辑：<ref_file>Sbuffer/Sbuffer.scala:552-583</ref_file>

### 数据写入功能组
- **概述**：管理SBuffer中数据和掩码的写入操作。
- **执行流程**：
  1. 第一拍：锁存请求信息和写入编码
  2. 第二拍：根据mask写入相应数据并设置掩码位
- **边界与异常**：处理部分字写入，确保只更新有效的字节。
- **性能与约束**：2周期写入延迟，支持向量数据写入。

#### 数据与掩码管理

每个cacheline包含4个vwords，每个vword为16字节，每个byte有对应的mask位。

#### 写入时序控制

精确控制数据和掩码的写入时机，确保数据一致性。

### 前递查询功能组
- **概述**：为Load单元提供存储数据的前递服务。支持LoadPipelineWidth个并发前递查询。
- **执行流程**：
  1. 接收Load查询请求（物理地址和虚拟地址）
  2. 并行比较所有entry的vtag和ptag
  3. 检测vtag和ptag不匹配的情况，触发微架构排空
  4. 根据年龄优先级选择最新的匹配数据
  5. 1周期延迟返回前递数据
- **边界与异常**：无ready信号，查询请求必须立即处理。当检测到tag不匹配时，触发forward_need_uarch_drain。
- **性能与约束**：固定1周期响应延迟，支持LoadPipelineWidth个并发查询。

#### Tag比较逻辑

同时比较物理地址tag和虚拟地址tag，确保匹配准确性：<ref_file>Sbuffer/Sbuffer.scala:782-788</ref_file>
- vtag_matches：使用虚拟地址tag进行初筛
- ptag_matches：使用物理地址tag进行精确匹配
- tag_mismatch：检测vtag和ptag不匹配的情况

#### 优先级仲裁

根据entry的年龄信息确定数据新旧程度，优先返回最新数据。

#### 微架构排空

当检测到tag不匹配时，触发微架构排空：<ref_file>Sbuffer/Sbuffer.scala:789-792</ref_file>
- 设置forward_need_uarch_drain标志
- 转换到x_drain_sbuffer状态
- 确保地址一致性

### 子组件描述

SBuffer包含多个功能独立的子组件，分别负责不同的功能模块。

#### 组件 SbufferData

负责SBuffer中数据和掩码的存储管理，包括数据写入、掩码更新和清理功能。

具体请参考文档 `<ref_file>unity_test/Sbuffer_spec_SbufferData.md</ref_file>`

#### 组件 ValidPLRUWrapper

实现伪LRU替换策略，用于选择合适的entry进行替换和写回。

具体请参考文档 `<ref_file>unity_test/Sbuffer_spec_ValidPLRUWrapper.md</ref_file>`

### 状态机与时序
- **状态机列表**：
  - **x_idle**：空闲状态，等待请求或触发条件
  - **x_drain_sbuffer**：清空SBuffer状态，响应flush请求
  - **x_replace**：替换状态，执行被动写回
- **关键时序图**：
  - **入队时序**：2周期处理，握手+锁存+写入
  - **出队时序**：2周期处理，选择+发送请求
  - **前递时序**：1周期响应，查询+数据返回

### 配置寄存器及存储
| 寄存器名/地址 | 访问属性 | 位段 | 缺省值 | 描述 | 读写副作用 |
| ------------- | -------- | ---- | ------ | ---- | ---------- |
| cohCount | 内部 | [19:0] | 0x00000 | 一致性计数器，达到1M时触发写回 | 自动递增，写回时清零 |
| missqReplayCount | 内部 | [4:0] | 0x00000 | 重试计数器，达到16时重发请求 | miss时递增，重发时清零 |
- **寄存器映射基地址**：无直接总线接口，通过内部寄存器管理状态。
- **配置流程**：上电复位时所有状态寄存器清零，运行时由硬件自动管理。

### 复位与错误处理
- **复位行为**：同步复位，清零所有状态寄存器和掩码，数据保持不变。
- **错误上报**：通过状态位报告超时、重试等异常情况。
- **自恢复策略**：支持自动重试机制，最多重试16次，超时后重新发送请求。

### 功耗、时钟与电源管理（如适用）
- **功耗模式**：暂缺
- **时钟门控**：暂缺
- **电源域**：单电源域设计

### 参数化与可配置特性
- **模块参数**：

  | 参数名 | 类型/取值范围 | 默认值 | 功能影响 |
  | ------ | ------------- | ------ | -------- |
  | StoreBufferSize | {16,32,64} | 16 | SBuffer entry数量，影响缓冲容量 |
  | CacheLineSize | 64,128,256 | 64 | 缓存行大小，影响存储粒度 |
  | EvictCycles | 2^20 | 1048576 | 写回阈值周期数 |

- **编译宏/生成选项**：支持不同的StoreBufferSize配置。

## 验证需求与覆盖建议
- **功能覆盖点**：
  - 入队合并逻辑覆盖
  - 出队替换策略覆盖  
  - 前递查询优先级覆盖
  - Miss重试机制覆盖
- **约束与假设**：输入请求必须满足时序要求，DCache响应延迟在合理范围内。
- **测试接口**：需要StoreQueue驱动器、DCache模型、Load单元监视器。

## 潜在 bug 分析

> 汇总目前已知或推测存在风险的设计区域，方便后续验证重点聚焦。若暂无信息，请写明"暂缺"。

- **风险列表**：按照"问题标题（置信度 %）"列出潜在缺陷，建议包含以下要素：
  1. **触发条件**：描述在何种输入、时序或配置下可能出现问题；如有相关测试或场景编号请引用。
  2. **影响范围**：说明对功能、性能、功耗或安全性的潜在影响。
  3. **定位线索**：给出可能关联的 RTL 文件、代码行或子模块，必要时附上伪代码/逻辑片段。
  4. **验证建议**：提出需要补充的测试、断言、监控点或覆盖项。

### 并发入队竞争条件（置信度 45%）
- **触发条件**：当EnsbufferWidth > 1时，多个并发入队请求可能竞争同一个entry的分配或合并。
- **影响范围**：可能导致数据丢失或状态不一致，影响存储顺序的正确性。
- **关联位置**：<ref_file>Sbuffer/Sbuffer.scala:363-382</ref_file> 中的奇偶分配逻辑，<ref_file>Sbuffer/Sbuffer.scala:325-335</ref_file> 中的合并检查逻辑。
- **验证建议**：
  1. 增加并发入队冲突测试用例
  2. 验证相同ptag请求的合并行为
  3. 检查奇偶分配的互斥性

### Tag不匹配处理延迟（置信度 40%）
- **触发条件**：Load前递查询时检测到vtag和ptag不匹配，触发微架构排空，但处理可能存在延迟。
- **影响范围**：可能导致Load单元获得错误的前递数据，影响程序正确性。
- **关联位置**：<ref_file>Sbuffer/Sbuffer.scala:789-792</ref_file> 中的tag不匹配检测和排空触发逻辑。
- **验证建议**：
  1. 增加tag不匹配场景测试
  2. 验证微架构排空的时序正确性
  3. 检查排空期间的前递行为

### DCache响应处理竞争（置信度 35%）
- **触发条件**：多个DCache响应同时到达时，状态更新和掩码清理可能出现竞争。
- **影响范围**：可能导致状态机状态错误或掩码不一致，影响后续操作。
- **关联位置**：<ref_file>Sbuffer/Sbuffer.scala:712-762</ref_file> 中的DCache响应处理逻辑。
- **验证建议**：
  1. 增加并发DCache响应测试
  2. 验证状态更新的原子性
  3. 检查w_sameblock_inflight标志的清理时序

### 超时计数器溢出（置信度 30%）
- **触发条件**：cohCount或missqReplayCount达到最大值时的处理逻辑可能存在边界问题。
- **影响范围**：可能导致超时检测失效或重试机制异常。
- **关联位置**：<ref_file>Sbuffer/Sbuffer.scala:287-293</ref_file> 中的超时检测和重试计数逻辑。
- **验证建议**：
  1. 测试计数器边界条件
  2. 验证超时触发后的状态转换
  3. 检查重试计数器的重置逻辑

### 阈值配置边界问题（置信度 25%）
- **触发条件**：当threshold或base配置不当时，可能导致替换策略异常。
- **影响范围**：可能影响SBuffer的性能和稳定性。
- **关联位置**：<ref_file>Sbuffer/Sbuffer.scala:537-544</ref_file> 中的阈值计算和替换触发逻辑。
- **验证建议**：
  1. 测试各种阈值配置组合
  2. 验证force_write标志的影响
  3. 检查边界条件下的替换行为

- **状态跟踪**：暂无已确认问题，需要进一步验证分析。基于源码分析发现的上述潜在风险点需要在后续验证中重点关注。