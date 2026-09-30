# bosc_LoadUnit 功能点与检测点描述

## DUT 整体功能描述

`bosc_LoadUnit` 是 LSU 中的 Load 指令执行单元。它从标量发射口、向量发射口、MisalignBuffer、replay 通路、uncache/NC 通路和预取通路接收请求，经 stage 0 到 stage 3 完成仲裁、地址翻译、DCache 访问、前递判断、违例检查、异常整合、重放决策和最终写回。

该 DUT 的对外可见行为主要包括：

- 接收标量 load、向量 load、MMIO load、NC load、非对齐 load 和预取请求
- 向 TLB、DCache、LSQ、StoreQueue/SBuffer、prefetcher 等外部模块发起请求或反馈
- 输出标量写回 `ldout`、向量写回 `vecldout`
- 输出 wakeup、feedback、rollback、redirect、kill、prefetch_train 等控制信息

### 端口接口说明

- 输入端口：`clock`、`reset`、`io_ldin_*`、`io_vecldin_*`、`io_misalign_ldin_*`、`io_replay_*`、`io_fast_rep_in_*`、`io_redirect_*`、`io_tlb_*`、`io_dcache_*`、`io_pmp_*`、`io_lsq_*`、`io_sbuffer_*`、`io_ubuffer_*`、`io_l2l_fwd_in_*`、`io_prefetch_req_*`
- 输出端口：`io_ldout_*`、`io_vecldout_*`、`io_misalign_ldout_*`、`io_misalign_enq_*`、`io_tlb_*`、`io_dcache_req_*`、`io_lsq_*`、`io_wakeup_*`、`io_feedback_fast_*`、`io_feedback_slow_*`、`io_rollback_*`、`io_prefetch_train_*`
- 控制信号：`io_redirect_*`、`io_csrCtrl_*`、`io_dcache_s1_kill`、`io_dcache_s2_kill`、`io_ldCancel_*`

## 功能分组与检测点

### DUT 测试 API 分组

<FG-API>

用于定义后续验证中需要沉淀的标准测试 API，包括复位、发请求、注入 DCache/TLB/PMP 返回、观察写回和反馈等通用操作。

#### 时钟与复位控制 API

<FC-RESET-AND-CLOCK>

定义 DUT 时钟初始化、复位拉高拉低和按周期推进的基础控制 API。

**检测点：**

<CK-RESET-SEQUENCE>

通过 `clock`、`reset` 和 `Step` 驱动标准复位序列，检查复位期间主要输出保持无效或空闲状态，复位释放后 DUT 恢复可接收请求。

<CK-MULTI-CYCLE-STEP>

连续调用多拍 `Step` 后，检查 ready/valid 与阶段性输出随周期推进而变化，不出现停滞或跳拍。

#### 标量请求发送 API

<FC-SEND-SCALAR-LOAD>

定义向 `io_ldin` 发送标量 load 请求的标准事务接口，统一封装 valid/ready 握手与 uop 字段填充。

**检测点：**

<CK-READY-HANDSHAKE>

当 `io_ldin_ready=1` 时发送单个标量请求，检查该请求在一个握手窗口内被 DUT 接收。

<CK-BACKPRESSURE-HOLD>

当 `io_ldin_ready=0` 时维持 `io_ldin_valid` 与关键载荷稳定，检查接口层不会丢失或提前消费请求。

#### 向量请求发送 API

<FC-SEND-VECTOR-LOAD>

定义向 `io_vecldin` 发送向量 load 请求的标准事务接口，统一封装地址、mask、元素索引与 uop 相关字段。

**检测点：**

<CK-VECTOR-HANDSHAKE>

当 `io_vecldin_ready=1` 时发送向量请求，检查请求能够被正常接收并进入向量路径。

<CK-VECTOR-FIELD-FILL>

发送包含 `mask`、`reg_offset`、`elemIdx` 的向量请求，检查接口封装后 DUT 可见字段与预期一致。

#### 存储系统响应注入 API

<FC-INJECT-MEMORY-RESP>

定义向 TLB、PMP、DCache、前递网络和 LSQ 相关接口注入响应的标准事务接口。

**检测点：**

<CK-TLB-PMP-INJECT>

注入 TLB 和 PMP 响应后，检查 DUT 在后续周期按注入结果推进异常或正常路径。

