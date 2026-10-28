
# Bug Review 结构

目标是核实原报告声明。规范流程、开关和输出布局以 [README.md](README.md) 为准，执行字段和完整示例以 [Guide_Doc/analysis.md](src/bug_review/Guide_Doc/analysis.md) 为准。

- `core/records.py`：当前结构化契约；原声明与最终裁决分开。
- `core/layout.py`：输入只读归档、输出寻址与来源行段。
- `core/replay.py`：定向收集、真实报告导入、波形会话归属。
- `core/validation.py`：来源覆盖、测试分析、裁决与共享根因校验。
- `core/evidence.py`：可选签名波形及真实测量。
- `core/reporting.py`：可携带报告、源码链接与可选静态波形查看器。
- `tools/`：按输入、分析、波形和发布分文件，直接接收分析字段。
- `checkers/analysis.py`：使用实际产物验收，阶段状态由 UCAgent 管理。

无跨运行草稿、哈希冲突或修订恢复机制。保留单文件原子写入、路径边界、Schema 和真实执行身份检查。输入文件只读不能替代对分析内容与真实证据的核实。
