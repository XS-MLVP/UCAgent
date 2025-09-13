
### 双端口栈

双端口栈是一个拥有两个端口的栈，每个端口都支持push和pop操作。与传统单端口栈相比，双端口栈允许同时进行数据的读写操作，在例如多线程并发读写等场景下，双端口栈能够提供更好的性能。

除了时钟信号(clk)和复位信号(rst)之外，还包含了两个端口的输入输出信号，它们拥有相同的接口定义。每个端口的信号含义如下：

请求端口（in）
- in_valid 输入数据有效信号
- in_ready 输入数据准备好信号
- in_data 输入数据
- in_cmd 输入命令 （0:PUSH, 1:POP）

响应端口（out）
- out_valid 输出数据有效信号
- out_ready 输出数据准备好信号
- out_data 输出数据
- out_cmd 输出命令 （2:PUSH_OKAY, 3:POP_OKAY）

当我们想通过一个端口对栈进行一次操作时，首先需要将需要的数据和命令写入到输入端口，然后等待输出端口返回结果。

具体地，如果我们想对栈进行一次 PUSH 操作。首先我们应该将需要 PUSH 的数据写入到 in_data 中，然后将 in_cmd 设置为 0，表示 PUSH 操作，并将 in_valid 置为 1，表示输入数据有效。接着，我们需要等待 in_ready 为 1，保证数据已经正确的被接收，此时 PUSH 请求已经被正确发送。

命令发送成功后，我们需要在响应端口等待栈的响应信息。当 out_valid 为 1 时，表示栈已经完成了对应的操作，此时我们可以从 out_data 中读取栈的返回数据（POP 操作的返回数据将会放置于此），从 out_cmd 中读取栈的返回命令。当读取到数据后，需要将 out_ready 置为 1，以通知栈正确接收到了返回信息。

如果两个端口的请求同时有效时，栈将会优先处理端口 0 的请求。

### 验证目标

对双端口栈的压栈，和弹栈功能进行验证，考虑边界条件，例如栈满等情况。不要验证其他功能，例如波形，接口等。

请基于文件`DualPort/DualPort_env.py`中实现的`DualPortEnv`，编写API和测试用例 (如果有错误，需要你修正)，如果功能不能满足你的需要，你可以增加新的接口或Env。

可通过如下方式导入：

```python

from DualPort.DualPort_env import DualPortEnv

@pytest.fixture()
def env(dut):
    return DualPortEnv(dut)

def test_example(env):
    dut = env.dut
    ...
```
