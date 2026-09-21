
# RTL2Spec 文档生成

RTL2Spec 是按需安装的 UCAgent 插件，位于 `plugins/RTL2Spec/`。当前工作流面向
XiangShan 模块，结合 Chisel/Scala 源码与同 commit、同配置生成的 RTL，交付中文
设计与功能检测点文档、质量报告和版本历史。

工作流分为三个阶段：

1. **生成证据**：检查工具环境和源码，生成 RTL、端口清单及证据清单。
2. **编写文档**：按模板整理模块行为、接口和验证计划，无法确认的内容保留为 `OPEN-*`。
3. **渲染与验收**：将 Mermaid 渲染为 SVG，检查文档结构、证据和引用的一致性。

先安装 UCAgent，再从仓库根目录安装插件：

```bash
python -m pip install ./plugins/RTL2Spec
ucagent --validate-plugin rtl2spec
```

完整输入准备、Sbuffer 运行示例、产物路径及环境要求统一维护在
[RTL2Spec README](https://github.com/XS-MLVP/UCAgent/blob/main/plugins/RTL2Spec/README.md)。
文档验收通过后，仍需人工审核设计意图；它不代表 SVA 编译或 formal 证明通过。

扩展插件请参考[插件开发与发布](../03_develop/09_plugins.md)。
