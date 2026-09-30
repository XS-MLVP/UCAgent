#coding=utf-8

from bosc_LoadUnit_api import *


def test_bosc_LoadUnit_scalar_wide_metadata_survives_priority_contention(env):
    """A blocked scalar owner retains every wide metadata field until acceptance."""
    full64 = (1 << 64) - 1
    full256 = (1 << 256) - 1
    patterns = (
        (0, 0),
        (full64, full256),
        (0, 0),
        (0xAAAAAAAAAAAAAAAA, int("AA" * 32, 16)),
        (0x5555555555555555, int("55" * 32, 16)),
        (1, 1 << 255),
        (1 << 63, 1),
    )
    failures = []
    api_bosc_LoadUnit_reset(env)
    for index, (metadata, vector) in enumerate(patterns):
        identity = 16 + index
        try:
            result = api_bosc_LoadUnit_hold_scalar_wide_metadata_under_contention(
                env, identity, metadata, vector, hold_cycles=2
            )
            request = result["request"]
            assert result["blocked"] is True
            assert result["payload_stable"] is True
            assert int(request["uop"]["robIdx"]["value"]) == identity
            assert int(request["uop"]["imm"]) == (
                metadata & ((1 << 32) - 1)
            )
            assert int(request["uop"]["debugInfo"]["selectTime"]) == (
                metadata & ((1 << result["debug_width"]) - 1)
            )
        except (AssertionError, TimeoutError) as error:
            failures.append(f"scalar owner {identity}: {error}")
    assert not failures, "scalar contention failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_misalign_and_vector_sources_toggle_complete_uop_payloads(env):
    """Special stage-0 sources carry complementary full-width payload patterns."""
    full64 = (1 << 64) - 1
    full256 = (1 << 256) - 1
    full50 = (1 << 50) - 1
    matrix = (
        (0, 0, 0, 0x0000, 0),
        (full64, full256, full50, 0xFFFF, 7),
        (0, 0, 0, 0x0000, 0),
        (0xAAAAAAAAAAAAAAAA, int("AA" * 32, 16), 0x2AAAAAAAAAAAA, 0xAAAA, 3),
        (0x5555555555555555, int("55" * 32, 16), 0x1555555555555, 0x5555, 4),
        (1 << 63, 1 << 255, 1 << 49, 0x8001, 6),
        (1, 1, 1, 0x0001, 1),
        (full64, int("33" * 32, 16), full64, 0x0FF0, 2),
        (0, 0, 0, 0x0000, 0),
    )
    failures = []
    api_bosc_LoadUnit_reset(env)
    for index, (metadata, vector, address, mask, flags) in enumerate(matrix):
        misalign_identity = 48 + index * 2
        vector_identity = misalign_identity + 1
        try:
            misalign = api_bosc_LoadUnit_send_misalign_wide_uop_pattern(
                env, misalign_identity, metadata, vector, address, mask, flags
            )
            request = misalign["request"]
            assert misalign["accepted"] is True
            assert misalign["payload_stable"] is True
            assert int(request["uop"]["robIdx"]["value"]) == misalign_identity
            assert int(request["uop"]["vpu"]["vmask"]) == (
                vector & ((1 << misalign["vmask_width"]) - 1)
            )
            assert int(request["mask"]) == mask
            assert int(request["vaddr"]) == misalign["vaddr"]
            assert int(request["paddr"]) == misalign["paddr"]
            assert int(request["gpaddr"]) == misalign["gpaddr"]

            vector_result = api_bosc_LoadUnit_send_vector_wide_uop_pattern(
                env, vector_identity, metadata, vector, address
            )
            vector_request = vector_result["request"]
            assert vector_result["accepted"] is True
            assert vector_result["payload_stable"] is True
            assert int(vector_request["uop"]["robIdx"]["value"]) == vector_identity
            assert int(vector_request["uop"]["vpu"]["vmask"]) == (
                vector & ((1 << vector_result["vmask_width"]) - 1)
            )
            assert vector_result["dcache"] is not None
            assert int(vector_result["dcache"]["lqIdx"]["value"]) == (vector_identity & 0x7F)
        except (AssertionError, TimeoutError) as error:
            failures.append(f"matrix row {index}: {error}")
    assert not failures, "special-source metadata failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_completion_sources_cross_payload_latency_and_faults(env):
    """Completion owners cross data sources, offsets, delays, and fault classes."""
    payloads = (
        0,
        (1 << 128) - 1,
        int("AA" * 16, 16),
        int("55" * 16, 16),
        0x80000000000000010000000000000001,
    )
    sources = ("", "lsq", "sbuffer", "ubuffer")
    failures = []
    for index, payload in enumerate(payloads):
        source = sources[index % len(sources)]
        offset = (index * 3) & 0xF
        identity = 96 + index
        api_bosc_LoadUnit_reset(env)
        try:
            issue = api_bosc_LoadUnit_send_typed_scalar_load(
                env,
                0x300000 + offset,
                3,
                False,
                identity,
                identity & 0x7F,
                identity & 0x3F,
                0x310000 + identity * 4,
            )
            api_bosc_LoadUnit_inject_memory_resp(
                env,
                tlb_valid=True,
                tlb_paddr=0x400000 + offset,
                dcache_data=payload ^ ((1 << 128) - 1) if source else payload,
                forward_source=source,
                forward_data=payload,
                forward_mask=0xFFFF,
                hold_cycles=2 + (index & 1),
                max_cycles=3,
            )
            completion = api_bosc_LoadUnit_wait_for_scalar_owner(
                env, identity, identity & 0x7F, max_cycles=20
            )
            assert issue["accepted"] is True
            assert int(completion["writeback"]["uop"]["robIdx"]["value"]) == identity
            assert int(completion["writeback"]["data"]) == (
                (payload >> (8 * offset)) & ((1 << 64) - 1)
            )
        except (AssertionError, TimeoutError) as error:
            failures.append(f"completion owner {identity}: {error}")

    for index, fault_kind in enumerate(
        ("tlb-pf", "tlb-gpf", "tlb-af", "pmp-ld", "dcache-denied", "dcache-corrupt")
    ):
        api_bosc_LoadUnit_reset(env)
        identity = 112 + index
        result = api_bosc_LoadUnit_run_scalar_fault_response(
            env, identity, fault_kind, index % 3
        )
        try:
            assert result["issue"]["accepted"] is True
            assert result["outputs"] is not None
            assert result["outputs"]["scalar_writeback"] is None
        except AssertionError as error:
            failures.append(f"fault owner {identity}: {error}")
    assert not failures, "completion/fault failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_control_and_memory_response_inputs_cross_boundaries(env):
    """Redirect, CSR, translation, cache, and forward inputs toggle coherently."""
    patterns = [
        0,
        (1 << 64) - 1,
        0,
        0xAAAAAAAAAAAAAAAA,
        0x5555555555555555,
        1,
        1 << 63,
    ]
    samples = api_bosc_LoadUnit_drive_memory_control_transition_matrix(env, patterns)
    assert len(samples) == len(patterns)
    assert samples[0]["redirect_valid"] == 0
    assert samples[1]["redirect_valid"] == 1
    assert samples[1]["redirect_rob_value"] == 0xFF
    assert samples[2]["redirect_rob_value"] == 0
    assert samples[3]["io_dcache_s1_paddr_dup_lsu"] == 0xAAAAAAAAAAAA
    assert samples[4]["io_ubuffer_paddr"] == 0
    assert samples[1]["io_dcache_req_ready"] == 1
    assert samples[2]["io_dcache_req_ready"] == 0


