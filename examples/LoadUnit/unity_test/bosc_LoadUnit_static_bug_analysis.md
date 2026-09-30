# bosc_LoadUnit 静态 Bug 分析

## 静态分析发现

<FG-ARBITRATION>

#### uncache 与 NC 请求优先级

<FC-UNCACHE-NC-PRIORITY>

<CK-UNCACHE-OVER-REPLAY-VECTOR-SCALAR>

<BG-STATIC-001-UNCACHE-PRIORITY-ORDER>

问题描述：README 规定 stage 0 中 uncache 请求优先级高于普通 replay、高置信度预取、向量请求和标量请求，但当前 RTL 实际把 `io.lsq.uncache.valid` 放在这些源之后，导致 uncache 请求可能被更低规格优先级的请求抢占。

影响分析：该问题直接违反 FG-ARBITRATION/FC-UNCACHE-NC-PRIORITY/CK-UNCACHE-OVER-REPLAY-VECTOR-SCALAR，对 MMIO load 的早唤醒与写回时序也会形成连锁影响。

置信度：98%

<LINK-BUG-[BG-UNCACHE-PRIORITY-ORDER-98]>

<FILE-bosc_LoadUnit_RTL/LoadUnit.scala:289-325,330-335>

```scala
// bosc_LoadUnit_RTL/LoadUnit.scala 第289-325,330-335行
289:   // src 3: mmio (io.lsq.uncache)
294:   // src 4: nc (io.lsq.nc_ldin)
295:   // src 5: load replayed by LSQ (io.replay)
296:   // src 6: hardware prefetch from prefetchor (high confidence) (io.prefetch)
301:   // src 7: vec read from RS (io.vecldin)
302:   // src 8: int read / software prefetch first issue from RS (io.in)
305:   // priority: high to low
314:   val s0_src_valid_vec = WireInit(VecInit(Seq(
315:     io.misalign_ldin.valid,
316:     io.replay.valid && io.replay.bits.forward_tlDchannel,
317:     io.fast_rep_in.valid,
318:     io.replay.valid && !io.replay.bits.forward_tlDchannel && !s0_rep_stall,
319:     io.prefetch_req.valid && io.prefetch_req.bits.confidence > 0.U,
320:     io.vecldin.valid,
321:     io.ldin.valid,
322:     io.lsq.uncache.valid,
323:     io.lsq.nc_ldin.valid,
324:     io.l2l_fwd_in.valid,
325:     io.prefetch_req.valid && io.prefetch_req.bits.confidence === 0.U,
331:     s0_src_ready_vec(i) := !s0_src_valid_vec.take(i).reduce(_ || _)
334:   val s0_src_select_vec = WireInit(VecInit((0 until SRC_NUM).map{i => s0_src_valid_vec(i) && s0_src_ready_vec(i)}))
```

根因分析：仲裁优先级完全由 `s0_src_valid_vec` 的排列顺序决定，而该顺序与上方注释和 README 的优先级表不一致。`io.lsq.uncache.valid` 被排在普通 replay、高置信预取、vector、scalar 之后，因此一旦这些请求并发，uncache 永远不可能先被选中。

修复建议：将 `s0_src_valid_vec` 与 `mab_idx ... low_pf_idx` 的物理顺序调整为与 README 一致，或者改用显式的优先级选择逻辑，不再依赖向量位置隐式表达优先级。

<CK-NC-OVER-VECTOR-SCALAR>

<BG-STATIC-002-NC-PRIORITY-ORDER>

问题描述：README 规定 NC 请求优先级高于普通 replay、高置信度预取、向量请求和标量请求，但当前 RTL 把 `io.lsq.nc_ldin.valid` 放在这些请求之后，NC 请求会被更低规格优先级源抢占。

影响分析：该问题直接违反 FG-ARBITRATION/FC-UNCACHE-NC-PRIORITY/CK-NC-OVER-VECTOR-SCALAR，会导致 NC 第二次上流水的专用路径启动时机错误，进一步影响前递、RAR/RAW 检查和写回。

