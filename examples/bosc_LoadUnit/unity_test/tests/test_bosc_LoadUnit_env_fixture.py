#coding=utf-8

from bosc_LoadUnit_api import *


def test_api_bosc_LoadUnit_env_bundle_aliases(env):
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-COLLECT-WRITEBACK-FEEDBACK",
        test_api_bosc_LoadUnit_env_bundle_aliases,
        ["CK-VECTOR-AND-CONTROL-CAPTURE"],
    )

    assert env.scalar_req is env.io.ldin
    assert env.scalar_resp is env.io.ldout
    assert env.vector_req is env.io.vecldin
    assert env.vector_resp is env.io.vecldout
    assert env.lsq is env.io.lsq
    assert env.dcache is env.io.dcache
    assert env.tlb is env.io.tlb

    # 数字下标层次是 LoadUnit 端口树的高频结构，后续 testcase 需要能直接访问。
    assert getattr(env.vector_req.bits.uop.exceptionVec, "4") is not None
    assert getattr(env.wakeup.bits.srcLoadDependency["0"], "1") is not None


def test_api_bosc_LoadUnit_env_default_inputs(env):
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-RESET-AND-CLOCK",
        test_api_bosc_LoadUnit_env_default_inputs,
        ["CK-RESET-SEQUENCE"],
    )

    assert env.reset_pin.value == 0
    assert env.scalar_resp.ready.value == 1
    assert env.lsq.ldld_nuke_query.req.ready.value == 1
    assert env.lsq.stld_nuke_query.req.ready.value == 1
    assert env.misalign.enq_req.ready.value == 1
    assert env.dcache.req.ready.value == 1

    assert env.scalar_req.valid.value == 0
    assert env.vector_req.valid.value == 0
    assert env.replay.valid.value == 0
    assert env.lsq.uncache.valid.value == 0
    assert env.lsq.nc_ldin.valid.value == 0


def test_api_bosc_LoadUnit_env_clear_and_restore_defaults(env):
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-RESET-AND-CLOCK",
        test_api_bosc_LoadUnit_env_clear_and_restore_defaults,
        ["CK-RESET-SEQUENCE"],
    )

    env.clear_inputs()
    assert env.reset_pin.value == 0
    assert env.scalar_resp.ready.value == 0
    assert env.lsq.ldld_nuke_query.req.ready.value == 0
    assert env.lsq.stld_nuke_query.req.ready.value == 0
    assert env.misalign.enq_req.ready.value == 0
    assert env.dcache.req.ready.value == 0

    env.set_default_inputs()
    assert env.scalar_resp.ready.value == 1
    assert env.lsq.ldld_nuke_query.req.ready.value == 1
    assert env.lsq.stld_nuke_query.req.ready.value == 1
    assert env.misalign.enq_req.ready.value == 1
    assert env.dcache.req.ready.value == 1
    assert env.scalar_req.valid.value == 0
    assert env.vector_req.valid.value == 0


def test_api_bosc_LoadUnit_env_reset_and_step(env):
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-RESET-AND-CLOCK",
        test_api_bosc_LoadUnit_env_reset_and_step,
        ["CK-RESET-SEQUENCE", "CK-MULTI-CYCLE-STEP"],
    )

    env.scalar_req.valid.value = 1
    env.vector_req.valid.value = 1
    env.redirect.valid.value = 1

    env.reset(cycles=1)

    assert env.reset_pin.value == 0
    assert env.scalar_req.valid.value == 0
    assert env.vector_req.valid.value == 0
    assert env.redirect.valid.value == 0
    assert env.scalar_resp.ready.value == 1

    env.Step(1)
    assert env.reset_pin.value == 0
