
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

#### 详尽的注释

在每个API函数中都需要通过函数 DOC 编写对应的注释，遵循Google风格的docstring规范。注释应该详细、准确、可维护。

##### 注释格式要求

```python
def api_demo_op(dut, a: int, b: int, mode: str = "add") -> Tuple[int, bool]:
    """对API的功能进行详细描述，说明其作用、适用场景和注意事项

    详细描述API的工作原理、时序要求、边界条件等重要信息。
    如果有特殊的使用注意事项或限制条件，也要在这里说明。

    Args:
        dut: DUT实例，必须是已初始化的{DUT_NAME}对象
        a (int): 第一个操作数，取值范围[0, 2^32-1]，表示输入A的数值
        b (int): 第二个操作数，取值范围[0, 2^32-1]，表示输入B的数值
        mode (str, optional): 操作模式，可选值为"add"/"sub"/"mul"，默认为"add"

    Returns:
        Tuple[int, bool]: 包含两个元素的元组
            - result (int): 运算结果，范围取决于操作模式
            - overflow (bool): 溢出标志，True表示发生溢出

    Raises:
        ValueError: 当参数超出有效范围时抛出
        RuntimeError: 当DUT硬件故障时抛出
        TimeoutError: 当操作超时时抛出（适用于时序电路）

    Example:
        >>> result, overflow = api_demo_op(dut, 100, 200, "add")
        >>> print(f"结果: {result}, 溢出: {overflow}")
        结果: 300, 溢出: False

    Note:
        - 该API适用于同步时序电路，会自动处理时钟推进
        - 对于组合电路，结果立即有效
        - 连续调用时建议间隔至少1个时钟周期
    """
    # 参数验证
    if not (0 <= a <= 0xFFFFFFFF):
        raise ValueError(f"参数a超出范围: {a}")
    if not (0 <= b <= 0xFFFFFFFF):
        raise ValueError(f"参数b超出范围: {b}")
    if mode not in ["add", "sub", "mul"]:
        raise ValueError(f"无效的操作模式: {mode}")

    # 设置输入信号
    dut.input_a.value = a
    dut.input_b.value = b
    dut.operation_mode.value = {"add": 0, "sub": 1, "mul": 2}[mode]

    # 推进时钟（时序电路需要）
    dut.Step(1)

    # 读取结果
    result = dut.output_result.value
    overflow = bool(dut.overflow_flag.value)

    return result, overflow
```

##### 注释结构说明

API函数的docstring应包含以下几个部分：

1. **功能描述**：简洁明了地说明API的主要功能
2. **详细说明**：补充重要的实现细节、使用场景、注意事项
3. **Args**：详细描述每个参数的含义、类型、取值范围、默认值
4. **Returns**：描述返回值的类型、含义、可能的取值
5. **Raises**：列出可能抛出的异常及其触发条件
6. **Example**：提供使用示例，帮助理解API用法
7. **Note**：补充重要的使用注意事项

##### 参数描述最佳实践

```python
def api_memory_access(dut, address: int, data: Optional[int] = None,
                     read_enable: bool = True, timeout: float = 1.0) -> Union[int, None]:
    """访问DUT内存接口，支持读写操作

    Args:
        dut: DUT实例，必须包含memory接口信号
        address (int): 内存地址，范围[0x0000, 0xFFFF]，必须4字节对齐
        data (Optional[int]): 写入数据，None表示读操作，其他值表示写操作
                             写入时取值范围[0, 2^32-1]
        read_enable (bool): 读使能信号，True表示读操作，False表示写操作
                           当data不为None时，该参数被忽略
        timeout (float): 操作超时时间，单位秒，范围[0.1, 10.0]

    Returns:
        Union[int, None]:
            - 读操作时返回int类型的数据值
            - 写操作时返回None
    """
    pass
```

##### 类型提示的使用