置信度：97%

<LINK-BUG-[BG-NC-PRIORITY-ORDER-VS-ORDINARY-REPLAY-97][BG-NC-PRIORITY-ORDER-VS-VECTOR-SCALAR-97][BG-NC-CONTENTION-PRIORITY-BROKEN-99]>

<FILE-bosc_LoadUnit_RTL/LoadUnit.scala:314-325,330-335>

```scala
// bosc_LoadUnit_RTL/LoadUnit.scala 第314-325,330-335行
314:   val s0_src_valid_vec = WireInit(VecInit(Seq(
315:     io.misalign_ldin.valid,
316:     io.replay.valid && io.replay.bits.forward_tlDchannel,
317:     io.fast_rep_in.valid,
318:     io.replay.valid && !io.replay.bits.forward_tlDchannel && !s0_rep_stall,
319:     io.prefetch_req.valid && io.prefetch_req.bits.confidence > 0.U,
320:     io.vecldin.valid,
321:     io.ldin.valid,
322:     io.lsq.uncache.valid,
323:     io.lsq.nc_ldin.valid,
324:     io.l2l_fwd_in.valid,
325:     io.prefetch_req.valid && io.prefetch_req.bits.confidence === 0.U,
331:     s0_src_ready_vec(i) := !s0_src_valid_vec.take(i).reduce(_ || _)
334:   val s0_src_select_vec = WireInit(VecInit((0 until SRC_NUM).map{i => s0_src_valid_vec(i) && s0_src_ready_vec(i)}))
```

根因分析：`io.lsq.nc_ldin.valid` 的实际位置在 `io.vecldin.valid` 和 `io.ldin.valid` 之后，优先级被错误降低。只要 vector 或 scalar 同拍有效，NC 请求就无法优先进入 stage 0。

修复建议：把 NC 请求移动到符合规格的位置，即仅低于 uncache 和更高等级 replay，而高于普通 replay、prefetch、vector 和 scalar。

#### dcache miss replay 优先级

<FC-DCACHE-MISS-REPLAY-PRIORITY>

<CK-REPLAY-INVALID-NO-STALL>

<BG-STATIC-003-REPLAY-STALL-WITHOUT-VALID>

问题描述：`s0_rep_stall` 在比较 replay 与 scalar/vector 的 LoadQueue 顺序时，直接读取 `io.replay.bits.uop.lqIdx`，但没有使用 `io.replay.valid` 保护。当 replay 无效而 scalar 或 vector 请求有效时，组合逻辑仍可能基于无意义的 `replay.bits` 产生错误 stall。

影响分析：该问题直接违反 FG-ARBITRATION/FC-DCACHE-MISS-REPLAY-PRIORITY/CK-REPLAY-INVALID-NO-STALL，会导致本不应该被阻塞的普通发射请求被随机卡住，且故障表现依赖 `io.replay.bits` 的残留值，隐蔽性很高。

置信度：95%

<LINK-BUG-[BG-NA]>

- 误判说明：动态测试 `test_stage0_replay_invalid_bits_do_not_stall_scalar_or_vector` 已通过；在当前黑盒可观测条件下，`io.replay.valid=0` 时未复现对 scalar/vector 的伪 stall。

<FILE-bosc_LoadUnit_RTL/LoadUnit.scala:306-318>

```scala
// bosc_LoadUnit_RTL/LoadUnit.scala 第306-318行
306:   val s0_rep_stall           = io.ldin.valid && isAfter(io.replay.bits.uop.lqIdx, io.ldin.bits.uop.lqIdx) ||
307:                                io.vecldin.valid && isAfter(io.replay.bits.uop.lqIdx, io.vecldin.bits.uop.lqIdx)
314:   val s0_src_valid_vec = WireInit(VecInit(Seq(
315:     io.misalign_ldin.valid,
316:     io.replay.valid && io.replay.bits.forward_tlDchannel,
317:     io.fast_rep_in.valid,
318:     io.replay.valid && !io.replay.bits.forward_tlDchannel && !s0_rep_stall,
```

