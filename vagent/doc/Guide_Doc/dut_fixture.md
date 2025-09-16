
# DUT Fixture 指南

本文档介绍如何为DUT（Design Under Test）创建必要pytest fixture，确保测试的稳定性和可维护性。

## DUT Fixture 创建

### 概述

根据验证需要，unitytest 定义了2类Fixture：

- dut：必须实现（有且仅有一个），用于获得待验证模块的实例。
- env：根据需要可选实现，用户获得验证环境（可以有多个， 名称以env开头）。

#### dut Fixture
在所有测试函数中，都需要通过参数 `dut` 获取DUT的实例，因此需要提供对应的pytest fixture。DUT fixture负责：

1. **实例化DUT**：创建和初始化被测设计
2. **功能覆盖设置**：配置覆盖率组和采样机制
3. **时钟管理**：为时序电路初始化时钟
4. **测试清理**：测试结束后的资源清理和数据收集

在实现fixture dut之前，需要先实现 `create_dut` 函数，他的作用是创建DUT。其基本结构如下：

```python
import os

def current_path_file(file_name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), file_name)

def create_dut():
    """创建DUT实例的工厂函数
    
    Returns:
        DUT实例，已完成基本初始化
    """
    # 导入并实例化具体的DUT类
    from {dut_module} import DUT{DutClass}
    
    dut = DUT{DutClass}()

    # 设置覆盖率生成文件(必须设置覆盖率文件，否则无法统计覆盖率，导致测试失败)
    dut.SetCoverage(current_path_file("{dut_module}.dat"))

    # 设置覆波形生成文件（根据需要设置，可选）
    # dut.SetWaveform(current_path_file("{dut_module}.fst"))

    # 进行必要的初始化设置
    # 例如：设置默认值、复位等
    dut.reset.value = 1  # 示例：设置复位信号
    
    return dut
```

dut Fixture 参考如下：

```python
import pytest
from toffee_test.reporter import set_func_coverage, set_line_coverage
from {dut_name}_function_coverage_def import get_coverage_groups

@pytest.fixture()
def dut(request):
    # 1. 创建DUT实例
    dut = create_dut()
    
    # 2. 获取功能覆盖组
    func_coverage_group = get_coverage_groups(dut)
    
    # 3. 初始化时钟（仅时序电路需要）
    # 确保DUT有对应的时钟引脚，常见名称：clock, clk, clk_i等
    # 组合电路不需要InitClock
    if hasattr(dut, 'clock'):
        dut.InitClock("clock")
    elif hasattr(dut, 'clk'):
        dut.InitClock("clk")
    
    # 4. 设置覆盖率采样回调（在StepRis中调用sample采样，必须用dut.Step方法推进电路）
    dut.StepRis(lambda _: [g.sample() for g in func_coverage_group])
    
    # 5. 将覆盖组绑定到DUT实例
    setattr(dut, "fc_cover", {g.name: g for g in func_coverage_group})
    
    # 6. 返回DUT实例给测试函数
    yield dut
    
    # 7. 测试后处理（清理阶段）
    set_func_coverage(request, func_coverage_group)  # 向toffee_test传递功能覆盖率数据

    # 8. 设置需要收集的代码行覆盖率文件
    set_line_coverage(request, current_path_file("{{DUT}}.dat"),
                      ignore=current_path_file("{{DUT}}.ignore"))  # 向toffee_test传代码行递覆盖率数据

    for g in func_coverage_group:
        g.clear()  # 清空覆盖率统计
    dut.Finish()   # 清理DUT资源

```

#### env Fixture

在DUT接口或者逻辑比较复杂时，或者需要依赖其他组件时，仅仅对DUT的接口进行操作可能无法满足验证需求，为此需要在DUT之上提供更高层次的抽象来简化测试用例（例如封装依赖组件、封装复杂逻辑、封装Reference Model等），该环境我们称为测试环境（Test Environment）。例如 Cache + Memory 构造的验证环境。env Fixture依赖 dut Fixture，具体参考如下：

##### 基本用法

```python
class MyTestEnv:
    def __init__(self, dut):
        self.dut = dut
        # 初始化测试环境相关组件
        self._setup_environment()
    
    def _setup_environment(self):
        """初始化测试环境"""
        # 配置默认状态
        self.reset_system()
        # 初始化内部状态
        self._transaction_count = 0
    
    def reset_system(self):
        """系统复位"""
        self.dut.reset.value = 1
        self.dut.Step()
        self.dut.reset.value = 0
        self.dut.Step()
    
    def wait_cycles(self, cycles):
        """等待指定周期数"""
        for _ in range(cycles):
            self.dut.Step()

@pytest.fixture()
def env(dut):
    return MyTestEnv(dut)

@pytest.fixture()
def env_simple(dut):
    return MyTestEnv(dut)

```

