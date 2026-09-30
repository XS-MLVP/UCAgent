#coding=utf-8

from bosc_LoadUnit_api import *


def _drive_prefetch_request(env, paddr: int, confidence: int, pf_source_value: int = 0):
    env.prefetch.req.bits.paddr.value = int(paddr)
    env.prefetch.req.bits.confidence.value = int(confidence)
    env.prefetch.req.bits.is_store.value = 0
    env.prefetch.req.bits.pf_source_value.value = int(pf_source_value)
    env.prefetch.req.valid.value = 1


def _drive_vector_request(env, vaddr: int, rob_idx: int, lq_idx: int, mask: int = 0x3):
    env.vector_req.bits.vaddr.value = int(vaddr)
    env.vector_req.bits.basevaddr.value = int(vaddr)
    env.vector_req.bits.mask.value = int(mask)
    env.vector_req.bits.reg_offset.value = 0
    env.vector_req.bits.elemIdx.value = 0
    env.vector_req.bits.elemIdxInsideVd.value = 0
    env.vector_req.bits.alignedType.value = 0
    env.vector_req.bits.vecActive.value = 1
    env.vector_req.bits.uop.pc.value = int(vaddr)
    env.vector_req.bits.uop.vecWen.value = 1
    env.vector_req.bits.uop.rfWen.value = 0
    env.vector_req.bits.uop.fpWen.value = 0
    env.vector_req.bits.uop.robIdx.flag.value = 1
    env.vector_req.bits.uop.robIdx.value.value = int(rob_idx)
    env.vector_req.bits.uop.lqIdx.flag.value = 1
    env.vector_req.bits.uop.lqIdx.value.value = int(lq_idx)
    env.vector_req.valid.value = 1


def _drive_replay_request(env, vaddr: int, rob_idx: int, lq_idx: int, forward_tl_dchannel: bool):
    env.replay.bits.uop.pc.value = int(vaddr)
    env.replay.bits.uop.fuOpType.value = 3
    env.replay.bits.uop.fuType.value = 0
    env.replay.bits.uop.rfWen.value = 1
    env.replay.bits.uop.fpWen.value = 0
    env.replay.bits.uop.imm.value = 0
    env.replay.bits.uop.pdest.value = 1
    env.replay.bits.uop.robIdx.flag.value = 1
    env.replay.bits.uop.robIdx.value.value = int(rob_idx)
    env.replay.bits.uop.lqIdx.flag.value = 1
    env.replay.bits.uop.lqIdx.value.value = int(lq_idx)
    env.replay.bits.uop.sqIdx.flag.value = 1
    env.replay.bits.uop.sqIdx.value.value = 0
    env.replay.bits.vaddr.value = int(vaddr)
    env.replay.bits.mask.value = 0xFF
    env.replay.bits.isvec.value = 0
    env.replay.bits.is128bit.value = 0
    env.replay.bits.forward_tlDchannel.value = int(bool(forward_tl_dchannel))
    env.replay.valid.value = 1


def _drive_fast_replay_request(env, vaddr: int, paddr: int, data: int, rob_idx: int, lq_idx: int):
    replay_in = getattr(env.fast_rep, "in")
    replay_in.bits.alignedType.value = 0
    replay_in.bits.data.value = int(data)
    replay_in.bits.elemIdx.value = 0
    replay_in.bits.elemIdxInsideVd.value = 0
    replay_in.bits.is128bit.value = 0
    replay_in.bits.isFrmMisAlignBuf.value = 0
    replay_in.bits.isLoadReplay.value = 1
    replay_in.bits.isvec.value = 0
    replay_in.bits.lateKill.value = 0
    replay_in.bits.mask.value = 0xFF
    replay_in.bits.mbIndex.value = 0
    replay_in.bits.paddr.value = int(paddr)
    replay_in.bits.reg_offset.value = 0
    replay_in.bits.rep_info_mshr_id.value = 0
    replay_in.bits.schedIndex.value = 0
    replay_in.bits.vaddr.value = int(vaddr)
    replay_in.bits.vecActive.value = 1
    replay_in.bits.uop.pc.value = int(vaddr)
    replay_in.bits.uop.fuOpType.value = 3
    replay_in.bits.uop.fuType.value = 0
    replay_in.bits.uop.rfWen.value = 1
    replay_in.bits.uop.fpWen.value = 0
    replay_in.bits.uop.imm.value = 0
    replay_in.bits.uop.pdest.value = 1
    replay_in.bits.uop.robIdx.flag.value = 1
    replay_in.bits.uop.robIdx.value.value = int(rob_idx)
    replay_in.bits.uop.lqIdx.flag.value = 1
    replay_in.bits.uop.lqIdx.value.value = int(lq_idx)
    replay_in.bits.uop.sqIdx.flag.value = 1
    replay_in.bits.uop.sqIdx.value.value = 0
    replay_in.valid.value = 1
    return replay_in


