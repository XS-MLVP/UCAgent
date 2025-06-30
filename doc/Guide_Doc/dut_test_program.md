## 测试用例编程方法

在基于 picker 的芯片验证用例开发中，根据编程逻辑的不同，常见三种方法：顺序编程、回调编程和异步编程。每种方法各有优缺点和适用场景。

- **顺序编程**：最符合传统软件开发思路，适用于简单时序电路（输入输出逻辑较少）或组合逻辑电路。基本流程是：先设置状态，驱动电路，再检测电路状态。
- **回调编程**：采用事件驱动模型，适合多状态、多接口的场景。
- **异步编程**：对回调模式的进一步简化，适合复杂 DUT 验证，能有效避免“回调地狱”，但入门曲线略高。

本文以 `SimpleBus.v` 为例，分别展示三种用例编程方法。

```verilog
module SimpleBus #(
    parameter DATA_WIDTH = 32
) (
    input wire clk,
    input wire reset,
    input  wire [DATA_WIDTH-1:0] send_data_in,
    input  wire                  send_valid_in,
    output wire                  send_ready_out,
    output wire [DATA_WIDTH-1:0] recv_data_out,
    output wire                  recv_valid_out,
    input  wire                  recv_ready_in
);
    reg [DATA_WIDTH-1:0] data_reg;
    reg                  valid_reg;
    wire sender_fire   = send_valid_in && send_ready_out;
    wire receiver_fire = recv_valid_out && recv_ready_in;
    assign send_ready_out = !valid_reg || receiver_fire;
    assign recv_data_out  = data_reg;
    assign recv_valid_out = valid_reg;
    always @(posedge clk or posedge reset) begin
        if (reset) begin
            data_reg  <= 0;
            valid_reg <= 1'b0;
        end else begin
            if (sender_fire) begin
                data_reg  <= send_data_in;
                valid_reg <= 1'b1;
            end else if (receiver_fire) begin
                valid_reg <= 1'b0;
            end
        end
    end
endmodule
```

### 顺序编程

顺序模式的验证代码如下：

```python
import pytest
from SimpleBus import *
import random

@pytest.fixture()
def dut(request):
    bus = DUTSimpleBus()
    yield bus
    bus.Finish()

def api_DUTSimpleBus_reset(dut):
    """顺序逻辑封装的 reset 操作"""
    dut.InitClock("clk")
    dut.reset.value = 1
    dut.xclock.Step(10)
    dut.reset.value = 0
    dut.xclock.Step(10)

def api_DUTSimpleBus_send_rec_seq(dut, data, timeout_steps=100):
    """顺序逻辑封装的发送与接收操作"""
    return_data = []
    in_data = [d for d in data]
    api_DUTSimpleBus_reset(dut)  # 复位 DUT
    cycle = 0
    while True:
        # 接收逻辑
        if dut.recv_valid_out.value and dut.recv_ready_in.value:
            return_data.append(dut.recv_data_out.value)
        dut.recv_ready_in.value = random.randint(0, 1)  # 随机设置 recv 是否 ready
        # 发送逻辑
        if dut.send_ready_out.value:
            if len(in_data) > 0:
                dut.send_data_in.value = in_data.pop(0)
                dut.send_valid_in.value = 1
            else:
                dut.send_valid_in.value = 0
        if len(return_data) == len(data):
            break
        dut.Step(1)
        cycle += 1
    return return_data

def test_simple_bus_seq(dut):
    data = [0x01, 0x02, 0x03, 0x04]
    assert data == api_DUTSimpleBus_send_rec_seq(dut, data)
```

上述代码中，`api_DUTSimpleBus_send_rec_seq` 以顺序方式实现了数据的发送和接收。随着 DUT 端口和状态的增加，顺序模式的复杂度会迅速上升，导致用例难以维护。

### 回调编程

回调模式下，发送和接收逻辑被拆分为独立的回调函数，结构更清晰：

```python
def api_DUTSimpleBus_send_rec_callback(dut, data, timeout_steps=100):
    """基于回调的发送与接收操作封装"""
    return_data = []
    in_data = [d for d in data]
    api_DUTSimpleBus_reset(dut)
    dut.xclock.ClearRisCallBacks()  # 清空之前的上升沿回调
    def send_data(cycle):
        if dut.send_ready_out.value:
            if len(in_data) > 0:
                dut.send_data_in.value = in_data.pop(0)
                dut.send_valid_in.value = 1
            else:
                dut.send_valid_in.value = 0
    def recv_data(cycle):
        if dut.recv_valid_out.value and dut.recv_ready_in.value:
            return_data.append(dut.recv_data_out.value)
        dut.recv_ready_in.value = random.randint(0, 1)
    dut.StepRis(send_data)
    dut.StepRis(recv_data)
    s = timeout_steps
    while s >= 0:
        dut.Step(1)
        if len(return_data) == len(data):
            break
        s -= 1
    return return_data

def test_simple_bus_callback(dut):
    data = [0x01, 0x02, 0x03, 0x04]
    assert data == api_DUTSimpleBus_send_rec_callback(dut, data)
```

通过设置上升沿回调函数，发送和接收逻辑互不干扰，代码结构更清晰，便于扩展。

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
