# FSM 功能点与检测点描述

## DUT 整体功能描述

FSM（Finite State Machine，有限状态机）是一个Mealy型状态机，用于实现按键消抖与单次触发脉冲生成功能。当检测到按键按下时，状态机产生一个时钟周期宽度的脉冲信号。

### 端口接口说明

**输入端口：**
- `clk`：时钟信号，1位
- `reset`：异步复位信号，1位，高电平有效
- `key_in`：按键输入信号，1位，低电平有效（0表示按下）

**输出端口：**
- `pulse_out`：脉冲输出信号，1位，高电平有效

**控制接口：**
- 无额外控制接口

### 工作原理概述

状态机包含两个状态：IDLE（空闲状态）和PRESSED（按下状态）。
1. 复位时进入IDLE状态
2. 在IDLE状态检测到按键按下（key_in=0）时，转换到PRESSED状态
3. 在PRESSED状态时，如果按键仍然按下，输出一个时钟周期的脉冲（pulse_out=1），然后立即返回IDLE状态

## 功能分组与检测点

### DUT测试API

<FG-API>

#### 时钟功能

<FC-CLK>

提供时钟信号驱动状态机运行。

**检测点：**
- <CK-CLKFUNC> 时钟驱动：验证clk信号能够驱动状态机状态转换

#### 复位功能

<FC-RST>

提供复位信号将状态机重置到初始状态。

**检测点：**
- <CK-RSTIFUNC> 复位功能：验证reset信号能够异步复位状态机到IDLE状态

#### 按键输入功能

<FC-KEY>

提供按键输入信号给状态机。

**检测点：**
- <CK-KEYIFUNC> 按键输入：验证key_in信号能够被状态机正确识别

#### 脉冲输出功能

<FC-PULSE>

获取状态机输出的脉冲信号。

**检测点：**
- <CK-PULSEIFUNC> 脉冲输出：验证pulse_out信号能够正确输出脉冲

<FG-STATE>

### 状态管理功能分组

包含状态机的状态初始化、状态转换和复位功能。

#### 状态初始化功能

<FC-INIT>

实现状态机上电或复位后的初始化，进入IDLE状态。

**检测点：**
- <CK-INITIDLE> 初始化状态：验证复位后状态机正确进入IDLE状态

#### 状态转换功能

<FC-TRANS>

实现状态机在IDLE和PRESSED状态之间的转换。

**检测点：**
- <CK-TRANSIDLEPRESSED> 空闲到按下：验证IDLE状态下key_in=0时正确转换到PRESSED状态
- <CK-TRANSPRESSEDIDLE> 按下到空闲：验证PRESSED状态下key_in=1时正确转换到IDLE状态

#### 复位功能

<FC-RSTFUNC>

实现状态机在任意状态下都能通过复位信号回到IDLE状态。

**检测点：**
- <CK-RSTIDLE> 复位功能：验证任意状态下reset=1时状态机回到IDLE状态

<FG-KEY>

### 按键检测功能分组

包含按键按下和释放的检测功能。

#### 按键按下检测功能

<FC-KEYDOWN>

在IDLE状态下检测按键按下信号（key_in=0）。

**检测点：**
- <CK-KEYDOWNDETECT> 按键按下检测：验证IDLE状态下key_in=0被正确检测到

#### 按键释放检测功能

<FC-KEYUP>

在PRESSED状态下检测按键释放信号（key_in=1）。

**检测点：**
- <CK-KEYUPDETECT> 按键释放检测：验证PRESSED状态下key_in=1被正确检测到

<FG-PULSE>

### 脉冲输出功能分组

包含脉冲生成和持续时间控制功能。

#### 脉冲生成功能

<FC-PULSEGEN>

在PRESSED状态下输出一个时钟周期宽度的脉冲信号。

**检测点：**
- <CK-PULSEGEN> 脉冲生成：验证PRESSED状态下pulse_out=1

#### 脉冲持续时间控制功能

<FC-PULSELEN>

控制脉冲信号仅在一个时钟周期内为高电平。

**检测点：**
- <CK-PULSELEN> 脉冲持续时间：验证pulse_out仅在一个时钟周期内为高电平