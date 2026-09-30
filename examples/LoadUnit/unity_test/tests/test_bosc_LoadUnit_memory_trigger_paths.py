from bosc_LoadUnit_api import *


def test_bosc_LoadUnit_memory_trigger_unit_stride_lane_hit(env):
    """Exercise a 128-bit unit-stride trigger whose selected lane is active."""
    api_bosc_LoadUnit_reset(env, reset_cycles=2)
    result = api_bosc_LoadUnit_send_triggered_vector_load(
        env,
        vaddr=0x6400,
        mask=0x0008,
        aligned_type=4,
        triggers=[{"index": 0, "enabled": 1, "load": 1, "action": 1, "tdata2": 0x6403}],
    )
    assert result["accepted"] is True
    assert result["request"]["alignedType"] == 4
    assert result["trigger_config"][0]["tdata2"] == 0x6403


def test_bosc_LoadUnit_memory_trigger_unit_stride_mask_miss(env):
    """Exercise the unit-stride address hit while excluding the selected lane."""
    api_bosc_LoadUnit_reset(env, reset_cycles=2)
    result = api_bosc_LoadUnit_send_triggered_vector_load(
        env,
        vaddr=0x6500,
        mask=0x0004,
        aligned_type=5,
        triggers=[{"index": 0, "enabled": 1, "load": 1, "action": 0, "tdata2": 0x6503}],
    )
    assert result["accepted"] is True
    assert result["request"]["mask"] == 0x0004
    assert result["trigger_config"][0]["action"] == 0


def test_bosc_LoadUnit_memory_trigger_scalar_comparator_matrix(env):
    """Exercise exact, greater-or-equal, and less-than address comparators."""
    api_bosc_LoadUnit_reset(env, reset_cycles=3)
    result = api_bosc_LoadUnit_send_triggered_vector_load(
        env,
        vaddr=0x6600,
        mask=0x00FF,
        aligned_type=0,
        triggers=[
            {"index": 0, "enabled": 1, "load": 1, "match_type": 0, "action": 0, "tdata2": 0x6600},
            {"index": 1, "enabled": 1, "load": 1, "match_type": 2, "action": 1, "tdata2": 0x6500},
            {"index": 2, "enabled": 1, "load": 1, "match_type": 3, "action": 0, "tdata2": 0x6700},
        ],
    )
    assert result["accepted"] is True
    assert [item["match_type"] for item in result["trigger_config"][:3]] == [0, 2, 3]


def test_bosc_LoadUnit_memory_trigger_chain_and_priority(env):
    """Exercise adjacent trigger chaining with equal timing and mixed actions."""
    api_bosc_LoadUnit_reset(env, reset_cycles=1)
    result = api_bosc_LoadUnit_send_triggered_vector_load(
        env,
        vaddr=0x6800,
        mask=0xFFFF,
        aligned_type=6,
        triggers=[
            {"index": 0, "enabled": 1, "load": 1, "chain": 1, "timing": 1, "action": 0, "tdata2": 0x6800},
            {"index": 1, "enabled": 1, "load": 1, "chain": 0, "timing": 1, "action": 1, "tdata2": 0x6800},
            {"index": 2, "enabled": 1, "load": 1, "chain": 1, "timing": 0, "action": 0, "tdata2": 0x680F},
            {"index": 3, "enabled": 1, "load": 1, "chain": 0, "timing": 0, "action": 1, "tdata2": 0x680F},
        ],
    )
    assert result["accepted"] is True
    assert [item["chain"] for item in result["trigger_config"]] == [1, 0, 1, 0]


def test_bosc_LoadUnit_memory_trigger_global_gate_matrix(env):
    """Exercise debug, select, enable, and breakpoint-permission suppression gates."""
    api_bosc_LoadUnit_reset(env, reset_cycles=4)
    result = api_bosc_LoadUnit_send_triggered_vector_load(
        env,
        vaddr=0x6900,
        mask=0xA5A5,
        aligned_type=7,
        debug_mode=1,
        can_raise_breakpoint=0,
        triggers=[
            {"index": 0, "enabled": 1, "load": 1, "select": 1, "action": 0, "tdata2": 0x6900},
            {"index": 1, "enabled": 0, "load": 1, "select": 0, "action": 1, "tdata2": 0x6902},
            {"index": 2, "enabled": 1, "load": 0, "select": 0, "action": 0, "tdata2": 0x6905},
            {"index": 3, "enabled": 1, "load": 1, "select": 0, "action": 1, "tdata2": 0x6907},
        ],
    )
    assert result["accepted"] is True
    assert result["trigger_config"][0]["select"] == 1
    assert result["trigger_config"][1]["enabled"] == 0
    assert result["trigger_config"][2]["load"] == 0


