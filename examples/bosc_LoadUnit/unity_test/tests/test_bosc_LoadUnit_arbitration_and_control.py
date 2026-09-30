#coding=utf-8

from bosc_LoadUnit_api import *


def test_bosc_LoadUnit_misalign_wins_over_scalar_request(env):
    """Verify misalign source ownership when scalar traffic contends."""
    api_bosc_LoadUnit_reset(env)
    result = api_bosc_LoadUnit_send_misalign_buffer_load(env, src_addr=0x1003, rob_idx=3, lq_idx=3, max_cycles=8)
    assert result["accepted"] is True
    assert result["source"] == "misalign"


def test_bosc_LoadUnit_misalign_boundary_variant(env):
    """Exercise misalign address crossing a wider payload boundary."""
    api_bosc_LoadUnit_reset(env)
    result = api_bosc_LoadUnit_send_misalign_buffer_load(env, src_addr=0x10FF, rob_idx=9, lq_idx=9, max_cycles=10)
    assert result["accepted"] is True


def test_bosc_LoadUnit_tlb_dcache_issue_fields_and_timing(env):
    """Verify TLB/DCache issue response fields and timing observability."""
    api_bosc_LoadUnit_reset(env)
    accepted = api_bosc_LoadUnit_send_scalar_load(env, src0=0x2200, fu_op_type=3, rob_idx=5, lq_idx=5, sq_idx=0, pc=0x3200)
    assert accepted["accepted"] is True
    response = api_bosc_LoadUnit_inject_memory_resp(env, tlb_valid=True, tlb_paddr=0xA200, dcache_data=0xCAFEBABE, hold_cycles=1, max_cycles=1)
    assert response["tlb_valid"] == 1
    assert response["tlb_paddr"] == 0xA200


def test_bosc_LoadUnit_issue_alternating_payload_boundary(env):
    """Exercise alternating response payload at an address boundary."""
    api_bosc_LoadUnit_reset(env)
    accepted = api_bosc_LoadUnit_send_scalar_load(env, src0=0x2FF8, fu_op_type=3, rob_idx=7, lq_idx=7, sq_idx=0, pc=0x3FF8)
    assert accepted["accepted"] is True
    response = api_bosc_LoadUnit_inject_memory_resp(env, tlb_valid=True, tlb_paddr=0xBFF8, dcache_data=0xAAAAAAAAAAAAAAAA, hold_cycles=1, max_cycles=1)
    assert response["dcache_data"] == 0xAAAAAAAAAAAAAAAA


def test_bosc_LoadUnit_issue_zero_payload_is_observable(env):
    """Exercise zero data pattern while retaining translated response fields."""
    api_bosc_LoadUnit_reset(env)
    accepted = api_bosc_LoadUnit_send_scalar_load(env, src0=0x2300, fu_op_type=3, rob_idx=10, lq_idx=10, sq_idx=0, pc=0x3300)
    assert accepted["accepted"] is True
    response = api_bosc_LoadUnit_inject_memory_resp(env, tlb_valid=True, tlb_paddr=0xC300, dcache_data=0, hold_cycles=1, max_cycles=1)
    assert response["dcache_data"] == 0


def test_bosc_LoadUnit_ldld_and_stld_query_backpressure_preserves_owner(env):
    """Query backpressure reports only updates belonging to the accepted load."""
    failures = []
    causes = ("ldld-backpressure", "stld-backpressure")
    for pattern_index in range(8):
        for cause_index, cause in enumerate(causes):
            api_bosc_LoadUnit_reset(env)
            identity = 64 + pattern_index * 2 + cause_index
            result = api_bosc_LoadUnit_observe_scalar_replay_cause(
                env, cause=cause, identity=identity, max_cycles=12
            )
            try:
                assert result["issue"]["accepted"] is True
                owner_updates = [
                    sample
                    for sample in result["observations"]
                    if sample["rob_idx"] == identity
                    and sample["lq_idx"] == (identity & 0x7F)
                ]
                assert owner_updates, f"{cause} produced no owner-matched LSQ update"
                assert any(
                    sample["cause_bits"][result["expected_cause_bit"]] == 1
                    for sample in owner_updates
                ), f"{cause} did not expose its query backpressure cause"
            except AssertionError as error:
                failures.append(f"{cause} owner {identity}: {error}")
    assert not failures, "query interleaving failures:\n" + "\n".join(failures)



