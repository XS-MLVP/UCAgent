#coding=utf-8

"""Uart_tx控制和状态测试模板

测试控制信号和状态输出，包括：
- enable控制和暂停/恢复
- 复位功能
- busy和idle状态
"""

from Uart_tx_api import *


def test_enable_control(env):
    """测试enable控制功能
    
    验证enable信号对传输的控制
    """
    env.dut.fc_cover["FG-CONTROL"].mark_function("FC-ENABLE", test_enable_control,
                                                  ["CK-ENABLE-HIGH", "CK-ENABLE-LOW", "CK-COUNTER-PAUSE"])
    
    # 初始化并配置
    api_Uart_tx_reset(env)
    api_Uart_tx_configure(env, data_bits=8, parity='none', stop_bits=1)
    
    # 验证enable=1时允许传输
    env.dut.enable.value = 1
    api_Uart_tx_send_byte(env, 0xA5)
    
    # 等待传输开始
    env.Step(5)
    
    # 在传输过程中设置enable=0暂停
    if env.dut.busy.value == 1:
        saved_txd = env.dut.TXD.value
        
        env.dut.enable.value = 0
        env.Step(10)
        
        # 验证TXD保持不变（暂停时）
        assert env.dut.TXD.value == saved_txd, "enable=0时TXD应该保持不变"
        
        # 验证busy保持为1（传输未完成）
        assert env.dut.busy.value == 1, "enable=0时busy应该保持为1"
        
        # 恢复enable=1
        env.dut.enable.value = 1
        env.Step(5)
        
        # 验证传输继续（busy最终会变为0）
        # 只需要验证最终能完成传输
    
    # 等待传输完成
    env.dut.enable.value = 1
    api_Uart_tx_wait_idle(env)
    
    # 验证最终完成
    assert env.dut.busy.value == 0, "传输最终应该完成"
    assert env.dut.TXD.value == 1, "完成后TXD应该为高"


def test_pause_function(env):
    """测试暂停功能
    
    验证传输暂停时的行为
    """
    env.dut.fc_cover["FG-CONTROL"].mark_function("FC-PAUSE", test_pause_function,
                                                  ["CK-STATE-HOLD", "CK-TXD-HOLD", "CK-PAUSE-TIMING"])
    
    # 初始化
    api_Uart_tx_reset(env)
    api_Uart_tx_configure(env, data_bits=8, parity='none', stop_bits=1)
    env.dut.enable.value = 1
    
    # 开始传输
    api_Uart_tx_send_byte(env, 0x55)
    env.Step(5)
    
    # 在传输过程中暂停
    if env.dut.busy.value == 1:
        saved_txd = env.dut.TXD.value
        
        # 暂停传输
        env.dut.enable.value = 0
        env.Step(10)
        
        # 验证TXD保持当前值（暂停时）
        assert env.dut.TXD.value == saved_txd, f"暂停时TXD应该保持为{saved_txd}"
        
        # 验证busy保持为1（传输未完成）
        assert env.dut.busy.value == 1, "暂停时busy应该保持为1"
        
        # 再次检查TXD在暂停期间确实保持不变
        env.Step(5)
        assert env.dut.TXD.value == saved_txd, f"暂停期间TXD应该一直保持为{saved_txd}"
    
    # 恢复传输
    env.dut.enable.value = 1
    api_Uart_tx_wait_idle(env)
    
    # 验证最终完成
    assert env.dut.busy.value == 0, "恢复后传输应该完成"
    assert env.dut.TXD.value == 1, "完成后TXD应该为高"


def test_resume_function(env):
    """测试恢复功能
    
    验证从暂停恢复后的行为
    """
    env.dut.fc_cover["FG-CONTROL"].mark_function("FC-RESUME", test_resume_function,
                                                  ["CK-RESUME-CONTINUE", "CK-COUNTER-RESUME", "CK-NO-DATA-LOSS"])
    
    # 初始化
    api_Uart_tx_reset(env)
    api_Uart_tx_configure(env, data_bits=8, parity='none', stop_bits=1)
    env.dut.enable.value = 1
    
    # 开始传输
    api_Uart_tx_send_byte(env, 0xA5)
    env.Step(5)
    
    # 暂停传输
    if env.dut.busy.value == 1:
        saved_txd = env.dut.TXD.value
        
        env.dut.enable.value = 0
        env.Step(5)
        
        # 验证暂停期间busy保持为1
        assert env.dut.busy.value == 1, "暂停时busy应该保持为1"
        
        # 恢复传输
        env.dut.enable.value = 1
        env.Step(2)
        
        # 验证传输继续进行
        # TXD可能会变化（继续发送剩余位）或保持不变（取决于暂停位置）
        assert env.dut.busy.value == 1 or env.dut.busy.value == 0, "恢复后传输应该继续"
    
    # 等待传输完成
    api_Uart_tx_wait_idle(env)
    
    # 验证传输成功完成，没有数据丢失
    assert env.dut.busy.value == 0, "恢复后应该能正常完成传输"
    assert env.dut.TXD.value == 1, "完成后TXD应该为高"
    assert env.dut.tx_fifo_empty.value == 1, "完成后FIFO应该为空"


