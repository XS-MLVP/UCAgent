# DUT 测试程序编程方法指南

## 概述

在基于 picker 的芯片验证用例开发中，根据DUT复杂度和编程逻辑的不同，主要有三种编程方法：**顺序编程**、**回调编程**和**异步编程**。每种方法都有其优缺点和最佳适用场景。

## 三种方法的适用场景

### 顺序编程 - 适用于简单验证

**推荐使用场景：**
- DUT端口数量较少（例如<10个）
- 功能相对简单的模块验证
- 团队初次接触DUT测试
- 快速原型和基础功能验证
- 调试阶段的单步验证

**优势：**
- 代码逻辑清晰，易于理解和维护
- 调试简单，问题定位容易
- 学习成本低，适合新手
- 测试结果可预测性强

**局限性：**
- 测试执行效率低
- 难以处理复杂的并发场景
- 不适合大规模验证

### 回调编程 - 适用于中等复杂度验证

**推荐使用场景：**
- DUT端口数量中等（例如10-50个）
- 需要处理多种协议交互
- 有一定的并发测试需求
- 团队有事件驱动编程经验
- 需要响应式测试模式

**优势：**
- 较好的执行效率
- 支持事件驱动的测试模式
- 可以处理一定的并发场景
- 相比异步编程更容易理解

**局限性：**
- 回调地狱问题
- 错误处理复杂
- 代码可读性随复杂度下降

### 异步编程 - 适用于复杂验证

**推荐使用场景：**
- DUT端口数量多（例如>50个）
- 复杂的多协议并发验证
- 大规模回归测试
- 性能敏感的验证环境
- 团队有异步编程经验

**优势：**
- 最高的执行效率
- 出色的并发处理能力
- 现代化的编程模式
- 适合大规模测试

**局限性：**
- 学习成本高
- 调试相对复杂
- 需要careful的异常处理

### 选择决策流程图

```
开始验证项目
    ↓
评估DUT复杂度
    ↓
├─ 简单DUT（<10端口）
│   ↓
│   选择顺序编程 ✓
│
├─ 中等DUT（10-50端口）
│   ↓
│   团队编程经验如何？
│   ├─ 有事件编程经验 → 回调编程 ✓
│   └─ 无事件编程经验 → 顺序编程
│
└─ 复杂DUT（>50端口）
    ↓
    项目时间和资源如何？
    ├─ 时间充裕，团队经验丰富 → 异步编程 ✓
    ├─ 时间有限，团队经验一般 → 回调编程
    └─ 快速验证需求 → 顺序编程
```

| 编程方法 | 优点 | 缺点 | 适用场景 | 学习成本 |
|----------|------|------|----------|----------|
| 顺序编程 | 简单直观，易于理解和调试 | 复杂场景下代码冗长，难以维护 | 简单组合电路，简单时序电路 | 低 |
| 回调编程 | 事件驱动，逻辑分离清晰，扩展性好 | 回调嵌套，调试相对困难 | 多接口、多状态的中等复杂度DUT | 中 |
| 异步编程 | 代码简洁，避免回调地狱，并发性好 | 学习曲线陡峭，需要异步编程基础 | 复杂DUT，多协议交互场景 | 高 |

### 选择建议

1. **简单DUT**：推荐顺序编程
2. **中等复杂DUT**：推荐回调编程
3. **复杂DUT**：推荐异步编程

### 编程流程对比

```
顺序编程流程：
设置输入 → 推进时钟 → 检查输出 → 设置下一组输入 → ...

回调编程流程：
注册回调函数 → 推进时钟（自动触发回调） → 回调函数处理逻辑

异步编程流程：
启动协程任务 → await等待事件 → 处理逻辑 → 继续等待或结束
```

## 示例DUT介绍

本文以 `SimpleBus.v` 为例，展示三种编程方法。这是一个简单的ready-valid协议总线模块，具有发送和接收接口，实现了数据的缓冲传输。

### 模块功能说明

**SimpleBus模块特点：**
- 32位数据宽度（可配置）
- Ready-Valid握手协议
- 单级缓冲
- 同步复位

**端口说明：**
- `send_*`：发送端接口（输入数据）
- `recv_*`：接收端接口（输出数据）
- `*_valid`：数据有效信号
- `*_ready`：准备接收信号方法

在基于 picker 的芯片验证用例开发中，根据编程逻辑的不同，常见三种方法：顺序编程、回调编程和异步编程。每种方法各有优缺点和适用场景。

