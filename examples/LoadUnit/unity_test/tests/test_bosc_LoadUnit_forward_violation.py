#coding=utf-8

from bosc_LoadUnit_api import *


FORWARD_DATA_128 = 0xFFEEDDCCBBAA99887766554433221100
FORWARD_LOW64 = 0x7766554433221100
DCACHE_DATA_64 = 0x8877665544332211


def test_loadunit_l2l_fast_forward_data_path(env):
    """当前交付 wrapper 应暴露 L2L fast forward 必要输入端口。"""
    env.dut.fc_cover["FG-FORWARD-VIOLATION"].mark_function(
        "FC-L2L-FAST-FORWARD",
        test_loadunit_l2l_fast_forward_data_path,
        ["CK-FAST-FWD-DATA"],
    )
    api_bosc_LoadUnit_reset(env, max_cycles=8)

    # 当前 black-box wrapper 没有暴露 L2L 所需的输入端口，无法从顶层驱动该功能。
    # 该用例保留为 Fail，用于记录交付件的可测性缺口。
    assert hasattr(env.dut, "io_l2l_fwd_in_valid"), (
        "当前交付 wrapper 未暴露 io_l2l_fwd_in_* 输入端口，"
        "黑盒环境无法构造 L2L fast forward 数据成功路径"
    )


def test_loadunit_l2l_fast_forward_fail_path(env):
    """当前交付 wrapper 应暴露 L2L fast forward 失败判定控制端口。"""
    env.dut.fc_cover["FG-FORWARD-VIOLATION"].mark_function(
        "FC-L2L-FAST-FORWARD",
        test_loadunit_l2l_fast_forward_fail_path,
        ["CK-FAST-FWD-FAIL-PATH"],
    )
    api_bosc_LoadUnit_reset(env, max_cycles=8)

    assert hasattr(env.dut, "io_ld_fast_match"), (
        "当前交付 wrapper 未暴露 io_ld_fast_match / io_ld_fast_imm / io_ld_fast_fuOpType 等"
        "L2L fast forward 失败判定控制端口，黑盒环境无法构造失败路径"
    )


