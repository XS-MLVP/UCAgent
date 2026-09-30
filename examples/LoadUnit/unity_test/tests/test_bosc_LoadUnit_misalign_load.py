#coding=utf-8

from bosc_LoadUnit_api import *


MISALIGN_DATA_64 = 0x0123456789ABCDEF
MISALIGN_NO_CROSS_ADDR = 0x1003
MISALIGN_CROSS_16B_ADDR = 0x100F


def _enable_scalar_misalign_path(env):
    env.csr_ctrl.hd_misalign_ld_enable.value = 1
    if env.misalign_allow_spec is not None:
        env.misalign_allow_spec.value = 1


def test_loadunit_misalign_detect_and_enqueue(env):
    """跨 16B 边界的标量 misalign 请求应被识别并送入 MisalignBuffer。"""
    env.dut.fc_cover["FG-MISALIGN-LOAD"].mark_function(
        "FC-MISALIGN-DETECT-ENQUEUE",
        test_loadunit_misalign_detect_and_enqueue,
        ["CK-DETECT-AND-ENQ"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=MISALIGN_CROSS_16B_ADDR,
        fu_op_type=3,
        rob_idx=5,
        lq_idx=2,
        sq_idx=0,
        pc=0x1000,
        max_cycles=12,
    )
    _enable_scalar_misalign_path(env)
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x200F,
        dcache_data=MISALIGN_DATA_64,
        hold_cycles=2,
        max_cycles=2,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=6)

    assert result["misalign_enq"] is not None
    assert result["misalign_enq"]["paddr"] == 0x200F
    assert result["misalign_enq"]["mask"] != 0
    assert result["scalar_writeback"] is None


def test_loadunit_aligned_request_does_not_enqueue_misalign(env):
    """完全对齐的标量 load 不应误入 MisalignBuffer。"""
    env.dut.fc_cover["FG-MISALIGN-LOAD"].mark_function(
        "FC-MISALIGN-DETECT-ENQUEUE",
        test_loadunit_aligned_request_does_not_enqueue_misalign,
        ["CK-NON-MISALIGN-NO-ENQ"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1000,
        fu_op_type=3,
        rob_idx=6,
        lq_idx=3,
        sq_idx=0,
        pc=0x1000,
        max_cycles=12,
    )
    _enable_scalar_misalign_path(env)
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x2000,
        dcache_data=MISALIGN_DATA_64,
        hold_cycles=2,
        max_cycles=2,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=6)

    assert result["misalign_enq"] is None
    assert result["scalar_writeback"] is not None
    assert result["scalar_writeback"]["debug"]["vaddr"] == 0x1000


