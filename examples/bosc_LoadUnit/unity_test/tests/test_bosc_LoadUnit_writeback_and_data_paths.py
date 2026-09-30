#coding=utf-8

from bosc_LoadUnit_api import *


def test_bosc_LoadUnit_source_physical_addresses_toggle_independently(env):
    """DCache, LSU, SBuffer and UBuffer physical-address inputs cross wide patterns."""
    patterns = [0, (1 << 48) - 1, 0xAAAAAAAAAAAA, 0x555555555555]
    patterns.extend(1 << bit for bit in range(0, 48, 3))
    samples = api_bosc_LoadUnit_drive_source_paddr_transitions(env, patterns)
    assert len(samples) == len(patterns)
    assert samples[0]["io_dcache_s1_paddr_dup_lsu"] == 0
    assert samples[1]["io_dcache_s1_paddr_dup_lsu"] == ((1 << 48) - 1)


def test_bosc_LoadUnit_cached_and_forwarded_sources_select_owner_data(env):
    """DCache and forward sources select distinct byte windows without owner leakage."""
    sources = (
        ("", 0x00112233445566778899AABBCCDDEEFF),
        ("lsq", 0xFFEEDDCCBBAA99887766554433221100),
        ("sbuffer", 0x807F00FF55AA33CC1020304050607080),
        ("ubuffer", 0x7F0080FFAA55CC33FFEEDDCCBBAA9988),
    )
    failures = []
    for source_index, (forward_source, data) in enumerate(sources):
        for offset in range(16):
            api_bosc_LoadUnit_reset(env)
            identity = 64 + source_index * 16 + offset
            vaddr = 0x300000 + source_index * 0x1000 + offset
            paddr = 0x400000 + source_index * 0x1000 + offset
            try:
                issue = api_bosc_LoadUnit_send_typed_scalar_load(
                    env, vaddr, 3, False, identity, identity & 0x7F,
                    identity & 0x3F, vaddr + 4
                )
                api_bosc_LoadUnit_inject_memory_resp(
                    env,
                    tlb_valid=True,
                    tlb_paddr=paddr,
                    dcache_data=data ^ ((1 << 128) - 1) if forward_source else data,
                    forward_source=forward_source,
                    forward_data=data,
                    forward_mask=0xFFFF,
                    hold_cycles=2,
                    max_cycles=2,
                )
                capture = api_bosc_LoadUnit_wait_for_scalar_owner(
                    env, identity, identity & 0x7F, max_cycles=16
                )
                writeback = capture["writeback"]
                expected = (data >> (8 * offset)) & ((1 << 64) - 1)
                assert issue["accepted"] is True
                assert int(writeback["data"]) == expected
                assert int(writeback["uop"]["robIdx"]["value"]) == identity
                assert int(writeback["debug"]["vaddr"]) == vaddr
                assert int(writeback["debug"]["paddr"]) == paddr
            except (AssertionError, TimeoutError) as error:
                failures.append(f"source {forward_source or 'dcache'} offset {offset}: {error}")
    assert not failures, "data-source failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_translation_protection_and_tl_errors_are_owner_bound(env):
    """Fault responses suppress clean-owner behavior and remain transaction scoped."""
    scenarios = (
        ("clean", 0),
        ("tlb-pf", 0),
        ("tlb-gpf", 1),
        ("tlb-af", 2),
        ("pmp-ld", 0),
        ("pmp-mmio", 1),
        ("dcache-denied", 0),
        ("dcache-corrupt", 1),
        ("denied-corrupt", 2),
    )
    failures = []
    for index, (fault_kind, response_delay) in enumerate(scenarios):
        api_bosc_LoadUnit_reset(env)
        identity = 144 + index
        result = api_bosc_LoadUnit_run_scalar_fault_response(
            env, identity, fault_kind, response_delay
        )
        try:
            assert result["issue"]["accepted"] is True
            assert result["injection"]["tlb_valid"] == 1
            assert result["injection"]["dcache_denied"] == int(
                fault_kind in {"dcache-denied", "denied-corrupt"}
            )
            assert result["injection"]["dcache_corrupt"] == int(
                fault_kind in {"dcache-corrupt", "denied-corrupt"}
            )
            assert result["outputs"] is not None, "no observable output"
            scalar = result["outputs"]["scalar_writeback"]
            if fault_kind == "clean":
                assert scalar is not None
                assert int(scalar["uop"]["robIdx"]["value"]) == identity
            else:
                assert scalar is None, "produced a normal scalar writeback"
        except AssertionError as error:
            failures.append(f"{fault_kind} owner {identity}: {error}")
    assert not failures, "fault propagation failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_scalar_metadata_patterns_preserve_completion_owner(env):
    """Wide uop metadata patterns flow with the owning scalar transaction."""
    patterns = (0x00000000, 0xFFFFFFFF, 0xAAAAAAAA, 0x55555555, 0x8001003F)
    for index, pattern in enumerate(patterns):
        identity = 132 + index
        result = api_bosc_LoadUnit_complete_scalar_metadata_pattern(
            env,
            identity=identity,
            metadata_pattern=pattern,
            data_pattern=(pattern << 96) | ((~pattern & 0xFFFFFFFF) << 64) | pattern,
        )
        writeback = result["writeback"]
        assert int(writeback["uop"]["robIdx"]["value"]) == identity
        assert int(writeback["uop"]["lqIdx"]["value"]) == (identity & 0x7F)
        assert int(writeback["uop"]["pdest"]) == ((pattern & 0xFF) or 1)
        assert int(writeback["uop"]["debug_seqNum"]["seqNum"]) == (pattern & ((1 << 56) - 1))
        assert int(writeback["uop"]["debug_seqNum"]["uopIdx"]) == ((pattern >> 8) & 0xFF)
        assert int(writeback["uop"]["preDecodeInfo"]["valid"]) == (pattern & 1)
        assert int(writeback["debug"]["vaddr"]) == result["vaddr"]
        assert int(writeback["debug"]["paddr"]) == result["paddr"]


