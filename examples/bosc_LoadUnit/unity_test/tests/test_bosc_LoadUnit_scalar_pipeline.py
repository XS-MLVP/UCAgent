#coding=utf-8

from bosc_LoadUnit_api import *


SCALAR_HIT_DATA_64 = 0x8877665544332211


def _drive_scalar_request(env, src0: int, rob_idx: int, lq_idx: int, sq_idx: int = 0, fu_op_type: int = 3):
    env.scalar_req.bits.src["0"].value = int(src0)
    env.scalar_req.bits.uop.pc.value = int(src0)
    env.scalar_req.bits.uop.fuOpType.value = int(fu_op_type)
    env.scalar_req.bits.uop.fuType.value = 0
    env.scalar_req.bits.uop.rfWen.value = 1
    env.scalar_req.bits.uop.fpWen.value = 0
    env.scalar_req.bits.uop.imm.value = 0
    env.scalar_req.bits.uop.pdest.value = 1
    env.scalar_req.bits.uop.preDecodeInfo.valid.value = 0
    env.scalar_req.bits.uop.preDecodeInfo.isRVC.value = 0
    env.scalar_req.bits.uop.preDecodeInfo.brType.value = 0
    env.scalar_req.bits.uop.preDecodeInfo.isCall.value = 0
    env.scalar_req.bits.uop.preDecodeInfo.isRet.value = 0
    env.scalar_req.bits.uop.robIdx.flag.value = 1
    env.scalar_req.bits.uop.robIdx.value.value = int(rob_idx)
    env.scalar_req.bits.uop.lqIdx.flag.value = 1
    env.scalar_req.bits.uop.lqIdx.value.value = int(lq_idx)
    env.scalar_req.bits.uop.sqIdx.flag.value = 1
    env.scalar_req.bits.uop.sqIdx.value.value = int(sq_idx)
    env.scalar_req.bits.uop.ftqPtr.flag.value = 0
    env.scalar_req.bits.uop.ftqPtr.value.value = 0
    env.scalar_req.bits.uop.waitForRobIdx.flag.value = 0
    env.scalar_req.bits.uop.waitForRobIdx.value.value = 0
    env.scalar_req.valid.value = 1


def _drive_misalign_blocker(env, vaddr: int, rob_idx: int = 2, lq_idx: int = 2):
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


def _issue_scalar_hit(env, src0: int, paddr: int, data: int, rob_idx: int, lq_idx: int, sq_idx: int = 0):
    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=src0,
        fu_op_type=3,
        rob_idx=rob_idx,
        lq_idx=lq_idx,
        sq_idx=sq_idx,
        pc=src0,
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


def _wait_for_scalar_writeback(env, max_cycles: int = 8):
    for _ in range(max_cycles):
        if int(env.scalar_resp.valid.value):
            return
        env.Step(1)
    raise TimeoutError("在 max_cycles 周期内未等到标量写回 valid")