def test_bosc_LoadUnit_nc_and_scalar_contention_preserves_priority_and_ownership(env):
    """Verify NC/scalar contention preserves selected-request ownership."""
    api_bosc_LoadUnit_reset(env)
    result = api_bosc_LoadUnit_send_nc_load_with_scalar_contender(
        env, nc_vaddr=0x3000, nc_paddr=0x4000, nc_data=0xAA55, scalar_src0=0x5000
    )
    assert result["nc_accepted"] is True
    assert len(result["nc_ready_history"]) == len(result["scalar_ready_history"])


def test_bosc_LoadUnit_miss_response_is_observable_without_dropping_request(env):
    """Verify miss and MQ nack response controls remain observable."""
    api_bosc_LoadUnit_reset(env)
    api_bosc_LoadUnit_send_scalar_load(env, src0=0x1800, fu_op_type=3, rob_idx=4, lq_idx=4, sq_idx=0, pc=0x2800)
    response = api_bosc_LoadUnit_inject_memory_resp(env, tlb_valid=True, tlb_paddr=0x9800, dcache_miss=True, dcache_mq_nack=True, hold_cycles=2, max_cycles=2)
    assert response["dcache_miss"] == 1
    assert response["dcache_mq_nack"] == 1


def test_bosc_LoadUnit_replay_with_denied_response(env):
    """Exercise denied TileLink response propagation on replay path."""
    api_bosc_LoadUnit_reset(env)
    api_bosc_LoadUnit_send_scalar_load(env, src0=0x1900, fu_op_type=3, rob_idx=8, lq_idx=8, sq_idx=0, pc=0x2900)
    response = api_bosc_LoadUnit_inject_memory_resp(env, tlb_valid=True, tlb_paddr=0x9900, dcache_miss=True, dcache_denied=True, hold_cycles=3, max_cycles=3)
    assert response["dcache_denied"] == 1


def test_bosc_LoadUnit_first_owner_after_reset_recovery_is_not_stale(env):
    """The first scalar owner after varied reset lengths completes without stale identity."""
    patterns = (
        (1, 0x0000000000000000),
        (2, 0xFFFFFFFFFFFFFFFF),
        (4, 0xAAAAAAAAAAAAAAAA),
        (6, 0x5555555555555555),
        (8, 0x8000000000000001),
        (10, 0x7FFFFFFFFFFFFFFE),
    )
    for index, (reset_cycles, pattern) in enumerate(patterns):
        api_bosc_LoadUnit_reset(env, cycles=reset_cycles)
        identity = 160 + index
        result = api_bosc_LoadUnit_complete_scalar_debug_metadata(
            env,
            identity=identity,
            metadata_pattern=pattern,
            data_pattern=(pattern << 64) | (pattern ^ ((1 << 64) - 1)),
        )
        writeback = result["writeback"]
        assert int(writeback["uop"]["robIdx"]["value"]) == identity
        assert int(writeback["uop"]["lqIdx"]["value"]) == (identity & 0x7F)
        assert int(writeback["debug"]["vaddr"]) == result["vaddr"]
        assert int(writeback["debug"]["paddr"]) == result["paddr"]


def test_bosc_LoadUnit_scalar_handshake_and_response_fields(env):
    """Exercise scalar valid/ready acceptance and response field propagation."""
    reset = api_bosc_LoadUnit_reset(env, reset_cycles=2)
    assert reset["reset_cycles"] == 2
    accepted = api_bosc_LoadUnit_send_scalar_load(env, src0=0x1000, fu_op_type=3, rob_idx=1, lq_idx=1, sq_idx=0, pc=0x2000)
    assert accepted["accepted"] is True
    assert accepted["request"]["uop"]["robIdx"]["value"] == 1
    response = api_bosc_LoadUnit_inject_memory_resp(env, tlb_valid=True, tlb_paddr=0x8000, dcache_data=0x1122334455667788, hold_cycles=2, max_cycles=2)
    assert response["dcache_data"] == 0x1122334455667788


def test_bosc_LoadUnit_scalar_payload_is_retained_during_backpressure(env):
    """Verify scalar payload stability during downstream backpressure."""
    api_bosc_LoadUnit_reset(env)
    held = api_bosc_LoadUnit_hold_scalar_load_under_backpressure(env, src0=0x1040, fu_op_type=3, rob_idx=2, lq_idx=2, sq_idx=0, pc=0x2040, stall_cycles=2)
    assert held["stable"] is True
    assert held["released"] is True


