
# DUT Fixture 和 API 设计指南

本文档介绍如何为DUT（Design Under Test）创建pytest fixture和设计API接口，确保测试框架的稳定性和可维护性。

## DUT Fixture 创建

### 概述

在所有测试函数中，都需要通过参数 `dut` 获取DUT的实例，因此需要提供对应的pytest fixture。DUT fixture负责：

1. **实例化DUT**：创建和初始化被测设计
2. **功能覆盖设置**：配置覆盖率组和采样机制
3. **时钟管理**：为时序电路初始化时钟
4. **测试清理**：测试结束后的资源清理和数据收集

### 标准 Fixture 实现

```python
import pytest
from toffee_test.reporter import set_func_coverage
from {dut_name}_function_coverage_def import get_coverage_groups

@pytest.fixture()
def dut(request):
    # 1. 创建DUT实例
    dut = create_dut()
    
    # 2. 获取功能覆盖组
    func_coverage_group = get_coverage_groups(dut)
    
    # 3. 初始化时钟（仅时序电路需要）
    # 确保DUT有对应的时钟引脚，常见名称：clock, clk, clk_i等
    if hasattr(dut, 'clock'):
        dut.InitClock("clock")
    elif hasattr(dut, 'clk'):
        dut.InitClock("clk")
    # 组合电路不需要InitClock
    
    # 4. 设置覆盖率采样回调
    dut.StepRis(lambda _: [g.sample() for g in func_coverage_group])
    
    # 5. 将覆盖组绑定到DUT实例
    setattr(dut, "fc_cover", {g.name: g for g in func_coverage_group})
    
    # 6. 返回DUT实例给测试函数
    yield dut
    
    # 7. 测试后处理（清理阶段）
    set_func_coverage(request, func_coverage_group)  # 向toffee_test传递覆盖率数据
    for g in func_coverage_group:
        g.clear()  # 清空覆盖率统计
    dut.Finish()   # 清理DUT资源

def create_dut():
    """创建DUT实例的工厂函数
    
    Returns:
        DUT实例，已完成基本初始化
    """
    # 导入并实例化具体的DUT类
    from {dut_module} import DUT{DutClass}
    
    dut = DUT{DutClass}()
    
    # 进行必要的初始化设置
    # 例如：设置默认值、复位等
    dut.reset.value = 1  # 示例：设置复位信号
    
    return dut
```

### 时钟配置指南

不同类型的电路需要不同的时钟配置：

#### 时序电路
```python
# 单时钟系统
dut.InitClock("clk")

# 多时钟系统  
dut.InitClock("clk_core")    # 核心时钟
dut.InitClock("clk_mem")     # 内存时钟
```

#### 组合电路
```python  
# 组合电路不需要InitClock
# 直接使用Step()或RefreshComb()推进
```

#### 查找时钟引脚名称

可以通过以下方式确定时钟引脚名称：

1. **查看DUT模块定义**：检查 `{DUT}/__init__.py` 或相关模块文件
2. **查看端口列表**：使用 `dir(dut)` 查看所有属性
3. **参考设计文档**：查看RTL设计的端口定义

```python
# 动态查找时钟引脚示例
def setup_clock(dut):
    clock_names = ['clock', 'clk', 'clk_i', 'clk_in', 'sys_clk']
    for clk_name in clock_names:
        if hasattr(dut, clk_name):
            dut.InitClock(clk_name)
            print(f"时钟已初始化: {clk_name}")
            return
    print("警告：未找到时钟引脚，可能是组合电路")
```

## DUT API 设计

### 设计原则

DUT API的设计应遵循以下原则：

1. **封装性**：隐藏底层实现细节和时序
2. **稳定性**：接口变更不应影响测试用例
3. **通用性**：API应覆盖主要功能，避免过度细化
4. **一致性**：命名和参数传递保持统一风格
5. **可测试性**：便于单元测试和集成测试

### 命名规范

API函数命名格式：`api_{dut_name}_{function_name}`

- `dut_name`：DUT的名称，如adder、alu、cache等
- `function_name`：具体功能名称，使用动词描述操作

```python
# 良好的命名示例
api_adder_add(dut, a, b, cin)           # 加法器执行加法
api_cache_read(dut, address)            # 缓存读取
api_uart_send(dut, data)                # UART发送数据
api_cpu_execute(dut, instruction)       # CPU执行指令

# 避免的命名
api_test_func(dut)                      # 命名不明确
api_adder_do_something(dut)             # 功能描述模糊
```

### API 实现模式

#### 1. 基础操作API

```python
def api_adder_add(dut, a, b, cin=0):
    """执行加法操作
    
    Args:
        dut: DUT实例
        a: 操作数A 
        b: 操作数B
        cin: 进位输入，默认为0
        
    Returns:
        tuple: (sum_result, carry_out) 求和结果和进位输出
    """
    # 设置输入
    dut.a.value = a
    dut.b.value = b  
    dut.cin.value = cin
    
    # 推进计算（组合电路也可以使用Step）
    dut.Step(1)
    
    # 读取结果
    return dut.sum.value, dut.cout.value
```

#### 2. 复杂时序API

