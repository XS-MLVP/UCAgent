
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

在实现 dut Fixture 之前，需要先实现 `create_dut` 函数，它的作用是创建 DUT。其基本结构如下：

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

    # 设置波形生成文件（根据需要设置，可选）
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
from {DUT}_function_coverage_def import get_coverage_groups

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
- 常规情况下，统一使用 `dut.Step(...)` 推进电路；通过 `dut.StepRis(...)` 在上升沿回调中自动采样功能覆盖
- 组合电路通常不需要时钟即可生效；为流程统一，可仍调用 `dut.Step(1)` 以触发 StepRis 回调与采样
- 仅在特殊需求下使用 `RefreshComb` 推进组合逻辑，例如：模块同时包含组合与时序逻辑，需要在同一周期内刷新组合路径
    - 此时可采用 `RefreshComb + Step` 的混合方式
- 使用 `RefreshComb` 时，需要在 API 或测试用例中手动调用覆盖组 `CovGroup.sample()` 完成采样（因为不会触发 StepRis 回调）

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
from toffee import Bundle
...

# 根据需要定义子Bundle
# class MyPort(Bundle):
#     signal1, signal2 = Signals(2)
#     # 根据需要定义Port对应的操作
#     def some_operation(self):
#         pass

# 定义{{DUT}}Env类，封装DUT的引脚和常用操作
class {{DUT}}Env:
    '''请在这里对Env的功能进行描述'''

    def __init__(self, dut):
        self.dut = dut
        # 请在这里根据DUT的引脚定义，封装引脚为toffee.Bundle
        # self.some_input = MyPort.from_prefix("some_input_", dut)
        # self.axi_master = Bundle.from_prefix("io_axi_master_", dut)
        # self.some_input.bind(dut)

    # 根据需要定义Env的常用操作
    # def reset(self):
    #    # 根据DUT的复位方式，完成复位操作
    #    pass

    # 直接导出DUT的通用操作
    def Finish(self):
        self.dut.Finish()

    def Step(self, i:int = 1):
        return self.dut.Step(i)

    def RefreshComb(self):
        return self.dut.RefreshComb()

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

**注意**：`Bundle.from_prefix`也可以不定义Bundle的子类，而直接创建对引脚进行绑定。

例如：
```python
adder = DUTAdder()
adder_io = Bundle.from_prefix("io_", adder) # 该方法内部调用了bind(dut)，不用再次显示bind
```

方法`Bundle.from_prefix(prefix, dut)`是简化方法，虽然去掉Bundle子类定义，但可读性差，不建议使用


###### 通过正则表达式进行绑定

在某些情况下，DUT 中的接口名称与 Bundle 中的接口名称之间的对应关系并不是简单的前缀或者字典关系，而是更为复杂的规则。例如，Bundle 中的接口名称与 DUT 中的接口名称之间的对应关系为：

```
a    -> io_a_in
b    -> io_b_in
sum  -> io_sum_out
cin  -> io_cin_in
cout -> io_cout_out
```

在这种情况下，我们可以通过传入正则表达式，来告知 `Bundle` 以正则表达式的方式进行绑定。

```python
adder = DUTAdder()
adder_bundle = AdderBundle.from_regex(r'io_(.*)_.*')
adder_bundle.bind(adder)
```

使用正则表达式时，Bundle 会尝试将 DUT 中的接口名称与正则表达式进行匹配，匹配成功的接口，将会读取正则表达式中的所有捕获组，将其连接为一个字符串。再使用这个字符串与 Bundle 中的接口名称进行匹配。

例如对于上面代码中的正则表达式，`io_a_in` 会与正则表达式成功匹配，唯一的捕获组捕获到的内容为 `a`。`a` 这个名称与 Bundle 中的接口名称 `a` 匹配，因此 `io_a_in` 会被正确绑定至 `a`。

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

##### 创建 SignalList

在某些情况下，会存在有一组信号的名称相似，且数量较多，例如以下情况：

```
io_vec_0
io_vec_1
io_vec_2
...
io_vec_9
```

如果使用 `Signal` 一个一个定义，会显得非常繁琐。为了解决这个问题，toffee 提供了 `SignalList` 类，用于定义一组信号。按照如下方式使用：

```python
from toffee import Bundle, SignalList

class VectorBundle(Bundle):
    vec = SignalList("vec_#", 10)
```

上面的代码定义了一个 `VectorBundle`，它包含了一个 `vec` 信号列表，该信号列表包含了 10 个信号，信号名称分别为 `vec_0`, `vec_1`, `vec_2`, ..., `vec_9`。这取决于 `SignalList` 定义时传入的名称字符串`vec_#` ，其中的 `#` 根据第二个参数 10 被替换为 0 到 9。

