#coding=utf-8

from bosc_LoadUnit_api import *


def _scalar_exception_bits(result):
    assert result["scalar_writeback"] is not None, "期望观测到标量写回"
    return {
        bit
        for bit, value in result["scalar_writeback"]["uop"]["exceptionVec"].items()
        if value
    }


def test_loadunit_single_tlb_or_pmp_exception_report(env):
    """单一 TLB/PMP 异常应通过异常写回路径上报。"""
    env.dut.fc_cover["FG-EXCEPTION-CONTROL"].mark_function(
        "FC-TLB-PMP-EXCEPTION-MERGE",
        test_loadunit_single_tlb_or_pmp_exception_report,
        ["CK-SINGLE-EXCEPTION"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1000,
        rob_idx=11,
        lq_idx=4,
        sq_idx=0,
        pc=0x1000,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x3000,
        tlb_pf_ld=True,
        dcache_data=0x1122334455667788,
        hold_cycles=1,
        max_cycles=1,
    )
    pf_result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=12)
    pf_bits = _scalar_exception_bits(pf_result)

    assert "13" in pf_bits, f"TLB page fault 应映射到异常位 13，实际为 {sorted(pf_bits)}"
    assert pf_result["scalar_writeback"]["uop"]["rfWen"] == 0, "异常写回应关闭整数寄存器写使能"
    assert pf_result["scalar_writeback"]["uop"]["robIdx"]["value"] == 11
    assert pf_result["feedback_slow"] is not None, "异常写回仍需携带后端慢反馈"

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1800,
        rob_idx=12,
        lq_idx=5,
        sq_idx=0,
        pc=0x1800,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x3800,
        pmp_ld=True,
        dcache_data=0x8877665544332211,
        hold_cycles=3,
        max_cycles=3,
    )
    pmp_result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=12)
    pmp_bits = _scalar_exception_bits(pmp_result)

    assert "5" in pmp_bits, f"PMP load fault 应映射到异常位 5，实际为 {sorted(pmp_bits)}"
    assert pmp_result["scalar_writeback"]["uop"]["rfWen"] == 0
    assert pmp_result["scalar_writeback"]["uop"]["robIdx"]["value"] == 12


def test_loadunit_multi_exception_priority_resolution(env):
    """多种地址异常并存时，高优先级异常不应被低优先级异常吞掉。"""
    env.dut.fc_cover["FG-EXCEPTION-CONTROL"].mark_function(
        "FC-TLB-PMP-EXCEPTION-MERGE",
        test_loadunit_multi_exception_priority_resolution,
        ["CK-MULTI-EXCEPTION-PRIORITY"],
    )

    # 顶层端口没有暴露“折叠后的单一异常编码”，因此这里使用可观测代理：
    # 高优先级的 page fault 在与低优先级 PMP access fault 并存时必须仍然保留下来，
    # 且最终必须走异常写回路径而非普通数据提交路径。
    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1C00,
        rob_idx=13,
        lq_idx=6,
        sq_idx=0,
        pc=0x1C00,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x3C00,
        tlb_pf_ld=True,
        pmp_ld=True,
        dcache_data=0xCAFEBABECAFED00D,
        hold_cycles=3,
        max_cycles=3,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=12)
    exc_bits = _scalar_exception_bits(result)

    assert "13" in exc_bits, f"高优先级 page fault 不应在异常合并中丢失，实际为 {sorted(exc_bits)}"
    assert result["scalar_writeback"]["uop"]["rfWen"] == 0
    assert result["scalar_writeback"]["uop"]["robIdx"]["value"] == 13
    assert result["feedback_slow"] is not None


