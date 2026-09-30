
# bosc_LoadUnit 缺陷分析

## 未测试通过检测点分析

<FG-EXCEPTION-CONTROL>

#### 回滚与重定向控制 <FC-ROLLBACK-REDIRECT>

- <CK-LDLD-ROLLBACK> ld-ld 违例 rollback 未阻止普通写回：当 `io_lsq_ldld_nuke_query_resp_valid=1` 且 `io_lsq_ldld_nuke_query_resp_bits_rep_frm_fetch=1` 时，DUT 虽然能正确拉高 `io_rollback_valid`，但同拍仍继续拉高 `io_ldout_valid` 与 `io_feedback_slow_valid`，导致违例 load 同时沿“回滚路径”和“普通提交路径”对外可见；Bug 置信度 98% <BG-LDLD_ROLLBACK_NOT_BLOCKING_WRITEBACK-98>
  - 触发 Bug 的测试用例：
    - <TC-unity_test/tests/test_bosc_LoadUnit_exception_control.py::test_loadunit_ldld_violation_rollback> 使能 `ldld_vio_check_enable` 并注入 `ldld_nuke_query.resp.rep_frm_fetch=1` 后稳定复现；测试中 `rollback.robIdx` 正确等于当前 load 的 ROB=61，但 `ldout` 与 `feedback_slow` 仍在同一输出窗口出现
    - <TC-unity_test/tests/test_bosc_LoadUnit_forward_violation.py::test_loadunit_ldld_violation_control_response> 通过前递/违例功能域中的 `ldld_nuke_query` 路径再次稳定复现；可见 `rollback`/`revoke` 已出现，但 `ldout` 仍未被抑制
  - 备注：同批次的 `test_loadunit_stld_violation_redirect` 已通过，说明 testbench 对违例窗口和取消/写回互斥关系的建模是正确的，问题集中在 ld-ld rollback 后续抑制逻辑

<FG-FORWARD-VIOLATION>

#### load-to-load fast forward <FC-L2L-FAST-FORWARD>

- <CK-FAST-FWD-DATA> 顶层 wrapper 未暴露 L2L fast forward 数据输入接口：RTL 定义了 `io.l2l_fwd_in` 作为 load-to-load fast path 的外部输入，但当前交付 wrapper 中不存在 `io_l2l_fwd_in_valid` / `io_l2l_fwd_in_data` / `io_l2l_fwd_in_dly_ld_err` 等端口，导致黑盒环境无法构造成功路径；Bug 置信度 99% <BG-L2L_DATA_PORTS_MISSING-99>
  - 触发 Bug 的测试用例：
    - <TC-unity_test/tests/test_bosc_LoadUnit_forward_violation.py::test_loadunit_l2l_fast_forward_data_path> 用例在黑盒端口层检查 `io_l2l_fwd_in_*` 是否存在时稳定失败，无法进入真正的数据路径验证
    - <TC-unity_test/tests/test_bosc_LoadUnit_replay_kill.py::test_loadunit_l2l_success_has_no_false_kill> replay/kill 功能域中的 L2L success-no-false-kill 场景同样需要 `io_l2l_fwd_in_valid/data/dly_ld_err` 作为黑盒输入，但 wrapper 未导出这些端口，测试在接口存在性检查阶段稳定失败

- <CK-FAST-FWD-FAIL-PATH> 顶层 wrapper 未暴露 L2L fast forward 失败判定控制接口：RTL 需要外部提供 `io.ld_fast_match` / `io.ld_fast_imm` / `io.ld_fast_fuOpType` 才能判定 fast forward 的 mismatch、地址越界和立即数相关失败路径，但当前交付 wrapper 缺失这些输入端口，导致黑盒环境无法构造失败路径；Bug 置信度 99% <BG-L2L_CTRL_PORTS_MISSING-99>
  - 触发 Bug 的测试用例：
    - <TC-unity_test/tests/test_bosc_LoadUnit_forward_violation.py::test_loadunit_l2l_fast_forward_fail_path> 用例在黑盒端口层检查 `io_ld_fast_*` 是否存在时稳定失败，无法进入真正的失败路径验证
    - <TC-unity_test/tests/test_bosc_LoadUnit_replay_kill.py::test_loadunit_l2l_fail_triggers_stage1_kill> replay/kill 功能域中的 L2L fail-kill 场景需要 `io_ld_fast_match` / `io_ld_fast_fuOpType` / `io_ld_fast_imm` 与 `io_l2l_fwd_in_valid` 共同驱动，但当前 wrapper 未暴露这些控制输入，测试在接口存在性检查阶段稳定失败

<FG-REPLAY-KILL>

#### stage1 kill on L2L fail <FC-S1-KILL-ON-L2L-FAIL>

- <CK-L2L-FAIL-KILL> 顶层 wrapper 缺少 L2L fail path 的黑盒控制入口，导致无法从 replay/kill 功能域构造 pointer-chasing mismatch 并验证 stage1 kill；Bug 置信度 99% <BG-L2L-KILL-CTRL-PORTS-MISSING-99>
  - 触发 Bug 的测试用例：
    - <TC-unity_test/tests/test_bosc_LoadUnit_replay_kill.py::test_loadunit_l2l_fail_triggers_stage1_kill> 用例需要 `io_l2l_fwd_in_valid`、`io_ld_fast_match`、`io_ld_fast_fuOpType`、`io_ld_fast_imm` 共同驱动 L2L fail path，但运行时顶层 wrapper 缺少这些输入端口
  - 备注：根因与 BG-L2L_CTRL_PORTS_MISSING-99 相同，属于交付 wrapper 与 RTL 接口定义不一致

- <CK-L2L-SUCCESS-NO-KILL> 顶层 wrapper 缺少 L2L success path 的黑盒数据入口，导致无法从 replay/kill 功能域构造 pointer-chasing 成功路径并验证“不误杀”；Bug 置信度 99% <BG-L2L-KILL-DATA-PORTS-MISSING-99>
  - 触发 Bug 的测试用例：
    - <TC-unity_test/tests/test_bosc_LoadUnit_replay_kill.py::test_loadunit_l2l_success_has_no_false_kill> 用例需要 `io_l2l_fwd_in_valid`、`io_l2l_fwd_in_data`、`io_l2l_fwd_in_dly_ld_err` 作为黑盒输入，但运行时顶层 wrapper 缺少这些数据端口
  - 备注：根因与 BG-L2L_DATA_PORTS_MISSING-99 相同，属于交付 wrapper 与 RTL 接口定义不一致

<FG-MISALIGN-LOAD>

#### 16B 边界相关处理 <FC-MISALIGN-BOUNDARY-HANDLING>

- <CK-NO-CROSS-16B> 不跨 16B 边界的首次 misalign 请求未进入 MisalignBuffer：按照 README 的“特性 5”描述，首次上流水的非对齐 load 若“不跨越 16 字节边界”应通过 `io_misalign_enq` 进入 MisalignBuffer；但当前 RTL 在该场景下不会产生 `io_misalign_enq.req.valid`，而是继续沿普通 `ldout/feedback_slow` 路径完成写回；Bug 置信度 97% <BG-MISALIGN-NO-CROSS16-NOT-ENQUEUED-97>
  - 触发 Bug 的测试用例：
    - <TC-unity_test/tests/test_bosc_LoadUnit_misalign_load.py::test_loadunit_misalign_no_cross_16b_boundary_path> 使用地址 `0x1003` 的 64bit 标量 load（非对齐但不跨 16B），并显式打开 `hd_misalign_ld_enable` 与 `misalign_allow_spec`；结果观察到普通 `ldout` 写回，但始终没有 `misalign_enq`
  - 备注：同批次的 `test_loadunit_misalign_detect_and_enqueue` 与 `test_loadunit_misalign_cross_16b_boundary_path` 使用跨 16B 地址 `0x100f` 可稳定观察到 `misalign_enq`，说明 testbench 对 misalign 控制位和响应窗口的建模正确，问题集中在 no-cross-16B 的首次分流条件

<FG-NONCACHEABLE-LOAD>

#### 第二次上流水 bypass TLB <FC-NC-BYPASS-TLB>