def test_bosc_LoadUnit_direct_mshr_forward_data_preserves_query_and_owner(env):
    """Direct MSHR replies use all byte offsets while preserving query and owner identity."""
    patterns = (
        0x00112233445566778899AABBCCDDEEFF,
        0xFF00EE11DD22CC33BB44AA5599668877,
    )
    for pattern_index, data_128 in enumerate(patterns):
        for offset in range(16):
            identity = 176 + pattern_index * 16 + offset
            paddr = 0xA0000 + pattern_index * 0x1000 + offset
            mshr_id = (pattern_index * 8 + offset) & 0xF
            api_bosc_LoadUnit_reset(env)
            result = api_bosc_LoadUnit_complete_direct_mshr_forward(
                env,
                identity=identity,
                paddr=paddr,
                mshr_id=mshr_id,
                data_128=data_128,
            )
            writeback = result["writeback"]
            expected = (data_128 >> (8 * offset)) & ((1 << 64) - 1)

            assert result["query"]["mshr_id"] == mshr_id
            assert result["query"]["paddr"] == paddr
            assert int(writeback["data"]) == expected
            assert int(writeback["uop"]["robIdx"]["value"]) == identity
            assert int(writeback["uop"]["lqIdx"]["value"]) == (identity & 0x7F)
            assert int(writeback["debug"]["paddr"]) == paddr


def test_bosc_LoadUnit_tl_d_refill_selects_matching_beat_window_and_owner(env):
    """Matching TL-D refills select the addressed beats and preserve replay identity."""
    payloads = (
        0x0000000000000000000000000000000000000000000000000000000000000000,
        0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,
        0xAA55AA55AA55AA5555AA55AA55AA55AAAA55AA55AA55AA5555AA55AA55AA55AA,
        0x0123456789ABCDEFFEDCBA987654321000112233445566778899AABBCCDDEEFF,
    )
    offsets = (0x00, 0x08, 0x10, 0x18, 0x07, 0x0F, 0x17, 0x1F)

    api_bosc_LoadUnit_reset(env)
    for payload_index, data_256 in enumerate(payloads):
        for offset_index, offset in enumerate(offsets):
            identity = 96 + payload_index * 16 + offset_index
            paddr = 0xB0000 + payload_index * 0x1000 + offset
            mshr_id = (payload_index * 5 + offset_index) & 0xF
            result = api_bosc_LoadUnit_complete_tl_d_replay(
                env,
                identity=identity,
                paddr=paddr,
                mshr_id=mshr_id,
                data_256=data_256,
            )
            writeback = result["writeback"]

            assert result["query"]["mshr_id"] == mshr_id
            assert result["query"]["paddr"] == paddr
            assert int(writeback["data"]) == result["expected_data"]
            assert int(writeback["uop"]["robIdx"]["value"]) == identity
            assert int(writeback["uop"]["lqIdx"]["value"]) == (identity & 0x7F)
            assert int(writeback["debug"]["paddr"]) == paddr