<CK-DCACHE-FORWARD-INJECT>

注入 DCache 数据、前递命中或 nack 信息后，检查 DUT 对应输出与注入场景一致。

#### 写回与反馈采集 API

<FC-COLLECT-WRITEBACK-FEEDBACK>

定义采集 `ldout`、`vecldout`、`wakeup`、`feedback`、`rollback` 等输出的统一观测 API。

**检测点：**

<CK-SCALAR-CAPTURE>

在标量命中写回场景下，检查 API 能采集 `io_ldout_valid`、`io_ldout_bits_data` 与关键 uop 字段。

<CK-VECTOR-AND-CONTROL-CAPTURE>

在向量写回和 rollback 场景下，检查 API 能同时采集 `io_vecldout_*` 与控制输出信号。

### 标量基础流水分组

<FG-SCALAR-PIPELINE>

覆盖普通标量 load 从 `ldin` 进入到 `ldout` 写回的基本流水行为，包括握手、流水推进、命中路径和写回输出。

#### 标量发射握手

<FC-SCALAR-HANDSHAKE>

定义普通标量 load 在 `io_ldin` 接口上的 ready/valid 握手行为。

**检测点：**

<CK-SINGLE-ACCEPT>

单个标量请求且 `ready=1` 时，检查请求仅被接收一次，并在下一阶段产生后续活动。

<CK-STALL-AND-RESUME>

`ready` 先拉低后拉高时，检查同一请求在停顿期间保持稳定，恢复后继续被正常接收。

#### 标量请求向 TLB 与 DCache 发起查询

<FC-SCALAR-TLB-DCACHE-REQ>

定义标量 load 进入流水后对 TLB 和 DCache 请求接口的发起行为。

**检测点：**

<CK-REQ-ISSUE-TIMING>

标量请求发射后，检查 TLB 请求和 DCache 请求在预期拍次被拉起，不出现漏发或提前发出。

<CK-REQ-FIELD-MATCH>

检查发出的请求字段与输入请求一致，包括地址、LoadQueue 索引和访问类型等可观测载荷。

<CK-NO-ISSUE-WHEN-S1-BLOCKED>

当下游阻塞导致 stage 0 不能推进到 stage 1 时，检查 `io.tlb.req.valid` 与 `io.dcache.req.valid` 不应提前握手发出请求。

#### 标量命中写回

<FC-SCALAR-HIT-WRITEBACK>

定义普通标量 load 在命中路径下通过 `io_ldout` 正常写回的行为。

**检测点：**

<CK-HIT-DATA-WRITEBACK>

注入 DCache 命中数据后，检查 `io_ldout_valid` 置位且写回数据与地址偏移对应的期望值一致。

<CK-UOP-META-WRITEBACK>

检查写回时 `robIdx`、`lqIdx`、`pdest` 和异常位等元数据与原请求保持一致。

#### 标量写回背压保持

<FC-SCALAR-WRITEBACK-BACKPRESSURE>

定义 `io_ldout_ready` 拉低时，标量写回结果的保持与延迟释放行为。

**检测点：**

<CK-HOLD-UNDER-BACKPRESSURE>

在 `io_ldout_valid=1` 且 `io_ldout_ready=0` 的周期，检查 `data`、`uop` 等输出保持稳定不抖动。

<CK-RELEASE-ON-READY>

恢复 `io_ldout_ready=1` 后，检查此前被阻塞的写回在正确拍次完成，不丢失也不重复。

### stage 0 仲裁分组

<FG-ARBITRATION>

覆盖 stage 0 对不同请求源的选择行为，包括 MisalignBuffer、replay、fast replay、uncache、NC、prefetch、vector、scalar 等来源的优先级规则。

#### MisalignBuffer 最高优先级

<FC-MISALIGN-PRIORITY>

定义 misalign 请求与其他请求并发时，misalign 请求优先进入 stage 0 的行为。

**检测点：**

<CK-OVER-VECTOR-SCALAR>

同时给出 misalign、vector、scalar 请求时，检查被接受的是 misalign 路径请求。

<CK-OVER-LOWER-PRIORITY-REPLAY>

同时给出 misalign 与普通 replay 请求时，检查 misalign 请求先被发射。

#### dcache miss replay 优先级

<FC-DCACHE-MISS-REPLAY-PRIORITY>