- <CK-NC-NO-TLB-QUERY-WITH-CONTENTION> NC 请求与普通标量请求同拍竞争时错误触发 TLB 查询：README 明确规定 NC 第二次上流水优先级高于普通标量 load，且该路径不应重新查询 TLB；但当前 DUT 在 `io_lsq_nc_ldin` 与 `io_ldin` 同拍有效时，仍然稳定观察到 `io_tlb_req_valid=1`，说明 stage 0 实际选中的并不是 NC bypass 路径；Bug 置信度 99% <BG-NC-CONTENTION-PRIORITY-BROKEN-99>
  - 触发 Bug 的测试用例：
    - <TC-unity_test/tests/test_bosc_LoadUnit_noncacheable_load.py::test_loadunit_nc_contention_still_does_not_query_tlb> 同拍驱动 `io_lsq_nc_ldin` 与 `io_ldin` 后，在随后的 4 拍观察窗口首拍稳定看到 `tlb_req_valid=1`，违反“NC 在竞争下仍 bypass TLB”的规格
  - 备注：同批次的 `test_loadunit_nc_attribute_detect_first_pass`、`test_loadunit_nc_second_pass_has_no_tlb_request`、`test_loadunit_nc_path_entry_differs_from_normal_path` 在无竞争场景均已 Pass，说明 NC 路径本身具备 bypass-TLB 机制，问题集中在 stage 0 竞争仲裁

<FG-SCALAR-PIPELINE>

#### 标量请求向 TLB 与 DCache 发起查询 <FC-SCALAR-TLB-DCACHE-REQ>

- <CK-NO-ISSUE-WHEN-S1-BLOCKED> 第一条标量 load 在 `io_ldout_ready=0` 下占用写回口时，第二条标量请求仍被提前送往 TLB/DCache：黑盒观察可见第一条请求的 `ldout` 写回仍在 backpressure 窗口中有效，但第二条请求同拍已经把 `dcache.req.bits.lqIdx=34` 推出到外部接口，违反“stage1 blocked 时 stage0 不得先行发请求”的协议要求；Bug 置信度 99% <BG-S0-REQ-FIRES-WHEN-S1-BLOCKED-99>
  - 触发 Bug 的测试用例：
    - <TC-unity_test/tests/test_bosc_LoadUnit_scalar_pipeline.py::test_loadunit_scalar_no_issue_when_stage1_blocked> 先发射 `lqIdx=33` 的标量 load，再在其写回窗口拉低 `io_ldout_ready` 并发射 `lqIdx=34` 的第二条请求；结果在第一条 `ldout` 仍有效的窗口内，稳定观察到第二条请求的 `dcache.req` 已经对外可见
  - 备注：该缺陷是对 `unity_test/bosc_LoadUnit_static_bug_analysis.md` 中 `BG-STATIC-004-S0-REQ-FIRES-WHEN-STAGE1-BLOCKED` 的动态复现确认

#### 标量写回背压 <FC-SCALAR-WRITEBACK-BACKPRESSURE>

- <CK-HOLD-UNDER-BACKPRESSURE> 标量写回在 `io_ldout_ready=0` 时不能稳定保持：单条普通标量 load 在 ready 预先拉低的场景下，只会输出 1 拍 `io_ldout_valid`，下一拍 `valid` 与写回元数据即被撤掉，没有形成符合 Decoupled 语义的持续保持；Bug 置信度 98% <BG-LDOUT-BACKPRESSURE-NOT-HELD-98>
  - 触发 Bug 的测试用例：
    - <TC-unity_test/tests/test_bosc_LoadUnit_scalar_pipeline.py::test_loadunit_scalar_writeback_holds_under_backpressure> 在请求发射前即拉低 `io_ldout_ready`，随后观察目标 `robIdx=89/lqIdx=36` 的写回窗口；当前 DUT 只在首个到达周期给出 1 拍 `ldout.valid`

- <CK-RELEASE-ON-READY> 标量写回在背压期间被提前丢失，导致 `ready` 恢复后无法按“一次且仅一次”正确释放：由于挂起写回没有被保存，`io_ldout_ready` 从 0 恢复为 1 时，不存在稳定待释放的同一条写回，释放语义因此被破坏；Bug 置信度 98% <BG-LDOUT-READY-RELEASE-BROKEN-98>
  - 触发 Bug 的测试用例：
    - <TC-unity_test/tests/test_bosc_LoadUnit_scalar_pipeline.py::test_loadunit_scalar_writeback_releases_on_ready> 在 `io_ldout_ready=0` 下发射 `robIdx=90/lqIdx=37` 的标量 load，测试要求先看到稳定保持，再在 `ready=1` 后释放；当前 DUT 在“保持”阶段即已失败，说明释放语义不存在可靠的前置状态

<FG-ARBITRATION>

#### uncache / NC 仲裁优先级 <FC-UNCACHE-NC-PRIORITY>

- <CK-UNCACHE-OVER-REPLAY-VECTOR-SCALAR> uncache 请求在与普通 replay、vector、scalar 同拍竞争时没有拿到最高规格优先级：黑盒观察可见 `io_lsq_uncache_ready=0`，同时普通 replay 已经占用了 `dcache.req.bits.lqIdx=63`，说明 stage0 实际先选择了普通 replay 而不是 uncache；Bug 置信度 98% <BG-UNCACHE-PRIORITY-ORDER-98>
  - 触发 Bug 的测试用例：
    - <TC-unity_test/tests/test_bosc_LoadUnit_stage0_arbitration.py::test_stage0_uncache_priority_over_replay_vector_and_scalar> 同拍驱动 uncache、普通 replay、vector 和 scalar 请求后，在竞争拍稳定观察到 `uncache.ready=0`、`replay.ready=1`、`dcache.req.lqIdx=63`
  - 备注：该缺陷动态确认了 `unity_test/bosc_LoadUnit_static_bug_analysis.md` 中的 `BG-STATIC-001-UNCACHE-PRIORITY-ORDER`

- <CK-NC-OVER-ORDINARY-REPLAY> NC 请求在与普通 replay 同拍竞争时被普通 replay 抢占：黑盒观察可见 `io_lsq_nc_ldin_ready=0`，而 `io_replay_ready=1` 且 `dcache.req.bits.lqIdx=73`，违反 README 中“NC 高于普通 replay”的优先级要求；Bug 置信度 97% <BG-NC-PRIORITY-ORDER-VS-ORDINARY-REPLAY-97>
  - 触发 Bug 的测试用例：
    - <TC-unity_test/tests/test_bosc_LoadUnit_stage0_arbitration.py::test_stage0_nc_priority_over_ordinary_replay> 同拍驱动 NC 与 `forward_tlDchannel=0` 的普通 replay 后，stage0 稳定先接受 replay，NC 保持未消费

- <CK-NC-OVER-VECTOR-SCALAR> NC 请求在与 vector/scalar 同拍竞争时被 vector 抢占：黑盒观察可见 `io_lsq_nc_ldin_ready=0`，同时 `io_vecldin_ready=1` 且 `dcache.req.bits.lqIdx=83`，说明 NC 的 stage0 优先级被错误降到了 vector/scalar 之后；Bug 置信度 97% <BG-NC-PRIORITY-ORDER-VS-VECTOR-SCALAR-97>
  - 触发 Bug 的测试用例：
    - <TC-unity_test/tests/test_bosc_LoadUnit_stage0_arbitration.py::test_stage0_nc_priority_over_vector_and_scalar> 同拍驱动 NC、vector 和 scalar 请求后，stage0 稳定先接受 vector，请求元数据对应 `lqIdx=83`
  - 备注：`CK-NC-OVER-ORDINARY-REPLAY` 与 `CK-NC-OVER-VECTOR-SCALAR` 共享同一根因，均属于 `BG-STATIC-002-NC-PRIORITY-ORDER` 的动态复现

#### 预取 / 向量 / 标量 仲裁 <FC-PREFETCH-VECTOR-SCALAR-PRIORITY>

