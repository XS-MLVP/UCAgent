#coding=utf-8

from bosc_LoadUnit_api import *


def test_bosc_LoadUnit_misalign_input_carries_wide_metadata_and_addresses(env):
    """Misalign arbitration retains owner, address and wide debug metadata."""
    patterns = list((
        (0x0000000000000000, 0x0000000000000, 0x0001, 0),
        (0xFFFFFFFFFFFFFFFF, 0x3FFFFFFFFFFFF, 0x8000, 1),
        (0xAAAAAAAAAAAAAAAA, 0x2AAAAAAAAAAAA, 0xAAAA, 2),
        (0x5555555555555555, 0x1555555555555, 0x5555, 3),
        (0x8000000000000001, 0x2000000000001, 0xFFFF, 7),
    ))
    patterns.extend(
        (1 << bit, (1 << bit) & ((1 << 50) - 1), 1 << (bit & 0xF), bit & 7)
        for bit in range(0, 64, 4)
    )
    api_bosc_LoadUnit_reset(env)
    failures = []
    for index, (metadata, address, mask, phase) in enumerate(patterns):
        identity = 32 + index
        try:
            result = api_bosc_LoadUnit_send_misalign_debug_metadata(
                env, identity, metadata, address, mask, phase
            )
            request = result["request"]
            assert result["accepted"] is True
            assert result["payload_stable"] is True
            assert int(request["uop"]["robIdx"]["value"]) == identity
            assert int(request["uop"]["lqIdx"]["value"]) == (identity & 0x7F)
            assert int(request["uop"]["sqIdx"]["value"]) == (identity & 0x3F)
            assert int(request["vaddr"]) == result["vaddr"]
            assert int(request["paddr"]) == result["paddr"]
            assert int(request["gpaddr"]) == result["gpaddr"]
            assert int(request["mask"]) == mask
            assert int(request["uop"]["debugInfo"]["selectTime"]) == metadata
            assert int(request["uop"]["debugInfo"]["issueTime"]) == metadata
        except (AssertionError, TimeoutError) as error:
            failures.append(f"owner {identity}: {error}")
    assert not failures, "misalign metadata failures:\n" + "\n".join(failures)


def test_bosc_LoadUnit_misalign_final_split_outcomes_preserve_response_owner(env):
    """Final split hit and replay outcomes return the accepted misalign owner."""
    for index, outcome in enumerate(
        ("hit", "miss", "bank-conflict", "mq-nack", "forward-invalid")
    ):
        api_bosc_LoadUnit_reset(env)
        identity = 48 + index
        result = api_bosc_LoadUnit_run_misalign_second_split_response(
            env, outcome=outcome, identity=identity, is128bit=bool(index & 1)
        )
        responses = [
            sample["outputs"]["misalign_ldout"]
            for sample in result["observations"]
            if sample["outputs"]["misalign_ldout"] is not None
        ]
        assert result["request"]["accepted"] is True
        assert responses, f"{outcome} produced no misalign response"
        assert any(
            int(response["uop"]["robIdx"]["value"]) == identity
            for response in responses
        )


def test_bosc_LoadUnit_final_split_response_and_replay_identity_matrix(env):
    """Final split outcomes preserve transaction identity at the MisalignBuffer response."""
    api_bosc_LoadUnit_reset(env)
    outcomes = ("hit", "miss", "bank-conflict", "mq-nack", "forward-invalid")
    for offset, outcome in enumerate(outcomes):
        identity = 70 + offset
        result = api_bosc_LoadUnit_run_misalign_second_split_response(
            env,
            outcome=outcome,
            identity=identity,
            is128bit=bool(offset & 1),
        )
        request = result["request"]["request"]
        assert result["request"]["accepted"] is True
        assert int(request["isFinalSplit"]) == 1
        assert int(request["uop"]["robIdx"]["value"]) == identity
        assert int(request["uop"]["lqIdx"]["value"]) == (identity & 0x7F)
        assert int(request["uop"]["sqIdx"]["value"]) == (identity & 0x3F)

        misalign_outputs = [
            sample["outputs"]["misalign_ldout"]
            for sample in result["observations"]
            if sample["outputs"]["misalign_ldout"] is not None
        ]
        assert misalign_outputs, f"{outcome} produced no MisalignBuffer response"
        assert any(
            int(output["uop"]["robIdx"]["value"]) == identity
            for output in misalign_outputs
        ), f"{outcome} response lost ROB ownership"


