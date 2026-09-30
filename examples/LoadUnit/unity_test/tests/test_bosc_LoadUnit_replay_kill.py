#coding=utf-8

from bosc_LoadUnit_api import *


def _drive_redirect(env, rob_idx: int, level: int = 0):
    env.redirect.valid.value = 1
    env.redirect.bits.level.value = int(level)
    env.redirect.bits.robIdx.flag.value = 1
    env.redirect.bits.robIdx.value.value = int(rob_idx)


def _drive_replay_request(
    env,
    vaddr: int,
    rob_idx: int,
    lq_idx: int,
    sq_idx: int = 0,
    forward_tl_dchannel: bool = False,
):
    env.replay.bits.uop.pc.value = int(vaddr)
    env.replay.bits.uop.fuOpType.value = 3
    env.replay.bits.uop.fuType.value = 0
    env.replay.bits.uop.rfWen.value = 1
    env.replay.bits.uop.fpWen.value = 0
    env.replay.bits.uop.imm.value = 0
    env.replay.bits.uop.pdest.value = 1
    env.replay.bits.uop.preDecodeInfo.valid.value = 0
    env.replay.bits.uop.preDecodeInfo.isRVC.value = 0
    env.replay.bits.uop.preDecodeInfo.brType.value = 0
    env.replay.bits.uop.preDecodeInfo.isCall.value = 0
    env.replay.bits.uop.preDecodeInfo.isRet.value = 0
    env.replay.bits.uop.robIdx.flag.value = 1
    env.replay.bits.uop.robIdx.value.value = int(rob_idx)
    env.replay.bits.uop.lqIdx.flag.value = 1
    env.replay.bits.uop.lqIdx.value.value = int(lq_idx)
    env.replay.bits.uop.sqIdx.flag.value = 1
    env.replay.bits.uop.sqIdx.value.value = int(sq_idx)
    env.replay.bits.uop.ftqPtr.flag.value = 0
    env.replay.bits.uop.ftqPtr.value.value = 0
    env.replay.bits.uop.waitForRobIdx.flag.value = 0
    env.replay.bits.uop.waitForRobIdx.value.value = 0
    env.replay.bits.vaddr.value = int(vaddr)
    env.replay.bits.mask.value = 0xFF
    env.replay.bits.isvec.value = 0
    env.replay.bits.is128bit.value = 0
    env.replay.bits.elemIdx.value = 0
    env.replay.bits.alignedType.value = 0
    env.replay.bits.mbIndex.value = 0
    env.replay.bits.mshrid.value = 0
    env.replay.bits.reg_offset.value = 0
    env.replay.bits.elemIdxInsideVd.value = 0
    env.replay.bits.vecActive.value = 1
    env.replay.bits.forward_tlDchannel.value = int(bool(forward_tl_dchannel))
    env.replay.bits.schedIndex.value = 0
    env.replay.valid.value = 1


