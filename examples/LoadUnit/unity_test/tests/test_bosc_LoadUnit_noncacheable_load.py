#coding=utf-8

from bosc_LoadUnit_api import *


NC_DATA_128 = 0xFFEEDDCCBBAA99887766554433221100
NC_LOW64 = 0x7766554433221100


def _capture_nc_history(env, cycles: int):
    history = []
    for cycle in range(cycles):
        writeback = env.scalar_resp.bits.as_dict() if env.scalar_resp.valid.value else None
        history.append(
            {
                "cycle": cycle,
                "tlb_req_valid": int(env.tlb.req.valid.value),
                "dcache_req_valid": int(env.dcache.req.valid.value),
                "wakeup_valid": int(env.wakeup.valid.value),
                "ubuffer_valid": int(env.ubuffer.valid.value),
                "forward_query_valid": int(env.lsq.forward.valid.value),
                "ldld_query_valid": int(env.lsq.ldld_nuke_query.req.valid.value),
                "stld_query_valid": int(env.lsq.stld_nuke_query.req.valid.value),
                "feedback_valid": int(env.feedback_slow.valid.value),
                "cancel_ld2": int(env.ld_cancel_ld2.value) if env.ld_cancel_ld2 is not None else 0,
                "rollback_valid": int(env.rollback.valid.value),
                "misalign_enq_valid": int(env.misalign.enq_req.valid.value),
                "misalign_ldout_valid": int(env.misalign.ldout.valid.value),
                "ldout_valid": int(env.scalar_resp.valid.value),
                "writeback": writeback,
            }
        )
        env.Step(1)
    return history


def _drive_nc_addr_invalid_on_forward_query(env, sq_idx: int = 1, hold_cycles: int = 2, max_wait_cycles: int = 6):
    for _ in range(max_wait_cycles):
        if env.lsq.forward.valid.value:
            for _ in range(hold_cycles):
                env.lsq.forward.addrInvalid.value = 1
                env.lsq.forward.addrInvalidSqIdx.flag.value = 1
                env.lsq.forward.addrInvalidSqIdx.value.value = int(sq_idx)
                env.Step(1)
            env.lsq.forward.addrInvalid.value = 0
            env.lsq.forward.addrInvalidSqIdx.flag.value = 0
            env.lsq.forward.addrInvalidSqIdx.value.value = 0
            return True
        env.Step(1)
    return False


def _first_nc_writeback(history):
    for sample in history:
        if sample["ldout_valid"]:
            return sample["writeback"]
    return None


def _capture_scalar_history(env, cycles: int):
    history = []
    for cycle in range(cycles):
        writeback = env.scalar_resp.bits.as_dict() if env.scalar_resp.valid.value else None
        history.append(
            {
                "cycle": cycle,
                "tlb_req_valid": int(env.tlb.req.valid.value),
                "dcache_req_valid": int(env.dcache.req.valid.value),
                "wakeup_valid": int(env.wakeup.valid.value),
                "ubuffer_valid": int(env.ubuffer.valid.value),
                "forward_query_valid": int(env.lsq.forward.valid.value),
                "ldld_query_valid": int(env.lsq.ldld_nuke_query.req.valid.value),
                "stld_query_valid": int(env.lsq.stld_nuke_query.req.valid.value),
                "feedback_valid": int(env.feedback_slow.valid.value),
                "ldout_valid": int(env.scalar_resp.valid.value),
                "writeback": writeback,
            }
        )
        env.Step(1)
    return history


def _drive_nc_forward_data_on_query(env, forward_data: int, forward_source: str = "ubuffer", forward_mask: int = 0x00FF):
    for _ in range(6):
        if env.ubuffer.valid.value or env.lsq.forward.valid.value:
            if forward_source == "ubuffer":
                for idx in range(16):
                    getattr(env.ubuffer.forwardData, str(idx)).value = (int(forward_data) >> (idx * 8)) & 0xFF
                    getattr(env.ubuffer.forwardMask, str(idx)).value = (int(forward_mask) >> idx) & 0x1
                env.ubuffer.matchInvalid.value = 0
            else:
                for idx in range(16):
                    getattr(env.lsq.forward.forwardData, str(idx)).value = (int(forward_data) >> (idx * 8)) & 0xFF
                    getattr(env.lsq.forward.forwardMask, str(idx)).value = (int(forward_mask) >> idx) & 0x1
                env.lsq.forward.dataInvalid.value = 0
                env.lsq.forward.addrInvalid.value = 0
                env.lsq.forward.matchInvalid.value = 0
            return True
        env.Step(1)
    return False