- **顺序编程**：最符合传统软件开发思路，适用于简单时序电路（输入输出逻辑较少）或组合逻辑电路。基本流程是：先设置状态，驱动电路，再检测电路状态。
- **回调编程**：采用事件驱动模型，适合多状态、多接口的场景。
- **异步编程**：对回调模式的进一步简化，适合复杂 DUT 验证，能有效避免“回调地狱”，但入门曲线略高。

本文以 `SimpleBus.v` 为例，分别展示三种用例编程方法。

### SimpleBus Verilog 实现

```verilog
module SimpleBus #(
    parameter DATA_WIDTH = 32
) (
    input wire clk,                          // 时钟信号
    input wire reset,                        // 同步复位信号，高电平有效
    
    // 发送端接口（数据输入）
    input  wire [DATA_WIDTH-1:0] send_data_in,   // 输入数据
    input  wire                  send_valid_in,  // 输入数据有效信号
    output wire                  send_ready_out, // 准备接收输入数据信号
    
    // 接收端接口（数据输出）
    output wire [DATA_WIDTH-1:0] recv_data_out,  // 输出数据
    output wire                  recv_valid_out, // 输出数据有效信号
    input  wire                  recv_ready_in   // 下游准备接收信号
);
    // 内部寄存器
    reg [DATA_WIDTH-1:0] data_reg;           // 数据缓冲寄存器
    reg                  valid_reg;          // 有效标志寄存器
    
    // 握手信号
    wire sender_fire   = send_valid_in && send_ready_out;    // 发送端握手成功
    wire receiver_fire = recv_valid_out && recv_ready_in;    // 接收端握手成功
    
    // 输出信号连接
    assign send_ready_out = !valid_reg || receiver_fire;     // 缓冲区为空或正在输出时可接收
    assign recv_data_out  = data_reg;                        // 输出缓冲的数据
    assign recv_valid_out = valid_reg;                       // 输出有效标志
    
    // 时序逻辑
    always @(posedge clk or posedge reset) begin
        if (reset) begin
            data_reg  <= {DATA_WIDTH{1'b0}};     // 复位时清零数据
            valid_reg <= 1'b0;                   // 复位时清零有效标志
        end else begin
            if (sender_fire) begin
                data_reg  <= send_data_in;        // 锁存输入数据
                valid_reg <= 1'b1;               // 设置有效标志
            end else if (receiver_fire) begin
                valid_reg <= 1'b0;               // 数据被取走，清除有效标志
            end
        end
    end
endmodule
```

**工作原理说明：**
1. 当发送端有数据且模块ready时，数据被锁存到内部寄存器
2. 锁存的数据通过接收端输出，直到下游ready
3. 模块在缓冲区空闲或正在输出数据时可以接收新数据
4. 实现了基本的流水线操作，提高数据传输效率

## 方法一：顺序编程

顺序编程是最符合传统软件开发思路的方法，代码逻辑直观易懂。

### 基本原理

顺序编程按照时间顺序执行操作：
1. 设置输入信号
2. 推进时钟
3. 检查输出结果
4. 重复上述步骤

### 实现示例