- <CK-HIGHCONF-OVER-VECTOR> 高置信度 prefetch 与 vector 同拍竞争时出现“prefetch 占用 DCache，但 vector 同时误触发 TLB”的双发射撕裂：外部观察可见 `dcache.req` 已经对应高置信度 prefetch（`pf_source=5`，向量 `ready=0`），但 `io_tlb_req_valid` 却仍被拉高，违反“prefetch 请求不应重新走 TLB 翻译”的规格；Bug 置信度 97% <BG-HIGHCONF-PREFETCH-SPURIOUS-TLB-REQ-97>
  - 触发 Bug 的测试用例：
    - <TC-unity_test/tests/test_bosc_LoadUnit_stage0_arbitration.py::test_stage0_high_confidence_prefetch_priority_over_vector> 同拍驱动 `confidence=3` 的 prefetch 和 `lqIdx=40` 的 vector 请求后，观察到 `vector.ready=0`、`dcache.req.valid=1`，说明 DCache 端仲裁选中了 prefetch；但同拍 `io_tlb_req_valid=1`，证明 vector 的普通翻译请求仍被错误带出
  - 备注：该问题不会在“只有 prefetch”的空闲场景出现，因此 `test_loadunit_highconf_prefetch_accept_when_available` 仍可通过；问题只在与 vector/scalar 等普通翻译源竞争时暴露

<FG-VECTOR-LOAD>

#### 向量写回输出 <FC-VECTOR-WRITEBACK>

- <CK-VECLDOUT-BACKPRESSURE> 向量写回口未导出 `vecldout.ready`，导致黑盒环境无法对 Decoupled 写回通道施加背压：当前交付的 `signals.json`、`bosc_LoadUnit_top.v` 和 Python env 仅暴露 `io_vecldout_valid` 与 `io_vecldout_bits_*`，没有任何 `ready` 入口；因此 `CK-VECLDOUT-BACKPRESSURE` 会在接口存在性检查阶段稳定失败。结合 `LoadUnit.scala` 中 stage3 仍只依赖 `io.ldout.ready` 的实现，该问题同时说明向量写回的 ready/valid 协议存在真实设计风险；Bug 置信度 99% <BG-VECLDOUT-READY-PORT-MISSING-99>
  - 触发 Bug 的测试用例：
    - <TC-unity_test/tests/test_bosc_LoadUnit_vector_load.py::test_loadunit_vector_writeback_holds_under_backpressure> 复位后直接检查 `env.vector_resp` 是否具备 `ready` 属性，稳定失败；失败信息明确表明当前黑盒接口无法对向量写回口施加背压
  - 备注：该问题与 `unity_test/bosc_LoadUnit_static_bug_analysis.md` 中的 `BG-STATIC-005-VECLDOUT-READY-IGNORED` 相互印证；前者是“交付接口缺口”，后者是“内部 stage3 未消费 ready”

## 缺陷根因分析

### 1. ld-ld 违例 rollback 未屏蔽普通写回

**缺陷描述：**  
LoadUnit 在 stage 3 收到 ld-ld violation 的 `rep_frm_fetch` 响应后，会正确产生 `io.rollback.valid`，但没有同步关闭普通写回相关控制，导致同一条指令既请求回滚，又继续通过 `ldout`/`feedback_slow` 向后端传播“正常完成”语义。

**影响范围：**
- FG-EXCEPTION-CONTROL/FC-ROLLBACK-REDIRECT/CK-LDLD-ROLLBACK （BG-LDLD_ROLLBACK_NOT_BLOCKING_WRITEBACK-98）

**根本原因：**  
`s3_ldld_rep_inst` / `s3_flushPipe` 只被用于生成 `io.rollback.valid`，但没有参与 `s3_out.valid`、`io.feedback_slow.valid`、`io.ldout.valid`，甚至 `io.lsq.ldin.valid` 的抑制条件。也就是说，违例检测命中了“回滚控制”，却没有命中“结果提交屏蔽”，于是形成互相矛盾的双重外发。

**具体代码缺陷：**
```scala
// bosc_LoadUnit_RTL/LoadUnit.scala 第1578-1579,1605-1609,1631-1632,1672,1694-1701,1785-1788行
1578:   val s3_can_enter_lsq_valid = s3_valid && (!s3_fast_rep || s3_fast_rep_canceled) && !s3_in.feedbacked
1579:   io.lsq.ldin.valid := s3_can_enter_lsq_valid
1605:   val s3_ldld_rep_inst =
1606:       io.lsq.ldld_nuke_query.resp.valid &&
1607:       io.lsq.ldld_nuke_query.resp.bits.rep_frm_fetch &&
1608:       GatedValidRegNext(io.csrCtrl.ldld_vio_check_enable)
1609:   val s3_flushPipe = s3_ldld_rep_inst
1631:   s3_out.valid                := s3_valid && s3_safe_writeback && !toMisalignBufferValid
1632:   s3_out.bits.uop             := s3_in.uop
1672:   io.rollback.valid := s3_valid && (s3_rep_frm_fetch || s3_flushPipe || s3_frm_mis_flush) && !s3_exception
1694:   val s3_fb_no_waiting = !s3_in.isLoadReplay &&
1695:                         (!(s3_fast_rep && !s3_fast_rep_canceled)) &&
1696:                         !s3_in.feedbacked
1700:   io.feedback_slow.valid                 := s3_valid && s3_fb_no_waiting && !s3_isvec && !s3_frm_mabuf
1785:   val s3_ldout_valid  = s3_mmio_req.valid ||
1786:                         s3_out.valid && RegNext(!s2_out.isvec && !s2_out.isFrmMisAlignBuf)
1787:   io.ldout.valid       := s3_ldout_valid
1788:   io.ldout.bits        := s3_ld_wb_meta
```

上述代码中，`s3_flushPipe` 只参与了 `io.rollback.valid`，却没有出现在 `s3_out.valid`、`io.feedback_slow.valid`、`io.ldout.valid` 和 `io.lsq.ldin.valid` 的屏蔽条件里，因此 rollback 与正常写回可以并存。

**修复建议：**
```scala
// 建议引入统一的 stage 3 提交屏蔽条件
val s3_cancel_commit = s3_rep_frm_fetch || s3_flushPipe || s3_frm_mis_flush

s3_out.valid := s3_valid && s3_safe_writeback && !toMisalignBufferValid && !s3_cancel_commit
io.feedback_slow.valid := s3_valid && s3_fb_no_waiting && !s3_isvec && !s3_frm_mabuf && !s3_cancel_commit
io.lsq.ldin.valid := s3_can_enter_lsq_valid && !s3_cancel_commit
io.ldout.valid := s3_mmio_req.valid || (s3_out.valid && RegNext(!s2_out.isvec && !s2_out.isFrmMisAlignBuf))
```

如果设计者希望 `rollback` 与某些 debug-only 观测信号共存，也应至少保证 `ldout`、`feedback_slow`、`lsq.ldin` 这三类会影响架构态或队列状态的接口在 rollback 场景下被完全屏蔽。

**验证方法：**  
修复后重新运行 `unity_test/tests/test_bosc_LoadUnit_exception_control.py::test_loadunit_ldld_violation_rollback`。期望波形与断言表现为：`io_rollback_valid=1` 时，`io_ldout_valid=0`、`io_feedback_slow_valid=0`、`io_lsq_ldin_valid=0`；同批次其余 9 个异常控制测试应继续保持 Pass。

### 2. L2L fast forward 数据输入端口在交付 wrapper 中缺失

**缺陷描述：**  
`LoadUnit.scala` 明确定义了 `io.l2l_fwd_in` 输入端口，并在 stage 0 / stage 1 中直接读取该端口的数据与 delayed-error 信息作为 load-to-load fast path 的输入，但当前交付给验证环境的顶层 wrapper 没有导出 `io_l2l_fwd_in_*` 引脚，导致黑盒测试无法驱动该功能。

**影响范围：**
- FG-FORWARD-VIOLATION/FC-L2L-FAST-FORWARD/CK-FAST-FWD-DATA （BG-L2L_DATA_PORTS_MISSING-99）

**根本原因：**  
RTL 逻辑层面保留了 `l2l_fwd_in` 作为顶层输入，但最终交付的 wrapper / signal tree 没有同步暴露这些信号，导致验证环境只能看到 `io_s2_ptr_chasing` 这类结果侧代理，却没有任何手段从黑盒端口驱动真实的 point-chasing 请求。

**具体代码缺陷：**
```scala
// bosc_LoadUnit_RTL/LoadUnit.scala 第173-174,372-374,920行
173:     val l2l_fwd_in    = Input(new LoadToLoadIO)
174:     val l2l_fwd_out   = Output(new LoadToLoadIO)
372:   val s0_try_ptr_chasing      = s0_src_select_vec(l2l_fwd_idx)
373:   val s0_do_try_ptr_chasing   = s0_try_ptr_chasing && s0_can_go && io.dcache.req.ready
374:   val s0_ptr_chasing_vaddr    = io.l2l_fwd_in.data(5, 0) +& io.ld_fast_imm(5, 0)
920:   val s1_l2l_fwd_dly_err  = RegEnable(io.l2l_fwd_in.dly_ld_err, io.l2l_fwd_in.valid) && s1_in.isFastPath
```

