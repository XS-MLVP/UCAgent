#coding=utf-8

from bosc_LoadUnit_api import *


DCACHE_DATA_128 = 0xFFEEDDCCBBAA99887766554433221100
DCACHE_LOW64 = 0x7766554433221100
DCACHE_HIGH64 = 0xFFEEDDCCBBAA9988
FORWARD_DATA_128 = 0x112233445566778899AABBCCDDEEFF00
FORWARD_LOW64 = 0x99AABBCCDDEEFF00
MMIO_RAW_DATA_64 = 0x8877665544332211


def _scalar_hit_result(
    env,
    *,
    src0: int,
    paddr: int,
    data: int,
    rob_idx: int,
    lq_idx: int,
    sq_idx: int = 0,
    pc: int | None = None,
    forward_source: str = "",
    forward_data: int = 0,
    forward_mask: int = 0xFFFF,
):
    if pc is None:
        pc = src0
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
        forward_source=forward_source,
        forward_data=forward_data,
        forward_mask=forward_mask,
        hold_cycles=2,
        max_cycles=2,
    )
    return api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=12)


def _capture_scalar_history(env, cycles: int):
    history = []
    for cycle in range(cycles):
        writeback = env.scalar_resp.bits.as_dict() if env.scalar_resp.valid.value else None
        lsq_ldin = env.lsq.ldin.bits.as_dict() if env.lsq.ldin.valid.value else None
        history.append(
            {
                "cycle": cycle,
                "lsq_ldin_valid": int(env.lsq.ldin.valid.value),
                "lsq_ldin": lsq_ldin,
                "ldout_valid": int(env.scalar_resp.valid.value),
                "writeback": writeback,
            }
        )
        env.Step(1)
    return history


def _first_scalar_writeback(history):
    for sample in history:
        if sample["ldout_valid"]:
            return sample["writeback"]
    return None


def _capture_mmio_history(env, cycles: int):
    history = []
    for cycle in range(cycles):
        writeback = env.scalar_resp.bits.as_dict() if env.scalar_resp.valid.value else None
        history.append(
            {
                "cycle": cycle,
                "wakeup_valid": int(env.wakeup.valid.value),
                "ldout_valid": int(env.scalar_resp.valid.value),
                "writeback": writeback,
            }
        )
        env.Step(1)
    return history


def _first_mmio_writeback(history):
    for sample in history:
        if sample["ldout_valid"]:
            return sample["writeback"]
    return None


def _issue_mmio_writeback(
    env,
    *,
    rob_idx: int,
    lq_idx: int,
    pc: int,
    pdest: int,
    raw_data: int = MMIO_RAW_DATA_64,
    addr_offset: int = 0,
    raw_fu_op_type: int = 3,
    debug_vaddr: int | None = None,
    debug_paddr: int = 0,
):
    api_bosc_LoadUnit_reset(env, max_cycles=8)
    issue = api_bosc_LoadUnit_send_mmio_load(
        env,
        rob_idx=rob_idx,
        lq_idx=lq_idx,
        sq_idx=0,
        pc=pc,
        pdest=pdest,
        pmp_mmio_hint=True,
        debug_vaddr=pc if debug_vaddr is None else debug_vaddr,
        debug_paddr=debug_paddr,
        debug_is_mmio=True,
        raw_data=raw_data,
        raw_addr_offset=addr_offset,
        raw_fu_op_type=raw_fu_op_type,
        max_cycles=12,
    )
    history = _capture_mmio_history(env, cycles=6)
    return issue, history


def test_loadunit_writeback_selects_dcache_source(env):
    """写回选择 DCache 数据源模板。"""
    env.dut.fc_cover["FG-WRITEBACK-DATA"].mark_function(
        "FC-DATA-SOURCE-SELECTION",
        test_loadunit_writeback_selects_dcache_source,
        ["CK-DCACHE-SOURCE"],
    )

    result = _scalar_hit_result(
        env,
        src0=0x2000,
        paddr=0x8000,
        data=DCACHE_DATA_128,
        rob_idx=105,
        lq_idx=35,
    )

    assert result["scalar_writeback"] is not None, "仅有 DCache 数据的场景应产生标量写回"
    assert result["scalar_writeback"]["data"] == DCACHE_LOW64, "无前递/uncache 竞争时应直接选择 DCache 数据"
    assert result["scalar_writeback"]["data"] != MMIO_RAW_DATA_64
    assert result["feedback_slow"] is not None


def test_loadunit_writeback_selects_forward_source(env):
    """写回优先选择前递数据模板。"""
    env.dut.fc_cover["FG-WRITEBACK-DATA"].mark_function(
        "FC-DATA-SOURCE-SELECTION",
        test_loadunit_writeback_selects_forward_source,
        ["CK-FORWARD-SOURCE"],
    )

    result = _scalar_hit_result(
        env,
        src0=0x2040,
        paddr=0x8040,
        data=DCACHE_DATA_128,
        rob_idx=106,
        lq_idx=36,
        forward_source="lsq",
        forward_data=FORWARD_DATA_128,
        forward_mask=0x00FF,
    )

    assert result["scalar_writeback"] is not None, "前递命中场景应仍产生最终写回"
    assert result["scalar_writeback"]["data"] == FORWARD_LOW64, "前递数据可用时应优先选择前递结果"
    assert result["scalar_writeback"]["data"] != DCACHE_LOW64, "前递优先级应高于 DCache 返回数据"


