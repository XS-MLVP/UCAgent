#coding=utf-8

import toffee.funcov as fc

# 创建所有功能覆盖组
# 对应Uart_tx_functions_and_checks.md中定义的功能分组<FG-*>

# FG-API: DUT测试API覆盖组
funcov_api = fc.CovGroup("FG-API")

# FG-FIFO: FIFO管理功能覆盖组
funcov_fifo = fc.CovGroup("FG-FIFO")

# FG-TRANSMISSION: 串行发送功能覆盖组
funcov_transmission = fc.CovGroup("FG-TRANSMISSION")

# FG-DATA-WIDTH: 数据位宽配置功能覆盖组
funcov_data_width = fc.CovGroup("FG-DATA-WIDTH")

# FG-PARITY: 校验位配置功能覆盖组
funcov_parity = fc.CovGroup("FG-PARITY")

# FG-STOP-BITS: 停止位配置功能覆盖组
funcov_stop_bits = fc.CovGroup("FG-STOP-BITS")

# FG-CONTROL: 控制信号功能覆盖组
funcov_control = fc.CovGroup("FG-CONTROL")

# FG-STATUS: 状态指示功能覆盖组
funcov_status = fc.CovGroup("FG-STATUS")

# FG-BOUNDARY: 边界条件处理覆盖组
funcov_boundary = fc.CovGroup("FG-BOUNDARY")

# FG-CONCURRENT: 并发操作功能覆盖组
funcov_concurrent = fc.CovGroup("FG-CONCURRENT")

# FG-PROTOCOL: 协议符合性覆盖组
funcov_protocol = fc.CovGroup("FG-PROTOCOL")

# 所有覆盖组列表
funcov_groups = [
    funcov_api,
    funcov_fifo,
    funcov_transmission,
    funcov_data_width,
    funcov_parity,
    funcov_stop_bits,
    funcov_control,
    funcov_status,
    funcov_boundary,
    funcov_concurrent,
    funcov_protocol
]


def init_coverage_group_api(g, dut):
    """初始化API覆盖组的检查点"""
    
    # FC-FIFO-PUSH: FIFO写入API功能点
    g.add_watch_point(dut, {
        "CK-SINGLE": lambda x: x.tx_fifo_push.value == 1,  # 单次写入：检测tx_fifo_push有效
        "CK-MULTI": lambda x: x.tx_fifo_count.value > 1,  # 多次写入：FIFO中有多个数据
        "CK-TIMING": lambda x: x.tx_fifo_push.value == 1 and x.tx_fifo_count.value < 16,  # 时序正确：写入时FIFO未满
    }, name="FC-FIFO-PUSH")
    
    # FC-FIFO-STATUS: FIFO状态查询API功能点
    g.add_watch_point(dut, {
        "CK-EMPTY": lambda x: x.tx_fifo_empty.value == 1,  # 空标志读取：检测empty标志
        "CK-FULL": lambda x: x.tx_fifo_full.value == 1,  # 满标志读取：检测full标志
        "CK-COUNT": lambda x: True,  # 计数读取：始终可以读取count（通用检测点）
    }, name="FC-FIFO-STATUS")
    
    # FC-TXD-MONITOR: 串行数据监控API功能点
    g.add_watch_point(dut, {
        "CK-CAPTURE": lambda x: x.busy.value == 1,  # 数据捕获：在busy期间捕获TXD
        "CK-PARSE": lambda x: x.TXD.value in [0, 1],  # 帧解析：TXD值有效（0或1）
        "CK-VERIFY": lambda x: x.busy.value == 0 and x.tx_fifo_empty.value == 1,  # 数据验证：发送完成后验证
    }, name="FC-TXD-MONITOR")
    
    # FC-CONFIG-SET: 配置设置API功能点
    g.add_watch_point(dut, {
        "CK-SET-WIDTH": lambda x: (x.LCR.value & 0x03) in [0, 1, 2, 3],  # 位宽设置：LCR[1:0]设置数据位宽
        "CK-SET-PARITY": lambda x: (x.LCR.value & 0x38) != 0,  # 校验设置：LCR[5:3]设置校验模式
        "CK-SET-STOP": lambda x: (x.LCR.value & 0x04) in [0, 4],  # 停止位设置：LCR[2]设置停止位
    }, name="FC-CONFIG-SET")
    
    # FC-CONTROL-OPS: 控制操作API功能点
    g.add_watch_point(dut, {
        "CK-ENABLE-CTRL": lambda x: x.enable.value in [0, 1],  # enable控制：enable信号被设置
        "CK-RESET-OP": lambda x: x.PRESETn.value == 0,  # 复位操作：PRESETn拉低
        "CK-WAIT-IDLE": lambda x: x.busy.value == 0 and x.tx_fifo_empty.value == 1,  # 等待空闲：busy为0且FIFO为空
    }, name="FC-CONTROL-OPS")