def test_loadunit_ldld_nuke_query_issue(env):
    """普通标量 load 在 stage 2 应发起 ld-ld 违例查询。"""
    env.dut.fc_cover["FG-FORWARD-VIOLATION"].mark_function(
        "FC-LDLD-NUKE-QUERY",
        test_loadunit_ldld_nuke_query_issue,
        ["CK-QUERY-ISSUE"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1000,
        fu_op_type=3,
        rob_idx=5,
        lq_idx=2,
        sq_idx=1,
        pc=0x1000,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x3000,
        dcache_data=DCACHE_DATA_64,
        hold_cycles=2,
        max_cycles=2,
    )

    assert env.lsq.ldld_nuke_query.req.valid.value == 1, "stage 2 应发起 ld-ld 查询"
    req = env.lsq.ldld_nuke_query.req.bits.as_dict()
    assert req["paddr"] == 0x3000
    assert req["uop"]["robIdx"]["value"] == 5
    assert req["uop"]["lqIdx"]["value"] == 2
    assert req["data_valid"] == 1


def test_loadunit_ldld_violation_control_response(env):
    """ld-ld 违例命中后应触发控制响应，并阻止正常写回。"""
    env.dut.fc_cover["FG-FORWARD-VIOLATION"].mark_function(
        "FC-LDLD-NUKE-QUERY",
        test_loadunit_ldld_violation_control_response,
        ["CK-VIOLATION-CONTROL"],
    )
    env.dut.fc_cover["FG-EXCEPTION-CONTROL"].mark_function(
        "FC-ROLLBACK-REDIRECT",
        test_loadunit_ldld_violation_control_response,
        ["CK-LDLD-ROLLBACK"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1400,
        fu_op_type=3,
        rob_idx=6,
        lq_idx=3,
        sq_idx=1,
        pc=0x1400,
        max_cycles=12,
    )
    env.csr_ctrl.ldld_vio_check_enable.value = 1
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x3400,
        dcache_data=DCACHE_DATA_64,
        hold_cycles=2,
        max_cycles=2,
    )
    env.lsq.ldld_nuke_query.resp.valid.value = 1
    env.lsq.ldld_nuke_query.resp.bits_rep_frm_fetch.value = 1

    rollback_seen = False
    revoke_seen = False
    scalar_writeback_seen = False
    for _ in range(6):
        rollback_seen |= bool(env.rollback.valid.value)
        revoke_seen |= bool(env.lsq.ldld_nuke_query.revoke.value)
        scalar_writeback_seen |= bool(env.scalar_resp.valid.value)
        env.Step(1)
    env.lsq.ldld_nuke_query.resp.valid.value = 0
    env.lsq.ldld_nuke_query.resp.bits_rep_frm_fetch.value = 0

    assert rollback_seen or revoke_seen, "ld-ld 违例命中后至少应有 rollback 或 revoke 可见"
    assert not scalar_writeback_seen, "ld-ld 违例命中后不应继续正常写回"


def test_loadunit_stld_forward_address_mismatch_control(env):
    """store set 命中且前递地址不匹配时，应触发控制性取消而非正常写回。"""
    env.dut.fc_cover["FG-FORWARD-VIOLATION"].mark_function(
        "FC-STLD-FORWARD-ADDR-MISMATCH",
        test_loadunit_stld_forward_address_mismatch_control,
        ["CK-MISMATCH-REDIRECT-OR-KILL"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x2400,
        fu_op_type=3,
        rob_idx=9,
        lq_idx=3,
        sq_idx=1,
        pc=0x2400,
        store_set_hit=1,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x4400,
        dcache_data=DCACHE_DATA_64,
        forward_addr_invalid=True,
        forward_addr_invalid_sq_idx=1,
        hold_cycles=2,
        max_cycles=2,
    )

    revoke_seen = False
    cancel_seen = False
    feedback_seen = False
    scalar_writeback_seen = False
    for _ in range(6):
        revoke_seen |= bool(env.lsq.stld_nuke_query.revoke.value) or bool(env.lsq.ldld_nuke_query.revoke.value)
        cancel_seen |= bool(env.ld_cancel_ld2.value) if env.ld_cancel_ld2 is not None else False
        feedback_seen |= bool(env.feedback_slow.valid.value)
        scalar_writeback_seen |= bool(env.scalar_resp.valid.value)
        env.Step(1)

    assert revoke_seen or cancel_seen, "地址不匹配时至少应有 revoke 或 ldCancel 等控制响应"
    assert feedback_seen or cancel_seen, "地址不匹配时应对后端给出可见控制反馈"
    assert not scalar_writeback_seen, "地址不匹配控制路径下不应继续正常标量写回"


def test_loadunit_stld_forward_address_mismatch_no_wrong_data(env):
    """地址不匹配时即使给出伪前递数据，也不应把错误数据写回。"""
    env.dut.fc_cover["FG-FORWARD-VIOLATION"].mark_function(
        "FC-STLD-FORWARD-ADDR-MISMATCH",
        test_loadunit_stld_forward_address_mismatch_no_wrong_data,
        ["CK-NO-WRONG-DATA"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x2800,
        fu_op_type=3,
        rob_idx=10,
        lq_idx=4,
        sq_idx=1,
        pc=0x2800,
        store_set_hit=1,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x4800,
        dcache_data=DCACHE_DATA_64,
        forward_source="lsq",
        forward_data=FORWARD_DATA_128,
        forward_mask=0xFFFF,
        forward_addr_invalid=True,
        forward_addr_invalid_sq_idx=1,
        hold_cycles=2,
        max_cycles=2,
    )

    observed_data = None
    control_seen = False
    for _ in range(6):
        control_seen |= bool(env.lsq.stld_nuke_query.revoke.value) or bool(env.ld_cancel_ld2.value)
        if env.scalar_resp.valid.value:
            observed_data = env.scalar_resp.bits.data.value
        env.Step(1)

    assert control_seen, "地址不匹配时应触发控制路径，而不是把伪前递数据当作成功命中"
    assert observed_data is None, "地址不匹配场景不应产生正常标量写回"
    assert observed_data != FORWARD_LOW64


def test_loadunit_storequeue_forward_data_success(env):
    """StoreQueue 前递成功时，最终写回数据应来自 LSQ forward 而非 DCache。"""
    env.dut.fc_cover["FG-FORWARD-VIOLATION"].mark_function(
        "FC-STLD-FORWARD-SUCCESS",
        test_loadunit_storequeue_forward_data_success,
        ["CK-SQ-FORWARD-DATA"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1800,
        fu_op_type=3,
        rob_idx=11,
        lq_idx=4,
        sq_idx=2,
        pc=0x1800,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x3800,
        dcache_data=DCACHE_DATA_64,
        forward_source="lsq",
        forward_data=FORWARD_DATA_128,
        forward_mask=0x00FF,
        hold_cycles=2,
        max_cycles=2,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=6)

    assert result["scalar_writeback"] is not None
    assert result["scalar_writeback"]["data"] == FORWARD_LOW64
    assert result["scalar_writeback"]["data"] != DCACHE_DATA_64
    assert result["feedback_slow"] is not None


def test_loadunit_sbuffer_forward_data_success(env):
    """SBuffer 前递成功时，最终写回数据应来自 SBuffer。"""
    env.dut.fc_cover["FG-FORWARD-VIOLATION"].mark_function(
        "FC-STLD-FORWARD-SUCCESS",
        test_loadunit_sbuffer_forward_data_success,
        ["CK-SBUFFER-FORWARD-DATA"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1C00,
        fu_op_type=3,
        rob_idx=12,
        lq_idx=5,
        sq_idx=2,
        pc=0x1C00,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x3C00,
        dcache_data=DCACHE_DATA_64,
        forward_source="sbuffer",
        forward_data=FORWARD_DATA_128,
        forward_mask=0x00FF,
        hold_cycles=2,
        max_cycles=2,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=6)

    assert result["scalar_writeback"] is not None
    assert result["scalar_writeback"]["data"] == FORWARD_LOW64
    assert result["scalar_writeback"]["data"] != DCACHE_DATA_64
    assert result["feedback_slow"] is not None


def test_loadunit_stld_forward_wait_for_data(env):
    """前递数据未 ready 的等待窗口内，不应产生错误写回。"""
    env.dut.fc_cover["FG-FORWARD-VIOLATION"].mark_function(
        "FC-STLD-FORWARD-DATA-NOT-READY",
        test_loadunit_stld_forward_wait_for_data,
        ["CK-WAIT-FOR-DATA"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x2000,
        fu_op_type=3,
        rob_idx=13,
        lq_idx=6,
        sq_idx=2,
        pc=0x2000,
        max_cycles=12,
    )

    env.tlb.resp.valid.value = 1
    getattr(env.tlb.resp.bits.paddr, "0").value = 0x4000
    env.dcache.resp_bits.data.value = DCACHE_DATA_64
    env.dcache.resp_bits.handled.value = 1
    env.lsq.forward.dataInvalid.value = 1
    env.Step(1)

    env.tlb.resp.valid.value = 1
    getattr(env.tlb.resp.bits.paddr, "0").value = 0x4000
    env.dcache.resp_bits.data.value = DCACHE_DATA_64
    env.dcache.resp_bits.handled.value = 1
    env.lsq.forward.dataInvalid.value = 1
    assert env.lsq.forward.valid.value == 1, "等待窗口前一拍应已向 LSQ 发出前递查询"
    assert env.scalar_resp.valid.value == 0, "数据未 ready 的等待窗口内不应产生 ldout 写回"
    assert env.feedback_slow.valid.value == 0, "等待窗口内不应过早产生恢复性反馈"
    env.Step(1)

    env.tlb.resp.valid.value = 0
    env.lsq.forward.dataInvalid.value = 0


def test_loadunit_stld_forward_replay_when_data_not_ready(env):
    """前递数据持续未 ready 时，应进入恢复性控制路径而非正常提交。"""
    env.dut.fc_cover["FG-FORWARD-VIOLATION"].mark_function(
        "FC-STLD-FORWARD-DATA-NOT-READY",
        test_loadunit_stld_forward_replay_when_data_not_ready,
        ["CK-REPLAY-WHEN-NOT-READY"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x2400,
        fu_op_type=3,
        rob_idx=14,
        lq_idx=7,
        sq_idx=2,
        pc=0x2400,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x4400,
        dcache_data=DCACHE_DATA_64,
        forward_data_invalid=True,
        hold_cycles=2,
        max_cycles=2,
    )

    control_seen = False
    scalar_writeback_seen = False
    for _ in range(4):
        control_seen |= bool(env.feedback_slow.valid.value) or (
            env.ld_cancel_ld2 is not None and bool(env.ld_cancel_ld2.value)
        )
        scalar_writeback_seen |= bool(env.scalar_resp.valid.value)
        env.Step(1)

    assert control_seen, "长期未 ready 应触发恢复性反馈/取消控制"
    assert not scalar_writeback_seen, "前递数据长期未 ready 时不应误提交正常写回"


def test_loadunit_stld_nuke_query_issue(env):
    """普通标量 load 在 stage 2 应发起 st-ld 违例查询。"""
    env.dut.fc_cover["FG-FORWARD-VIOLATION"].mark_function(
        "FC-STLD-NUKE-QUERY",
        test_loadunit_stld_nuke_query_issue,
        ["CK-STORE-QUERY-ISSUE"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x2800,
        fu_op_type=3,
        rob_idx=15,
        lq_idx=8,
        sq_idx=3,
        pc=0x2800,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x4800,
        dcache_data=DCACHE_DATA_64,
        hold_cycles=2,
        max_cycles=2,
    )

    assert env.lsq.stld_nuke_query.req.valid.value == 1, "stage 2 应发起 st-ld 查询"
    req = env.lsq.stld_nuke_query.req.bits.as_dict()
    assert req["paddr"] == 0x4800
    assert req["uop"]["robIdx"]["value"] == 15
    assert req["uop"]["sqIdx"]["value"] == 3
    assert req["mask"] == 0xFF
    assert req["data_valid"] == 1


def test_loadunit_stld_nuke_result_handling(env):
    """st-ld 违例命中后应触发取消/重定向代理，并阻止正常写回。"""
    env.dut.fc_cover["FG-FORWARD-VIOLATION"].mark_function(
        "FC-STLD-NUKE-QUERY",
        test_loadunit_stld_nuke_result_handling,
        ["CK-NUKE-RESULT-HANDLING"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x2C00,
        fu_op_type=3,
        rob_idx=16,
        lq_idx=9,
        sq_idx=3,
        pc=0x2C00,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x4C00,
        dcache_data=DCACHE_DATA_64,
        hold_cycles=1,
        max_cycles=1,
    )

    assert env.ld_cancel_ld2 is not None, "需要通过 io_ldCancel_ld2Cancel 观察 st-ld 违例控制响应"
    ld_cancel_seen = False
    scalar_writeback_seen = False
    for _ in range(6):
        env.stld_nuke_query["0"].valid.value = 1
        env.stld_nuke_query["0"].bits.matchType.value = 0
        env.stld_nuke_query["0"].bits.paddr.value = 0x4C00
        env.stld_nuke_query["0"].bits.mask.value = 0xFF
        env.stld_nuke_query["0"].bits.robIdx.flag.value = 1
        env.stld_nuke_query["0"].bits.robIdx.value.value = 1
        ld_cancel_seen |= bool(env.ld_cancel_ld2.value)
        scalar_writeback_seen |= bool(env.scalar_resp.valid.value)
        env.Step(1)
    env.stld_nuke_query["0"].valid.value = 0

    assert ld_cancel_seen, "st-ld 违例命中后应触发可见取消/重定向代理"
    assert not scalar_writeback_seen, "st-ld 违例命中后不应继续正常写回"
