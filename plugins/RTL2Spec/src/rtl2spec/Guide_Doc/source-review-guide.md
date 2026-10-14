
# 源码语义复核

本阶段逐项核对当前设计文档与源码。不能用文档中的结论给同一结论作证。对每个 P-* 重新定位对应实现，发现问题时同时修正行为、Testplan、Coverage 和场景。

## 七类复核项

- acceptance：逐个接口列出实际接受和消费事件；入口、目标与响应缓冲之间不能混用接受边界。
- storage_backpressure：占用、满空、释放条件、同周期入出队与背压期间的有效性/载荷保持。
- bypass：空状态或同周期请求/响应旁路；没有所有者记录是否真的会屏蔽响应。
- configuration：配置作用于哪个版本和分支；控制是锁存还是实时输入，等待期间是否需要稳定。
- reset_recovery：复位/取消时哪些状态清除，是否需要外部隔离旧事务，ready 是否真的要求为零。
- assumptions：区分 RTL 保证与生产者稳定、合法响应、互斥、公平性等环境前提。
- verification_plan：CK 触发及预期与行为一致；每个覆盖分箱的采样事件确实可达，等待或空选择不要求完成握手。

## 记录流程

1. 修订文档和质量报告后执行 metadata/generic_metadata，再运行 review/generic_review；工具在 `{OUT}/semantic_review.json` 创建绑定当前证据的复核问题。
2. 每个行为的七个 checks 均填写 status、conclusion 和 evidence。status 为 reviewed、not_applicable 或 open；不适用仍需说明源码理由。每项至少引用一个捕获 RTL 或已登记相关源文件的真实非空范围，每段不超过 100 行。
3. open 项还须包含 open_id，并在设计文档定义对应 OPEN-* 及关闭条件。verification_plan 的 ck_ids 必须引用 Testplan 中关联当前 P-* 的检查；coverage_ids 必须来自所选检查关联的 COV-*。reviewed 时两者都不能空；没有适用覆盖项时可用 not_applicable 并说明理由，不制造覆盖项。open_id 必须在开放项表定义且状态为 Open/Deferred。
4. 不改 baseline。若设计文档或证据变化，重新运行 review 并重新填写问题；同一基线再次调用保留已有答案。需要诊断时运行 lint/generic_lint，然后记录日志并 Complete。

格式、引用、摘要校验只证明复核记录完整且对应当前工件，不证明结论的语义正确，更不代表仿真或形式化通过。

## 完整记录示例

下例展示单个组合行为的完整记录。摘要和签名为演示值，实际 baseline 必须使用 review 为本次工件生成的值，不能复制演示值。

```json
{
  "schema_version": 1,
  "baseline": {
    "module": "ExampleBlock",
    "config": "Generic",
    "document_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "manifest_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "sources": {
      "outputs/evidence/ExampleBlock.sv": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    },
    "signature": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  },
  "behaviors": [
    {
      "id": "P-FORWARD",
      "checks": {
        "acceptance": {
          "status": "reviewed",
          "conclusion": "该路径没有 ready/valid 接受事件，输入变化直接影响输出。",
          "evidence": [
            {
              "path": "outputs/evidence/ExampleBlock.sv",
              "start_line": 7,
              "end_line": 7
            }
          ]
        },
        "storage_backpressure": {
          "status": "not_applicable",
          "conclusion": "组合转发路径没有存储或握手状态；输出直接由输入连续赋值。",
          "evidence": [
            {
              "path": "outputs/evidence/ExampleBlock.sv",
              "start_line": 7,
              "end_line": 7
            }
          ]
        },
        "bypass": {
          "status": "not_applicable",
          "conclusion": "组合转发路径没有存储或握手状态；输出直接由输入连续赋值。",
          "evidence": [
            {
              "path": "outputs/evidence/ExampleBlock.sv",
              "start_line": 7,
              "end_line": 7
            }
          ]
        },
        "configuration": {
          "status": "not_applicable",
          "conclusion": "顶层无参数和条件编译指令，数据宽度由端口声明固定为 8 位；不存在运行时配置输入。",
          "evidence": [
            {
              "path": "outputs/evidence/ExampleBlock.sv",
              "start_line": 1,
              "end_line": 8
            }
          ]
        },
        "reset_recovery": {
          "status": "not_applicable",
          "conclusion": "时钟和复位端口没有用于连续赋值，模块无状态，复位不能清零输出，也不存在待恢复事务。",
          "evidence": [
            {
              "path": "outputs/evidence/ExampleBlock.sv",
              "start_line": 1,
              "end_line": 8
            }
          ]
        },
        "assumptions": {
          "status": "reviewed",
          "conclusion": "比较输出时要求输入为已知值并等待组合传播稳定；这些是验证采样前提，不是 RTL 对生产者的保证。",
          "evidence": [
            {
              "path": "outputs/evidence/ExampleBlock.sv",
              "start_line": 7,
              "end_line": 7
            }
          ]
        },
        "verification_plan": {
          "status": "reviewed",
          "conclusion": "CK-EVENT-RESULT 比较当前输入输出，COV-NORMAL 按有效等值观察采样，不要求不存在的握手。",
          "evidence": [
            {
              "path": "outputs/evidence/ExampleBlock.sv",
              "start_line": 7,
              "end_line": 7
            }
          ],
          "ck_ids": [
            "CK-EVENT-RESULT"
          ],
          "coverage_ids": [
            "COV-NORMAL"
          ]
        }
      }
    }
  ]
}
```