def test_bosc_LoadUnit_nc_second_pass_payload_identity_and_width_transitions(env):
    """Verify NC second-pass requests preserve full-width payload and transaction identity."""
    api_bosc_LoadUnit_reset(env, reset_cycles=2)
    full_width_mask = (1 << 128) - 1
    patterns = [
        (0xD000, 0x8000D000, 0, False, 3, 1),
        (0xD010, 0x8000D010, full_width_mask, True, 3, 0),
        (0xD020, 0x8000D020, int("AA" * 16, 16), True, 2, 1),
        (0xD030, 0x8000D030, int("55" * 16, 16), False, 6, 0),
        (0xD040, 0x8000D040, 0, True, 3, 1),
        ((1 << 49) - 0x10, (1 << 48) - 0x20, full_width_mask, True, 3, 0),
        (0x10, 0x20, int("AA" * 16, 16), False, 2, 1),
        (0x2AAAAAAAAAA0, 0x155555555550, int("55" * 16, 16), True, 6, 0),
        (0x155555555550, 0x2AAAAAAAAAA0, 0, False, 3, 1),
    ]
    results = []

    for index, (vaddr, paddr, data, is128bit, fu_op_type, store_set_hit) in enumerate(patterns):
        results.append(api_bosc_LoadUnit_send_nc_load(
            env,
            vaddr=vaddr,
            paddr=paddr,
            data=data,
            fu_op_type=fu_op_type,
            rob_idx=208 + index,
            lq_idx=104 + index,
            sq_idx=16 + index,
            pc=0x1800 + index * 4,
            pdest=8 + index,
            store_set_hit=store_set_hit,
            is128bit=is128bit,
            vec_active=index & 1,
        ))

    assert all(result["accepted"] for result in results)
    for index, (result, expected) in enumerate(zip(results, patterns)):
        vaddr, paddr, data, is128bit, fu_op_type, store_set_hit = expected
        request = result["request"]
        checks = {
            "vaddr": (int(request["vaddr"]), vaddr),
            "paddr": (int(request["paddr"]), paddr),
            "data": (int(request["data"]), data),
            "is128bit": (int(request["is128bit"]), int(is128bit)),
            "fuOpType": (int(request["uop"]["fuOpType"]), fu_op_type),
            "storeSetHit": (int(request["uop"]["storeSetHit"]), store_set_hit),
            "robIdx": (int(request["uop"]["robIdx"]["value"]), 208 + index),
            "lqIdx": (int(request["uop"]["lqIdx"]["value"]), 104 + index),
            "sqIdx": (int(request["uop"]["sqIdx"]["value"]), 16 + index),
        }
        for field, (actual, expected_value) in checks.items():
            assert actual == expected_value, (
                f"NC transaction {index} {field} identity mismatch: "
                f"expected {expected_value:#x}, observed {actual:#x}"
            )


def test_bosc_LoadUnit_uncache_wide_addresses_and_payload_preserve_owner(env):
    """Uncache completion carries legal address extremes and raw data exactly."""
    scenarios = (
        (0x0000000000000, 0x000000000000, 0x0000000000000000, 0, 0),
        (0x3FFFFFFFFFFFF, 0xFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF, 7, 3),
        (0x2AAAAAAAAAAAA, 0xAAAAAAAAAAAA, 0xAA55AA55AA55AA55, 3, 6),
        (0x1555555555555, 0x555555555555, 0x55AA55AA55AA55AA, 5, 0x1E),
    )
    for index, (vaddr, paddr, raw_data, offset, fu_op_type) in enumerate(scenarios):
        api_bosc_LoadUnit_reset(env)
        identity = 48 + index
        issue = api_bosc_LoadUnit_send_mmio_load(
            env,
            rob_idx=identity,
            lq_idx=identity & 0x7F,
            sq_idx=identity & 0x3F,
            pc=(vaddr + 4) & ((1 << 50) - 1),
            pdest=(identity & 0x1F) + 1,
            pmp_mmio_hint=True,
            debug_vaddr=vaddr,
            debug_paddr=paddr,
            debug_is_mmio=True,
            raw_data=raw_data,
            raw_addr_offset=offset,
            raw_fu_op_type=fu_op_type,
        )
        capture = api_bosc_LoadUnit_wait_for_scalar_owner(
            env, rob_idx=identity, lq_idx=identity & 0x7F, max_cycles=16
        )
        writeback = capture["writeback"]
        assert issue["accepted"] is True
        assert int(writeback["uop"]["robIdx"]["value"]) == identity
        assert int(writeback["uop"]["lqIdx"]["value"]) == (identity & 0x7F)
        assert int(writeback["debug"]["vaddr"]) == vaddr
        assert int(writeback["debug"]["paddr"]) == paddr
        assert int(writeback["debug"]["isMMIO"]) == 1



