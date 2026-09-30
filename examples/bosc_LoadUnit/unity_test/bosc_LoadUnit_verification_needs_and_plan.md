# bosc_LoadUnit 验证需求与规划

## 1. 文档目的与依据

本文档用于明确 `bosc_LoadUnit` 的验证目标、外部接口、风险点与后续测试规划，作为后续 API 设计、功能点拆解、测试用例开发和缺陷分析的基础。

本阶段主要依据以下资料完成需求分析：

- `bosc_LoadUnit/README.md`
- `bosc_LoadUnit_RTL/LoadUnit.scala`
- `bosc_LoadUnit/bosc_LoadUnit_top.sv`
- `bosc_LoadUnit/signals.json`

验证工作遵循以下原则：

- 仅通过 DUT 对外输入输出接口进行验证，不依赖内部信号实现细节。
- 以功能正确性、时序交互正确性、异常/重放路径正确性为核心。
- 测试失败时优先分析设计缺陷，不直接修改 DUT 实现。
- DUT 为时序电路，后续所有测试均使用 `Step` 接口推进时钟。

## 2. DUT 功能理解

`bosc_LoadUnit` 是 LSU 中负责执行 load 指令的流水单元，支持标量 load、向量 load、MMIO load、Non-cacheable load、非对齐 load 以及预取相关请求。其核心职责包括：

- 从多个请求源接收 load 类请求并在 stage 0 仲裁。
- 向 TLB、DCache、LSQ、StoreQueue、SBuffer 等接口发起查询或交互。
- 在 stage 1 到 stage 3 处理中完成异常检测、前递判断、重放原因整合、违例检查、数据选择、写回和反馈。
- 向后端输出标量写回 `ldout`、向量写回 `vecldout`、快速唤醒/反馈/回滚/重定向等控制信息。

结合 README 与上层源码，可以将 DUT 的外部可见行为概括为以下功能域：

### 2.1 标量 load 基本流水

- 从 `io_ldin` 接收标量 load 请求。
- stage 0 发起 TLB/DCache 查询。
- stage 1 结合 TLB 返回继续处理并发起前递/违例相关查询。
- stage 2 根据 PMP、DCache、RAR/RAW 检查结果决定是否写回、重放或重定向。
- stage 3 输出 `io_ldout`、更新 LoadQueue、发出慢反馈和必要的 redirect/rollback。

### 2.2 多源请求仲裁

stage 0 同时支持来自以下来源的请求，并具有固定优先级：

- MisalignBuffer load 请求
- dcache miss 引发的 replay
- LoadUnit fast replay
- uncache 请求
- nc 请求
- 其他 replay
- 高置信度硬件预取
- 向量 load
- 标量 load / 软件预取
- load pointer chasing 请求（当前架构不支持）
- 低置信度硬件预取

该优先级直接决定哪些请求能够进入流水线，是一个高风险验证点。

### 2.3 向量 load

- 从 `io_vecldin` 接收请求。
- stage 0 优先级高于标量 load。
- stage 1 需要处理向量地址偏移和触发器相关信息。
- stage 3 通过 `io_vecldout` 写回，不经标量 `feedback_slow` 路径。

### 2.4 MMIO load

- MMIO load 在 stage 0 即可向后端发送唤醒请求。
- 实际数据写回发生在 stage 3。
- 此类请求的“早唤醒”和“晚写回”可能在控制时序上存在缺陷。

### 2.5 Non-cacheable load

- NC 指令会上流水两次。
- 第一次用于识别 NC 属性。
- 第二次绕过 TLB 翻译，重点检查 store 前递、RAR/RAW 违例、LoadQueueUncache 重发及最终 `ldout` 写回。
- 不支持非对齐 NC load。

### 2.6 非对齐 load

- 非对齐 load 最多经历 4 次上流水。
- 首次用于识别并进入 `LoadMisalignBuffer`。
- 后续两次执行拆分后的对齐子请求。
- 最后一次负责唤醒消费者，并由 `LoadMisalignBuffer` 完成写回。
- 对是否跨越 16B 边界、是否来自 MisalignBuffer、是否需要 wakeup 的处理存在多分支路径。