```python
from typing import Union, Optional, List, Dict, Tuple, Any

def api_batch_operation(dut,
                       operations: List[Dict[str, Any]],
                       config: Optional[Dict[str, Union[int, str]]] = None) -> List[Tuple[bool, Any]]:
    """批量执行多个操作

    Args:
        dut: DUT实例
        operations (List[Dict[str, Any]]): 操作列表，每个元素为操作字典
                                          字典格式: {"type": str, "params": Dict, "id": int}
        config (Optional[Dict[str, Union[int, str]]]): 可选配置参数
                                                      键为配置名，值为配置值

    Returns:
        List[Tuple[bool, Any]]: 结果列表，每个元素为(成功标志, 结果数据)的元组
    """
    pass
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

### API 测试

完成API编写后，需要对其进行功能测试，检验其是否满足要求。API测试主要关注单个API函数的功能正确性。

#### 测试文件组织

需要创建`test_{DUT}_api_<category>.py`的测试文件进行测试，其中：
- `{DUT}`: DUT名称，如adder、alu、cache等
- `<category>`: 功能分类，如basic、advanced等

```
tests/
├── test_adder_api_basic.py      # 基础功能测试
├── test_adder_api_advanced.py   # 高级功能测试
└── test_adder_api_edge_cases.py # 边界情况测试
```

#### 测试函数命名规范

测试函数采用`test_<api_name>[_<test_scenario>]`的命名方式：

```python
# 基础功能测试
def test_api_adder_add():
    """测试加法API的基本功能"""
    pass

# 边界条件测试
def test_api_adder_add_overflow():
    """测试加法API的溢出处理"""
    pass

# 错误处理测试
def test_api_adder_add_invalid_input():
    """测试加法API的无效输入处理"""
    pass
```

#### 测试用例编写规范

每个测试用例需要包含详细的docstring，描述测试目标、流程和预期结果：

```python
import pytest
from {dut_name}_api import *

def test_api_adder_add_basic(dut):
    """测试加法器API基础功能

    测试目标:
        验证api_adder_add函数能正确执行基本加法运算

    测试流程:
        1. 使用典型正数进行加法运算
        2. 验证结果正确性
        3. 检查进位输出

    预期结果:
        - 计算结果正确
        - 进位标志符合预期
        - 无异常抛出
    """
    # 测试典型情况
    result, carry = api_adder_add(dut, 100, 200)
    assert result == 300, f"预期结果300，实际{result}"
    assert carry == 0, f"预期进位0，实际{carry}"

    # 测试带进位情况
    result, carry = api_adder_add(dut, 0xFFFFFFFF, 1)
    assert result == 0, f"溢出时预期结果0，实际{result}"
    assert carry == 1, f"溢出时预期进位1，实际{carry}"

def test_api_adder_add_edge_cases(dut):
    """测试加法器API边界情况

    测试目标:
        验证API在边界条件下的正确行为

    测试流程:
        1. 测试零值加法
        2. 测试最大值加法
        3. 测试单操作数为最大值的情况

    预期结果:
        - 边界值计算正确
        - 溢出检测准确
        - 特殊情况处理得当
    """
    # 零值测试
    result, carry = api_adder_add(dut, 0, 0)
    assert result == 0 and carry == 0

    # 最大值测试
    max_val = 0xFFFFFFFF
    result, carry = api_adder_add(dut, max_val, max_val)
    assert carry == 1, "最大值相加应产生进位"

def test_api_adder_add_error_handling(dut):
    """测试加法器API错误处理

    测试目标:
        验证API对无效输入的错误处理机制

    测试流程:
        1. 传入超出范围的参数
        2. 传入错误类型的参数
        3. 验证异常类型和错误信息

    预期结果:
        - 正确抛出预期异常
        - 错误信息描述准确
        - 不会导致程序崩溃
    """
    # 测试参数超出范围
    with pytest.raises(ValueError, match="参数.*超出范围"):
        api_adder_add(dut, -1, 100)

    with pytest.raises(ValueError, match="参数.*超出范围"):
        api_adder_add(dut, 100, 0x100000000)

    # 测试参数类型错误
    with pytest.raises(TypeError):
        api_adder_add(dut, "100", 200)
