---
name: case-normalization
description: 把旧版 unitytest 产物（bullet 式 Bug 声明、独立标签行、五级标题、短 TC 标签、缺失摘要或报告）规范化为 Bug Review 当前要求的输入形状；不推断 Bug 结论、波形或启动材料。
---

# Bug Review 产物规范化

把旧版 unitytest 产物转换成 `INPUTS.md` 要求的输入形状，供之后 `make init_<module>` /
`make bug_review_<module>` 使用。这是一个离线批处理工具：工作流本身不依赖本 Skill，
不运行它时按 `INPUTS.md` 手工准备输入同样是完整路径。确定性脚本见
`scripts/normalize_case.py`，转换规则与其内嵌的解析镜像一致，并在
`plugins/bug_review/tests/test_case_normalization.py` 与插件真实解析器对账。

## 何时使用

目标是 `/Users/fy/work/XSV/UCSwarm/third-party/case` 这类旧产物目录（也可用于其他
目录）。产物存在以下任一情况时需要规范化：

- Bug 声明嵌在 bullet 内（`- <CK-..> … 置信度 98% <BG-XXX-98>`）或独立标签行（`<BG-…>` 单独成段）；
- BG 标题使用了五级或更高级别标题；
- `<TC-…>` 标签缺少 `unity_test/tests/` 前缀；
- 缺少 `unity_test/<模块>_bug_summary.md` 或 `_bug_analysis.md`；
- 报告文件名与模块目录名不一致（前缀漂移）。

已符合当前契约的产物（六级 `######` BG 标题、摘要与 analysis 身份一致）保持逐字节不动。

## 用法

```bash
# 单模块原地规范化（改写 corpus，先备份原件）
python3 scripts/normalize_case.py --case-root <case根> --module bosc_Ftq

# 全量试运行：只报告计划动作，不写任何文件
python3 scripts/normalize_case.py --case-root <case根> --all --dry-run

# 复制模式：corpus 只读，规范化产物放到指定目录
python3 scripts/normalize_case.py --case-root <case根> --module bosc_Ftq --output-dir <目录>

# 审计报告与备份位置
python3 scripts/normalize_case.py --case-root <case根> --all --report report.json \
  --backup-dir <case根>/.normalization_backup
```

原地模式把被改写文件的原副本按 `<case根>` 相对路径保存在 `--backup-dir`（默认
`<case根>/.normalization_backup/`），已有备份永不覆盖。复制模式不备份，并排除
`__pycache__/`、`.pytest_cache/`、`toffee_tmp_*`、`uc_test_report`、`.coverage-report-*`。

## 转换规则

- 含 `<BG-…>` 的 bullet：引导行改写为 `###### <去标签描述> (NN%) <BG-原始标签>`，原行剩余
  文本与嵌套子项作为块体保留；一条 bullet 含多个 BG 标签时每个标签各得一个标题（正文挂在
  首个标题下）并记录异常。
- 独立 `<BG-…>` 行：其后到下一个标签/标题的散文成为 `######` 标题与块体。
- 一至五级 BG 标题降为六级。
- 短 `<TC-file.py::node>` 标签：`unity_test/tests/<file>` 存在时补全前缀；不存在时保持
  原样并记录异常。TC 扩展只发生在含 BG 块的文档，零声明报告完全不动。
- 缺失摘要：从转换后的 BG 块生成八列表（Name=去 `-NN` 身份、Confidence=NN/100、
  Ref=块行段）；已有摘要与 analysis 身份一致时逐字节保留，不一致时重新生成并记录。
- 缺失报告：只生成显式的零声明空模板（含"原始产物缺失，0 个原始 Bug 声明"标注），
  永不覆盖既有文件。
- 前缀漂移：`<X>_bug_summary.md`/`<X>_bug_analysis.md` 且 X≠模块名、规范名空缺时重命名；
  其他非规范文件名只报告。
- AGENTS.md 逐字节相同的重复目录对：只规范化文件更多的一方，另一方 `skipped_duplicate`。
- `unity_test/tests/` 没有 `test_*.py` 的目录 `skipped_no_tests`，不生成任何文件。

幂等性：转换后的产物再次运行是 no-op（报告仍会列出建议性异常，如缺失 TC 文件）。

## 边界

- 不生成或补写 Bug 结论、波形证据、RTL、`launch.yaml`、`filelist.f`。每个模块报告
  `launch_materials_missing`（launch.yaml / filelist / `<模块>/` 运行时包）；补齐路径见
  input-preparation Skill。在这些材料补齐之前 `make init_<module>` 仍会失败。
- 不改写测试代码、Kbuild、顶层 `conftest.py`（复制模式把顶层 `conftest.py` 原样放到
  输出目录根，保持其按 `bosc_*/unity_test/tests/` 路径形状收集的语义）。
- 重复 BG 身份（同一 Bug 在多个场景标题下复用同一标签）合并为一条摘要行，Ref 列保留
  全部块行段。