def test_loadunit_nc_attribute_detect_first_pass(env):
    """NC 属性首次识别模板。"""
    env.dut.fc_cover["FG-NONCACHEABLE-LOAD"].mark_function(
        "FC-NC-ATTRIBUTE-DETECT",
        test_loadunit_nc_attribute_detect_first_pass,
        ["CK-FIRST-PASS-DETECT"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_nc_load(
        env,
        vaddr=0x1100,
        paddr=0x4100,
        data=NC_DATA_128,
        fu_op_type=3,
        rob_idx=75,
        lq_idx=25,
        sq_idx=1,
        pc=0x1100,
        store_set_hit=1,
        max_cycles=12,
    )
    history = _capture_nc_history(env, cycles=6)

    assert issue["accepted"] is True
    assert history[0]["wakeup_valid"] == 1, "NC 第二次上流水应先出现 stage 0 早唤醒"
    assert all(sample["tlb_req_valid"] == 0 for sample in history), "NC 专用路径不应重新发起 TLB 请求"
    assert all(sample["dcache_req_valid"] == 0 for sample in history), "NC 专用路径不应重新发起 DCache 请求"
    assert any(sample["ubuffer_valid"] or sample["forward_query_valid"] for sample in history), "NC 属性识别后应切入专用前递入口"
    assert _first_nc_writeback(history) is not None, "NC 正常场景最终仍应产生写回"


def test_loadunit_non_nc_request_does_not_double_pass(env):
    """非 NC 请求不误触发两次上流水模板。"""
    env.dut.fc_cover["FG-NONCACHEABLE-LOAD"].mark_function(
        "FC-NC-ATTRIBUTE-DETECT",
        test_loadunit_non_nc_request_does_not_double_pass,
        ["CK-NON-NC-NO-DOUBLE-PASS"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1200,
        fu_op_type=3,
        rob_idx=76,
        lq_idx=26,
        sq_idx=0,
        pc=0x1200,
        store_set_hit=0,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x5200,
        dcache_data=0x123456789ABCDEF0,
        hold_cycles=2,
        max_cycles=2,
    )
    history = _capture_scalar_history(env, cycles=6)
    writeback = _first_nc_writeback(history)

    assert issue["accepted"] is True
    assert writeback is not None, "普通标量 load 应按正常缓存路径完成写回"
    assert writeback["data"] == 0x123456789ABCDEF0
    assert any(sample["ldld_query_valid"] or sample["stld_query_valid"] for sample in history), "普通标量 load 仍应进入常规违例检查阶段"
    assert not any(sample["wakeup_valid"] for sample in history), "普通标量 load 不应误表现为 NC 第二次上流水的早唤醒"
    assert not any(sample["ubuffer_valid"] or sample["forward_query_valid"] for sample in history), "普通标量 load 不应误进入 NC 专用前递入口"


def test_loadunit_nc_second_pass_has_no_tlb_request(env):
    """NC 第二次上流水不再发 TLB 请求模板。"""
    env.dut.fc_cover["FG-NONCACHEABLE-LOAD"].mark_function(
        "FC-NC-BYPASS-TLB",
        test_loadunit_nc_second_pass_has_no_tlb_request,
        ["CK-NO-TLB-REQ-SECOND-PASS"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_nc_load(
        env,
        vaddr=0x1140,
        paddr=0x4140,
        data=NC_DATA_128,
        fu_op_type=3,
        rob_idx=77,
        lq_idx=27,
        sq_idx=1,
        pc=0x1140,
        store_set_hit=1,
        max_cycles=12,
    )
    history = _capture_nc_history(env, cycles=6)

    assert issue["accepted"] is True
    assert all(sample["tlb_req_valid"] == 0 for sample in history), "NC 第二次上流水应完全 bypass TLB"
    assert any(sample["ubuffer_valid"] or sample["forward_query_valid"] for sample in history), "NC 路径应继续推进到专用前递接口"
    assert any(sample["ldld_query_valid"] or sample["stld_query_valid"] for sample in history), "NC 路径后续仍应执行 RAR/RAW 查询"
    assert _first_nc_writeback(history) is not None, "NC bypass TLB 后仍应能够完成写回"


def test_loadunit_nc_path_entry_differs_from_normal_path(env):
    """NC 第二次上流水进入专用路径模板。"""
    env.dut.fc_cover["FG-NONCACHEABLE-LOAD"].mark_function(
        "FC-NC-BYPASS-TLB",
        test_loadunit_nc_path_entry_differs_from_normal_path,
        ["CK-NC-PATH-ENTER"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_nc_load(
        env,
        vaddr=0x1180,
        paddr=0x4180,
        data=NC_DATA_128,
        fu_op_type=3,
        rob_idx=78,
        lq_idx=28,
        sq_idx=1,
        pc=0x1180,
        store_set_hit=1,
        max_cycles=12,
    )
    nc_history = _capture_nc_history(env, cycles=6)

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1280,
        fu_op_type=3,
        rob_idx=79,
        lq_idx=29,
        sq_idx=0,
        pc=0x1280,
        store_set_hit=0,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x5280,
        dcache_data=0x0FEDCBA987654321,
        hold_cycles=2,
        max_cycles=2,
    )
    scalar_history = _capture_scalar_history(env, cycles=6)

    assert any(sample["ubuffer_valid"] or sample["forward_query_valid"] for sample in nc_history), "NC 路径应出现专用前递入口"
    assert not any(sample["ubuffer_valid"] or sample["forward_query_valid"] for sample in scalar_history), "普通标量路径不应出现 NC 专用前递入口"
    assert _first_nc_writeback(nc_history) is not None
    assert _first_nc_writeback(scalar_history) is not None


def test_loadunit_nc_contention_still_does_not_query_tlb(env):
    """NC 第二次上流水在竞争下仍不查询 TLB 模板。"""
    env.dut.fc_cover["FG-NONCACHEABLE-LOAD"].mark_function(
        "FC-NC-BYPASS-TLB",
        test_loadunit_nc_contention_still_does_not_query_tlb,
        ["CK-NC-NO-TLB-QUERY-WITH-CONTENTION"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_nc_load_with_scalar_contender(
        env,
        nc_vaddr=0x11C0,
        nc_paddr=0x41C0,
        nc_data=NC_DATA_128,
        scalar_src0=0x21C0,
        nc_fu_op_type=3,
        scalar_fu_op_type=3,
        nc_rob_idx=80,
        nc_lq_idx=30,
        nc_sq_idx=1,
        scalar_rob_idx=81,
        scalar_lq_idx=31,
        scalar_sq_idx=0,
        pc=0x11C0,
        max_cycles=8,
    )
    history = _capture_nc_history(env, cycles=4)

    assert issue["nc_accepted"] is True
    assert not any(sample["tlb_req_valid"] for sample in history), "NC 即使与低优先级标量请求同拍竞争，也不应错误拉起 TLB 查询"


def test_loadunit_nc_forward_success_uses_forwarded_data(env):
    """NC 前递成功模板。"""
    env.dut.fc_cover["FG-NONCACHEABLE-LOAD"].mark_function(
        "FC-NC-FORWARD-VIOLATION",
        test_loadunit_nc_forward_success_uses_forwarded_data,
        ["CK-NC-FORWARD-SUCCESS"],
    )

    forward_data = 0x112233445566778899AABBCCDDEEFF00

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_nc_load(
        env,
        vaddr=0x1300,
        paddr=0x4300,
        data=NC_DATA_128,
        fu_op_type=3,
        rob_idx=82,
        lq_idx=32,
        sq_idx=1,
        pc=0x1300,
        store_set_hit=1,
        max_cycles=12,
    )
    forward_seen = _drive_nc_forward_data_on_query(
        env,
        forward_data=forward_data,
        forward_source="ubuffer",
        forward_mask=0x00FF,
    )
    history = _capture_nc_history(env, cycles=6)
    writeback = _first_nc_writeback(history)

    assert issue["accepted"] is True
    assert forward_seen, "NC 前递成功场景应看到可驱动的前递查询窗口"
    assert writeback is not None, "前递成功后仍应完成最终写回"
    assert writeback["data"] == (forward_data & ((1 << 64) - 1)), "最终写回数据应来自前递结果而不是原始 NC 数据"
    assert writeback["data"] != NC_LOW64
    assert not any(sample["rollback_valid"] or sample["cancel_ld2"] for sample in history), "前递成功不应误触发 redirect/取消路径"


def test_loadunit_nc_forward_address_mismatch_control(env):
    """NC 前递地址不匹配时，应触发控制路径而不是继续正常写回。"""
    env.dut.fc_cover["FG-NONCACHEABLE-LOAD"].mark_function(
        "FC-NC-FORWARD-VIOLATION",
        test_loadunit_nc_forward_address_mismatch_control,
        ["CK-NC-ADDR-MISMATCH"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_nc_load(
        env,
        vaddr=0x1000,
        paddr=0x4000,
        data=NC_DATA_128,
        fu_op_type=3,
        rob_idx=71,
        lq_idx=21,
        sq_idx=1,
        pc=0x1000,
        store_set_hit=1,
        max_cycles=12,
    )
    forward_query_seen = _drive_nc_addr_invalid_on_forward_query(env, sq_idx=1)
    history = _capture_nc_history(env, cycles=6)

    assert issue["accepted"] is True
    assert forward_query_seen, "NC 路径应先向 forward 网络发起查询"
    assert any(sample["cancel_ld2"] or sample["feedback_valid"] for sample in history), "地址不匹配时应有可见控制反馈"
    assert not any(sample["ldout_valid"] for sample in history), "地址不匹配时不应继续正常写回"


def test_loadunit_nc_replay_on_rar_raw_full(env):
    """RAR 查询口被占满时，NC 请求应进入 replay/取消控制路径。"""
    env.dut.fc_cover["FG-NONCACHEABLE-LOAD"].mark_function(
        "FC-NC-REPLAY-ON-RAR-RAW-PRESSURE",
        test_loadunit_nc_replay_on_rar_raw_full,
        ["CK-RAR-RAW-FULL-REPLAY"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_nc_load(
        env,
        vaddr=0x1040,
        paddr=0x4040,
        data=NC_DATA_128,
        fu_op_type=3,
        rob_idx=72,
        lq_idx=22,
        sq_idx=1,
        pc=0x1040,
        store_set_hit=1,
        max_cycles=12,
    )
    env.lsq.ldld_nuke_query.req.ready.value = 0
    history = _capture_nc_history(env, cycles=8)

    assert issue["accepted"] is True
    assert any(sample["ldld_query_valid"] for sample in history), "RAR 口压力场景下应看到 ldld_nuke_query 请求"
    assert any(sample["cancel_ld2"] or sample["feedback_valid"] for sample in history), "RAR 口不可用时应进入 replay/取消路径"
    assert not any(sample["ldout_valid"] for sample in history), "RAR 口不可用时不应正常写回"


def test_loadunit_nc_replay_on_rar_raw_not_ready(env):
    """RAW 查询口未 ready 时，NC 请求应进入 replay/取消控制路径。"""
    env.dut.fc_cover["FG-NONCACHEABLE-LOAD"].mark_function(
        "FC-NC-REPLAY-ON-RAR-RAW-PRESSURE",
        test_loadunit_nc_replay_on_rar_raw_not_ready,
        ["CK-RAR-RAW-NOTREADY-REPLAY"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_nc_load(
        env,
        vaddr=0x1080,
        paddr=0x4080,
        data=NC_DATA_128,
        fu_op_type=3,
        rob_idx=73,
        lq_idx=23,
        sq_idx=1,
        pc=0x1080,
        store_set_hit=1,
        max_cycles=12,
    )
    env.lsq.stld_nuke_query.req.ready.value = 0
    history = _capture_nc_history(env, cycles=8)

    assert issue["accepted"] is True
    assert any(sample["stld_query_valid"] for sample in history), "RAW 口未 ready 场景下应看到 stld_nuke_query 请求"
    assert any(sample["cancel_ld2"] or sample["feedback_valid"] for sample in history), "RAW 口未 ready 时应进入 replay/取消路径"
    assert not any(sample["ldout_valid"] for sample in history), "RAW 口未 ready 时不应正常写回"


def test_loadunit_nc_writeback_data_path(env):
    """NC 正常完成时，最终写回数据应来自 NC 输入数据。"""
    env.dut.fc_cover["FG-NONCACHEABLE-LOAD"].mark_function(
        "FC-NC-LDOUT-WRITEBACK",
        test_loadunit_nc_writeback_data_path,
        ["CK-NC-WRITEBACK-DATA"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_nc_load(
        env,
        vaddr=0x10C0,
        paddr=0x40C0,
        data=NC_DATA_128,
        fu_op_type=3,
        rob_idx=74,
        lq_idx=24,
        sq_idx=1,
        pc=0x10C0,
        store_set_hit=1,
        max_cycles=12,
    )
    history = _capture_nc_history(env, cycles=8)
    writeback = _first_nc_writeback(history)

    assert issue["accepted"] is True
    assert writeback is not None, "NC 正常场景应产生最终写回"
    assert writeback["data"] == NC_LOW64
    assert writeback["uop"]["robIdx"]["value"] == 74
    assert writeback["uop"]["lqIdx"]["value"] == 24
    assert writeback["debug"]["vaddr"] == 0x10C0
    assert any(sample["feedback_valid"] for sample in history), "NC 正常完成仍应对后端给出慢反馈"


def test_loadunit_nc_writeback_has_no_spurious_redirect(env):
    """NC 正常写回不误触发 redirect 模板。"""
    env.dut.fc_cover["FG-NONCACHEABLE-LOAD"].mark_function(
        "FC-NC-LDOUT-WRITEBACK",
        test_loadunit_nc_writeback_has_no_spurious_redirect,
        ["CK-NC-NO-SPURIOUS-REDIRECT"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_nc_load(
        env,
        vaddr=0x10C0,
        paddr=0x40C0,
        data=NC_DATA_128,
        fu_op_type=3,
        rob_idx=83,
        lq_idx=33,
        sq_idx=1,
        pc=0x10C0,
        store_set_hit=1,
        max_cycles=12,
    )
    history = _capture_nc_history(env, cycles=6)

    assert issue["accepted"] is True
    assert _first_nc_writeback(history) is not None, "NC 正常完成场景应观察到最终写回"
    assert any(sample["feedback_valid"] for sample in history), "NC 正常完成仍应对后端给出慢反馈"
    assert not any(sample["rollback_valid"] for sample in history), "正常 NC 写回不应误触发 rollback"
    assert not any(sample["cancel_ld2"] for sample in history), "正常 NC 写回不应误触发 ldCancel"
    assert not any(sample["misalign_enq_valid"] or sample["misalign_ldout_valid"] for sample in history), "正常 NC 写回不应误进入 misalign 相关路径"


def test_loadunit_nc_misalign_unsupported_is_blocked(env):
    """NC 与 misalign 非法组合被阻止模板。"""
    env.dut.fc_cover["FG-NONCACHEABLE-LOAD"].mark_function(
        "FC-NC-MISALIGN-UNSUPPORTED",
        test_loadunit_nc_misalign_unsupported_is_blocked,
        ["CK-NC-MISALIGN-BLOCK"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_nc_load(
        env,
        vaddr=0x1103,
        paddr=0x4103,
        data=NC_DATA_128,
        fu_op_type=3,
        rob_idx=84,
        lq_idx=34,
        sq_idx=1,
        pc=0x1103,
        store_set_hit=1,
        max_cycles=12,
    )
    history = _capture_nc_history(env, cycles=6)
    writeback = _first_nc_writeback(history)

    assert issue["accepted"] is True
    assert writeback is not None, "不支持的 NC+misalign 组合应对后端给出可见阻断结果"
    assert writeback["uop"]["exceptionVec"]["4"] == 1, "不支持的 NC+misalign 组合应显式报告 loadAddrMisaligned 异常"
    assert any(sample["cancel_ld2"] or sample["feedback_valid"] for sample in history), "非法组合应伴随可见的阻断/取消控制"
    assert not any(sample["misalign_enq_valid"] or sample["misalign_ldout_valid"] for sample in history), "不支持的 NC+misalign 不应误进入普通 misalign 完成路径"


def test_loadunit_nc_misalign_unsupported_never_uses_ordinary_misalign_path(env):
    """NC+misalign 非法组合不进入普通 misalign 成功路径模板。"""
    env.dut.fc_cover["FG-NONCACHEABLE-LOAD"].mark_function(
        "FC-NC-MISALIGN-UNSUPPORTED",
        test_loadunit_nc_misalign_unsupported_never_uses_ordinary_misalign_path,
        ["CK-NO-ORDINARY-MISALIGN-PATH"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_nc_load(
        env,
        vaddr=0x110F,
        paddr=0x410F,
        data=NC_DATA_128,
        fu_op_type=3,
        rob_idx=85,
        lq_idx=35,
        sq_idx=1,
        pc=0x110F,
        store_set_hit=1,
        max_cycles=12,
    )
    history = _capture_nc_history(env, cycles=6)

    assert issue["accepted"] is True
    assert not any(sample["misalign_enq_valid"] for sample in history), "NC+misalign 非法组合不应误向 MisalignBuffer 入队"
    assert not any(sample["misalign_ldout_valid"] for sample in history), "NC+misalign 非法组合不应误使用 MisalignBuffer 返回口"
    assert _first_nc_writeback(history) is not None, "非法组合当前仍应有可观测的后端结果用于异常处理"