```python
import pytest
from SimpleBus import *
import random

@pytest.fixture()
def dut(request):
    """DUT fixture，负责创建和清理DUT实例"""
    bus = DUTSimpleBus()
    yield bus
    bus.Finish()

def api_DUTSimpleBus_reset(dut):
    """顺序逻辑封装的复位操作"""
    dut.InitClock("clk")           # 初始化时钟
    dut.reset.value = 1            # 拉高复位信号
    dut.Step(10)                   # 保持复位10个时钟周期
    dut.reset.value = 0            # 释放复位信号
    dut.Step(10)                   # 等待电路稳定

def api_DUTSimpleBus_send_rec_seq(dut, data, timeout_steps=100):
    """顺序逻辑封装的发送与接收操作
    
    Args:
        dut: DUT实例
        data: 要发送的数据列表
        timeout_steps: 超时时钟周期数
        
    Returns:
        list: 接收到的数据列表
    """
    return_data = []
    in_data = [d for d in data]    # 复制输入数据
    cycle = 0
    
    api_DUTSimpleBus_reset(dut)    # 复位DUT
    
    # 初始化信号
    dut.send_valid_in.value = 0
    dut.recv_ready_in.value = 0
    
    while len(return_data) < len(data) and cycle < timeout_steps:
        # 接收逻辑：检查是否有有效数据输出
        if dut.recv_valid_out.value and dut.recv_ready_in.value:
            return_data.append(dut.recv_data_out.value)
            print(f"Cycle {cycle}: 接收数据 0x{dut.recv_data_out.value:08x}")
        
        # 随机设置接收准备信号，模拟下游模块的随机性
        dut.recv_ready_in.value = random.randint(0, 1)
        
        # 发送逻辑：当模块准备好接收时发送数据
        if dut.send_ready_out.value and len(in_data) > 0:
            data_to_send = in_data.pop(0)
            dut.send_data_in.value = data_to_send
            dut.send_valid_in.value = 1
            print(f"Cycle {cycle}: 发送数据 0x{data_to_send:08x}")
        else:
            dut.send_valid_in.value = 0
        
        dut.Step(1)                # 推进一个时钟周期
        cycle += 1
    
    # 清理发送信号
    dut.send_valid_in.value = 0
    
    if cycle >= timeout_steps:
        raise TimeoutError(f"传输超时，已传输 {len(return_data)}/{len(data)} 个数据")
    
    return return_data

def test_simple_bus_seq_basic(dut):
    """基本顺序测试"""
    data = [0x01, 0x02, 0x03, 0x04]
    received = api_DUTSimpleBus_send_rec_seq(dut, data)
    assert data == received, f"数据不匹配：发送 {data}, 接收 {received}"

def test_simple_bus_seq_large_data(dut):
    """大数据量顺序测试"""
    data = list(range(100))  # 0-99
    received = api_DUTSimpleBus_send_rec_seq(dut, data, timeout_steps=500)
    assert data == received, "大数据量传输失败"

def test_simple_bus_seq_random_data(dut):
    """随机数据顺序测试"""
    import random
    data = [random.randint(0, 0xFFFFFFFF) for _ in range(20)]
    received = api_DUTSimpleBus_send_rec_seq(dut, data, timeout_steps=200)
    assert data == received, "随机数据传输失败"
```

### 顺序编程的优缺点

**优点：**
- 代码逻辑清晰，易于理解和调试
- 符合传统软件开发思维
- 适合简单的测试场景
- 错误定位相对容易

**缺点：**
- 随着DUT复杂度增加，代码复杂度急剧上升
- 难以处理并发操作
- 时序控制精确度有限
- 不适合复杂的协议交互

## 方法二：回调编程

回调编程采用事件驱动模型，将不同的逻辑分离到独立的回调函数中，结构更加清晰。

### 基本原理

回调编程通过注册回调函数来响应时钟边沿事件：
1. 注册上升沿回调函数
2. 每个时钟上升沿自动触发回调
3. 回调函数中处理相应逻辑
4. 主循环只负责推进时钟

### 实现示例

