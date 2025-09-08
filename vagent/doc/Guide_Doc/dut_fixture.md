
# DUT Fixture 指南

本文档介绍如何为DUT（Design Under Test）创建必要pytest fixture，确保测试的稳定性和可维护性。

## DUT Fixture 创建

### 概述

在所有测试函数中，都需要通过参数 `dut` 获取DUT的实例，因此需要提供对应的pytest fixture。DUT fixture负责：

1. **实例化DUT**：创建和初始化被测设计
2. **功能覆盖设置**：配置覆盖率组和采样机制
3. **时钟管理**：为时序电路初始化时钟
4. **测试清理**：测试结束后的资源清理和数据收集

在实现fixture dut之前，需要先实现 `create_dut` 函数，他的作用是创建DUT。其基本结构如下：

```python
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

**重点：**
- 没有特殊需求时，请用dut.Step方法推进组合电路，通过dut.StepRis设置“功能覆盖组”在上升沿回调中自动采样
- 有特殊需求时，使用RefreshComb推进组合电路，需要在API或者测试用例中手动调用CovGroup中的sample进行采样

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

