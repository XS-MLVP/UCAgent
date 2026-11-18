
# 已有资产审查与增量修复

`extension-review` 检查已有模块的 CTP/验证计划、coverpoints、规范映射、testgen 和生成用例。
输入可以来自 riscv-arch-test，也可以是本地生成的模块资产。它保留原始输入，
在副本中修复有充分依据的问题，并交付审查报告、修改补丁和前后验证证据。

## 输入与启动

先按 [插件安装说明](../README.md) 安装。每个模块使用独立工作区，准备只读 ISA manual
及待审查资产。ACT checkout 应完整初始化所需子模块；本地资产无需 Git，但需包含其
共享依赖、原生生成/验证入口或明确说明缺少哪些上下文。工具软件由 [环境首阶段](environment.md) 准备。

审查 ACT checkout，默认目录是 `riscv-arch-test/`：

```bash
ACT4_WORKSPACE="$PWD/output/review-Sstc"
mkdir -p "$ACT4_WORKSPACE"
ucagent "$ACT4_WORKSPACE" Sstc \
  --plugin act4 \
  --plugin-workflow act4:extension-review \
  --output act4_review --backend langchain --tui
```

资源首阶段会按 [共享资源规则](environment.md) 复用已有仓库，缺失才下载；已有显式输入不会切换提交。
审查本地资产时，在工作区内准备 `local-assets/Sstc/`，然后运行：

```bash
ACT4_REVIEW_ROOT=local-assets/Sstc \
ucagent "$ACT4_WORKSPACE" Sstc \
  --plugin act4 \
  --plugin-workflow act4:extension-review \
  --output local_review --backend langchain --tui
```

`ACT4_REVIEW_ROOT` 可为工作区相对路径或外部只读资产的绝对路径，不能与输出重叠或经过符号链接。
例如可直接指定上次运行的候选资产目录，不必先把它复制到新工作区；使用 ACT4Resources 浏览该输入。
`ACT4_MANUAL_ROOT` 默认为 `riscv-isa-manual`，可指定独立外部只读规范库的绝对路径。
模块名及资产名称按实际大小写填写。

## 流程与结果

| 阶段 | 工作 |
| --- | --- |
| prepare_resources | 固定输入来源，复用仓库，按需取得缺失资源 |
| prepare_environment | 探测工具、安装缺项、复验；只读依赖说明，不提前阅读测试内容 |
| review_plan | 仅依据 ISA 和用户范围形成独立测试计划并冻结 |
| review_audit | 对照现有资产发现遗漏/错误，执行独立验证，形成优化方案 |
| review_repair | 在候选副本修复、复验，输出最终报告与补丁 |

优先阅读根目录 `<OUT>/final.md`：开头说明发现什么、修复什么、遗留问题及原因、需要用户提供什么帮助。
`<OUT>/changes.patch` 是相对于原始输入的修改；报告中的证据链接指向
`<OUT>/intermediate/<模块>/review/`，包括初审、计划、候选副本和前后验证记录。
环境准备摘要位于 `<OUT>/intermediate/<模块>/environment/summary.md`。

Questa/VCS/Xcelium 会探测且均为可选；缺少程序或许可证不妨碍源码审查和独立验证。
安装失败保留真实限制；工具不运行不能标记为通过，不能把环境问题当成测试资产缺陷。
缺少 ISA/框架能力依据的问题保留具体原因，不通过猜测更改预期值。
本地执行与远端 CI 通过、真实 DUT 验证分别记录。

完整产物格式及核验规则见 [运行指南](../src/ucagent_act4/Guide_Doc/ACT4_Extension_Review_Guide.md)。
