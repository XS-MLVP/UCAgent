
# DUT Fixture 指南

本文档介绍如何为DUT（Design Under Test）创建必要的 pytest fixture，确保测试的稳定性和可维护性。

## DUT Fixture 创建

### 概述

根据验证需要，unity_test 定义了 2 类 Fixture：

- dut：必须实现（有且仅有一个），用于获得待验证模块的实例。
- env：针对dut的抽象封装（引脚封装，功能封装，环境封装等），至少有一个，根据需要可以有多个

### dut Fixture
DUT fixture负责：

1. **实例化DUT**：创建和初始化被测设计
2. **功能覆盖设置**：配置覆盖率组和采样机制
3. **时钟管理**：为时序电路初始化时钟
4. **测试清理**：测试结束后的资源清理和数据收集

在实现 dut Fixture 之前，需要先实现 `create_dut(request)` 函数，它的作用是创建 DUT。其基本结构如下：

```python
import os
from toffee_test.reporter import get_file_in_tmp_dir


def current_path_file(file_name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), file_name)


def get_coverage_data_path(request, new_path:bool):
    # 通过toffee_test.reporter提供的get_file_in_tmp_dir方法可以让各用例产生的文件名称不重复 (获取新路径需要new_path=True，获取已有路径new_path=False)
    return get_file_in_tmp_dir(request, current_path_file("data/"), "{{DUT}}.dat",  new_path=new_path)


def create_dut(request):
    """创建DUT实例的工厂函数
    
    Returns:
        DUT实例，已完成基本初始化
    """
    # 导入并实例化具体的DUT类
    from {DUT} import DUT{DutClass}
    
    dut = DUT{DutClass}()

    # 设置覆盖率生成文件(必须设置覆盖率文件，否则无法统计覆盖率，导致测试失败)
    dut.SetCoverage(get_coverage_data_path(request, new_path=True))

    # 设置波形生成文件（根据需要设置，可选）
    # wave_path = get_file_in_tmp_dir(request, current_path_file("data/"), "{DUT}.fst",  new_path=True)
    # dut.SetWaveform(wave_path)

    # 进行必要的初始化设置
    # 例如：设置默认值、复位等
    dut.reset.value = 1  # 示例：设置复位信号
    
    return dut
```

dut Fixture 参考如下：

```python
import pytest
from toffee_test.reporter import set_func_coverage, set_line_coverage, get_file_in_tmp_dir
from {DUT}_function_coverage_def import get_coverage_groups


@pytest.fixture(scope="module")
def dut(request):
    # 1. 创建DUT实例
    dut = create_dut(request)
    
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

    # 8. 设置需要收集的代码行覆盖率文件(获取已有路径new_path=False) 向toffee_test传代码行递覆盖率数据
    # 代码行覆盖率 ignore 文件的固定路径为当前文件所在目录下的：{{DUT}}.ignore，请不要改变
    set_line_coverage(request, get_coverage_data_path(request, new_path=False), ignore=current_path_file("{{DUT}}.ignore"))

    for g in func_coverage_group:
        g.clear()  # 清空覆盖率统计
    dut.Finish()   # 清理DUT资源

```

#### 时钟配置指南

不同类型的电路需要不同的时钟配置：

##### 时序电路
```python
# 单时钟系统
dut.InitClock("clk")

# 多时钟系统  
dut.InitClock("clk_core")    # 核心时钟
dut.InitClock("clk_mem")     # 内存时钟
```

##### 组合电路
```python  
# 组合电路不需要InitClock
```

**重点：**
- 常规情况下，无论是组合电路还是时序电路，都统一使用 `dut.Step(...)` 推进电路；通过 `dut.StepRis(...)` 在上升沿回调中自动采样功能覆盖
- 混合电路（同时包含时序电路与组合电路）的推进逻辑：`dut.RefreshComb() + dut.Step(1) + dut.RefreshComb()`

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

### env Fixture

在DUT接口或者逻辑比较复杂时，或者需要依赖其他组件时，仅仅对DUT的接口进行操作可能无法满足验证需求，为此需要在DUT之上提供更高层次的抽象来简化测试用例（例如封装引脚、封装依赖组件、封装复杂逻辑、封装Reference Model等），该环境我们称为测试环境（Test Environment）。例如 Cache + Memory 构造的验证环境。env Fixture依赖 dut Fixture。

