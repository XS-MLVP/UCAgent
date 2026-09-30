#coding=utf-8

from bosc_LoadUnit_api import *


def test_bosc_LoadUnit_high_confidence_prefetch_precedes_scalar_and_vector(env):
    """High-confidence prefetch owns the collision cycle, then releases its contender."""
    api_bosc_LoadUnit_reset(env)
    scenarios = (
        ("scalar", False),
        ("vector", False),
        ("scalar", True),
        ("vector", True),
    )
    for index, (competitor, is_store) in enumerate(scenarios):
        result = api_bosc_LoadUnit_observe_prefetch_priority(
            env,
            confidence=1,
            competitor=competitor,
            paddr=0x12345000 + index * 0x1000,
            identity=48 + index,
            is_store=is_store,
        )
        assert result["prefetch_accepts"] == 1
        assert result["competitor_accepts"] == 1
        assert result["history"][0]["high_accept"] == 1
        assert result["history"][0]["competitor_ready"] == 0
        assert result["payload_stable"] is True
        assert result["is_store"] == int(is_store)


def test_bosc_LoadUnit_low_confidence_prefetch_waits_for_scalar_and_vector(env):
    """Low-confidence prefetch remains suppressed until all demand traffic clears."""
    api_bosc_LoadUnit_reset(env)
    scenarios = (
        ("scalar", False),
        ("vector", False),
        ("scalar", True),
        ("vector", True),
    )
    for index, (competitor, is_store) in enumerate(scenarios):
        result = api_bosc_LoadUnit_observe_prefetch_priority(
            env,
            confidence=0,
            competitor=competitor,
            paddr=0x23456000 + index * 0x1000,
            identity=52 + index,
            is_store=is_store,
        )
        assert result["prefetch_accepts"] == 1
        assert result["competitor_accepts"] == 1
        assert result["history"][0]["low_accept"] == 0
        assert result["history"][0]["competitor_ready"] == 1
        assert result["payload_stable"] is True
        assert result["is_store"] == int(is_store)


def test_bosc_LoadUnit_ifetch_prefetch_preserves_address_and_bypasses_load_outputs(env):
    """Scalar instruction-prefetch requests update only the dedicated ifetch output."""
    addresses = (
        0x0000000000000,
        0x3FFFFFFFFFFFF,
        0x2AAAAAAAAAAAA,
        0x1555555555555,
    )

    api_bosc_LoadUnit_reset(env)
    for index, address in enumerate(addresses):
        result = api_bosc_LoadUnit_observe_ifetch_prefetch(
            env,
            vaddr=address,
            identity=232 + index,
        )
        assert result["accepted"] is True
        assert result["ifetch_vaddr"] == result["expected_vaddr"]
        assert result["dcache_seen"] is False
        assert result["wakeup_seen"] is False
        assert result["owner_writeback_seen"] is False


def test_bosc_LoadUnit_completed_demand_carries_full_width_training_metadata(env):
    """Completed demand loads retain wide metadata and owner identity."""
    patterns = (
        0x0000000000000000,
        0xFFFFFFFFFFFFFFFF,
        0xAAAAAAAAAAAAAAAA,
        0x5555555555555555,
        0x80000001000101FF,
    ) + tuple(1 << bit for bit in range(0, 64, 4))
    for index, pattern in enumerate(patterns):
        api_bosc_LoadUnit_reset(env)
        identity = 32 + index
        result = api_bosc_LoadUnit_complete_scalar_debug_metadata(
            env,
            identity=identity,
            metadata_pattern=pattern,
            data_pattern=((pattern << 64) | (pattern ^ ((1 << 64) - 1))),
        )
        writeback = result["writeback"]
        assert int(writeback["uop"]["robIdx"]["value"]) == identity
        assert int(writeback["uop"]["lqIdx"]["value"]) == (identity & 0x7F)
        assert int(writeback["uop"]["debug_seqNum"]["seqNum"]) == (
            pattern & ((1 << 56) - 1)
        )
        assert int(writeback["uop"]["debugInfo"]["runahead_checkpoint_id"]) == pattern
        assert int(writeback["debug"]["vaddr"]) == result["vaddr"]
        assert int(writeback["debug"]["paddr"]) == result["paddr"]