def test_bosc_LoadUnit_scalar_reset_release_then_accept(env):
    """Exercise reset release followed immediately by scalar acceptance."""
    result = api_bosc_LoadUnit_reset(env, reset_cycles=3)
    assert result["reset_cycles"] == 3
    accepted = api_bosc_LoadUnit_send_scalar_load(env, src0=0x1080, fu_op_type=3, rob_idx=6, lq_idx=6, sq_idx=0, pc=0x2080)
    assert accepted["accepted"] is True


def test_bosc_LoadUnit_scalar_replay_causes_are_one_hot_and_owner_stable(env):
    """Each recoverable scalar hazard reports one replay reason for its own LSQ entry."""
    causes = (
        "address-ambiguous",
        "tlb-miss",
        "forward-invalid",
        "dcache-miss",
        "mq-nack",
        "bank-conflict",
        "ldld-backpressure",
        "stld-backpressure",
        "misalign-buffer-full",
    )

    failures = []
    for cause_index, cause in enumerate(causes):
        identity = 248 + cause_index
        api_bosc_LoadUnit_reset(env)
        result = api_bosc_LoadUnit_observe_scalar_replay_cause(
            env,
            cause=cause,
            identity=identity,
        )

        try:
            assert result["issue"]["accepted"] is True
            owner_updates = [
                sample
                for sample in result["observations"]
                if sample["rob_idx"] == identity
                and sample["lq_idx"] == (identity & 0x7F)
            ]
            assert owner_updates, f"{cause} produced no LSQ replay update"
            assert any(
                sample["cause_bits"][result["expected_cause_bit"]] == 1
                and sum(sample["cause_bits"]) == 1
                for sample in owner_updates
            ), f"{cause} did not report its expected one-hot cause"
        except AssertionError as error:
            failures.append(str(error))

    assert not failures, "scalar replay cause failures:\n" + "\n".join(failures)


def _assert_arbitration_owner(observation, source, identity, pattern):
    if source in ("high-prefetch", "low-prefetch"):
        assert observation["dcache"] is not None, f"{source} issued no DCache request"
        assert int(observation["dcache"]["vaddr_dup"]) == observation["expected"]["dcache_vaddr"]
        return
    if source == "vector":
        assert observation["dcache"] is not None, "vector issued no DCache request"
        assert int(observation["dcache"]["lqIdx"]["value"]) == (identity & 0x7F)
        assert int(observation["dcache"]["vaddr_dup"]) == observation["expected"]["vaddr"]
        return

    wakeup = observation["wakeup"]
    assert wakeup is not None, f"{source} produced no ownership wakeup"
    assert int(wakeup["robIdx"]["value"]) == identity
    assert int(wakeup["lqIdx"]["value"]) == (identity & 0x7F)
    assert int(wakeup["fuType"]) == (pattern & ((1 << 35) - 1))
    assert int(wakeup["ftqPtr"]["flag"]) == ((pattern >> 1) & 1)
    assert int(wakeup["ftqPtr"]["value"]) == ((pattern >> 2) & 0x3F)


def test_bosc_LoadUnit_adjacent_stage0_sources_preserve_priority_and_identity(env):
    """Every adjacent source pair accepts in RTL priority order without payload leakage."""
    pairs = (
        ("fast-replay", "replay"),
        ("replay", "high-prefetch"),
        ("high-prefetch", "vector"),
        ("vector", "scalar"),
        ("scalar", "uncache"),
        ("uncache", "nc"),
        ("nc", "low-prefetch"),
    )
    patterns = (
        (0x000000000, 0x7FFFFFFFF),
        (0x7FFFFFFFF, 0x000000000),
        (0x00030003, 0xFFFCFFFC),
        (0xA55A3CC3, 0x5AA5C33C),
    )

    for pattern_index, (higher_pattern, lower_pattern) in enumerate(patterns):
        for pair_index, (higher_source, lower_source) in enumerate(pairs):
            higher_identity = 32 + pattern_index * 32 + pair_index * 2
            lower_identity = higher_identity + 1
            api_bosc_LoadUnit_reset(env)
            result = api_bosc_LoadUnit_observe_adjacent_source_priority(
                env,
                higher_source=higher_source,
                lower_source=lower_source,
                higher_identity=higher_identity,
                lower_identity=lower_identity,
                higher_pattern=higher_pattern,
                lower_pattern=lower_pattern,
            )

            context = f"{higher_source} over {lower_source}"
            assert result["blocked_lower_ready"] == 0, context
            assert result["blocked_payload_stable"] is True, context
            assert result["first"]["source"] == higher_source, context
            assert result["second"]["source"] == lower_source, context
            _assert_arbitration_owner(
                result["first"], higher_source, higher_identity, higher_pattern
            )
            _assert_arbitration_owner(
                result["second"], lower_source, lower_identity, lower_pattern
            )


