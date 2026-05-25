# 形式化反例 Python 测试用例编写指南

本文档介绍如何使用 picker 生成的 Python DUT 包编写形式化反例测试用例，用于复现和验证形式化验证发现的 RTL 缺陷。

## 概述

当形式化验证发现 RTL 缺陷（FALSE 属性，标记为 `[RTL_BUG]`）时，需要将其转换为可执行的 Python 测试用例。测试用例**直接操作 DUT 引脚**，按照反例（counterexample）提供的信号时序复现 Bug。

## picker DUT 基本用法

### DUT 实例化

picker 将 RTL 转换为 Python 可调用的 DUT 类。类名格式为 `DUT{DutClass}`，其中 `{DutClass}` 为模块名首字母大写。

```python
from {DUT} import DUT{DutClass}

# 创建 DUT 实例
dut = DUT{DutClass}()
```

### 时钟初始化

时序电路必须初始化时钟。时钟名称需与 RTL 端口名一致（可从 wrapper.sv 的 Clock/Reset Remapping 注释中确认）。

```python
# 常见时钟名
dut.InitClock("clk")      # 或 "clock", "sys_clk" 等
```

**组合电路不需要 InitClock。**

### 引脚操作

```python
# 写入引脚值
dut.a.value = 0xFF
dut.b.value = 0x01
dut.cin.value = 1
dut.rst_n.value = 0

# 读取引脚值（无符号）
result = dut.sum.value

# 读取引脚值（有符号）
signed_result = dut.sum.S()

# 读取/修改指定位
lsb = dut.addr[0]     # 读取最低位
dut.addr[2] = 0       # 修改第2位
```

### 电路推进

```python
# 推进 N 个时钟周期
dut.Step(1)   # 推进 1 个周期
dut.Step(5)   # 推进 5 个周期

# 组合电路也使用 Step 推进
dut.Step(1)
```

### 资源释放

每个测试函数结束时**必须**调用 `Finish()` 释放 DUT 资源：

```python
dut.Finish()
```

## 反例测试用例标准结构

### 文件命名

测试文件命名为 `test_{DUT}_counterexample.py`。

### 函数命名

每个测试函数命名为 `test_cex_{ck_name}`，其中 `{ck_name}` 为对应属性名的小写形式（去除 `A_` 前缀）。

例如：属性 `A_CK_SUM_WIDTH` → 函数 `test_cex_ck_sum_width`

### 完整示例

```python
"""形式化反例测试用例

本文件由形式化验证反例自动生成，用于复现 [RTL_BUG] 标记的缺陷。
每个测试函数对应一个 FALSE 属性的反例。
"""

from {DUT} import DUT{DutClass}


def test_cex_ck_sum_width():
    """反例测试：CK_SUM_WIDTH — 加法结果位宽不足导致高位截断

    对应属性: A_CK_SUM_WIDTH
    反例条件: a=0xFF, b=0x01, cin=1
    预期行为: sum 应等于 0x101 (9位)
    实际行为: sum 被截断为 0x01 (仅8位)
    根本原因: sum 声明为 [7:0]，缺少高位扩展
    """
    dut = DUT{DutClass}()

    # 组合电路无需 InitClock

    # 驱动反例激励
    dut.a.value = 0xFF
    dut.b.value = 0x01
    dut.cin.value = 1
    dut.Step(1)

    # 验证：预期 vs 实际
    expected_sum = 0x101
    actual_sum = dut.sum.value
    assert actual_sum == expected_sum, \
        f"CK_SUM_WIDTH Bug: 预期 sum={expected_sum:#x}, 实际 sum={actual_sum:#x}"

    dut.Finish()


def test_cex_ck_cout_logic():
    """反例测试：CK_COUT_LOGIC — 进位输出逻辑错误

    对应属性: A_CK_COUT_LOGIC
    反例条件: a=0x80, b=0x80, cin=0
    预期行为: cout 应为 1（产生进位）
    实际行为: cout 为 0（未检测到进位）
    根本原因: cout 仅检查最高位与，未考虑低位进位传播
    """
    dut = DUT{DutClass}()

    dut.a.value = 0x80
    dut.b.value = 0x80
    dut.cin.value = 0
    dut.Step(1)

    expected_cout = 1
    actual_cout = dut.cout.value
    assert actual_cout == expected_cout, \
        f"CK_COUT_LOGIC Bug: 预期 cout={expected_cout}, 实际 cout={actual_cout}"

    dut.Finish()
```

### 时序电路示例

对于时序电路，需要先初始化时钟并执行复位序列：

```python
def test_cex_ck_counter_overflow():
    """反例测试：CK_COUNTER_OVERFLOW — 计数器溢出后未正确归零

    对应属性: A_CK_COUNTER_OVERFLOW
    反例条件: 连续计数至最大值后继续递增
    预期行为: count 溢出后归零
    实际行为: count 溢出后保持最大值
    """
    dut = DUTCounter()
    dut.InitClock("clk")

    # 复位序列
    dut.rst_n.value = 0
    dut.Step(5)
    dut.rst_n.value = 1
    dut.Step(1)

    # 按反例时序驱动
    dut.enable.value = 1
    for _ in range(256):  # 计数至溢出
        dut.Step(1)

    # 验证溢出后的值
    assert dut.count.value == 0, \
        f"CK_COUNTER_OVERFLOW Bug: 溢出后 count 应为 0, 实际为 {dut.count.value}"

    dut.Finish()
```

## 注意事项

1. **时钟/复位名称**：从 `{DUT}_wrapper.sv` 的 Clock/Reset Remapping 注释区域确认 RTL 原始端口名
2. **docstring 必填**：每个函数的 docstring 必须包含对应属性名、反例条件、预期/实际行为
3. **assert 必需**：每个测试函数至少包含一个 `assert` 语句，检查预期 vs 实际
4. **Finish() 必调**：每个测试函数末尾必须调用 `dut.Finish()` 释放资源
5. **无 Bug 情况**：若无 `[RTL_BUG]` 属性，文件中写注释 `# 形式化验证未发现 RTL 缺陷，无需生成反例测试用例`