在所有Env能提供的功能中，引脚封装为最基本的功能。基本模板如下：

```python
...
from toffee import Bundle, Signals
...

# 根据需要定义子Bundle
# class MyPort(Bundle):
#     signal1, signal2 = Signals(2)
#     # 根据需要定义Port对应的操作
#     def some_operation(self):
#         ...

# 定义{{DUT}}Env类，封装DUT的引脚和常用操作
class {{DUT}}Env:
    '''请在这里对Env的功能进行描述'''

    def __init__(self, dut):
        self.dut = dut
        # 请在这里根据DUT的引脚定义，提供toffee.Bundle进行引脚封装
        #  1.如果引脚有多组，且有不同前缀，请用from_prefix方法
        # self.some_input1 = MyPort.from_prefix("some_input_")
        # self.some_input1.bind(dut)
        #  2.如果引脚无法分组，请用from_dict方法进行映射
        # self.some_input2 = MyPort.from_dict({...})
        # self.some_input2.bind(dut)

    # 根据需要定义Env的常用操作
    # def reset(self):
    #    # 根据DUT的复位方式，完成复位操作
    #    ...

    # 直接导出DUT的通用操作Step
    def Step(self, i:int = 1):
        return self.dut.Step(i)


# 定义env fixture, 请取消下面的注释，并根据需要修改名称
@pytest.fixture()
def env(dut):
     # 一般情况下为每个test都创建全新的 env 不需要 yield
     return {{DUT}}Env(dut)
```

#### Toffee中的Bundle介绍

Bundle是对DUT引脚的抽象

##### 一个简单的 Bundle 的定义

为了定义一个 `Bundle`，需要自定义一个新类，并继承 toffee 中的 `Bundle` 类。下面是一个简单的 `Bundle` 的定义示例：

```python
from toffee import Bundle, Signals

class AdderBundle(Bundle):
    a, b, sum, cin, cout = Signals(5)
```

该 Bundle 定义了一个简单的加法器接口，在 `AdderBundle` 类中，我们定义了五个信号 `a`, `b`, `sum`, `cin`, `cout`，这五个信号分别代表了加法器的输入端口 `a`, `b`，输出端口 `sum`，以及进位输入端口 `cin` 和进位输出端口 `cout`。

定义完成后，我们可以通过 `AdderBundle` 类的实例来访问这些信号，例如：

```python
adder_bundle = AdderBundle()

adder_bundle.a.value = 1
adder_bundle.b.value = 2
adder_bundle.cin.value = 0
print(adder_bundle.sum.value)
print(adder_bundle.cout.value)
```

##### 将 DUT 绑定到 Bundle

在上述代码中，我们虽然创建了一个 bundle 实例，并对他进行了驱动，但是我们并没有将这个 bundle 与任何 DUT 绑定，也就意味着对这个 bundle 的操作，无法真正影响到 DUT。

使用 `bind` 方法，可以将一个 DUT 绑定到 bundle 上。例如我们有一个简单的加法器 DUT，其接口名称与 Bundle 中定义的名称相同。

```python
adder = DUTAdder()

adder_bundle = AdderBundle()
adder_bundle.bind(adder)
```

`bind` 函数会自动检索 DUT 中所有的接口，并将名称相同的接口进行绑定。绑定完成后，对 bundle 的操作，就会直接影响到 DUT。

但是，如果 DUT 的接口名称与 Bundle 中定义的名称不同，直接使用 `bind` 则无法正确绑定。在 Bundle 中，我们提供多种绑定方法，以适应不同的绑定需求。

###### 通过字典进行绑定

在 `bind` 函数中，我们可以通过传入一个字典，来指定 DUT 中的接口名称与 Bundle 中的接口名称之间的映射关系。

假设 Bundle 中的接口名称与 DUT 中的接口名称拥有如下对应关系：

```
a    -> a_in
b    -> b_in
sum  -> sum_out
cin  -> cin_in
cout -> cout_out
```

在实例化 `bundle` 时，我们可以通过 `from_dict` 方法创建，并传入一个字典，告知 `Bundle` 以字典的方式进行绑定。

