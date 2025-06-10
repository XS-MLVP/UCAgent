
# 测试用例

在测试用例中，仅仅之需要`import` DUT 提供的API，一般情况下，不需要依赖其他模块，例如

```python

from <dut_name>_api import *

def test_function_A(dut):
    # test and assert logic
    # ...

```

在测试用例中，需要和检查点进行关联，表明该测试函数覆盖到了哪些检查点，例如：

```python

def test_function_A(dut):
    # ...
    # 利用 mark_function 函数标记函数 test_function_A 覆盖了 组FG-A中功能点FC-A1中的检查点CK-1和CK-3
    dut._g["FG-A"].mark_function("FC-A1", test_add_overflow, ["CK-1", "CK-3"])
    # ...
```

在实际例子中，`FG-A`、`FC-A1`、`CK-1`、`CK-3`等需要从名字中表达出具体含义，例如 `FC-ADD-NORN`，`FC-ADD-OVERFLOW`等。
注意，每个test函数都需要覆盖至少一个检测点，每个检测点至少被一个test函数覆盖。