def test_bosc_LoadUnit_memory_trigger_payload_and_priority_sequence(env):
    """Exercise bidirectional trigger payload toggles and each action-priority arm."""
    api_bosc_LoadUnit_reset(env, reset_cycles=2)
    scenarios = [
        (0x6A00, 0x0001, 4, 0, 1, [{"index": 0, "enabled": 1, "load": 1, "action": 1, "tdata2": 0xFFFFFFFFFFFF6A00}]),
        (0x6B00, 0x8000, 5, 0, 1, [{"index": 1, "enabled": 1, "load": 1, "action": 1, "tdata2": 0xAAAAAAAAAAAA6B0F}]),
        (0x6C00, 0x0020, 6, 0, 1, [{"index": 2, "enabled": 1, "load": 1, "action": 0, "tdata2": 0x5555555555556C05}]),
        (0x6D00, 0x0400, 7, 0, 1, [{"index": 3, "enabled": 1, "load": 1, "action": 0, "tdata2": 0x0000000000006D0A}]),
        (0x6E00, 0xFFFF, 4, 0, 1, [
            {"index": index, "enabled": 1, "load": 1, "action": 0, "tdata2": 0x6E00 + index}
            for index in range(4)
        ]),
        (0x6F00, 0xFFFF, 4, 0, 1, [
            {"index": 0, "enabled": 1, "load": 1, "action": 0, "tdata2": 0x6F00},
            {"index": 1, "enabled": 1, "load": 1, "action": 1, "tdata2": 0x6F01},
            {"index": 2, "enabled": 1, "load": 1, "action": 0, "tdata2": 0x6F02},
            {"index": 3, "enabled": 1, "load": 1, "action": 1, "tdata2": 0x6F03},
        ]),
    ]

    results = []
    for offset, (vaddr, mask, aligned_type, debug_mode, can_raise, triggers) in enumerate(scenarios):
        results.append(api_bosc_LoadUnit_send_triggered_vector_load(
            env,
            vaddr=vaddr,
            mask=mask,
            aligned_type=aligned_type,
            debug_mode=debug_mode,
            can_raise_breakpoint=can_raise,
            rob_idx=24 + offset,
            lq_idx=24 + offset,
            triggers=triggers,
            clear_cycles=1,
            observe_cycles=2,
        ))

    assert all(result["accepted"] for result in results)
    assert [result["request"]["mask"] for result in results[:4]] == [0x0001, 0x8000, 0x0020, 0x0400]
    assert [result["trigger_config"][index]["enabled"] for index, result in enumerate(results[:4])] == [1, 1, 1, 1]


def test_bosc_LoadUnit_memory_trigger_high_address_payload_transitions(env):
    """Exercise high address bits, full-width trigger payloads, and trigger-three selection."""
    api_bosc_LoadUnit_reset(env, reset_cycles=2)
    addresses = [
        0x2AAAAAAAAAAA0,
        0x1555555555550,
        0x3FFFFFFFFFFF0,
        0x1000000000000,
    ]
    payload_patterns = [
        0xFFFFFFFFFFFFFFFF,
        0xAAAAAAAAAAAAAAAA,
        0x5555555555555555,
        0x0000000000000000,
    ]
    results = []

    for selected_index, vaddr in enumerate(addresses):
        lane = (selected_index * 5) & 0xF
        triggers = []
        for index, pattern in enumerate(payload_patterns):
            rotated_pattern = payload_patterns[(index + selected_index) % len(payload_patterns)]
            tdata2 = rotated_pattern if index != selected_index else (vaddr | lane)
            triggers.append({
                "index": index,
                "enabled": int(index == selected_index),
                "load": 1,
                "action": 1 if index == selected_index else ((index * 5 + selected_index * 3) & 0xF),
                "match_type": (index + selected_index) & 0x3,
                "select": (selected_index + index) & 0x1,
                "timing": (selected_index + index) & 0x1,
                "chain": (selected_index + index + 1) & 0x1,
                "tdata2": tdata2,
            })
        triggers[selected_index]["select"] = 0
        triggers[selected_index]["chain"] = 0
        results.append(api_bosc_LoadUnit_send_triggered_vector_load(
            env,
            vaddr=vaddr,
            mask=1 << lane,
            aligned_type=4 + selected_index,
            rob_idx=40 + selected_index,
            lq_idx=40 + selected_index,
            triggers=triggers,
            clear_cycles=1,
            observe_cycles=2,
        ))

    low_result = api_bosc_LoadUnit_send_triggered_vector_load(
        env,
        vaddr=0x10,
        mask=0x0001,
        aligned_type=4,
        rob_idx=44,
        lq_idx=44,
        triggers=[
            {"index": 3, "enabled": 1, "load": 1, "action": 1, "tdata2": 0x10}
        ],
        clear_cycles=1,
        observe_cycles=2,
    )

    assert all(result["accepted"] for result in results)
    assert low_result["accepted"] is True
    assert results[3]["trigger_config"][3]["action"] == 1
    assert results[3]["request"]["vaddr"] == addresses[3]


