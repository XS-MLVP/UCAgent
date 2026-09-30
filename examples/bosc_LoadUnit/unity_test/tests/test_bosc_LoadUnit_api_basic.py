#coding=utf-8

import pytest

from bosc_LoadUnit_api import *


def test_api_bosc_LoadUnit_reset_basic(env):
    """测试复位 API 的基础功能与参数检查。

    测试目标:
        验证 `api_bosc_LoadUnit_reset` 能正确执行标准复位序列，并对非法参数给出异常。

    测试流程:
        1. 调用复位 API 完成 2 拍复位和 1 拍释放。
        2. 检查返回的周期统计和关键输出空闲状态。
        3. 继续推进多拍，验证 API 之后电路仍可正常前进。
        4. 检查非法 `reset_cycles/max_cycles` 时会抛出 `ValueError`。

    预期结果:
        - 复位 API 返回值中的周期统计正确。
        - 复位释放后 `reset_pin` 为 0，主要写回输出保持无效。
        - 多拍 `Step` 不会引发异常。
        - 非法参数能被 API 拦截。
    """
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-RESET-AND-CLOCK",
        test_api_bosc_LoadUnit_reset_basic,
        ["CK-RESET-SEQUENCE", "CK-MULTI-CYCLE-STEP"],
    )

    result = api_bosc_LoadUnit_reset(env, reset_cycles=2, max_cycles=8)
    assert result["reset_cycles"] == 2
    assert result["consumed_cycles"] == 3
    assert env.reset_pin.value == 0
    assert env.scalar_resp.valid.value == 0
    assert env.vector_resp.valid.value == 0

    env.Step(2)
    assert env.reset_pin.value == 0

    with pytest.raises(ValueError):
        api_bosc_LoadUnit_reset(env, reset_cycles=0, max_cycles=8)
    with pytest.raises(ValueError):
        api_bosc_LoadUnit_reset(env, reset_cycles=4, max_cycles=3)


def test_api_bosc_LoadUnit_send_scalar_load_basic(env):
    """测试标量 load 发射 API 的基础功能与参数检查。

    测试目标:
        验证 `api_bosc_LoadUnit_send_scalar_load` 能完成基础 ready/valid 握手，并按预期填充关键请求字段。

    测试流程:
        1. 先执行一次标准复位，确保 DUT 处于空闲状态。
        2. 发送一个标量 load 请求并等待握手完成。
        3. 检查返回镜像中的 `src0/robIdx/lqIdx/sqIdx/pc` 等关键字段。
        4. 检查请求发射结束后 `valid` 已被 API 拉低。
        5. 检查非法参数会触发 `ValueError`。

    预期结果:
        - 标量请求被成功接收。
        - 请求镜像字段与输入参数一致。
        - 非法参数被正确拒绝。
    """
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-SEND-SCALAR-LOAD",
        test_api_bosc_LoadUnit_send_scalar_load_basic,
        ["CK-READY-HANDSHAKE"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    result = api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1234,
        fu_op_type=5,
        rob_idx=3,
        lq_idx=2,
        sq_idx=1,
        pc=0x2000,
        max_cycles=12,
    )

    assert result["accepted"] is True
    assert result["request"]["src"]["0"] == 0x1234
    assert result["request"]["uop"]["fuOpType"] == 5
    assert result["request"]["uop"]["robIdx"]["value"] == 3
    assert result["request"]["uop"]["lqIdx"]["value"] == 2
    assert result["request"]["uop"]["sqIdx"]["value"] == 1
    assert result["request"]["uop"]["pc"] == 0x2000
    assert env.scalar_req.valid.value == 0

    with pytest.raises(ValueError):
        api_bosc_LoadUnit_send_scalar_load(env, src0=-1, max_cycles=8)
    with pytest.raises(ValueError):
        api_bosc_LoadUnit_send_scalar_load(env, src0=0x1000, max_cycles=0)