```python
def api_cache_read(dut, address, timeout_cycles=100):
    """从缓存读取数据
    
    Args:
        dut: DUT实例
        address: 读取地址
        timeout_cycles: 超时周期数
        
    Returns:
        int: 读取的数据值
        
    Raises:
        TimeoutError: 读取超时
    """
    # 发起读请求
    dut.addr.value = address
    dut.read_enable.value = 1
    dut.Step(1)
    
    # 等待响应
    cycles = 0
    while not dut.data_valid.value:
        if cycles >= timeout_cycles:
            raise TimeoutError(f"缓存读取超时，地址: 0x{address:x}")
        dut.Step(1)
        cycles += 1
    
    # 获取数据并清除请求
    data = dut.data_out.value
    dut.read_enable.value = 0
    dut.Step(1)
    
    return data
```

#### 3. 批量操作API

```python
def api_fifo_write_batch(dut, data_list, check_full=True):
    """批量写入FIFO
    
    Args:
        dut: DUT实例  
        data_list: 要写入的数据列表
        check_full: 是否检查FIFO满状态
        
    Returns:
        int: 成功写入的数据个数
    """
    written_count = 0
    
    for data in data_list:
        if check_full and dut.full.value:
            print(f"FIFO已满，停止写入，已写入{written_count}个数据")
            break
            
        dut.data_in.value = data
        dut.write_enable.value = 1
        dut.Step(1)
        dut.write_enable.value = 0
        written_count += 1
    
    return written_count
```

#### 4. 状态查询API

```python  
def api_cpu_get_status(dut):
    """获取CPU状态信息
    
    Args:
        dut: DUT实例
        
    Returns:
        dict: CPU状态字典
    """
    return {
        'pc': dut.program_counter.value,
        'running': bool(dut.cpu_running.value),
        'interrupt_pending': bool(dut.int_pending.value),
        'flags': {
            'zero': bool(dut.zero_flag.value),
            'carry': bool(dut.carry_flag.value),
            'overflow': bool(dut.overflow_flag.value),
        }
    }
```

### API 错误处理

```python
def api_memory_write(dut, address, data, verify=True):
    """写入内存数据
    
    Args:
        dut: DUT实例
        address: 写入地址  
        data: 写入数据
        verify: 是否验证写入成功
        
    Returns:
        bool: 写入是否成功
        
    Raises:
        ValueError: 地址或数据超出范围
        RuntimeError: 硬件错误
    """
    # 参数验证
    if address < 0 or address >= dut.MEM_SIZE:
        raise ValueError(f"地址超出范围: {address}")
        
    if data < 0 or data >= (1 << dut.DATA_WIDTH):
        raise ValueError(f"数据超出范围: {data}")
    
    # 执行写操作
    dut.mem_addr.value = address
    dut.mem_data_in.value = data  
    dut.mem_write_enable.value = 1
    dut.Step(1)
    dut.mem_write_enable.value = 0
    
    # 可选的写入验证
    if verify:
        dut.Step(1)  # 确保写入完成
        readback = api_memory_read(dut, address)
        if readback != data:
            raise RuntimeError(f"写入验证失败，期望: {data}, 实际: {readback}")
    
    return True
```

## 最佳实践

### 1. 模块化组织

将相关的API函数组织在一起：

```python
# {dut_name}_api.py
"""DUT API模块 - 提供高级接口函数"""

# 基础操作
def api_{dut}_reset(dut):
    """复位DUT"""
    pass

def api_{dut}_init(dut, config=None):
    """初始化DUT"""  
    pass

# 数据操作
def api_{dut}_read(dut, addr):
    """读取数据"""
    pass

def api_{dut}_write(dut, addr, data):
    """写入数据"""
    pass

# 状态查询
def api_{dut}_status(dut):
    """获取状态"""
    pass
```

### 2. 文档和类型提示

```python
from typing import Tuple, List, Optional, Dict, Any

def api_processor_execute(
    dut: Any, 
    instruction: int, 
    operands: Optional[List[int]] = None,
    timeout: int = 1000
) -> Tuple[int, Dict[str, Any]]:
    """执行处理器指令
    
    详细描述指令执行过程和返回值含义...
    
    Args:
        dut: 处理器DUT实例
        instruction: 指令编码
        operands: 操作数列表，可选
        timeout: 执行超时时间（周期数）
        
    Returns:
        Tuple包含:
        - result: 执行结果
        - status: 状态信息字典
        
    Raises:
        TimeoutError: 指令执行超时
        ValueError: 指令编码无效
    """
    pass
```

### 3. 测试友好的设计

```python
def api_dut_configure(dut, **kwargs):
    """配置DUT参数
    
    支持灵活的参数配置，便于测试不同场景
    """
    config_map = {
        'enable_cache': lambda v: setattr(dut, 'cache_enable', v),
        'cache_size': lambda v: setattr(dut, 'cache_size_config', v),
        'debug_mode': lambda v: setattr(dut, 'debug_enable', v),
    }
    
    for key, value in kwargs.items():
        if key in config_map:
            config_map[key](value)
        else:
            print(f"警告：未知配置参数 {key}")

# 使用示例
api_dut_configure(dut, enable_cache=True, debug_mode=False)
```
