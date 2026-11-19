
# 自动模块规格准备

本阶段已自动准备模块资料，无需调用生成工具。用 Check 查看准备状态和发现的 spec 数量；数量为0也可记录阶段日志并 Complete。失败时保留实际目录，请操作者处理，不自行重新启动生成。

准备成功后，四个下游阶段的 reference_files 会分别列出本次发现的全部 spec/info；每阶段用 ReadTextFile 读取自己的参考清单。模块规格表示预期要求，源码和 RTL 表示实现观察；冲突按原文档流程登记开放项。不得修订原始模块资料或导出的 spec 正文。info 可选，不要求 spec/info 配对，也不要求 spec 存在、非空或具有特定格式。

原始资料保存在 `{OUT}-fmagent/fm_agent/`，参考路径始终指向该副本；项目中的 `fm_agent/` 和存在的 `.codegraph/` 已永久迁出，任务结束不会搬回。进入草稿阶段时，发现的 spec 会自动原样复制到 `{OUT}/specs/`；此操作不属于文档质量签核，不需要额外模型生成。

## 完整交付示例

以下为包含两个同名模块 spec 的完整目录示例。只复制 spec，保留相对 `extracted_functions/` 的路径、文件名和字节；info 仍留在原始资料内。

```text
outputs/
  Top_design_document_zh.md
  Top_document_quality_review.md
  semantic_review.json
  validation.json
  evidence/
  logs/
  specs/
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

没有任何 spec 时，仍创建空的 `outputs/specs/`，不生成占位文件；没有 info 或 `.codegraph/` 时不要求补齐。reuse 没有原生运行日志也允许。原中文文档、证据、源码复核与最终验收规则保持不变，见 `Guide_Doc/finalization-guide.md`。