def test_loadunit_writeback_selects_uncache_source(env):
    """写回选择 uncache 数据源模板。"""
    env.dut.fc_cover["FG-WRITEBACK-DATA"].mark_function(
        "FC-DATA-SOURCE-SELECTION",
        test_loadunit_writeback_selects_uncache_source,
        ["CK-UNCACHE-SOURCE"],
    )

    issue, history = _issue_mmio_writeback(
        env,
        rob_idx=107,
        lq_idx=37,
        pc=0x2080,
        pdest=5,
        raw_data=MMIO_RAW_DATA_64,
        addr_offset=0,
        raw_fu_op_type=3,
    )
    writeback = _first_mmio_writeback(history)

    assert issue["accepted"] is True
    assert writeback is not None, "uncache/MMIO 场景最终应产生标量写回"
    assert writeback["data"] == MMIO_RAW_DATA_64, "uncache 数据源场景下最终写回应来自 io_lsq_ld_raw_data"
    assert writeback["data"] != DCACHE_LOW64, "uncache 数据源场景不应误选 DCache 默认数据"


def test_loadunit_extracts_low_half_from_128b_data(env):
    """128bit 低半段提取模板。"""
    env.dut.fc_cover["FG-WRITEBACK-DATA"].mark_function(
        "FC-EXTRACT-128B-TO-64B",
        test_loadunit_extracts_low_half_from_128b_data,
        ["CK-LOW-HALF-EXTRACT"],
    )

    result = _scalar_hit_result(
        env,
        src0=0x20C0,
        paddr=0x80C0,
        data=DCACHE_DATA_128,
        rob_idx=108,
        lq_idx=38,
    )

    assert result["scalar_writeback"] is not None
    assert result["scalar_writeback"]["data"] == DCACHE_LOW64, "低半段访问应取自 128bit 数据的低 64bit"


def test_loadunit_extracts_high_half_from_128b_data(env):
    """128bit 高半段提取模板。"""
    env.dut.fc_cover["FG-WRITEBACK-DATA"].mark_function(
        "FC-EXTRACT-128B-TO-64B",
        test_loadunit_extracts_high_half_from_128b_data,
        ["CK-HIGH-HALF-EXTRACT"],
    )

    result = _scalar_hit_result(
        env,
        src0=0x2100,
        paddr=0x8108,
        data=DCACHE_DATA_128,
        rob_idx=109,
        lq_idx=39,
    )

    assert result["scalar_writeback"] is not None
    assert result["scalar_writeback"]["data"] == DCACHE_HIGH64, "高半段访问应取自 128bit 数据的高 64bit"


def test_loadunit_selects_bytes_by_offset(env):
    """128bit 数据按地址偏移选字节模板。"""
    env.dut.fc_cover["FG-WRITEBACK-DATA"].mark_function(
        "FC-EXTRACT-128B-TO-64B",
        test_loadunit_selects_bytes_by_offset,
        ["CK-OFFSET-SELECT"],
    )

    cases = [
        (0x2300, 0x8300, 0x7766554433221100),
        (0x2301, 0x8301, 0x8877665544332211),
        (0x2302, 0x8302, 0x9988776655443322),
        (0x2304, 0x8304, 0xBBAA998877665544),
        (0x2308, 0x8308, 0xFFEEDDCCBBAA9988),
    ]
    observed = []

    for idx, (src0, paddr, expected) in enumerate(cases):
        result = _scalar_hit_result(
            env,
            src0=src0,
            paddr=paddr,
            data=DCACHE_DATA_128,
            rob_idx=120 + idx,
            lq_idx=50 + idx,
        )

        assert result["scalar_writeback"] is not None, f"offset=0x{paddr & 0xF:x} 场景应产生标量写回"
        observed.append(result["scalar_writeback"]["data"])
        assert result["scalar_writeback"]["data"] == expected, (
            f"offset=0x{paddr & 0xF:x} 时 ldout.data 应按字节偏移选通，"
            f"期望 0x{expected:016x}，实际 0x{result['scalar_writeback']['data']:016x}"
        )

    assert len(set(observed)) == len(cases), "不同地址偏移应产生彼此可区分的写回结果，避免固定分支误判"