### 2.7 预取请求及训练

- 支持高置信度和低置信度硬件预取。
- stage 2 输出 `io_prefetch_train_l1` 和 `io_prefetch_train` 用于训练 L1/SMS 预取器。
- `io_canAcceptHighConfPrefetch`、`io_canAcceptLowConfPrefetch` 反映受理能力。

## 3. 外部接口与验证观察点

根据 `LoadUnit.scala` 与顶层端口，后续验证需要重点驱动和观察如下接口。

### 3.1 主要输入接口

- `clock`、`reset`
- `io_ldin`：标量 load 发射输入
- `io_vecldin`：向量 load 输入
- `io_misalign_ldin`：MisalignBuffer 重发输入
- `io_replay`：LoadQueue replay 输入
- `io_fast_rep_in`：快速重发输入
- `io_redirect`：重定向/刷流水控制
- `io_csrCtrl_*`：包括 `ldld_vio_check_enable`、`hd_misalign_ld_enable`
- `io_lsq_uncache`、`io_lsq_nc_ldin`、`io_lsq_ld_raw_data`：LSQ/uncache/NC 相关输入
- `io_dcache_req_ready`、`io_dcache_resp_bits_*`、`io_dcache_s2_*`：DCache 握手与响应
- `io_tlb_*`、`io_pmp_*`：地址翻译与 PMP 检查返回
- `io_sbuffer_*`、`io_ubuffer_*`、`io_forward_mshr_*`：前递相关输入
- `io_l2l_fwd_in`、`io_ld_fast_match`、`io_ld_fast_fuOpType`、`io_ld_fast_imm`：load-to-load fast path
- `io_stld_nuke_query`：StoreUnit 发起的 st-ld 违例检查输入
- `io_prefetch_req`：硬件预取输入

### 3.2 主要输出接口

- `io_ldout`：标量 load 写回结果
- `io_vecldout`：向量 load 写回结果
- `io_misalign_ldout`：向 MisalignBuffer 返回写回或重发结果
- `io_tlb_*`、`io_dcache_req_*`、`io_dcache_s1_kill`、`io_dcache_s2_kill`：对外查询与 kill 控制
- `io_lsq_ldin`、`io_lsq_forward_*`、`io_lsq_ldld_nuke_query`、`io_lsq_stld_nuke_query`：对 LSQ 的更新与查询
- `io_wakeup`、`io_feedback_fast`、`io_feedback_slow`、`io_ldCancel`
- `io_fast_uop`：快速唤醒
- `io_rollback`：RAR 或其他路径引发的回滚
- `io_prefetch_train`、`io_prefetch_train_l1`
- `io_ifetchPrefetch`
- `io_canAcceptHighConfPrefetch`、`io_canAcceptLowConfPrefetch`

### 3.3 核心可观察行为

后续测试重点检查以下行为是否正确：

- ready/valid 握手是否符合优先级和背压规则
- 请求进入流水后，外部查询接口是否在正确拍次发出
- kill、rollback、redirect 是否在正确条件下触发
- 写回数据、异常标记、debug 信息、队列索引是否与请求匹配
- 前递成功/失败时，结果、重放和重定向是否符合预期
- replay、NC、MMIO、misalign、vector 等特殊路径是否走到正确出口

## 4. 验证目标

本次验证的总体目标是确认 `bosc_LoadUnit` 在正常路径、异常路径、重放路径和复杂边界场景下均满足规格描述，重点包括：

1. 验证标量 load 基本流程可正确完成仲裁、查询、返回、写回。
2. 验证多输入源优先级严格符合 README 描述。
3. 验证 vector/MMIO/NC/misalign/prefetch 等专用功能路径正确。
4. 验证异常、kill、redirect、rollback、feedback 等控制输出时序正确。
5. 验证 DCache miss、bank conflict、mq nack、RAR/RAW 满或未 ready 等场景下的 replay 行为正确。
6. 验证 store-to-load forward、load-to-load forward 成功与失败两类路径。
7. 验证边界条件下的数据选择、数据拼接和写回行为。
8. 发现潜在设计缺陷，并在后续缺陷分析文档中形成“现象-根因-修复建议”的闭环记录。