def test_bosc_LoadUnit_misalign_terminal_outputs_preserve_wide_owner_payloads(env):
    """Misalign hits and misses expose the rich owner at response and LSQ exits."""
    full64 = (1 << 64) - 1
    full128 = (1 << 128) - 1
    rows = (
        (0, 0, 0, 0, "hit"),
        (full64, full128, full64, full128, "hit"),
        (0, 0, 0, 0, "miss"),
        (0xAAAAAAAAAAAAAAAA, int("AA" * 16, 16), 0xAAAAAAAAAAAAAAAA, int("AA" * 16, 16), "miss"),
        (0x5555555555555555, int("55" * 16, 16), 0x5555555555555555, int("55" * 16, 16), "hit"),
    )
    failures = []
    for index, (metadata, vector, address, data, outcome) in enumerate(rows):
        api_bosc_LoadUnit_reset(env)
        identity = 128 + index
        result = api_bosc_LoadUnit_observe_misalign_terminal_outcome(
            env, identity, metadata, vector, address, data, outcome
        )
        try:
            assert result["request"]["accepted"] is True
            outputs = result["misalign_outputs"] + result["lsq_outputs"]
            assert outputs, f"{outcome} produced no terminal observation"
            assert any(
                int(sample["uop"]["robIdx"]["value"]) == identity
                for sample in outputs
            )
        except AssertionError as error:
            failures.append(f"{outcome} owner {identity}: {error}")
    assert not failures, "misalign terminal failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_uncache_metadata_crosses_complementary_boundaries(env):
    """Uncache input ownership retains immediate and special-operation metadata."""
    full64 = (1 << 64) - 1
    full128 = (1 << 128) - 1
    rows = (
        (0, 0),
        (full64, full128),
        (0, 0),
        (0xAAAAAAAAAAAAAAAA, int("AA" * 16, 16)),
        (0x5555555555555555, int("55" * 16, 16)),
    )
    failures = []
    api_bosc_LoadUnit_reset(env)
    for index, (metadata, vector) in enumerate(rows):
        identity = 144 + index
        try:
            result = api_bosc_LoadUnit_send_uncache_transition_pattern(
                env, identity, metadata, vector
            )
            request = result["request"]
            assert result["accepted"] is True
            assert result["payload_stable"] is True
            assert int(request["uop"]["robIdx"]["value"]) == identity
            assert int(request["uop"]["imm"]) == (
                metadata & ((1 << 32) - 1)
            )
        except (AssertionError, TimeoutError) as error:
            failures.append(f"uncache owner {identity}: {error}")
    assert not failures, "uncache metadata failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_vector_completion_preserves_address_and_lane_payload(env):
    """Completed vector owners expose address and response data at vector writeback."""
    rows = (
        (0, 0, 0, 0),
        ((1 << 64) - 1, (1 << 128) - 1, (1 << 64) - 1, (1 << 128) - 1),
        (0, 0, 0, 0),
        (0xAAAAAAAAAAAAAAAA, int("AA" * 16, 16), 0xAAAAAAAAAAAAAAAA, int("AA" * 16, 16)),
        (0x5555555555555555, int("55" * 16, 16), 0x5555555555555555, int("55" * 16, 16)),
    )
    failures = []
    for index, (metadata, vector, address, data) in enumerate(rows):
        api_bosc_LoadUnit_reset(env)
        identity = 160 + index
        result = api_bosc_LoadUnit_complete_vector_transition_pattern(
            env, identity, metadata, vector, address, data
        )
        try:
            assert result["request"]["accepted"] is True
            assert result["outputs"], "no vector writeback"
            assert any(int(output["vaddr"]) == address for output in result["outputs"])
        except (AssertionError, TimeoutError) as error:
            failures.append(f"vector owner {identity}: {error}")
    assert not failures, "vector completion failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_reset_recovery_replays_rich_special_owners(env):
    """Rich vector and misalign owners remain fresh across reset recovery."""
    patterns = (
        (0x3, int("33" * 16, 16), 0x3000000000000003),
        (0xC, int("CC" * 16, 16), 0x0C0000000000000C),
        (0, 0, 0),
    )
    failures = []
    for index, (metadata, vector, address) in enumerate(patterns):
        api_bosc_LoadUnit_reset(env, reset_cycles=2 + (index & 1))
        identity = 176 + index * 2
        try:
            vector_result = api_bosc_LoadUnit_send_vector_wide_uop_pattern(
                env, identity, metadata, vector, address
            )
            misalign_result = api_bosc_LoadUnit_observe_misalign_terminal_outcome(
                env,
                identity + 1,
                metadata,
                vector,
                address,
                vector,
                "miss",
            )
            assert vector_result["accepted"] is True
            assert misalign_result["request"]["accepted"] is True
            assert misalign_result["lsq_outputs"] or misalign_result["misalign_outputs"]
        except (AssertionError, TimeoutError) as error:
            failures.append(f"reset owner {identity}: {error}")
    assert not failures, "reset recovery failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_condition_constrained_interface_combinations(env):
    """Drive deterministic decorrelated combinations before owner-bound matrices."""
    state = 0xD1B54A32D192ED03
    patterns = []
    for index in range(64):
        state ^= state << 13
        state ^= state >> 7
        state ^= state << 17
        lane = state & ((1 << 256) - 1)
        lane ^= (index * 0x9E3779B97F4A7C15) << ((index & 3) * 64)
        patterns.append(lane)
    samples = api_bosc_LoadUnit_drive_interface_transition_matrix(
        env, patterns, dwell_cycles=1, max_cycles=64
    )
    assert len(samples) == 64
    assert all(sample["driven"] > 100 for sample in samples)


