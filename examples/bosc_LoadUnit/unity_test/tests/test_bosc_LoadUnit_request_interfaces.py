#coding=utf-8

from bosc_LoadUnit_api import *


DCACHE_HIT_DATA_64 = 0x8877665544332211
FORWARD_DATA_128 = 0xFFEEDDCCBBAA99887766554433221100
FORWARD_LOW64 = 0x7766554433221100
VECTOR_DATA_128 = 0x0123456789ABCDEFFEDCBA9876543210


def _scalar_hit_result(env, src0: int, paddr: int, data: int, rob_idx: int, lq_idx: int, sq_idx: int, pc: int):
    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=src0,
        fu_op_type=3,
        rob_idx=rob_idx,
        lq_idx=lq_idx,
        sq_idx=sq_idx,
        pc=pc,
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
    return api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=12)


def test_loadunit_reset_sequence(env):
    """复位序列模板。"""
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-RESET-AND-CLOCK",
        test_loadunit_reset_sequence,
        ["CK-RESET-SEQUENCE"],
    )

    result = api_bosc_LoadUnit_reset(env, reset_cycles=3, max_cycles=8)

    assert result["reset_cycles"] == 3
    assert result["consumed_cycles"] == 4
    assert int(env.reset_pin.value) == 0
    assert int(env.scalar_resp.valid.value) == 0
    assert int(env.vector_resp.valid.value) == 0
    assert int(env.wakeup.valid.value) == 0
    assert int(env.feedback_slow.valid.value) == 0
    assert int(env.rollback.valid.value) == 0

    issue = api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1100,
        fu_op_type=3,
        rob_idx=68,
        lq_idx=16,
        sq_idx=0,
        pc=0x1100,
        max_cycles=12,
    )
    assert issue["accepted"] is True, "复位释放后 DUT 应恢复到可接收普通标量请求的状态"


def test_loadunit_multi_cycle_step_progression(env):
    """多周期 Step 推进模板。"""
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-RESET-AND-CLOCK",
        test_loadunit_multi_cycle_step_progression,
        ["CK-MULTI-CYCLE-STEP"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    idle_history = []
    for _ in range(2):
        idle_history.append(
            (
                int(env.scalar_resp.valid.value),
                int(env.vector_resp.valid.value),
                int(env.wakeup.valid.value),
                int(env.feedback_slow.valid.value),
            )
        )
        env.Step(1)

    assert all(sample == (0, 0, 0, 0) for sample in idle_history), "空闲多拍推进期间不应凭空产生输出脉冲"

    issue = api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1140,
        fu_op_type=3,
        rob_idx=69,
        lq_idx=17,
        sq_idx=0,
        pc=0x1140,
        max_cycles=12,
    )
    assert issue["accepted"] is True

    pre_resp_sample = (
        int(env.scalar_resp.valid.value),
        int(env.feedback_slow.valid.value),
        int(env.tlb.req.valid.value),
        int(env.dcache.req.valid.value),
    )
    env.Step(1)

    assert pre_resp_sample[0] == 0 and pre_resp_sample[1] == 0, "未注入响应前不应提前产生最终写回或慢反馈"
    assert pre_resp_sample[2] or pre_resp_sample[3], "请求进入流水后应在后续拍次对 TLB/DCache 发起访问"

    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x5140,
        dcache_data=DCACHE_HIT_DATA_64,
        hold_cycles=2,
        max_cycles=2,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=12)

    assert result["scalar_writeback"] is not None, "多拍推进后在命中响应注入场景应观察到最终标量写回"
    assert result["scalar_writeback"]["uop"]["robIdx"]["value"] == 69


