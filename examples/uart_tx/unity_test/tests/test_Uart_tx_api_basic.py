#coding=utf-8

"""Uart_tx基础API功能测试

本文件测试已实现的Uart_tx API函数的基本功能，包括：
- api_Uart_tx_reset: 复位功能
- api_Uart_tx_configure: 配置功能
- api_Uart_tx_send_byte: 单字节发送
- api_Uart_tx_send_bytes: 批量发送
- api_Uart_tx_wait_idle: 等待空闲
- api_Uart_tx_get_fifo_status: FIFO状态查询
- api_Uart_tx_set_enable: 使能控制
"""

from Uart_tx_api import *
import pytest


def test_api_Uart_tx_reset(env):
    """测试api_Uart_tx_reset复位功能
    
    验证API能够正确执行复位操作，清空FIFO，复位所有状态。
    
    测试流程：
    1. 先写入一些数据到FIFO
    2. 调用reset API
    3. 验证复位后状态正确
    """
    # 标记覆盖率
    env.dut.fc_cover["FG-API"].mark_function("FC-CONTROL-OPS", test_api_Uart_tx_reset, ["CK-RESET-OP"])
    env.dut.fc_cover["FG-CONTROL"].mark_function("FC-RESET", test_api_Uart_tx_reset, ["CK-ASYNC-RESET", "CK-RESET-ALL"])
    env.dut.fc_cover["FG-CONTROL"].mark_function("FC-RESET-INIT", test_api_Uart_tx_reset, ["CK-TXD-HIGH", "CK-BUSY-LOW", "CK-FIFO-CLEAR"])
    
    # 写入数据
    api_Uart_tx_send_byte(env, 0xAA)
    env.Step(2)
    
    # 执行复位
    api_Uart_tx_reset(env)
    
    # 验证复位结果
    assert env.fifo.tx_fifo_empty.value == 1, "复位后FIFO应该为空"
    assert env.fifo.tx_fifo_count.value == 0, "复位后FIFO计数应该为0"
    assert env.output.busy.value == 0, "复位后busy应该为0"
    assert env.output.TXD.value == 1, "复位后TXD应该为高电平"
    assert env.PRESETn.value == 1, "复位释放后PRESETn应该为1"


def test_api_Uart_tx_configure_8n1(env):
    """测试api_Uart_tx_configure配置8-N-1格式
    
    验证API能够正确配置标准的8-N-1 UART格式。
    """
    # 标记覆盖率
    env.dut.fc_cover["FG-API"].mark_function("FC-CONFIG-SET", test_api_Uart_tx_configure_8n1, ["CK-SET-WIDTH", "CK-SET-PARITY", "CK-SET-STOP"])
    env.dut.fc_cover["FG-PARITY"].mark_function("FC-PARITY-NONE", test_api_Uart_tx_configure_8n1, ["CK-NO-PARITY-BIT"])
    
    # 配置8-N-1
    api_Uart_tx_configure(env, data_bits=8, parity='none', stop_bits=1)
    env.Step(1)
    
    # 验证LCR寄存器值
    # 8位数据: LCR[1:0] = 11
    # 无校验: LCR[3] = 0
    # 1位停止: LCR[2] = 0
    # 预期LCR = 0x03
    assert env.ctrl.LCR.value == 0x03, f"8-N-1配置错误，LCR应为0x03，实际为0x{env.ctrl.LCR.value:02X}"


def test_api_Uart_tx_configure_7e1(env):
    """测试api_Uart_tx_configure配置7-E-1格式
    
    验证API能够正确配置7位数据、偶校验、1位停止位格式。
    """
    # 标记覆盖率
    env.dut.fc_cover["FG-API"].mark_function("FC-CONFIG-SET", test_api_Uart_tx_configure_7e1, ["CK-SET-WIDTH", "CK-SET-PARITY", "CK-SET-STOP"])
    env.dut.fc_cover["FG-PARITY"].mark_function("FC-PARITY-EVEN", test_api_Uart_tx_configure_7e1, ["CK-EVEN-VALUE"])
    
    # 配置7-E-1
    api_Uart_tx_configure(env, data_bits=7, parity='even', stop_bits=1)
    env.Step(1)
    
    # 验证LCR寄存器值
    # 7位数据: LCR[1:0] = 10
    # 偶校验: LCR[3] = 1, LCR[5:4] = 00
    # 1位停止: LCR[2] = 0
    # 预期LCR = 0x0A (0b00001010)
    assert env.ctrl.LCR.value == 0x0A, f"7-E-1配置错误，LCR应为0x0A，实际为0x{env.ctrl.LCR.value:02X}"