在实例化 `VectorBundle` 后，我们可以通过 `vec` 来访问这一组信号：

```python
vector_bundle = VectorBundle()

vector_bundle.vec[0].value = 1
vector_bundle.vec[1].value = 2
...
vector_bundle.vec[9].value = 10
```

如果想要自定义从数字到信号名称的映射，可以通过传入一个函数来实现，例如：

```python
def custom_name_func(i):
    return f"vec_{i + 1}"

class VectorBundle(Bundle):
    vec = SignalList("vec_#", 10, custom_name_func)
```

##### 创建 BundleList

类似的，还有可能会存在有一组 Bundle 的情况，例如以下情况：

```
io_vec0_a
io_vec0_b
io_vec0_c
io_vec1_a
io_vec1_b
io_vec1_c
...
io_vec9_a
io_vec9_b
io_vec9_c
```

如果使用多个 SubBundle 一个一个定义，也会非常繁琐。为此，Toffee 还提供了 `BundleList` 类，用于定义一组 Bundle。按照如下方式使用：

```python

from toffee import Bundle, BundleList

class SubBundle(Bundle):
    a, b, c = Signals(3)

class VectorBundle(Bundle):
    vec = BundleList(SubBundle, "vec#_", 10)
```

上面的代码定义了一个 `VectorBundle`，它包含了一个 `vec` Bundle 列表，该 Bundle 列表包含了 10 个 SubBundle，每个 SubBundle 的匹配方法都被指定为**前缀匹配**，待匹配前缀分别为 `vec0_`, `vec1_`, `vec2_`, ..., `vec9_`。如果要访问这一组 Bundle，可以通过 `vec` 来访问：

```python
vector_bundle = VectorBundle()

vector_bundle.vec[0].a.value = 1
vector_bundle.vec[0].b.value = 2
vector_bundle.vec[0].c.value = 3
...

vector_bundle.vec[9].a.value = 28
vector_bundle.vec[9].b.value = 29
vector_bundle.vec[9].c.value = 30
```

与 `SignalList` 类似，如果想要自定义从数字到 Bundle 名称的映射，可以通过传入一个函数来实现，例如：

```python
def custom_name_func(i):
    return f"vec{i + 1}_"

class VectorBundle(Bundle):
    vec = BundleList(SubBundle, "vec#_", 10, custom_name_func)
```

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


### 异步支持

在 Bundle 中，为了方便的接收时钟信息，提供了 `step` 函数。当 Bundle 连接至 DUT 的任意一个信号时，step 函数会自动同步至 DUT 的时钟信号。

可以通过 `step` 函数来完成时钟周期的等待。

```python
async def adder_process(adder_bundle):
    adder_bundle.a.value = 1
    adder_bundle.b.value = 2
    adder_bundle.cin.value = 0
    await adder_bundle.step()
    print(adder_bundle.sum.value)
    print(adder_bundle.cout.value)
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
        # 以 from_prefix(prefix, dut) 方式封装
        self.custom_a = Bundle.from_prefix("my_custom_a_", dut)
        self.custom_x = Bundle.from_prefix("my_custom_x_", dut)
        # 引脚绑定
    self.axi_sin_a.bind(dut)
    self.axi_sin_b.bind(dut)

    # 把DUT非引脚相关通用函数进行env级暴露：例如 Step 和 RefreshComb
    def Step(self, c=1):
        return self.dut.Step(c)

    def RefreshComb(self):
        return self.dut.RefreshComb()

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

**注意：**

- 与 dut Fixture 不同，env Fixture 可以有多个（例如：`env`, `env_1`, `env_fast`, ...），其名称必须以 `env` 开头
- env Fixture 的第一个参数必须为 `dut`，其他参数可按需添加


##### 其他用法示例

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
from toffee import Bundle, Signals

class AXI4LiteMasterBundle(Bundle):
    ...
    async def send_write_addr(self, len, id):
        ....

class AXI4LiteSlaveBundle(Bundle):
    ...


class AXITestEnv:
    def __init__(self, dut):
        self.dut = dut
        self.axi_master = AXI4LiteMasterBundle.from_prefix("master_") # AXI主控接口封装
        self.axi_slave  = AXI4LiteSlaveBundle.from_prefix("slave_") # AXI从设备接口封装
        self.outstanding_transactions = {}     # 未完成事务跟踪
        self.axi_master.bind(dut)
        self.axi_slave.bind(dut)
        
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

**注意事项：**
- env Fixture必须返回一个Class实例，且必须有dut属性
- 环境类应该封装复杂的DUT操作，提供高层次的API
- 建议在环境类中实现自检和调试功能
- 环境类应该负责自己的资源管理和清理
- 考虑使用async/await支持异步操作（如果需要）
