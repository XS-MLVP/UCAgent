
# Chisel 源码验证

本阶段确认当前 Chisel 源码与已冻结 architecture、Python 可执行规格和共用测试保持一致。
先调用 Check 获取当前诊断；修复诊断指向的 Chisel 源码或共用测试，再以 RunTestCases 验证
Python backend，最后调用 Check 复验 Chisel backend。所有行为期望必须来自同一套测试，不能
为某个 backend 复制 expected、弱化断言、skip 或 xfail。

只维护 CurrentTips 中列出的 `.scala` 源码、共用 Python 测试和公开验证报告。源码遵守
`Guide_Doc/coding_standard_chisel.md`，接口、时钟、reset、latency 和 handshake 必须与
architecture 完全一致。编译、验证和报告收集均由 Check/Complete 执行，不直接运行构建命令。

## 修复顺序

1. 对照诊断中的 artifact 和 location 定位当前 Chisel 源码或测试。
2. 对照 Spec、architecture 和 Python reference 确认期望行为。
3. 修正参数、端口、位宽、signedness、reset、时序或 transaction 实现。
4. 使用 RunTestCases 运行受影响节点，确认 Python backend 的共用合同仍通过。
5. 调用 Check 验证 Chisel backend；继续修正最早的具体失败。
6. 所有功能和源码证据通过后调用 Complete。

## 完整源码示例

下面是一个完整的、仅用于说明本阶段公开源码形态的组合模块。真实设计必须使用当前
architecture 中的模块名、参数和端口。

```scala
/** Saturating unsigned adder with an explicit overflow result. */
import chisel3._

class SaturatingAdder(val width: Int = 8) extends RawModule {
  require(width >= 2 && width <= 64)

  val a_i = IO(Input(UInt(width.W)))
  val b_i = IO(Input(UInt(width.W)))
  val sum_o = IO(Output(UInt(width.W)))
  val overflow_o = IO(Output(Bool()))

  val extended = a_i +& b_i
  overflow_o := extended(width)
  sum_o := Mux(overflow_o, Fill(width, 1.U(1.W)), extended(width - 1, 0))
}
```

## 完成标准

- 当前 Chisel 源码可被 Check 接受并与 architecture 一致。
- Python 和 Chisel backend 使用同一套共用测试且全部通过。
- 没有 backend 专用 expected、skip、xfail 或手写验证证据。
- `{OUT}/{DUT}_chisel_source_validation.md` 由通过的验证过程生成并绑定当前源码哈希。