def test_loadunit_scalar_request_ready_handshake(env):
    """标量请求 ready 握手模板。"""
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-SEND-SCALAR-LOAD",
        test_loadunit_scalar_request_ready_handshake,
        ["CK-READY-HANDSHAKE"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    result = api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1234,
        fu_op_type=3,
        rob_idx=70,
        lq_idx=18,
        sq_idx=2,
        pc=0x2234,
        max_cycles=12,
    )

    assert result["accepted"] is True
    assert result["request"]["src"]["0"] == 0x1234
    assert result["request"]["uop"]["fuOpType"] == 3
    assert result["request"]["uop"]["robIdx"]["value"] == 70
    assert result["request"]["uop"]["lqIdx"]["value"] == 18
    assert result["request"]["uop"]["sqIdx"]["value"] == 2
    assert result["request"]["uop"]["pc"] == 0x2234
    assert int(env.scalar_req.valid.value) == 0, "握手完成后 API 应撤销 ldin.valid，避免重复消费同一请求"

    env.Step(1)
    assert int(env.scalar_req.valid.value) == 0


def test_loadunit_scalar_request_backpressure_hold(env):
    """标量请求背压保持模板。"""
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-SEND-SCALAR-LOAD",
        test_loadunit_scalar_request_backpressure_hold,
        ["CK-BACKPRESSURE-HOLD"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    hold = api_bosc_LoadUnit_hold_scalar_load_under_backpressure(
        env,
        src0=0x1800,
        fu_op_type=3,
        rob_idx=71,
        lq_idx=19,
        sq_idx=0,
        pc=0x1800,
        hold_cycles=3,
        max_cycles=8,
    )

    assert hold["held"] is True, "背压场景中应至少出现一拍 ldin.ready=0"
    assert hold["stable"] is True, "背压持续期间关键请求字段应保持稳定"
    assert 0 in hold["ready_history"]
    assert hold["before"]["src"]["0"] == 0x1800
    assert hold["after"]["uop"]["robIdx"]["value"] == 71

    issue = api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1800,
        fu_op_type=3,
        rob_idx=71,
        lq_idx=19,
        sq_idx=0,
        pc=0x1800,
        max_cycles=12,
    )
    assert issue["accepted"] is True, "背压解除后相同载荷应能重新被正常接收"