```python
def api_DUTSimpleBus_send_rec_callback(dut, data, timeout_steps=100):
    """基于回调的发送与接收操作封装
    
    Args:
        dut: DUT实例
        data: 要发送的数据列表
        timeout_steps: 超时时钟周期数
        
    Returns:
        list: 接收到的数据列表
    """
    return_data = []
    in_data = [d for d in data]
    send_state = {'active': False, 'data_sent': 0}  # 发送状态
    recv_state = {'data_received': 0}               # 接收状态
    
    api_DUTSimpleBus_reset(dut)
    dut.StepRis.ClearCallBacks()  # 清空之前的上升沿回调
    
    def send_callback(cycle):
        """发送端回调函数"""
        if len(in_data) > 0 and dut.send_ready_out.value:
            # 有数据要发送且模块准备好接收
            data_to_send = in_data.pop(0)
            dut.send_data_in.value = data_to_send
            dut.send_valid_in.value = 1
            send_state['active'] = True
            send_state['data_sent'] += 1
            print(f"Cycle {cycle}: 发送数据 0x{data_to_send:08x} ({send_state['data_sent']}/{len(data)})")
        elif send_state['active'] and dut.send_ready_out.value:
            # 数据已被接收，清除发送信号
            dut.send_valid_in.value = 0
            send_state['active'] = False
        elif not dut.send_ready_out.value:
            # 模块未准备好，保持当前状态
            pass
    
    def recv_callback(cycle):
        """接收端回调函数"""
        # 随机设置接收准备信号，模拟下游模块行为
        dut.recv_ready_in.value = random.choice([0, 1]) if random.random() > 0.2 else 1
        
        # 检查是否有有效数据输出
        if dut.recv_valid_out.value and dut.recv_ready_in.value:
            received_data = dut.recv_data_out.value
            return_data.append(received_data)
            recv_state['data_received'] += 1
            print(f"Cycle {cycle}: 接收数据 0x{received_data:08x} ({recv_state['data_received']}/{len(data)})")
    
    def status_callback(cycle):
        """状态监控回调函数"""
        if cycle % 50 == 0:  # 每50个周期打印一次状态
            print(f"Cycle {cycle}: 发送进度 {send_state['data_sent']}/{len(data)}, "
                  f"接收进度 {recv_state['data_received']}/{len(data)}")
    
    # 注册回调函数
    dut.StepRis(send_callback)
    dut.StepRis(recv_callback)
    dut.StepRis(status_callback)
    
    # 初始化信号
    dut.send_valid_in.value = 0
    dut.recv_ready_in.value = 0
    
    # 主循环：只负责推进时钟
    cycle = 0
    while len(return_data) < len(data) and cycle < timeout_steps:
        dut.Step(1)
        cycle += 1
    
    # 清理信号
    dut.send_valid_in.value = 0
    dut.recv_ready_in.value = 0
    
    if cycle >= timeout_steps:
        raise TimeoutError(f"传输超时，已传输 {len(return_data)}/{len(data)} 个数据")
    
    return return_data

def test_simple_bus_callback_basic(dut):
    """基本回调测试"""
    data = [0x01, 0x02, 0x03, 0x04]
    received = api_DUTSimpleBus_send_rec_callback(dut, data)
    assert data == received, f"数据不匹配：发送 {data}, 接收 {received}"

def test_simple_bus_callback_stress(dut):
    """回调压力测试"""
    data = list(range(0, 1000, 7))  # 0, 7, 14, ..., 994
    received = api_DUTSimpleBus_send_rec_callback(dut, data, timeout_steps=2000)
    assert data == received, "压力测试失败"

# 高级回调示例：多状态机管理
def api_DUTSimpleBus_advanced_callback(dut, data_streams, timeout_steps=500):
    """高级回调示例：处理多个数据流
    
    Args:
        dut: DUT实例
        data_streams: 数据流字典，{stream_id: data_list}
        timeout_steps: 超时时钟周期数
    """
    results = {stream_id: [] for stream_id in data_streams}
    stream_queues = {stream_id: list(data) for stream_id, data in data_streams.items()}
    current_stream = 0
    stream_ids = list(data_streams.keys())
    
    api_DUTSimpleBus_reset(dut)
    dut.StepRis.ClearCallBacks()
    
    def stream_scheduler_callback(cycle):
        """数据流调度回调"""
        nonlocal current_stream
        if cycle % 10 == 0:  # 每10个周期切换数据流
            current_stream = (current_stream + 1) % len(stream_ids)
    
    def adaptive_send_callback(cycle):
        """自适应发送回调"""
        current_stream_id = stream_ids[current_stream]
        current_queue = stream_queues[current_stream_id]
        
        if current_queue and dut.send_ready_out.value:
            data_to_send = current_queue.pop(0)
            dut.send_data_in.value = data_to_send
            dut.send_valid_in.value = 1
            print(f"Cycle {cycle}: Stream {current_stream_id} 发送 0x{data_to_send:08x}")
        else:
            dut.send_valid_in.value = 0
    
    def intelligent_recv_callback(cycle):
        """智能接收回调"""
        # 根据当前负载动态调整接收准备信号
        total_pending = sum(len(queue) for queue in stream_queues.values())
        ready_probability = 0.9 if total_pending > 10 else 0.7
        dut.recv_ready_in.value = 1 if random.random() < ready_probability else 0
        
        if dut.recv_valid_out.value and dut.recv_ready_in.value:
            received_data = dut.recv_data_out.value
            # 简单地按顺序分配给当前流（实际应用中需要更复杂的逻辑）
            stream_id = stream_ids[current_stream]
            results[stream_id].append(received_data)
            print(f"Cycle {cycle}: Stream {stream_id} 接收 0x{received_data:08x}")
    
    # 注册回调
    dut.StepRis(stream_scheduler_callback)
    dut.StepRis(adaptive_send_callback)
    dut.StepRis(intelligent_recv_callback)
    
    # 执行测试
    cycle = 0
    total_expected = sum(len(data) for data in data_streams.values())
    total_received = 0
    
    while total_received < total_expected and cycle < timeout_steps:
        dut.Step(1)
        cycle += 1
        total_received = sum(len(result) for result in results.values())
    
    return results
```

