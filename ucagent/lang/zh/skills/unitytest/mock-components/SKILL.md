---
name: mock-components
description: Mock组件设计、mock_dut fixture实现和Mock独立单元测试阶段专属技能；用于严格区分Mock测试的mock_dut参数与普通DUT测试的env/ref_model参数契约
---

# Mock组件实现与测试

## 先识别当前子阶段

根据当前stage名称只执行对应工作：

| stage | 工作范围 |
|---|---|
| `mock_design_and_implementation` | 设计并实现`{DUT}_mock_<Name>.py`中的Mock类 |
| `mock_fixture_implementation` | 在`{DUT}_api.py`实现`mock_dut` fixture |
| `test_mock_components_in_batch` | 为当前批次Mock编写独立单元测试并修复到全部Pass |

不要跨阶段提前实现无关内容。

## 不可混用的三类对象

| 对象 | 用途 | 测试签名 |
|---|---|---|
| `env` | 驱动真实DUT的功能测试 | `test_xxx(env[, ref_model])` |
| `ref_model` | 为真实DUT测试独立计算预期 | 普通DUT测试模板中存在时作为第二个参数 |
| `mock_dut` | 不运行RTL的Mock组件单元测试 | `test_api_{DUT}_mock_xxx(mock_dut)` |

普通DUT测试是否包含`ref_model`不改变Mock单元测试签名。Mock测试不接收`env`或`ref_model`。反过来，普通DUT测试也不能把`env`替换为`mock_dut`。

## Mock组件实现

1. 只为与DUT引脚交互的真实上下游依赖建立Mock；直接功能输入由API驱动，不建立Mock。
2. 文件命名为`{OUT}/tests/{DUT}_mock_<ComponentName>.py`，类名以`Mock`开头。
3. Mock绑定真实DUT对象或引脚Bundle，不绑定`env`。
4. 实现`on_clock_edge(self, cycles)`，通过`dut.StepRis`或`dut.StepFal`注册；不要改变无关回调顺序。
5. 只模拟协议所需行为，保持状态、队列、延迟和背压语义明确。
6. 对非法输入和内部不变量使用有意义的assert；不要用assert制造预期失败。

## mock_dut fixture

在`{OUT}/tests/{DUT}_api.py`中使用唯一规范实现：

```python
@pytest.fixture(scope="function")
def mock_dut():
    return ucagent.get_mock_dut_from(DUT{DUT})
```

- scope必须为`function`。
- 每个测试获得全新实例。
- 不要让fixture创建真实RTL DUT、`env`或参考模型。
- 不要增加兼容别名或第二套Mock fixture。

## Mock独立单元测试

```python
from {DUT}_api import *
from {DUT}_mock_Memory import MockMemory


def test_api_{DUT}_mock_memory_response(mock_dut):
    mock = MockMemory()
    mock.bind(mock_dut)

    mock_dut.req_valid.value = 1
    mock_dut.req_addr.value = 0x100
    mock_dut.Step(1)

    assert mock_dut.req_ready.value == 1
```

测试要求：

- 函数式编写，名称以`test_api_{DUT}_mock_`开头，第一个且通常唯一的fixture参数为`mock_dut`。
- 通过`.value`读写XPin；禁止直接覆盖pin对象。
- 先实例化并`bind(mock_dut)`，再用`mock_dut.Step()`触发回调。
- 覆盖基本交互、配置延迟、背压、复位、队列/状态清理和可选错误注入。
- 不调用`mark_function`，不访问`fc_cover`，不生成DUT功能覆盖率。
- 所有Mock测试必须Pass。发现问题时修复Mock、fixture或测试，不创建DUT Bug，不调用WaveInfo，不写Bug文档。

## 与env集成的边界

Mock单元测试通过后，后续`env_fixture_implementation`才把Mock实例集成到真实DUT环境。集成时仍需保证：

- 普通DUT测试只通过`env`和API驱动DUT。
- Mock只模拟外部依赖，不替代DUT待验证功能。
- Mock的响应不能硬编码成当前断言期望，也不能掩盖DUT输出错误。
- Mock或回调问题导致的Fail属于验证基础设施问题，必须修复到Pass。

## 完成条件

- 当前stage要求的文件存在且命名正确。
- Mock类、`on_clock_edge(self, cycles)`和`mock_dut` fixture通过对应Checker。
- 当前批次每个Mock都有独立测试，所有测试Pass。
- 没有混用`env`、`ref_model`和`mock_dut`。
- 没有DUT覆盖标记、WaveInfo调用或动态Bug记录。