定义 dcache miss 引发的 replay 相对普通 replay、vector 和 scalar 请求的优先级。

**检测点：**

<CK-OVER-ORDINARY-REPLAY>

同时给出 dcache miss replay 和普通 replay 时，检查 dcache miss replay 被优先选择。

<CK-OVER-SCALAR>

同时给出 dcache miss replay 和标量请求时，检查 replay 优先于标量请求。

<CK-REPLAY-INVALID-NO-STALL>

当 `io.replay.valid=0` 时，无论 `io.replay.bits` 内容为何，标量或向量请求都不应被伪造的 replay 顺序比较结果错误阻塞。

#### fast replay 优先级

<FC-FAST-REPLAY-PRIORITY>

定义 fast replay 相对 uncache、NC、vector 和 scalar 请求的优先级。

**检测点：**

<CK-OVER-UNCACHE-LOWER>

同时给出 fast replay 与更低优先级普通请求时，检查 fast replay 被优先发射。

<CK-BELOW-DCACHE-MISS>

同时给出 dcache miss replay 和 fast replay 时，检查 dcache miss replay 仍高于 fast replay。

#### uncache 与 NC 请求优先级

<FC-UNCACHE-NC-PRIORITY>

定义 uncache 请求和 NC 请求在 stage 0 中的相对优先级及其相对普通请求的优先级。

**检测点：**

<CK-UNCACHE-OVER-NC>

同时给出 uncache 请求和 NC 请求时，检查 uncache 请求优先被选择。

<CK-NC-OVER-ORDINARY-REPLAY>

同时给出 NC 请求和普通低优先级请求时，检查 NC 请求先进入流水。

<CK-UNCACHE-OVER-REPLAY-VECTOR-SCALAR>

同时给出 uncache 请求与普通 replay、向量请求或标量请求时，检查 uncache 请求仍保持更高优先级。

<CK-NC-OVER-VECTOR-SCALAR>

同时给出 NC 请求与向量请求或标量请求时，检查 NC 请求仍保持更高优先级。

#### 预取与向量标量请求优先级

<FC-PREFETCH-VECTOR-SCALAR-PRIORITY>

定义高置信度预取、低置信度预取、向量请求和标量请求之间的仲裁优先级。

**检测点：**

<CK-HIGHCONF-OVER-VECTOR>

同时给出高置信度预取和向量请求时，检查高置信度预取优先被受理。

<CK-VECTOR-OVER-SCALAR>

同时给出向量请求和标量请求时，检查向量请求优先于标量请求。

<CK-LOWCONF-LOWEST>

当同时存在低置信度预取和其他普通请求时，检查低置信度预取处于最低优先级。

### replay 与 kill 控制分组

<FG-REPLAY-KILL>

覆盖 queue-based replay、fast replay、dcache miss replay、kill 追发和请求取消等行为。

#### dcache miss 重放

<FC-DCACHE-MISS-REPLAY>

定义 DCache miss 后请求进入 replay 并重新发射的行为。

**检测点：**

<CK-MISS-TO-REPLAY>

注入 DCache miss 响应后，检查 DUT 不直接写回，而是输出 replay 所需信息。

<CK-REPLAY-REISSUE>

向 replay 接口回送该请求后，检查请求能重新进入流水并再次发起访问。

#### bank conflict 重放

<FC-BANK-CONFLICT-REPLAY>

定义 DCache bank conflict 场景下的 replay 触发行为。

**检测点：**

<CK-BANK-CONFLICT-DETECT>

注入 `io_dcache_s2_bank_conflict=1` 时，检查该请求被标记为需要重放。

<CK-REPLAY-CAUSE-PRESERVE>

重放后检查 LoadQueue/反馈中反映的重放原因保持为 bank conflict 场景。

#### mq nack 重放

<FC-MQ-NACK-REPLAY>

定义 miss queue nack 场景下的 replay 触发行为。

**检测点：**

<CK-MQ-NACK-DETECT>

注入 `io_dcache_s2_mq_nack=1` 时，检查该请求进入 replay 路径而非直接写回。

<CK-RETRY-LATER>

在 nack 清除后重发同一请求，检查其能够重新被发射并继续执行。

#### redirect 触发 s1 kill

<FC-S1-KILL-ON-REDIRECT>

定义 redirect 有效时 stage 1 kill 以及对 TLB/DCache kill 追发的行为。