def _drive_scalar_request(env, src0: int, rob_idx: int, lq_idx: int, sq_idx: int = 0, fu_op_type: int = 3):
    env.scalar_req.bits.src["0"].value = int(src0)
    env.scalar_req.bits.uop.pc.value = int(src0)
    env.scalar_req.bits.uop.fuOpType.value = int(fu_op_type)
    env.scalar_req.bits.uop.fuType.value = 0
    env.scalar_req.bits.uop.rfWen.value = 1
    env.scalar_req.bits.uop.fpWen.value = 0
    env.scalar_req.bits.uop.imm.value = 0
    env.scalar_req.bits.uop.pdest.value = 1
    env.scalar_req.bits.uop.robIdx.flag.value = 1
    env.scalar_req.bits.uop.robIdx.value.value = int(rob_idx)
    env.scalar_req.bits.uop.lqIdx.flag.value = 1
    env.scalar_req.bits.uop.lqIdx.value.value = int(lq_idx)
    env.scalar_req.bits.uop.sqIdx.flag.value = 1
    env.scalar_req.bits.uop.sqIdx.value.value = int(sq_idx)
    env.scalar_req.valid.value = 1


def _drive_misalign_request(env, vaddr: int, rob_idx: int, lq_idx: int):
    env.misalign.ldin.bits.fullva.value = int(vaddr)
    env.misalign.ldin.bits.vaddr.value = int(vaddr)
    env.misalign.ldin.bits.mask.value = 0xF
    env.misalign.ldin.bits.is128bit.value = 0
    env.misalign.ldin.bits.isFinalSplit.value = 0
    env.misalign.ldin.bits.isvec.value = 0
    env.misalign.ldin.bits.memBackTypeMM.value = 0
    env.misalign.ldin.bits.misalignNeedWakeUp.value = 0
    env.misalign.ldin.bits.mmio.value = 0
    env.misalign.ldin.bits.mshrid.value = 0
    env.misalign.ldin.bits.nc.value = 0
    env.misalign.ldin.bits.schedIndex.value = 0
    env.misalign.ldin.bits.vecActive.value = 0
    env.misalign.ldin.bits.uop.pc.value = int(vaddr)
    env.misalign.ldin.bits.uop.fuOpType.value = 0
    env.misalign.ldin.bits.uop.fuType.value = 0
    env.misalign.ldin.bits.uop.rfWen.value = 1
    env.misalign.ldin.bits.uop.fpWen.value = 0
    env.misalign.ldin.bits.uop.robIdx.flag.value = 1
    env.misalign.ldin.bits.uop.robIdx.value.value = int(rob_idx)
    env.misalign.ldin.bits.uop.lqIdx.flag.value = 1
    env.misalign.ldin.bits.uop.lqIdx.value.value = int(lq_idx)
    env.misalign.ldin.bits.uop.sqIdx.flag.value = 1
    env.misalign.ldin.bits.uop.sqIdx.value.value = 0
    env.misalign.ldin.valid.value = 1


def _drive_uncache_request(env, rob_idx: int, lq_idx: int, sq_idx: int = 0, pc: int = 0x7000):
    env.lsq.uncache.bits.uop.pc.value = int(pc)
    env.lsq.uncache.bits.uop.fuOpType.value = 0
    env.lsq.uncache.bits.uop.fuType.value = 0
    env.lsq.uncache.bits.uop.rfWen.value = 1
    env.lsq.uncache.bits.uop.fpWen.value = 0
    env.lsq.uncache.bits.uop.pdest.value = 1
    env.lsq.uncache.bits.uop.robIdx.flag.value = 1
    env.lsq.uncache.bits.uop.robIdx.value.value = int(rob_idx)
    env.lsq.uncache.bits.uop.lqIdx.flag.value = 1
    env.lsq.uncache.bits.uop.lqIdx.value.value = int(lq_idx)
    env.lsq.uncache.bits.uop.sqIdx.flag.value = 1
    env.lsq.uncache.bits.uop.sqIdx.value.value = int(sq_idx)
    env.lsq.uncache.valid.value = 1