上述源码证明 `io.l2l_fwd_in` 是功能必需输入；但当前 `bosc_LoadUnit/signals.json` 与运行时 DUT 反射结果都没有对应的 `io_l2l_fwd_in_*` 端口，属于交付 wrapper 与 RTL 接口定义不一致。

**修复建议：**  
重新生成并核对 `bosc_LoadUnit` 顶层 wrapper / signal tree，确保 `LoadToLoadIO` 的 `valid`、`data`、`dly_ld_err` 等字段完整导出到 Python DUT 接口。如果当前配置确实不支持 point-chasing，则应同时：
1. 在 README 和功能覆盖定义中显式删除/屏蔽 `FC-L2L-FAST-FORWARD`；
2. 不再让 `signals.json`、模板测试和覆盖模型宣称该功能可测。

**验证方法：**  
修复后重新运行 `unity_test/tests/test_bosc_LoadUnit_forward_violation.py::test_loadunit_l2l_fast_forward_data_path`。期望结果是黑盒环境能够成功访问 `io_l2l_fwd_in_*` 端口，并进一步把测试从“端口存在性检查”升级为真实数据路径断言。

### 3. L2L fast forward 失败判定控制端口在交付 wrapper 中缺失

**缺陷描述：**  
L2L fast forward 失败路径需要 `io.ld_fast_match`、`io.ld_fast_imm`、`io.ld_fast_fuOpType` 等外部输入来构造 mismatch、地址跨 cache set 和 fuOpType 不匹配等失败条件，但当前交付 wrapper 同样没有导出这些信号，导致黑盒环境无法验证 fail path。

**影响范围：**
- FG-FORWARD-VIOLATION/FC-L2L-FAST-FORWARD/CK-FAST-FWD-FAIL-PATH （BG-L2L_CTRL_PORTS_MISSING-99）

**根本原因：**  
fast forward 失败路径的关键判定全部依赖外部输入，但 wrapper 没有把这些输入暴露出来，功能逻辑存在于 RTL，验证入口却在交付件中被截断。

**具体代码缺陷：**
```scala
// bosc_LoadUnit_RTL/LoadUnit.scala 第176-178,1075-1083行
176:     val ld_fast_match    = Input(Bool())
177:     val ld_fast_fuOpType = Input(UInt())
178:     val ld_fast_imm      = Input(UInt(12.W))
1075:     s1_addr_mismatch     := s1_ptr_chasing_vaddr(6) ||
1076:                              RegEnable(io.ld_fast_imm(11, 6).orR, s0_do_try_ptr_chasing)
1077:     // Case 1: the address is not 64-bit aligned or the fuOpType is not LD
1078:     s1_addr_misaligned := s1_ptr_chasing_vaddr(2, 0).orR
1083:     s1_fast_mismatch := RegEnable(!io.ld_fast_match, s0_do_try_ptr_chasing)
```

这些判定信号在 RTL 中是标准输入，但当前黑盒接口中不存在 `io_ld_fast_match` / `io_ld_fast_fuOpType` / `io_ld_fast_imm`，因此 fail path 无法被激励。

**修复建议：**  
与 `BG-L2L_DATA_PORTS_MISSING-99` 一样，需要统一修复 wrapper 导出逻辑；如果该配置下彻底不支持 point-chasing，则应在规格、覆盖模型和测试模板中同步移除对应失败路径检查点，避免“逻辑存在但接口不可达”的半交付状态。

**验证方法：**  
修复后重新运行 `unity_test/tests/test_bosc_LoadUnit_forward_violation.py::test_loadunit_l2l_fast_forward_fail_path`。期望黑盒环境能够驱动 `io_ld_fast_*` 端口，构造 mismatch/imm 越界等失败条件，并看到 `s1_kill` 代理或 fallback 路径的可观测行为。

### 4. no-cross-16B 的首次 misalign 请求未进入 MisalignBuffer

**缺陷描述：**  
README 明确要求“如果不是来自于 LoadMisalignBuffer 的请求并且没有跨越 16 字节边界的非对齐请求，那么需要进入 LoadMisalignBuffer 处理”。但当前 RTL 对首次 misalign 的条件编码正好相反：不跨 16B 的 misalign 被当成普通写回路径继续执行，只有跨 16B 的场景才会进入 `io.misalign_enq`。

**影响范围：**
- FG-MISALIGN-LOAD/FC-MISALIGN-BOUNDARY-HANDLING/CK-NO-CROSS-16B （BG-MISALIGN-NO-CROSS16-NOT-ENQUEUED-97）

**根本原因：**  
`s0_misalignWith16Byte` 的定义实际表示“非对齐且不跨 16B”，但 stage 2 的 `s2_mis_align` 又要求 `!s2_in.misalignWith16Byte` 才认为需要进入 misalign 流程。两者组合起来后，真正被送入 MisalignBuffer 的变成了“跨 16B”的子集，而 README 规定应进入 MisalignBuffer 的“非跨 16B”场景反而被排除。

**具体代码缺陷：**
```scala
// bosc_LoadUnit_RTL/LoadUnit.scala 第729-733,1237-1238,1586-1588行
729:   val s0_rs_cross16Bytes = s0_check_vaddr_Up_low(4) =/= s0_check_vaddr_low(4)
730:   val s0_misalignWith16Byte = !s0_rs_cross16Bytes && !s0_addr_aligned && !s0_hw_prf_select
731:   val s0_misalignNeedWakeUp = s0_sel_src.frm_mabuf && io.misalign_ldin.bits.misalignNeedWakeUp
732:   val s0_finalSplit = s0_sel_src.frm_mabuf && io.misalign_ldin.bits.isFinalSplit
733:   s0_is128bit := s0_sel_src.is128bit || s0_misalignWith16Byte

1237:   val s2_mis_align = s2_valid && GatedValidRegNext(io.csrCtrl.hd_misalign_ld_enable) &&
1238:                      s2_out.isMisalign && !s2_in.misalignWith16Byte && !s2_exception_vec(breakPoint) && !s2_trigger_debug_mode && !s2_uncache

1586:   val toMisalignBufferValid = s3_can_enter_lsq_valid && s3_mis_align && !s3_frm_mabuf
1587:   io.misalign_enq.req.valid := toMisalignBufferValid && s3_misalign_can_go
1588:   io.misalign_enq.req.bits  := s3_in
```

从上述逻辑可见：
1. `s0_misalignWith16Byte` 在 `!s0_rs_cross16Bytes` 条件下置位，实际对应“不跨 16B”的 misalign；
2. `s2_mis_align` 又要求 `!s2_in.misalignWith16Byte` 才进入 misalign 分流；
3. 最终 `io.misalign_enq.req.valid` 只能在“跨 16B”的场景下被拉高。

这与 README 第 155-158 行对 no-cross-16B 场景的描述直接冲突。

**修复建议：**
```scala
// 方案一：修正布尔语义，使其真正表示“跨 16B”
val s0_cross16ByteMisalign = s0_rs_cross16Bytes && !s0_addr_aligned && !s0_hw_prf_select

// 如果规格要求 no-cross-16B 进入 MisalignBuffer，则 stage 2 条件也应按规格重写
val s2_mis_align = s2_valid &&
                   GatedValidRegNext(io.csrCtrl.hd_misalign_ld_enable) &&
                   s2_out.isMisalign &&
                   s2_in.misalignWith16Byte &&
                   !s2_exception_vec(breakPoint) &&
                   !s2_trigger_debug_mode &&
                   !s2_uncache
```

或者更稳妥地，将“是否跨 16B”与“是否需要进入 MisalignBuffer”拆成两个含义清晰的独立信号，避免继续用 `misalignWith16Byte` 这种容易误读的命名承载两层语义。

**验证方法：**  
修复后重新运行 `unity_test/tests/test_bosc_LoadUnit_misalign_load.py::test_loadunit_misalign_no_cross_16b_boundary_path`。期望结果为：在地址 `0x1003` 的 64bit misalign 首次请求下，`io_misalign_enq_req_valid=1`，且窗口内不会出现普通 `io_ldout_valid`。同时，`test_loadunit_aligned_request_does_not_enqueue_misalign` 应继续保持 Pass，证明修复没有把对齐请求误导入 MisalignBuffer。