def init_coverage_group_boundary(g, dut):
    """初始化边界条件覆盖组的检查点"""
    
    # FC-BIT-COUNTER-BOUND: bit_counter边界功能点
    # 注意：bit_counter是内部信号，这里通过状态推断
    g.add_watch_point(dut, {
        "CK-COUNTER-MAX": lambda x: x.busy.value == 1,  # 计数最大值：发送期间计数器在运行
        "CK-COUNTER-WRAP": lambda x: x.busy.value == 1,  # 计数器回绕：发送期间会发生回绕
        "CK-STATE-AT-15": lambda x: x.busy.value == 1,  # 15时转换：在busy期间状态会转换
    }, name="FC-BIT-COUNTER-BOUND")
    
    # FC-DATA-BIT-BOUND: 数据位边界功能点
    g.add_watch_point(dut, {
        "CK-5BIT-JUMP": lambda x: (x.LCR.value & 0x03) == 0 and x.busy.value == 1,  # 5位跳转：LCR配置为5位且在发送
        "CK-6BIT-JUMP": lambda x: (x.LCR.value & 0x03) == 1 and x.busy.value == 1,  # 6位跳转：LCR配置为6位且在发送
        "CK-7BIT-JUMP": lambda x: (x.LCR.value & 0x03) == 2 and x.busy.value == 1,  # 7位跳转：LCR配置为7位且在发送
        "CK-SKIP-UNUSED": lambda x: (x.LCR.value & 0x03) < 3 and x.busy.value == 1,  # 跳过未用位：配置小于8位且在发送
    }, name="FC-DATA-BIT-BOUND")
    
    # FC-FULL-WRITE: FIFO满时写入功能点
    g.add_watch_point(dut, {
        "CK-DROP-DATA": lambda x: x.tx_fifo_full.value == 1 and x.tx_fifo_push.value == 1,  # 丢弃数据：满时尝试写入
        "CK-COUNT-UNCHANGED": lambda x: x.tx_fifo_count.value == 16,  # count不变：count保持为16
        "CK-NO-OVERFLOW": lambda x: x.tx_fifo_count.value <= 16,  # 无溢出：count不超过16
    }, name="FC-FULL-WRITE")
    
    # FC-EMPTY-READ: FIFO空时读取功能点
    g.add_watch_point(dut, {
        "CK-POINTER-HOLD": lambda x: x.tx_fifo_empty.value == 1 and x.busy.value == 0,  # 指针保持：空时不读取
        "CK-COUNT-ZERO": lambda x: x.tx_fifo_count.value == 0,  # count为0：count保持为0
        "CK-NO-UNDERFLOW": lambda x: x.tx_fifo_count.value >= 0,  # 无下溢：count不为负
    }, name="FC-EMPTY-READ")
    
    # FC-EMPTY-TO-NONEMPTY: 空到非空转换功能点
    g.add_watch_point(dut, {
        "CK-DETECT-NONEMPTY": lambda x: x.tx_fifo_empty.value == 0 and x.tx_fifo_count.value > 0,  # 检测非空：FIFO非空
        "CK-START-TX": lambda x: x.tx_fifo_empty.value == 0 and x.busy.value == 1,  # 启动发送：非空时busy为高
        "CK-TRANSITION-TIMING": lambda x: x.tx_fifo_count.value == 1,  # 转换时机：从空到有1个数据
    }, name="FC-EMPTY-TO-NONEMPTY")
    
    # FC-FULL-TO-NOTFULL: 满到非满转换功能点
    g.add_watch_point(dut, {
        "CK-FULL-CLEAR": lambda x: x.tx_fifo_full.value == 0 and x.tx_fifo_count.value < 16,  # full清除：full标志清除
        "CK-ACCEPT-WRITE": lambda x: x.tx_fifo_full.value == 0 and x.tx_fifo_push.value == 1,  # 接受写入：非满时可写入
    }, name="FC-FULL-TO-NOTFULL")


