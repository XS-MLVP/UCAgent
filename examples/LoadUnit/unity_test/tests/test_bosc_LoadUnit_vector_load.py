#coding=utf-8

from bosc_LoadUnit_api import *


VECTOR_WRITEBACK_DATA_128 = 0x0123456789ABCDEFFEDCBA9876543210


def _vector_hit_result(
    env,
    *,
    vaddr: int,
    paddr: int,
    mask: int,
    reg_offset: int,
    elem_idx: int,
    elem_idx_inside_vd: int,
    aligned_type: int,
    rob_idx: int,
    lq_idx: int,
    data: int = VECTOR_WRITEBACK_DATA_128,
):
    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_vector_load(
        env,
        vaddr=vaddr,
        mask=mask,
        reg_offset=reg_offset,
        elem_idx=elem_idx,
        elem_idx_inside_vd=elem_idx_inside_vd,
        aligned_type=aligned_type,
        vec_active=1,
        rob_idx=rob_idx,
        lq_idx=lq_idx,
        pc=vaddr,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=paddr,
        dcache_data=data,
        hold_cycles=2,
        max_cycles=2,
    )
    capture = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=4)
    if capture["vector_writeback"] is None:
        capture = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=8)
    return issue, capture


def test_loadunit_vector_accepts_request(env):
    """向量请求正常受理模板。"""
    env.dut.fc_cover["FG-VECTOR-LOAD"].mark_function(
        "FC-VECTOR-HANDSHAKE",
        test_loadunit_vector_accepts_request,
        ["CK-VECTOR-ACCEPT"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    result = api_bosc_LoadUnit_send_vector_load(
        env,
        vaddr=0x4000,
        mask=0x0033,
        reg_offset=2,
        elem_idx=5,
        elem_idx_inside_vd=1,
        aligned_type=4,
        vec_active=1,
        rob_idx=96,
        lq_idx=28,
        pc=0x4000,
        max_cycles=12,
    )

    assert result["accepted"] is True, "向量请求应在 ready 窗口内被正常受理"
    assert result["request"]["uop"]["robIdx"]["value"] == 96
    assert result["request"]["uop"]["lqIdx"]["value"] == 28
    assert int(env.vector_req.valid.value) == 0, "vecldin 握手完成后 valid 应自动撤销"
    assert int(env.tlb.req.valid.value) == 1, "向量请求进入 stage0 后应对 TLB 发起查询"
    assert int(env.dcache.req.valid.value) == 1, "向量请求进入 stage0 后应对 DCache 发起查询"
    assert int(env.dcache.req.bits.lqIdx.value.value) == 28, "可见的 DCache 请求应携带当前向量请求的 lqIdx"


def test_loadunit_vector_request_holds_under_backpressure(env):
    """向量请求背压保持模板。"""
    env.dut.fc_cover["FG-VECTOR-LOAD"].mark_function(
        "FC-VECTOR-HANDSHAKE",
        test_loadunit_vector_request_holds_under_backpressure,
        ["CK-VECTOR-BACKPRESSURE"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.set_default_inputs()
    env.misalign.ldin.bits.fullva.value = 0x8000
    env.misalign.ldin.bits.vaddr.value = 0x8000
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
    env.misalign.ldin.bits.uop.pc.value = 0x8000
    env.misalign.ldin.bits.uop.fuOpType.value = 0
    env.misalign.ldin.bits.uop.fuType.value = 0
    env.misalign.ldin.bits.uop.rfWen.value = 1
    env.misalign.ldin.bits.uop.fpWen.value = 0
    env.misalign.ldin.bits.uop.robIdx.flag.value = 1
    env.misalign.ldin.bits.uop.robIdx.value.value = 97
    env.misalign.ldin.bits.uop.lqIdx.flag.value = 1
    env.misalign.ldin.bits.uop.lqIdx.value.value = 41
    env.misalign.ldin.bits.uop.sqIdx.flag.value = 1
    env.misalign.ldin.bits.uop.sqIdx.value.value = 0
    env.misalign.ldin.valid.value = 1

    env.vector_req.bits.vaddr.value = 0x9000
    env.vector_req.bits.basevaddr.value = 0x9000
    env.vector_req.bits.mask.value = 0x0055
    env.vector_req.bits.reg_offset.value = 3
    env.vector_req.bits.elemIdx.value = 9
    env.vector_req.bits.elemIdxInsideVd.value = 2
    env.vector_req.bits.alignedType.value = 4
    env.vector_req.bits.vecActive.value = 1
    env.vector_req.bits.uop.pc.value = 0x9000
    env.vector_req.bits.uop.vecWen.value = 1
    env.vector_req.bits.uop.rfWen.value = 0
    env.vector_req.bits.uop.fpWen.value = 0
    env.vector_req.bits.uop.robIdx.flag.value = 1
    env.vector_req.bits.uop.robIdx.value.value = 98
    env.vector_req.bits.uop.lqIdx.flag.value = 1
    env.vector_req.bits.uop.lqIdx.value.value = 43
    env.vector_req.valid.value = 1
    before = env.vector_req.bits.as_dict()

    ready_history = []
    for _ in range(2):
        env.Step(1)
        ready_history.append(int(env.vector_req.ready.value))

    after = env.vector_req.bits.as_dict()
    env.misalign.ldin.valid.value = 0
    env.Step(1)

    assert 0 in ready_history, "更高优先级 misalign 占用 stage0 时，应至少出现一拍 vecldin.ready=0"
    assert before == after, "向量请求在背压保持期间不应丢字段或被错误改写"
    assert int(env.vector_req.ready.value) == 1, "上游背压解除后，同一条向量请求应恢复可发射"
    assert int(env.dcache.req.valid.value) == 1
    assert int(env.dcache.req.bits.lqIdx.value.value) == 43, "解除背压后发出的请求应仍是原始向量载荷"


def test_loadunit_vector_offset_and_mask_pass_through(env):
    """向量 offset 与 mask 信息传递模板。"""
    env.dut.fc_cover["FG-VECTOR-LOAD"].mark_function(
        "FC-VECTOR-ADDR-MASK-INFO",
        test_loadunit_vector_offset_and_mask_pass_through,
        ["CK-OFFSET-AND-MASK-PASS"],
    )

    _, capture = _vector_hit_result(
        env,
        vaddr=0x4400,
        paddr=0x6400,
        mask=0xA55A,
        reg_offset=7,
        elem_idx=4,
        elem_idx_inside_vd=1,
        aligned_type=4,
        rob_idx=99,
        lq_idx=29,
    )

    assert capture["vector_writeback"] is not None, "向量命中场景应产生 vecldout 写回"
    assert capture["vector_writeback"]["mask"] == 0xA55A, "vecldout 应保留原始 mask 信息"
    assert capture["vector_writeback"]["reg_offset"] == 7, "vecldout 应保留原始 reg_offset 信息"


def test_loadunit_vector_element_index_pass_through(env):
    """向量元素索引传递模板。"""
    env.dut.fc_cover["FG-VECTOR-LOAD"].mark_function(
        "FC-VECTOR-ADDR-MASK-INFO",
        test_loadunit_vector_element_index_pass_through,
        ["CK-ELEM-IDX-PASS"],
    )

    _, capture = _vector_hit_result(
        env,
        vaddr=0x4480,
        paddr=0x6480,
        mask=0x0033,
        reg_offset=2,
        elem_idx=15,
        elem_idx_inside_vd=3,
        aligned_type=4,
        rob_idx=100,
        lq_idx=30,
    )

    assert capture["vector_writeback"] is not None, "向量命中场景应产生 vecldout 写回"
    assert capture["vector_writeback"]["elemIdx"] == 15, "vecldout 应保留原始 elemIdx"
    assert capture["vector_writeback"]["elemIdxInsideVd"] == 3, "vecldout 应保留原始 elemIdxInsideVd"


def test_loadunit_vector_writes_back_vecdata(env):
    """向量数据写回模板。"""
    env.dut.fc_cover["FG-VECTOR-LOAD"].mark_function(
        "FC-VECTOR-WRITEBACK",
        test_loadunit_vector_writes_back_vecdata,
        ["CK-VECDATA-WRITEBACK"],
    )

    _, capture = _vector_hit_result(
        env,
        vaddr=0x4500,
        paddr=0x6500,
        mask=0x0033,
        reg_offset=5,
        elem_idx=6,
        elem_idx_inside_vd=2,
        aligned_type=4,
        rob_idx=101,
        lq_idx=31,
        data=VECTOR_WRITEBACK_DATA_128,
    )

    assert capture["vector_writeback"] is not None, "向量命中场景应产生 vecldout 写回"
    assert capture["scalar_writeback"] is None, "vecdata 检查场景不应误走标量写回口"
    assert capture["vector_writeback"]["vecdata"] == VECTOR_WRITEBACK_DATA_128, "alignedType=4 时 vecldout.vecdata 应回写完整 128bit 数据"


def test_loadunit_vector_writeback_exception_fields(env):
    """向量异常字段写回模板。"""
    env.dut.fc_cover["FG-VECTOR-LOAD"].mark_function(
        "FC-VECTOR-WRITEBACK",
        test_loadunit_vector_writeback_exception_fields,
        ["CK-EXCEPTION-FIELD-WRITEBACK"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_vector_load(
        env,
        vaddr=0x4680,
        mask=0x0003,
        reg_offset=1,
        elem_idx=2,
        elem_idx_inside_vd=0,
        aligned_type=4,
        vec_active=1,
        rob_idx=104,
        lq_idx=34,
        pc=0x4680,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x6680,
        tlb_pf_ld=True,
        pmp_ld=True,
        hold_cycles=2,
        max_cycles=2,
    )
    capture = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=8)

    assert capture["vector_writeback"] is not None, "向量异常场景仍应通过 vecldout 对外可见"
    assert capture["scalar_writeback"] is None, "向量异常场景不应误走标量 ldout"
    assert capture["vector_writeback"]["hasException"] == 1, "向量异常场景应显式拉高 hasException"
    assert capture["vector_writeback"]["exceptionVec"]["13"] == 1, "TLB page fault 应映射到向量写回异常位"
    assert capture["vector_writeback"]["exceptionVec"]["5"] == 1, "PMP load fault 应映射到向量写回异常位"
    assert capture["vector_writeback"]["vecdata"] == 0, "异常向量写回不应伪造正常 vecdata 成功语义"


def test_loadunit_vector_writeback_holds_under_backpressure(env):
    """向量写回背压保持模板。

    该模板优先对应静态缺陷 BG-STATIC-005，用于后续动态复现 vecldout.ready 被忽略、
    向量写回在背压下可能丢失的风险。
    """
    env.dut.fc_cover["FG-VECTOR-LOAD"].mark_function(
        "FC-VECTOR-WRITEBACK",
        test_loadunit_vector_writeback_holds_under_backpressure,
        ["CK-VECLDOUT-BACKPRESSURE"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)

    assert hasattr(env.vector_resp, "ready"), (
        "交付黑盒接口缺少 vecldout.ready，无法对 Decoupled 向量写回口施加背压；"
        "这同时意味着 CK-VECLDOUT-BACKPRESSURE 无法按规格验证"
    )


def test_loadunit_vector_path_has_no_slow_feedback(env):
    """向量路径不输出慢反馈模板。"""
    env.dut.fc_cover["FG-VECTOR-LOAD"].mark_function(
        "FC-VECTOR-NO-FEEDBACK-SLOW",
        test_loadunit_vector_path_has_no_slow_feedback,
        ["CK-NO-SLOW-FEEDBACK"],
    )

    _, capture = _vector_hit_result(
        env,
        vaddr=0x4580,
        paddr=0x6580,
        mask=0x00F0,
        reg_offset=4,
        elem_idx=8,
        elem_idx_inside_vd=1,
        aligned_type=4,
        rob_idx=102,
        lq_idx=32,
    )

    assert capture["vector_writeback"] is not None, "向量正常完成场景应产生 vecldout"
    assert capture["feedback_slow"] is None, "向量路径完成时不应误走标量 slow feedback"
    assert capture["scalar_writeback"] is None, "向量路径无 slow feedback 时也不应混入标量 ldout"


def test_loadunit_vector_path_still_writes_back_without_slow_feedback(env):
    """向量路径无慢反馈但仍写回模板。"""
    env.dut.fc_cover["FG-VECTOR-LOAD"].mark_function(
        "FC-VECTOR-NO-FEEDBACK-SLOW",
        test_loadunit_vector_path_still_writes_back_without_slow_feedback,
        ["CK-STILL-WRITES-BACK"],
    )

    issue, capture = _vector_hit_result(
        env,
        vaddr=0x4600,
        paddr=0x6600,
        mask=0x0033,
        reg_offset=5,
        elem_idx=6,
        elem_idx_inside_vd=2,
        aligned_type=4,
        rob_idx=103,
        lq_idx=33,
    )

    assert issue["accepted"] is True
    assert capture["feedback_slow"] is None, "无 slow feedback 的向量场景下不应出现标量反馈"
    assert capture["vector_writeback"] is not None, "抑制 feedback_slow 不应影响向量写回本身"
    assert capture["vector_writeback"]["mask"] == 0x0033