## 5. 风险点与边界条件分析

结合需求文档和 LoadUnit 结构，以下内容是最可能出现缺陷的区域，应在后续阶段优先验证。

### 5.1 仲裁与背压风险

- 多源同时有效时是否严格按优先级选择。
- 高优先级请求持续存在时，低优先级请求是否被异常饿死。
- `ready` 反压时是否仍保持输入稳定，不发生重复发射或丢包。

### 5.2 kill / redirect / replay 时序风险

- `redirect` 与普通请求同时出现时，stage 1/2/3 是否错误保留旧请求。
- fast replay 虚实地址不匹配、l2l forward 失败时，`s1_kill` 是否完整传播到外部接口。
- replay 原因整合是否有优先级覆盖错误，导致应重放却写回，或应写回却错误重放。

### 5.3 数据路径风险

- DCache 返回 128bit 数据，标量 `ldout` 仅 64bit，字节选择和拼接可能出错。
- 前递数据、DCache 数据、uncache 数据之间的选择优先级可能出错。
- misalign 场景下两次对子请求的返回数据拼接与最终写回存在高风险。

### 5.4 特殊功能路径风险

- vector load 不走 `feedback_slow`，可能遗漏写回、反馈或异常传播。
- MMIO load 的“s0 提前唤醒”和“s3 延迟写回”可能导致依赖关系错误。
- NC load 第二次上流水绕过 TLB，可能引入地址检查、违例检查或 replay 行为异常。
- README 明确“不支持非对齐 NC load”，需要验证非法组合不会被错误当作普通路径处理。

### 5.5 违例与异常优先级风险

- PMP/TLB/DCache/tl-error/ldld/stld 等多个异常或违例同时出现时，最终异常向量和 redirect/rollback 选择可能错误。
- RAR/RAW 查询满或 not ready 时，是否按规格进入 replay，而不是直接丢弃请求。
- `ldld_vio_check_enable` 等 CSR 控制位使能/关闭时，行为是否同步变化。

### 5.6 边界条件

- 最小/最大掩码、最低/最高地址偏移、跨 16B 边界的非对齐访问。
- `io_ldout_ready`、`io_vecldout_ready`、`io_dcache_req_ready` 拉低时的停顿。
- 异常请求、redirect 请求与 replay 请求同时到达。
- 空闲状态切换到高压并发状态时的首拍行为。

## 6. 验证策略

### 6.1 总体策略

后续验证采用“接口级黑盒验证 + 分功能域覆盖 + 随机扰动补充”的策略：

- 先建立稳定的基础驱动与监视 API，覆盖标量、向量、replay、misalign、NC、MMIO 等主要入口。
- 对每类功能先做定向测试，验证单一功能正确性。
- 在定向测试通过后，引入并发输入、背压、随机响应时序，验证复杂场景稳健性。
- 对已发现的缺陷场景保留 Fail 用例，用于固定化复现设计问题。

### 6.2 后续 testbench 架构规划

后续测试环境建议包含以下组件：

- `Env`：统一管理时钟、复位、默认输入、周期推进。
- 输入驱动器：
  - 标量 load 驱动
  - 向量 load 驱动
  - replay/fast replay 驱动
  - misalign/uncache/nc 请求驱动
  - DCache/TLB/PMP/LSQ 响应驱动
- 输出监视器：
  - `ldout`/`vecldout` 写回监视
  - `wakeup`/`feedback`/`rollback` 控制监视
  - `dcache req` / `tlb req` 查询监视
- checker：
  - 时序次序检查
  - 数据正确性检查
  - 异常/重放原因检查
  - 接口互斥和优先级检查

### 6.3 参考模型思路

若后续阶段启用 `ref_model`，建议采用轻量事务级模型，不复刻内部实现，仅根据输入场景和规格规则判断以下结果：

- 当前拍应接收哪一路请求
- 该请求是否应被 kill / replay / rollback / writeback
- 应选择哪类数据源
- 应产生哪些外部接口副作用