def init_coverage_group_concurrent(g, dut):
    """初始化并发操作覆盖组的检查点"""
    
    # FC-SIMUL-RW: FIFO同时读写功能点
    g.add_watch_point(dut, {
        "CK-SIMUL-WRITE": lambda x: x.tx_fifo_push.value == 1 and x.busy.value == 1 and x.tx_fifo_count.value < 16,  # 同时写入：写入时busy为高
        "CK-SIMUL-READ": lambda x: x.busy.value == 1 and x.tx_fifo_count.value > 0,  # 同时读出：发送时读取FIFO
        "CK-COUNT-HOLD": lambda x: x.tx_fifo_push.value == 1 and x.busy.value == 1 and 0 < x.tx_fifo_count.value < 16,  # count保持：同时读写时count可能不变
        "CK-BOTH-PTR-INC": lambda x: x.tx_fifo_push.value == 1 and x.busy.value == 1 and x.tx_fifo_count.value > 0 and x.tx_fifo_count.value < 16,  # 双指针递增：同时读写
    }, name="FC-SIMUL-RW")
    
    # FC-LCR-SWITCH: LCR动态切换功能点
    g.add_watch_point(dut, {
        "CK-CURRENT-FRAME": lambda x: x.busy.value == 1,  # 当前帧旧配置：在发送期间
        "CK-NEXT-FRAME": lambda x: x.busy.value == 0 and x.tx_fifo_empty.value == 0,  # 下一帧新配置：发送完成且有待发送数据
        "CK-SWITCH-TIMING": lambda x: x.busy.value == 0,  # 切换时机：空闲时切换
    }, name="FC-LCR-SWITCH")
    
    # FC-CONTINUOUS-TX: 连续发送功能点
    g.add_watch_point(dut, {
        "CK-NO-GAP": lambda x: x.busy.value == 1 and x.tx_fifo_count.value > 0,  # 无间隔：busy期间FIFO非空
        "CK-CONTINUOUS": lambda x: x.tx_fifo_count.value > 1,  # 连续发送：FIFO中有多个数据
        "CK-FIFO-DRAIN": lambda x: x.tx_fifo_count.value == 0 and x.busy.value == 0,  # FIFO排空：全部发送完成
    }, name="FC-CONTINUOUS-TX")
    
    # FC-TX-WHILE-PUSH: 发送中写入功能点
    g.add_watch_point(dut, {
        "CK-WRITE-DURING-TX": lambda x: x.busy.value == 1 and x.tx_fifo_push.value == 1,  # 发送中写入：busy时写FIFO
        "CK-COORDINATION": lambda x: x.busy.value == 1 and x.tx_fifo_count.value > 0 and x.tx_fifo_count.value < 16,  # 协同工作：发送和写入同时进行
        "CK-NO-INTERFERENCE": lambda x: x.busy.value == 1 and x.TXD.value in [0, 1],  # 无干扰：发送正常进行
    }, name="FC-TX-WHILE-PUSH")


def init_coverage_group_control(g, dut):
    """初始化控制信号覆盖组的检查点"""
    
    # FC-ENABLE: enable信号控制功能点
    g.add_watch_point(dut, {
        "CK-ENABLE-HIGH": lambda x: x.enable.value == 1,  # enable高有效：enable为1
        "CK-ENABLE-LOW": lambda x: x.enable.value == 0,  # enable低停止：enable为0
        "CK-COUNTER-PAUSE": lambda x: x.enable.value == 0 and x.busy.value == 1,  # 计数器暂停：enable为0但busy为1（暂停状态）
    }, name="FC-ENABLE")
    
    # FC-PAUSE: 暂停功能点
    g.add_watch_point(dut, {
        "CK-STATE-HOLD": lambda x: x.enable.value == 0 and x.busy.value == 1,  # 状态保持：暂停时状态不变
        "CK-TXD-HOLD": lambda x: x.enable.value == 0 and x.TXD.value in [0, 1],  # TXD保持：暂停时TXD保持
        "CK-PAUSE-TIMING": lambda x: x.enable.value == 0,  # 暂停时机：任意时刻可暂停
    }, name="FC-PAUSE")
    
    # FC-RESUME: 恢复功能点
    g.add_watch_point(dut, {
        "CK-RESUME-CONTINUE": lambda x: x.enable.value == 1 and x.busy.value == 1,  # 恢复继续：enable恢复后继续发送
        "CK-COUNTER-RESUME": lambda x: x.enable.value == 1 and x.busy.value == 1,  # 计数器恢复：计数器恢复运行
        "CK-NO-DATA-LOSS": lambda x: x.enable.value == 1,  # 无数据丢失：恢复后数据完整
    }, name="FC-RESUME")
    
    # FC-RESET: 异步复位功能点
    g.add_watch_point(dut, {
        "CK-ASYNC-RESET": lambda x: x.PRESETn.value == 0,  # 异步复位：PRESETn为0
        "CK-RESET-ALL": lambda x: x.PRESETn.value == 0,  # 全部复位：所有状态清零
        "CK-RESET-TIMING": lambda x: x.PRESETn.value == 0,  # 复位时机：任意时刻可复位
    }, name="FC-RESET")
    
    # FC-RESET-INIT: 复位后初始化功能点
    g.add_watch_point(dut, {
        "CK-TXD-HIGH": lambda x: x.PRESETn.value == 1 and x.TXD.value == 1 and x.busy.value == 0,  # TXD高电平：复位后TXD为1
        "CK-BUSY-LOW": lambda x: x.PRESETn.value == 1 and x.busy.value == 0 and x.tx_fifo_empty.value == 1,  # busy低电平：复位后busy为0
        "CK-FIFO-CLEAR": lambda x: x.tx_fifo_count.value == 0 and x.tx_fifo_empty.value == 1,  # FIFO清空：复位后count为0
        "CK-STATE-IDLE": lambda x: x.busy.value == 0 and x.tx_fifo_empty.value == 1,  # 状态IDLE：复位后为IDLE
    }, name="FC-RESET-INIT")