def _fill_fast_replay_request(
    env,
    vaddr: int,
    paddr: int,
    data: int,
    late_kill: bool,
    rob_idx: int,
    lq_idx: int,
):
    replay_in = getattr(env.fast_rep, "in")
    replay_in.bits.alignedType.value = 0
    replay_in.bits.data.value = int(data)
    replay_in.bits.elemIdx.value = 0
    replay_in.bits.elemIdxInsideVd.value = 0
    replay_in.bits.is128bit.value = 0
    replay_in.bits.isFrmMisAlignBuf.value = 0
    replay_in.bits.isLoadReplay.value = 1
    replay_in.bits.isvec.value = 0
    replay_in.bits.lateKill.value = int(bool(late_kill))
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
    replay_in.bits.uop.ftqOffset.value = 0
    replay_in.bits.uop.ssid.value = 0
    replay_in.bits.uop.storeSetHit.value = 0
    replay_in.bits.uop.loadWaitBit.value = 0
    replay_in.bits.uop.loadWaitStrict.value = 0
    replay_in.bits.uop.preDecodeInfo.valid.value = 0
    replay_in.bits.uop.preDecodeInfo.isRVC.value = 0
    replay_in.bits.uop.preDecodeInfo.brType.value = 0
    replay_in.bits.uop.preDecodeInfo.isCall.value = 0
    replay_in.bits.uop.preDecodeInfo.isRet.value = 0
    replay_in.bits.uop.robIdx.flag.value = 1
    replay_in.bits.uop.robIdx.value.value = int(rob_idx)
    replay_in.bits.uop.lqIdx.flag.value = 1
    replay_in.bits.uop.lqIdx.value.value = int(lq_idx)
    replay_in.bits.uop.sqIdx.flag.value = 1
    replay_in.bits.uop.sqIdx.value.value = 0
    replay_in.bits.uop.ftqPtr.flag.value = 0
    replay_in.bits.uop.ftqPtr.value.value = 0
    replay_in.bits.uop.waitForRobIdx.flag.value = 0
    replay_in.bits.uop.waitForRobIdx.value.value = 0
    replay_in.valid.value = 1
    return replay_in


def _drive_hit_memory_response(env, paddr: int, data: int):
    env.tlb.resp.valid.value = 1
    env.tlb.resp.bits.miss.value = 0
    getattr(env.tlb.resp.bits.paddr, "0").value = int(paddr)
    if hasattr(env.tlb.resp.bits.paddr, "1"):
        getattr(env.tlb.resp.bits.paddr, "1").value = 0
    env.dcache.resp_bits.data.value = int(data)
    env.dcache.resp_bits.miss.value = 0
    env.dcache.resp_bits.handled.value = 1
    env.dcache.resp_bits.tl_error_delayed_tl.denied.value = 0
    env.dcache.resp_bits.tl_error_delayed_tl.corrupt.value = 0


def _clear_hit_memory_response(env):
    env.tlb.resp.valid.value = 0
    env.tlb.resp.bits.miss.value = 0
    getattr(env.tlb.resp.bits.paddr, "0").value = 0
    if hasattr(env.tlb.resp.bits.paddr, "1"):
        getattr(env.tlb.resp.bits.paddr, "1").value = 0
    env.dcache.resp_bits.data.value = 0
    env.dcache.resp_bits.miss.value = 0
    env.dcache.resp_bits.handled.value = 0
    env.dcache.resp_bits.tl_error_delayed_tl.denied.value = 0
    env.dcache.resp_bits.tl_error_delayed_tl.corrupt.value = 0


def _capture_kill_history(env, cycles: int):
    replay_in = getattr(env.fast_rep, "in")
    history = []
    for cycle in range(cycles):
        history.append(
            {
                "cycle": cycle,
                "redirect_valid": int(env.redirect.valid.value),
                "fast_rep_valid": int(replay_in.valid.value),
                "s1_kill": int(env.dcache.s1.kill.value),
                "s2_kill": int(env.dcache.s2.kill.value),
                "replay_ready": int(env.replay.ready.value),
                "tlb_req_valid": int(env.tlb.req.valid.value),
                "dcache_req_valid": int(env.dcache.req.valid.value),
                "dcache_req_lq_idx": int(env.dcache.req.bits.lqIdx.value.value),
                "fast_rep_out_valid": int(env.fast_rep.out.valid.value),
                "fast_rep_out_lq_idx": int(env.fast_rep.out.bits.uop.lqIdx.value.value),
                "bank_conflict": int(env.dcache.s2.bank_conflict.value),
                "mq_nack": int(env.dcache.s2.mq_nack.value),
                "ldout_valid": int(env.scalar_resp.valid.value),
                "feedback_valid": int(env.feedback_slow.valid.value),
                "s2_ptr_chasing": int(env.dut.io_s2_ptr_chasing.value),
            }
        )
        env.Step(1)
    return history