def _expected_window(data_128, offset):
    return (int(data_128) >> (8 * offset)) & ((1 << 64) - 1)


def _sign_extend(value, width):
    mask = (1 << width) - 1
    narrowed = int(value) & mask
    if narrowed & (1 << (width - 1)):
        narrowed |= ((1 << 64) - 1) ^ mask
    return narrowed & ((1 << 64) - 1)


def _expected_cached_load_data(data_128, offset, fu_op_type, fp_wen=False):
    selected = _expected_window(data_128, offset)
    if fu_op_type in (0, 0x10):
        return _sign_extend(selected, 8)
    if fu_op_type == 1 and fp_wen:
        return 0xFFFFFFFFFFFF0000 | (selected & 0xFFFF)
    if fu_op_type in (1, 0x11):
        return _sign_extend(selected, 16)
    if fu_op_type == 2 and fp_wen:
        return 0xFFFFFFFF00000000 | (selected & 0xFFFFFFFF)
    if fu_op_type in (2, 0x12):
        return _sign_extend(selected, 32)
    if fu_op_type in (3, 0x13):
        return selected
    if fu_op_type in (4, 0x14):
        return selected & 0xFF
    if fu_op_type in (5, 0x15, 0x1D):
        return selected & 0xFFFF
    if fu_op_type in (6, 0x16, 0x1E):
        return selected & 0xFFFFFFFF
    raise ValueError(f"unsupported cached load type: {fu_op_type}")


def _expected_mmio_load_data(raw_data, offset, fu_op_type):
    selected = (int(raw_data) >> (8 * offset)) & ((1 << 64) - 1)
    if fu_op_type in (0, 0x10):
        return _sign_extend(selected, 8)
    if fu_op_type in (1, 0x11):
        return _sign_extend(selected, 16)
    if fu_op_type in (2, 0x12):
        return _sign_extend(selected, 32)
    if fu_op_type in (3, 0x13):
        return selected
    if fu_op_type in (4, 0x14):
        return selected & 0xFF
    if fu_op_type in (5, 0x15, 0x1D):
        return selected & 0xFFFF
    if fu_op_type in (6, 0x16, 0x1E):
        return selected & 0xFFFFFFFF
    raise ValueError(f"unsupported MMIO load type: {fu_op_type}")


def test_bosc_LoadUnit_dcache_byte_offset_selects_exact_64bit_window(env):
    """Every byte offset selects the matching little-endian window and transaction owner."""
    patterns = (
        0x00112233445566778899AABBCCDDEEFF,
        0xFFEEDDCCBBAA99887766554433221100,
    )
    for pattern_index, data_128 in enumerate(patterns):
        for offset in range(16):
            identity = 80 + pattern_index * 16 + offset
            vaddr = 0x10000 + pattern_index * 0x1000 + offset
            paddr = 0x20000 + pattern_index * 0x1000 + offset
            api_bosc_LoadUnit_reset(env)
            issue = api_bosc_LoadUnit_send_scalar_load(
                env,
                src0=vaddr,
                fu_op_type=3,
                rob_idx=identity,
                lq_idx=identity & 0x7F,
                sq_idx=identity & 0x3F,
                pc=vaddr + 4,
            )
            api_bosc_LoadUnit_inject_memory_resp(
                env,
                tlb_valid=True,
                tlb_paddr=paddr,
                dcache_data=data_128,
                hold_cycles=2,
                max_cycles=2,
            )
            capture = api_bosc_LoadUnit_wait_for_scalar_owner(
                env, rob_idx=identity, lq_idx=identity & 0x7F, max_cycles=12
            )
            writeback = capture["writeback"]
            assert issue["accepted"] is True
            assert writeback is not None, f"offset {offset} produced no scalar writeback"
            assert int(writeback["data"]) == _expected_window(data_128, offset)
            assert int(writeback["uop"]["robIdx"]["value"]) == identity
            assert int(writeback["uop"]["lqIdx"]["value"]) == (identity & 0x7F)
            assert int(writeback["debug"]["vaddr"]) == vaddr
            assert int(writeback["debug"]["paddr"]) == paddr