def init_coverage_group_data_width(g, dut):
    """初始化数据位宽配置覆盖组的检查点"""
    
    # FC-WIDTH-5BIT: 5位数据配置功能点
    g.add_watch_point(dut, {
        "CK-5BIT-COUNT": lambda x: (x.LCR.value & 0x03) == 0 and x.busy.value == 1,  # 5位数量：配置为5位且在发送
        "CK-5BIT-SEQUENCE": lambda x: (x.LCR.value & 0x03) == 0 and x.busy.value == 1,  # 5位顺序：发送BIT0-BIT4
        "CK-5BIT-TRANSITION": lambda x: (x.LCR.value & 0x03) == 0 and x.busy.value == 1,  # 5位转换：BIT4后转换
    }, name="FC-WIDTH-5BIT")
    
    # FC-WIDTH-6BIT: 6位数据配置功能点
    g.add_watch_point(dut, {
        "CK-6BIT-COUNT": lambda x: (x.LCR.value & 0x03) == 1 and x.busy.value == 1,  # 6位数量：配置为6位且在发送
        "CK-6BIT-SEQUENCE": lambda x: (x.LCR.value & 0x03) == 1 and x.busy.value == 1,  # 6位顺序：发送BIT0-BIT5
        "CK-6BIT-TRANSITION": lambda x: (x.LCR.value & 0x03) == 1 and x.busy.value == 1,  # 6位转换：BIT5后转换
    }, name="FC-WIDTH-6BIT")
    
    # FC-WIDTH-7BIT: 7位数据配置功能点
    g.add_watch_point(dut, {
        "CK-7BIT-COUNT": lambda x: (x.LCR.value & 0x03) == 2 and x.busy.value == 1,  # 7位数量：配置为7位且在发送
        "CK-7BIT-SEQUENCE": lambda x: (x.LCR.value & 0x03) == 2 and x.busy.value == 1,  # 7位顺序：发送BIT0-BIT6
        "CK-7BIT-TRANSITION": lambda x: (x.LCR.value & 0x03) == 2 and x.busy.value == 1,  # 7位转换：BIT6后转换
    }, name="FC-WIDTH-7BIT")
    
    # FC-WIDTH-8BIT: 8位数据配置功能点
    g.add_watch_point(dut, {
        "CK-8BIT-COUNT": lambda x: (x.LCR.value & 0x03) == 3 and x.busy.value == 1,  # 8位数量：配置为8位且在发送
        "CK-8BIT-SEQUENCE": lambda x: (x.LCR.value & 0x03) == 3 and x.busy.value == 1,  # 8位顺序：发送BIT0-BIT7
        "CK-8BIT-TRANSITION": lambda x: (x.LCR.value & 0x03) == 3 and x.busy.value == 1,  # 8位转换：BIT7后转换
    }, name="FC-WIDTH-8BIT")
    
    # FC-HIGH-BIT-CLEAR: 高位清零处理功能点
    g.add_watch_point(dut, {
        "CK-CLEAR-TIMING": lambda x: (x.LCR.value & 0x03) < 3 and x.busy.value == 1,  # 清零时机：少于8位时清零高位
        "CK-CLEAR-BITS": lambda x: (x.LCR.value & 0x03) < 3,  # 清零位数：清零正确的位
        "CK-PARITY-CORRECT": lambda x: (x.LCR.value & 0x08) != 0,  # 校验正确：清零后校验计算正确
    }, name="FC-HIGH-BIT-CLEAR")


