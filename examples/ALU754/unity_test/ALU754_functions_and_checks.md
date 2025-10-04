# ALU754 功能点与检测点描述

## DUT 整体功能描述

ALU754 是一个 IEEE 754 单精度浮点数运算单元，支持加法、减法、乘法、除法和比较操作，并集成了溢出和下溢处理。它是一个组合电路，没有时钟信号，根据输入立即产生输出。

### 端口接口说明

**输入端口：**
- `a`：第一个操作数，32位IEEE 754单精度浮点数
- `b`：第二个操作数，32位IEEE 754单精度浮点数
- `op`：功能选择信号，3位，用于选择运算类型

**输出端口：**
- `result`：运算结果，32位
- `overflow`：溢出标志，1位
- `underflow`：下溢标志，1位
- `gt`：A > B 比较结果，1位
- `lt`：A < B 比较结果，1位
- `eq`：A == B 比较结果，1位

### 运算模式定义

| op值 | 运算类型 | 功能描述 |
|------|----------|----------|
| 0    | 加法     | result = a + b |
| 1    | 乘法     | result = a × b |
| 2    | 除法     | result = a / b |
| 3    | 比较     | result = 0, gt/lt/eq 根据 a 与 b 的比较结果设置 |
| 其他 | 保留     | result = 0, overflow/underflow/gt/lt/eq = 0 |

## 功能分组与检测点

### DUT测试API

<FG-API>

#### 通用operation功能

<FC-OPERATION>

提供DUT支持的各种运算操作接口，涵盖所有op操作码对应的运算类型。这些操作是DUT的核心功能实现。

**检测点：**
- <CK-ADD> 加法操作：验证op=0时的加法运算功能，result = a + b
- <CK-MUL> 乘法操作：验证op=1时的乘法运算功能，result = a × b
- <CK-DIV> 除法操作：验证op=2时的除法运算功能，result = a / b
- <CK-CMP> 比较操作：验证op=3时的比较运算功能，result = 0, gt/lt/eq根据比较结果设置
- <CK-INVALID> 无效操作码：验证op值超出定义范围时的处理，result = 0

<FG-ARITHMETIC>

### 算术运算功能分组

包含基本的浮点算术运算功能：加法、乘法、除法等。

#### 加法功能

<FC-ADD>

实现IEEE 754单精度浮点数加法运算，支持特殊值处理。运算公式：result = a + b

**检测点：**
- <CK-BASIC> 基本加法：验证正常浮点数的加法运算
- <CK-OVERFLOW> 加法溢出：验证结果超出浮点表示范围时溢出标志的正确性
- <CK-UNDERFLOW> 加法下溢：验证结果小于浮点最小正数时下溢标志的正确性
- <CK-ZERO> 零值运算：验证操作数为0时的运算正确性，如0+0=0, 1+0=1
- <CK-NEGATIVE> 负数运算：验证负数参与的加法运算
- <CK-NAN> NaN运算：验证NaN参与的加法运算结果为NaN
- <CK-INFINITY> 无穷运算：验证无穷参与的加法运算

#### 乘法功能

<FC-MUL>

实现IEEE 754单精度浮点数乘法运算，支持特殊值处理。运算公式：result = a × b

**检测点：**
- <CK-BASIC> 基本乘法：验证正常浮点数的乘法运算
- <CK-OVERFLOW> 乘法溢出：验证结果超出浮点表示范围时溢出标志的正确性
- <CK-UNDERFLOW> 乘法下溢：验证结果小于浮点最小正数时下溢标志的正确性
- <CK-ZERO-FACTOR> 零乘数：验证操作数为0时结果为0
- <CK-NEGATIVE> 负数运算：验证负数参与的乘法运算
- <CK-NAN> NaN运算：验证NaN参与的乘法运算结果为NaN
- <CK-INFINITY> 无穷运算：验证无穷参与的乘法运算

#### 除法功能

<FC-DIV>

实现IEEE 754单精度浮点数除法运算，支持特殊值处理。运算公式：result = a / b

**检测点：**
- <CK-BASIC> 基本除法：验证正常浮点数的除法运算
- <CK-OVERFLOW> 除法溢出：验证结果超出浮点表示范围时溢出标志的正确性
- <CK-UNDERFLOW> 除法下溢：验证结果小于浮点最小正数时下溢标志的正确性
- <CK-DIV-BY-ZERO> 除零运算：验证被除数为0时的行为
- <CK-ZERO-DIV> 零被除：验证0除以非零数的运算
- <CK-NAN> NaN运算：验证NaN参与的除法运算结果为NaN
- <CK-INFINITY> 无穷运算：验证无穷参与的除法运算

<FG-COMPARATOR>

### 比较功能分组

包含IEEE 754单精度浮点数比较功能。

#### 比较功能

<FC-CMP>

实现IEEE 754单精度浮点数比较运算，输出gt,lt,eq标志。运算不产生result值。

**检测点：**
- <CK-GT> 大于比较：验证A > B时gt为1，lt和eq为0
- <CK-LT> 小于比较：验证A < B时lt为1，gt和eq为0
- <CK-EQ> 等于比较：验证A == B时eq为1，gt和lt为0
- <CK-NAN-COMP> NaN比较：验证任一操作数为NaN时，gt、lt、eq均为0
- <CK-ZERO-COMP> 零值比较：验证正零与负零的比较结果
- <CK-INFINITY-COMP> 无穷比较：验证无穷值之间的比较
- <CK-NEGATIVE-COMP> 负数比较：验证负数间的比较运算

<FG-SPECIAL-VALUES>

### 特殊值处理分组

包含IEEE 754标准中定义的各种特殊值的处理。

#### 特殊值运算

<FC-SPECIAL-VALUES>

处理IEEE 754标准中定义的特殊值，包括NaN、无穷、零等。

**检测点：**
- <CK-NAN-ARITH> NaN算术：验证NaN参与的所有算术运算结果为NaN
- <CK-INFINITY-ARITH> 无穷算术：验证无穷参与的算术运算
- <CK-ZERO-ARITH> 零值算术：验证+0和-0参与的算术运算
- <CK-SUBNORMAL> 非规约数：验证非规约浮点数的运算处理
- <CK-ROUNDING> 舍入处理：验证运算结果的舍入行为