def test_loadunit_vector_request_handshake(env):
    """向量请求握手模板。"""
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-SEND-VECTOR-LOAD",
        test_loadunit_vector_request_handshake,
        ["CK-VECTOR-HANDSHAKE"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    result = api_bosc_LoadUnit_send_vector_load(
        env,
        vaddr=0x4000,
        mask=0x0F0F,
        reg_offset=2,
        elem_idx=3,
        elem_idx_inside_vd=1,
        aligned_type=1,
        vec_active=1,
        rob_idx=72,
        lq_idx=20,
        pc=0x3000,
        max_cycles=12,
    )

    assert result["accepted"] is True
    assert result["request"]["vaddr"] == 0x4000
    assert result["request"]["mask"] == 0x0F0F
    assert result["request"]["reg_offset"] == 2
    assert result["request"]["elemIdx"] == 3
    assert result["request"]["elemIdxInsideVd"] == 1
    assert result["request"]["uop"]["robIdx"]["value"] == 72
    assert result["request"]["uop"]["lqIdx"]["value"] == 20
    assert int(env.vector_req.valid.value) == 0, "向量握手完成后 vecldin.valid 应自动撤销"


def test_loadunit_vector_request_field_fill(env):
    """向量请求字段封装模板。"""
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-SEND-VECTOR-LOAD",
        test_loadunit_vector_request_field_fill,
        ["CK-VECTOR-FIELD-FILL"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    result = api_bosc_LoadUnit_send_vector_load(
        env,
        vaddr=0x41C0,
        mask=0xA55A,
        reg_offset=7,
        elem_idx=15,
        elem_idx_inside_vd=3,
        aligned_type=2,
        vec_active=1,
        rob_idx=73,
        lq_idx=21,
        pc=0x31C0,
        max_cycles=12,
    )

    assert result["accepted"] is True
    assert result["request"]["basevaddr"] == 0x41C0
    assert result["request"]["mask"] == 0xA55A
    assert result["request"]["reg_offset"] == 7
    assert result["request"]["elemIdx"] == 15
    assert result["request"]["elemIdxInsideVd"] == 3
    assert result["request"]["alignedType"] == 2
    assert result["request"]["uop"]["vecWen"] == 1
    assert result["request"]["uop"]["rfWen"] == 0
    assert result["request"]["uop"]["robIdx"]["value"] == 73
    assert result["request"]["uop"]["lqIdx"]["value"] == 21


def test_loadunit_tlb_pmp_response_injection(env):
    """TLB/PMP 响应注入模板。"""
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-INJECT-MEMORY-RESP",
        test_loadunit_tlb_pmp_response_injection,
        ["CK-TLB-PMP-INJECT"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1A00,
        fu_op_type=3,
        rob_idx=66,
        lq_idx=14,
        sq_idx=0,
        pc=0x1A00,
        max_cycles=12,
    )
    inject = api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x5A00,
        dcache_data=0x0123456789ABCDEF,
        hold_cycles=1,
        max_cycles=1,
    )
    hit_result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=8)

    assert inject["tlb_valid"] == 1
    assert inject["tlb_paddr"] == 0x5A00
    assert int(env.tlb.resp.valid.value) == 0, "单拍 TLB 响应注入结束后应自动清零"
    assert int(env.pmp.ld.value) == 0 and int(env.pmp.st.value) == 0, "PMP 瞬时输入在 API 返回后不应残留"
    assert hit_result["scalar_writeback"] is not None, "正常 TLB/PMP 注入后请求应继续推进到写回"
    assert hit_result["scalar_writeback"]["debug"]["paddr"] == 0x5A00

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1A40,
        fu_op_type=3,
        rob_idx=67,
        lq_idx=15,
        sq_idx=0,
        pc=0x1A40,
        max_cycles=12,
    )
    fault_inject = api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x5A40,
        tlb_pf_ld=True,
        pmp_ld=True,
        hold_cycles=1,
        max_cycles=1,
    )
    fault_result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=8)
    fault_bits = {
        bit
        for bit, value in fault_result["scalar_writeback"]["uop"]["exceptionVec"].items()
        if value
    }

    assert fault_inject["tlb_pf_ld"] == 1 and fault_inject["pmp_ld"] == 1
    assert int(env.tlb.resp.valid.value) == 0 and int(env.pmp.ld.value) == 0, "异常响应注入结束后也应清理瞬时输入"
    assert "13" in fault_bits or "5" in fault_bits, "TLB/PMP 异常注入后应在写回中留下可见异常位"
    assert fault_result["feedback_slow"] is not None, "异常场景仍应留下可见的慢反馈/控制输出"


def test_loadunit_dcache_and_forward_response_injection(env):
    """DCache/前递响应注入模板。"""
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-INJECT-MEMORY-RESP",
        test_loadunit_dcache_and_forward_response_injection,
        ["CK-DCACHE-FORWARD-INJECT"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1C00,
        fu_op_type=3,
        rob_idx=74,
        lq_idx=22,
        sq_idx=0,
        pc=0x1C00,
        max_cycles=12,
    )
    bank_conflict = api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x5C00,
        dcache_bank_conflict=True,
        hold_cycles=1,
        max_cycles=1,
    )
    assert bank_conflict["dcache_bank_conflict"] == 1
    assert int(env.dcache.s2.bank_conflict.value) == 0, "bank conflict 注入结束后一拍应自动清理"

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1C40,
        fu_op_type=3,
        rob_idx=75,
        lq_idx=23,
        sq_idx=0,
        pc=0x1C40,
        max_cycles=12,
    )
    mq_nack = api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x5C40,
        dcache_mq_nack=True,
        hold_cycles=1,
        max_cycles=1,
    )
    assert mq_nack["dcache_mq_nack"] == 1
    assert int(env.dcache.s2.mq_nack.value) == 0, "mq nack 注入结束后一拍应自动清理"

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1C80,
        fu_op_type=3,
        rob_idx=76,
        lq_idx=24,
        sq_idx=2,
        pc=0x1C80,
        max_cycles=12,
    )
    forward = api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x5C80,
        dcache_data=DCACHE_HIT_DATA_64,
        forward_source="lsq",
        forward_data=FORWARD_DATA_128,
        forward_mask=0x00FF,
        hold_cycles=2,
        max_cycles=2,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=6)

    assert forward["forward_source"] == "lsq"
    assert forward["forward_mask"] == 0x00FF
    assert result["scalar_writeback"] is not None
    assert result["scalar_writeback"]["data"] == FORWARD_LOW64, "前递命中时最终写回应取自注入的 forwardData"
    assert result["scalar_writeback"]["data"] != DCACHE_HIT_DATA_64
    assert int(getattr(env.lsq.forward.forwardData, "0").value) == 0
    assert int(getattr(env.lsq.forward.forwardMask, "0").value) == 0


