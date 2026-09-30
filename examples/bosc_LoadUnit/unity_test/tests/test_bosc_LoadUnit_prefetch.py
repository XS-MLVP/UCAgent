#coding=utf-8

from bosc_LoadUnit_api import *


def _drive_prefetch_request(
    env,
    paddr: int,
    confidence: int,
    is_store: int = 0,
    pf_source_value: int = 0,
):
    env.prefetch.req.bits.paddr.value = int(paddr)
    env.prefetch.req.bits.confidence.value = int(confidence)
    env.prefetch.req.bits.is_store.value = int(is_store)
    env.prefetch.req.bits.pf_source_value.value = int(pf_source_value)
    env.prefetch.req.valid.value = 1


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


def _capture_prefetch_train_history(env, cycles: int):
    history = []
    for cycle in range(cycles):
        sms_train = env.prefetch.train.bits.as_dict() if env.prefetch.train.valid.value else None
        l1_train = env.prefetch.train.l1.bits.as_dict() if env.prefetch.train.l1.valid.value else None
        history.append(
            {
                "cycle": cycle,
                "sms_valid": int(env.prefetch.train.valid.value),
                "l1_valid": int(env.prefetch.train.l1.valid.value),
                "sms_train": sms_train,
                "l1_train": l1_train,
                "ldout_valid": int(env.scalar_resp.valid.value),
            }
        )
        env.Step(1)
    return history


def _first_sms_train(history):
    for sample in history:
        if sample["sms_valid"]:
            return sample["sms_train"]
    return None


def _first_l1_train(history):
    for sample in history:
        if sample["l1_valid"]:
            return sample["l1_train"]
    return None