def test_bosc_LoadUnit_memory_trigger_guard_truth_table(env):
    """Exercise each trigger guard independently and both sides of every comparator."""
    api_bosc_LoadUnit_reset(env, reset_cycles=2)
    results = []
    lanes = [0, 5, 10, 15]

    for index, lane in enumerate(lanes):
        vaddr = 0x7000 + index * 0x100
        base = {
            "index": index,
            "enabled": 1,
            "load": 1,
            "select": 0,
            "action": 1,
            "tdata2": vaddr | lane,
        }
        variants = [
            ({}, 0, 1 << lane),
            ({"select": 1}, 0, 1 << lane),
            ({"enabled": 0}, 0, 1 << lane),
            ({"load": 0}, 0, 1 << lane),
            ({"tdata2": (vaddr + 0x10) | lane}, 0, 1 << lane),
            ({}, 0, 1 << ((lane + 1) & 0xF)),
            ({}, 1, 1 << lane),
        ]
        for variant_index, (changes, debug_mode, mask) in enumerate(variants):
            trigger = {**base, **changes}
            results.append(api_bosc_LoadUnit_send_triggered_vector_load(
                env,
                vaddr=vaddr,
                mask=mask,
                aligned_type=4 + index,
                debug_mode=debug_mode,
                rob_idx=48 + index * 8 + variant_index,
                lq_idx=48 + index * 8 + variant_index,
                triggers=[trigger],
                clear_cycles=1,
                observe_cycles=1,
            ))

    comparator_relations = [
        (0, 0),
        (0, 1),
        (2, -1),
        (2, 1),
        (3, 1),
        (3, -1),
    ]
    for index in range(4):
        vaddr = 0x8000 + index * 0x100
        for relation_index, (match_type, delta) in enumerate(comparator_relations):
            results.append(api_bosc_LoadUnit_send_triggered_vector_load(
                env,
                vaddr=vaddr,
                mask=0xFFFF,
                aligned_type=index,
                rob_idx=80 + index * 8 + relation_index,
                lq_idx=80 + index * 8 + relation_index,
                triggers=[{
                    "index": index,
                    "enabled": 1,
                    "load": 1,
                    "select": 0,
                    "action": relation_index & 1,
                    "match_type": match_type,
                    "tdata2": vaddr + delta,
                }],
                clear_cycles=1,
                observe_cycles=1,
            ))

    assert len(results) == 52
    assert all(result["accepted"] for result in results)
    assert {result["request"]["alignedType"] for result in results} == set(range(8))


def test_bosc_LoadUnit_memory_trigger_all_lane_hit_miss_matrix(env):
    """Verify each trigger lane is included only by its matching vector mask."""
    api_bosc_LoadUnit_reset(env, reset_cycles=2)
    lane_pairs = []

    for trigger_index in range(4):
        for lane in range(16):
            vaddr = 0x9000 + trigger_index * 0x100 + lane * 0x10
            trigger = {
                "index": trigger_index,
                "enabled": 1,
                "load": 1,
                "action": trigger_index & 1,
                "tdata2": vaddr | lane,
            }
            pair = []
            for mask in (1 << lane, 0xFFFF ^ (1 << lane)):
                pair.append(api_bosc_LoadUnit_send_triggered_vector_load(
                    env,
                    vaddr=vaddr,
                    mask=mask,
                    aligned_type=4 + trigger_index,
                    rob_idx=128 + trigger_index * 32 + lane,
                    lq_idx=64 + trigger_index * 16 + lane,
                    triggers=[trigger],
                    clear_cycles=0,
                    observe_cycles=0,
                ))
            lane_pairs.append((trigger_index, lane, vaddr, pair[0], pair[1]))

    assert len(lane_pairs) == 64
    for trigger_index, lane, vaddr, hit, miss in lane_pairs:
        expected_lane_mask = 1 << lane
        assert hit["accepted"] is True and miss["accepted"] is True
        assert hit["request"]["vaddr"] == miss["request"]["vaddr"] == vaddr
        assert hit["request"]["mask"] == expected_lane_mask
        assert miss["request"]["mask"] == (0xFFFF ^ expected_lane_mask)
        assert hit["request"]["mask"] & expected_lane_mask
        assert not (miss["request"]["mask"] & expected_lane_mask)
        assert hit["trigger_config"][trigger_index]["enabled"] == 1
        assert hit["trigger_config"][trigger_index]["tdata2"] & 0xF == lane
        assert hit["request"]["alignedType"] == 4 + trigger_index