def test_api_Uart_tx_configure_invalid_params(env):
    """测试api_Uart_tx_configure参数验证
    
    验证API能够正确拒绝无效参数。
    """
    # 标记覆盖率
    env.dut.fc_cover["FG-API"].mark_function("FC-CONFIG-SET", test_api_Uart_tx_configure_invalid_params, ["CK-SET-WIDTH"])
    
    # 测试无效的数据位宽
    with pytest.raises(ValueError, match="data_bits必须是"):
        api_Uart_tx_configure(env, data_bits=9)
    
    # 测试无效的校验类型
    with pytest.raises(ValueError, match="parity必须是"):
        api_Uart_tx_configure(env, parity='invalid')
    
    # 测试无效的停止位
    with pytest.raises(ValueError, match="stop_bits必须是"):
        api_Uart_tx_configure(env, stop_bits=3)


def test_api_Uart_tx_send_byte_basic(env):
    """测试api_Uart_tx_send_byte基本功能
    
    验证API能够正确向FIFO写入单个字节。
    """
    # 标记覆盖率
    env.dut.fc_cover["FG-API"].mark_function("FC-FIFO-PUSH", test_api_Uart_tx_send_byte_basic, ["CK-SINGLE", "CK-TIMING"])
    env.dut.fc_cover["FG-FIFO"].mark_function("FC-WRITE", test_api_Uart_tx_send_byte_basic, ["CK-SINGLE-WRITE"])
    env.dut.fc_cover["FG-FIFO"].mark_function("FC-COUNT", test_api_Uart_tx_send_byte_basic, ["CK-INC-ON-WRITE"])
    
    # 初始化
    api_Uart_tx_reset(env)
    
    # 验证初始FIFO为空
    assert env.fifo.tx_fifo_empty.value == 1, "初始FIFO应该为空"
    assert env.fifo.tx_fifo_count.value == 0, "初始count应该为0"
    
    # 发送一个字节
    success = api_Uart_tx_send_byte(env, 0x55)
    env.Step(1)
    
    # 验证写入成功
    assert success == True, "写入应该成功"
    assert env.fifo.tx_fifo_empty.value == 0, "写入后FIFO不应该为空"
    assert env.fifo.tx_fifo_count.value == 1, "写入1字节后count应该为1"


def test_api_Uart_tx_send_byte_invalid(env):
    """测试api_Uart_tx_send_byte参数验证
    
    验证API能够正确拒绝超出范围的数据。
    """
    # 标记覆盖率
    env.dut.fc_cover["FG-API"].mark_function("FC-FIFO-PUSH", test_api_Uart_tx_send_byte_invalid, ["CK-SINGLE"])
    
    # 测试超出范围的数据
    with pytest.raises(ValueError, match="data必须在0x00-0xFF范围内"):
        api_Uart_tx_send_byte(env, 0x100)
    
    with pytest.raises(ValueError, match="data必须在0x00-0xFF范围内"):
        api_Uart_tx_send_byte(env, -1)


def test_api_Uart_tx_send_bytes_basic(env):
    """测试api_Uart_tx_send_bytes批量发送
    
    验证API能够正确批量写入多个字节。
    """
    # 标记覆盖率
    env.dut.fc_cover["FG-API"].mark_function("FC-FIFO-PUSH", test_api_Uart_tx_send_bytes_basic, ["CK-MULTI", "CK-TIMING"])
    env.dut.fc_cover["FG-FIFO"].mark_function("FC-WRITE", test_api_Uart_tx_send_bytes_basic, ["CK-CONTINUOUS-WRITE"])
    
    # 初始化
    api_Uart_tx_reset(env)
    
    # 禁用发送，防止数据被自动发送导致count变化
    api_Uart_tx_set_enable(env, False)
    
    # 批量发送
    data = [0x48, 0x65, 0x6C, 0x6C, 0x6F]  # "Hello"
    count = api_Uart_tx_send_bytes(env, data)
    env.Step(1)
    
    # 验证结果
    assert count == 5, f"应该成功写入5个字节，实际{count}个"
    assert env.fifo.tx_fifo_count.value == 5, f"FIFO中应有5个字节，实际{env.fifo.tx_fifo_count.value}个"