### 回调编程的优缺点

**优点：**
- 逻辑分离清晰，每个回调处理特定功能
- 事件驱动，响应及时
- 扩展性好，容易添加新功能
- 适合多接口、多状态的场景

**缺点：**
- 调试相对困难，需要在多个回调间跳转
- 回调间的数据共享需要谨慎处理
- 复杂场景下容易出现"回调地狱"
- 时序依赖关系不够直观

### 异步编程

对于复杂 DUT，回调模式容易出现“回调地狱”，不利于用例维护。异步编程模型可以有效解决这一问题。具体如下：

```python
import asyncio

async def sender(dut, data_to_send):
    for data in data_to_send:        
        await dut.AStep(1) # 等待一个时钟周期
        if not dut.send_ready_out.value == 1:
            dut.send_valid_in.value = 0 # 如果发送不准备好，则不发送数据
            continue
        dut.send_data_in.value = data
        dut.send_valid_in.value = 1     # 发送数据
    # 发送完后清零
    await dut.AStep(1)
    dut.send_valid_in.value = 0

async def receiver(dut, num_items_to_receive):
    received_data = []
    while len(received_data) < num_items_to_receive:
        dut.recv_ready_in.value = 1 # allways ready to receive
        await dut.AStep(1)  # 等待一个时钟周期
        if dut.recv_valid_out.value:
            received_data.append(dut.recv_data_out.value)
            print(f"recv {dut.recv_data_out.value} at cycle {dut.xclock.clk}")
    return received_data

async def api_DUTSimpleBus_send_rec_async(dut, data, timeout_steps=1000):
    api_DUTSimpleBus_reset(dut)                                       # reset dut
    # 创建并启动发送和接收两个并发任务
    receiver_task = asyncio.create_task(receiver(dut, len(data)))
    asyncio.create_task(sender(dut, data))
    while not receiver_task.done() and timeout_steps > 0:
        dut.Step(1) # 推进电路
        await asyncio.sleep(0) # 让出控制权，允许其他协程运行
        timeout_steps -= 1
    if timeout_steps <= 0:
        raise TimeoutError("Timeout while waiting for receiver to finish")
    return receiver_task.result()  # 返回接收任务的结果

@pytest.mark.asyncio
async def test_simple_bus_async(dut):
    data = [0x01, 0x02, 0x03, 0x04]
    received_data = await api_DUTSimpleBus_send_rec_async(dut, data)
    assert data == received_data
```

异步编程模式能有效应对复杂 DUT 验证场景，避免回调嵌套，提升用例可维护性。对于简单模块，异步模式的编程成本略高，但对于复杂场景优势明显。

对于更复杂的DUT验证可以参考toffee框架的使用，相关文档和地址如下：

- [toffee](https://github.com/XS-MLVP/toffee) 基于picker和异步编程的芯片验证框架
- [toffee-test](https://github.com/XS-MLVP/toffee-test) toffee与pytest的结合
- [picker](https://github.com/XS-MLVP/picker) 基于多语言大芯片验证工具
- [picker验证入门](https://open-verify.cc/mlvp/docs/) 如何使用picker进行芯片验证
- [toffee doc](https://pytoffee.readthedocs.io/zh-cn/latest/) toffee使用帮助

## 总结与建议

### 方法选择决策树

```
DUT复杂度评估
├── 简单
│   └── 顺序编程 ✓
├── 中等
│   ├── 团队熟悉回调编程 → 回调编程 ✓
│   └── 团队不熟悉回调编程 → 顺序编程
└── 复杂
    ├── 团队有异步编程经验 → 异步编程 ✓
    ├── 团队无异步编程经验 → 回调编程
    └── 快速原型验证 → 顺序编程
```

### 最佳实践建议

1. **从简单开始**：优先使用顺序编程验证基本功能
2. **逐步演进**：根据需求复杂度逐步采用更高级的方法
3. **统一标准**：团队内部保持编程方法的一致性
4. **文档完善**：详细记录API设计和使用方法
5. **持续改进**：根据实际使用效果调整和优化方法选择

### 性能优化技巧

- **合理设置超时**：避免死锁，但不要过短影响正常传输
- **适度并发**：过度并发可能增加复杂度而非性能
- **错误处理**：完善的异常处理机制提高测试可靠性
- **日志记录**：详细的日志有助于问题定位和性能分析