def test_loadunit_scalar_single_accept(env):
    """标量请求单次握手模板。"""
    env.dut.fc_cover["FG-SCALAR-PIPELINE"].mark_function(
        "FC-SCALAR-HANDSHAKE",
        test_loadunit_scalar_single_accept,
        ["CK-SINGLE-ACCEPT"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    result = api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1000,
        fu_op_type=3,
        rob_idx=82,
        lq_idx=29,
        sq_idx=1,
        pc=0x1000,
        max_cycles=12,
    )

    assert result["accepted"] is True
    assert int(env.scalar_req.valid.value) == 0, "单次握手完成后不应残留 ldin.valid"
    assert int(env.tlb.req.valid.value) == 1 or int(env.dcache.req.valid.value) == 1, "单次握手后应触发后续 TLB/DCache 访问"


def test_loadunit_scalar_stall_and_resume(env):
    """标量请求停顿恢复模板。"""
    env.dut.fc_cover["FG-SCALAR-PIPELINE"].mark_function(
        "FC-SCALAR-HANDSHAKE",
        test_loadunit_scalar_stall_and_resume,
        ["CK-STALL-AND-RESUME"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.set_default_inputs()
    _drive_scalar_request(env, src0=0x1040, rob_idx=83, lq_idx=30, sq_idx=0)
    _drive_misalign_blocker(env, vaddr=0x4040)

    before = env.scalar_req.bits.as_dict()
    ready_history = []
    for _ in range(2):
        ready_history.append(int(env.scalar_req.ready.value))
        env.Step(1)
    stalled = env.scalar_req.bits.as_dict()

    env.misalign.ldin.valid.value = 0
    resumed = False
    for _ in range(4):
        ready_now = int(env.scalar_req.ready.value)
        env.Step(1)
        if ready_now:
            resumed = True
            env.scalar_req.valid.value = 0
            break

    assert 0 in ready_history, "制造的高优先级竞争应先让标量请求进入 stall"
    assert before == stalled, "stall 期间同一条标量请求载荷必须保持稳定"
    assert resumed, "解除竞争后标量请求应恢复并被正常接收"
    assert int(env.scalar_req.valid.value) == 0


def test_loadunit_scalar_tlb_dcache_request_issue_timing(env):
    """标量请求发起 TLB/DCache 时序模板。"""
    env.dut.fc_cover["FG-SCALAR-PIPELINE"].mark_function(
        "FC-SCALAR-TLB-DCACHE-REQ",
        test_loadunit_scalar_tlb_dcache_request_issue_timing,
        ["CK-REQ-ISSUE-TIMING"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    assert int(env.tlb.req.valid.value) == 0 and int(env.dcache.req.valid.value) == 0, "空闲状态不应凭空发起 TLB/DCache 请求"

    env.set_default_inputs()
    _drive_scalar_request(env, src0=0x1080, rob_idx=84, lq_idx=31, sq_idx=0)

    issue_cycle = None
    for cycle in range(3):
        if int(env.tlb.req.valid.value) or int(env.dcache.req.valid.value):
            issue_cycle = cycle
            break
        env.Step(1)

    env.scalar_req.valid.value = 0

    assert issue_cycle is not None, "标量请求被发射后应在有限拍次内对 TLB 或 DCache 发起请求"
    assert issue_cycle <= 1, "stage0 请求发起不应无故拖延超过一个拍次"


def test_loadunit_scalar_tlb_dcache_request_fields_match(env):
    """标量请求发起字段匹配模板。"""
    env.dut.fc_cover["FG-SCALAR-PIPELINE"].mark_function(
        "FC-SCALAR-TLB-DCACHE-REQ",
        test_loadunit_scalar_tlb_dcache_request_fields_match,
        ["CK-REQ-FIELD-MATCH"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.set_default_inputs()
    _drive_scalar_request(env, src0=0x10C0, rob_idx=85, lq_idx=32, sq_idx=0, fu_op_type=3)

    env.Step(1)

    assert int(env.tlb.req.valid.value) == 1 and int(env.dcache.req.valid.value) == 1
    assert int(env.tlb.req.bits.vaddr.value) == 0x10C0
    assert int(env.tlb.req.bits.fullva.value) == 0x10C0
    assert int(env.tlb.req.bits.checkfullva.value) == 1
    assert int(env.tlb.req.bits.no_translate.value) == 0
    assert int(env.dcache.req.bits.vaddr_dup.value) == 0x10C0
    assert int(env.dcache.req.bits.lqIdx.flag.value) == 1
    assert int(env.dcache.req.bits.lqIdx.value.value) == 32
    assert int(env.dcache.req.bits.cmd.value) == 0
    assert int(env.dcache.req.bits.instrtype.value) == 0

    env.scalar_req.valid.value = 0


def test_loadunit_scalar_no_issue_when_stage1_blocked(env):
    """stage1 阻塞时不提前发起 TLB/DCache 请求模板。

    该模板优先对应静态缺陷 BG-STATIC-004，用于后续动态复现 stage0 在 s1 阻塞时
    仍向 TLB/DCache 发出请求的协议撕裂风险。
    """
    env.dut.fc_cover["FG-SCALAR-PIPELINE"].mark_function(
        "FC-SCALAR-TLB-DCACHE-REQ",
        test_loadunit_scalar_no_issue_when_stage1_blocked,
        ["CK-NO-ISSUE-WHEN-S1-BLOCKED"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x2000,
        fu_op_type=3,
        rob_idx=86,
        lq_idx=33,
        sq_idx=0,
        pc=0x2000,
        max_cycles=12,
    )

    # 先让第一条请求进入 stage3，再通过 ldout.ready=0 制造真正的下游阻塞窗口。
    env.Step(2)
    env.scalar_resp.ready.value = 0
    _drive_scalar_request(env, src0=0x2040, rob_idx=87, lq_idx=34, sq_idx=0)
    history = []
    for _ in range(6):
        history.append(
            {
                "ready": int(env.scalar_req.ready.value),
                "tlb_req_valid": int(env.tlb.req.valid.value),
                "dcache_req_valid": int(env.dcache.req.valid.value),
                "dcache_lq_idx": int(env.dcache.req.bits.lqIdx.value.value),
                "ldout_valid": int(env.scalar_resp.valid.value),
                "ldout_lq_idx": int(env.scalar_resp.bits.uop.lqIdx.value.value),
            }
        )
        env.Step(1)

    env.scalar_req.valid.value = 0

    assert any(
        sample["ldout_valid"] == 1 and sample["ldout_lq_idx"] == 33 for sample in history
    ), "测试必须先构造出第一条 load 在 ldout.ready=0 下占用写回口的阻塞窗口"
    assert all(
        not (
            sample["ldout_valid"] == 1
            and sample["ldout_lq_idx"] == 33
            and sample["dcache_lq_idx"] == 34
            and (sample["tlb_req_valid"] or sample["dcache_req_valid"])
        )
        for sample in history
    ), "第一条请求在写回端被 backpressure 阻塞时，第二条标量请求不应提前发给 TLB/DCache"


def test_loadunit_scalar_hit_data_writeback(env):
    """标量命中数据写回模板。"""
    env.dut.fc_cover["FG-SCALAR-PIPELINE"].mark_function(
        "FC-SCALAR-HIT-WRITEBACK",
        test_loadunit_scalar_hit_data_writeback,
        ["CK-HIT-DATA-WRITEBACK"],
    )

    _issue_scalar_hit(env, src0=0x2400, paddr=0x6400, data=SCALAR_HIT_DATA_64, rob_idx=88, lq_idx=35, sq_idx=0)
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=12)

    assert result["scalar_writeback"] is not None
    assert result["scalar_writeback"]["data"] == SCALAR_HIT_DATA_64
    assert result["scalar_writeback"]["data"] != 0
    assert result["scalar_writeback"]["debug"]["paddr"] == 0x6400
    assert result["feedback_slow"] is not None


def test_loadunit_scalar_hit_writeback_meta_match(env):
    """标量命中写回元数据匹配模板。"""
    env.dut.fc_cover["FG-SCALAR-PIPELINE"].mark_function(
        "FC-SCALAR-HIT-WRITEBACK",
        test_loadunit_scalar_hit_writeback_meta_match,
        ["CK-UOP-META-WRITEBACK"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x2800,
        fu_op_type=3,
        rob_idx=81,
        lq_idx=28,
        sq_idx=3,
        pc=0x2800,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x6800,
        dcache_data=0x1020304050607080,
        hold_cycles=2,
        max_cycles=2,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=12)

    assert result["scalar_writeback"] is not None
    assert result["feedback_slow"] is not None
    assert result["scalar_writeback"]["uop"]["robIdx"]["value"] == 81
    assert result["scalar_writeback"]["uop"]["lqIdx"]["value"] == 28
    assert result["scalar_writeback"]["uop"]["pdest"] == 1
    assert result["scalar_writeback"]["uop"]["rfWen"] == 1
    assert not any(result["scalar_writeback"]["uop"]["exceptionVec"].values()), "正常命中写回不应伪造异常元数据"
    assert result["scalar_writeback"]["debug"]["vaddr"] == 0x2800
    assert result["scalar_writeback"]["debug"]["paddr"] == 0x6800
    assert result["feedback_slow"]["robIdx"]["value"] == 81
    assert result["feedback_slow"]["lqIdx"]["value"] == 28


def test_loadunit_scalar_writeback_holds_under_backpressure(env):
    """标量写回背压保持模板。"""
    env.dut.fc_cover["FG-SCALAR-PIPELINE"].mark_function(
        "FC-SCALAR-WRITEBACK-BACKPRESSURE",
        test_loadunit_scalar_writeback_holds_under_backpressure,
        ["CK-HOLD-UNDER-BACKPRESSURE"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.scalar_resp.ready.value = 0
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x2440,
        fu_op_type=3,
        rob_idx=89,
        lq_idx=36,
        sq_idx=0,
        pc=0x2440,
        max_cycles=12,
    )

    history = []
    for _ in range(6):
        history.append(
            {
                "valid": int(env.scalar_resp.valid.value),
                "data": int(env.scalar_resp.bits.data.value),
                "rob_idx": int(env.scalar_resp.bits.uop.robIdx.value.value),
                "lq_idx": int(env.scalar_resp.bits.uop.lqIdx.value.value),
            }
        )
        env.Step(1)

    first_valid_idx = next(
        (idx for idx, sample in enumerate(history) if sample["valid"] and sample["rob_idx"] == 89),
        None,
    )
    assert first_valid_idx is not None, "写回背压测试必须先观察到目标标量写回到达 ldout"
    assert first_valid_idx + 1 < len(history), "采样窗口必须覆盖写回到达后的至少一拍"
    assert history[first_valid_idx + 1]["valid"] == 1, "背压期间 ldout.valid 应持续保持"
    assert history[first_valid_idx + 1] == history[first_valid_idx], "背压期间写回 data/uop 元数据应保持稳定不抖动"

    env.scalar_resp.ready.value = 1


def test_loadunit_scalar_writeback_releases_on_ready(env):
    """标量写回背压解除后释放模板。"""
    env.dut.fc_cover["FG-SCALAR-PIPELINE"].mark_function(
        "FC-SCALAR-WRITEBACK-BACKPRESSURE",
        test_loadunit_scalar_writeback_releases_on_ready,
        ["CK-RELEASE-ON-READY"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    env.scalar_resp.ready.value = 0
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x2480,
        fu_op_type=3,
        rob_idx=90,
        lq_idx=37,
        sq_idx=0,
        pc=0x2480,
        max_cycles=12,
    )

    history = []
    for _ in range(6):
        history.append(
            {
                "valid": int(env.scalar_resp.valid.value),
                "data": int(env.scalar_resp.bits.data.value),
                "rob_idx": int(env.scalar_resp.bits.uop.robIdx.value.value),
                "lq_idx": int(env.scalar_resp.bits.uop.lqIdx.value.value),
            }
        )
        env.Step(1)

    first_valid_idx = next(
        (idx for idx, sample in enumerate(history) if sample["valid"] and sample["rob_idx"] == 90),
        None,
    )
    assert first_valid_idx is not None, "释放测试必须先观察到目标写回到达 ldout"
    assert first_valid_idx + 1 < len(history), "释放测试必须覆盖背压下的保持窗口"
    assert history[first_valid_idx + 1]["valid"] == 1, "ready 拉低时写回必须先被稳定保持，随后才能谈释放"

    held_snapshot = history[first_valid_idx + 1]

    env.scalar_resp.ready.value = 1
    release_cycles = 0
    release_seen = False
    for _ in range(3):
        if int(env.scalar_resp.valid.value):
            release_seen = True
            assert {
                "valid": int(env.scalar_resp.valid.value),
                "data": int(env.scalar_resp.bits.data.value),
                "rob_idx": int(env.scalar_resp.bits.uop.robIdx.value.value),
                "lq_idx": int(env.scalar_resp.bits.uop.lqIdx.value.value),
            } == held_snapshot
            release_cycles += 1
        env.Step(1)

    assert release_seen, "恢复 ready 后此前被阻塞的写回应被正常释放"
    assert release_cycles <= 1, "ready 恢复后的被阻塞写回不应重复提交多次"