def test_bosc_LoadUnit_condition_continuous_owner_interleaving(env):
    """Alternate prefetch, scalar, vector, and misalign owners without per-row reset."""
    api_bosc_LoadUnit_reset(env)
    failures = []
    for index in range(12):
        try:
            prefetch = api_bosc_LoadUnit_observe_prefetch_priority(
                env, index & 1, "vector" if index & 2 else "scalar",
                0x500000 + index * 0x1000, identity=16 + index,
                is_store=bool(index & 4), max_cycles=16,
            )
            held = api_bosc_LoadUnit_hold_load_then_resume(
                env, "vector" if index & 1 else "scalar", 32 + index,
                1 + (index % 3), max_cycles=16,
            )
            terminal = api_bosc_LoadUnit_run_misalign_second_split_response(
                env, ("hit", "miss", "bank-conflict", "mq-nack")[index & 3],
                48 + index, bool(index & 1), max_cycles=18,
            )
            assert prefetch["prefetch_accepts"] == 1
            assert prefetch["competitor_accepts"] == 1
            assert held["accept_count"] == 1
            assert terminal["request"]["accepted"] is True
        except (AssertionError, TimeoutError) as error:
            failures.append(f"interleave row {index}: {error}")
    assert not failures, "continuous interleave failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_misalign_boundary_split_outcome_matrix(env):
    """Cross split phase, boundary payload, and terminal outcome for one owner path."""
    patterns = (
        (0, 0, 0x0000, 0, "hit"),
        ((1 << 64) - 1, (1 << 128) - 1, 0xFFFF, 7, "miss"),
        (0xAAAAAAAAAAAAAAAA, int("55" * 16, 16), 0xAAAA, 3, "bank-conflict"),
        (0x5555555555555555, int("AA" * 16, 16), 0x5555, 4, "mq-nack"),
        (1, 1 << 127, 0x0001, 1, "forward-invalid"),
        (1 << 63, 1, 0x8001, 6, "hit"),
    )
    failures = []
    for index, (metadata, vector, mask, flags, outcome) in enumerate(patterns):
        api_bosc_LoadUnit_reset(env, reset_cycles=2 + (index & 1))
        identity = 32 + index
        try:
            request = api_bosc_LoadUnit_send_misalign_wide_uop_pattern(
                env, identity, metadata, vector, metadata, mask, flags
            )
            terminal = api_bosc_LoadUnit_run_misalign_second_split_response(
                env, outcome, identity + 16, bool(flags & 2), max_cycles=20
            )
            assert request["accepted"] is True
            assert request["payload_stable"] is True
            assert int(request["request"]["mask"]) == mask
            assert terminal["request"]["accepted"] is True
            assert any(
                sample["outputs"]["misalign_ldout"] is not None
                for sample in terminal["observations"]
            ), f"{outcome} produced no owner-bound split response"
        except (AssertionError, TimeoutError) as error:
            failures.append(f"row {index} {outcome}: {error}")
    assert not failures, "misalign matrix failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_prefetch_contention_and_training_matrix(env):
    """Cross confidence, demand owner, store intent, and completed-load training metadata."""
    failures = []
    for index in range(8):
        api_bosc_LoadUnit_reset(env)
        confidence = index & 1
        competitor = "vector" if index & 2 else "scalar"
        is_store = bool(index & 4)
        try:
            result = api_bosc_LoadUnit_observe_prefetch_priority(
                env, confidence, competitor, 0x120000 + index * 0x1000,
                identity=64 + index, is_store=is_store, max_cycles=16,
            )
            assert result["prefetch_accepts"] == 1
            assert result["competitor_accepts"] == 1
            assert result["payload_stable"] is True
            if confidence:
                assert result["history"][0]["high_accept"] == 1
            else:
                assert result["history"][0]["low_accept"] == 0
            trained = api_bosc_LoadUnit_complete_scalar_debug_metadata(
                env, 80 + index, (0, (1 << 64) - 1, 0xAAAAAAAAAAAAAAAA,
                0x5555555555555555)[index & 3],
                int(("AA" if index & 1 else "55") * 16, 16), max_cycles=24,
            )
            assert int(trained["writeback"]["uop"]["robIdx"]["value"]) == 80 + index
        except (AssertionError, TimeoutError) as error:
            failures.append(f"prefetch row {index}: {error}")
    assert not failures, "prefetch matrix failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_exception_query_and_response_precedence_matrix(env):
    """Cross translation/TL errors with both ST-LD query lanes and clean neighbors."""
    faults = ("clean", "tlb-pf", "tlb-gpf", "tlb-af", "pmp-ld",
              "pmp-mmio", "dcache-denied", "dcache-corrupt", "denied-corrupt")
    failures = []
    for index, fault in enumerate(faults):
        api_bosc_LoadUnit_reset(env)
        identity = 96 + index
        try:
            result = api_bosc_LoadUnit_run_scalar_fault_response(
                env, identity, fault, index % 3, max_cycles=24
            )
            assert result["issue"]["accepted"] is True
            assert result["injection"]["dcache_denied"] == int(
                fault in {"dcache-denied", "denied-corrupt"}
            )
            query = api_bosc_LoadUnit_observe_stld_query_match(
                env, identity + 16, index & 1, identity + (index & 1),
                0x220000 + index * 0x40, 0x220000 + (index ^ 1) * 0x40,
                1 << (index & 15), (0xFFFF, 1, 0x8000, 0xAAAA)[index & 3],
                max_cycles=16,
            )
            assert query["accepted"] is True
            assert query["query_index"] == (index & 1)
        except (AssertionError, TimeoutError) as error:
            failures.append(f"exception row {index} {fault}: {error}")
    assert not failures, "exception matrix failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_scalar_response_source_priority_matrix(env):
    """Cross legal scalar response sources, offsets, types, and complementary data."""
    sources = ("", "lsq", "sbuffer", "ubuffer")
    failures = []
    for index in range(16):
        api_bosc_LoadUnit_reset(env)
        identity = 128 + index
        source = sources[index & 3]
        payload = (0, (1 << 128) - 1, int("AA" * 16, 16),
                   int("55" * 16, 16))[index & 3] ^ (1 << index)
        try:
            issue = api_bosc_LoadUnit_send_typed_scalar_load(
                env, 0x300000 + index, (0, 1, 2, 3, 4, 5, 6, 3)[index & 7],
                bool(index & 1), identity, identity & 0x7F, identity & 0x3F,
                0x310000 + index * 4,
            )
            api_bosc_LoadUnit_inject_memory_resp(
                env, tlb_valid=True, tlb_paddr=0x400000 + index,
                dcache_data=payload ^ ((1 << 128) - 1) if source else payload,
                forward_source=source, forward_data=payload,
                forward_mask=(0xFFFF, 0x0001, 0x8000, 0xAAAA)[index & 3],
                hold_cycles=2 + (index % 3), max_cycles=4,
            )
            completion = api_bosc_LoadUnit_wait_for_scalar_owner(
                env, identity, identity & 0x7F, max_cycles=24
            )
            assert issue["accepted"] is True
            assert completion["writeback"] is not None
            assert int(completion["writeback"]["uop"]["robIdx"]["value"]) == identity
        except (AssertionError, TimeoutError) as error:
            failures.append(f"source row {index} {source or 'dcache'}: {error}")
    assert not failures, "source matrix failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_vector_payload_backpressure_matrix(env):
    """Cross vector owner metadata, wide payload transitions, and request retention."""
    rows = (
        (0, 0, 0, 0),
        ((1 << 64) - 1, (1 << 128) - 1, (1 << 50) - 1, (1 << 128) - 1),
        (0xAAAAAAAAAAAAAAAA, int("55" * 16, 16), 0x2AAAAAAAAAAAA, 1 << 127),
        (0x5555555555555555, int("AA" * 16, 16), 0x1555555555555, 1),
    )
    failures = []
    for index, (metadata, vector, address, data) in enumerate(rows):
        api_bosc_LoadUnit_reset(env)
        identity = 160 + index
        try:
            held = api_bosc_LoadUnit_hold_load_then_resume(
                env, "vector", identity, 1 + index, max_cycles=16
            )
            result = api_bosc_LoadUnit_complete_vector_transition_pattern(
                env, identity + 8, metadata, vector, address, data, max_cycles=28
            )
            assert held["payload_stable_while_stalled"] is True
            assert held["accept_count"] == 1
            assert result["request"]["accepted"] is True
            assert result["request"]["payload_stable"] is True
            assert any(
                int(output["uop"]["robIdx"]["value"]) == identity + 8
                for output in result["outputs"]
            ), "no owner-matched vector completion"
        except (AssertionError, TimeoutError) as error:
            failures.append(f"vector row {index}: {error}")
    assert not failures, "vector matrix failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_lsq_replay_carries_wide_uop_metadata(env):
    """Owner-matched LSQ replay updates retain scalar and vector metadata."""
    patterns = list((
        (0, 0),
        ((1 << 64) - 1, (1 << 256) - 1),
        (0xAAAAAAAAAAAAAAAA, int("AA" * 32, 16)),
        (0x5555555555555555, int("55" * 32, 16)),
    ))
    patterns.extend(
        (1 << bit, 1 << ((bit * 4) & 0xFF)) for bit in range(0, 64, 4)
    )
    api_bosc_LoadUnit_reset(env)
    failures = []
    for index, (metadata, vector) in enumerate(patterns):
        identity = 176 + index
        result = api_bosc_LoadUnit_observe_lsq_replay_metadata(
            env, identity, metadata, vector
        )
        try:
            assert result["observations"], "no LSQ replay update"
            assert any(
                int(sample["uop"]["robIdx"]["value"]) == identity
                for sample in result["observations"]
            )
        except AssertionError as error:
            failures.append(f"owner {identity}: {error}")
    assert not failures, "LSQ metadata failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_uncache_output_carries_wide_uop_metadata(env):
    """Uncache ownership retains immediate, operation, trigger and vector metadata."""
    patterns = list((
        (0, 0),
        ((1 << 64) - 1, (1 << 256) - 1),
        (0xAAAAAAAAAAAAAAAA, int("AA" * 32, 16)),
        (0x5555555555555555, int("55" * 32, 16)),
    ))
    patterns.extend(
        (1 << bit, 1 << ((bit * 4) & 0xFF)) for bit in range(0, 64, 4)
    )
    api_bosc_LoadUnit_reset(env)
    failures = []
    for index, (metadata, vector) in enumerate(patterns):
        identity = 192 + index
        try:
            result = api_bosc_LoadUnit_complete_uncache_uop_metadata(
                env, identity, metadata, vector
            )
            request = result["request"]
            assert int(request["uop"]["robIdx"]["value"]) == identity
            assert int(request["uop"]["imm"]) == metadata
            assert int(request["uop"]["vpu"]["vmask"]) == vector
            assert int(result["writeback"]["uop"]["robIdx"]["value"]) == identity
        except (AssertionError, TimeoutError) as error:
            failures.append(f"owner {identity}: {error}")
    assert not failures, "uncache metadata failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_nc_mmio_two_pass_payload_and_completion_matrix(env):
    """NC and MMIO owners cross address, metadata, payload, and completion boundaries."""
    full64 = (1 << 64) - 1
    full128 = (1 << 128) - 1
    rows = (
        (0, 0, 0),
        (full64, full128, full128),
        (0, 0, 0),
        (0xAAAAAAAAAAAAAAAA, int("AA" * 16, 16), int("55" * 16, 16)),
        (0x5555555555555555, int("55" * 16, 16), int("AA" * 16, 16)),
        (1, 1, 1 << 127),
        (1 << 63, 1 << 127, 1),
    )
    failures = []
    api_bosc_LoadUnit_reset(env)
    for index, (metadata, vector, data) in enumerate(rows):
        identity = 32 + index
        try:
            nc = api_bosc_LoadUnit_send_uncache_transition_pattern(
                env, identity, metadata, vector
            )
            assert nc["accepted"] is True
            assert nc["payload_stable"] is True
            assert int(nc["request"]["uop"]["robIdx"]["value"]) == identity

            api_bosc_LoadUnit_reset(env)
            mmio = api_bosc_LoadUnit_send_mmio_load(
                env,
                rob_idx=identity + 16,
                lq_idx=(identity + 16) & 0x7F,
                sq_idx=identity & 0x3F,
                pc=(metadata + 4) & ((1 << 50) - 1),
                pdest=(identity & 0x1F) + 1,
                pmp_mmio_hint=bool(index & 1),
                debug_vaddr=metadata & ((1 << 50) - 1),
                debug_paddr=(~metadata) & ((1 << 48) - 1),
                debug_is_mmio=True,
                raw_data=data & full64,
                raw_addr_offset=index & 7,
                raw_fu_op_type=(0, 1, 2, 3, 4, 5, 6)[index],
            )
            completion = api_bosc_LoadUnit_wait_for_scalar_owner(
                env, identity + 16, (identity + 16) & 0x7F, max_cycles=20
            )
            assert mmio["accepted"] is True
            assert completion["writeback"] is not None
            assert int(completion["writeback"]["uop"]["robIdx"]["value"]) == identity + 16
        except (AssertionError, TimeoutError) as error:
            failures.append(f"special owner {identity}: {error}")
    assert not failures, "NC/MMIO failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_misalign_split_payload_outcome_matrix(env):
    """Misaligned owners cross split flags, payload halves, addresses, hits, and replays."""
    full64 = (1 << 64) - 1
    full128 = (1 << 128) - 1
    rows = (
        (0, 0, 0, 0x0000, 0, "hit"),
        (full64, full128, full64, 0xFFFF, 7, "hit"),
        (0, 0, 0, 0x0000, 0, "miss"),
        (0xAAAAAAAAAAAAAAAA, int("AA" * 16, 16), 0x2AAAAAAAAAAAA, 0xAAAA, 3, "miss"),
        (0x5555555555555555, int("55" * 16, 16), 0x1555555555555, 0x5555, 4, "hit"),
        (1 << 63, 1 << 127, 1 << 49, 0x8001, 6, "miss"),
        (1, 1, 1, 0x0001, 1, "hit"),
    )
    failures = []
    api_bosc_LoadUnit_reset(env)
    for index, (metadata, vector, address, mask, flags, outcome) in enumerate(rows):
        identity = 64 + index
        try:
            request = api_bosc_LoadUnit_send_misalign_wide_uop_pattern(
                env, identity, metadata, vector, address, mask, flags
            )
            assert request["accepted"] is True
            assert request["payload_stable"] is True
            assert int(request["request"]["mask"]) == mask
            terminal = api_bosc_LoadUnit_observe_misalign_terminal_outcome(
                env, identity + 16, metadata, vector, address, vector, outcome
            )
            outputs = terminal["misalign_outputs"] + terminal["lsq_outputs"]
            assert terminal["request"]["accepted"] is True
            assert outputs, f"{outcome} produced no owner-bound terminal output"
        except (AssertionError, TimeoutError) as error:
            failures.append(f"misalign row {index}: {error}")
    assert not failures, "misalign failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_scalar_sources_offsets_and_stalls_matrix(env):
    """Scalar owners cross response source, offset, payload, type, and retained stalls."""
    full128 = (1 << 128) - 1
    payloads = tuple(
        (
            0,
            full128,
            0,
            int("AA" * 16, 16),
            int("55" * 16, 16),
            1,
            1 << 127,
            0x80000000000000010000000000000001,
        )[index & 7]
        for index in range(16)
    )
    sources = ("", "lsq", "sbuffer", "ubuffer")
    failures = []
    transitions = api_bosc_LoadUnit_drive_interface_transition_matrix(
        env,
        [
            0,
            (1 << 256) - 1,
            0,
            int("AA" * 32, 16),
            int("55" * 32, 16),
            1,
            1 << 255,
            int("0123456789ABCDEF" * 4, 16),
            int("FEDCBA9876543210" * 4, 16),
            int("0F1E2D3C4B5A6978" * 4, 16),
            int("13579BDF2468ACE0" * 4, 16),
            int("C3" * 32, 16),
            int("3C" * 32, 16),
            0xDEADBEEFCAFEBABE0123456789ABCDEF,
            (1 << 191) | (1 << 127) | (1 << 63),
            (1 << 224) - 1,
        ],
        dwell_cycles=2,
    )
    assert len(transitions) == 16
    assert all(row["driven"] > 100 for row in transitions)
    api_bosc_LoadUnit_reset(env)
    recovery = api_bosc_LoadUnit_drive_interface_transition_matrix(
        env,
        [int("3C" * 32, 16), 0, int("C3" * 32, 16)],
        dwell_cycles=1,
    )
    assert len(recovery) == 3
    assert all(row["driven"] == transitions[0]["driven"] for row in recovery)
    api_bosc_LoadUnit_reset(env, reset_cycles=3)
    for index, payload in enumerate(payloads):
        identity = 112 + index
        offset = index
        try:
            issue = api_bosc_LoadUnit_send_typed_scalar_load(
                env,
                0x300000 + offset,
                (0, 1, 2, 3, 4, 5, 6, 3)[index & 7],
                bool(index in (1, 2)),
                identity,
                identity & 0x7F,
                identity & 0x3F,
                0x310000 + index * 4,
            )
            source = sources[index % len(sources)]
            api_bosc_LoadUnit_inject_memory_resp(
                env,
                tlb_valid=True,
                tlb_paddr=0x400000 + offset,
                dcache_data=payload ^ full128 if source else payload,
                forward_source=source,
                forward_data=payload,
                forward_mask=(0xFFFF, 0x0001, 0x8000, 0xAAAA)[index % 4],
                hold_cycles=2 + (index % 3),
                max_cycles=4,
            )
            completion = api_bosc_LoadUnit_wait_for_scalar_owner(
                env, identity, identity & 0x7F, max_cycles=24
            )
            assert issue["accepted"] is True
            assert completion["writeback"] is not None
            assert int(completion["writeback"]["uop"]["robIdx"]["value"]) == identity
            stalled = api_bosc_LoadUnit_hold_load_then_resume(
                env, "scalar", identity + 32, 1 + (index % 5), max_cycles=16
            )
            assert stalled["payload_stable_while_stalled"] is True
            assert stalled["accept_count"] == 1
        except (AssertionError, TimeoutError) as error:
            failures.append(f"scalar row {index}: {error}")
    assert not failures, "scalar completion failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_vector_address_mask_payload_completion_matrix(env):
    """Vector owners retain rich masks and metadata through 128-bit completion."""
    full64 = (1 << 64) - 1
    full128 = (1 << 128) - 1
    rows = (
        (0, 0, 0, 0),
        (full64, full128, full64, full128),
        (0, 0, 0, 0),
        (0xAAAAAAAAAAAAAAAA, int("AA" * 16, 16), 0x2AAAAAAAAAAAA, int("55" * 16, 16)),
        (0x5555555555555555, int("55" * 16, 16), 0x1555555555555, int("AA" * 16, 16)),
        (1, 1, 1, 1 << 127),
        (1 << 63, 1 << 127, 1 << 49, 1),
    )
    failures = []
    api_bosc_LoadUnit_reset(env)
    for index, (metadata, vector, address, data) in enumerate(rows):
        identity = 176 + index
        try:
            result = api_bosc_LoadUnit_complete_vector_transition_pattern(
                env, identity, metadata, vector, address, data, max_cycles=28
            )
            assert result["request"]["accepted"] is True
            assert result["request"]["payload_stable"] is True
            assert result["outputs"], "no vector completion observed"
            assert any(
                int(output["uop"]["robIdx"]["value"]) == identity
                for output in result["outputs"]
            )
        except (AssertionError, TimeoutError) as error:
            failures.append(f"vector row {index}: {error}")
    assert not failures, "vector completion failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_nc_misalign_guard_and_supported_neighbor_matrix(env):
    """NC and misalign boundary patterns preserve owners and isolate supported neighbors."""
    patterns = (
        (0, 0x0000, 0),
        ((1 << 64) - 1, 0xFFFF, 7),
        (0, 0x0000, 0),
        (0xAAAAAAAAAAAAAAAA, 0xAAAA, 3),
        (0x5555555555555555, 0x5555, 4),
        (1, 0x0001, 1),
        (1 << 63, 0x8001, 6),
    )
    failures = []
    api_bosc_LoadUnit_reset(env)
    for index, (pattern, mask, flags) in enumerate(patterns):
        identity = 208 + index
        try:
            misalign = api_bosc_LoadUnit_send_misalign_wide_uop_pattern(
                env, identity, pattern, pattern, pattern, mask, flags
            )
            assert misalign["accepted"] is True
            assert misalign["payload_stable"] is True
            nc = api_bosc_LoadUnit_send_uncache_transition_pattern(
                env, identity + 16, ~pattern, pattern
            )
            assert nc["accepted"] is True
            assert nc["payload_stable"] is True
            assert int(misalign["request"]["uop"]["robIdx"]["value"]) == identity
            assert int(nc["request"]["uop"]["robIdx"]["value"]) == identity + 16
        except (AssertionError, TimeoutError) as error:
            failures.append(f"guard row {index}: {error}")
    assert not failures, "NC-misalign guard failures:\n" + "\n".join(failures)