该模型主要服务于仲裁、路径选择和输出合法性判断，不追求完全微架构同构。

## 7. 功能域测试规划

后续测试用例按以下功能域组织。

### 7.1 基础时序与复位

- 复位后主要输出清零或无效。
- 非复位状态下单拍推进有效。
- ready/valid 基础握手稳定。

### 7.2 标量 load 基本路径

- 单个标量 load 正常发射、查询、DCache 命中、`ldout` 写回。
- 不同地址偏移和不同 mask 下的数据抽取正确。
- `io_ldout_ready` 施加背压时，写回保持稳定。

### 7.3 stage 0 多源仲裁

- 两路及多路请求并发时，验证优先级符合规格。
- replay、fast replay、misalign、vector、scalar、prefetch 混合并发。
- 高低置信度预取之间的受理差异。

### 7.4 replay / kill / redirect

- DCache miss、bank conflict、mq nack、前递失败触发 replay。
- redirect 到来时中止旧请求。
- fast replay 地址不匹配、l2l forward 失败触发 kill。

### 7.5 前递与违例

- store-to-load forward 成功路径。
- forward 数据未 ready、地址未 ready、地址不匹配路径。
- ld-ld / st-ld 违例导致 replay、redirect 或 rollback。

### 7.6 异常路径

- TLB/PMP/tl-error/denied/corrupt 等异常注入。
- 多异常并发时的优先级与最终异常向量检查。
- 异常请求不应产生错误数据写回。

### 7.7 MMIO / NC load

- MMIO 早唤醒与晚写回验证。
- NC 首次识别、二次执行、违例检查和回写路径验证。
- NC 与 replay、forward、违例并发交互。
- 非对齐 NC 非法组合验证。

### 7.8 misalign load

- 非对齐检测后进入 MisalignBuffer。
- 两个子 load 分别成功、分别失败、部分重放。
- 跨 16B 边界与不跨 16B 边界差异。
- `misalignNeedWakeUp` 不同取值下的最终行为。

### 7.9 vector load

- `vecldin` 发射与 `vecldout` 写回。
- 向量请求优先级高于标量。
- 向量路径不输出 `feedback_slow`。
- 向量数据/掩码/偏移相关边界场景。

### 7.10 prefetch

- 高/低置信度预取请求受理。
- `canAcceptHighConfPrefetch`、`canAcceptLowConfPrefetch` 行为。
- `prefetch_train` 与 `prefetch_train_l1` 输出时机。

## 8. 覆盖率规划

后续覆盖率至少包括以下几类：

- 功能覆盖：
  - 标量、向量、MMIO、NC、misalign、prefetch 六大功能域
  - stage 0 仲裁来源组合
  - replay 原因类型
  - 前递成功/失败类型
  - 异常与违例类型
- 交叉覆盖：
  - 请求类型 × 是否 replay
  - 请求类型 × 是否 exception
  - 请求类型 × 是否 kill/redirect
  - misalign 场景 × 跨 16B 边界 × wakeup 模式
  - prefetch 置信度 × 受理结果
- 代码覆盖：
  - 以现有 line coverage 机制收集行覆盖
  - 后续根据未覆盖分支补充场景

## 9. 缺陷发现与记录策略

后续若出现用例失败，按以下方式处理：

- 先判断失败是否由 DUT 设计行为导致，而非测试平台错误。
- 若怀疑设计缺陷，保留最小复现实例，使对应测试继续 Fail。
- 在 `unity_test/bosc_LoadUnit_bug_analysis.md` 中补充：
  - 失败现象
  - 触发条件
  - 预期行为
  - 源码根因分析
  - 修复建议

## 10. 本阶段结论

`bosc_LoadUnit` 的验证重点不在单一 load 命中路径，而在于“多源仲裁 + 多阶段 kill/replay/exception + 特殊 load 类型”的交互正确性。后续阶段应优先建立稳定的接口驱动和行为 checker，再按“基础标量路径 -> 特殊路径 -> 并发与异常路径 -> 随机补充”的顺序逐步展开验证。
