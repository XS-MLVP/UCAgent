
# Mux 功能点与检测点描述

## DUT 整体功能描述

Mux (多路选择器) 的主要功能是根据2位的选择信号 `sel`，从4路输入数据 `in_data` 中选择其中一路作为输出 `out`。

### 端口接口说明
- **输入端口:**
  - `in_data[3:0]`: 4位输入数据
  - `sel[1:0]`: 2位选择信号
- **输出端口:**
  - `out`: 1位输出数据

## 功能分组与检测点

### Mux选择功能

<FG-SELECT>

该功能组主要覆盖Mux的核心选择功能，确保在所有`sel`组合下都能正确选择对应的输入。

#### 选择in_data[0]

<FC-SELECT-0>

当`sel`为00时，选择`in_data[0]`作为输出。

**检测点：**
- <CK-BASIC> 基本功能：验证`in_data[0]`为1，其他为0时，输出为1。
- <CK-ISOLATION> 隔离性：验证`in_data[0]`为0，其他为1时，输出为0。

#### 选择in_data[1]

<FC-SELECT-1>

当`sel`为01时，选择`in_data[1]`作为输出。

**检测点：**
- <CK-BASIC> 基本功能：验证`in_data[1]`为1，其他为0时，输出为1。
- <CK-ISOLATION> 隔离性：验证`in_data[1]`为0，其他为1时，输出为0。

#### 选择in_data[2]

<FC-SELECT-2>

当`sel`为10时，选择`in_data[2]`作为输出。

**检测点：**
- <CK-BASIC> 基本功能：验证`in_data[2]`为1，其他为0时，输出为1。
- <CK-ISOLATION> 隔离性：验证`in_data[2]`为0，其他为1时，输出为0。

#### 选择in_data[3]

<FC-SELECT-3>

当`sel`为11时，选择`in_data[3]`作为输出。

**检测点：**
- <CK-BASIC> 基本功能：验证`in_data[3]`为1，其他为0时，输出为1。
- <CK-ISOLATION> 隔离性：验证`in_data[3]`为0，其他为1时，输出为0。

### DUT测试API

<FG-API>

该功能组用于验证提供给测试用例的API接口的正确性。

#### 通用operation功能

<FC-OPERATION>

提供DUT支持的各种运算操作接口，涵盖所有op操作码对应的运算类型。这些操作是DUT的核心功能实现。

**检测点：**
- <CK-SELECT-0> API功能：验证通过API选择`in_data[0]`。
- <CK-SELECT-1> API功能：验证通过API选择`in_data[1]`。
- <CK-SELECT-2> API功能：验证通过API选择`in_data[2]`。
- <CK-SELECT-3> API功能：验证通过API选择`in_data[3]`。