def _observed_scalar_trigger_action(result, request_vaddr):
    payloads = [
        sample["payload"]
        for sample in result["response_history"]
        if sample["payload"] is not None and int(sample["payload"]["debug"]["vaddr"]) == request_vaddr
    ]
    assert payloads, f"completed scalar request {request_vaddr:#x} must produce its own observable writeback"
    return int(payloads[0]["uop"]["trigger"])


def test_bosc_LoadUnit_memory_trigger_request_class_transition_and_prefetch_isolation(env):
    """Verify trigger state survives scalar/vector/prefetch mode changes without contaminating prefetch routing."""
    api_bosc_LoadUnit_reset(env, reset_cycles=2)
    result = api_bosc_LoadUnit_run_trigger_request_class_sequence(
        env,
        scalar_high_addr=0x3FFFFFFFFFFF0,
        vector_low_addr=0x20,
        prefetch_addr=0x2AAAAAAAAAAA0,
        scalar_low_addr=0x10,
        triggers=[
            {"index": 0, "enabled": 1, "load": 1, "match_type": 0, "action": 1, "tdata2": 0x3FFFFFFFFFFF0},
            {"index": 3, "enabled": 1, "load": 1, "match_type": 2, "action": 0, "tdata2": 0x10},
        ],
    )

    assert result["mode_order"] == ["scalar", "vector-unit-stride", "prefetch", "scalar"]
    assert result["scalar_high"]["accepted"] is True
    assert result["scalar_high"]["request"]["src"]["0"] == 0x3FFFFFFFFFFF0
    assert result["vector"]["accepted"] is True
    assert result["vector"]["request"]["vaddr"] == 0x20
    assert result["vector"]["request"]["alignedType"] == 4
    assert result["prefetch"]["accepted"] is True
    assert result["prefetch"]["paddr"] == 0x2AAAAAAAAAAA0
    assert result["prefetch"]["dcache_req_valid"] != 0
    assert result["prefetch"]["tlb_req_valid"] == 0
    assert result["scalar_low"]["accepted"] is True
    assert result["scalar_low"]["request"]["src"]["0"] == 0x10
    assert result["scalar_low"]["tlb_req_valid"] != 0