**检测点：**

<CK-REDIRECT-KILL>

请求在 stage 1 期间注入 redirect，检查 `io_dcache_s1_kill` 或相关 kill 行为被拉起。

<CK-KILL-PROPAGATE>

redirect kill 后，检查被杀死请求不再进入正常写回路径。

#### fast replay 地址不匹配触发 kill

<FC-S1-KILL-ON-FAST-REPLAY-MISMATCH>

定义 fast replay 虚实地址匹配失败时的 kill 行为。

**检测点：**

<CK-MISMATCH-KILL>

构造 fast replay 地址不匹配场景，检查 stage 1 请求被 kill 并停止向正常写回推进。

<CK-NO-FALSE-KILL>

构造 fast replay 地址匹配场景，检查不会误触发 kill。

#### l2l forward 失败触发 kill

<FC-S1-KILL-ON-L2L-FAIL>

定义 load-to-load fast path 失败时 stage 1 kill 的行为。

**检测点：**

<CK-L2L-FAIL-KILL>

构造 l2l forward 失败场景，检查请求被 kill 或进入规定的失败处理路径。

<CK-L2L-SUCCESS-NO-KILL>

构造 l2l forward 成功场景，检查不会错误触发 kill。

### 前递与违例检查分组

<FG-FORWARD-VIOLATION>

覆盖 store-to-load forward、load-to-load fast path、ld-ld 违例、st-ld 违例以及相关查询/反馈接口。

#### store-to-load 前递成功

<FC-STLD-FORWARD-SUCCESS>

定义从 StoreQueue 或 SBuffer 成功获得前递数据的行为。

**检测点：**

<CK-SQ-FORWARD-DATA>

构造 StoreQueue 前递命中场景，检查最终写回数据来自前递通路而非 DCache。

<CK-SBUFFER-FORWARD-DATA>

构造 SBuffer 前递命中场景，检查最终写回数据与前递输入一致。

#### store-to-load 数据未就绪

<FC-STLD-FORWARD-DATA-NOT-READY>

定义前递数据尚未准备好时的等待或重放行为。

**检测点：**

<CK-WAIT-FOR-DATA>

构造前递匹配但数据未 ready 的场景，检查 DUT 不产生错误写回。

<CK-REPLAY-WHEN-NOT-READY>

在数据持续未就绪时，检查 DUT 产生 replay 或等待反馈而不是错误提交。

#### store-to-load 地址不匹配

<FC-STLD-FORWARD-ADDR-MISMATCH>

定义前递查询存在虚实地址不匹配时的处理行为。

**检测点：**

<CK-MISMATCH-REDIRECT-OR-KILL>

构造地址不匹配场景，检查 DUT 触发 kill、redirect 或规格要求的控制输出。

<CK-NO-WRONG-DATA>

地址不匹配场景下，检查 DUT 不会把错误前递数据写回后端。

#### ld-ld 违例查询

<FC-LDLD-NUKE-QUERY>

定义 stage 2 或 NC 路径下发起 ld-ld 违例查询及后续处理的行为。

**检测点：**

<CK-QUERY-ISSUE>

相关场景下检查 DUT 通过 `io_lsq_ldld_nuke_query_*` 发起 ld-ld 违例查询。

<CK-VIOLATION-CONTROL>

注入 ld-ld 违例结果后，检查 DUT 触发 rollback、redirect 或 replay 等预期控制。

#### st-ld 违例查询

<FC-STLD-NUKE-QUERY>

定义接收 StoreUnit 的 st-ld 违例信息并触发相应控制动作的行为。

**检测点：**

<CK-STORE-QUERY-ISSUE>

普通或 NC 路径下检查 DUT 发起 st-ld 违例相关查询请求。

<CK-NUKE-RESULT-HANDLING>

注入 st-ld 违例命中结果后，检查 DUT 触发对应 redirect 或取消行为。

#### load-to-load 快路径

<FC-L2L-FAST-FORWARD>

定义 `io_l2l_fwd_in` 参与的 load-to-load fast forward 行为。

**检测点：**

<CK-FAST-FWD-DATA>

构造 fast forward 成功场景，检查下游请求获得来自 `io_l2l_fwd_in` 的数据。

<CK-FAST-FWD-FAIL-PATH>