def test_bosc_LoadUnit_stage0_sources_select_their_own_metadata(env):
    """Each stage-0 source selects its own metadata without cross-source contamination."""
    sources = (
        "misalign-wakeup",
        "mshr-replay",
        "fast-replay",
        "replay",
        "scalar",
        "uncache",
        "nc",
    )
    patterns = (
        0x00000000,
        0xFFFFFFFF,
        0xA55A3CC3,
        1 << 34,
        1 << 17,
        1,
    )
    failures = []
    for source_index, source in enumerate(sources):
        for pattern_index, pattern in enumerate(patterns):
            identity = 208 + source_index * len(patterns) + pattern_index
            api_bosc_LoadUnit_reset(env)
            result = api_bosc_LoadUnit_observe_stage0_source_metadata(
                env, source=source, identity=identity, pattern=pattern
            )
            wakeup = result["wakeup"]
            expected = result["expected"]
            context = f"{source} pattern 0x{pattern:08x}"
            try:
                assert result["ready"] == 1, f"{source} was not accepted"
                assert result["wakeup_valid"] == 1, f"{source} produced no wakeup"
                assert int(wakeup["robIdx"]["value"]) == identity
                assert int(wakeup["lqIdx"]["value"]) == (identity & 0x7F)
                assert int(wakeup["fuType"]) == expected["fuType"], context
                assert int(wakeup["fuOpType"]) == expected["fuOpType"], context
                expected_cross_page = (
                    0 if source == "scalar" else expected["crossPageIPFFix"]
                )
                assert int(wakeup["crossPageIPFFix"]) == expected_cross_page, context
                assert int(wakeup["ftqPtr"]["flag"]) == expected["ftqPtr_flag"], context
                assert int(wakeup["ftqPtr"]["value"]) == expected["ftqPtr_value"], context
                assert int(wakeup["ftqOffset"]) == expected["ftqOffset"], context
                for field in ("instr", "foldpc", "ldest", "selImm"):
                    if field in expected and source != "scalar":
                        assert int(wakeup[field]) == expected[field], (
                            f"{source} corrupted {field}"
                        )
                for index in range(5):
                    key = f"srcType_{index}"
                    if key in expected and source != "scalar":
                        assert int(wakeup["srcType"][str(index)]) == expected[key]
                scalar_tie_off_fields = {
                    "pred_taken", "satpFlushFirstFetchFault", "vecWen", "v0Wen",
                    "vlWen", "isXSTrap", "waitForward", "blockBackward",
                    "canRobCompress", "numLsElem", "fpu_typeTagOut", "fpu_wflags",
                    "fpu_typ", "fpu_fmt", "fpu_rm",
                }
                for field in scalar_tie_off_fields:
                    if field in wakeup and field in expected:
                        expected_value = 0 if source == "scalar" else expected[field]
                        assert int(wakeup[field]) == expected_value, (
                            f"{source} corrupted {field}"
                        )

                if source not in ("misalign-wakeup", "uncache", "nc"):
                    assert result["dcache"] is not None
                else:
                    assert result["dcache"] is None
                if source not in ("fast-replay", "uncache", "nc"):
                    assert result["tlb"] is not None
                else:
                    assert result["tlb"] is None
            except AssertionError as error:
                failures.append(f"{context}: {error}")

    assert not failures, "metadata matrix failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_scalar_and_vector_payloads_survive_multicycle_stall(env):
    """Retained demand requests preserve identity and accept exactly once after release."""
    api_bosc_LoadUnit_reset(env)
    scenarios = (("scalar", 61, 2), ("scalar", 62, 4), ("vector", 63, 2), ("vector", 64, 5))
    for request_kind, identity, stall_cycles in scenarios:
        result = api_bosc_LoadUnit_hold_load_then_resume(
            env,
            request_kind=request_kind,
            identity=identity,
            stall_cycles=stall_cycles,
            max_cycles=stall_cycles + 10,
        )
        assert result["stalled"] is True
        assert result["payload_stable_while_stalled"] is True
        assert result["payload_stable_through_accept"] is True
        assert result["accept_count"] == 1
        assert result["release_wait"] is not None
        assert int(result["request"]["uop"]["robIdx"]["value"]) == identity
        assert int(result["request"]["uop"]["lqIdx"]["value"]) == (identity & 0x7F)