```python
adder = DUTAdder()
adder_bundle = AdderBundle.from_dict({
    'a': 'a_in',
    'b': 'b_in',
    'sum': 'sum_out',
    'cin': 'cin_in',
    'cout': 'cout_out'
})
adder_bundle.bind(adder)
```

此时，`adder_bundle` 可正确绑定至 `adder`。

###### 通过前缀进行绑定

假设 Bundle 中的接口名称与 DUT 中的接口名称拥有如下对应关系：

```
a    -> io_a
b    -> io_b
sum  -> io_sum
cin  -> io_cin
cout -> io_cout
```

可以发现，实际 DUT 的接口名称相比于 Bundle 中的接口名称，都多了一个 `io_` 的前缀。在这种情况下，我们可以通过 `from_prefix` 方法创建 `Bundle`，并传入前缀名称，告知 `Bundle` 以前缀的方式进行绑定。

```python
adder = DUTAdder()
adder_bundle = AdderBundle.from_prefix('io_')
adder_bundle.bind(adder)
```

##### 创建子 Bundle

很多时候，我们会需要一个 Bundle 包含一个或多个其他 Bundle 的情况，这时我们可以将其他已经定义好的 Bundle 作为当前 Bundle 的子 Bundle。

```python
from toffee import Bundle, Signal, Signals

class AdderBundle(Bundle):
    a, b, sum, cin, cout = Signals(5)

class MultiplierBundle(Bundle):
    a, b, product = Signals(3)

class ArithmeticBundle(Bundle):
    selector = Signal()

    adder = AdderBundle.from_prefix('add_')
    multiplier = MultiplierBundle.from_prefix('mul_')
```

在上面的代码中，我们定义了一个 `ArithmeticBundle`，它包含了自己的信号 `selector`。除此之外它还包含了一个 `AdderBundle` 和一个 `MultiplierBundle`，这两个子 Bundle 分别被命名为 `adder` 和 `multiplier`。

当我们需要访问 `ArithmeticBundle` 中的子 Bundle 时，可以通过 `.` 运算符来访问：

```python
arithmetic_bundle = ArithmeticBundle()

arithmetic_bundle.selector.value = 1
arithmetic_bundle.adder.a.value = 1
arithmetic_bundle.adder.b.value = 2
arithmetic_bundle.multiplier.a.value = 3
arithmetic_bundle.multiplier.b.value = 4
```

同时，当我们以这种定义方式进行定义后，在最顶层的 Bundle 进行绑定时，会同时将子 Bundle 也绑定到 DUT 上，在定义子 Bundle 时，依然可以使用前文提到的多种绑定方式。

需要注意的是，子 Bundle 的创建方法去匹配的信号名称，是经过上一次 Bundle 的创建方法进行处理过后的名称。例如在上面的代码中，我们将顶层 Bundle 的匹配方式设置为 `from_prefix('io_')`，那么在 `AdderBundle` 中去匹配的信号，是去除了 `io_` 前缀后的名称。

同时，字典匹配方法会将信号名称转换为字典映射后的名称传递给子 Bundle 进行匹配，正则表达式匹配方法会将正则表达式捕获到的名称传递给子 Bundle 进行匹配。

##### Bundle 中的实用操作

1. 信号访问与赋值

**访问信号值**

在 Bundle 中，我们不仅可以通过 `.` 运算符来访问 Bundle 中的信号，也可以通过 `[]` 运算符来访问 Bundle 中的信号。

```python
adder_bundle = AdderBundle()
adder_bundle['a'].value = 1
```

**访问未连接信号**

```python
def bind(self, dut, unconnected_signal_access=True)
```

在 `bind` 时，我们可以通过传入 `unconnected_signal_access` 参数来控制是否允许访问未连接的信号。默认为 `True`，即允许访问未连接的信号，此时当写入该信号时，该信号不会发生变化，当读取该信号时，会返回 `None`。 当 `unconnected_signal_access` 为 `False` 时，访问未连接的信号会抛出异常。

**同时赋值所有信号**

可以通过 `set_all` 方法同时将所有输入信号更改为某个值。

```python
adder_bundle.set_all(0)
```

**随机赋值所有信号**