根因分析：`s0_rep_stall` 的顺序比较条件没有把 `io.replay.valid` 作为先决条件。即使 `io.replay.valid=0`，只要 `io.ldin.valid` 或 `io.vecldin.valid` 为 1，`isAfter(io.replay.bits.uop.lqIdx, ...)` 仍会被求值，导致无效 replay 载荷反向影响正常仲裁。

修复建议：将 `s0_rep_stall` 改为 `io.replay.valid && (...)` 的形式，或者把 `isAfter(...)` 包装进 `Mux(io.replay.valid, ..., false.B)`，彻底隔离无效 replay 载荷。

<FG-SCALAR-PIPELINE>

#### 标量请求向 TLB 与 DCache 发起查询

<FC-SCALAR-TLB-DCACHE-REQ>

<CK-NO-ISSUE-WHEN-S1-BLOCKED>

<BG-STATIC-004-S0-REQ-FIRES-WHEN-STAGE1-BLOCKED>

问题描述：stage 0 的 TLB/DCache 请求 valid 没有与 `s0_can_go` 绑定，但 stage 1 的寄存器只在 `s0_fire = s0_valid && s0_can_go` 时才锁存输入。这意味着当 `s1_ready=0` 时，stage 0 仍可能向 TLB/DCache 发出握手请求，而该请求不会被流水线状态保存，形成重复访问或请求丢失。

影响分析：该问题直接违反 FG-SCALAR-PIPELINE/FC-SCALAR-TLB-DCACHE-REQ/CK-NO-ISSUE-WHEN-S1-BLOCKED，也会破坏 vector、replay、prefetch 等所有复用 stage 0 请求通路的源。

置信度：96%

<LINK-BUG-[BG-S0-REQ-FIRES-WHEN-S1-BLOCKED-99]>

<FILE-bosc_LoadUnit_RTL/LoadUnit.scala:231-232,383-406,846-848,913-916>

```scala
// bosc_LoadUnit_RTL/LoadUnit.scala 第231-232,383-406,846-848,913-916行
231:   val s0_can_go        = s1_ready
232:   val s0_fire          = s0_valid && s0_can_go
383:   io.tlb.req.valid                   := s0_tlb_valid
406:   io.dcache.req.valid             := s0_valid && !s0_sel_src.prf_i && !s0_nc_with_data
846:   io.vecldin.ready := s0_can_go && io.dcache.req.ready && s0_src_ready_vec(vec_iss_idx)
847:   io.ldin.ready := s0_can_go && io.dcache.req.ready && s0_src_ready_vec(int_iss_idx)
848:   io.misalign_ldin.ready := s0_can_go && io.dcache.req.ready && s0_src_ready_vec(mab_idx)
913:   when (s0_fire) { s1_valid := true.B }
916:   s1_in   := RegEnable(s0_out, s0_fire)
```

根因分析：上游 ready 使用 `s0_can_go` 保护，而对 TLB/DCache 的 valid 没有使用同样的保护条件。这样会出现“上游认为请求尚未被接收，但下游外设已经收到了请求”的协议撕裂。

修复建议：把 `io.tlb.req.valid` 与 `io.dcache.req.valid` 均改为基于 `s0_fire` 或至少显式与 `s0_can_go` 相与；同时检查所有依赖 `s0_valid` 的旁路控制输出，避免同类握手撕裂。

<FG-VECTOR-LOAD>

#### 向量写回输出

<FC-VECTOR-WRITEBACK>

<CK-VECLDOUT-BACKPRESSURE>

<BG-STATIC-005-VECLDOUT-READY-IGNORED>

问题描述：`io.vecldout` 是 Decoupled 接口，但 stage 3 的推进条件只看 `io.ldout.ready`，且 `io.vecldout.valid` 的生成完全不参考 `io.vecldout.ready`。当向量写回下游施加背压时，当前设计没有保存机制，可能直接丢失向量写回结果。