def test_api_bosc_LoadUnit_hold_scalar_load_under_backpressure_basic(env):
    """测试标量 load 背压保持 API。

    测试目标:
        验证 `api_bosc_LoadUnit_hold_scalar_load_under_backpressure` 能在 `ready=0` 场景下保持
        标量请求载荷稳定，并返回可用于断言的背压历史。

    测试流程:
        1. 复位 DUT。
        2. 调用背压 API，用高优先级 misalign 请求压住普通标量请求。
        3. 检查返回结果中的 `ready_history`、`held` 和 `stable`。
        4. 检查非法周期参数会抛出 `ValueError`。

    预期结果:
        - 标量请求至少出现一次 `ready=0`。
        - 背压期间关键字段保持不变。
        - 非法周期参数抛出 `ValueError`。
    """
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-SEND-SCALAR-LOAD",
        test_api_bosc_LoadUnit_hold_scalar_load_under_backpressure_basic,
        ["CK-BACKPRESSURE-HOLD"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    result = api_bosc_LoadUnit_hold_scalar_load_under_backpressure(
        env,
        src0=0x1800,
        fu_op_type=0,
        rob_idx=4,
        lq_idx=3,
        sq_idx=0,
        pc=0x1800,
        hold_cycles=3,
        max_cycles=8,
    )

    assert result["held"] is True
    assert result["stable"] is True
    assert 0 in result["ready_history"]
    assert result["before"]["src"]["0"] == 0x1800
    assert result["after"]["uop"]["robIdx"]["value"] == 4

    with pytest.raises(ValueError):
        api_bosc_LoadUnit_hold_scalar_load_under_backpressure(env, src0=0x1000, hold_cycles=1, max_cycles=8)
    with pytest.raises(ValueError):
        api_bosc_LoadUnit_hold_scalar_load_under_backpressure(env, src0=0x1000, hold_cycles=3, max_cycles=2)


def test_api_bosc_LoadUnit_send_vector_load_basic(env):
    """测试向量 load 发射 API 的基础功能与字段填充。

    测试目标:
        验证 `api_bosc_LoadUnit_send_vector_load` 能完成向量请求握手，并按预期封装地址、mask 和元素索引字段。

    测试流程:
        1. 复位 DUT。
        2. 调用向量发射 API 发送一条带 mask 和元素索引的请求。
        3. 检查返回镜像中的 `vaddr/mask/reg_offset/elemIdx` 等字段。
        4. 验证无效参数会被 API 拦截。

    预期结果:
        - 向量请求成功握手。
        - 关键字段填充正确。
        - 非法参数抛出 `ValueError`。
    """
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-SEND-VECTOR-LOAD",
        test_api_bosc_LoadUnit_send_vector_load_basic,
        ["CK-VECTOR-HANDSHAKE", "CK-VECTOR-FIELD-FILL"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    result = api_bosc_LoadUnit_send_vector_load(
        env,
        vaddr=0x4000,
        mask=0x5A,
        reg_offset=3,
        elem_idx=4,
        elem_idx_inside_vd=1,
        aligned_type=2,
        vec_active=1,
        rob_idx=7,
        lq_idx=5,
        pc=0x3000,
        max_cycles=12,
    )

    assert result["accepted"] is True
    assert result["request"]["vaddr"] == 0x4000
    assert result["request"]["mask"] == 0x5A
    assert result["request"]["reg_offset"] == 3
    assert result["request"]["elemIdx"] == 4
    assert result["request"]["elemIdxInsideVd"] == 1
    assert result["request"]["alignedType"] == 2
    assert result["request"]["uop"]["robIdx"]["value"] == 7
    assert result["request"]["uop"]["lqIdx"]["value"] == 5
    assert env.vector_req.valid.value == 0

    with pytest.raises(ValueError):
        api_bosc_LoadUnit_send_vector_load(env, vaddr=-1, max_cycles=8)
    with pytest.raises(ValueError):
        api_bosc_LoadUnit_send_vector_load(env, vaddr=0x4000, max_cycles=0)


def test_api_bosc_LoadUnit_inject_memory_resp_basic(env):
    """测试存储系统响应注入 API 的基础功能与参数检查。

    测试目标:
        验证 `api_bosc_LoadUnit_inject_memory_resp` 能正确驱动 TLB/PMP/DCache/前递相关输入，并在单拍后清理瞬时信号。

    测试流程:
        1. 复位 DUT。
        2. 调用注入 API，同时给出 TLB、PMP、DCache 和 LSQ forward 参数。
        3. 检查返回摘要是否保留了本次注入的关键配置。
        4. 检查 API 调用结束后瞬时响应信号已经被清零。
        5. 检查非法 `forward_source/max_cycles` 参数的异常处理。

    预期结果:
        - 注入摘要正确。
        - 单拍注入后输入恢复到非有效状态。
        - 非法参数抛出 `ValueError`。
    """
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-INJECT-MEMORY-RESP",
        test_api_bosc_LoadUnit_inject_memory_resp_basic,
        ["CK-TLB-PMP-INJECT", "CK-DCACHE-FORWARD-INJECT"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    result = api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x8888,
        pmp_ld=True,
        dcache_data=0x1122334455667788,
        forward_source="lsq",
        forward_data=0xFFEEDDCCBBAA99887766554433221100,
        forward_mask=0x00FF,
        max_cycles=1,
    )

    assert result["tlb_valid"] == 1
    assert result["tlb_paddr"] == 0x8888
    assert result["pmp_ld"] == 1
    assert result["dcache_data"] == 0x1122334455667788
    assert result["forward_source"] == "lsq"
    assert result["forward_mask"] == 0x00FF

    assert env.tlb.resp.valid.value == 0
    assert env.pmp.ld.value == 0
    assert env.dcache.resp_bits.data.value == 0
    assert env.dcache.s2.bank_conflict.value == 0

    with pytest.raises(ValueError):
        api_bosc_LoadUnit_inject_memory_resp(env, forward_source="bad", max_cycles=1)
    with pytest.raises(ValueError):
        api_bosc_LoadUnit_inject_memory_resp(env, max_cycles=0)


def test_api_bosc_LoadUnit_collect_writeback_feedback_basic(env):
    """测试输出采集 API 的基础功能与异常处理。

    测试目标:
        验证 `api_bosc_LoadUnit_collect_writeback_feedback` 能在最小标量命中路径下采集到 `ldout` 与 `feedback_slow`，
        并对非法参数做出异常响应。

    测试流程:
        1. 复位 DUT。
        2. 发送一条标量 load 请求。
        3. 注入 TLB 与 DCache 正常响应。
        4. 调用输出采集 API，检查是否成功采集标量写回和控制反馈。
        5. 检查非法 `max_cycles` 参数会抛出 `ValueError`。

    预期结果:
        - `scalar_writeback` 与 `feedback_slow` 被成功采集。
        - 采集结果中的关键索引与请求一致。
        - 非法参数抛出 `ValueError`。
    """
    env.dut.fc_cover["FG-API"].mark_function(
        "FC-COLLECT-WRITEBACK-FEEDBACK",
        test_api_bosc_LoadUnit_collect_writeback_feedback_basic,
        ["CK-SCALAR-CAPTURE", "CK-VECTOR-AND-CONTROL-CAPTURE"],
    )

    api_bosc_LoadUnit_reset(env, max_cycles=8)
    api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=0x1000,
        fu_op_type=0,
        rob_idx=1,
        lq_idx=1,
        sq_idx=0,
        pc=0x1000,
        max_cycles=12,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=0x3000,
        dcache_data=0x1122334455667788,
        max_cycles=1,
    )
    result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=12)

    assert result["scalar_writeback"] is not None
    assert result["feedback_slow"] is not None
    assert result["scalar_writeback"]["uop"]["robIdx"]["value"] == 1
    assert result["scalar_writeback"]["uop"]["lqIdx"]["value"] == 1
    assert result["scalar_writeback"]["debug"]["paddr"] == 0x3000
    assert result["scalar_writeback"]["debug"]["vaddr"] == 0x1000
    assert result["feedback_slow"]["robIdx"]["value"] == 1
    assert result["feedback_slow"]["lqIdx"]["value"] == 1

    with pytest.raises(ValueError):
        api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=-1)