def test_loadunit_dcache_denied_error_propagation(env):
    """DCache denied 错误应传播为 load access fault。"""
    env.dut.fc_cover["FG-EXCEPTION-CONTROL"].mark_function(
        "FC-DCACHE-TL-ERROR-PROPAGATION",
        test_loadunit_dcache_denied_error_propagation,
        ["CK-DENIED-PROPAGATION"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x2000,
        rob_idx=21,
        lq_idx=7,
        sq_idx=0,
        pc=0x2000,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x4000,
        dcache_data=0x0123456789ABCDEF,
        dcache_denied=True,
        hold_cycles=3,
        max_cycles=3,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=12)
    exc_bits = _scalar_exception_bits(result)

    assert "5" in exc_bits, f"denied 应传播为 access fault 位 5，实际为 {sorted(exc_bits)}"
    assert "19" not in exc_bits, "denied 不应同时被错误编码为 hardware error"
    assert result["scalar_writeback"]["uop"]["rfWen"] == 0
    assert result["scalar_writeback"]["debug"]["paddr"] == 0x4000
    assert result["feedback_slow"] is not None


def test_loadunit_dcache_corrupt_error_propagation(env):
    """DCache corrupt 错误应传播为 hardware error。"""
    env.dut.fc_cover["FG-EXCEPTION-CONTROL"].mark_function(
        "FC-DCACHE-TL-ERROR-PROPAGATION",
        test_loadunit_dcache_corrupt_error_propagation,
        ["CK-CORRUPT-PROPAGATION"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x2400,
        rob_idx=22,
        lq_idx=8,
        sq_idx=0,
        pc=0x2400,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x4400,
        dcache_data=0xFEDCBA9876543210,
        dcache_corrupt=True,
        hold_cycles=3,
        max_cycles=3,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=12)
    exc_bits = _scalar_exception_bits(result)

    assert "19" in exc_bits, f"corrupt 应传播为 hardware error 位 19，实际为 {sorted(exc_bits)}"
    assert "5" not in exc_bits, "纯 corrupt 场景不应被误标成 access fault"
    assert result["scalar_writeback"]["uop"]["rfWen"] == 0
    assert result["scalar_writeback"]["debug"]["paddr"] == 0x4400
    assert result["feedback_slow"] is not None


def test_loadunit_normal_wakeup_generation(env):
    """普通标量 load 在 stage 0 发射成功后应立即产生唤醒。"""
    env.dut.fc_cover["FG-EXCEPTION-CONTROL"].mark_function(
        "FC-WAKEUP-GENERATION",
        test_loadunit_normal_wakeup_generation,
        ["CK-NORMAL-WAKEUP"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x2800,
        rob_idx=31,
        lq_idx=9,
        sq_idx=0,
        pc=0x2800,
        max_cycles=12,
    )

    assert issue["accepted"] is True
    assert env.wakeup.valid.value == 1, "普通标量 load 在发射拍应产生 wakeup"
    assert env.wakeup.bits.robIdx.value.value == 31
    assert env.scalar_resp.valid.value == 0, "stage 0 wakeup 不应等到最终写回"
    assert env.feedback_slow.valid.value == 0

    env.Step(1)
    assert env.wakeup.valid.value == 0, "普通 wakeup 应是单拍脉冲"

    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x4800,
        dcache_data=0xA5A55A5A11223344,
        hold_cycles=1,
        max_cycles=1,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=12)

    assert result["scalar_writeback"] is not None
    assert result["feedback_slow"] is not None
    assert result["scalar_writeback"]["uop"]["robIdx"]["value"] == 31


def test_loadunit_mmio_wakeup_generation(env):
    """MMIO/uncache load 应在最终写回前先产生早唤醒。"""
    env.dut.fc_cover["FG-EXCEPTION-CONTROL"].mark_function(
        "FC-WAKEUP-GENERATION",
        test_loadunit_mmio_wakeup_generation,
        ["CK-MMIO-WAKEUP"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_mmio_load(
        env,
        rob_idx=41,
        lq_idx=10,
        sq_idx=0,
        pc=0x2C00,
        pdest=3,
        pmp_mmio_hint=True,
        max_cycles=12,
    )

    assert issue["accepted"] is True
    assert env.wakeup.valid.value == 1, "MMIO/uncache load 应在发射完成后立即唤醒消费者"
    assert env.wakeup.bits.robIdx.value.value == 41
    assert env.scalar_resp.valid.value == 0, "MMIO 早唤醒不应等到 stage 3 写回"
    assert env.feedback_slow.valid.value == 0, "MMIO 唤醒不应误走普通慢反馈路径"

    env.Step(1)
    assert env.wakeup.valid.value == 0, "MMIO wakeup 也应表现为单拍脉冲"
    assert env.scalar_resp.valid.value == 0, "wakeup 脉冲结束后仍不应立刻写回"

    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=8)
    assert result["scalar_writeback"] is not None, "MMIO/uncache 路径后续仍应产生最终写回"
    assert result["feedback_slow"] is None, "MMIO load 只负责唤醒消费者，不应额外产生普通慢反馈"
    assert result["scalar_writeback"]["uop"]["robIdx"]["value"] == 41
    assert result["wait_cycles"] >= 1, "MMIO 写回应晚于早唤醒出现"


def test_loadunit_stage2_fast_feedback_generation(env):
    """生成 wrapper 未暴露 feedback_fast 时，使用最早可见控制输出代理验证快反馈。"""
    env.dut.fc_cover["FG-EXCEPTION-CONTROL"].mark_function(
        "FC-FEEDBACK-FAST-SLOW",
        test_loadunit_stage2_fast_feedback_generation,
        ["CK-STAGE2-FAST-FEEDBACK"],
    )

    # 当前生成的 top wrapper 没有暴露 io_feedback_fast / io_fast_uop，因此采用与覆盖模型一致的
    # 可观测代理：stage 0/2 最早可见的 wakeup 必须先于 stage 3 feedback_slow 出现。
    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x3000,
        rob_idx=51,
        lq_idx=11,
        sq_idx=0,
        pc=0x3000,
        max_cycles=12,
    )

    assert env.wakeup.valid.value == 1, "最早可见快反馈代理应在请求发射后立即出现"
    assert env.feedback_slow.valid.value == 0, "stage 2 快反馈代理出现时不应已经进入慢反馈"
    assert env.wakeup.bits.robIdx.value.value == 51

    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x5000,
        dcache_data=0xDEADBEEF00001111,
        hold_cycles=1,
        max_cycles=1,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=12)

    assert result["feedback_slow"] is not None, "普通命中路径最终仍需在 stage 3 给出慢反馈"
    assert result["feedback_slow"]["robIdx"]["value"] == 51
    assert result["wait_cycles"] >= 1, "慢反馈不应与最早可见快反馈代理同拍出现"


def test_loadunit_stage3_slow_feedback_generation(env):
    """普通标量命中应在 stage 3 产生 slow feedback。"""
    env.dut.fc_cover["FG-EXCEPTION-CONTROL"].mark_function(
        "FC-FEEDBACK-FAST-SLOW",
        test_loadunit_stage3_slow_feedback_generation,
        ["CK-STAGE3-SLOW-FEEDBACK"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x3400,
        rob_idx=52,
        lq_idx=12,
        sq_idx=0,
        pc=0x3400,
        max_cycles=12,
    )
    env.Step(1)
    assert env.feedback_slow.valid.value == 0, "未到 stage 3 前不应出现慢反馈"

    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x5400,
        dcache_data=0x123456789ABCDEF0,
        hold_cycles=1,
        max_cycles=1,
    )
    assert env.feedback_slow.valid.value == 0, "响应注入完成当拍不应把慢反馈提前到 stage 2"

    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=12)
    assert result["feedback_slow"] is not None
    assert result["scalar_writeback"] is not None
    assert result["feedback_slow"]["robIdx"]["value"] == 52
    assert result["feedback_slow"]["lqIdx"]["value"] == 12
    assert result["scalar_writeback"]["uop"]["robIdx"]["value"] == 52
    assert result["wait_cycles"] >= 1