### 5. NC 与标量竞争时优先级错误，导致 bypass-TLB 失效

**缺陷描述：**  
README 规定 NC 请求在 stage 0 的优先级高于普通标量 load，且 NC 第二次上流水不应重新向 TLB 发请求。但当前 RTL 在 `io.lsq.nc_ldin` 与 `io.ldin` 同拍有效时，会让标量路径先被选中，于是外部可见 `io_tlb_req_valid=1`，破坏了 NC 的 bypass-TLB 语义。

**影响范围：**
- FG-NONCACHEABLE-LOAD/FC-NC-BYPASS-TLB/CK-NC-NO-TLB-QUERY-WITH-CONTENTION （BG-NC-CONTENTION-PRIORITY-BROKEN-99）

**根本原因：**  
stage 0 的仲裁优先级完全由 `s0_src_valid_vec` 的排列顺序隐式决定，而当前实现把 `io.ldin.valid` 放在 `io.lsq.nc_ldin.valid` 之前。这样一来，只要 scalar 和 NC 同拍有效，`s0_src_ready_vec` 就会先把标量端口选中。与此同时，`io.tlb.req.valid` 又是根据“哪类源 valid”而不是“最终选中了哪一类源”生成的，因此一旦 scalar 被抢先选中，就会直接拉起普通 TLB 查询，NC bypass-TLB 语义随之失效。

**具体代码缺陷：**
```scala
// bosc_LoadUnit_RTL/LoadUnit.scala 第309-369行，NC 在仲裁顺序中落在 scalar 之后，TLB valid 也按普通源类型生成
309:   private val Seq(
310:     mab_idx, super_rep_idx, fast_rep_idx, lsq_rep_idx, high_pf_idx,
311:     vec_iss_idx, int_iss_idx, mmio_idx, nc_idx, l2l_fwd_idx, low_pf_idx
312:   ) = (0 until SRC_NUM).toSeq
313:   // load flow source valid
314:   val s0_src_valid_vec = WireInit(VecInit(Seq(
315:     io.misalign_ldin.valid,
316:     io.replay.valid && io.replay.bits.forward_tlDchannel,
317:     io.fast_rep_in.valid,
318:     io.replay.valid && !io.replay.bits.forward_tlDchannel && !s0_rep_stall,
319:     io.prefetch_req.valid && io.prefetch_req.bits.confidence > 0.U,
320:     io.vecldin.valid,
321:     io.ldin.valid, // BUG: scalar 被放在 NC 之前
322:     io.lsq.uncache.valid,
323:     io.lsq.nc_ldin.valid,
324:     io.l2l_fwd_in.valid,
325:     io.prefetch_req.valid && io.prefetch_req.bits.confidence === 0.U,
326:   )))
330:   for(i <- 1 until SRC_NUM){
331:     s0_src_ready_vec(i) := !s0_src_valid_vec.take(i).reduce(_ || _)
332:   }
334:   val s0_src_select_vec = WireInit(VecInit((0 until SRC_NUM).map{i => s0_src_valid_vec(i) && s0_src_ready_vec(i)}))
337:   val s0_tlb_no_query = s0_hw_prf_select || s0_sel_src.prf_i ||
338:     s0_src_select_vec(fast_rep_idx) || s0_src_select_vec(mmio_idx) ||
339:     s0_src_select_vec(nc_idx)
362:   s0_tlb_valid := (
363:     s0_src_valid_vec(mab_idx) ||
364:     s0_src_valid_vec(super_rep_idx) ||
365:     s0_src_valid_vec(lsq_rep_idx) ||
366:     s0_src_valid_vec(vec_iss_idx) ||
367:     s0_src_valid_vec(int_iss_idx) || // scalar 胜出时会直接触发 TLB
368:     s0_src_valid_vec(l2l_fwd_idx)
369:   ) && io.dcache.req.ready
```

从上述代码可见：
1. `io.ldin.valid` 的优先级高于 `io.lsq.nc_ldin.valid`；
2. `s0_src_ready_vec`/`s0_src_select_vec` 因此前者先命中时会压制 NC；
3. `io.tlb.req.valid` 又会把被选中的 scalar 当作普通请求处理，于是外部直接观察到 `tlb_req_valid=1`。

**修复建议：**
```scala
// 方案一：按 README 规格重排 stage 0 的源优先级
private val Seq(
  mab_idx, super_rep_idx, fast_rep_idx, mmio_idx, nc_idx, lsq_rep_idx,
  high_pf_idx, vec_iss_idx, int_iss_idx, l2l_fwd_idx, low_pf_idx
) = (0 until SRC_NUM).toSeq

val s0_src_valid_vec = WireInit(VecInit(Seq(
  io.misalign_ldin.valid,
  io.replay.valid && io.replay.bits.forward_tlDchannel,
  io.fast_rep_in.valid,
  io.lsq.uncache.valid,
  io.lsq.nc_ldin.valid,
  io.replay.valid && !io.replay.bits.forward_tlDchannel && !s0_rep_stall,
  io.prefetch_req.valid && io.prefetch_req.bits.confidence > 0.U,
  io.vecldin.valid,
  io.ldin.valid,
  io.l2l_fwd_in.valid,
  io.prefetch_req.valid && io.prefetch_req.bits.confidence === 0.U,
)))

// 方案二：TLB valid 尽量基于“最终选中的源”而不是原始 valid 列表生成
val s0_selected_need_tlb =
  s0_src_select_vec(mab_idx) ||
  s0_src_select_vec(super_rep_idx) ||
  s0_src_select_vec(lsq_rep_idx) ||
  s0_src_select_vec(vec_iss_idx) ||
  s0_src_select_vec(int_iss_idx) ||
  s0_src_select_vec(l2l_fwd_idx)
io.tlb.req.valid := s0_selected_need_tlb && io.dcache.req.ready
```

至少要保证 NC 的优先级真实高于普通 scalar/vector/replay，同时避免未被选中的低优先级源通过“原始 valid”旁路影响 TLB 请求生成。

**验证方法：**  
修复后重新运行 `unity_test/tests/test_bosc_LoadUnit_noncacheable_load.py::test_loadunit_nc_contention_still_does_not_query_tlb`。期望结果为：同拍驱动 NC 与 scalar 请求时，观察窗口内 `io_tlb_req_valid=0`，且后续仍能看到 NC 的专用前递/RAR-RAW/写回路径。同时 `test_loadunit_nc_second_pass_has_no_tlb_request` 与 `test_loadunit_nc_attribute_detect_first_pass` 应继续保持 Pass，证明修复没有破坏无竞争场景下的 NC 行为。

### 6. stage1/stage3 被阻塞时，stage0 仍会提前向 TLB/DCache 发第二条请求

**缺陷描述：**  
当第一条标量请求已经进入写回阶段且 `io_ldout_ready=0` 时，LoadUnit 理应把 backpressure 一直向前传回 stage2/stage1/stage0，阻止第二条请求继续对外发出 TLB/DCache 访问。但当前实现仍会在该窗口内让第二条请求直接占用 `io.tlb.req` / `io.dcache.req`，形成“第一条尚未完成，第二条已经对外出站”的协议撕裂。

**影响范围：**
- FG-SCALAR-PIPELINE/FC-SCALAR-TLB-DCACHE-REQ/CK-NO-ISSUE-WHEN-S1-BLOCKED （BG-S0-REQ-FIRES-WHEN-S1-BLOCKED-99）

**根本原因：**  
stage0 的 `s0_fire` 明确要求 `s0_can_go=s1_ready`，但 `io.tlb.req.valid` 与 `io.dcache.req.valid` 并没有绑定到 `s0_fire`，而是分别由 `s0_tlb_valid` / `s0_valid` 直接驱动。这样当下游阻塞导致上游 `ready=0` 时，stage0 仍可能把尚未被流水线正式接收的新请求发给 TLB/DCache。