def test_loadunit_scalar_writeback_capture(env):
    """标量写回采集模板。"""
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-COLLECT-WRITEBACK-FEEDBACK",
        test_loadunit_scalar_writeback_capture,
        ["CK-SCALAR-CAPTURE"],
    )

    result = _scalar_hit_result(
        env,
        src0=0x2200,
        paddr=0x6200,
        data=DCACHE_HIT_DATA_64,
        rob_idx=77,
        lq_idx=25,
        sq_idx=0,
        pc=0x2200,
    )

    assert result["scalar_writeback"] is not None
    assert result["feedback_slow"] is not None
    assert result["scalar_writeback"]["data"] == DCACHE_HIT_DATA_64
    assert result["scalar_writeback"]["uop"]["robIdx"]["value"] == 77
    assert result["scalar_writeback"]["uop"]["lqIdx"]["value"] == 25
    assert result["scalar_writeback"]["uop"]["pdest"] == 1
    assert not any(result["scalar_writeback"]["uop"]["exceptionVec"].values()), "普通命中写回不应伪造异常位"
    assert result["scalar_writeback"]["debug"]["paddr"] == 0x6200
    assert result["scalar_writeback"]["debug"]["vaddr"] == 0x2200


def test_loadunit_vector_and_control_capture(env):
    """向量写回和控制输出采集模板。"""
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-COLLECT-WRITEBACK-FEEDBACK",
        test_loadunit_vector_and_control_capture,
        ["CK-VECTOR-AND-CONTROL-CAPTURE"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_mmio_load(
        env,
        rob_idx=78,
        lq_idx=26,
        sq_idx=0,
        pc=0x3400,
        pdest=8,
        pmp_mmio_hint=True,
        max_cycles=12,
    )
    control = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=2)

    assert control["wakeup"] is not None, "统一采集 API 应能捕获纯控制型 wakeup 输出"
    assert control["wakeup"]["robIdx"]["value"] == 78
    assert control["scalar_writeback"] is None

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_vector_load(
        env,
        vaddr=0x4400,
        mask=0x0033,
        reg_offset=5,
        elem_idx=6,
        elem_idx_inside_vd=2,
        aligned_type=1,
        vec_active=1,
        rob_idx=79,
        lq_idx=27,
        pc=0x4400,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x6400,
        dcache_data=VECTOR_DATA_128,
        hold_cycles=2,
        max_cycles=2,
    )
    first_capture = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=4)
    vector_capture = first_capture
    if vector_capture["vector_writeback"] is None:
        vector_capture = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=8)

    assert vector_capture["vector_writeback"] is not None, "统一采集 API 应能返回 vecldout 写回内容"
    assert vector_capture["vector_writeback"]["mask"] == 0x0033
    assert vector_capture["vector_writeback"]["reg_offset"] == 5
    assert vector_capture["vector_writeback"]["elemIdx"] == 6
    assert vector_capture["vector_writeback"]["elemIdxInsideVd"] == 2
    assert vector_capture["vector_writeback"]["alignedType"] == 1
    assert vector_capture["feedback_slow"] is None, "向量写回采集场景不应混入普通 slow feedback"
