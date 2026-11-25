
# 环境、oracle 与场景实现

## 实现路径

1. 对齐实际端口与合同：缺字段报错，不能用默认零补齐。宽度被裁剪时记录语义来源、
   消费者需要、关闭条件和承接位置，不把端口宽度改写为规格。
2. 由 env 绑定实际 DUT，封装 reset 与事务 API；tests 不直接驱动/轮询物理引脚。
   根 conftest.py 负责唯一 fixture 注册，释放顺序为组件/Execution、Backend、DUT。
3. 时序环境使用一个 `Execution(XCommClockBackend(dut.GetXClock()))`。明确实际时钟
   引脚和采样沿；Execution 活动期间只等待 Trigger，不额外调用 dut.Step 或启动第二
   套时钟。无时钟 DUT 由环境封装合法求值与稳定观察，不虚构时钟合同。
4. 优先复用 Toffee 的 Driver、SamplingMonitor、Scoreboard、Agent 和覆盖组；只有
   通用能力不足才实现自定义组件，说明差异。正常和异常路径都必须释放资源。
5. 从独立模型或性质构造 expected，不读取实际输出来生成 expected，也不照抄 RTL
   同一算法。比较 payload、身份、有效 mask、时序及禁止副作用，不只检查 valid。
6. 按身份分别记录 offered、accepted、completed、cancelled 和 outstanding。同拍
   先抓取所有相关通道快照，再更新状态；不能因等待一路响应而漏掉其他 fire。

## 直接可用的 Toffee 接口

| 目的 | API 与注意事项 |
|---|---|
| 同步等待输入接受 | `await driver.send(request)`；接受不等于响应完成 |
| 异步流水提交 | `AsyncDriver.submit(request)` 或 `scoreboard.submit(request)` 返回句柄；调用方定义响应义务 |
| 快照观察 | `SamplingMonitor(trigger, capture=...)`；capture 同步保存不可变值，不能返回稍后变化的 DUT 对象 |
| 直接比较 | `Scoreboard("name").check(expected=..., actual=...)` |
| 关联与结束 | `Scoreboard.bind(...)` 显式指定时钟、匹配方式和响应预算；`finish(timeout_cycles=..., observe_cycles=...)` 严格结束 |
| 功能覆盖 | `CoverGroupDef` / `CoverPointDef` / `CrossDef` / `Bin`；在真实观察路径 sample，或绑定到 Execution |
| 正常释放 | Monitor/Scoreboard 的关闭不代替有界完成检查；不能通过关闭时清空缓存隐藏未完成事务 |

一个 Monitor 的响应流只由一个消费者管理。检查和覆盖使用同一份快照或明确的事务
返回值，不能分别 recv 互相抢数据。输入、响应与模型更新所用相位必须一致。

## 原生 DUT 与 seed

新工程的 native_dut fixture 显式调用 `toffee_register_dut(dut)`，并把 seed 放入原生
构造参数。已有工程可沿用直接返回 DUT、带 dut 的环境或 `_instances` 工厂的 fixture；
会提前释放的工厂对象仍需显式登记。每个真实用例必须能关联到同次运行的 DUT 构建，
不能用另一个自检的原生覆盖冒充。

`RunToffee(seed=...)` 传递请求种子；已有 fixture 还需核对它确实使用该值。收据里有
requested_seed 不证明原生构造器实际采用了该 seed，不据此声称多 seed 已生效。
直接 `toffee run` 时模板 seed 默认 1。

## 完整用例示例

以下是已经完成的场景文件形状；env 的方法和 Response 字段必须由本次真实合同
定义，不是插件预设的 DUT API。将其替换为当前 DUT 的事务，不另建演示设计。

```python
"""Check two accepted entries against the independent input history."""

import pytest


@pytest.mark.scenario("Q-BACKPRESSURE")
async def test_order_after_backpressure(env):
    """Exercise a legal pause, compare each response and settle all obligations."""
    await env.reset()
    values = [0x12, 0xA7]
    for uid, value in enumerate(values):
        await env.offer(uid=uid, payload=value)
    await env.backpressure(cycles=3)
    for uid, expected in enumerate(values):
        response = await env.receive(timeout_cycles=20)
        assert response.uid == uid
        assert response.payload == expected
    await env.finish(timeout_cycles=40, observe_cycles=2)
```

不能用“等到结果等于 expected 才读”的轮询选择有利样本；应在合同规定时刻读取首个
响应。`finish` 不得自动补响应、复位或发出尚未授权的计划来清债。

## 自检与验收

给关键 checker 做合法对照和单一错误对照：错字段、错身份、丢响应、重复响应、零
接受或接受后不完成。错误对照应在预定检查点被识别，不能被 setup error 偶然挡住。
自检使用 `@pytest.mark.selftest`，其结果不计入 DUT 功能覆盖；模块实现自检归其 tests，
真正共享自检归 shared/tests。
分阶段验收另按测试目标加标记：环境自检 `@pytest.mark.envcheck`，独立模型自检
`@pytest.mark.modelcheck`，上游替身自检 `@pytest.mark.mockcheck`；真实 DUT 基础事务
API 用例 `@pytest.mark.api`，约束随机场景 `@pytest.mark.random` 并保留实际 seed 接线。
这些标记只能分类真实执行节点，不能自动证明已检查语义或原生构造器用了请求 seed。
模块导入时或整个会话共享的辅助覆盖组还须显式 `capture=False`，不能仅靠用例标记
排除已经创建的全局组。核对真实功能报告中没有混入这些自检组。

删除初始占位 `assert False, "Not implemented"`。先定向 `RunToffee(targets=[...])`，
再用 `RunToffee()` 完整选择回归；编译、目录或静态审计通过不代替真实仿真和比较。
