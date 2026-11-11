
# ACT4 报告引用提取与 YAML 写入优化

日期：2026-11-10。这是优化计划中的第二项，范围为 `extension-review` 的报告机械生成。
本项在开发分支实现、测试并独立提交后，单独转移到基于 main 的分支 `perf/act4-report-writing`。

## 目的与行为

此前模型需要手工复制源码原文，再处理 YAML 引号、缩进和转义。本轮历史报告修正涉及精确引用、
路径和 YAML 问题；原生命令完成到报告通过的 9 分 19.819 秒也包含语义审查及人工操作，
不能全部归为机械格式开销或可节省时间。

新增 `WriteACT4ReviewReport(path, document)`：模型提供完整语义报告对象，每个引用保留
`path`、`lines`、`observation`，工具提取 `quote` 并写入 YAML。已有 quote 必须与原文一致。
工具只写入当前工作流声明的 `review.yaml`、`final.yaml`，遵守工作区写权限及符号链接限制。

写入工具与现有 Check 共用来源白名单、SHA-256、UTF-8 和 1..100 行范围校验；
不改写状态、置信度、推理、结论、观察或 evidence digest。过期 digest、引用错误或并发修改会阻止写入。
普通 Check 继续负责完整性、语义状态、原生证据及阶段验收，成功写入不等于检查通过。
生成工作流不注册此工具；审查工作流在 Skill 开关两种配置下均可用，工具被过滤时仍可手工写报告后 Check。

## 实测

在临时目录复制原 Zihintpause 报告的必要证据，未改动原工作区或原审查状态。
计时覆盖一次公开工具调用：证据读取、哈希校验、引用提取、YAML 序列化、写入前重检和原子写入。
复制和初始化在计时之外，每次完成后核对完整报告对象与原报告一致。

| 指标 | 结果 |
| --- | ---: |
| 语义判断 | 8 项 |
| 精确引用 | 44 条 |
| 引用文件 | 23 个 |
| 模型提交报告时可省略的 quote 正文 | 18,581 字符 |
| 测量次数 | 30 次 |
| 单次写入中位数 | 42.828 ms |
| 最短 / 最长 | 40.309 / 61.024 ms |

44 条引用的机械提取和写入约需 **43 ms**。完整语义内容保持一致，原输入文件的 SHA-256 前后相同。
模型仍须读取和理解引用依据；省略 quote 正文的字符数不等于实际 token 或费用节省。
此次未调用模型，也没有可直接比较的旧版机械生成工具，因此不报告完整 workflow 加速百分比。

复现命令（仓库根目录，使用安装了核心及插件测试依赖的 Python）：

```bash
PYTHONPATH=plugins/ACT4/src:. python plugins/ACT4/tests/benchmark_report_write.py \
  --review-dir act4-run-01/runs/20261109T100239Z-4c0cdb94/workspace/act4_review/Zihintpause/review \
  --repeats 30 \
  --output /tmp/act4-report-write.json
```

本轮 Python：`/tmp/ucagent-tui-pr-sv8hkm6s/venv/bin/python`。
原始样本、原输入哈希和隔离验证工作区保存在 `/tmp/ucagent-act4-report-HE5TtF/`。
正式计时结果为 `report-write-final.json`。

## 测试与独立交付

- 包含第一项优化的开发分支：报告工具、已有审查、文档契约、插件集成共 **298 项通过**。
- 在 upstream/main `1fe8bd02b119450bc3f72e8c2054d22ddd428e75` 的临时独立工作区，仅应用本项补丁及新增源文件，相同测试集合 **281 项通过**。差异来自第一项优化的 17 个测试。
- 新增 37 个用例覆盖精确引用、YAML 往返、行号边界、非法/未记录路径、来源变化、过期 digest、二进制/空引用、写权限、并发修改、失败保持原报告、final 前后证据引用、MCP schema 和普通 Check 集成。
- 模型状态并未自动修正：工具成功写入后，现有 Check 仍会拒绝将推断结论标为 passed。
- 工作流初始化在 Skill 启用/禁用时均验证工具可用，提示同时保留普通文件写入路径。

第二项已在不含第一项或 TUI 补丁的 main 工作区独立通过，可单独提交和 cherry-pick。
不要整文件复制当前 checker、指南或工作流来制作新 PR，以免把第一项的修改一并带入。