def test_loadunit_dcache_miss_transitions_to_replay(env):
    """DCache miss 触发 replay 模板。"""
    env.dut.fc_cover["FG-REPLAY-KILL"].mark_function(
        "FC-DCACHE-MISS-REPLAY",
        test_loadunit_dcache_miss_transitions_to_replay,
        ["CK-MISS-TO-REPLAY"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1800,
        fu_op_type=3,
        rob_idx=55,
        lq_idx=12,
        sq_idx=0,
        pc=0x1800,
        max_cycles=12,
    )
    env.tlb.resp.valid.value = 1
    env.tlb.resp.bits.miss.value = 0
    getattr(env.tlb.resp.bits.paddr, "0").value = 0x5800
    env.dcache.resp_bits.miss.value = 1
    env.dcache.resp_bits.handled.value = 0
    history = _capture_kill_history(env, cycles=5)
    _clear_hit_memory_response(env)
    env.dcache.resp_bits.miss.value = 0

    assert issue["accepted"] is True
    assert any(sample["bank_conflict"] == 0 and sample["mq_nack"] == 0 and sample["feedback_valid"] for sample in history), "DCache miss 应进入 replay/慢反馈路径"
    assert not any(sample["ldout_valid"] for sample in history), "DCache miss 不应伪造普通命中写回"


def test_loadunit_dcache_miss_request_can_reissue(env):
    """DCache miss replay 后可重发模板。"""
    env.dut.fc_cover["FG-REPLAY-KILL"].mark_function(
        "FC-DCACHE-MISS-REPLAY",
        test_loadunit_dcache_miss_request_can_reissue,
        ["CK-REPLAY-REISSUE"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1840,
        fu_op_type=3,
        rob_idx=56,
        lq_idx=13,
        sq_idx=0,
        pc=0x1840,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x5840,
        dcache_miss=True,
        hold_cycles=2,
        max_cycles=2,
    )
    _drive_replay_request(env, vaddr=0x1840, rob_idx=56, lq_idx=13)
    history = _capture_kill_history(env, cycles=4)
    env.replay.valid.value = 0

    assert any(sample["redirect_valid"] == 0 for sample in history)
    assert any(
        sample["replay_ready"] and (sample["tlb_req_valid"] or sample["dcache_req_valid"])
        for sample in history
    ), "miss replay 回送后应重新发起访存请求"


def test_loadunit_bank_conflict_detects_replay_need(env):
    """bank conflict 检测触发 replay 模板。"""
    env.dut.fc_cover["FG-REPLAY-KILL"].mark_function(
        "FC-BANK-CONFLICT-REPLAY",
        test_loadunit_bank_conflict_detects_replay_need,
        ["CK-BANK-CONFLICT-DETECT"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1880,
        fu_op_type=3,
        rob_idx=57,
        lq_idx=14,
        sq_idx=0,
        pc=0x1880,
        max_cycles=12,
    )
    env.tlb.resp.valid.value = 1
    env.tlb.resp.bits.miss.value = 0
    getattr(env.tlb.resp.bits.paddr, "0").value = 0x5880
    env.dcache.resp_bits.data.value = 0
    env.dcache.resp_bits.miss.value = 0
    env.dcache.resp_bits.handled.value = 1
    env.dcache.s2.bank_conflict.value = 1
    history = _capture_kill_history(env, cycles=4)
    _clear_hit_memory_response(env)
    env.dcache.s2.bank_conflict.value = 0

    assert any(sample["bank_conflict"] and sample["fast_rep_out_valid"] for sample in history), "bank conflict 应转化为 fast replay 输出"
    assert not any(sample["ldout_valid"] for sample in history), "bank conflict 不应直接完成普通写回"


def test_loadunit_bank_conflict_replay_cause_preserved(env):
    """bank conflict replay 原因保持模板。"""
    env.dut.fc_cover["FG-REPLAY-KILL"].mark_function(
        "FC-BANK-CONFLICT-REPLAY",
        test_loadunit_bank_conflict_replay_cause_preserved,
        ["CK-REPLAY-CAUSE-PRESERVE"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x18C0,
        fu_op_type=3,
        rob_idx=58,
        lq_idx=15,
        sq_idx=0,
        pc=0x18C0,
        max_cycles=12,
    )
    env.tlb.resp.valid.value = 1
    env.tlb.resp.bits.miss.value = 0
    getattr(env.tlb.resp.bits.paddr, "0").value = 0x58C0
    env.dcache.resp_bits.data.value = 0
    env.dcache.resp_bits.miss.value = 0
    env.dcache.resp_bits.handled.value = 1
    env.dcache.s2.bank_conflict.value = 1
    history = []
    for cycle in range(6):
        if cycle >= 2:
            _drive_replay_request(env, vaddr=0x18C0, rob_idx=58, lq_idx=15)
        history.extend(_capture_kill_history(env, cycles=1))
    _clear_hit_memory_response(env)
    env.dcache.s2.bank_conflict.value = 0
    env.replay.valid.value = 0

    replay_sample = next(
        (
            sample
            for sample in history
            if sample["bank_conflict"]
            and sample["fast_rep_out_valid"]
            and sample["fast_rep_out_lq_idx"] == sample["dcache_req_lq_idx"]
        ),
        None,
    )

    assert replay_sample is not None, "bank conflict 应产出可见的 fast replay 记录"
    assert replay_sample["bank_conflict"] == 1
    assert replay_sample["fast_rep_out_lq_idx"] == 15, "bank conflict replay 应保留原始请求的 lqIdx"


def test_loadunit_mq_nack_detects_replay(env):
    """mq nack 检测触发 replay 模板。"""
    env.dut.fc_cover["FG-REPLAY-KILL"].mark_function(
        "FC-MQ-NACK-REPLAY",
        test_loadunit_mq_nack_detects_replay,
        ["CK-MQ-NACK-DETECT"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1900,
        fu_op_type=3,
        rob_idx=59,
        lq_idx=16,
        sq_idx=0,
        pc=0x1900,
        max_cycles=12,
    )
    env.tlb.resp.valid.value = 1
    env.tlb.resp.bits.miss.value = 0
    getattr(env.tlb.resp.bits.paddr, "0").value = 0x5900
    env.dcache.resp_bits.data.value = 0
    env.dcache.resp_bits.miss.value = 0
    env.dcache.resp_bits.handled.value = 1
    env.dcache.s2.mq_nack.value = 1
    history = _capture_kill_history(env, cycles=4)
    _clear_hit_memory_response(env)
    env.dcache.s2.mq_nack.value = 0

    assert any(sample["mq_nack"] and sample["fast_rep_out_valid"] for sample in history), "mq nack 应转化为 fast replay 输出"
    assert not any(sample["ldout_valid"] for sample in history), "mq nack 不应直接完成普通写回"


def test_loadunit_mq_nack_request_retries_later(env):
    """mq nack 清除后重试模板。"""
    env.dut.fc_cover["FG-REPLAY-KILL"].mark_function(
        "FC-MQ-NACK-REPLAY",
        test_loadunit_mq_nack_request_retries_later,
        ["CK-RETRY-LATER"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1940,
        fu_op_type=3,
        rob_idx=60,
        lq_idx=17,
        sq_idx=0,
        pc=0x1940,
        max_cycles=12,
    )
    env.tlb.resp.valid.value = 1
    env.tlb.resp.bits.miss.value = 0
    getattr(env.tlb.resp.bits.paddr, "0").value = 0x5940
    env.dcache.resp_bits.data.value = 0
    env.dcache.resp_bits.miss.value = 0
    env.dcache.resp_bits.handled.value = 1
    env.dcache.s2.mq_nack.value = 1
    _capture_kill_history(env, cycles=4)
    _clear_hit_memory_response(env)
    env.dcache.s2.mq_nack.value = 0

    replay_in = _fill_fast_replay_request(
        env,
        vaddr=0x1940,
        paddr=0x5940,
        data=0x1122334455667788,
        late_kill=False,
        rob_idx=60,
        lq_idx=17,
    )
    history = _capture_kill_history(env, cycles=4)
    replay_in.valid.value = 0

    assert any(
        sample["fast_rep_valid"] and not sample["mq_nack"] and (sample["tlb_req_valid"] or sample["dcache_req_valid"])
        for sample in history
    ), "mq nack 清除后，同一 replay 请求应能重新发起访存"


def test_loadunit_redirect_kills_stage1_request(env):
    """redirect 触发 stage1 kill 模板。"""
    env.dut.fc_cover["FG-REPLAY-KILL"].mark_function(
        "FC-S1-KILL-ON-REDIRECT",
        test_loadunit_redirect_kills_stage1_request,
        ["CK-REDIRECT-KILL"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1200,
        fu_op_type=3,
        rob_idx=40,
        lq_idx=7,
        sq_idx=0,
        pc=0x1200,
        max_cycles=12,
    )
    _drive_redirect(env, rob_idx=0)

    assert issue["accepted"] is True
    assert int(env.redirect.valid.value) == 1
    assert int(env.dcache.s1.kill.value) == 1, "redirect 命中旧 ROB 请求时应立即拉起 s1 kill"
    assert int(env.dcache.s2.kill.value) == 1, "redirect kill 应同步传播到后续 kill 代理"
    assert int(env.scalar_resp.valid.value) == 0

    env.redirect.valid.value = 0


def test_loadunit_redirect_kill_does_not_propagate_to_writeback(env):
    """redirect kill 不进入正常写回模板。"""
    env.dut.fc_cover["FG-REPLAY-KILL"].mark_function(
        "FC-S1-KILL-ON-REDIRECT",
        test_loadunit_redirect_kill_does_not_propagate_to_writeback,
        ["CK-KILL-PROPAGATE"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1240,
        fu_op_type=3,
        rob_idx=41,
        lq_idx=8,
        sq_idx=0,
        pc=0x1240,
        max_cycles=12,
    )
    _drive_redirect(env, rob_idx=0)

    history = []
    for cycle in range(5):
        if cycle < 2:
            _drive_hit_memory_response(env, paddr=0x5240, data=0xDEADBEEFCAFEBABE)
        else:
            _clear_hit_memory_response(env)
        history.extend(_capture_kill_history(env, cycles=1))

    _clear_hit_memory_response(env)
    env.redirect.valid.value = 0

    assert issue["accepted"] is True
    assert any(sample["s1_kill"] for sample in history), "redirect kill 场景必须可见 s1 kill"
    assert not any(sample["ldout_valid"] for sample in history), "被 redirect 杀死的请求不应继续进入正常 ldout 写回"
    assert not any(sample["feedback_valid"] for sample in history), "被 redirect 杀死的请求不应继续产生普通 slow feedback"


def test_loadunit_fast_replay_mismatch_triggers_kill(env):
    """fast replay 地址不匹配触发 kill 模板。"""
    env.dut.fc_cover["FG-REPLAY-KILL"].mark_function(
        "FC-S1-KILL-ON-FAST-REPLAY-MISMATCH",
        test_loadunit_fast_replay_mismatch_triggers_kill,
        ["CK-MISMATCH-KILL"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    replay_in = _fill_fast_replay_request(
        env,
        vaddr=0x2000,
        paddr=0x6000,
        data=0x123456789ABCDEF0,
        late_kill=True,
        rob_idx=33,
        lq_idx=9,
    )
    history = _capture_kill_history(env, cycles=4)

    replay_in.valid.value = 0

    assert any(sample["fast_rep_valid"] for sample in history), "fast replay mismatch 场景必须真实驱动 fast_rep_in"
    assert any(sample["s1_kill"] for sample in history), "fast replay mismatch 应触发 s1 kill"
    assert all(not sample["ldout_valid"] for sample in history), "被 mismatch 杀死的 fast replay 请求不应进入正常写回"
    assert all(not sample["feedback_valid"] for sample in history), "被 mismatch 杀死的 fast replay 请求不应产生普通 slow feedback"


def test_loadunit_fast_replay_match_has_no_false_kill(env):
    """fast replay 地址匹配不误杀模板。"""
    env.dut.fc_cover["FG-REPLAY-KILL"].mark_function(
        "FC-S1-KILL-ON-FAST-REPLAY-MISMATCH",
        test_loadunit_fast_replay_match_has_no_false_kill,
        ["CK-NO-FALSE-KILL"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    replay_in = _fill_fast_replay_request(
        env,
        vaddr=0x2040,
        paddr=0x6040,
        data=0x0FEDCBA987654321,
        late_kill=False,
        rob_idx=34,
        lq_idx=10,
    )
    history = _capture_kill_history(env, cycles=5)
    replay_in.valid.value = 0

    assert any(
        sample["fast_rep_valid"] and not sample["s1_kill"] and (sample["dcache_req_valid"] or sample["fast_rep_out_valid"])
        for sample in history
    ), "地址匹配的 fast replay 不应被误杀，应继续向正常路径推进"
    assert any(sample["ldout_valid"] for sample in history), "地址匹配的 fast replay 最终应能写回"


def test_loadunit_l2l_fail_triggers_stage1_kill(env):
    """l2l fast path 失败触发 kill 模板。"""
    env.dut.fc_cover["FG-REPLAY-KILL"].mark_function(
        "FC-S1-KILL-ON-L2L-FAIL",
        test_loadunit_l2l_fail_triggers_stage1_kill,
        ["CK-L2L-FAIL-KILL"],
    )
    env.dut.fc_cover["FG-FORWARD-VIOLATION"].mark_function(
        "FC-L2L-FAST-FORWARD",
        test_loadunit_l2l_fail_triggers_stage1_kill,
        ["CK-FAST-FWD-FAIL-PATH"],
    )
    api_bosc_LoadUnit_reset(env, max_cycles=8)

    missing_inputs = [
        name
        for name in ("io_l2l_fwd_in_valid", "io_ld_fast_match", "io_ld_fast_fuOpType", "io_ld_fast_imm")
        if not hasattr(env.dut, name)
    ]

    assert not missing_inputs, (
        "当前顶层 wrapper 缺少构造 L2L fail path 所需的黑盒输入端口，"
        f"无法驱动 stage1 kill 场景: {missing_inputs}"
    )


def test_loadunit_l2l_success_has_no_false_kill(env):
    """l2l fast path 成功不误杀模板。"""
    env.dut.fc_cover["FG-REPLAY-KILL"].mark_function(
        "FC-S1-KILL-ON-L2L-FAIL",
        test_loadunit_l2l_success_has_no_false_kill,
        ["CK-L2L-SUCCESS-NO-KILL"],
    )
    env.dut.fc_cover["FG-FORWARD-VIOLATION"].mark_function(
        "FC-L2L-FAST-FORWARD",
        test_loadunit_l2l_success_has_no_false_kill,
        ["CK-FAST-FWD-DATA"],
    )
    api_bosc_LoadUnit_reset(env, max_cycles=8)

    missing_inputs = [
        name
        for name in ("io_l2l_fwd_in_valid", "io_l2l_fwd_in_data", "io_l2l_fwd_in_dly_ld_err")
        if not hasattr(env.dut, name)
    ]

    assert not missing_inputs, (
        "当前顶层 wrapper 缺少构造 L2L success path 所需的黑盒输入端口，"
        f"无法验证 no-false-kill 场景: {missing_inputs}"
    )