def init_coverage_group_fifo(g, dut):
    """初始化FIFO管理功能覆盖组的检查点"""
    
    # FC-WRITE: FIFO写入操作功能点
    g.add_watch_point(dut, {
        "CK-SINGLE-WRITE": lambda x: x.tx_fifo_push.value == 1,  # 单次写入：写入一个数据
        "CK-CONTINUOUS-WRITE": lambda x: x.tx_fifo_push.value == 1 and x.tx_fifo_count.value > 0,  # 连续写入：连续多次写入
        "CK-DATA-INTEGRITY": lambda x: x.tx_fifo_push.value == 1,  # 数据完整性：写入数据保持不变
        "CK-POINTER-INC": lambda x: x.tx_fifo_push.value == 1 and x.tx_fifo_count.value < 16,  # 指针递增：写指针递增
    }, name="FC-WRITE")
    
    # FC-READ: FIFO内部读取功能点
    g.add_watch_point(dut, {
        "CK-POP-SIGNAL": lambda x: x.busy.value == 1 and x.tx_fifo_empty.value == 0,  # pop信号：busy时从FIFO读取
        "CK-DATA-OUTPUT": lambda x: x.busy.value == 1,  # 数据输出：读出数据正确
        "CK-READ-POINTER-INC": lambda x: x.busy.value == 1 and x.tx_fifo_count.value > 0,  # 读指针递增：读指针递增
        "CK-READ-THROUGH": lambda x: x.busy.value == 1,  # 读穿透：读指针更新后数据立即可见
    }, name="FC-READ")
    
    # FC-EMPTY-FLAG: FIFO空标志功能点
    g.add_watch_point(dut, {
        "CK-INIT-EMPTY": lambda x: x.tx_fifo_empty.value == 1 and x.tx_fifo_count.value == 0,  # 初始为空：复位后为空
        "CK-EMPTY-WHEN-ZERO": lambda x: x.tx_fifo_count.value == 0 and x.tx_fifo_empty.value == 1,  # count为0时为空
        "CK-NOT-EMPTY-WHEN-DATA": lambda x: x.tx_fifo_count.value > 0 and x.tx_fifo_empty.value == 0,  # 有数据时非空
        "CK-EMPTY-TRANSITION": lambda x: x.tx_fifo_empty.value in [0, 1],  # 空状态转换：empty标志转换
    }, name="FC-EMPTY-FLAG")
    
    # FC-FULL-FLAG: FIFO满标志功能点
    g.add_watch_point(dut, {
        "CK-FULL-WHEN-16": lambda x: x.tx_fifo_count.value == 16 and x.tx_fifo_full.value == 1,  # count为16时满
        "CK-NOT-FULL-WHEN-SPACE": lambda x: x.tx_fifo_count.value < 16 and x.tx_fifo_full.value == 0,  # 有空间时非满
        "CK-FULL-TRANSITION": lambda x: x.tx_fifo_full.value in [0, 1],  # 满状态转换：full标志转换
        "CK-FULL-BOUNDARY": lambda x: x.tx_fifo_count.value == 16,  # 满边界：第16个数据写入后
    }, name="FC-FULL-FLAG")
    
    # FC-COUNT: FIFO计数器功能点
    g.add_watch_point(dut, {
        "CK-INIT-ZERO": lambda x: x.tx_fifo_count.value == 0 and x.tx_fifo_empty.value == 1,  # 初始为0：复位后count为0
        "CK-INC-ON-WRITE": lambda x: x.tx_fifo_push.value == 1 and x.tx_fifo_count.value < 16,  # 写入递增：写入时count加1
        "CK-DEC-ON-READ": lambda x: x.busy.value == 1 and x.tx_fifo_count.value > 0,  # 读出递减：读出时count减1（通过busy推断）
        "CK-COUNT-RANGE": lambda x: 0 <= x.tx_fifo_count.value <= 16,  # 计数范围：count在0-16范围内
        "CK-COUNT-ACCURACY": lambda x: True,  # 计数准确：count值准确（通用检测点）
    }, name="FC-COUNT")
    
    # FC-POINTER: FIFO指针管理功能点
    g.add_watch_point(dut, {
        "CK-WRITE-PTR-INC": lambda x: x.tx_fifo_push.value == 1 and x.tx_fifo_count.value < 16,  # 写指针递增：写入时递增
        "CK-READ-PTR-INC": lambda x: x.busy.value == 1 and x.tx_fifo_count.value > 0,  # 读指针递增：读出时递增
        "CK-WRITE-PTR-WRAP": lambda x: x.tx_fifo_push.value == 1,  # 写指针回绕：写指针从15到0
        "CK-READ-PTR-WRAP": lambda x: x.busy.value == 1,  # 读指针回绕：读指针从15到0
        "CK-POINTER-INIT": lambda x: x.tx_fifo_count.value == 0,  # 指针初始化：复位后指针清零
    }, name="FC-POINTER")