def test_bosc_LoadUnit_vector_mask_and_element_metadata(env):
    """Exercise vector mask, register offset, and element index metadata."""
    reset = api_bosc_LoadUnit_reset(env, reset_cycles=2)
    assert reset["reset_cycles"] == 2
    accepted = api_bosc_LoadUnit_send_vector_load(
        env,
        vaddr=0x6000,
        mask=0xA55A,
        reg_offset=3,
        elem_idx=5,
        elem_idx_inside_vd=9,
        aligned_type=1,
        rob_idx=11,
        lq_idx=11,
        pc=0x7000,
    )
    assert accepted["accepted"] is True
    assert accepted["request"]["mask"] == 0xA55A
    assert accepted["request"]["reg_offset"] == 3
    assert accepted["request"]["elemIdx"] == 5
    assert accepted["request"]["elemIdxInsideVd"] == 9


def test_bosc_LoadUnit_vector_alternating_mask_boundary(env):
    """Exercise alternating vector mask at an address boundary."""
    api_bosc_LoadUnit_reset(env, reset_cycles=3)
    accepted = api_bosc_LoadUnit_send_vector_load(
        env,
        vaddr=0x6FF0,
        mask=0xF0F0,
        reg_offset=15,
        elem_idx=31,
        elem_idx_inside_vd=63,
        aligned_type=2,
        rob_idx=12,
        lq_idx=12,
        pc=0x7FF0,
    )
    assert accepted["accepted"] is True
    assert accepted["request"]["mask"] == 0xF0F0


def test_bosc_LoadUnit_vector_full_mask_high_index(env):
    """Exercise full-lane mask and maximum element metadata."""
    api_bosc_LoadUnit_reset(env, reset_cycles=1)
    accepted = api_bosc_LoadUnit_send_vector_load(
        env, vaddr=0x7FF0, mask=0xFFFF, reg_offset=15, elem_idx=63,
        elem_idx_inside_vd=127, aligned_type=3, rob_idx=13, lq_idx=13, pc=0x8FF0
    )
    assert accepted["accepted"] is True
    assert accepted["request"]["mask"] == 0xFFFF
    assert accepted["request"]["elemIdx"] == 63


def test_bosc_LoadUnit_vector_sparse_mask_low_index(env):
    """Exercise sparse mask and low element metadata after recovery."""
    api_bosc_LoadUnit_reset(env, reset_cycles=4)
    accepted = api_bosc_LoadUnit_send_vector_load(
        env, vaddr=0x6100, mask=0x0001, reg_offset=1, elem_idx=1,
        elem_idx_inside_vd=2, aligned_type=0, rob_idx=14, lq_idx=14, pc=0x7100
    )
    assert accepted["accepted"] is True
    assert accepted["request"]["mask"] == 1


def test_bosc_LoadUnit_vector_checkerboard_mask(env):
    """Exercise checkerboard mask with a mid-range element index."""
    api_bosc_LoadUnit_reset(env, reset_cycles=2)
    accepted = api_bosc_LoadUnit_send_vector_load(env, vaddr=0x6200, mask=0xAAAA, reg_offset=7, elem_idx=17, elem_idx_inside_vd=33, aligned_type=1, rob_idx=15, lq_idx=15, pc=0x7200)
    assert accepted["accepted"] is True
    assert accepted["request"]["mask"] == 0xAAAA


def test_bosc_LoadUnit_vector_zero_mask_preserves_empty_lane_set(env):
    """Verify an accepted zero-mask request preserves an empty active-lane set."""
    api_bosc_LoadUnit_reset(env, reset_cycles=5)
    accepted = api_bosc_LoadUnit_send_vector_load(env, vaddr=0x6300, mask=0x0000, reg_offset=0, elem_idx=0, elem_idx_inside_vd=0, aligned_type=0, rob_idx=16, lq_idx=16, pc=0x7300)
    assert accepted["accepted"] is True
    assert accepted["request"]["mask"] == 0
    assert accepted["request"]["elemIdx"] == 0
    assert accepted["request"]["elemIdxInsideVd"] == 0

