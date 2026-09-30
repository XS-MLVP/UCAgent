#coding=utf-8

from bosc_LoadUnit_api import *
import random
import ucagent


def _expected_low64_from_128(data_128: int, offset: int) -> int:
    """按 little-endian 字节序计算 128bit 数据在给定 offset 下的 64bit 视图。"""
    data_bytes = [(data_128 >> (8 * idx)) & 0xFF for idx in range(16)]
    window = data_bytes[offset: offset + 8]
    return sum(byte << (8 * idx) for idx, byte in enumerate(window))


def _first_mmio_writeback(env, cycles: int = 8):
    for _ in range(cycles):
        if env.scalar_resp.valid.value:
            return env.scalar_resp.bits.as_dict()
        env.Step(1)
    return None


def test_random_writeback_offset_extract(env):
    """随机验证 128bit DCache 数据在不同地址偏移下的 64bit 提取结果。"""
    env.dut.fc_cover["FG-WRITEBACK-DATA"].mark_function(
        "FC-EXTRACT-128B-TO-64B",
        test_random_writeback_offset_extract,
        ["CK-LOW-HALF-EXTRACT", "CK-HIGH-HALF-EXTRACT", "CK-OFFSET-SELECT"],
    )

    repeat = ucagent.repeat_count()
    rng = random.Random(0x20260603)

    for idx in range(repeat):
        data_128 = rng.getrandbits(128)
        offset = rng.randint(0, 8)
        src0 = 0x4000 + (idx << 4) + offset
        paddr = 0x8000 + (idx << 4) + offset
        expected = _expected_low64_from_128(data_128, offset)

        api_bosc_LoadUnit_reset(env, max_cycles=8)
        api_bosc_LoadUnit_send_scalar_load(
            env,
            src0=src0,
            fu_op_type=3,
            rob_idx=200 + idx,
            lq_idx=60 + idx,
            sq_idx=0,
            pc=src0,
            max_cycles=12,
        )
        api_bosc_LoadUnit_inject_memory_resp(
            env,
            tlb_valid=True,
            tlb_paddr=paddr,
            dcache_data=data_128,
            hold_cycles=2,
            max_cycles=2,
        )
        result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=12)

        assert result["scalar_writeback"] is not None, f"随机 offset 提取场景 #{idx} 应产生标量写回"
        assert result["scalar_writeback"]["data"] == expected, (
            f"随机 offset 提取场景 #{idx} 结果错误："
            f"offset=0x{offset:x}, expected=0x{expected:016x}, "
            f"actual=0x{result['scalar_writeback']['data']:016x}"
        )


def test_random_mmio_writeback_metadata(env):
    """随机验证 MMIO/uncache 写回对 data/debug/uop 元信息的保持。"""
    env.dut.fc_cover["FG-WRITEBACK-DATA"].mark_function(
        "FC-DATA-SOURCE-SELECTION",
        test_random_mmio_writeback_metadata,
        ["CK-UNCACHE-SOURCE"],
    )
    env.dut.fc_cover["FG-WRITEBACK-DATA"].mark_function(
        "FC-UNCACHE-DATA-WRITEBACK",
        test_random_mmio_writeback_metadata,
        ["CK-UNCACHE-DATA-PATH", "CK-UNCACHE-META-PATH"],
    )
    env.dut.fc_cover["FG-WRITEBACK-DATA"].mark_function(
        "FC-WRITEBACK-META-UPDATE",
        test_random_mmio_writeback_metadata,
        ["CK-DEBUG-ADDR-UPDATE"],
    )

    repeat = ucagent.repeat_count()
    rng = random.Random(0x4D4D10)

    for idx in range(repeat):
        debug_vaddr = rng.getrandbits(40) | 0x1000
        debug_paddr = rng.getrandbits(40) | 0x2000
        raw_data = rng.getrandbits(64) | 0x1
        rob_idx = 20 + (idx % 60)
        lq_idx = 10 + (idx % 50)
        pc = 0x9000 + (idx << 4)

        api_bosc_LoadUnit_reset(env, max_cycles=8)
        issue = api_bosc_LoadUnit_send_mmio_load(
            env,
            rob_idx=rob_idx,
            lq_idx=lq_idx,
            sq_idx=0,
            pc=pc,
            pdest=(idx % 31) + 1,
            pmp_mmio_hint=True,
            debug_vaddr=debug_vaddr,
            debug_paddr=debug_paddr,
            debug_is_mmio=True,
            raw_data=raw_data,
            raw_addr_offset=0,
            raw_fu_op_type=3,
            max_cycles=12,
        )
        writeback = _first_mmio_writeback(env, cycles=8)

        assert issue["accepted"] is True, f"随机 MMIO 场景 #{idx} 请求必须被 DUT 接收"
        assert writeback is not None, f"随机 MMIO 场景 #{idx} 必须在 stage3 产生标量写回"
        assert writeback["data"] == raw_data, (
            f"随机 MMIO 场景 #{idx} raw_data 透传错误："
            f"expected=0x{raw_data:016x}, actual=0x{writeback['data']:016x}"
        )
        assert writeback["debug"]["vaddr"] == debug_vaddr, (
            f"随机 MMIO 场景 #{idx} debug.vaddr 错误："
            f"expected=0x{debug_vaddr:x}, actual=0x{writeback['debug']['vaddr']:x}"
        )
        assert writeback["debug"]["paddr"] == debug_paddr, (
            f"随机 MMIO 场景 #{idx} debug.paddr 错误："
            f"expected=0x{debug_paddr:x}, actual=0x{writeback['debug']['paddr']:x}"
        )
        assert writeback["debug"]["isMMIO"] == 1, f"随机 MMIO 场景 #{idx} 必须显式标记 isMMIO"
        assert writeback["uop"]["robIdx"]["value"] == rob_idx
        assert writeback["uop"]["lqIdx"]["value"] == lq_idx