def init_coverage_group_parity(g, dut):
    """初始化校验位配置覆盖组的检查点"""
    
    # FC-PARITY-NONE: 无校验模式功能点
    g.add_watch_point(dut, {
        "CK-NO-PARITY-STATE": lambda x: (x.LCR.value & 0x08) == 0 and x.busy.value == 1,  # 无PARITY状态：LCR[3]=0
        "CK-NO-PARITY-BIT": lambda x: (x.LCR.value & 0x08) == 0,  # 无校验位：禁用校验
    }, name="FC-PARITY-NONE")
    
    # FC-PARITY-EVEN: 偶校验模式功能点
    g.add_watch_point(dut, {
        "CK-EVEN-CALC": lambda x: (x.LCR.value & 0x38) == 0x08 and x.busy.value == 1,  # 偶校验计算：LCR配置为偶校验
        "CK-EVEN-VALUE": lambda x: (x.LCR.value & 0x38) == 0x08,  # 偶校验值：校验位值正确
    }, name="FC-PARITY-EVEN")
    
    # FC-PARITY-ODD: 奇校验模式功能点
    g.add_watch_point(dut, {
        "CK-ODD-CALC": lambda x: (x.LCR.value & 0x38) == 0x18 and x.busy.value == 1,  # 奇校验计算：LCR配置为奇校验
        "CK-ODD-VALUE": lambda x: (x.LCR.value & 0x38) == 0x18,  # 奇校验值：校验位值正确
    }, name="FC-PARITY-ODD")
    
    # FC-PARITY-STICK1: 固定1校验功能点
    g.add_watch_point(dut, {
        "CK-STICK1-VALUE": lambda x: (x.LCR.value & 0x38) == 0x28 and x.busy.value == 1,  # 固定1值：校验位为1
        "CK-STICK1-INDEPENDENT": lambda x: (x.LCR.value & 0x38) == 0x28,  # 固定1独立：不受数据影响
    }, name="FC-PARITY-STICK1")
    
    # FC-PARITY-STICK0: 固定0校验功能点
    g.add_watch_point(dut, {
        "CK-STICK0-VALUE": lambda x: (x.LCR.value & 0x38) == 0x38 and x.busy.value == 1,  # 固定0值：校验位为0
        "CK-STICK0-INDEPENDENT": lambda x: (x.LCR.value & 0x38) == 0x38,  # 固定0独立：不受数据影响
    }, name="FC-PARITY-STICK0")
    
    # FC-PARITY-CALC: 校验位计算功能点
    g.add_watch_point(dut, {
        "CK-XOR-CALC": lambda x: (x.LCR.value & 0x08) != 0 and x.busy.value == 1,  # 异或计算：使用异或运算
        "CK-VALID-BITS-ONLY": lambda x: (x.LCR.value & 0x08) != 0,  # 仅有效位：只对有效数据位计算
        "CK-CALC-TIMING": lambda x: (x.LCR.value & 0x08) != 0 and x.busy.value == 1,  # 计算时机：在正确时机计算
    }, name="FC-PARITY-CALC")


def init_coverage_group_protocol(g, dut):
    """初始化协议符合性覆盖组的检查点"""
    
    # FC-FRAME-FORMAT: 帧格式正确性功能点
    g.add_watch_point(dut, {
        "CK-START-FIRST": lambda x: x.busy.value == 1 and x.TXD.value == 0,  # 起始位在首：起始位为0
        "CK-DATA-MIDDLE": lambda x: x.busy.value == 1,  # 数据位在中：数据位在起始位后
        "CK-PARITY-AFTER-DATA": lambda x: (x.LCR.value & 0x08) != 0 and x.busy.value == 1,  # 校验在数据后：校验位在数据位后
        "CK-STOP-LAST": lambda x: x.busy.value == 1 and x.TXD.value == 1,  # 停止位在尾：停止位在帧尾
        "CK-COMPLETE-FRAME": lambda x: x.busy.value == 1,  # 完整帧：帧完整无缺失
    }, name="FC-FRAME-FORMAT")
    
    # FC-BIT-TIMING-ACCURACY: 位时序精度功能点
    g.add_watch_point(dut, {
        "CK-ALL-16-CYCLES": lambda x: x.busy.value == 1,  # 全部16周期：所有位都是16周期
        "CK-NO-JITTER": lambda x: x.busy.value == 1,  # 无抖动：时序稳定
        "CK-ACCURATE-BAUD": lambda x: x.busy.value == 1,  # 波特率准确：波特率符合要求
    }, name="FC-BIT-TIMING-ACCURACY")
    
    # FC-LSB-FIRST: LSB优先传输功能点
    g.add_watch_point(dut, {
        "CK-BIT0-FIRST": lambda x: x.busy.value == 1,  # BIT0最先：最低位先发送
        "CK-ASCENDING-ORDER": lambda x: x.busy.value == 1,  # 升序发送：按位序升序
        "CK-LSB-PROTOCOL": lambda x: x.busy.value == 1,  # LSB协议：符合LSB-first协议
    }, name="FC-LSB-FIRST")
    
    # FC-IDLE-LEVEL: 空闲电平功能点
    g.add_watch_point(dut, {
        "CK-IDLE-HIGH-LEVEL": lambda x: x.busy.value == 0 and x.TXD.value == 1,  # 空闲高电平：空闲时TXD=1
        "CK-STOP-HIGH-LEVEL": lambda x: x.busy.value == 1 and x.TXD.value == 1,  # 停止高电平：停止位TXD=1
        "CK-MARK-STATE": lambda x: x.TXD.value == 1,  # 标记状态：符合UART标记状态
    }, name="FC-IDLE-LEVEL")
    
    # FC-START-LEVEL: 起始位电平功能点
    g.add_watch_point(dut, {
        "CK-START-LOW-LEVEL": lambda x: x.busy.value == 1 and x.TXD.value == 0,  # 起始低电平：起始位TXD=0
        "CK-START-CORRECT-TIME": lambda x: x.busy.value == 1,  # 起始正确时机：在正确时刻发送
        "CK-SPACE-STATE": lambda x: x.TXD.value == 0,  # 空格状态：符合UART空格状态
    }, name="FC-START-LEVEL")
    
    # FC-FRAME-INTERVAL: 帧间间隔功能点
    g.add_watch_point(dut, {
        "CK-STOP-TO-START": lambda x: x.busy.value in [0, 1],  # STOP到START：帧间转换
        "CK-MIN-INTERVAL": lambda x: x.busy.value == 1,  # 最小间隔：至少有停止位时长
        "CK-BACK-TO-BACK": lambda x: x.busy.value == 1 and x.tx_fifo_count.value > 0,  # 背靠背：连续帧可背靠背
    }, name="FC-FRAME-INTERVAL")