def test_loadunit_misalign_first_split_success_response(env):
    """来自 MisalignBuffer 的第一条子请求命中后，应返回成功响应。"""
    env.dut.fc_cover["FG-MISALIGN-LOAD"].mark_function(
        "FC-MISALIGN-FIRST-SPLIT-RESP",
        test_loadunit_misalign_first_split_success_response,
        ["CK-FIRST-SPLIT-SUCCESS"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_misalign_buffer_load(
        env,
        vaddr=0x1000,
        mask=0x0F,
        rob_idx=7,
        lq_idx=4,
        sq_idx=0,
        pc=0x1000,
        fu_op_type=3,
        is_final_split=False,
        misalign_need_wakeup=False,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x2000,
        dcache_data=MISALIGN_DATA_64,
        hold_cycles=2,
        max_cycles=2,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=6)

    assert result["misalign_ldout"] is not None
    assert not any(result["misalign_ldout"]["rep_info_cause"].values())
    assert result["misalign_ldout"]["uop"]["robIdx"]["value"] == 7
    assert result["scalar_writeback"] is None


def test_loadunit_misalign_first_split_replay_response(env):
    """第一条子请求 miss 后，应通过 MisalignBuffer 路径返回 replay。"""
    env.dut.fc_cover["FG-MISALIGN-LOAD"].mark_function(
        "FC-MISALIGN-FIRST-SPLIT-RESP",
        test_loadunit_misalign_first_split_replay_response,
        ["CK-FIRST-SPLIT-REPLAY"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_misalign_buffer_load(
        env,
        vaddr=0x1000,
        mask=0x0F,
        rob_idx=8,
        lq_idx=5,
        sq_idx=0,
        pc=0x1000,
        fu_op_type=3,
        is_final_split=False,
        misalign_need_wakeup=False,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x2000,
        dcache_data=MISALIGN_DATA_64,
        dcache_miss=True,
        hold_cycles=2,
        max_cycles=2,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=6)

    assert result["misalign_ldout"] is not None
    assert any(result["misalign_ldout"]["rep_info_cause"].values())
    assert result["ld_cancel_ld2"] == 1
    assert result["scalar_writeback"] is None


def test_loadunit_misalign_second_split_success_response(env):
    """来自 MisalignBuffer 的第二条子请求命中后，应返回 final split 成功响应。"""
    env.dut.fc_cover["FG-MISALIGN-LOAD"].mark_function(
        "FC-MISALIGN-SECOND-SPLIT-RESP",
        test_loadunit_misalign_second_split_success_response,
        ["CK-SECOND-SPLIT-SUCCESS"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_misalign_buffer_load(
        env,
        vaddr=0x1008,
        mask=0xF0,
        rob_idx=11,
        lq_idx=8,
        sq_idx=0,
        pc=0x1008,
        fu_op_type=3,
        is_final_split=True,
        misalign_need_wakeup=False,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x2008,
        dcache_data=MISALIGN_DATA_64,
        hold_cycles=2,
        max_cycles=2,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=6)

    assert result["misalign_ldout"] is not None
    assert result["misalign_ldout"]["misalignNeedWakeUp"] == 0
    assert not any(result["misalign_ldout"]["rep_info_cause"].values())
    assert result["misalign_ldout"]["uop"]["robIdx"]["value"] == 11
    assert result["scalar_writeback"] is None


def test_loadunit_misalign_second_split_replay_response(env):
    """第二条拆分子请求 miss 后，应继续通过 MisalignBuffer 路径返回 replay。"""
    env.dut.fc_cover["FG-MISALIGN-LOAD"].mark_function(
        "FC-MISALIGN-SECOND-SPLIT-RESP",
        test_loadunit_misalign_second_split_replay_response,
        ["CK-SECOND-SPLIT-REPLAY"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_misalign_buffer_load(
        env,
        vaddr=0x1008,
        mask=0xF0,
        rob_idx=12,
        lq_idx=9,
        sq_idx=0,
        pc=0x1008,
        fu_op_type=3,
        is_final_split=True,
        misalign_need_wakeup=False,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x2008,
        dcache_data=MISALIGN_DATA_64,
        dcache_miss=True,
        hold_cycles=2,
        max_cycles=2,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=6)

    assert result["misalign_ldout"] is not None
    assert any(result["misalign_ldout"]["rep_info_cause"].values())
    assert result["ld_cancel_ld2"] == 1
    assert result["scalar_writeback"] is None


def test_loadunit_misalign_wakeup_when_needed(env):
    """misalignNeedWakeUp=1 时，应走直接写回/唤醒语义而非 replay。"""
    env.dut.fc_cover["FG-MISALIGN-LOAD"].mark_function(
        "FC-MISALIGN-WAKEUP-OR-REPLAY",
        test_loadunit_misalign_wakeup_when_needed,
        ["CK-WAKEUP-WHEN-NEEDED"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_misalign_buffer_load(
        env,
        vaddr=0x1010,
        mask=0xF0,
        rob_idx=9,
        lq_idx=6,
        sq_idx=0,
        pc=0x1010,
        fu_op_type=3,
        is_final_split=True,
        misalign_need_wakeup=True,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x2010,
        dcache_data=MISALIGN_DATA_64,
        hold_cycles=2,
        max_cycles=2,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=6)

    assert result["misalign_ldout"] is not None or result["wakeup"] is not None
    if result["misalign_ldout"] is not None:
        assert result["misalign_ldout"]["misalignNeedWakeUp"] == 1
        assert not any(result["misalign_ldout"]["rep_info_cause"].values())
    assert result["scalar_writeback"] is None


def test_loadunit_misalign_replay_when_not_woken(env):
    """misalignNeedWakeUp=0 且子请求失败时，应继续通过 MisalignBuffer replay。"""
    env.dut.fc_cover["FG-MISALIGN-LOAD"].mark_function(
        "FC-MISALIGN-WAKEUP-OR-REPLAY",
        test_loadunit_misalign_replay_when_not_woken,
        ["CK-REPLAY-WHEN-NOT-WOKEN"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_misalign_buffer_load(
        env,
        vaddr=0x1010,
        mask=0xF0,
        rob_idx=10,
        lq_idx=7,
        sq_idx=0,
        pc=0x1010,
        fu_op_type=3,
        is_final_split=True,
        misalign_need_wakeup=False,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x2010,
        dcache_data=MISALIGN_DATA_64,
        dcache_miss=True,
        hold_cycles=2,
        max_cycles=2,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=6)

    assert result["misalign_ldout"] is not None
    assert any(result["misalign_ldout"]["rep_info_cause"].values())
    assert result["wakeup"] is None
    assert result["scalar_writeback"] is None


def test_loadunit_misalign_no_cross_16b_boundary_path(env):
    """不跨 16B 边界的 misalign 首次请求应进入普通 MisalignBuffer 分支。"""
    env.dut.fc_cover["FG-MISALIGN-LOAD"].mark_function(
        "FC-MISALIGN-BOUNDARY-HANDLING",
        test_loadunit_misalign_no_cross_16b_boundary_path,
        ["CK-NO-CROSS-16B"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=MISALIGN_NO_CROSS_ADDR,
        fu_op_type=3,
        rob_idx=11,
        lq_idx=8,
        sq_idx=0,
        pc=0x1000,
        max_cycles=12,
    )
    _enable_scalar_misalign_path(env)
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x2003,
        dcache_data=MISALIGN_DATA_64,
        hold_cycles=2,
        max_cycles=2,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=6)

    assert result["misalign_enq"] is not None, "README 要求不跨 16B 的首次 misalign 请求进入 MisalignBuffer"
    assert result["scalar_writeback"] is None, "进入 MisalignBuffer 前不应沿普通标量写回路径直接提交"


def test_loadunit_misalign_cross_16b_boundary_path(env):
    """跨 16B 边界的 misalign 请求应走专用边界处理分支。"""
    env.dut.fc_cover["FG-MISALIGN-LOAD"].mark_function(
        "FC-MISALIGN-BOUNDARY-HANDLING",
        test_loadunit_misalign_cross_16b_boundary_path,
        ["CK-CROSS-16B-PATH"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=MISALIGN_CROSS_16B_ADDR,
        fu_op_type=3,
        rob_idx=12,
        lq_idx=9,
        sq_idx=0,
        pc=0x1000,
        max_cycles=12,
    )
    _enable_scalar_misalign_path(env)
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x200F,
        dcache_data=MISALIGN_DATA_64,
        hold_cycles=2,
        max_cycles=2,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=6)

    assert result["misalign_enq"] is not None
    assert result["misalign_enq"]["mask"] & 0xFF00 != 0
    assert result["misalign_enq"]["paddr"] & 0xF != 0
    assert result["scalar_writeback"] is None