构造 fast forward 失败场景，检查 DUT 不会错误使用该数据，并进入 kill 或 fallback 路径。

### 异常与后端控制分组

<FG-EXCEPTION-CONTROL>

覆盖 TLB/PMP/DCache 异常整合、redirect、rollback、wakeup、feedback_fast、feedback_slow、ldCancel 等控制输出。

#### TLB 与 PMP 异常整合

<FC-TLB-PMP-EXCEPTION-MERGE>

定义 TLB、PMP 等地址相关异常的合并与最终上报行为。

**检测点：**

<CK-SINGLE-EXCEPTION>

单独注入一种地址相关异常时，检查最终 `ldout` 或 `vecldout` 的异常字段正确置位。

<CK-MULTI-EXCEPTION-PRIORITY>

同时注入多种异常时，检查最终异常选择与控制输出符合优先级预期。

#### DCache TL 错误传播

<FC-DCACHE-TL-ERROR-PROPAGATION>

定义 DCache 返回的 denied、corrupt 等错误如何反映到最终输出。

**检测点：**

<CK-DENIED-PROPAGATION>

注入 denied 场景，检查写回异常位或控制反馈能反映总线访问被拒绝。

<CK-CORRUPT-PROPAGATION>

注入 corrupt 场景，检查对应错误信息不会被静默吞掉。

#### 快速唤醒生成

<FC-WAKEUP-GENERATION>

定义正常路径、特殊路径和 MMIO 路径中的 wakeup 与 fast_uop 生成行为。

**检测点：**

<CK-NORMAL-WAKEUP>

普通 load 正常推进到快速唤醒阶段时，检查 `io_fast_uop` 或 `io_wakeup` 被正确拉起。

<CK-MMIO-WAKEUP>

MMIO 场景下检查 stage 0 就产生唤醒，而不等待最终数据写回。

#### 快反馈与慢反馈输出

<FC-FEEDBACK-FAST-SLOW>

定义 `feedback_fast` 和 `feedback_slow` 在不同流水阶段的输出行为。

**检测点：**

<CK-STAGE2-FAST-FEEDBACK>

检查需要快速反馈的场景在 stage 2 产生 `feedback_fast`。

<CK-STAGE3-SLOW-FEEDBACK>

检查需要慢反馈的标量写回场景在 stage 3 产生 `feedback_slow`。

#### rollback 与 redirect 输出

<FC-ROLLBACK-REDIRECT>

定义 ldld/stld 违例、异常或其他控制条件触发的 rollback 与 redirect 行为。

**检测点：**

<CK-LDLD-ROLLBACK>

构造 ld-ld 违例场景，检查 `io_rollback` 输出有效并携带对应回滚信息。

<CK-STLD-REDIRECT>

构造 st-ld 违例或其他需要重定向的场景，检查 `io_redirect` 相关后续效果或等价控制被触发。

### 向量 load 分组

<FG-VECTOR-LOAD>

覆盖 `vecldin` 到 `vecldout` 的向量 load 专用路径，包括向量偏移、掩码和不经过 `feedback_slow` 的行为。

#### 向量请求握手

<FC-VECTOR-HANDSHAKE>

定义向量 load 在 `io_vecldin` 接口上的握手与进入流水行为。

**检测点：**

<CK-VECTOR-ACCEPT>

当 `io_vecldin_ready=1` 时发送向量请求，检查请求被接收并产生向量路径活动。

<CK-VECTOR-BACKPRESSURE>

当 `io_vecldin_ready=0` 时保持请求稳定，检查向量请求不会丢失或重复接收。

#### 向量地址与掩码信息处理

<FC-VECTOR-ADDR-MASK-INFO>

定义向量路径中 `vecVaddrOffset`、mask、elemIdx、reg_offset 等信息的处理行为。

**检测点：**

<CK-OFFSET-AND-MASK-PASS>

构造不同 `mask` 和 `reg_offset` 输入，检查写回时相关字段能被正确带出或影响结果。

<CK-ELEM-IDX-PASS>

构造不同 `elemIdx` 和 `elemIdxInsideVd`，检查 `vecldout` 中索引字段与输入对应。

#### 向量写回输出

<FC-VECTOR-WRITEBACK>

定义向量 load 通过 `io_vecldout` 输出结果、异常信息和向量数据的行为。

**检测点：**

<CK-VECDATA-WRITEBACK>

