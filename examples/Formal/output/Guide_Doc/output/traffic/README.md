# Traffic Light Controller 形式化验证规格说明文档

## 简介
- **设计背景**：Traffic Light Controller是一个十字路口交通灯控制系统，包含农场道路（farm）和高速公路（hwy）两个方向的交通灯。系统通过车辆检测和定时器控制两个方向灯的协调切换，确保交通安全。
- **设计目标**：实现双向交通灯的智能控制，根据车辆存在情况和定时约束，实现安全高效的互斥状态转换。

## 术语与缩写
| 缩写 | 全称 | 说明 |
| ---- | ---- | ---- |
| DUT | Design Under Test | 待测试设计 |
| RTL | Register Transfer Level | 寄存器传输级 |
| SVA | SystemVerilog Assertions | SystemVerilog断言 |

## RTL源文件

对涉及文件进行简要说明。

文件列表：
- <ref_file>traffic/traffic.v:1-23</ref_file> 宏定义和参数
- <ref_file>traffic/traffic.v:24-56</ref_file> main模块（顶层）
- <ref_file>traffic/traffic.v:58-102</ref_file> timer模块
- <ref_file>traffic/traffic.v:104-170</ref_file> farm_control模块
- <ref_file>traffic/traffic.v:172-205</ref_file> hwy_control模块

## 系统架构

### 模块层次结构
```
main (顶层模块)
├── timer (定时器模块)
├── farm_control (农场道路控制)
└── hwy_control (高速公路控制)
```

### 模块职责
- **main模块**：顶层协调器，连接farm_control和hwy_control，确保两个方向交通灯互斥运行
- **timer模块**：产生short_timer和long_timer信号，控制灯状态切换的时序
- **farm_control模块**：控制农场道路交通灯状态（GREEN→YELLOW→RED）
- **hwy_control模块**：控制高速公路交通灯状态（GREEN→YELLOW→RED）

### 信号流向
1. **输入信号**：clk、reset_n、car_present、long_timer_value、short_timer_value
2. **定时器**：timer接收start信号，输出short_timer和long_timer
3. **控制协调**：farm_control和hwy_control通过enable_farm和enable_hwy信号互相使能
4. **输出信号**：farm_light、hwy_light

## 顶层接口概览
- **模块名称**：`main` 交通灯控制顶层模块
- **端口列表**：

  | 信号名 | 方向 | 位宽/类型 | 复位值 | 描述 |
  | ------ | ---- | -------- | ------ | ---- |
  | clk | input | 1-bit | - | 系统时钟 |
  | reset_n | input | 1-bit | - | 异步复位信号，低电平有效 |
  | car_present | input | 1-bit | - | 车辆检测信号，`YES`=1表示有车，`NO`=0表示无车 |
  | long_timer_value | input | [4:0] | - | 长定时器阈值 |
  | short_timer_value | input | [4:0] | - | 短定时器阈值 |
  | farm_light | output | [1:0] | RED | 农场道路交通灯状态 |
  | hwy_light | output | [1:0] | GREEN | 高速公路交通灯状态 |

- **时钟与复位要求**：单一时钟域，异步复位，低电平有效。
- **内部信号**：
  - `short_timer`：短定时信号（5个周期）
  - `long_timer`：长定时信号（15个周期）
  - `enable_farm`、`enable_hwy`：两个方向的使能信号

### 内部信号定义
- **timer模块内部寄存器**：
  - `state`：reg [1:0]，定时器状态机（START=0, SHORT=1, LONG=2）
  - `timer`：reg [4:0]，当前计数值

- **farm_control模块内部寄存器**：
  - `farm_light`：reg [1:0]，农场灯状态

- **hwy_control模块内部寄存器**：
  - `hwy_light`：reg [1:0]，高速路灯状态

## 功能描述
> 将整体功能拆解为若干子模块或功能组，每组建议以二级标题呈现，包含正常流程、边界条件、异常处理。

### 定时器模块 (timer)

#### 定时器状态机
- **状态定义**：
  - `START`：初始状态（0）
  - `SHORT`：短定时状态（1）
  - `LONG`：长定时状态（2）

- **状态转移**：
  - `START` → `SHORT`：timer >= short_timer_value（5个周期）
  - `SHORT` → `LONG`：timer >= long_timer_value（15个周期）
  - 任何状态 → `START`：start信号有效或reset_n=0

- **输出信号**：
  - `short`：当state=SHORT或LONG时有效
  - `long`：当state=LONG时有效

### 农场灯状态控制 (farm_control)
- **概述**：Farm Control模块管理农场道路的交通灯状态，根据车辆检测和定时器信号控制灯的状态转换。
- **执行流程**：
  1. 在复位期间，农场灯设置为RED状态 (farm_light被设置为RED，在代码第138行)
  2. 在非复位状态下，根据当前状态进行转换：
     - 当farm_light为GREEN时：如果car_present等于NO或long_timer有效，则转为YELLOW
     - 当farm_light为YELLOW时：如果short_timer，则转为RED
     - 当farm_light为RED时：如果enable_farm，则转为GREEN
  3. 所有状态转换在时钟上升沿发生 (always @(posedge clk))