def test_loadunit_highconf_prefetch_accept_when_available(env):
    """高置信度预取在空闲资源下被受理模板。"""
    env.dut.fc_cover["FG-PREFETCH"].mark_function(
        "FC-HIGHCONF-PREFETCH-ACCEPT",
        test_loadunit_highconf_prefetch_accept_when_available,
        ["CK-HIGHCONF-ACCEPT-WHEN-AVAILABLE"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    _drive_prefetch_request(env, paddr=0x9000, confidence=2, pf_source_value=1)

    assert int(env.io.canAcceptHighConfPrefetch.value) == 1, "空闲流水应接受高置信度预取"
    assert int(env.io.canAcceptLowConfPrefetch.value) == 1, "空闲流水下低置信度入口也应保持空闲"
    assert int(env.dcache.req.valid.value) == 0
    assert int(env.tlb.req.valid.value) == 0

    env.Step(1)

    assert int(env.io.canAcceptHighConfPrefetch.value) == 1, "高置信度预取被受理后不应错误标记为忙"
    assert int(env.dcache.req.valid.value) == 1, "高置信度预取被选中后应向 DCache 发请求"
    assert int(env.tlb.req.valid.value) == 0, "prefetch 请求不应误触发 TLB 查询"

    env.prefetch.req.valid.value = 0


def test_loadunit_highconf_prefetch_block_when_pipeline_busy(env):
    """高置信度预取在忙碌时不抢占模板。"""
    env.dut.fc_cover["FG-PREFETCH"].mark_function(
        "FC-HIGHCONF-PREFETCH-ACCEPT",
        test_loadunit_highconf_prefetch_block_when_pipeline_busy,
        ["CK-HIGHCONF-BLOCK-WHEN-BUSY"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    _drive_prefetch_request(env, paddr=0x9040, confidence=3, pf_source_value=2)
    _drive_misalign_blocker(env, vaddr=0x4040)

    env.Step(1)

    assert int(env.prefetch.req.valid.value) == 1
    assert int(env.misalign.ldin.valid.value) == 1
    assert int(env.io.canAcceptHighConfPrefetch.value) == 0, "更高优先级请求占用 stage 0 时应阻塞高置信预取"
    assert int(env.dcache.req.valid.value) == 1, "忙碌场景下应由高优先级请求占用 DCache 端口"
    assert int(env.tlb.req.valid.value) == 1, "misalign 请求被选中时应继续普通地址翻译路径"

    env.prefetch.req.valid.value = 0
    env.misalign.ldin.valid.value = 0


def test_loadunit_lowconf_prefetch_only_when_idle(env):
    """低置信度预取仅在空闲时受理模板。"""
    env.dut.fc_cover["FG-PREFETCH"].mark_function(
        "FC-LOWCONF-PREFETCH-ACCEPT",
        test_loadunit_lowconf_prefetch_only_when_idle,
        ["CK-LOWCONF-ONLY-WHEN-IDLE"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    _drive_prefetch_request(env, paddr=0x9080, confidence=0, pf_source_value=3)

    assert int(env.io.canAcceptLowConfPrefetch.value) == 1, "空闲流水应接受低置信度预取"
    assert int(env.dcache.req.valid.value) == 0
    assert int(env.tlb.req.valid.value) == 0

    env.Step(1)

    assert int(env.io.canAcceptLowConfPrefetch.value) == 1, "低置信度预取在空闲场景被受理后不应被误阻塞"
    assert int(env.dcache.req.valid.value) == 1, "低置信度预取在空闲时应向 DCache 发请求"
    assert int(env.tlb.req.valid.value) == 0, "低置信度预取也不应重新走 TLB 翻译"

    env.prefetch.req.valid.value = 0


def test_loadunit_lowconf_prefetch_has_lowest_priority(env):
    """低置信度预取保持最低优先级模板。"""
    env.dut.fc_cover["FG-PREFETCH"].mark_function(
        "FC-LOWCONF-PREFETCH-ACCEPT",
        test_loadunit_lowconf_prefetch_has_lowest_priority,
        ["CK-LOWCONF-LOWEST-PRIORITY"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    _drive_prefetch_request(env, paddr=0x90C0, confidence=0, pf_source_value=4)
    _drive_scalar_request(env, src0=0x1200, rob_idx=40, lq_idx=7)

    env.Step(1)

    assert int(env.prefetch.req.valid.value) == 1
    assert int(env.scalar_req.valid.value) == 1
    assert int(env.io.canAcceptLowConfPrefetch.value) == 0, "普通标量请求同拍竞争时，低置信度预取必须保持最低优先级"
    assert int(env.dcache.req.valid.value) == 1, "低置信度预取被阻塞时应由普通请求占用 DCache 端口"
    assert int(env.tlb.req.valid.value) == 1, "标量请求被选中时应可见普通 TLB 查询"

    env.prefetch.req.valid.value = 0
    env.scalar_req.valid.value = 0


def test_loadunit_l1_prefetch_train_on_load(env):
    """L1 预取训练有效时机模板。"""
    env.dut.fc_cover["FG-PREFETCH"].mark_function(
        "FC-PREFETCH-TRAIN-L1",
        test_loadunit_l1_prefetch_train_on_load,
        ["CK-L1-TRAIN-ON-LOAD"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1200,
        fu_op_type=3,
        rob_idx=91,
        lq_idx=27,
        sq_idx=0,
        pc=0x1200,
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
    history = _capture_prefetch_train_history(env, cycles=6)

    assert issue["accepted"] is True
    assert history[0]["l1_valid"] == 0, "load 尚未完成前不应提前产生 L1 prefetch train"
    assert history[1]["l1_valid"] == 1, "普通命中 load 在训练窗口应产生 L1 prefetch train"
    assert history[1]["ldout_valid"] == 1, "L1 train 应与该次 load 的最终写回窗口对齐"
    assert sum(sample["l1_valid"] for sample in history) == 1, "L1 train 应为单拍有效脉冲"


def test_loadunit_l1_prefetch_train_fields_match_load(env):
    """L1 预取训练字段匹配模板。"""
    env.dut.fc_cover["FG-PREFETCH"].mark_function(
        "FC-PREFETCH-TRAIN-L1",
        test_loadunit_l1_prefetch_train_fields_match_load,
        ["CK-L1-TRAIN-FIELDS"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1240,
        fu_op_type=3,
        rob_idx=92,
        lq_idx=28,
        sq_idx=0,
        pc=0x1240,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x5240,
        dcache_data=0x0FEDCBA987654321,
        hold_cycles=2,
        max_cycles=2,
    )
    history = _capture_prefetch_train_history(env, cycles=6)
    train = _first_l1_train(history)

    assert issue["accepted"] is True
    assert train is not None, "命中 load 场景应产生 L1 prefetch train"
    assert train["vaddr"] == 0x1240
    assert train["uop_robIdx"]["flag"] == 1
    assert train["uop_robIdx"]["value"] == 92
    assert train["isFirstIssue"] == 1
    assert train["miss"] == 0
    assert train["meta_prefetch"] == 0


def test_loadunit_sms_prefetch_train_fields_match_load(env):
    """SMS 预取训练字段模板。"""
    env.dut.fc_cover["FG-PREFETCH"].mark_function(
        "FC-PREFETCH-TRAIN-SMS",
        test_loadunit_sms_prefetch_train_fields_match_load,
        ["CK-SMS-TRAIN-FIELDS"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1200,
        fu_op_type=3,
        rob_idx=91,
        lq_idx=27,
        sq_idx=0,
        pc=0x1200,
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
    history = _capture_prefetch_train_history(env, cycles=6)
    train = _first_sms_train(history)

    assert issue["accepted"] is True
    assert train is not None, "普通 load 命中场景应产生 SMS prefetch train 输出"
    assert train["vaddr"] == 0x1200
    assert train["paddr"] == 0x5200
    assert train["uop_robIdx"]["flag"] == 1
    assert train["uop_robIdx"]["value"] == 91
    assert train["isFirstIssue"] == 1
    assert train["miss"] == 0
    assert any(sample["ldout_valid"] for sample in history), "训练字段场景也应能推进到最终写回"


def test_loadunit_sms_prefetch_train_on_load(env):
    """SMS 预取训练有效时机模板。"""
    env.dut.fc_cover["FG-PREFETCH"].mark_function(
        "FC-PREFETCH-TRAIN-SMS",
        test_loadunit_sms_prefetch_train_on_load,
        ["CK-SMS-TRAIN-ON-LOAD"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1200,
        fu_op_type=3,
        rob_idx=91,
        lq_idx=27,
        sq_idx=0,
        pc=0x1200,
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
    history = _capture_prefetch_train_history(env, cycles=6)

    assert issue["accepted"] is True
    assert history[0]["sms_valid"] == 0, "load 尚未完成前不应提前产生 SMS prefetch train"
    assert history[1]["sms_valid"] == 1, "普通命中 load 在训练窗口应产生 SMS prefetch train"
    assert history[1]["ldout_valid"] == 1, "SMS train 应与该次 load 的最终写回窗口对齐"
    assert sum(sample["sms_valid"] for sample in history) == 1, "SMS train 应为单拍有效脉冲"