**具体代码缺陷：**
```scala
// bosc_LoadUnit_RTL/LoadUnit.scala 第231-232,362-369,383-406,846-848,912-916行
231:   val s0_can_go        = s1_ready
232:   val s0_fire          = s0_valid && s0_can_go
362:   s0_tlb_valid := (
363:     s0_src_valid_vec(mab_idx) ||
364:     s0_src_valid_vec(super_rep_idx) ||
365:     s0_src_valid_vec(lsq_rep_idx) ||
366:     s0_src_valid_vec(vec_iss_idx) ||
367:     s0_src_valid_vec(int_iss_idx) ||
368:     s0_src_valid_vec(l2l_fwd_idx)
369:   ) && io.dcache.req.ready
383:   io.tlb.req.valid                   := s0_tlb_valid
406:   io.dcache.req.valid             := s0_valid && !s0_sel_src.prf_i && !s0_nc_with_data
846:   io.vecldin.ready := s0_can_go && io.dcache.req.ready && s0_src_ready_vec(vec_iss_idx)
847:   io.ldin.ready := s0_can_go && io.dcache.req.ready && s0_src_ready_vec(int_iss_idx)
848:   io.misalign_ldin.ready := s0_can_go && io.dcache.req.ready && s0_src_ready_vec(mab_idx)
912:   s1_ready := !s1_valid || s1_kill || s2_ready
913:   when (s0_fire) { s1_valid := true.B }
916:   s1_in   := RegEnable(s0_out, s0_fire)
```

从上述实现可见：`ready` 路径用 `s0_can_go` 保护了“流水线是否真正接收请求”，但 `tlb.req.valid` / `dcache.req.valid` 没有使用同样的保护，因此会出现“流水线认为第二条请求还没进来，外设却已经看到了请求”的错误。

**修复建议：**
```scala
// 方案一：直接把对外请求 valid 绑定到 s0_fire
io.tlb.req.valid := s0_fire && s0_selected_need_tlb
io.dcache.req.valid := s0_fire && !s0_sel_src.prf_i && !s0_nc_with_data

// 方案二：至少与 s0_can_go 显式相与，避免未握手请求提前出站
io.tlb.req.valid := s0_tlb_valid && s0_can_go
io.dcache.req.valid := s0_valid && s0_can_go && !s0_sel_src.prf_i && !s0_nc_with_data
```

同时建议统一检查所有依赖 `s0_valid` / `s0_src_valid_vec(*)` 的旁路控制输出，确保它们不会在 `s0_fire=0` 时对外暴露“请求已经发出”的假象。

**验证方法：**  
修复后重新运行 `unity_test/tests/test_bosc_LoadUnit_scalar_pipeline.py::test_loadunit_scalar_no_issue_when_stage1_blocked`。期望结果为：当第一条请求的 `ldout` 因 `ready=0` 而占用写回口时，第二条请求的 `io_tlb_req_valid` / `io_dcache_req_valid` 全部保持 0，直到 backpressure 解除。

### 7. stage3 标量写回没有真正实现可停顿的 valid 保持

**缺陷描述：**  
普通标量 load 在 `io_ldout_ready=0` 的场景下，首个到达 stage3 的写回结果只会对外输出 1 拍 `io_ldout_valid`，下一拍即使 `ready` 仍为 0 也会被撤掉。这违反了 Decoupled 接口“valid 必须持续保持直到 ready 握手”的基本语义。

**影响范围：**
- FG-SCALAR-PIPELINE/FC-SCALAR-WRITEBACK-BACKPRESSURE/CK-HOLD-UNDER-BACKPRESSURE （BG-LDOUT-BACKPRESSURE-NOT-HELD-98）
- FG-SCALAR-PIPELINE/FC-SCALAR-WRITEBACK-BACKPRESSURE/CK-RELEASE-ON-READY （BG-LDOUT-READY-RELEASE-BROKEN-98）

**根本原因：**  
stage1 和 stage2 都使用 `RegInit(false.B)` + `fire/kill` 风格的可停顿 valid 寄存器；但 stage3 的 `s3_valid` 却是 `GatedValidRegNext(s2_valid && ...)` 的单拍导出信号，不受 `s3_ready` 反压控制。当某条请求第一次进入 stage3 时，如果下一拍 `s2_valid` 已经清零，`s3_valid` 就会跟着消失，即使 `io.ldout.ready` 仍为 0。

**具体代码缺陷：**
```scala
// bosc_LoadUnit_RTL/LoadUnit.scala 第1161-1166,1187-1191,1533,1572,1785-1788行
1161:   val s2_valid  = RegInit(false.B)
1165:   val s2_can_go = s3_ready
1166:   val s2_fire   = s2_valid && !s2_kill && s2_can_go
1187:   s2_ready := !s2_valid || s2_kill || s3_ready
1188:   when (s1_fire) { s2_valid := true.B }
1189:   .elsewhen (s2_fire) { s2_valid := false.B }
1191:   s2_in := RegEnable(s1_out, s1_fire)

1533:   val s3_valid        = GatedValidRegNext(s2_valid && !s2_out.isHWPrefetch && !s2_out.uop.robIdx.needFlush(io.redirect))
1572:   s3_ready := !s3_valid || s3_kill || io.ldout.ready
1785:   val s3_ldout_valid  = s3_mmio_req.valid ||
1786:                         s3_out.valid && RegNext(!s2_out.isvec && !s2_out.isFrmMisAlignBuf)
1787:   io.ldout.valid       := s3_ldout_valid
1788:   io.ldout.bits        := s3_ld_wb_meta
```

这里的关键问题是：`s3_ready` 虽然定义了反压条件，但 `s3_valid` 本身不是一个可停顿状态寄存器，因此首个 `ldout` 脉冲不会被保留。`CK-RELEASE-ON-READY` 之所以也失败，是因为“待释放的挂起写回”在 ready 恢复前就已经丢失了。

**修复建议：**
```scala
// 参照 s1/s2 的实现方式，把 s3_valid 改成真正的停顿寄存器
val s3_valid = RegInit(false.B)
when (s2_fire) {
  s3_valid := true.B
}.elsewhen (s3_valid && (s3_kill || io.ldout.ready)) {
  s3_valid := false.B
}

when (s2_fire) {
  s3_in := s2_out
}
```

如果还需要同时支持 `vecldout` / `misalign_ldout` / `mmio` 等多种写回出口，建议统一抽象 stage3 的“结果持有寄存器”和“出口选择寄存器”，避免继续把 `ldout.valid` 建立在 `RegNext(s2_out...)` 这种只适用于无背压路径的单拍脉冲上。

**验证方法：**  
修复后重新运行：
- `unity_test/tests/test_bosc_LoadUnit_scalar_pipeline.py::test_loadunit_scalar_writeback_holds_under_backpressure`
- `unity_test/tests/test_bosc_LoadUnit_scalar_pipeline.py::test_loadunit_scalar_writeback_releases_on_ready`

期望结果为：`ready=0` 时 `ldout.valid` 与相应 payload 持续保持不变；`ready` 恢复为 1 后，该写回仅完成一次，不重复、不丢失。

### 8. 高置信度 prefetch 与 vector 竞争时，未被选中的 vector 仍错误拉起 TLB 请求

**缺陷描述：**  
按照 README，硬件 prefetch 不需要重新走普通 TLB 翻译；当高置信度 prefetch 与 vector 同拍竞争时，stage0 应选择 prefetch 并阻塞 vector。但当前 RTL 在 DCache 端确实选中了 prefetch，却同时因为 vector 的原始 `valid` 仍为 1 而把 `io_tlb_req_valid` 一并拉高，形成“一条请求占 DCache，另一条请求占 TLB”的双发射撕裂。

**影响范围：**
- FG-ARBITRATION/FC-PREFETCH-VECTOR-SCALAR-PRIORITY/CK-HIGHCONF-OVER-VECTOR （BG-HIGHCONF-PREFETCH-SPURIOUS-TLB-REQ-97）

**根本原因：**  
`s0_tlb_valid` 是用 `s0_src_valid_vec(*)` 直接求或得到的，而不是根据“最终选中的源”生成。于是只要 vector/scalar/replay 等普通翻译源在同拍保持 `valid=1`，即便仲裁实际已经选中了高置信度 prefetch，`io.tlb.req.valid` 仍会被这些未选中的低优先级源错误拉高。