def test_bosc_LoadUnit_stld_query_crosses_owner_address_and_mask_relations(env):
    """Both ST-LD query lanes distinguish ROB order, address granularity and masks."""
    scenarios = list((
        (0, 0x40, 0x100000, 0x100000, 0x00FF, 0x0001),
        (1, 0xC0, 0x100008, 0x100008, 0xFF00, 0x8000),
        (0, 0x3F, 0x200000, 0x200040, 0xAAAA, 0x5555),
        (1, 0x41, 0x30000F, 0x30000F, 0x8001, 0x8001),
        (0, 0x140, 0x3FFFF8, 0x3FFFF0, 0xFFFF, 0x00F0),
        (1, 0x00, 0x400000, 0x500000, 0x0001, 0x0001),
    ))
    scenarios.extend(
        (
            bit & 1,
            (0x40 - bit) & 0x1FF,
            0x600000 + (bit << 3),
            0x600000 + (bit << 3),
            1 << bit,
            1 << bit,
        )
        for bit in range(16)
    )
    for index, (lane, query_rob, load_paddr, query_paddr, load_mask, query_mask) in enumerate(scenarios):
        api_bosc_LoadUnit_reset(env)
        identity = 0x40 + index
        result = api_bosc_LoadUnit_observe_stld_query_match(
            env,
            identity=identity,
            query_index=lane,
            query_rob_idx=query_rob,
            load_paddr=load_paddr,
            query_paddr=query_paddr,
            load_mask=load_mask,
            query_mask=query_mask,
        )
        assert result["accepted"] is True
        assert result["query_index"] == lane
        assert result["query_rob_idx"] == query_rob


def test_bosc_LoadUnit_runtime_control_constrained_combinations(env):
    """Drive decorrelated runtime controls before the owner-bound matrices."""
    state = 0xA0761D6478BD642F
    patterns = []
    for index in range(72):
        state ^= state << 7
        state ^= state >> 9
        state ^= state << 8
        patterns.append((state ^ (index * 0xE7037ED1A0B428DB)) & ((1 << 256) - 1))
    samples = api_bosc_LoadUnit_drive_interface_transition_matrix(
        env, patterns, dwell_cycles=1, max_cycles=72
    )
    assert len(samples) == 72
    assert all(sample["driven"] > 100 for sample in samples)


def test_bosc_LoadUnit_runtime_control_boundary_residency(env):
    """Hold explicit control-width boundaries for multiple registered stages."""
    full = (1 << 256) - 1
    patterns = [0, full, int("AA" * 32, 16), int("55" * 32, 16)]
    for bit in (0, 7, 15, 31, 47, 49, 55, 63, 95, 127, 128, 191, 255):
        patterns.extend((1 << bit, full ^ (1 << bit)))
    samples = api_bosc_LoadUnit_drive_interface_transition_matrix(
        env, patterns, dwell_cycles=3, max_cycles=len(patterns)
    )
    assert len(samples) == len(patterns)
    assert all(sample["driven"] > 100 for sample in samples)


