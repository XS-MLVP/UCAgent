
# RTL 静态候选与动态复核

## 当前阶段

调用 `UTProject(action="inspect")` 确认本轮每份 RTL 的路径与哈希。逐文件阅读真实源，
对照 `Guide_Doc/ut-contracts.md` 中的已确认合同、层级与合法输入，检查控制、位宽、
状态与并发。疑点只是候选，不能由源码表象直接推断真实可达缺陷。

在 `docs/reviews/<DUT>-static-review.md` 保留一份 `kind: static_review` 的
typed YAML；`sources` 一项一份已盘点 RTL，`candidates` 可以为空数组。静态候选
须有唯一 ID、已盘点的源码路径、真实物理行号和可证伪假设。动态复核逐项填状态、
当前执行依据或缺少什么及下一实验；缺原生运行或独立判据保持 `unconfirmed`。

## 完整工件示例

下列哈希只是格式占位，落地时替换为本次实际文件字节的 SHA-256；不要抄写示例的判断。

````markdown

# Queue 静态候选审查

## 逐源与待确认事项

输入时序与输出有效沿由当前规格定义；静态疑点待合法事务验证。

```yaml
kind: static_review
dut: Queue
sources:
  - path: inputs/queue.sv
    sha256: <current-source-sha256>
    review: 已逐项检查复位、入队、出队和背压状态路径；候选见下方
candidates:
  - id: S-RESET-1
    source: inputs/queue.sv
    line: 42
    hypothesis: 在途条目的复位取消条件可能没有覆盖全部输出状态
    status: unconfirmed
    evidence: 接口负责人尚未确认复位边沿；未运行可区分的 DUT 对照
```

## 后续实验

先确认复位语义，再构造有在途条目的合法请求与邻近对照。
````

允许 `unconfirmed`、`ruled-out`、`out-of-domain` 和具有实际根因证据的 `rtl`。
`out-of-domain` 须说明承接范围和独立依据；`rtl` 须在该候选中增加已确认的
`requirement`、当前 `run`、失败 `nodeids`，以及 `Guide_Doc/ut-waveform.md` 定义的
`waveform_evidence`。纯文本备注不生成用例或波形；证据未齐保留原始 FAIL 与未确认状态，
不能据此宣称完成要求根因确认的任务。
