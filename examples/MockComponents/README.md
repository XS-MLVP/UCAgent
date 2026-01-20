# Mock依赖组件 (Mock Component)

在数字电路领域，有很大一部分组件功能不是独立的，需要依赖多个组件才能工作，例如Cache，总线等。
在验证这些模块时，需要给DUT接上这些依赖才能工作，而这些依赖模块有些还没有实现，或者为了隔离测试，需要使用模拟的组件。
因此需要在测试时，对这些依赖组件进行模拟，我们称为Mock组件。

## 启用Mock组件

默认配置下，UCAgent关闭了Mock组件的相关步骤。
当您的DUT（Device Under Test）需要依赖外部组件时，可以通过以下方式开启Mock组件生成与验证流程：

使用环境变量 `IGNORE_MOCK_COMPONENT=false`。

### 启用后的流程变化

启用Mock组件后，UCAgent的执行流程会增加以下三个阶段（Stage）：

1. **Mock组件设计与实现 (mock_design_and_implementation)**
   - **目标**: 分析DUT的上下游依赖，设计并实现Mock组件。
   - **输出**: `{OUT}/tests/{DUT}_mock_<Name>.py` (例如 `Sbuffer_mock_basic.py`)。
   - **内容**: 包含Mock组件的类定义，通常实现了`on_clock_edge`方法来驱动信号。

2. **Mock Fixture实现 (mock_fixture_implementation)**
   - **目标**: 在测试框架中注册Mock组件，使其可以在测试用例中被调用，并处理Mock组件的初始化。
   - **输出**: 更新 `{OUT}/tests/{DUT}_api.py`。
   - **内容**: 实现 `mock_dut` fixture。

3. **Mock组件功能测试 (mock_functional_test)**
   - **目标**: 验证Mock组件本身的功能正确性（确保模拟器本身是对的）。
   - **输出**: `{OUT}/tests/test_{DUT}_mock_<Name>.py`。
   - **内容**: 针对Mock组件的单元测试。这些测试用例与DUT的功能测试隔离，专注于Mock组件的行为验证。

## 示例：Sbuffer

Sbuffer是一个不能独立存在的模块，它依赖上下游的总线握手信号，因此需要Mock组件来模拟上游发送数据和下游接收数据。

### 运行示例

在仓库主目录运行以下命令：

```bash
# 确保在运行前安装了依赖环境
# IGNORE_MOCK_COMPONENT=false 环境变量用于启用Mock阶段
ENABLE_LLM_FAIL_SUGGESTION=true ENABLE_LLM_PASS_SUGGESTION=true PYTEST_ADDOPTS="-n auto" \
IGNORE_MOCK_COMPONENT=false make mcp_Sbuffer BBV=true ARGS="--backend=qwen --loop --gen-instruct-file=QWEN.md"
```

注：请参考[examples/LLMCheck/README.md](/examples/LLMCheck/README.md)配置LLMcheck。设置qwen的mcp超时时间到一个比较大的值，例如10分钟。


参数解释：
- `ENABLE_LLM_FAIL_SUGGESTION=true`：启用Check Fail时的LLM检查
- `ENABLE_LLM_PASS_SUGGESTION=true`：启用Complete True时的LLM检查
- `PYTEST_ADDOPTS="-n auto"`: 启用多核运行pytest（可以把auto改值具体的核心数）
- `IGNORE_MOCK_COMPONENT=false`：启用Mock stage （Stage list中会多出3个阶段）
- `BBV=true`: 启用黑盒验证，清空RTL文件内容（RTL代码行数太长时建议开启）
- `ARGS="--backend=qwen --loop --gen-instruct-file=QWEN.md"`：设置UCagent参数，选用qwen作为后端执行，开启验证 loop并生成Qwen指导文件


### 预期产物

运行成功后，你可以在 `output/Sbuffer/tests/` 目录下找到生成的Mock相关代码（具体文件名取决于LLM生成的名称）：

- **Mock实现**: 类似于 `Sbuffer_mock_basic.py`，包含 `MockUpstream` / `MockDownstream` 等类。
- **Fixture封装**: `Sbuffer_api.py` 中增加了 `mock_dut` fixture。
- **Mock自测**: 类似于 `test_Sbuffer_mock_basic.py`，包含对Mock组件的测试用例。

## 验证指南

- **Mock组件实现**: Mock组件应尽量简单，只模拟必要的接口行为，避免包含复杂的业务逻辑，以减少Mock本身引入错误的风险。
- **驱动方式**: Mock组件主要通过 `on_clock_edge` 方法在时钟沿对DUT信号进行驱动或采样。
- **自测要求**: Mock组件本身的正确性至关重要，因此必须通过Mock功能测试阶段（Mock Functional Test）的验证。在这一步，我们只测试Mock组件本身，不涉及DUT的功能验证。
- **人机协同**: 对于复杂的Mock环境（如需模拟复杂协议或大规模状态机），建议采用人机协同模式。可先由LLM生成Mock组件框架及基础行为，再由人工介入完善关键逻辑与时序细节，以确保验证环境的高可靠性。

