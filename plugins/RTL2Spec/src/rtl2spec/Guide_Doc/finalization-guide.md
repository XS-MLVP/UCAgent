
# 最终验收与交付

在设计文档、质量报告和 semantic_review.json 已完成后调用 finalize/generic_finalize。工具执行字段、精确端口、追溯关系、源码位置、质量报告六个固定区块、签核状态和复核记录检查，自动更新质量报告中的验收区块，并生成 validation.json。若 manifest 的 generation_status 为 partial，验收前须在开放项表保留 `OPEN-GENERATION-PARTIAL`（Open 或 Deferred），并在质量报告说明生成失败的范围和受限结论。

成功后记录阶段日志并 Complete。无需依次重复 validate、lint、Check，也无需把工具结果手工抄回报告。若之后改动交付物，原验收记录会失效；按诊断处理，设计文档变化时重新 review，填写工具指出的受影响行为，最后重新 finalize。

## 完整交付目录示例

```text
outputs/
  ExampleBlock_design_document_zh.md
  ExampleBlock_document_quality_review.md
  semantic_review.json
  validation.json
  evidence/
    ExampleBlock.sv
    ExampleBlock.preprocessed.sv
    source_map.json
    ports.csv
    ports.md
    manifest.json
  logs/
    actions.jsonl
    stages.jsonl
```

预处理视图和 source_map.json 仅属于通用输入工作流。validation.json 保存模块、配置、工作流、插件与模板版本、完成时间、实际检查结果和最终工件摘要。logs/actions.jsonl 保存实际命令的开始时间、耗时和退出结果，不记录敏感配置或原始模型输出。阶段完成后，logs/stages.jsonl 记录该阶段的实际起止时间和总耗时。

生成与验收完成不表示功能已签核。自动验收区块保留动态验证与形式化的 Unrun；不得将复核记录、生成成功或文档检查通过改写为 Proved/Closed。