注入向量命中数据后，检查 `io_vecldout_bits_vecdata` 与预期向量数据一致。

<CK-EXCEPTION-FIELD-WRITEBACK>

构造向量异常场景，检查 `io_vecldout_bits_exceptionVec_*` 与 `hasException` 正确反映异常。

<CK-VECLDOUT-BACKPRESSURE>

当 `io_vecldout_ready=0` 时，检查向量写回结果保持稳定并等待握手，不应因为输出背压而直接丢失。

#### 向量路径不输出慢反馈

<FC-VECTOR-NO-FEEDBACK-SLOW>

定义向量 load 路径不通过标量 `feedback_slow` 输出的行为。

**检测点：**

<CK-NO-SLOW-FEEDBACK>

向量请求执行完成时，检查 `io_feedback_slow` 不会因向量路径而错误拉起。

<CK-STILL-WRITES-BACK>

虽然没有慢反馈，但检查 `io_vecldout_valid` 仍正常产生，确保功能未被抑制。

### MMIO load 分组

<FG-MMIO-LOAD>

覆盖 MMIO load 的早唤醒和晚写回行为，以及与普通标量 load 不同的时序特点。

#### MMIO 提前唤醒

<FC-MMIO-EARLY-WAKEUP>

定义 MMIO load 在 stage 0 即向后端发出唤醒信号的行为。

**检测点：**

<CK-S0-WAKEUP>

构造 MMIO 场景，检查在 stage 0 或最早允许阶段出现 wakeup 输出。

<CK-NO-DATA-BEFORE-S3>

在提前唤醒后检查 stage 3 之前不产生错误的数据写回。

#### MMIO stage 3 写回

<FC-MMIO-S3-WRITEBACK>

定义 MMIO load 在 stage 3 才完成最终写回的行为。

**检测点：**

<CK-MMIO-WRITEBACK-TIMING>

检查 MMIO 最终数据只在 stage 3 对应时机通过 `io_ldout` 写回。

<CK-MMIO-DEBUG-FLAGS>

检查 MMIO 写回时 `debug_isMMIO` 等调试标志与场景相匹配。

### Non-cacheable load 分组

<FG-NONCACHEABLE-LOAD>

覆盖 NC load 的两次上流水、绕过 TLB、前递判定、RAR/RAW 检查、重发与最终写回路径。

#### NC 属性识别

<FC-NC-ATTRIBUTE-DETECT>

定义 NC load 第一次上流水时对 NC 属性的识别行为。

**检测点：**

<CK-FIRST-PASS-DETECT>

构造 NC 属性请求，检查第一次上流水后 DUT 识别出 NC 特征并切换到 NC 路径。

<CK-NON-NC-NO-DOUBLE-PASS>

构造普通非 NC 请求，检查不会误进入 NC 两次上流水行为。

#### NC 路径绕过 TLB

<FC-NC-BYPASS-TLB>

定义 NC load 第二次上流水时无需再进行 TLB 翻译的行为。

**检测点：**

<CK-NO-TLB-REQ-SECOND-PASS>

在 NC 第二次上流水时，检查不会再次发出 TLB 翻译请求。

<CK-NC-PATH-ENTER>

检查 NC 第二次上流水时后续接口行为与普通路径不同，确认已进入专用 NC 路径。

<CK-NC-NO-TLB-QUERY-WITH-CONTENTION>

当 NC 第二次上流水与更低优先级请求并发时，检查该 NC 请求依然不会错误拉起 TLB 翻译接口。

#### NC 前递与违例检查

<FC-NC-FORWARD-VIOLATION>

定义 NC 路径中的 StoreQueue 前递、RAR 查询和 RAW 查询行为。

**检测点：**

<CK-NC-FORWARD-SUCCESS>

构造 NC 前递成功场景，检查最终写回数据来源于前递路径。

<CK-NC-ADDR-MISMATCH>

构造 NC 前递地址不匹配场景，检查 DUT 触发规定的异常控制或重定向行为。

#### NC 因资源压力重放

<FC-NC-REPLAY-ON-RAR-RAW-PRESSURE>

定义 RAR 或 RAW 查询满、未 ready 等情况下 NC 请求进入 replay 的行为。

**检测点：**

<CK-RAR-RAW-FULL-REPLAY>