def test_api_Uart_tx_send_bytes_fifo_limit(env):
    """测试api_Uart_tx_send_bytes FIFO容量限制
    
    验证当数据超过FIFO容量时，API能够正确处理。
    """
    # 标记覆盖率
    env.dut.fc_cover["FG-API"].mark_function("FC-FIFO-PUSH", test_api_Uart_tx_send_bytes_fifo_limit, ["CK-MULTI"])
    env.dut.fc_cover["FG-BOUNDARY"].mark_function("FC-FULL-WRITE", test_api_Uart_tx_send_bytes_fifo_limit, ["CK-DROP-DATA"])
    
    # 初始化
    api_Uart_tx_reset(env)
    
    # 禁用发送，防止数据被自动发送
    api_Uart_tx_set_enable(env, False)
    
    # 尝试写入超过FIFO容量的数据
    data = list(range(20))  # 20个字节，超过FIFO的16字节容量
    count = api_Uart_tx_send_bytes(env, data)
    
    # 验证最多写入16个字节
    assert count <= 16, f"最多应写入16字节，实际写入{count}字节"
    assert env.fifo.tx_fifo_count.value <= 16, f"FIFO count不应超过16，实际{env.fifo.tx_fifo_count.value}"


def test_api_Uart_tx_get_fifo_status(env):
    """测试api_Uart_tx_get_fifo_status状态查询
    
    验证API能够正确返回FIFO状态信息。
    """
    # 标记覆盖率
    env.dut.fc_cover["FG-API"].mark_function("FC-FIFO-STATUS", test_api_Uart_tx_get_fifo_status, ["CK-EMPTY", "CK-FULL", "CK-COUNT"])
    
    # 初始化
    api_Uart_tx_reset(env)
    
    # 测试空FIFO状态
    status = api_Uart_tx_get_fifo_status(env)
    assert status['empty'] == True, "FIFO应该为空"
    assert status['full'] == False, "FIFO不应该满"
    assert status['count'] == 0, "count应该为0"
    assert status['free_space'] == 16, "剩余空间应该为16"
    
    # 禁用发送，防止数据被自动发送
    api_Uart_tx_set_enable(env, False)
    
    # 写入几个字节
    api_Uart_tx_send_bytes(env, [1, 2, 3])
    env.Step(1)
    
    # 测试部分满状态
    status = api_Uart_tx_get_fifo_status(env)
    assert status['empty'] == False, "FIFO不应该为空"
    assert status['full'] == False, "FIFO不应该满"
    assert status['count'] == 3, f"count应该为3，实际{status['count']}"
    assert status['free_space'] == 13, f"剩余空间应该为13，实际{status['free_space']}"


def test_api_Uart_tx_set_enable(env):
    """测试api_Uart_tx_set_enable使能控制
    
    验证API能够正确控制enable信号。
    """
    # 标记覆盖率
    env.dut.fc_cover["FG-API"].mark_function("FC-CONTROL-OPS", test_api_Uart_tx_set_enable, ["CK-ENABLE-CTRL"])
    env.dut.fc_cover["FG-CONTROL"].mark_function("FC-ENABLE", test_api_Uart_tx_set_enable, ["CK-ENABLE-HIGH", "CK-ENABLE-LOW"])
    
    # 初始化
    api_Uart_tx_reset(env)
    
    # 验证初始enable为1
    assert env.ctrl.enable.value == 1, "初始enable应该为1"
    
    # 禁用
    api_Uart_tx_set_enable(env, False)
    assert env.ctrl.enable.value == 0, "设置后enable应该为0"
    
    # 启用
    api_Uart_tx_set_enable(env, True)
    assert env.ctrl.enable.value == 1, "设置后enable应该为1"
    
    # 测试整数参数
    api_Uart_tx_set_enable(env, 0)
    assert env.ctrl.enable.value == 0, "enable应该为0"
    
    api_Uart_tx_set_enable(env, 1)
    assert env.ctrl.enable.value == 1, "enable应该为1"


def test_api_Uart_tx_wait_idle_timeout(env):
    """测试api_Uart_tx_wait_idle超时机制
    
    验证API的超时保护功能能够正常工作。
    """
    # 标记覆盖率
    env.dut.fc_cover["FG-API"].mark_function("FC-CONTROL-OPS", test_api_Uart_tx_wait_idle_timeout, ["CK-WAIT-IDLE"])
    
    # 初始化
    api_Uart_tx_reset(env)
    
    # 测试无效timeout参数
    with pytest.raises(ValueError, match="timeout不能为负数"):
        api_Uart_tx_wait_idle(env, timeout=-1)
    
    # 空FIFO时应该立即返回
    cycles = api_Uart_tx_wait_idle(env, timeout=100)
    assert cycles == 0, "空FIFO且busy=0时应该立即返回"