def test_bosc_LoadUnit_memory_trigger_scalar_comparator_and_chain_observability(env):
    """Verify scalar comparator boundaries and chained ownership through vector trigger writeback masks."""
    api_bosc_LoadUnit_reset(env, reset_cycles=2)
    observations = []

    comparator_variants = [
        (1, 0, False, "reserved comparator encoding"),
        (2, 0, True, "greater-or-equal equality boundary"),
        (2, 1, False, "greater-or-equal lower-address miss"),
        (3, 0, False, "less-than equality boundary"),
        (3, 1, True, "less-than upper-threshold hit"),
        (3, -1, False, "less-than lower-threshold miss"),
    ]
    for trigger_index in range(4):
        vaddr = 0xA000 + trigger_index * 0x100
        for variant_index, (match_type, threshold_delta, should_fire, label) in enumerate(comparator_variants):
            api_bosc_LoadUnit_reset(env, reset_cycles=1)
            result = api_bosc_LoadUnit_send_triggered_scalar_load(
                env,
                vaddr=vaddr,
                rob_idx=224 + trigger_index * 6 + variant_index,
                lq_idx=96 + trigger_index * 6 + variant_index,
                triggers=[{
                    "index": trigger_index,
                    "enabled": 1,
                    "load": 1,
                    "select": 0,
                    "action": 1,
                    "match_type": match_type,
                    "tdata2": vaddr + threshold_delta * 0x10,
                }],
                observe_cycles=12,
            )
            observed_action = _observed_scalar_trigger_action(result, vaddr)
            expected_action = 1 if should_fire else 0xF
            observations.append((f"trigger {trigger_index}: {label}", observed_action, expected_action))

    for predecessor in range(3):
        successor = predecessor + 1
        vaddr = 0xB020 + predecessor * 0x100
        predecessor_lane = predecessor * 4 + 2
        successor_lane = successor * 4 + 2
        chain_variants = [
            (True, 1, 0, 1, True, "matching predecessor and equal timing"),
            (False, 1, 0, 1, False, "predecessor address miss"),
            (True, 1, 0, 0, False, "chained timing mismatch"),
            (True, 1, 1, 1, False, "successor remains chained"),
            (False, 0, 0, 1, True, "unchained successor bypasses predecessor miss"),
        ]
        for variant_index, (predecessor_hit, predecessor_chain, successor_chain, successor_timing, should_fire, label) in enumerate(chain_variants):
            api_bosc_LoadUnit_reset(env, reset_cycles=1)
            predecessor_addr = (
                (vaddr - 0x10) | predecessor_lane
                if predecessor_hit
                else (vaddr + 0x10) | predecessor_lane
            )
            successor_addr = (vaddr - 0x10) | successor_lane
            result = api_bosc_LoadUnit_send_triggered_scalar_load(
                env,
                vaddr=vaddr,
                rob_idx=160 + predecessor * 8 + variant_index,
                lq_idx=48 + predecessor * 8 + variant_index,
                triggers=[
                    {
                        "index": predecessor,
                        "enabled": 1,
                        "load": 1,
                        "chain": predecessor_chain,
                        "timing": 1,
                        "action": 0,
                        "match_type": 2,
                        "tdata2": predecessor_addr,
                    },
                    {
                        "index": successor,
                        "enabled": 1,
                        "load": 1,
                        "chain": successor_chain,
                        "timing": successor_timing,
                        "action": 1,
                        "match_type": 2,
                        "tdata2": successor_addr,
                    },
                ],
                observe_cycles=12,
            )
            observed_action = _observed_scalar_trigger_action(result, vaddr)
            expected_action = 1 if should_fire else 0xF
            observations.append((f"chain {predecessor}->{successor}: {label}", observed_action, expected_action))

    assert len(observations) == 39
    for label, observed_action, expected_action in observations:
        assert observed_action == expected_action, f"{label}: expected action {expected_action:#x}, observed {observed_action:#x}"


def test_bosc_LoadUnit_memory_trigger_scalar_guard_isolation(env):
    """Verify each scalar trigger guard independently suppresses an otherwise matching trigger."""
    observations = []
    guard_variants = [
        ({}, 0, "all scalar trigger guards enabled", True),
        ({"select": 1}, 0, "select chooses the unsupported data comparator", False),
        ({}, 1, "debug mode suppresses normal memory triggers", False),
        ({"enabled": 0}, 0, "trigger enable is clear", False),
        ({"load": 0}, 0, "load matching is disabled", False),
    ]

    for trigger_index in range(4):
        vaddr = 0xC000 + trigger_index * 0x100
        for variant_index, (changes, debug_mode, label, should_fire) in enumerate(guard_variants):
            api_bosc_LoadUnit_reset(env, reset_cycles=1)
            trigger = {
                "index": trigger_index,
                "enabled": 1,
                "load": 1,
                "select": 0,
                "action": 1,
                "match_type": 0,
                "tdata2": vaddr,
                **changes,
            }
            result = api_bosc_LoadUnit_send_triggered_scalar_load(
                env,
                vaddr=vaddr,
                rob_idx=192 + trigger_index * len(guard_variants) + variant_index,
                lq_idx=72 + trigger_index * len(guard_variants) + variant_index,
                triggers=[trigger],
                debug_mode=debug_mode,
                observe_cycles=12,
            )
            observed_action = _observed_scalar_trigger_action(result, vaddr)
            expected_action = 1 if should_fire else 0xF
            observations.append((f"trigger {trigger_index}: {label}", observed_action, expected_action))

    assert len(observations) == 20
    for label, observed_action, expected_action in observations:
        assert observed_action == expected_action, f"{label}: expected action {expected_action:#x}, observed {observed_action:#x}"