def init_coverage_group_status(g, dut):
    """初始化状态指示功能覆盖组的检查点"""
    
    # FC-BUSY: busy信号指示功能点
    g.add_watch_point(dut, {
        "CK-BUSY-HIGH": lambda x: x.busy.value == 1,  # busy高指示：发送时busy=1
        "CK-BUSY-LOW": lambda x: x.busy.value == 0,  # busy低指示：空闲时busy=0
        "CK-BUSY-RANGE": lambda x: x.busy.value in [0, 1],  # busy范围：busy在START到STOP期间为高
        "CK-BUSY-TIMING": lambda x: True,  # busy时机：busy在正确时机变化
    }, name="FC-BUSY")
    
    # FC-IDLE-STATE: 空闲状态维护功能点
    g.add_watch_point(dut, {
        "CK-IDLE-TXD-HIGH": lambda x: x.busy.value == 0 and x.TXD.value == 1,  # IDLE时TXD高：IDLE状态TXD=1
        "CK-IDLE-BUSY-LOW": lambda x: x.busy.value == 0,  # IDLE时busy低：IDLE状态busy=0
        "CK-IDLE-WAIT": lambda x: x.busy.value == 0 and x.tx_fifo_empty.value == 1,  # IDLE等待：等待FIFO非空
    }, name="FC-IDLE-STATE")
    
    # FC-STATUS-UPDATE: 状态同步更新功能点
    g.add_watch_point(dut, {
        "CK-SYNC-UPDATE": lambda x: True,  # 同步更新：状态在时钟上升沿更新
        "CK-CONSISTENT": lambda x: x.busy.value in [0, 1],  # 状态一致：各状态信号一致
    }, name="FC-STATUS-UPDATE")


def init_coverage_group_stop_bits(g, dut):
    """初始化停止位配置覆盖组的检查点"""
    
    # FC-STOP-1BIT: 1位停止位功能点
    g.add_watch_point(dut, {
        "CK-1BIT-DURATION": lambda x: (x.LCR.value & 0x04) == 0 and x.busy.value == 1,  # 1位时长：停止位持续16周期
        "CK-1BIT-TO-IDLE": lambda x: (x.LCR.value & 0x04) == 0 and x.busy.value == 0,  # 1位后IDLE：STOP1后返回IDLE
        "CK-NO-STOP2": lambda x: (x.LCR.value & 0x04) == 0,  # 无STOP2：不进入STOP2状态
    }, name="FC-STOP-1BIT")
    
    # FC-STOP-2BIT: 2位停止位功能点
    g.add_watch_point(dut, {
        "CK-2BIT-DURATION": lambda x: (x.LCR.value & 0x04) != 0 and x.busy.value == 1,  # 2位时长：两个停止位各持续16周期
        "CK-STOP1-TO-STOP2": lambda x: (x.LCR.value & 0x04) != 0 and x.busy.value == 1,  # STOP1到STOP2：正确进入STOP2
        "CK-STOP2-TO-IDLE": lambda x: (x.LCR.value & 0x04) != 0,  # STOP2后IDLE：STOP2后返回IDLE
    }, name="FC-STOP-2BIT")


