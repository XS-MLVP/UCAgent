
# Bug Review

复核已有 UnityTest 报告中的 Bug 是否成立。原文格式不限，LLM 整理声明、工具生成记录；默认只复跑关联用例，波形分析默认关闭。输入不修改，每次运行使用独立工作区。

流程：输入盘点 → 原声明整理 → 定向复跑及分析 → **可选波形分析** → 裁决与根因整理 → 发布。

## 运行

需要 UCAgent >=26.9.2.dev6。准备好 `inputs/<module>/unity_test` 以及可用的 DUT 包、规格和 RTL，然后在插件目录执行：

```bash
python3 scripts/download_standards.py --cache /absolute/path/standards-git-cache
make bug_review_demo OUTPUT_ROOT=/absolute/path/new-run PYTHON=/path/to/python
make mcp_bug_review_demo OUTPUT_ROOT=/absolute/path/another-run PYTHON=/path/to/python
```

Make 仅复制输入，不修改原报告、不自动编译源目录。`init_demo` 可单独准备工作区；已开始的工作区不会被另一次 Make 启动复用。模块目录名和实际 DUT 名不同时指定 `DUT=bosc_TLB`。原生包必须匹配所用 Python；缺依赖时记录复跑阻塞，不伪造结果。

也可直接在已准备的新工作区启动：

```bash
ucagent /absolute/path/workspace bosc_TLB --plugin /absolute/path/plugins/bug_review \
  --plugin-workflow bug_review:analysis --output results --tui
```

## 通用规范库

第三方文档不随 Git 仓库提交；首次运行前执行上述下载命令，准备完整文档源目录：香山设计文档 kunminghu-v2r2a / kunminghu-v3，以及 UnityChipForXiangShan 全部验证文档（中英文和图片）、RISC-V 官方 ISA 手册及其 docs-resources 子模块、Chisel docs / docs-target / website（含资源与示例）。下载结果保留原文及许可证，来源清单在 `src/bug_review/references/catalog.json`。

PrepareReviewInputs 将完整库归档到 `{OUT}/inputs/review_standards/`，供所有 Bug Review 按需检索。库不进入原 Bug 来源清单，也不复制到测试执行目录。正常启动及 Check 不联网；报告归档引用的实际条款。违反适用的任一规范并有合法测试和真实执行证据，可确认 Bug，无需等待额外的项目专用 Spec。必须核对版本、扩展和接口类型；不能把规范允许的行为或未采用的草案当作违例。

更新文档时在插件目录运行：

```bash
python3 scripts/download_standards.py --cache /absolute/path/standards-git-cache
```

每次刷新都会 fetch 指定上游分支的最新提交。RISC-V 使用官方仓库最新 `main`，具体 commit、章节版本及草案状态可追溯；运行中的复核使用自己归档的固定副本。原文图片及表格资源保留，未在此生成 PDF 或静态网站。

## 选项

| 已解析配置 | 默认值 | 用途 |
| --- | --- | --- |
| `runtime_options.bug_review_waveform_enabled` | `false` | 启用定向复核后的独立波形阶段；阶段内按需选择 Case |
| `runtime_options.bug_review_full_regression_enabled` | `false` | 收集并运行全量测试，默认仅原声明关联测试 |

可通过 `BUG_REVIEW_WAVEFORM_ENABLED=true`、`BUG_REVIEW_FULL_REGRESSION_ENABLED=true` 提供 YAML 默认值，或通过 UCAgent `--override` 设置上述正向布尔字段。阶段使用原生 `skip`；插件依据最终解析后的波形开关同步阶段与工具可用性。运行时不重新读取环境变量。

```bash
BUG_REVIEW_WAVEFORM_ENABLED=true make bug_review_demo OUTPUT_ROOT=/absolute/path/wave-run
```

关闭波形时不暴露专用波形工具，裁决和报告也不要求波形。原生 WaveInfo、签名回执与精确测量仅用于启用后的实际取证。Skill 可选，不影响完成标准。

## 输出

```text
results/                     # 即 {OUT}，可由 --output 或 Make OUT 修改
├── inputs/                  # 原 UnityTest、历史报告及 review_standards 完整规范库
├── review.json              # 模块背景、来源、原声明、完整 Case 分析、裁决与根因
├── runs/                    # work执行副本、实际报告、invocations与日志
└── report/                  # index.html、Bug/Case/根因页面、assets、manifest.json
```

不再维护分析草稿或跨运行版本历史。工具只更新分析字段，机器结果来自实际报告。来源校验保留行号、Case 和 invocation 身份；不重复扫描或哈希整个不可变输入。

报告由单一 `review.json` 渲染，共用模板和静态资源。声明整理阶段填写模块背景，定向复核阶段填写分析及失败日志行，裁决阶段补齐现象、正常行为、触发步骤、预期/实际对照、原因、影响与边界。模块页列出 Bug 和分类失败 Case；详情页左侧分析、右侧证据，整页统一滚动。Markdown 支持排版阅读与逐行源码切换；原始波形可下载或跳转 Surfer，并明确是否经过分析。

报告明确区分历史证据与本次复跑；功能违例成立不代表已定位内部根因。所有原声明都保留确认、排除或未定裁决，一次通过不能独自排除 Bug。缺材料可以完成有明确缺口的复核，不等于所有问题已经解决。

发布回调生成多模块门户和 `serve.py`。在输出根目录运行 `python3 serve.py`，打开 `http://127.0.0.1:8765/`。服务只开放已发布报告；`inputs`、`runs` 和内部记录不通过该服务暴露。波形预览需要 HTTP 和实际可用快照。

输入要求见 [INPUTS.md](INPUTS.md)，执行契约及完整例子见 [Guide_Doc/analysis.md](src/bug_review/Guide_Doc/analysis.md)。