可以通过 `randomize_all` 方法随机赋值所有信号。"value_range" 参数用于指定随机值的范围，"exclude_signals" 参数用于指定不需要随机赋值的信号，"random_func" 参数用于指定随机函数。

```python
adder_bundle.randomize_all()
```

**默认消息类型赋值**

toffee 支持一个默认的消息类型，可以通过 `assign` 方法将一个字典赋值给 Bundle 中的信号。

```python
adder_bundle.assign({
    'a': 1,
    'b': 2,
    'cin': 0
})
```

Bundle 将会自动将字典中的值赋值给对应的信号，当需要将未指定的信号赋值成某个默认值时，可以通过 `*` 来指定默认值：

```python
adder_bundle.assign({
    '*': 0,
    'a': 1,
})
```

**子 Bundle 的默认消息赋值支持**

如果希望通过默认消息类型同时赋值子 Bundle 中的信号，可以通过两种方式实现。当 `assign` 中的 `multilevel` 参数为 `True` 时，Bundle 支持多级字典赋值。

```python
arithmetic_bundle.assign({
    'selector': 1,
    'adder': {
        '*': 0,
        'cin': 0
    },
    'multiplier': {
        'a': 3,
        'b': 4
    }
}, multilevel=True)
```

当 `multilevel` 为 `False` 时，Bundle 支持通过 `.` 来指定子 Bundle 的赋值。

```python
arithmetic_bundle.assign({
    '*': 0,
    'selector': 1,
    'adder.cin': 0,
    'multiplier.a': 3,
    'multiplier.b': 4
}, multilevel=False)
```

**默认消息类型读取**

在 Bundle 中可以使用，`as_dict` 方法将 Bundle 当前的信号值转换为字典。其同样支持两种格式，当 `multilevel` 为 `True` 时，返回多级字典；当 `multilevel` 为 `False` 时，返回扁平化的字典。

```python
> arithmetic_bundle.as_dict(multilevel=True)
{
    'selector': 1,
    'adder': {
        'a': 0,
        'b': 0,
        'sum': 0,
        'cin': 0,
        'cout': 0
    },
    'multiplier': {
        'a': 0,
        'b': 0,
        'product': 0
    }
}
```

```python
> arithmetic_bundle.as_dict(multilevel=False)
{
    'selector': 1,
    'adder.a': 0,
    'adder.b': 0,
    'adder.sum': 0,
    'adder.cin': 0,
    'adder.cout': 0,
    'multiplier.a': 0,
    'multiplier.b': 0,
    'multiplier.product': 0
}
```


###### 举例

```python
from toffee import Bundle, Signals


class AXI4LiteBundle(Bundle):
    aw, w, b, ar, r, req, resp = Signals(7)


class AXI4BasedDUTEnv:
    def __init__(self, dut):
        self.dut = dut
        # 引脚封装（示例）
        # AXI 接口封装
        self.axi_sin_a = AXI4LiteBundle.from_prefix("io_axi_a_")
        self.axi_sin_b = AXI4LiteBundle.from_prefix("io_axi_b_")
        # 引脚绑定
        self.axi_sin_a.bind(dut)
        self.axi_sin_b.bind(dut)

    # 把DUT非引脚相关通用函数进行env级暴露：例如 Step
    def Step(self, c=1):
        return self.dut.Step(c)

    def reset(self):
        """系统复位"""
        self.dut.reset.value = 1
        self.aix_sin_a.assign({"*":0}) # 通过Bundle接口全赋值为0
        self.dut.Step()
        self.dut.reset.value = 0
        self.dut.Step()


@pytest.fixture()
def env(dut):
    return AXI4BasedDUTEnv(dut) # 一般情况下为每个test都创建全新的 env 不需要 yield
```

**注意事项：**
- 与 dut Fixture 不同，env Fixture 可以有多个（例如：`env`, `env_1`, `env_fast`, ...），其名称必须以 `env` 开头
- env Fixture 的第一个参数必须为 `dut`，其他参数可按需添加
- env Fixture必须返回一个Class实例，且必须有dut属性
- 环境类应该封装复杂的DUT操作，提供高层次的API
- 建议在环境类中实现自检和调试功能
- 环境类应该负责自己的资源管理和清理
- 考虑使用async/await支持异步操作（如果需要）