def test_loadunit_ldld_violation_rollback(env):
    """ld-ld 违例应触发 rollback，且不应继续正常写回。"""
    env.dut.fc_cover["FG-EXCEPTION-CONTROL"].mark_function(
        "FC-ROLLBACK-REDIRECT",
        test_loadunit_ldld_violation_rollback,
        ["CK-LDLD-ROLLBACK"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x3800,
        rob_idx=61,
        lq_idx=13,
        sq_idx=0,
        pc=0x3800,
        max_cycles=12,
    )
    # send_scalar_load 会恢复默认输入，因此依赖 CSR 的控制位必须在请求发射后重新配置。
    env.csr_ctrl.ldld_vio_check_enable.value = 1
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x5800,
        dcache_data=0x0102030405060708,
        hold_cycles=1,
        max_cycles=1,
    )

    env.lsq.ldld_nuke_query.resp.valid.value = 1
    env.lsq.ldld_nuke_query.resp.bits_rep_frm_fetch.value = 1
    rollback_seen = False
    rollback_rob = None
    scalar_writeback_seen = False
    feedback_slow_seen = False
    for _ in range(6):
        if env.rollback.valid.value:
            rollback_seen = True
            rollback_rob = env.rollback.bits.robIdx.value.value
        scalar_writeback_seen |= bool(env.scalar_resp.valid.value)
        feedback_slow_seen |= bool(env.feedback_slow.valid.value)
        env.Step(1)
    env.lsq.ldld_nuke_query.resp.valid.value = 0
    env.lsq.ldld_nuke_query.resp.bits_rep_frm_fetch.value = 0

    assert rollback_seen, "ld-ld violation 命中后必须产生 rollback"
    assert rollback_rob == 61, f"rollback 应指向当前 load 的 ROB=61，实际为 {rollback_rob}"
    assert not scalar_writeback_seen, "ld-ld rollback 期间不应继续沿正常 ldout 路径写回"
    assert not feedback_slow_seen, "ld-ld rollback 期间不应继续向 RS 发送普通 slow feedback"