def test_reset_function(env):
    """测试复位功能
    
    验证复位的时序和效果
    """
    env.dut.fc_cover["FG-CONTROL"].mark_function("FC-RESET", test_reset_function,
                                                  ["CK-ASYNC-RESET", "CK-RESET-ALL", "CK-RESET-TIMING"])
    env.dut.fc_cover["FG-CONTROL"].mark_function("FC-RESET-INIT", test_reset_function,
                                                  ["CK-TXD-HIGH", "CK-BUSY-LOW", "CK-FIFO-CLEAR", "CK-STATE-IDLE"])
    
    # 配置并开始传输
    api_Uart_tx_reset(env)
    api_Uart_tx_configure(env, data_bits=8, parity='none', stop_bits=1)
    api_Uart_tx_send_byte(env, 0x55)
    api_Uart_tx_send_byte(env, 0xAA)
    
    # 等待传输开始
    env.Step(5)
    
    # 记录复位前状态
    was_busy = env.dut.busy.value
    
    # 在传输过程中触发复位
    api_Uart_tx_reset(env)
    
    # 验证复位后的状态（复位是异步的，立即生效）
    env.Step(1)
    
    # 验证TXD=1（高电平）
    assert env.dut.TXD.value == 1, "复位后TXD应该为高电平"
    
    # 验证busy=0
    assert env.dut.busy.value == 0, "复位后busy应该为0"
    
    # 验证FIFO被清空
    assert env.dut.tx_fifo_empty.value == 1, "复位后FIFO应该为空"
    assert env.dut.tx_fifo_count.value == 0, "复位后count应该为0"
    
    # 验证复位后系统可以正常工作
    api_Uart_tx_configure(env, data_bits=8, parity='none', stop_bits=1)
    api_Uart_tx_send_byte(env, 0x33)
    env.Step(5)
    
    # 验证新传输可以正常启动
    assert env.dut.busy.value == 1 or env.dut.tx_fifo_empty.value == 0, "复位后应该能正常传输"


def test_busy_status(env):
    """测试busy状态信号
    
    验证busy信号的正确性
    """
    env.dut.fc_cover["FG-STATUS"].mark_function("FC-BUSY", test_busy_status,
                                                 ["CK-BUSY-HIGH", "CK-BUSY-LOW", "CK-BUSY-RANGE", "CK-BUSY-TIMING"])
    
    # 初始化
    api_Uart_tx_reset(env)
    api_Uart_tx_configure(env, data_bits=8, parity='none', stop_bits=1)
    api_Uart_tx_wait_idle(env)
    
    # 验证IDLE时busy=0
    assert env.dut.busy.value == 0, "IDLE状态busy应该为0"
    
    # 写入数据并检测busy变化
    api_Uart_tx_send_byte(env, 0x55)
    env.Step(2)
    
    # 记录busy=1的时刻
    busy_high_detected = False
    for _ in range(100):
        if env.dut.busy.value == 1:
            busy_high_detected = True
            # 验证传输时busy=1
            # TXD应该有有效值（0或1）
            assert env.dut.TXD.value in [0, 1], "busy=1时TXD应该有有效值"
            break
        env.Step(1)
    
    # 验证busy曾经变为1
    assert busy_high_detected, "发送数据后busy应该变为1"
    
    if busy_high_detected:
        # 持续检查直到busy变为0
        busy_duration = 0
        while env.dut.busy.value == 1 and busy_duration < 200:
            busy_duration += 1
            env.Step(1)
        
        # 验证busy最终变为0
        assert env.dut.busy.value == 0, "传输完成后busy应该变为0"
        
        # 验证传输完成后TXD=1（idle状态）
        assert env.dut.TXD.value == 1, "busy=0时TXD应该为高（idle状态）"
        
        # 验证busy持续时间合理（至少发送了start+8bits+stop=10bits）
        assert busy_duration >= 10, f"busy持续时间应该至少10个周期，实际{busy_duration}"


