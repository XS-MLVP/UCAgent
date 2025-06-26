
### DUT fixture 创建

在所有test函数中，都需要通过参数`dut`获取DUT的实例，因此需要提供对应的fixture。由于需要通过`request`参数保存测试结果，因此在dut对应的fixture中，需要参数`request`，其定义如下：

```python
@pytest.fixture()
def dut(request):
    dut = create_dut()                                   # 创建DUT
    func_coverage_group = get_coverage_groups(dut)
    dut.InitClock("clock")                               # 初始化时钟，确保dut有clock引脚。如果dut没有时钟则不需要InitClock
    dut.StepRis(lambda _: [g.sample()
                           for g in
                           func_coverage_group])         # 上升沿采样，组合电路也可以用Step接口进行推进
    setattr(dut, "fc_cover",
            {g.name:g for g in func_coverage_group})     # 保存覆盖组到DUT
    yield dut
    # 测试后处理
    set_func_coverage(request, func_coverage_group)      # 需要在测试结束的时候，通过set_func_coverage把覆盖组传递给toffee_test*
    for g in func_coverage_group:                        # 采样覆盖组
        g.clear()                                        # 清空统计
    dut.Finish()                                         # 清理DUT

def create_dut():
    # your code here
    # ...

```

对于所有测试，上述代码除了 `dut.InitClock("clock")`可能有区别外，其他部分基本相同。因为时钟引脚可能是其他名字例如`clk`，或者dut为组合电路没有时钟。对于时序电路，时钟的具体引脚名称，可以在 `{DUT}/__init__.py` 文件中查找。

### DUT 的 API定义

在测试DUT时，需要对DUT的功能进行封装，并且保持其接口稳定，这样在DUT的实现发生变化时，只需要修改对应api的实现，不用修改测试用例。通常情况下api内部包含了时序，时序对外不可见，例如以cache为例，其api可以为：

```python

def api_cache_read(dut, address) -> int:
    dut.in_addr.value = address   # 引脚赋值
    dut.in_valid.value = 1
    while dut.out_valid != 1:     # 等待返回值
        dut.Step(1)               # 推进时钟（组合电路也可以通过Step接口进行推进，或者使用RefreshComb推进组合电路）
    return dut.out_data.value     # 返回有效值
```

api的格式为`api_<dut_name>_<func_name>`，第一个参数为dut实例。api的定义需要按照需求来定，不是越多越好，而是越通用越好。