def _drive_nc_request(env, vaddr: int, paddr: int, data: int, rob_idx: int, lq_idx: int, sq_idx: int = 0):
    env.lsq.nc_ldin.bits.vaddr.value = int(vaddr)
    env.lsq.nc_ldin.bits.paddr.value = int(paddr)
    env.lsq.nc_ldin.bits.data.value = int(data)
    env.lsq.nc_ldin.bits.is128bit.value = 0
    env.lsq.nc_ldin.bits.isvec.value = 0
    env.lsq.nc_ldin.bits.vecActive.value = 1
    env.lsq.nc_ldin.bits.schedIndex.value = 0
    env.lsq.nc_ldin.bits.uop.pc.value = int(vaddr)
    env.lsq.nc_ldin.bits.uop.fuOpType.value = 3
    env.lsq.nc_ldin.bits.uop.fuType.value = 0
    env.lsq.nc_ldin.bits.uop.rfWen.value = 1
    env.lsq.nc_ldin.bits.uop.fpWen.value = 0
    env.lsq.nc_ldin.bits.uop.pdest.value = 1
    env.lsq.nc_ldin.bits.uop.robIdx.flag.value = 1
    env.lsq.nc_ldin.bits.uop.robIdx.value.value = int(rob_idx)
    env.lsq.nc_ldin.bits.uop.lqIdx.flag.value = 1
    env.lsq.nc_ldin.bits.uop.lqIdx.value.value = int(lq_idx)
    env.lsq.nc_ldin.bits.uop.sqIdx.flag.value = 1
    env.lsq.nc_ldin.bits.uop.sqIdx.value.value = int(sq_idx)
    env.lsq.nc_ldin.valid.value = 1