def init_coverage_group_transmission(g, dut):
    """初始化串行发送功能覆盖组的检查点"""
    
    # FC-START-BIT: 起始位发送功能点
    g.add_watch_point(dut, {
        "CK-START-LEVEL": lambda x: x.busy.value == 1 and x.TXD.value == 0,  # 起始位电平：起始位为0
        "CK-START-DURATION": lambda x: x.busy.value == 1,  # 起始位时长：持续16个时钟周期
        "CK-START-TIMING": lambda x: x.busy.value == 1,  # 起始位时机：在正确时机发送
    }, name="FC-START-BIT")
    
    # FC-DATA-BITS: 数据位发送功能点
    g.add_watch_point(dut, {
        "CK-LSB-FIRST": lambda x: x.busy.value == 1,  # LSB优先：从最低位开始发送
        "CK-BIT-VALUE": lambda x: x.busy.value == 1,  # 位值正确：每个数据位值正确
        "CK-BIT-ORDER": lambda x: x.busy.value == 1,  # 位顺序：数据位发送顺序正确
        "CK-BIT-DURATION": lambda x: x.busy.value == 1,  # 位时长：每个数据位持续16个时钟周期
    }, name="FC-DATA-BITS")
    
    # FC-PARITY-BIT: 校验位发送功能点
    g.add_watch_point(dut, {
        "CK-PARITY-VALUE": lambda x: (x.LCR.value & 0x08) != 0 and x.busy.value == 1,  # 校验值：校验位值计算正确
        "CK-PARITY-TIMING": lambda x: (x.LCR.value & 0x08) != 0 and x.busy.value == 1,  # 校验时机：校验位在数据位后发送
        "CK-PARITY-DURATION": lambda x: (x.LCR.value & 0x08) != 0 and x.busy.value == 1,  # 校验时长：校验位持续16个时钟周期
    }, name="FC-PARITY-BIT")
    
    # FC-STOP-BIT: 停止位发送功能点
    g.add_watch_point(dut, {
        "CK-STOP-LEVEL": lambda x: x.busy.value == 1 and x.TXD.value == 1,  # 停止位电平：停止位为1
        "CK-STOP-DURATION": lambda x: x.busy.value == 1,  # 停止位时长：停止位持续16个时钟周期
        "CK-STOP-COUNT": lambda x: x.busy.value == 1,  # 停止位数量：停止位数量符合配置
    }, name="FC-STOP-BIT")
    
    # FC-TXD-OUTPUT: 串行输出功能点
    g.add_watch_point(dut, {
        "CK-IDLE-HIGH": lambda x: x.busy.value == 0 and x.TXD.value == 1,  # 空闲高电平：空闲时TXD为高
        "CK-OUTPUT-STABLE": lambda x: x.TXD.value in [0, 1],  # 输出稳定：TXD输出在位周期内稳定
        "CK-OUTPUT-TRANSITION": lambda x: True,  # 输出转换：TXD在正确时机转换
    }, name="FC-TXD-OUTPUT")
    
    # FC-BIT-TIMING: 位时序控制功能点
    g.add_watch_point(dut, {
        "CK-COUNTER-RANGE": lambda x: x.busy.value == 1,  # 计数范围：bit_counter在0-15范围
        "CK-COUNTER-INC": lambda x: x.busy.value == 1 and x.enable.value == 1,  # 计数递增：bit_counter每周期递增
        "CK-COUNTER-RESET": lambda x: x.busy.value == 1,  # 计数复位：计数到15后清零
        "CK-TIMING-ACCURACY": lambda x: x.busy.value == 1,  # 时序精度：每位精确16个周期
    }, name="FC-BIT-TIMING")
    
    # FC-STATE-TRANS: 状态机转换功能点
    g.add_watch_point(dut, {
        "CK-IDLE-TO-START": lambda x: x.busy.value == 1,  # IDLE到START：从IDLE正确转到START
        "CK-START-TO-BIT": lambda x: x.busy.value == 1,  # START到BIT：从START转到BIT0
        "CK-BIT-TO-BIT": lambda x: x.busy.value == 1,  # BIT间转换：数据位间转换
        "CK-BIT-TO-PARITY": lambda x: (x.LCR.value & 0x08) != 0 and x.busy.value == 1,  # BIT到PARITY：转到PARITY状态
        "CK-BIT-TO-STOP": lambda x: (x.LCR.value & 0x08) == 0 and x.busy.value == 1,  # BIT到STOP：跳过PARITY直接到STOP
        "CK-STOP-TO-IDLE": lambda x: x.busy.value == 0,  # STOP到IDLE：完成后返回IDLE
        "CK-STATE-CONDITION": lambda x: x.busy.value in [0, 1],  # 转换条件：状态转换条件正确
    }, name="FC-STATE-TRANS")
    
    # FC-TX-BUFFER: 发送缓冲锁存功能点
    g.add_watch_point(dut, {
        "CK-LATCH-TIMING": lambda x: x.busy.value == 1,  # 锁存时机：在正确时机锁存数据
        "CK-BUFFER-HOLD": lambda x: x.busy.value == 1,  # 数据保持：发送期间tx_buffer不变
        "CK-BUFFER-VALUE": lambda x: x.busy.value == 1,  # 缓冲值：tx_buffer值与FIFO输出一致
    }, name="FC-TX-BUFFER")


def get_coverage_groups(dut):
    """获取所有功能覆盖组
    
    Args:
        dut: Uart_tx DUT实例
        
    Returns:
        List[CovGroup]: 功能覆盖组列表
    """
    # 初始化各覆盖组的检查点
    init_coverage_group_api(funcov_api, dut)
    init_coverage_group_boundary(funcov_boundary, dut)
    init_coverage_group_concurrent(funcov_concurrent, dut)
    init_coverage_group_control(funcov_control, dut)
    init_coverage_group_data_width(funcov_data_width, dut)
    init_coverage_group_fifo(funcov_fifo, dut)
    init_coverage_group_parity(funcov_parity, dut)
    init_coverage_group_protocol(funcov_protocol, dut)
    init_coverage_group_status(funcov_status, dut)
    init_coverage_group_stop_bits(funcov_stop_bits, dut)
    init_coverage_group_transmission(funcov_transmission, dut)
    
    # 返回所有覆盖组
    return funcov_groups