影响分析：该问题直接违反 FG-VECTOR-LOAD/FC-VECTOR-WRITEBACK/CK-VECLDOUT-BACKPRESSURE，会导致向量 load 在写回端存在非阻塞假设，破坏 ready/valid 协议。

置信度：98%

<LINK-BUG-[BG-VECLDOUT-READY-PORT-MISSING-99]>

- 说明：当前动态 Fail 直接证实了交付 wrapper 未导出 `vecldout.ready`，因此无法进一步黑盒验证内部是否正确消费 ready；该接口缺口与静态分析中“stage3 未参考 `io.vecldout.ready`”的结论相互印证。

<FILE-bosc_LoadUnit_RTL/LoadUnit.scala:1572-1573,1815-1855>

```scala
// bosc_LoadUnit_RTL/LoadUnit.scala 第1572-1573,1815-1855行
1572:   s3_ready := !s3_valid || s3_kill || io.ldout.ready
1815:   val vecFeedback = s3_valid && s3_fb_no_waiting && s3_lrq_rep_info.need_rep && !io.lsq.ldin.ready && s3_isvec
1818:   io.vecldout.bits.alignedType := s3_vec_alignedType
1823:   io.vecldout.bits.vecdata.get := Mux(
1832:   io.vecldout.bits.isvec := s3_vecout.isvec
1840:   io.vecldout.bits.hit := !s3_lrq_rep_info.need_rep || io.lsq.ldin.ready
1855:   io.vecldout.valid := s3_out.valid && !s3_out.bits.uop.robIdx.needFlush(io.redirect) && s3_vecout.isvec && !s3_mis_align && !s3_frm_mabuf
```

根因分析：vector 写回通道没有任何地方消费 `io.vecldout.ready`。stage 3 的 `s3_ready` 只依赖标量 `io.ldout.ready`，这意味着向量场景下即便 `vecldout.ready=0`，流水线也会继续前进并覆盖输出。

修复建议：将 stage 3 对向量写回的阻塞条件并入 `s3_ready`，例如在 vector 路径上要求 `io.vecldout.ready` 为真后才能释放当前结果；或者为 `vecldout` 增加独立寄存/缓冲，确保 ready/valid 满足标准协议。

## 批次分析进度

| 源文件 | 发现疑似Bug数 | 状态 |
|--------|-------------|------|
| <file>bosc_LoadUnit_RTL/LoadUnit.scala</file> | 5 | ✅ 完成 |

## 静态缺陷动态关联汇总

| 静态Bug | 动态Bug关联 | 结论 |
|--------|-------------|------|
| BG-STATIC-001-UNCACHE-PRIORITY-ORDER | LINK-BUG-[BG-UNCACHE-PRIORITY-ORDER-98] | 已证实 |
| BG-STATIC-002-NC-PRIORITY-ORDER | LINK-BUG-[BG-NC-PRIORITY-ORDER-VS-ORDINARY-REPLAY-97][BG-NC-PRIORITY-ORDER-VS-VECTOR-SCALAR-97][BG-NC-CONTENTION-PRIORITY-BROKEN-99] | 已证实，且在多个动态场景下表现为仲裁/旁路语义异常 |
| BG-STATIC-003-REPLAY-STALL-WITHOUT-VALID | LINK-BUG-[BG-NA] | 当前动态验证未复现，判定为静态误报 |
| BG-STATIC-004-S0-REQ-FIRES-WHEN-STAGE1-BLOCKED | LINK-BUG-[BG-S0-REQ-FIRES-WHEN-S1-BLOCKED-99] | 已证实 |
| BG-STATIC-005-VECLDOUT-READY-IGNORED | LINK-BUG-[BG-VECLDOUT-READY-PORT-MISSING-99] | 动态已证实接口缺口，且与内部 ready 风险相互印证 |