```

#### 测试数据驱动

使用pytest的参数化功能进行数据驱动测试：

```python
@pytest.mark.parametrize("a,b,expected_sum,expected_carry", [
    (0, 0, 0, 0),
    (1, 1, 2, 0),
    (100, 200, 300, 0),
    (0xFFFFFFFF, 1, 0, 1),
    (0x80000000, 0x80000000, 0, 1),
])
def test_api_adder_add_parametrized(dut, a, b, expected_sum, expected_carry):
    """参数化测试加法器API

    测试目标:
        使用多组测试数据验证API的正确性

    测试数据:
        覆盖典型值、边界值、特殊值等多种情况
    """
    result, carry = api_adder_add(dut, a, b)
    assert result == expected_sum, f"输入({a}, {b}): 预期和{expected_sum}，实际{result}"
    assert carry == expected_carry, f"输入({a}, {b}): 预期进位{expected_carry}，实际{carry}"

@pytest.mark.parametrize("invalid_input", [
    (-1, 100),      # 负数
    (100, -1),      # 负数
    (0x100000000, 0),  # 超出范围
    (0, 0x100000000),  # 超出范围
])
def test_api_adder_add_invalid_inputs(dut, invalid_input):
    """参数化测试无效输入处理"""
    a, b = invalid_input
    with pytest.raises(ValueError):
        api_adder_add(dut, a, b)
```

#### 测试要求

API测试应该覆盖以下几个方面：

1. **基础功能**：验证API的核心功能是否正确
2. **边界条件**：测试边界值和特殊值的处理
3. **错误处理**：验证异常情况的处理机制
4. **参数验证**：检查输入参数的合法性验证


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

### 4. 代码质量保证

#### 代码审查清单

在提交API代码前，请检查以下项目：

- [ ] **命名规范**：函数名遵循`api_{dut}_{function}`格式
- [ ] **类型提示**：所有参数和返回值都有正确的类型标注
- [ ] **文档完整**：docstring包含所有必需部分（功能、参数、返回值、异常）
- [ ] **参数验证**：对输入参数进行合理的范围和类型检查
- [ ] **错误处理**：适当的异常处理和有意义的错误信息
- [ ] **测试覆盖**：所有API都有对应的测试用例
- [ ] **性能考虑**：没有明显的性能瓶颈
- [ ] **依赖最小**：避免不必要的外部依赖

#### 代码风格规范

```python
# 良好的API示例
def api_cache_invalidate(dut, address_range: Tuple[int, int],
                        invalidate_type: str = "data") -> bool:
    """使指定地址范围的缓存失效

    Args:
        dut: 缓存DUT实例
        address_range: 地址范围元组(start_addr, end_addr)
        invalidate_type: 失效类型，"data"或"instruction"

    Returns:
        bool: 操作是否成功

    Raises:
        ValueError: 地址范围无效或类型不支持
    """
    start_addr, end_addr = address_range

    # 参数验证
    if start_addr < 0 or end_addr < start_addr:
        raise ValueError(f"无效的地址范围: [{start_addr:x}, {end_addr:x}]")

    if invalidate_type not in ["data", "instruction"]:
        raise ValueError(f"不支持的失效类型: {invalidate_type}")

    # 执行操作
    try:
        dut.cache_invalidate_start.value = start_addr
        dut.cache_invalidate_end.value = end_addr
        dut.cache_invalidate_type.value = 0 if invalidate_type == "data" else 1
        dut.cache_invalidate_enable.value = 1
        dut.Step(1)
        dut.cache_invalidate_enable.value = 0

        # 等待操作完成
        timeout = 100
        while dut.cache_invalidate_busy.value and timeout > 0:
            dut.Step(1)
            timeout -= 1

        if timeout == 0:
            raise TimeoutError("缓存失效操作超时")

        return not bool(dut.cache_invalidate_error.value)

    except Exception as e:
        raise RuntimeError(f"缓存失效操作失败: {e}")
```

### 5. 性能优化建议

#### 时钟管理优化

```python
def api_bulk_memory_write(dut, data_dict: Dict[int, int]) -> int:
    """批量写入内存，优化时钟推进

    Args:
        dut: DUT实例
        data_dict: 地址到数据的映射字典

    Returns:
        int: 成功写入的数据条数
    """
    success_count = 0

    # 预先排序地址，提高写入效率
    sorted_addresses = sorted(data_dict.keys())

    for addr in sorted_addresses:
        data = data_dict[addr]

        # 设置写入信号
        dut.mem_addr.value = addr
        dut.mem_data.value = data
        dut.mem_write_enable.value = 1

        # 只在必要时推进时钟
        dut.Step(1)

        # 检查写入状态
        if not dut.mem_error.value:
            success_count += 1

        # 清除写使能
        dut.mem_write_enable.value = 0

    return success_count