def test_bosc_LoadUnit_misalign_split_request_identity_and_completion_modes(env):
    """Verify MisalignBuffer split requests preserve identity across replay and wakeup modes."""
    api_bosc_LoadUnit_reset(env, reset_cycles=2)
    scenarios = [
        (0x10, 0x000F, False, False, False, 0, 0),
        ((1 << 49) - 0x10, 0xFFFF, False, True, True, 3, (1 << 49) - 4),
        (0x2AAAAAAAAAA0, 0x00F0, True, False, True, 2, 0x2AAAAAAAAAA8),
        (0x155555555550, 0x0F00, True, True, False, 6, 0x155555555554),
    ]
    results = []

    for index, (vaddr, mask, is_final_split, need_wakeup, is128bit, fu_op_type, pc) in enumerate(scenarios):
        results.append(api_bosc_LoadUnit_send_misalign_buffer_load(
            env,
            vaddr=vaddr,
            mask=mask,
            rob_idx=224 + index,
            lq_idx=112 + index,
            sq_idx=24 + index,
            pc=pc,
            fu_op_type=fu_op_type,
            is_final_split=is_final_split,
            misalign_need_wakeup=need_wakeup,
            is128bit=is128bit,
        ))

    assert all(result["accepted"] for result in results)
    for index, (result, expected) in enumerate(zip(results, scenarios)):
        vaddr, mask, is_final_split, need_wakeup, is128bit, fu_op_type, pc = expected
        request = result["request"]
        checks = {
            "vaddr": (int(request["vaddr"]), vaddr),
            "fullva": (int(request["fullva"]), vaddr),
            "mask": (int(request["mask"]), mask),
            "isFinalSplit": (int(request["isFinalSplit"]), int(is_final_split)),
            "misalignNeedWakeUp": (int(request["misalignNeedWakeUp"]), int(need_wakeup)),
            "is128bit": (int(request["is128bit"]), int(is128bit)),
            "fuOpType": (int(request["uop"]["fuOpType"]), fu_op_type),
            "pc": (int(request["uop"]["pc"]), pc),
            "robIdx": (int(request["uop"]["robIdx"]["value"]), 224 + index),
            "lqIdx": (int(request["uop"]["lqIdx"]["value"]), 112 + index),
            "sqIdx": (int(request["uop"]["sqIdx"]["value"]), 24 + index),
        }
        for field, (actual, expected_value) in checks.items():
            assert actual == expected_value, (
                f"misalign transaction {index} {field} identity mismatch: "
                f"expected {expected_value:#x}, observed {actual:#x}"
            )


def test_bosc_LoadUnit_misalign_wakeup_carries_address_and_owner_matrix(env):
    """Misalign wakeup requests retain legal address, mask, split and owner fields."""
    addresses = (0, (1 << 50) - 1, 0x2AAAAAAAAAAAA, 0x1555555555555)
    masks = (0x0001, 0x8000, 0xAAAA, 0x5555)
    for index, (address, mask) in enumerate(zip(addresses, masks)):
        api_bosc_LoadUnit_reset(env)
        identity = 120 + index
        paddr = ((~address) & ((1 << 48) - 1))
        gpaddr = ((address << 1) ^ ((1 << 50) - 1)) & ((1 << 50) - 1)
        issue = api_bosc_LoadUnit_send_misalign_wakeup_addresses(
            env,
            identity=identity,
            vaddr=address,
            paddr=paddr,
            gpaddr=gpaddr,
            mask=mask,
            split_phase=index,
        )
        request = issue["request"]
        assert issue["accepted"] is True
        assert int(request["vaddr"]) == address
        assert int(request["fullva"]) == address
        assert int(request["mask"]) == mask
        assert int(request["paddr"]) == paddr
        assert int(request["gpaddr"]) == gpaddr
        assert issue["payload_stable"] is True
        assert int(request["uop"]["robIdx"]["value"]) == identity
        assert int(request["uop"]["lqIdx"]["value"]) == (identity & 0x7F)
