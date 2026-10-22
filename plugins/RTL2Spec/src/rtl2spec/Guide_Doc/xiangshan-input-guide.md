
# 香山输入与证据

工作区提供干净的 `third_party/XiangShan` Git checkout 及递归子模块。DUT 使用准确的 Chisel class 名，配置使用实际配置 class；可选 `inputs/{DUT}/` 中的 spec 仅表达待核对的设计意图。

## 本阶段操作

1. 先用 ReadTextFile 读取本阶段 reference_files。确认 `{OUT}` 无旧产物；已有结果按用户授权清理或另选输出目录。
2. 运行 `RTL2SpecCommand(action="preflight", module="Sbuffer", config="DefaultConfig")` 检查构建条件；替换为本次模块和配置。
3. 运行 `action="evidence"` 生成 RTL，读取 `{OUT}/evidence/manifest.json`、`ports.csv` 和 `{DUT}.sv`，确认 commit、配置、生成状态与当前输入一致。
4. 读取 DUT Scala 和支撑结论的相关模块。使用 `action="related_sources", related_modules=["RelatedClass"]` 登记确实参考的模块；没有参考的模块不登记。
5. 运行 `action="ports"` 生成 `{OUT}/evidence/ports.md`；记录本阶段结果并 Complete。

构建得到目标 RTL 但后续编译失败时，证据状态为 partial；草稿可以继续用于记录已有模块证据，但 final 必须在开放项表中加入 `OPEN-GENERATION-PARTIAL` 并保持 `Open` 或 `Deferred`，同时在质量报告说明失败范围和受限结论，不能声称整个设计成功编译。生成和源文件检查都不证明仿真、形式化或覆盖率已完成。

## 本阶段完成产物

```text
outputs/
  evidence/
    Sbuffer.sv
    ports.csv
    ports.md
    manifest.json
  logs/
    actions.jsonl
```

manifest 由工具生成并校验；不得手工修改。正式设计文档的完整参考例见 Guide_Doc/generation-guide.md，固定结构见 Guide_Doc/chip_design_document_template_zh.md。