def test_loadunit_uncache_data_writeback_path(env):
    """uncache 数据写回模板。"""
    env.dut.fc_cover["FG-WRITEBACK-DATA"].mark_function(
        "FC-UNCACHE-DATA-WRITEBACK",
        test_loadunit_uncache_data_writeback_path,
        ["CK-UNCACHE-DATA-PATH"],
    )

    issue, history = _issue_mmio_writeback(
        env,
        rob_idx=110,
        lq_idx=40,
        pc=0x2140,
        pdest=6,
        raw_data=0x1122334455667788,
        addr_offset=0,
        raw_fu_op_type=3,
    )
    writeback = _first_mmio_writeback(history)

    assert issue["accepted"] is True
    assert writeback is not None, "uncache 返回路径最终应产生标量写回"
    assert writeback["data"] == 0x1122334455667788, "uncache 返回数据应原样参与最终写回"


def test_loadunit_uncache_meta_writeback_path(env):
    """uncache 写回元数据保持模板。"""
    env.dut.fc_cover["FG-WRITEBACK-DATA"].mark_function(
        "FC-UNCACHE-DATA-WRITEBACK",
        test_loadunit_uncache_meta_writeback_path,
        ["CK-UNCACHE-META-PATH"],
    )

    issue, history = _issue_mmio_writeback(
        env,
        rob_idx=111,
        lq_idx=41,
        pc=0x2180,
        pdest=7,
        raw_data=MMIO_RAW_DATA_64,
        addr_offset=0,
        raw_fu_op_type=3,
        debug_paddr=0x9180,
    )
    writeback = _first_mmio_writeback(history)

    assert issue["accepted"] is True
    assert writeback is not None
    assert writeback["uop"]["robIdx"]["value"] == 111
    assert writeback["uop"]["lqIdx"]["value"] == 41
    assert writeback["debug"]["vaddr"] == 0x2180, "uncache 写回应保留本次请求的 debug.vaddr"
    assert writeback["debug"]["paddr"] == 0x9180, "uncache 写回应保留本次请求的 debug.paddr"
    assert writeback["debug"]["isMMIO"] == 1, "uncache/MMIO 写回应显式标记 debug.isMMIO"


def test_loadunit_writeback_updates_debug_addresses_and_flags(env):
    """写回 debug 地址与属性标志更新模板。"""
    env.dut.fc_cover["FG-WRITEBACK-DATA"].mark_function(
        "FC-WRITEBACK-META-UPDATE",
        test_loadunit_writeback_updates_debug_addresses_and_flags,
        ["CK-DEBUG-ADDR-UPDATE"],
    )

    scalar_result = _scalar_hit_result(
        env,
        src0=0x21C0,
        paddr=0x81C0,
        data=0x0123456789ABCDEF,
        rob_idx=112,
        lq_idx=42,
    )
    issue, history = _issue_mmio_writeback(
        env,
        rob_idx=113,
        lq_idx=43,
        pc=0x2200,
        pdest=8,
        raw_data=MMIO_RAW_DATA_64,
        addr_offset=0,
        raw_fu_op_type=3,
        debug_paddr=0x9200,
    )
    mmio_writeback = _first_mmio_writeback(history)

    assert scalar_result["scalar_writeback"] is not None
    assert scalar_result["scalar_writeback"]["debug"]["vaddr"] == 0x21C0
    assert scalar_result["scalar_writeback"]["debug"]["paddr"] == 0x81C0
    assert scalar_result["scalar_writeback"]["debug"]["isMMIO"] == 0
    assert issue["accepted"] is True
    assert mmio_writeback is not None
    assert mmio_writeback["debug"]["vaddr"] == 0x2200, "MMIO/uncache 写回应更新 debug.vaddr"
    assert mmio_writeback["debug"]["paddr"] == 0x9200, "MMIO/uncache 写回应更新 debug.paddr"
    assert mmio_writeback["debug"]["isMMIO"] == 1, "MMIO/uncache 写回应更新 debug.isMMIO"


def test_loadunit_writeback_updates_lq_index_consistently(env):
    """写回阶段 LoadQueue 索引更新模板。"""
    env.dut.fc_cover["FG-WRITEBACK-DATA"].mark_function(
        "FC-WRITEBACK-META-UPDATE",
        test_loadunit_writeback_updates_lq_index_consistently,
        ["CK-LQ-INDEX-UPDATE"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x2240,
        fu_op_type=3,
        rob_idx=114,
        lq_idx=44,
        sq_idx=0,
        pc=0x2240,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x8240,
        dcache_data=0x8877665544332211,
        hold_cycles=2,
        max_cycles=2,
    )
    history = _capture_scalar_history(env, cycles=6)
    writeback = _first_scalar_writeback(history)
    lsq_update = next((sample["lsq_ldin"] for sample in history if sample["lsq_ldin_valid"]), None)

    assert writeback is not None, "普通完成场景应产生最终 ldout 写回"
    assert lsq_update is not None, "普通完成场景应同步更新 LoadQueue"
    assert writeback["uop"]["lqIdx"]["value"] == 44, "ldout 写回中的 lqIdx 应与原请求一致"
    assert lsq_update["uop"]["lqIdx"]["value"] == 44, "LoadQueue 更新中的 lqIdx 应与原请求一致"
