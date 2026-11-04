
# 最终验收与交付

在设计文档、质量报告和 semantic_review.json 已完成后调用 finalize/generic_finalize。工具执行字段、精确端口、追溯关系、源码位置、质量报告六个固定区块、签核状态和复核记录检查，自动更新质量报告中的验收区块，并生成 validation.json。若 manifest 的 generation_status 为 partial，验收前须在开放项表保留 `OPEN-GENERATION-PARTIAL`（Open 或 Deferred），并在质量报告说明生成失败的范围和受限结论。

成功后记录阶段日志并 Complete。无需依次重复 validate、lint、Check，也无需把工具结果手工抄回报告。若之后改动交付物，原验收记录会失效；按诊断处理，设计文档变化时重新 review，填写工具指出的受影响行为，最后重新 finalize。

## 可选模块规格交付

启用自动模块规格准备时，草稿阶段已将发现的全部 `*_spec.md` 原样复制到 `{OUT}/specs/`，保留相对 `extracted_functions/` 的层级、文件名和字节。info 仅为可选参考，留在 `{OUT}-fmagent/fm_agent/`；四阶段资料引用也保持指向该原生副本。没有 spec 时保留空的 specs 目录，不生成占位文件；空白或任意正文不会触发内容门槛，不修订其正文。

此交付不属于 validation.json 或质量报告的 spec 一致性签核，原中文文档验收标准不变。关闭准备功能时不创建 specs。启用后的附加完整目录示例：

```text
outputs/specs/
  parent/Module_spec.md
  child/Module_spec.md
outputs-fmagent/
  pipeline.log
  fm_agent/
    extracted_functions/
      parent/Module_spec.md
      parent/Module_info.md
      child/Module_spec.md
  .codegraph/
```

pipeline.log、info 和 .codegraph 仅在实际存在时保留。原生目录已永久迁出，不会在任务结束时搬回输入项目。复制失败必须按操作诊断处理，不能将部分目录宣称为完整导出。

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