def test_loadunit_stld_violation_redirect(env):
    """st-ld 违例应触发可见重定向代理，并抑制正常写回。"""
    env.dut.fc_cover["FG-EXCEPTION-CONTROL"].mark_function(
        "FC-ROLLBACK-REDIRECT",
        test_loadunit_stld_violation_redirect,
        ["CK-STLD-REDIRECT"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x3C00,
        rob_idx=71,
        lq_idx=14,
        sq_idx=0,
        pc=0x3C00,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x5C00,
        dcache_data=0x0F0E0D0C0B0A0908,
        hold_cycles=1,
        max_cycles=1,
    )

    assert env.ld_cancel_ld2 is not None, "当前 wrapper 应暴露 io_ldCancel_ld2Cancel 作为可见重定向代理"
    ld_cancel_seen = False
    scalar_writeback_seen = False
    feedback_slow_seen = False
    for _ in range(6):
        env.stld_nuke_query["0"].valid.value = 1
        env.stld_nuke_query["0"].bits.matchType.value = 0
        env.stld_nuke_query["0"].bits.paddr.value = 0x5C00
        env.stld_nuke_query["0"].bits.mask.value = 0xFF
        env.stld_nuke_query["0"].bits.robIdx.flag.value = 1
        env.stld_nuke_query["0"].bits.robIdx.value.value = 1
        ld_cancel_seen |= bool(env.ld_cancel_ld2.value)
        scalar_writeback_seen |= bool(env.scalar_resp.valid.value)
        feedback_slow_seen |= bool(env.feedback_slow.valid.value)
        env.Step(1)
    env.stld_nuke_query["0"].valid.value = 0

    assert ld_cancel_seen, "st-ld violation 应拉起 ldCancel 作为重定向/取消代理信号"
    assert not scalar_writeback_seen, "st-ld violation 期间不应继续正常 ldout 写回"
    assert not feedback_slow_seen, "st-ld violation 期间不应继续发送普通 slow feedback"