**具体代码缺陷：**
```scala
// bosc_LoadUnit_RTL/LoadUnit.scala 第314-320,334-339,362-400行
314:   val s0_src_valid_vec = WireInit(VecInit(Seq(
315:     io.misalign_ldin.valid,
316:     io.replay.valid && io.replay.bits.forward_tlDchannel,
317:     io.fast_rep_in.valid,
318:     io.replay.valid && !io.replay.bits.forward_tlDchannel && !s0_rep_stall,
319:     io.prefetch_req.valid && io.prefetch_req.bits.confidence > 0.U,
320:     io.vecldin.valid,
...
334:   val s0_src_select_vec = WireInit(VecInit((0 until SRC_NUM).map{i => s0_src_valid_vec(i) && s0_src_ready_vec(i)}))
337:   val s0_tlb_no_query = s0_hw_prf_select || s0_sel_src.prf_i ||
338:     s0_src_select_vec(fast_rep_idx) || s0_src_select_vec(mmio_idx) ||
339:     s0_src_select_vec(nc_idx)
362:   s0_tlb_valid := (
363:     s0_src_valid_vec(mab_idx) ||
364:     s0_src_valid_vec(super_rep_idx) ||
365:     s0_src_valid_vec(lsq_rep_idx) ||
366:     s0_src_valid_vec(vec_iss_idx) ||   // BUG: 未被选中的 vector.valid 也会拉高 tlb.req.valid
367:     s0_src_valid_vec(int_iss_idx) ||
368:     s0_src_valid_vec(l2l_fwd_idx)
369:   ) && io.dcache.req.ready
383:   io.tlb.req.valid                   := s0_tlb_valid
395:   io.tlb.req.bits.kill               := s0_kill || s0_tlb_no_query
400:   io.tlb.req.bits.no_translate       := s0_tlb_no_query
```

这段实现说明：虽然 `s0_tlb_no_query` 已经知道“当前被选中的是 prefetch，不应翻译”，但 `s0_tlb_valid` 仍然会被低优先级 vector 的原始 `valid` 拉高，最终只能靠 `kill/no_translate` 去补救。对黑盒接口而言，这已经是一个可观测的协议违例。

**修复建议：**
```scala
// 只允许“最终被选中且确实需要翻译”的源去驱动 tlb.req.valid
val s0_selected_need_tlb =
  s0_src_select_vec(mab_idx) ||
  s0_src_select_vec(super_rep_idx) ||
  s0_src_select_vec(lsq_rep_idx) ||
  s0_src_select_vec(vec_iss_idx) ||
  s0_src_select_vec(int_iss_idx) ||
  s0_src_select_vec(l2l_fwd_idx)

io.tlb.req.valid := s0_selected_need_tlb && s0_can_go && io.dcache.req.ready
```

如果设计需要保留 `kill/no_translate` 作为保护，也应保证在 `valid` 层面首先由“被选中的源”决定是否对外可见，避免未选中的低优先级请求泄漏到 TLB 口。

**验证方法：**  
修复后重新运行 `unity_test/tests/test_bosc_LoadUnit_stage0_arbitration.py::test_stage0_high_confidence_prefetch_priority_over_vector`。期望结果为：`vector.ready=0`、`dcache.req.valid=1`、`dcache.pf_source=5` 的同时，`io_tlb_req_valid=0`；随后当 prefetch 请求撤销后，vector 请求再恢复可发射。

### 9. uncache 请求的 stage0 优先级被错误降低到普通 replay/vector/scalar 之后

**缺陷描述：**  
README 规定 uncache 请求优先级应高于普通 replay、向量和标量请求。但当前实现中，只要这些低规格源与 `io.lsq.uncache` 同拍有效，stage0 就会先接收低规格请求，导致 `io_lsq_uncache_ready=0`，uncache/MMIO 路径的早唤醒与专用写回无法按规格启动。

**影响范围：**
- FG-ARBITRATION/FC-UNCACHE-NC-PRIORITY/CK-UNCACHE-OVER-REPLAY-VECTOR-SCALAR （BG-UNCACHE-PRIORITY-ORDER-98）

**根本原因：**  
stage0 的仲裁次序完全由 `s0_src_valid_vec` 的排列顺序决定，而当前实现把 `io.lsq.uncache.valid` 放在普通 replay、高置信预取、vector、scalar 之后。这样一来，只要这些源同时有效，`s0_src_ready_vec(mmio_idx)` 就必然为 0，uncache 路径永远拿不到同拍优先权。

**具体代码缺陷：**
```scala
// bosc_LoadUnit_RTL/LoadUnit.scala 第314-325,330-335,834行
314:   val s0_src_valid_vec = WireInit(VecInit(Seq(
315:     io.misalign_ldin.valid,
316:     io.replay.valid && io.replay.bits.forward_tlDchannel,
317:     io.fast_rep_in.valid,
318:     io.replay.valid && !io.replay.bits.forward_tlDchannel && !s0_rep_stall,
319:     io.prefetch_req.valid && io.prefetch_req.bits.confidence > 0.U,
320:     io.vecldin.valid,
321:     io.ldin.valid,
322:     io.lsq.uncache.valid, // BUG: 放在 replay/vector/scalar 之后
323:     io.lsq.nc_ldin.valid,
324:     io.l2l_fwd_in.valid,
325:     io.prefetch_req.valid && io.prefetch_req.bits.confidence === 0.U,
331:     s0_src_ready_vec(i) := !s0_src_valid_vec.take(i).reduce(_ || _)
334:   val s0_src_select_vec = WireInit(VecInit((0 until SRC_NUM).map{i => s0_src_valid_vec(i) && s0_src_ready_vec(i)}))
834:  io.lsq.uncache.ready := s0_mmio_fire
```

上述代码意味着：只要 `ordinary replay / vector / scalar` 任一源在 uncache 之前为真，`uncache.ready` 就不可能拉高。这与 README 的优先级表直接冲突。

**修复建议：**
```scala
// 按规格重排 stage0 的源优先级：uncache 应位于普通 replay/vector/scalar 之前
val s0_src_valid_vec = WireInit(VecInit(Seq(
  io.misalign_ldin.valid,
  io.replay.valid && io.replay.bits.forward_tlDchannel,
  io.fast_rep_in.valid,
  io.lsq.uncache.valid,
  io.lsq.nc_ldin.valid,
  io.replay.valid && !io.replay.bits.forward_tlDchannel && !s0_rep_stall,
  io.prefetch_req.valid && io.prefetch_req.bits.confidence > 0.U,
  io.vecldin.valid,
  io.ldin.valid,
  io.l2l_fwd_in.valid,
  io.prefetch_req.valid && io.prefetch_req.bits.confidence === 0.U,
)))
```

如果设计者不希望用数组位置表达优先级，建议改成显式的 `when/elsewhen` 或优先级仲裁器，避免后续再次因索引定义与规格文档偏离而引入同类错误。

**验证方法：**  
修复后重新运行 `unity_test/tests/test_bosc_LoadUnit_stage0_arbitration.py::test_stage0_uncache_priority_over_replay_vector_and_scalar`。期望结果为：竞争拍 `io_lsq_uncache_ready=1`，而 replay/vector/scalar 保持未消费；同时 `io_wakeup_valid=1` 继续符合 uncache/MMIO 早唤醒语义。

### 10. NC 请求的 stage0 优先级被错误降低到普通 replay / vector / scalar 之后

**缺陷描述：**  
README 规定 NC 请求应高于普通 replay、向量和标量请求；但当前 RTL 中 `io.lsq.nc_ldin.valid` 被排在这些源之后。结果是 NC 与 replay/vector/scalar 同拍竞争时，NC 路径拿不到优先权，破坏 NC 第二次上流水的 bypass-TLB、前递、RAR/RAW 检查与写回时机。

**影响范围：**
- FG-ARBITRATION/FC-UNCACHE-NC-PRIORITY/CK-NC-OVER-ORDINARY-REPLAY （BG-NC-PRIORITY-ORDER-VS-ORDINARY-REPLAY-97）
- FG-ARBITRATION/FC-UNCACHE-NC-PRIORITY/CK-NC-OVER-VECTOR-SCALAR （BG-NC-PRIORITY-ORDER-VS-VECTOR-SCALAR-97）

**根本原因：**  
与上一个缺陷相同，NC 的实际优先级由 `s0_src_valid_vec` 中的位置隐式决定。当前 `io.lsq.nc_ldin.valid` 排在普通 replay/vector/scalar 之后，因此这些低规格源会先占用 `s0_src_ready_vec`，使 `io_lsq_nc_ldin_ready` 被压成 0。

