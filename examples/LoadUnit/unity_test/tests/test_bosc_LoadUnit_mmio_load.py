#coding=utf-8

from bosc_LoadUnit_api import *


def _capture_mmio_history(env, cycles: int):
    history = []
    for cycle in range(cycles):
        writeback = env.scalar_resp.bits.as_dict() if env.scalar_resp.valid.value else None
        history.append(
            {
                "cycle": cycle,
                "wakeup_valid": int(env.wakeup.valid.value),
                "feedback_valid": int(env.feedback_slow.valid.value),
                "ldout_valid": int(env.scalar_resp.valid.value),
                "rob_idx": None if writeback is None else writeback["uop"]["robIdx"]["value"],
                "debug": None if writeback is None else writeback["debug"],
            }
        )
        env.Step(1)
    return history


def _first_mmio_writeback(history):
    for sample in history:
        if sample["ldout_valid"]:
            return sample
    return None


def test_loadunit_mmio_stage0_early_wakeup(env):
    """MMIO/uncache load 在发射完成拍应先产生早唤醒。"""
    env.dut.fc_cover["FG-MMIO-LOAD"].mark_function(
        "FC-MMIO-EARLY-WAKEUP",
        test_loadunit_mmio_stage0_early_wakeup,
        ["CK-S0-WAKEUP"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_mmio_load(
        env,
        rob_idx=51,
        lq_idx=11,
        sq_idx=0,
        pc=0x3000,
        pdest=5,
        pmp_mmio_hint=True,
        max_cycles=12,
    )

    assert issue["accepted"] is True
    assert env.wakeup.valid.value == 1, "MMIO 请求发射完成拍应立即产生 wakeup"
    assert env.wakeup.bits.robIdx.value.value == 51
    assert env.scalar_resp.valid.value == 0, "早唤醒拍不应提前出现最终写回"
    assert env.feedback_slow.valid.value == 0, "MMIO 早唤醒不应误走普通慢反馈"


def test_loadunit_mmio_no_data_writeback_before_stage3(env):
    """MMIO 提前唤醒后，stage 3 之前不应出现最终数据写回。"""
    env.dut.fc_cover["FG-MMIO-LOAD"].mark_function(
        "FC-MMIO-EARLY-WAKEUP",
        test_loadunit_mmio_no_data_writeback_before_stage3,
        ["CK-NO-DATA-BEFORE-S3"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_mmio_load(
        env,
        rob_idx=52,
        lq_idx=12,
        sq_idx=0,
        pc=0x3040,
        pdest=6,
        pmp_mmio_hint=True,
        max_cycles=12,
    )
    history = _capture_mmio_history(env, cycles=4)

    assert history[0]["wakeup_valid"] == 1, "MMIO 场景应先出现 wakeup"
    assert history[0]["ldout_valid"] == 0
    assert history[1]["ldout_valid"] == 0, "stage 3 之前不应出现 ldout 写回"
    assert any(sample["ldout_valid"] for sample in history[2:]), "后续应在 stage 3 窗口看到最终写回"


def test_loadunit_mmio_writeback_happens_in_stage3(env):
    """MMIO 最终写回应晚于早唤醒，并出现在 stage 3 对应窗口。"""
    env.dut.fc_cover["FG-MMIO-LOAD"].mark_function(
        "FC-MMIO-S3-WRITEBACK",
        test_loadunit_mmio_writeback_happens_in_stage3,
        ["CK-MMIO-WRITEBACK-TIMING"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_mmio_load(
        env,
        rob_idx=53,
        lq_idx=13,
        sq_idx=0,
        pc=0x3080,
        pdest=7,
        pmp_mmio_hint=True,
        max_cycles=12,
    )
    history = _capture_mmio_history(env, cycles=6)
    writeback_cycles = [sample["cycle"] for sample in history if sample["ldout_valid"]]

    assert history[0]["wakeup_valid"] == 1, "MMIO 写回场景也应先出现早唤醒"
    assert writeback_cycles, "MMIO 路径最终必须产生 ldout 写回"
    assert writeback_cycles[0] >= 2, "最终写回应晚于 stage 0/1/2 的早期控制窗口"
    assert all(not sample["ldout_valid"] for sample in history[:2]), "前两拍不应提前写回"
    assert _first_mmio_writeback(history)["rob_idx"] == 53
    assert not any(sample["feedback_valid"] for sample in history), "MMIO 写回不应混入普通慢反馈"


def test_loadunit_mmio_writeback_debug_flags(env):
    """MMIO 最终写回应携带正确的 MMIO 调试标志。"""
    env.dut.fc_cover["FG-MMIO-LOAD"].mark_function(
        "FC-MMIO-S3-WRITEBACK",
        test_loadunit_mmio_writeback_debug_flags,
        ["CK-MMIO-DEBUG-FLAGS"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x3400,
        fu_op_type=3,
        rob_idx=61,
        lq_idx=14,
        sq_idx=0,
        pc=0x3400,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x5400,
        dcache_data=0x0123456789ABCDEF,
        hold_cycles=2,
        max_cycles=2,
    )
    scalar_result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=8)
    assert scalar_result["scalar_writeback"]["debug"]["isMMIO"] == 0, "普通标量 load 不应误带 MMIO 调试标志"

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_mmio_load(
        env,
        rob_idx=62,
        lq_idx=15,
        sq_idx=0,
        pc=0x3480,
        pdest=8,
        pmp_mmio_hint=True,
        max_cycles=12,
    )
    history = _capture_mmio_history(env, cycles=6)
    writeback = _first_mmio_writeback(history)

    assert writeback is not None, "MMIO 场景应观察到最终写回"
    assert writeback["debug"]["isMMIO"] == 1, "MMIO 最终写回应显式标记 debug.isMMIO=1"