def test_bosc_LoadUnit_cached_and_forwarded_load_types_select_exact_data(env):
    """Cached, LSQ-forwarded and SBuffer-forwarded loads share exact type semantics."""
    load_modes = (
        (0, False), (1, False), (2, False), (3, False), (4, False), (5, False),
        (6, False), (0x10, False), (0x11, False), (0x12, False), (0x13, False),
        (0x14, False), (0x15, False), (0x16, False), (0x1D, False), (0x1E, False),
        (1, True), (2, True),
    )
    sources = (
        ("dcache", "", 0x0123456789ABCDEFFEDCBA9876543210),
        ("lsq", "lsq", 0x80FF7F0100AA55CC1020304050607080),
        ("sbuffer", "sbuffer", 0x7F0080FF55AA33CCFFEEDDCCBBAA9988),
    )
    for source_index, (source_name, forward_source, source_data) in enumerate(sources):
        for mode_index, (fu_op_type, fp_wen) in enumerate(load_modes):
            offsets = range(16) if source_name == "dcache" or fu_op_type == 3 else (0, 7, 15)
            for offset in offsets:
                scenario = source_index * 288 + mode_index * 16 + offset
                identity = 144 + (scenario % 96)
                vaddr = 0x70000 + source_index * 0x4000 + mode_index * 0x100 + offset
                paddr = 0x78000 + source_index * 0x4000 + mode_index * 0x100 + offset
                selected_data = source_data if scenario % 2 == 0 else source_data ^ ((1 << 128) - 1)
                fallback_data = selected_data ^ 0x5AA55AA55AA55AA55AA55AA55AA55AA5

                api_bosc_LoadUnit_reset(env)
                issue = api_bosc_LoadUnit_send_typed_scalar_load(
                    env,
                    src0=vaddr,
                    fu_op_type=fu_op_type,
                    fp_wen=fp_wen,
                    rob_idx=identity,
                    lq_idx=identity & 0x7F,
                    sq_idx=identity & 0x3F,
                    pc=vaddr + 4,
                )
                injection = api_bosc_LoadUnit_inject_memory_resp(
                    env,
                    tlb_valid=True,
                    tlb_paddr=paddr,
                    dcache_data=selected_data if source_name == "dcache" else fallback_data,
                    forward_source=forward_source,
                    forward_data=selected_data,
                    forward_mask=0xFFFF,
                    hold_cycles=2,
                    max_cycles=2,
                )
                capture = api_bosc_LoadUnit_wait_for_scalar_owner(
                    env, rob_idx=identity, lq_idx=identity & 0x7F, max_cycles=12
                )
                writeback = capture["writeback"]
                expected = _expected_cached_load_data(selected_data, offset, fu_op_type, fp_wen)

                assert issue["accepted"] is True
                assert injection["forward_source"] == forward_source
                assert int(writeback["data"]) == expected, (
                    f"{source_name} type 0x{fu_op_type:x} fp={int(fp_wen)} "
                    f"offset {offset} selected wrong data"
                )
                assert int(writeback["uop"]["robIdx"]["value"]) == identity
                assert int(writeback["uop"]["lqIdx"]["value"]) == (identity & 0x7F)
                assert int(writeback["debug"]["vaddr"]) == vaddr
                assert int(writeback["debug"]["paddr"]) == paddr