**具体代码缺陷：**
```scala
// bosc_LoadUnit_RTL/LoadUnit.scala 第318-325,331-335,835行
318:     io.replay.valid && !io.replay.bits.forward_tlDchannel && !s0_rep_stall,
319:     io.prefetch_req.valid && io.prefetch_req.bits.confidence > 0.U,
320:     io.vecldin.valid,
321:     io.ldin.valid,
322:     io.lsq.uncache.valid,
323:     io.lsq.nc_ldin.valid, // BUG: NC 实际晚于 replay/vector/scalar
324:     io.l2l_fwd_in.valid,
325:     io.prefetch_req.valid && io.prefetch_req.bits.confidence === 0.U,
331:     s0_src_ready_vec(i) := !s0_src_valid_vec.take(i).reduce(_ || _)
334:   val s0_src_select_vec = WireInit(VecInit((0 until SRC_NUM).map{i => s0_src_valid_vec(i) && s0_src_ready_vec(i)}))
835:  io.lsq.nc_ldin.ready := s0_src_ready_vec(nc_idx) && s0_can_go
```

`io.lsq.nc_ldin.ready` 直接依赖 `s0_src_ready_vec(nc_idx)`；由于 `nc_idx` 前面已经包含普通 replay、vector 和 scalar，NC 竞争这些源时天然处于劣势。这正是 `CK-NC-OVER-ORDINARY-REPLAY` 与 `CK-NC-OVER-VECTOR-SCALAR` 同时失败的共同根因。

**修复建议：**
```scala
// 将 NC 移到 uncache 之后、普通 replay / prefetch / vector / scalar 之前
val s0_src_valid_vec = WireInit(VecInit(Seq(
  io.misalign_ldin.valid,
  io.replay.valid && io.replay.bits.forward_tlDchannel,
  io.fast_rep_in.valid,
  io.lsq.uncache.valid,
  io.lsq.nc_ldin.valid, // FIX: 提前到普通 replay / vector / scalar 之前
  io.replay.valid && !io.replay.bits.forward_tlDchannel && !s0_rep_stall,
  io.prefetch_req.valid && io.prefetch_req.bits.confidence > 0.U,
  io.vecldin.valid,
  io.ldin.valid,
  io.l2l_fwd_in.valid,
  io.prefetch_req.valid && io.prefetch_req.bits.confidence === 0.U,
)))
```

同时建议补充一个断言：当 `io.lsq.nc_ldin.valid=1` 且更高优先级源全部无效时，`io_lsq_nc_ldin_ready` 必须在同拍拉高。这样可以把优先级表直接固化为可检查的设计约束。

**验证方法：**  
修复后重新运行：
- `unity_test/tests/test_bosc_LoadUnit_stage0_arbitration.py::test_stage0_nc_priority_over_ordinary_replay`
- `unity_test/tests/test_bosc_LoadUnit_stage0_arbitration.py::test_stage0_nc_priority_over_vector_and_scalar`

期望结果为：竞争拍 `io_lsq_nc_ldin_ready=1`，普通 replay/vector/scalar 保持未消费；同时 `io_tlb_req_valid=0` 的 NC bypass-TLB 语义在后续路径中继续成立。

### 11. 向量写回口未导出 `ready`，导致 `vecldout` 背压协议无法黑盒验证且内部实现也未消费该信号

**缺陷描述：**  
README 与 `LoadUnit.scala` 都将 `vecldout` 视为向量写回出口；源码里该接口定义为 `Decoupled(new VecPipelineFeedbackIO(...))`，按协议应具备 `valid/ready/bits` 三元握手。但当前交付的顶层 wrapper、`signals.json` 以及 Python 黑盒接口都只暴露了 `io_vecldout_valid` 与 `io_vecldout_bits_*`，完全没有 `io_vecldout_ready`。因此黑盒测试无法对向量写回通道施加 backpressure，`CK-VECLDOUT-BACKPRESSURE` 在接口存在性检查阶段即稳定失败；同时，内部 stage3 的推进条件也只依赖 `io.ldout.ready`，没有消费任何 `vecldout.ready`，说明即使补出端口，当前实现仍存在 ready/valid 协议风险。

**影响范围：**
- FG-VECTOR-LOAD/FC-VECTOR-WRITEBACK/CK-VECLDOUT-BACKPRESSURE （BG-VECLDOUT-READY-PORT-MISSING-99）
- 与静态分析中的 BG-STATIC-005-VECLDOUT-READY-IGNORED 直接相关，属于“接口导出缺失 + 内部 ready 未接入”的组合缺陷

**根本原因：**  
问题分成两个层面：
1. 设计源码层面，`io.vecldout` 在 `LoadUnit.scala` 中明确定义为 `Decoupled`，理论上必须有 `ready`。
2. 交付接口层面，生成后的 `bosc_LoadUnit_top.v` 与 `signals.json` 没有任何 `io_vecldout_ready` 端口，导致 Python DUT/env 完全无法从黑盒端驱动该握手。
3. 内部实现层面，stage3 的 `s3_ready` 只看 `io.ldout.ready`，并未把 `vecldout.ready` 纳入阻塞条件，说明即使接口补齐，也还需要修正内部停顿逻辑。

**具体代码缺陷：**
```scala
// bosc_LoadUnit_RTL/LoadUnit.scala 第131,1572,1818-1855行
131:    val vecldout = Decoupled(new VecPipelineFeedbackIO(isVStore = false))
1572:   s3_ready := !s3_valid || s3_kill || io.ldout.ready
1818:   io.vecldout.bits.alignedType := s3_vec_alignedType
1855:   io.vecldout.valid := s3_out.valid && !s3_out.bits.uop.robIdx.needFlush(io.redirect) && s3_vecout.isvec && !s3_mis_align && !s3_frm_mabuf

// bosc_LoadUnit/bosc_LoadUnit_top.v 第264-284行：只有 valid 和 bits，没有 ready
264:   wire  io_vecldout_valid;
265:   wire [3:0] io_vecldout_bits_mBIndex;
...
284:   wire [127:0] io_vecldout_bits_vecdata;

// bosc_LoadUnit/signals.json 第13997-14127行：vecldout 只导出 bits/valid，缺少 ready
13997:        "vecldout": {
13998:            "bits": {
...
14122:            "valid": {
14125:                "Pin": "output",
14127:            }
```

从这些源码可以直接看出：
1. RTL 原始定义要求 `vecldout` 是 Decoupled；
2. 交付顶层和信号树把 `ready` 丢掉了；
3. stage3 的推进条件仍然没有引用 `vecldout.ready`。

**触发 Bug 的测试用例：**
- `unity_test/tests/test_bosc_LoadUnit_vector_load.py::test_loadunit_vector_writeback_holds_under_backpressure` 复位后直接检查 `env.vector_resp` 是否具备 `ready` 属性，稳定失败；失败信息明确表明当前黑盒接口无法对向量写回口施加背压

**修复建议：**
```scala
// 第一层：修复交付接口，确保 vecldout.ready 被完整导出
// 顶层 wrapper / signals.json 应与 Decoupled 语义一致，补出：io_vecldout_ready

// 第二层：修复内部 stage3 ready 选择
val s3_vec_wb_ready = Mux(s3_vecout.isvec, io.vecldout.ready, io.ldout.ready)
s3_ready := !s3_valid || s3_kill || s3_vec_wb_ready
```

如果当前配置确实希望向量写回口“永远 ready”，也必须在规格与交付接口中显式说明这一点，并删除 `CK-VECLDOUT-BACKPRESSURE` / `BG-STATIC-005` 相关要求；否则就应按标准 Decoupled 接口完整交付并实现背压保持。

**验证方法：**  
修复后重新运行 `unity_test/tests/test_bosc_LoadUnit_vector_load.py::test_loadunit_vector_writeback_holds_under_backpressure`。期望结果为：
1. 黑盒接口可访问 `env.vector_resp.ready`；
2. 在 `ready=0` 的窗口，`vecldout.valid` 与对应 payload 持续保持不变；
3. `ready` 恢复为 1 后，同一条向量写回仅释放一次，不丢失、不重复；
4. `test_loadunit_vector_path_has_no_slow_feedback` 与 `test_loadunit_vector_path_still_writes_back_without_slow_feedback` 继续保持 Pass。