**注意：** 和dut Fixture不同，env Fixture可以有多个（eg： env, env_1, env_fast, ...），他们的名字必须以env开头。

##### 高级用法示例

**1. 带Reference Model的环境**

```python
class CPUTestEnv:
    def __init__(self, dut):
        self.dut = dut
        self.ref_model = CPUReferenceModel()  # 参考模型
        self.memory = MemoryModel()           # 内存模型
        self.instruction_queue = []           # 指令队列
        
    def execute_instruction(self, instruction):
        """执行指令并与参考模型对比"""
        # DUT执行
        dut_result = self._execute_on_dut(instruction)
        
        # 参考模型执行
        ref_result = self.ref_model.execute(instruction)
        
        # 结果比较
        assert dut_result == ref_result, f"结果不匹配: DUT={dut_result}, REF={ref_result}"
        
        return dut_result
    
    def load_program(self, program):
        """加载程序到内存"""
        for addr, instr in enumerate(program):
            self.memory.write(addr, instr)

@pytest.fixture()
def env_cpu(dut):
    return CPUTestEnv(dut)
```

**2. 协议封装环境**

```python
class AXITestEnv:
    def __init__(self, dut):
        self.dut = dut
        self.axi_master = AXIMaster(dut)      # AXI主控接口封装
        self.axi_slave = AXISlave(dut)        # AXI从设备接口封装
        self.outstanding_transactions = {}     # 未完成事务跟踪
        
    async def write_burst(self, addr, data, burst_len=1):
        """AXI突发写事务"""
        transaction_id = self._get_next_id()
        
        # 地址通道
        await self.axi_master.send_write_addr(addr, burst_len, transaction_id)
        
        # 数据通道
        for i, data_beat in enumerate(data):
            last = (i == len(data) - 1)
            await self.axi_master.send_write_data(data_beat, last)
        
        # 等待响应
        response = await self.axi_master.wait_write_response(transaction_id)
        return response
    
    async def read_burst(self, addr, burst_len=1):
        """AXI突发读事务"""
        transaction_id = self._get_next_id()
        
        # 发送读地址
        await self.axi_master.send_read_addr(addr, burst_len, transaction_id)
        
        # 接收读数据
        data = []
        for _ in range(burst_len):
            read_data = await self.axi_master.wait_read_data(transaction_id)
            data.append(read_data)
        
        return data

@pytest.fixture()
def env_aix(dut):
    return AXITestEnv(dut)
```

**3. 多组件协同环境**

```python
class SoCTestEnv:
    def __init__(self, dut):
        self.dut = dut
        self.cpu_env = CPUTestEnv(dut.cpu)
        self.cache_env = CacheTestEnv(dut.cache)  
        self.memory_env = MemoryTestEnv(dut.memory)
        self.interrupt_controller = InterruptController(dut.pic)
        
    def boot_system(self):
        """系统启动序列"""
        # 1. 复位所有组件
        self.reset_all_components()
        
        # 2. 初始化内存
        self.memory_env.load_bootloader()
        
        # 3. 配置中断控制器
        self.interrupt_controller.configure()
        
        # 4. 启动CPU
        self.cpu_env.start_execution()
        
    def run_benchmark(self, benchmark_name):
        """运行基准测试"""
        program = self.load_benchmark(benchmark_name)
        self.memory_env.load_program(program)
        
        start_cycles = self.dut.cycle_count.value
        result = self.cpu_env.run_until_halt()
        end_cycles = self.dut.cycle_count.value
        
        return {
            'result': result,
            'cycles': end_cycles - start_cycles,
            'cache_stats': self.cache_env.get_statistics()
        }

@pytest.fixture()
def env_soc(dut):
    return SoCTestEnv(dut)
```

**注意事项：**
- env Fixture不是必要的，请根据DUT的复杂度来定
- env Fixture必须返回一个Class实例，且必须有dut属性
- 环境类应该封装复杂的DUT操作，提供高层次的API
- 建议在环境类中实现自检和调试功能
- 环境类应该负责自己的资源管理和清理
- 考虑使用async/await支持异步操作（如果需要）


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
```

**重点：**
- 没有特殊需求时，请用dut.Step方法推进组合电路，通过dut.StepRis设置“功能覆盖组”在上升沿回调中自动采样
- 仅有特殊需求时，才建议用RefreshComb推进电路
  - 例如：dut既有组合电路逻辑又有时序电路逻辑，则可用 RefreshComb + Step的混合方式推进电路
- 使用RefreshComb时，需要在API或者测试用例中手动调用CovGroup中的sample进行采样

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