- **边界与异常**：确保农场灯状态始终在有效范围内（GREEN、YELLOW、RED）。
- **性能与约束**：状态转换在时钟上升沿发生。

### 定时器控制
- **概述**：根据当前农场灯状态生成定时器控制信号。
- **执行流程**：
  1. farm_start_timer信号由以下条件生成：
     - 当farm_light为GREEN且((car_present == `NO) || long_timer)时
     - 或者当farm_light为RED且enable_farm时
  2. enable_hwy信号在farm_light为YELLOW且short_timer时生成
- **边界与异常**：确保定时器控制逻辑的正确性。

### 高速路灯状态控制 (hwy_control)

#### 高速路灯状态机
- **状态定义**：与farm_control相同（GREEN=0, YELLOW=1, RED=2）
- **状态转移**：
  - `RED` → `GREEN`：enable_hwy有效
  - `GREEN` → `YELLOW`：(car_present == `YES) 且 long_timer有效
  - `YELLOW` → `RED`：short_timer有效

#### 定时器控制
- **hwy_start_timer**生成条件：
  - hwy_light为GREEN且((car_present == `YES) && long_timer)
  - 或hwy_light为RED且enable_hwy
- **enable_farm**生成条件：
  - hwy_light为YELLOW且short_timer

### 内部逻辑实现
- **概述**：根据源代码实现，模块内部使用组合逻辑实现farm_start_timer和enable_hwy信号
- **信号生成**：
  - farm_start_timer的赋值逻辑：当(farm_light为GREEN且(car_present为NO或long_timer有效))或(farm_light为RED且enable_farm有效)时，farm_start_timer为真 (line 132-134)
  - enable_hwy的赋值逻辑：当(farm_light为YELLOW且short_timer有效)时，enable_hwy为真 (line 135)
- **行为组合**：
  - **正常路径**：根据状态和输入信号正确生成控制信号
  - **边界条件**：复位时强制farm_light为RED状态
  - **性能假设**：信号传播在一个时钟周期内完成

### 状态机与时序

#### 交通灯状态编码
| 状态 | 编码 | 描述 |
| ---- | ---- | ---- |
| GREEN | 2'd0 | 绿灯，允许通行 |
| YELLOW | 2'd1 | 黄灯，警告即将转为红灯 |
| RED | 2'd2 | 红灯，禁止通行 |

#### 农场灯状态转移条件
| 当前状态 | 下一状态 | 转移条件 |
| -------- | -------- | -------- |
| RED | GREEN | enable_farm有效 |
| GREEN | YELLOW | (car_present == `NO) 或 long_timer有效 |
| YELLOW | RED | short_timer有效 |

#### 高速路灯状态转移条件
| 当前状态 | 下一状态 | 转移条件 |
| -------- | -------- | -------- |
| RED | GREEN | enable_hwy有效 |
| GREEN | YELLOW | (car_present == `YES) 且 long_timer有效 |
| YELLOW | RED | short_timer有效 |

#### 时序行为
- 所有状态转换在时钟上升沿（posedge clk）发生
- farm_control复位时状态为RED
- hwy_control复位时状态为GREEN
- 状态转移使用非阻塞赋值

### 配置寄存器及存储
无外部配置寄存器。
- **配置流程**：无配置流程，所有参数通过输入信号传递。

### 复位与错误处理
- **复位行为**：在复位信号reset_n为低电平时，农场灯状态复位为RED（farm_light被设置为RED；在代码第138行）。复位为同步复位，在时钟上升沿生效。
- **错误上报**：通过SVA断言检查错误状态，如农场灯状态超出有效范围。
- **自恢复策略**：无自恢复策略，系统依赖外部复位信号恢复。

### 输入输出约束
- **输入约束**：
  - `car_present`：应为有效的车辆检测信号值（`YES`=1或`NO`=0）
  - `enable_farm`：由hwy_control模块提供的使能信号
  - `short_timer`和`long_timer`：由timer模块提供的定时信号
- **输出约束**：
  - `farm_light`：输出必须为有效的交通灯状态（`GREEN`、`YELLOW`或`RED`）
  - `farm_start_timer`：根据内部状态和输入信号计算得出
  - `enable_hwy`：根据内部状态和输入信号计算得出

### 功耗、时钟与电源管理（如适用）
- **功耗模式**：无功耗管理模式，持续运行
- **时钟门控**：无时钟门控
- **电源域**：单电源域

### 参数化与可配置特性
无参数化特性。

- **编译宏/生成选项**：`SVA_ON` - 启用系统Verilog断言

## 验证需求与覆盖建议
- **功能覆盖点**：需要验证农场灯状态转换逻辑、定时器控制信号生成、复位行为。
- **约束与假设**：农场灯状态仅限于GREEN、YELLOW、RED三种有效状态。
- **测试接口**：需要驱动接口控制输入信号（clk、reset_n、car_present、enable_farm、定时器信号）和监视接口观察输出信号（farm_light、farm_start_timer、enable_hwy）。