```

#### 缓存和状态管理

```python
class APIStateManager:
    """API状态管理器，提供缓存和状态跟踪功能"""

    def __init__(self, dut):
        self.dut = dut
        self._cache = {}
        self._state_history = []

    def cached_read(self, address: int, force_refresh: bool = False) -> int:
        """带缓存的内存读取"""
        if not force_refresh and address in self._cache:
            return self._cache[address]

        # 执行实际读取
        value = self._read_from_hardware(address)
        self._cache[address] = value
        return value

    def invalidate_cache(self, address: Optional[int] = None):
        """使缓存失效"""
        if address is None:
            self._cache.clear()
        else:
            self._cache.pop(address, None)

    def save_state(self, name: str):
        """保存当前状态"""
        state = {
            'name': name,
            'timestamp': time.time(),
            'registers': self._capture_registers(),
            'cache': self._cache.copy()
        }
        self._state_history.append(state)

    def restore_state(self, name: str) -> bool:
        """恢复到指定状态"""
        for state in reversed(self._state_history):
            if state['name'] == name:
                self._restore_registers(state['registers'])
                self._cache = state['cache'].copy()
                return True
        return False

# 使用状态管理器的API示例
def api_transaction_execute(dut, operations: List[Dict]) -> List[Any]:
    """执行事务操作，支持回滚"""
    state_mgr = APIStateManager(dut)

    # 保存初始状态
    state_mgr.save_state("transaction_start")

    try:
        results = []
        for op in operations:
            result = _execute_single_operation(dut, op)
            results.append(result)

        return results

    except Exception as e:
        # 发生错误时回滚
        state_mgr.restore_state("transaction_start")
        raise RuntimeError(f"事务执行失败，已回滚: {e}")
```

### 6. 调试和诊断工具

#### 调试辅助API

```python
def api_debug_dump_state(dut, include_memory: bool = False) -> Dict[str, Any]:
    """转储DUT当前状态，用于调试

    Args:
        dut: DUT实例
        include_memory: 是否包含内存内容

    Returns:
        Dict: 状态信息字典
    """
    state = {
        'timestamp': time.time(),
        'clock_count': getattr(dut, '_clock_count', 0),
        'registers': {},
        'flags': {},
        'signals': {}
    }

    # 收集寄存器状态
    register_names = ['pc', 'sp', 'acc', 'status']
    for reg_name in register_names:
        if hasattr(dut, reg_name):
            state['registers'][reg_name] = getattr(dut, reg_name).value

    # 收集标志位
    flag_names = ['zero', 'carry', 'overflow', 'negative']
    for flag_name in flag_names:
        if hasattr(dut, f'{flag_name}_flag'):
            state['flags'][flag_name] = bool(getattr(dut, f'{flag_name}_flag').value)

    # 收集重要信号
    signal_names = ['ready', 'busy', 'error', 'interrupt']
    for sig_name in signal_names:
        if hasattr(dut, sig_name):
            state['signals'][sig_name] = getattr(dut, sig_name).value

    # 可选：收集内存内容
    if include_memory and hasattr(dut, 'memory'):
        state['memory'] = _dump_memory_contents(dut)

    return state

def api_debug_trace_enable(dut, trace_signals: List[str] = None):
    """启用信号跟踪，用于调试时序问题"""
    if trace_signals is None:
        trace_signals = ['clock', 'reset', 'enable', 'data_valid']

    # 实现信号跟踪逻辑
    for signal in trace_signals:
        if hasattr(dut, signal):
            # 设置跟踪回调
            dut.add_trace_callback(signal, _trace_callback)

def _trace_callback(signal_name: str, old_value, new_value, timestamp):
    """信号跟踪回调函数"""
    print(f"[{timestamp:0.3f}] {signal_name}: {old_value} -> {new_value}")
```