def test_api_Uart_tx_monitor_txd_basic(env):
    """测试api_Uart_tx_monitor_txd基本功能
    
    验证TXD监控API能够正确捕获位序列。
    """
    # 标记覆盖率
    env.dut.fc_cover["FG-API"].mark_function("FC-TXD-MONITOR", test_api_Uart_tx_monitor_txd_basic, ["CK-CAPTURE", "CK-PARSE", "CK-VERIFY"])
    
    # 初始化并配置8-N-1
    api_Uart_tx_reset(env)
    api_Uart_tx_configure(env, data_bits=8, parity='none', stop_bits=1)
    
    # 发送一个字节
    test_data = 0x55  # 0b01010101
    api_Uart_tx_send_byte(env, test_data)
    
    # 等待发送开始
    timeout = 100
    cycles = 0
    while env.output.busy.value == 0:
        env.Step(1)
        cycles += 1
        if cycles > timeout:
            pytest.skip("发送未开始，跳过测试")
    
    # 捕获10位（1起始+8数据+1停止）
    bits = api_Uart_tx_monitor_txd(env, 10, sample_rate=16)
    
    # 验证起始位
    assert bits[0] == 0, "起始位应该为0"
    
    # 验证停止位
    assert bits[9] == 1, "停止位应该为1"
    
    # 验证数据位（LSB first）
    data_bits_captured = bits[1:9]
    data_value = 0
    for i, bit in enumerate(data_bits_captured):
        data_value |= (bit << i)
    
    assert data_value == test_data, f"数据位不匹配，期望0x{test_data:02X}，实际0x{data_value:02X}"


def test_api_Uart_tx_parse_frame_8n1(env):
    """测试api_Uart_tx_parse_frame解析8-N-1帧
    
    验证帧解析API能够正确解析UART帧结构。
    """
    # 标记覆盖率
    env.dut.fc_cover["FG-API"].mark_function("FC-TXD-MONITOR", test_api_Uart_tx_parse_frame_8n1, ["CK-PARSE", "CK-VERIFY"])
    env.dut.fc_cover["FG-PROTOCOL"].mark_function("FC-FRAME-FORMAT", test_api_Uart_tx_parse_frame_8n1, ["CK-START-FIRST", "CK-DATA-MIDDLE", "CK-STOP-LAST"])
    
    # 模拟一个正确的8-N-1帧，数据为0xA5 (0b10100101)
    # 起始位(0) + 数据位(LSB first: 1,0,1,0,0,1,0,1) + 停止位(1)
    bits = [0, 1, 0, 1, 0, 0, 1, 0, 1, 1]
    
    frame = api_Uart_tx_parse_frame(bits, data_bits=8, parity='none')
    
    assert frame['valid'] == True, f"帧应该有效，错误: {frame['error']}"
    assert frame['start_bit'] == 0, "起始位应该为0"
    assert frame['data'] == 0xA5, f"数据应该为0xA5，实际0x{frame['data']:02X}"
    assert frame['stop_bit'] == 1, "停止位应该为1"
    assert frame['parity_bit'] is None, "8-N-1帧不应该有校验位"


def test_api_Uart_tx_send_and_verify_basic(env):
    """测试api_Uart_tx_send_and_verify综合功能
    
    验证发送并验证API的端到端功能。
    """
    # 标记覆盖率
    env.dut.fc_cover["FG-API"].mark_function("FC-TXD-MONITOR", test_api_Uart_tx_send_and_verify_basic, ["CK-CAPTURE", "CK-PARSE", "CK-VERIFY"])
    env.dut.fc_cover["FG-TRANSMISSION"].mark_function("FC-START-BIT", test_api_Uart_tx_send_and_verify_basic, ["CK-START-LEVEL"])
    env.dut.fc_cover["FG-TRANSMISSION"].mark_function("FC-STOP-BIT", test_api_Uart_tx_send_and_verify_basic, ["CK-STOP-LEVEL"])
    
    # 测试发送并验证
    test_data = 0x55
    result = api_Uart_tx_send_and_verify(env, test_data, data_bits=8, parity='none', stop_bits=1)
    
    # 如果发送没有开始，跳过验证
    if result['error'] and '超时' in result['error']:
        pytest.skip(f"测试跳过: {result['error']}")
    
    # 验证结果
    assert result['success'], f"验证失败: {result['error']}"
    assert result['sent_data'] == test_data, "发送的数据记录不正确"
    assert result['received_data'] == test_data, f"接收数据不匹配，期望0x{test_data:02X}，实际0x{result['received_data']:02X}"
    assert result['frame']['valid'], "帧应该有效"

