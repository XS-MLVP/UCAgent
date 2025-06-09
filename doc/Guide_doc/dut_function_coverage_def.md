
## 功能覆盖率

需要通过函数 `get_coverage_groups(dut=None) -> List[CovGroup]` 提供功能覆盖率。

功能检查点标需使用 `toffee` 和 `toffee_test` 库。


**常用功能覆盖接口：**

- `toffee.funcov.CovGroup(name: str)`
  创建功能覆盖组，参数为组名。

- `CovGroup.add_watch_point(target, bins: dict, name: str)`
  添加功能检查点：
    - `target`：检查函数的输入参数。注意该参数不要传递值传递类型参数，例如dut.a.value（int类型）, 值传递方法会导致其值再dut变化后不更新，建议直接传递dut或者dut.a *
    - `bins`：dict类型，key为名称，value为检查函数 `func(target): bool`
    - `name`：检查点名称，需有明确意义

- `CovGroup.sample()`
  采样，调用所有检查点的检查函数，统计功能覆盖率。

- `toffee_test.reporter.set_func_coverage(request, g: CovGroup or list[CovGroup])`
  测试结束时，将CovGroup传递给toffee_test生成测试结果：
  - `request`：pytest中的request fixture*
  - `g`: 需要传递给toff_test的单个CovGroup，或者CovGroup组数

- `CovGroup.mark_function(watch_point_name: str, test_function_name_or_list, bins=[])`
  关联测试用例与检查点：
    - `watch_point_name`：检查点名称
    - `test_function_name_or_list`：需标记的测试用例（可为单个或列表）
    - `bins`：需标记的具体检查函数

**举例如下**

```python
import toffee.funcov as fc

funcov_A = fc.CovGroup("FG-A")
funcov_B = fc.CovGroup("FG-B")
funcov_group = [funcov_A, funcov_B]

def init_coverage_group_A(g, dut):
    g.add_watch_point(dut,
        {
            "CK-1": lambda x: x.a.value + x.b.value == x.out.value,
            "CK-2": lambda x: x.cout.value == 1,
         },
        name="FC-A1") # 为dut中的功能点FC-A添加检查点CK-1 和 CK-2
    # other check point
    # ....

def init_coverage_group_B(g, dut):
    # check points for B
    # ....


def init_function_coverage(dut, cover_group):
    init_coverage_group_A(cover_group[0], dut)
    init_coverage_group_B(cover_group[1], dut)

def get_coverage_groups(dut=None):                    # 需要支持dut为None
    if dut:
        init_function_coverage(dut, funcov_group)     # 初始化功能覆盖
    return funcov_group
```