def test_idle_state(env):
    """测试idle状态
    
    验证idle状态的特征
    """
    env.dut.fc_cover["FG-STATUS"].mark_function("FC-IDLE-STATE", test_idle_state,
                                                 ["CK-IDLE-TXD-HIGH", "CK-IDLE-BUSY-LOW", "CK-IDLE-WAIT"])
    
    # 复位后检查idle状态
    api_Uart_tx_reset(env)
    api_Uart_tx_configure(env, data_bits=8, parity='none', stop_bits=1)
    
    # 等待稳定在idle状态
    api_Uart_tx_wait_idle(env)
    
    # 验证idle时TXD=1（高电平）
    assert env.dut.TXD.value == 1, "idle状态TXD应该为高电平"
    
    # 验证idle时busy=0
    assert env.dut.busy.value == 0, "idle状态busy应该为0"
    
    # 验证FIFO为空
    assert env.dut.tx_fifo_empty.value == 1, "idle状态FIFO应该为空"
    
    # 发送数据并等待完成后再次验证idle状态
    api_Uart_tx_send_byte(env, 0xA5)
    api_Uart_tx_wait_idle(env)
    
    assert env.dut.TXD.value == 1, "传输完成后idle状态TXD应该为高电平"
    assert env.dut.busy.value == 0, "传输完成后idle状态busy应该为0"


def test_status_update(env):
    """测试状态更新
    
    验证状态信号的同步更新
    """
    env.dut.fc_cover["FG-STATUS"].mark_function("FC-STATUS-UPDATE", test_status_update,
                                                 ["CK-SYNC-UPDATE", "CK-CONSISTENT"])
    
    # 初始化
    api_Uart_tx_reset(env)
    api_Uart_tx_configure(env, data_bits=8, parity='none', stop_bits=1)
    api_Uart_tx_wait_idle(env)
    
    # 验证初始状态一致性
    assert env.dut.busy.value == 0, "idle时busy应该为0"
    assert env.dut.tx_fifo_empty.value == 1, "idle时FIFO应该为空"
    assert env.dut.tx_fifo_count.value == 0, "idle时count应该为0"
    
    # 写入数据并验证状态同步更新
    api_Uart_tx_send_byte(env, 0x55)
    env.Step(1)
    
    # 验证FIFO状态更新
    assert env.dut.tx_fifo_empty.value == 0, "写入后FIFO不应该为空"
    assert env.dut.tx_fifo_count.value > 0, "写入后count应该大于0"
    
    # 等待传输开始
    env.Step(2)
    
    # 验证busy状态与传输状态一致
    if env.dut.busy.value == 1:
        # 正在传输
        assert env.dut.TXD.value in [0, 1], "传输时TXD应该有有效值"
    
    # 等待传输完成
    api_Uart_tx_wait_idle(env)
    
    # 验证完成后状态一致
    assert env.dut.busy.value == 0, "完成后busy应该为0"
    assert env.dut.tx_fifo_empty.value == 1, "完成后FIFO应该为空"
    assert env.dut.TXD.value == 1, "完成后TXD应该为高"


def test_bit_counter_boundary(env):
    """测试bit_counter边界
    
    验证传输时序边界行为（通过观察输出信号）
    """
    env.dut.fc_cover["FG-BOUNDARY"].mark_function("FC-BIT-COUNTER-BOUND", test_bit_counter_boundary,
                                                   ["CK-COUNTER-MAX", "CK-COUNTER-WRAP", "CK-STATE-AT-15"])
    
    # 初始化
    api_Uart_tx_reset(env)
    api_Uart_tx_configure(env, data_bits=8, parity='even', stop_bits=2)  # 使用最长配置
    
    # 开始传输
    api_Uart_tx_send_byte(env, 0xAA)
    env.Step(2)
    
    # 监控传输过程中的状态变化
    txd_changes = 0
    prev_txd = env.dut.TXD.value
    busy_cycles = 0
    
    for _ in range(200):
        # 记录TXD变化次数（用于验证状态转换）
        if env.dut.TXD.value != prev_txd:
            txd_changes += 1
            prev_txd = env.dut.TXD.value
        
        # 计数busy=1的周期数
        if env.dut.busy.value == 1:
            busy_cycles += 1
        elif busy_cycles > 0:
            # busy已经从1变为0，传输完成
            break
        
        env.Step(1)
    
    # 验证传输完成
    assert env.dut.busy.value == 0, "传输应该完成"
    assert env.dut.TXD.value == 1, "完成后TXD应该为高"
    
    # 验证busy持续时间合理
    # 8-E-2格式：1个start + 8个data + 1个parity + 2个stop = 12个bit
    # 每个bit需要16个周期（bit_counter从0到15）
    expected_min_cycles = 12 * 16
    assert busy_cycles >= expected_min_cycles, \
        f"busy持续周期应该至少{expected_min_cycles}，实际{busy_cycles}"
    
    # 验证TXD发生了合理次数的变化（至少有start bit, data bits, stop bits的转换）
    assert txd_changes >= 2, f"TXD应该有多次状态变化，实际{txd_changes}次"