构造 RAR 或 RAW 资源满场景，检查 NC 请求被送入 replay，而不是直接丢弃或写回。

<CK-RAR-RAW-NOTREADY-REPLAY>

构造 RAR 或 RAW 未 ready 场景，检查 NC 请求仍按规格进入重发路径。

#### NC 最终写回

<FC-NC-LDOUT-WRITEBACK>

定义 NC 请求不再重放时通过 `io_ldout` 完成写回的行为。

**检测点：**

<CK-NC-WRITEBACK-DATA>

构造 NC 正常完成场景，检查 `io_ldout_bits_data` 与 NC 返回数据一致。

<CK-NC-NO-SPURIOUS-REDIRECT>

NC 正常完成场景下，检查不会错误触发 redirect 或 rollback。

#### 非对齐 NC 非法组合

<FC-NC-MISALIGN-UNSUPPORTED>

定义“不支持非对齐 NC load”这一约束对应的行为边界。

**检测点：**

<CK-NC-MISALIGN-BLOCK>

构造同时具有 NC 和 misalign 特征的请求，检查 DUT 不会按受支持路径正常提交。

<CK-NO-ORDINARY-MISALIGN-PATH>

该非法组合下检查 DUT 不会错误进入普通 misalign 成功写回路径。

### 非对齐 load 分组

<FG-MISALIGN-LOAD>

覆盖非对齐 load 的检测、进入 MisalignBuffer、两次对齐子请求执行、最终 wakeup 或写回行为。

#### 非对齐检测与入队

<FC-MISALIGN-DETECT-ENQUEUE>

定义普通 load 被识别为非对齐后通过 `io_misalign_enq` 进入 MisalignBuffer 的行为。

**检测点：**

<CK-DETECT-AND-ENQ>

构造非对齐标量请求，检查 stage 3 产生 `io_misalign_enq` 入队动作。

<CK-NON-MISALIGN-NO-ENQ>

构造对齐请求，检查不会误触发 misalign 入队。

#### 第一条拆分子请求执行

<FC-MISALIGN-FIRST-SPLIT-RESP>

定义第一条对齐子请求执行成功、失败或重发响应的行为。

**检测点：**

<CK-FIRST-SPLIT-SUCCESS>

第一条子请求成功时，检查 DUT 向 MisalignBuffer 返回成功响应而不是继续重发。

<CK-FIRST-SPLIT-REPLAY>

第一条子请求 miss 或前递失败时，检查 DUT 返回重发信息。

#### 第二条拆分子请求执行

<FC-MISALIGN-SECOND-SPLIT-RESP>

定义第二条对齐子请求执行成功、失败或重发响应的行为。

**检测点：**

<CK-SECOND-SPLIT-SUCCESS>

第二条子请求成功时，检查 DUT 返回第二段响应并允许后续合并完成。

<CK-SECOND-SPLIT-REPLAY>

第二条子请求失败时，检查 DUT 继续通过 MisalignBuffer 路径重发。

#### misalign 唤醒或继续重发

<FC-MISALIGN-WAKEUP-OR-REPLAY>

定义 `misalignNeedWakeUp` 决定直接唤醒写回还是继续 replay 的行为。

**检测点：**

<CK-WAKEUP-WHEN-NEEDED>

当 `misalignNeedWakeUp=1` 时，检查 DUT 最终直接产生唤醒和写回相关行为。

<CK-REPLAY-WHEN-NOT-WOKEN>

当 `misalignNeedWakeUp=0` 时，检查 DUT 仍通过 MisalignBuffer 继续重发而不是错误提交。

#### 16B 边界相关处理

<FC-MISALIGN-BOUNDARY-HANDLING>

定义是否跨越 16 字节边界对 misalign 路径处理分支的影响。

**检测点：**

<CK-NO-CROSS-16B>

构造不跨 16B 边界的 misalign 请求，检查 DUT 走普通 misalign 分支。

<CK-CROSS-16B-PATH>

构造跨 16B 边界的 misalign 请求，检查 DUT 走边界相关的专用处理分支。

### 预取请求与训练分组

<FG-PREFETCH>

覆盖高/低置信度预取请求受理、`canAccept*` 输出以及 `prefetch_train`、`prefetch_train_l1` 训练行为。

#### 高置信度预取受理

<FC-HIGHCONF-PREFETCH-ACCEPT>