def test_bosc_LoadUnit_mmio_raw_data_offset_preserves_owner_and_shift(env):
    """MMIO load types apply exact extension rules without corrupting transaction identity."""
    patterns = (0x0123456789ABCDEF, 0xFEDCBA9876543210)
    fu_op_types = (
        0, 1, 2, 3, 4, 5, 6,
        0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x1D, 0x1E,
    )
    for pattern_index, raw_data in enumerate(patterns):
        for type_index, fu_op_type in enumerate(fu_op_types):
            for offset in range(8):
                scenario = pattern_index * len(fu_op_types) * 8 + type_index * 8 + offset
                identity = 144 + (scenario % 96)
                vaddr = 0x30000 + pattern_index * 0x4000 + type_index * 0x100 + offset
                paddr = 0x40000 + pattern_index * 0x4000 + type_index * 0x100 + offset
                api_bosc_LoadUnit_reset(env)
                issue = api_bosc_LoadUnit_send_mmio_load(
                    env,
                    rob_idx=identity,
                    lq_idx=identity & 0x7F,
                    sq_idx=identity & 0x3F,
                    pc=vaddr + 4,
                    pdest=(identity & 0x1F) + 1,
                    pmp_mmio_hint=True,
                    debug_vaddr=vaddr,
                    debug_paddr=paddr,
                    debug_is_mmio=True,
                    raw_data=raw_data,
                    raw_addr_offset=offset,
                    raw_fu_op_type=fu_op_type,
                )
                capture = api_bosc_LoadUnit_wait_for_scalar_owner(
                    env, rob_idx=identity, lq_idx=identity & 0x7F, max_cycles=12
                )
                writeback = capture["writeback"]
                expected = _expected_mmio_load_data(raw_data, offset, fu_op_type)
                assert issue["accepted"] is True
                assert int(writeback["data"]) == expected, (
                    f"MMIO type 0x{fu_op_type:x} offset {offset} selected wrong data"
                )
                assert int(writeback["uop"]["robIdx"]["value"]) == identity
                assert int(writeback["uop"]["lqIdx"]["value"]) == (identity & 0x7F)
                assert int(writeback["debug"]["vaddr"]) == vaddr
                assert int(writeback["debug"]["paddr"]) == paddr


def test_bosc_LoadUnit_mmio_reserved_types_fail_closed_without_owner_corruption(env):
    """Reserved MMIO type bits propagate through the pipe but select no load data."""
    raw_data = 0xFEDCBA9876543210
    type_sequence = (0x000, 0x1E0, 0x000, 0x1FF, 0x000)

    api_bosc_LoadUnit_reset(env)
    for index, fu_op_type in enumerate(type_sequence):
        identity = 224 + index
        vaddr = 0xD0000 + index * 0x40
        paddr = 0xE0000 + index * 0x40
        issue = api_bosc_LoadUnit_send_mmio_load(
            env,
            rob_idx=identity,
            lq_idx=identity & 0x7F,
            sq_idx=identity & 0x3F,
            pc=vaddr + 4,
            pdest=(identity & 0x1F) + 1,
            pmp_mmio_hint=True,
            debug_vaddr=vaddr,
            debug_paddr=paddr,
            debug_is_mmio=True,
            raw_data=raw_data,
            raw_addr_offset=index & 0x7,
            raw_fu_op_type=fu_op_type,
        )
        capture = api_bosc_LoadUnit_wait_for_scalar_owner(
            env, rob_idx=identity, lq_idx=identity & 0x7F, max_cycles=12
        )
        writeback = capture["writeback"]
        expected = _expected_mmio_load_data(raw_data, index & 0x7, 0) if fu_op_type == 0 else 0

        assert issue["accepted"] is True
        assert int(writeback["data"]) == expected
        assert int(writeback["uop"]["robIdx"]["value"]) == identity
        assert int(writeback["uop"]["lqIdx"]["value"]) == (identity & 0x7F)
        assert int(writeback["debug"]["vaddr"]) == vaddr
        assert int(writeback["debug"]["paddr"]) == paddr
        assert int(writeback["debug"]["isMMIO"]) == 1


def test_bosc_LoadUnit_consecutive_mmio_owners_do_not_leak_payload(env):
    """Consecutive uncache completions keep raw payload and owner transitions isolated."""
    api_bosc_LoadUnit_reset(env)
    payloads = (
        0x0000000000000000,
        0xFFFFFFFFFFFFFFFF,
        0xAAAAAAAAAAAAAAAA,
        0x5555555555555555,
        0x8000000000000001,
        0x7FFFFFFFFFFFFFFE,
    ) + tuple(1 << bit for bit in range(0, 64, 4))
    previous_owner = None
    for index, payload in enumerate(payloads):
        identity = 96 + index
        result = api_bosc_LoadUnit_complete_uncache_debug_metadata(
            env,
            identity=identity,
            metadata_pattern=payload,
            raw_data=payload,
            address_offset=index & 0x7,
        )
        writeback = result["writeback"]
        assert int(writeback["uop"]["robIdx"]["value"]) == identity
        assert int(writeback["uop"]["lqIdx"]["value"]) == (identity & 0x7F)
        assert int(writeback["debug"]["vaddr"]) == result["vaddr"]
        assert int(writeback["debug"]["paddr"]) == result["paddr"]
        assert int(writeback["uop"]["debugInfo"]["runahead_checkpoint_id"]) == payload
        assert previous_owner != identity
        previous_owner = identity