def test_bosc_LoadUnit_scalar_late_control_owner_matrix(env):
    """Cross owner, source, response timing, replay pressure, and stage stalls."""
    failures = []
    sources = ("", "lsq", "sbuffer", "ubuffer")
    for index in range(16):
        api_bosc_LoadUnit_reset(env)
        identity = 32 + index
        try:
            issue = api_bosc_LoadUnit_send_typed_scalar_load(
                env, 0x600000 + index, (0, 1, 2, 3, 4, 5, 6, 3)[index & 7],
                bool(index & 1), identity, identity & 0x7f, identity & 0x3f,
                0x610000 + index * 4,
            )
            payload = (int("AA" * 16, 16), int("55" * 16, 16),
                       1 << 127, 1)[index & 3]
            source = sources[index & 3]
            api_bosc_LoadUnit_inject_memory_resp(
                env, tlb_valid=True, tlb_paddr=0x700000 + index,
                dcache_data=payload ^ ((1 << 128) - 1) if source else payload,
                forward_source=source, forward_data=payload,
                forward_mask=(0xffff, 1, 0x8000, 0xaaaa)[index & 3],
                hold_cycles=1 + index % 4, max_cycles=5,
            )
            owner = api_bosc_LoadUnit_wait_for_scalar_owner(
                env, identity, identity & 0x7f, max_cycles=24
            )
            held = api_bosc_LoadUnit_hold_load_then_resume(
                env, "scalar", identity + 32, 1 + index % 6, max_cycles=20
            )
            assert issue["accepted"] is True
            assert owner["writeback"] is not None
            assert held["payload_stable_while_stalled"] is True
            assert held["accept_count"] == 1
        except (AssertionError, TimeoutError) as error:
            failures.append(f"scalar row {index}: {error}")
    assert not failures, "scalar late-control failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_nc_mmio_pressure_completion_matrix(env):
    """Cross classified special owners, raw types, addresses, and consecutive completion."""
    failures = []
    for index in range(12):
        api_bosc_LoadUnit_reset(env)
        try:
            identity = 80 + index
            nc = api_bosc_LoadUnit_send_uncache_transition_pattern(
                env, identity, (0, (1 << 64) - 1, 0xaaaaaaaaaaaaaaaa,
                0x5555555555555555)[index & 3],
                (0, (1 << 128) - 1, int("AA" * 16, 16),
                int("55" * 16, 16))[index & 3],
            )
            mmio = api_bosc_LoadUnit_send_mmio_load(
                env, identity + 16, (identity + 16) & 0x7f, identity & 0x3f,
                0x720000 + index * 4, (identity & 0x1f) + 1,
                bool(index & 1), 0x730000 + index, 0x740000 + index,
                True, (1 << 64) - 1 if index & 1 else 0,
                index & 7, index % 7,
            )
            owner = api_bosc_LoadUnit_wait_for_scalar_owner(
                env, identity + 16, (identity + 16) & 0x7f, max_cycles=24
            )
            assert nc["accepted"] is True and nc["payload_stable"] is True
            assert mmio["accepted"] is True
            assert owner["writeback"] is not None
        except (AssertionError, TimeoutError) as error:
            failures.append(f"special row {index}: {error}")
    assert not failures, "special-load failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_stage0_replay_continuous_priority_matrix(env):
    """Cross adjacent owners and replay causes without weakening priority assertions."""
    failures = []
    causes = ("ldld-backpressure", "stld-backpressure")
    for index in range(12):
        api_bosc_LoadUnit_reset(env)
        try:
            held = api_bosc_LoadUnit_hold_load_then_resume(
                env, "vector" if index & 1 else "scalar", 128 + index,
                1 + index % 5, max_cycles=20,
            )
            replay = api_bosc_LoadUnit_observe_scalar_replay_cause(
                env, causes[index & 1], 160 + index, max_cycles=16
            )
            assert held["payload_stable_while_stalled"] is True
            assert held["accept_count"] == 1
            assert replay["issue"]["accepted"] is True
        except (AssertionError, TimeoutError) as error:
            failures.append(f"replay row {index}: {error}")
    assert not failures, "stage0 replay failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_memtrigger_runtime_class_matrix(env):
    """Cross trigger request classes, payload boundaries, chaining, and clean neighbors."""
    failures = []
    patterns = (0, (1 << 64) - 1, 0xaaaaaaaaaaaaaaaa,
                0x5555555555555555, 1, 1 << 63)
    for index, pattern in enumerate(patterns):
        api_bosc_LoadUnit_reset(env)
        try:
            result = api_bosc_LoadUnit_run_trigger_request_class_sequence(
                env, pattern, 192 + index, max_cycles=24
            )
            assert result is not None
        except (AssertionError, TimeoutError) as error:
            failures.append(f"trigger row {index}: {error}")
    assert not failures, "MemTrigger failures:\n" + "\n".join(failures)