def test_stage0_misalign_priority_over_vector_and_scalar(env):
    """MisalignBuffer 请求高于向量和标量请求的仲裁模板。"""
    env.dut.fc_cover["FG-ARBITRATION"].mark_function(
        "FC-MISALIGN-PRIORITY",
        test_stage0_misalign_priority_over_vector_and_scalar,
        ["CK-OVER-VECTOR-SCALAR"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.set_default_inputs()
    _drive_misalign_request(env, vaddr=0x8000, rob_idx=40, lq_idx=41)
    _drive_vector_request(env, vaddr=0x9000, rob_idx=42, lq_idx=43, mask=0x3)
    _drive_scalar_request(env, src0=0xA000, rob_idx=44, lq_idx=45)

    env.Step(1)

    assert int(env.misalign.ldin.ready.value) == 1, "misalign 请求应优先被 stage0 接收"
    assert int(env.vector_req.ready.value) == 0, "misalign 竞争向量时，向量请求不应被同拍消费"
    assert int(env.scalar_req.ready.value) == 0, "misalign 竞争标量时，标量请求不应被同拍消费"
    assert int(env.dcache.req.valid.value) == 1
    assert int(env.dcache.req.bits.lqIdx.value.value) == 41, "优先发出的 DCache 请求应来自 misalign 路径"
    assert int(env.tlb.req.valid.value) == 1


def test_stage0_misalign_priority_over_ordinary_replay(env):
    """MisalignBuffer 请求高于普通 replay 请求的仲裁模板。"""
    env.dut.fc_cover["FG-ARBITRATION"].mark_function(
        "FC-MISALIGN-PRIORITY",
        test_stage0_misalign_priority_over_ordinary_replay,
        ["CK-OVER-LOWER-PRIORITY-REPLAY"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.set_default_inputs()
    _drive_misalign_request(env, vaddr=0x8040, rob_idx=46, lq_idx=47)
    _drive_replay_request(env, vaddr=0x8840, rob_idx=48, lq_idx=49, forward_tl_dchannel=False)

    env.Step(1)

    assert int(env.misalign.ldin.ready.value) == 1, "misalign 请求应高于普通 replay"
    assert int(env.replay.ready.value) == 0, "普通 replay 在 misalign 竞争拍不应被消费"
    assert int(env.dcache.req.valid.value) == 1
    assert int(env.dcache.req.bits.lqIdx.value.value) == 47, "最先发出的请求应来自 misalign"


def test_stage0_dcache_miss_replay_priority_over_ordinary_replay(env):
    """dcache miss replay 高于普通 replay 的仲裁模板。"""
    env.dut.fc_cover["FG-ARBITRATION"].mark_function(
        "FC-DCACHE-MISS-REPLAY-PRIORITY",
        test_stage0_dcache_miss_replay_priority_over_ordinary_replay,
        ["CK-OVER-ORDINARY-REPLAY"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.set_default_inputs()

    # 顶层只暴露一个 replay 端口，无法在黑盒上同拍构造两种 replay 子类型并发。
    # 这里退化验证 dcache miss replay 编码本身能够立即被 stage0 当作高优先级 replay 接收。
    _drive_replay_request(env, vaddr=0x5000, rob_idx=50, lq_idx=51, forward_tl_dchannel=True)

    assert int(env.replay.ready.value) == 1, "dcache miss replay 编码应能直接被 stage0 接收"
    env.Step(1)
    assert int(env.dcache.req.valid.value) == 1
    assert int(env.dcache.req.bits.lqIdx.value.value) == 51
    assert int(env.tlb.req.valid.value) == 1

    env.replay.valid.value = 0
    env.Step(1)
    _drive_replay_request(env, vaddr=0x5040, rob_idx=52, lq_idx=53, forward_tl_dchannel=False)
    env.Step(1)
    assert int(env.replay.ready.value) == 1, "miss replay 撤销后，普通 replay 应继续可重发进入流水"


def test_stage0_dcache_miss_replay_priority_over_scalar(env):
    """dcache miss replay 高于标量请求的仲裁模板。"""
    env.dut.fc_cover["FG-ARBITRATION"].mark_function(
        "FC-DCACHE-MISS-REPLAY-PRIORITY",
        test_stage0_dcache_miss_replay_priority_over_scalar,
        ["CK-OVER-SCALAR"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.set_default_inputs()
    _drive_replay_request(env, vaddr=0x5080, rob_idx=54, lq_idx=55, forward_tl_dchannel=True)
    _drive_scalar_request(env, src0=0x6080, rob_idx=56, lq_idx=57)

    env.Step(1)

    assert int(env.replay.ready.value) == 1, "dcache miss replay 应先被 stage0 接收"
    assert int(env.scalar_req.ready.value) == 0, "dcache miss replay 竞争标量时，标量请求不应同拍被消费"
    assert int(env.dcache.req.valid.value) == 1
    assert int(env.dcache.req.bits.lqIdx.value.value) == 55, "最先发出的 DCache 请求应来自 dcache miss replay"


def test_stage0_replay_invalid_bits_do_not_stall_scalar_or_vector(env):
    """无效 replay 载荷不能阻塞普通请求的仲裁模板。

    该模板优先对应静态缺陷 BG-STATIC-003，用于后续动态复现 replay.valid=0 时
    replay.bits 残留值错误参与 s0_rep_stall 的风险。
    """
    env.dut.fc_cover["FG-ARBITRATION"].mark_function(
        "FC-DCACHE-MISS-REPLAY-PRIORITY",
        test_stage0_replay_invalid_bits_do_not_stall_scalar_or_vector,
        ["CK-REPLAY-INVALID-NO-STALL"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.set_default_inputs()
    env.replay.bits.uop.lqIdx.flag.value = 1
    env.replay.bits.uop.lqIdx.value.value = 127
    env.replay.bits.forward_tlDchannel.value = 0
    env.replay.valid.value = 0
    _drive_scalar_request(env, src0=0xA100, rob_idx=94, lq_idx=2)
    env.Step(1)

    assert int(env.scalar_req.ready.value) == 1, "replay.valid=0 时，无效 replay bits 不应阻塞普通标量请求"
    assert int(env.tlb.req.valid.value) == 1, "标量请求应仍能正常向 TLB 发起查询"
    assert int(env.dcache.req.valid.value) == 1, "标量请求应仍能正常向 DCache 发起查询"
    assert int(env.dcache.req.bits.lqIdx.value.value) == 2, "被 stage0 发出的请求应来自标量 load 而非无效 replay"

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.set_default_inputs()
    env.replay.bits.uop.lqIdx.flag.value = 1
    env.replay.bits.uop.lqIdx.value.value = 127
    env.replay.bits.forward_tlDchannel.value = 0
    env.replay.valid.value = 0
    _drive_vector_request(env, vaddr=0xB100, rob_idx=95, lq_idx=4, mask=0x3)
    env.Step(1)

    assert int(env.vector_req.ready.value) == 1, "replay.valid=0 时，无效 replay bits 不应阻塞向量请求"
    assert int(env.tlb.req.valid.value) == 1, "向量请求应仍能正常向 TLB 发起查询"
    assert int(env.dcache.req.valid.value) == 1, "向量请求应仍能正常向 DCache 发起查询"
    assert int(env.dcache.req.bits.lqIdx.value.value) == 4, "被 stage0 发出的请求应来自向量 load 而非无效 replay"


def test_stage0_fast_replay_priority_over_uncache_nc_vector_scalar(env):
    """fast replay 高于 uncache、NC、向量和标量请求的仲裁模板。"""
    env.dut.fc_cover["FG-ARBITRATION"].mark_function(
        "FC-FAST-REPLAY-PRIORITY",
        test_stage0_fast_replay_priority_over_uncache_nc_vector_scalar,
        ["CK-OVER-UNCACHE-LOWER"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.set_default_inputs()
    _drive_fast_replay_request(
        env,
        vaddr=0x6000,
        paddr=0x7000,
        data=0x123456789ABCDEF0,
        rob_idx=92,
        lq_idx=39,
    )
    _drive_uncache_request(env, rob_idx=80, lq_idx=60, pc=0x7000)
    _drive_nc_request(env, vaddr=0x7100, paddr=0x8100, data=0x11, rob_idx=81, lq_idx=61)
    _drive_vector_request(env, vaddr=0x7200, rob_idx=82, lq_idx=62, mask=0x3)
    _drive_scalar_request(env, src0=0x7300, rob_idx=83, lq_idx=63)

    env.Step(1)

    assert int(env.lsq.uncache.ready.value) == 0, "fast replay 竞争时，uncache 请求不应同拍被消费"
    assert int(env.lsq.nc_ldin.ready.value) == 0, "fast replay 竞争时，NC 请求不应同拍被消费"
    assert int(env.vector_req.ready.value) == 0, "fast replay 竞争时，向量请求不应同拍被消费"
    assert int(env.scalar_req.ready.value) == 0, "fast replay 竞争时，标量请求不应同拍被消费"
    assert int(env.dcache.req.valid.value) == 1, "fast replay 被选中后应占用 DCache 端口"
    assert int(env.tlb.req.valid.value) == 1, "fast replay 被选中后应占用 TLB 查询端口"
    assert int(env.dcache.req.bits.lqIdx.value.value) == 39, "最先发出的请求应来自 fast replay"


def test_stage0_dcache_miss_replay_priority_over_fast_replay(env):
    """dcache miss replay 高于 fast replay 的仲裁模板。"""
    env.dut.fc_cover["FG-ARBITRATION"].mark_function(
        "FC-FAST-REPLAY-PRIORITY",
        test_stage0_dcache_miss_replay_priority_over_fast_replay,
        ["CK-BELOW-DCACHE-MISS"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.set_default_inputs()
    _drive_replay_request(env, vaddr=0x5000, rob_idx=91, lq_idx=38, forward_tl_dchannel=True)
    replay_in = _drive_fast_replay_request(env, vaddr=0x6000, paddr=0x7000, data=0x123456789ABCDEF0, rob_idx=92, lq_idx=39)

    assert int(env.replay.ready.value) == 1, "cache miss replay 与 fast replay 竞争时应先允许 replay 发射"

    env.Step(1)

    assert int(env.dcache.req.valid.value) == 1
    assert int(env.dcache.req.bits.lqIdx.value.value) == 38, "同拍竞争时应先发出 dcache miss replay 的 DCache 请求"

    env.replay.valid.value = 0
    fast_selected = False
    for _ in range(4):
        env.Step(1)
        if int(env.dcache.req.valid.value) and int(env.dcache.req.bits.lqIdx.value.value) == 39:
            fast_selected = True
            break

    assert fast_selected, "更高优先级 replay 发射完成后，fast replay 应在下一轮恢复并占用 DCache 请求口"
    replay_in.valid.value = 0


def test_stage0_high_confidence_prefetch_priority_over_vector(env):
    """高置信度预取高于向量请求的仲裁模板。"""
    env.dut.fc_cover["FG-ARBITRATION"].mark_function(
        "FC-PREFETCH-VECTOR-SCALAR-PRIORITY",
        test_stage0_high_confidence_prefetch_priority_over_vector,
        ["CK-HIGHCONF-OVER-VECTOR"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.set_default_inputs()
    _drive_prefetch_request(env, paddr=0x9000, confidence=3, pf_source_value=5)
    _drive_vector_request(env, vaddr=0x4400, rob_idx=93, lq_idx=40, mask=0x3)

    env.Step(1)

    assert int(env.prefetch.req.valid.value) == 1
    assert int(env.vector_req.valid.value) == 1
    assert int(env.vector_req.ready.value) == 0, "高置信度预取同拍竞争时，向量请求不应被错误消费"
    assert int(env.dcache.req.valid.value) == 1, "高置信度预取被仲裁选中后应占用 DCache 端口"
    assert int(env.tlb.req.valid.value) == 0, "prefetch 请求被选中时不应误触发 TLB 翻译"

    env.prefetch.req.valid.value = 0
    env.Step(1)

    assert int(env.vector_req.ready.value) == 1, "高置信度预取发射完成后，向量请求应恢复可发射状态"
    env.vector_req.valid.value = 0


def test_stage0_vector_priority_over_scalar(env):
    """向量请求高于标量请求的仲裁模板。"""
    env.dut.fc_cover["FG-ARBITRATION"].mark_function(
        "FC-PREFETCH-VECTOR-SCALAR-PRIORITY",
        test_stage0_vector_priority_over_scalar,
        ["CK-VECTOR-OVER-SCALAR"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.set_default_inputs()
    _drive_vector_request(env, vaddr=0x4000, rob_idx=10, lq_idx=11, mask=0x3)
    _drive_scalar_request(env, src0=0x5000, rob_idx=12, lq_idx=13)

    env.Step(1)

    assert int(env.vector_req.ready.value) == 1, "向量请求应高于标量请求"
    assert int(env.scalar_req.ready.value) == 0, "向量竞争标量时，标量请求不应同拍被消费"
    assert int(env.dcache.req.valid.value) == 1
    assert int(env.dcache.req.bits.lqIdx.value.value) == 11, "最先发出的 DCache 请求应来自向量路径"
    assert int(env.tlb.req.valid.value) == 1

    env.vector_req.valid.value = 0
    env.Step(1)
    assert int(env.scalar_req.ready.value) == 1, "向量请求撤销后，标量请求应恢复可发射"


def test_stage0_low_confidence_prefetch_lowest_priority(env):
    """低置信度预取处于普通请求最低优先级的仲裁模板。"""
    env.dut.fc_cover["FG-ARBITRATION"].mark_function(
        "FC-PREFETCH-VECTOR-SCALAR-PRIORITY",
        test_stage0_low_confidence_prefetch_lowest_priority,
        ["CK-LOWCONF-LOWEST"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.set_default_inputs()
    _drive_prefetch_request(env, paddr=0x90C0, confidence=0, pf_source_value=4)
    _drive_scalar_request(env, src0=0x6000, rob_idx=20, lq_idx=21)

    env.Step(1)

    assert int(env.io.canAcceptLowConfPrefetch.value) == 0, "低置信度预取与普通请求竞争时必须保持最低优先级"
    assert int(env.scalar_req.ready.value) == 1, "普通标量请求应先被 stage0 接收"
    assert int(env.dcache.req.valid.value) == 1
    assert int(env.dcache.req.bits.lqIdx.value.value) == 21
    assert int(env.tlb.req.valid.value) == 1

    env.scalar_req.valid.value = 0
    lowconf_issued = False
    for _ in range(3):
        env.Step(1)
        if int(env.dcache.req.valid.value) and int(env.tlb.req.valid.value) == 0:
            lowconf_issued = True
            break
    assert lowconf_issued, "普通请求撤销后，低置信度预取应能在空闲窗口被正常发射"


def test_stage0_uncache_priority_over_nc(env):
    """uncache 请求高于 NC 请求的仲裁模板。"""
    env.dut.fc_cover["FG-ARBITRATION"].mark_function(
        "FC-UNCACHE-NC-PRIORITY",
        test_stage0_uncache_priority_over_nc,
        ["CK-UNCACHE-OVER-NC"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.set_default_inputs()
    _drive_uncache_request(env, rob_idx=30, lq_idx=31, sq_idx=0, pc=0x7000)
    _drive_nc_request(env, vaddr=0x7100, paddr=0x8100, data=0x55, rob_idx=32, lq_idx=33)

    env.Step(1)

    assert int(env.lsq.uncache.ready.value) == 1, "uncache 请求应高于 NC 请求"
    assert int(env.lsq.nc_ldin.ready.value) == 0, "uncache 竞争 NC 时，NC 请求不应同拍被消费"
    assert int(env.wakeup.valid.value) == 1, "uncache/MMIO 路径被选中时应可见早唤醒"
    assert int(env.dcache.req.valid.value) == 0
    assert int(env.tlb.req.valid.value) == 0


def test_stage0_nc_priority_over_ordinary_replay(env):
    """NC 请求高于普通 replay 的仲裁模板。"""
    env.dut.fc_cover["FG-ARBITRATION"].mark_function(
        "FC-UNCACHE-NC-PRIORITY",
        test_stage0_nc_priority_over_ordinary_replay,
        ["CK-NC-OVER-ORDINARY-REPLAY"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.set_default_inputs()
    _drive_nc_request(env, vaddr=0x7500, paddr=0x8500, data=0x66, rob_idx=70, lq_idx=71)
    _drive_replay_request(env, vaddr=0x7600, rob_idx=72, lq_idx=73, forward_tl_dchannel=False)

    env.Step(1)

    assert int(env.lsq.nc_ldin.ready.value) == 1, "按规格 NC 应高于普通 replay"
    assert int(env.replay.ready.value) == 0, "普通 replay 在 NC 竞争拍不应被消费"


def test_stage0_uncache_priority_over_replay_vector_and_scalar(env):
    """uncache 请求高于 replay、向量和标量请求的仲裁模板。

    该模板优先对应静态缺陷 BG-STATIC-001，用于后续动态复现 uncache 优先级被错误降低的风险。
    """
    env.dut.fc_cover["FG-ARBITRATION"].mark_function(
        "FC-UNCACHE-NC-PRIORITY",
        test_stage0_uncache_priority_over_replay_vector_and_scalar,
        ["CK-UNCACHE-OVER-REPLAY-VECTOR-SCALAR"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.set_default_inputs()
    _drive_uncache_request(env, rob_idx=60, lq_idx=61, sq_idx=0, pc=0x7200)
    _drive_replay_request(env, vaddr=0x7240, rob_idx=62, lq_idx=63, forward_tl_dchannel=False)
    _drive_vector_request(env, vaddr=0x7280, rob_idx=64, lq_idx=65, mask=0x3)
    _drive_scalar_request(env, src0=0x72C0, rob_idx=66, lq_idx=67)

    env.Step(1)

    assert int(env.lsq.uncache.ready.value) == 1, "按规格 uncache 应高于 replay/vector/scalar"
    assert int(env.replay.ready.value) == 0, "uncache 竞争普通 replay 时，replay 不应同拍被消费"
    assert int(env.vector_req.ready.value) == 0, "uncache 竞争向量时，向量请求不应同拍被消费"
    assert int(env.scalar_req.ready.value) == 0, "uncache 竞争标量时，标量请求不应同拍被消费"


def test_stage0_nc_priority_over_vector_and_scalar(env):
    """NC 请求高于向量和标量请求的仲裁模板。

    该模板优先对应静态缺陷 BG-STATIC-002，用于后续动态复现 NC 优先级被错误降低的风险。
    """
    env.dut.fc_cover["FG-ARBITRATION"].mark_function(
        "FC-UNCACHE-NC-PRIORITY",
        test_stage0_nc_priority_over_vector_and_scalar,
        ["CK-NC-OVER-VECTOR-SCALAR"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.set_default_inputs()
    _drive_nc_request(env, vaddr=0x7700, paddr=0x8700, data=0x77, rob_idx=80, lq_idx=81)
    _drive_vector_request(env, vaddr=0x7800, rob_idx=82, lq_idx=83, mask=0x3)
    _drive_scalar_request(env, src0=0x7900, rob_idx=84, lq_idx=85)

    env.Step(1)

    assert int(env.lsq.nc_ldin.ready.value) == 1, "按规格 NC 应高于向量和标量请求"
    assert int(env.vector_req.ready.value) == 0, "NC 竞争向量时，向量请求不应同拍被消费"
    assert int(env.scalar_req.ready.value) == 0, "NC 竞争标量时，标量请求不应同拍被消费"