定义高置信度预取请求的仲裁受理和 `canAcceptHighConfPrefetch` 输出行为。

**检测点：**

<CK-HIGHCONF-ACCEPT-WHEN-AVAILABLE>

无更高优先级请求且资源可用时，检查高置信度预取可被受理。

<CK-HIGHCONF-BLOCK-WHEN-BUSY>

更高优先级请求占用流水时，检查高置信度预取不会错误抢占。

#### 低置信度预取受理

<FC-LOWCONF-PREFETCH-ACCEPT>

定义低置信度预取请求的仲裁受理和 `canAcceptLowConfPrefetch` 输出行为。

**检测点：**

<CK-LOWCONF-ONLY-WHEN-IDLE>

无其他可竞争请求时，检查低置信度预取才会被受理。

<CK-LOWCONF-LOWEST-PRIORITY>

存在普通标量、向量或 replay 请求时，检查低置信度预取保持最低优先级。

#### L1 预取训练

<FC-PREFETCH-TRAIN-L1>

定义 stage 2 通过 `io_prefetch_train_l1` 输出 L1 预取训练信息的行为。

**检测点：**

<CK-L1-TRAIN-ON-LOAD>

构造可训练场景，检查 `io_prefetch_train_l1` 在预期拍次有效。

<CK-L1-TRAIN-FIELDS>

检查训练输出中的关键地址或访问信息字段与本次 load 场景匹配。

#### SMS 预取训练

<FC-PREFETCH-TRAIN-SMS>

定义 stage 2 通过 `io_prefetch_train` 输出 SMS 预取训练信息的行为。

**检测点：**

<CK-SMS-TRAIN-ON-LOAD>

构造可训练场景，检查 `io_prefetch_train` 在预期拍次有效。

<CK-SMS-TRAIN-FIELDS>

检查 SMS 训练输出的关键字段与对应访问场景一致。

### 写回与数据选择分组

<FG-WRITEBACK-DATA>

覆盖 stage 3 的数据选择与写回结果，包括 DCache 数据、前递数据、uncache 数据之间的选择，以及标量/向量写回内容。

#### 多数据源选择

<FC-DATA-SOURCE-SELECTION>

定义 stage 3 在 DCache 数据、前递数据和 uncache 数据之间选择最终数据源的行为。

**检测点：**

<CK-DCACHE-SOURCE>

仅有 DCache 命中数据可用时，检查写回数据来源于 DCache。

<CK-FORWARD-SOURCE>

前递命中优先于 DCache 数据的场景下，检查写回值选自前递通路。

<CK-UNCACHE-SOURCE>

uncache 完成场景下，检查写回数据来源于 uncache 返回通路。

#### 128bit 到 64bit 标量提取

<FC-EXTRACT-128B-TO-64B>

定义 128bit 数据通路下按地址偏移抽取标量 64bit 写回数据的行为。

**检测点：**

<CK-LOW-HALF-EXTRACT>

构造低半段访问场景，检查 `io_ldout_bits_data` 取自 128bit 数据的低 64bit 对应范围。

<CK-HIGH-HALF-EXTRACT>

构造高半段访问场景，检查 `io_ldout_bits_data` 取自 128bit 数据的高 64bit 对应范围。

<CK-OFFSET-SELECT>

构造不同地址偏移场景，检查标量写回的字节选择与偏移一致。

#### uncache 数据写回

<FC-UNCACHE-DATA-WRITEBACK>

定义 uncache load 返回数据参与最终写回的行为。

**检测点：**

<CK-UNCACHE-DATA-PATH>

构造 uncache 返回场景，检查 `io_ldout_bits_data` 与 uncache 输入数据一致。

<CK-UNCACHE-META-PATH>

检查 uncache 写回时相关 `uop`、`debug` 和索引字段没有丢失或错配。

#### 写回附带信息更新

<FC-WRITEBACK-META-UPDATE>

定义写回时 `uop` 字段、debug 信息、LoadQueue 更新信息等附带内容的输出行为。

**检测点：**

<CK-LQ-INDEX-UPDATE>

普通完成场景下，检查写回相关的 `lqIdx` 和 LoadQueue 更新接口与原请求一致。

<CK-DEBUG-ADDR-UPDATE>

检查写回时 `debug_vaddr`、`debug_paddr` 以及 MMIO/NC 标志能正确反映请求属性。
