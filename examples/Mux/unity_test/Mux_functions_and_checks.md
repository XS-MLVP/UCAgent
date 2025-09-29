# Mux 功能点与检测点描述

## DUT 整体功能描述

Mux（多路选择器）是一个4选1的组合电路，根据2位选择信号从4个输入信号中选择一个输出。

### 端口接口说明

**输入端口：**
- `in_data[3:0]`：4个输入信号，每个1位
- `sel[1:0]`：2位选择信号，用于选择输出哪个输入信号

**输出端口：**
- `out`：1位输出信号，根据sel选择的输入信号

### 工作原理

根据sel信号的值，将对应的in_data[i]信号传递到out端口：
- sel=2'b00时，out = in_data[0]
- sel=2'b01时，out = in_data[1]
- sel=2'b10时，out = in_data[2]
- sel=2'b11时，out = in_data[0]（默认情况）

## 功能分组与检测点

### DUT测试API

<FG-API>

#### 通用选择功能

<FC-SELECT>

提供Mux的基本选择功能接口，根据sel信号选择对应的输入信号输出。

**检测点：**
- <CK-SEL-00> 选择信号00：验证sel=2'b00时选择in_data[0]输出
- <CK-SEL-01> 选择信号01：验证sel=2'b01时选择in_data[1]输出
- <CK-SEL-10> 选择信号10：验证sel=2'b10时选择in_data[2]输出
- <CK-SEL-11> 选择信号11：验证sel=2'b11时选择in_data[0]输出（默认情况）

### 信号选择功能分组

<FG-SELECT>

包含Mux的核心功能：根据选择信号从多个输入中选择一个输出。

#### 基本选择功能

<FC-BASIC-SELECT>

实现根据sel信号选择对应输入信号的功能。

**检测点：**
- <CK-SEL-00> 选择信号00：验证sel=2'b00时正确选择in_data[0]
- <CK-SEL-01> 选择信号01：验证sel=2'b01时正确选择in_data[1]
- <CK-SEL-10> 选择信号10：验证sel=2'b10时正确选择in_data[2]
- <CK-SEL-11> 选择信号11：验证sel=2'b11时正确选择in_data[0]（默认情况）

#### 输入通道连通性

<FC-CHANNEL-CONNECT>

验证每个输入通道到输出的连通性。

**检测点：**
- <CK-CHANNEL-0> 通道0连通性：验证in_data[0]能正确传输到out
- <CK-CHANNEL-1> 通道1连通性：验证in_data[1]能正确传输到out
- <CK-CHANNEL-2> 通道2连通性：验证in_data[2]能正确传输到out
- <CK-CHANNEL-3> 通道3连通性：验证in_data[3]能正确传输到out

### 边界条件处理分组

<FG-BOUNDARY>

处理特殊输入条件和边界情况。

#### 默认路径处理

<FC-DEFAULT-PATH>

处理sel=2'b11时的默认路径选择。

**检测点：**
- <CK-DEFAULT> 默认路径：验证sel=2'b11时选择in_data[0]作为默认输出

#### 全0输入测试

<FC-ALL-ZERO>

验证所有输入为0时的输出行为。

**检测点：**
- <CK-ALL-ZERO-SEL-00> 全0输入sel=00：验证所有输入为0且sel=00时输出为0
- <CK-ALL-ZERO-SEL-01> 全0输入sel=01：验证所有输入为0且sel=01时输出为0
- <CK-ALL-ZERO-SEL-10> 全0输入sel=10：验证所有输入为0且sel=10时输出为0
- <CK-ALL-ZERO-SEL-11> 全0输入sel=11：验证所有输入为0且sel=11时输出为0

#### 全1输入测试

<FC-ALL-ONE>

验证所有输入为1时的输出行为。

**检测点：**
- <CK-ALL-ONE-SEL-00> 全1输入sel=00：验证所有输入为1且sel=00时输出为1
- <CK-ALL-ONE-SEL-01> 全1输入sel=01：验证所有输入为1且sel=01时输出为1
- <CK-ALL-ONE-SEL-10> 全1输入sel=10：验证所有输入为1且sel=10时输出为1
- <CK-ALL-ONE-SEL-11> 全1输入sel=11：验证所有输入为1且sel=11时输出为1