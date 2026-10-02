
# Bug Review 报告使用指南

打开 `bug_report/index.html`，即可查看两个模块的验证报告。先进入模块概况，再点击具体 Bug 或失败用例。`bug_report` 是报告文件夹的示例名称。如需预览完整波形，请参考第 2 节。

## 1. 报告入口与 Bug 详情

| 模块 | 收集用例 | 失败用例 | 原始 Bug 声明 | 高置信度 Bug | 高置信度根因组 |
| --- | ---: | ---: | ---: | ---: |  --- |
| RAID 解码器 | 204 | 55 | 26 | **25** | **21** |
| RAID 编码器 | 234 | 83 | 14 | **13** | **11** |

高置信度采用报告主表的口径：最终裁决为 `confirmed`，且复核置信度不低于 `0.8`。共享同一根因的 Bug 在模块页合并为一组，每条 Bug 仍保留独立详情。

1. 从 `bug_report/index.html` 进入模块页。模块页汇总全量重跑、覆盖率、按最终根因聚合的高置信度缺陷和失败用例。
2. 点击 `高置信度缺陷 -> 涉及 Bug -> Bug 名称`，查看验证场景、预期行为、实际行为、归因与根因，以及证据链。相关文档包含原报告和 Spec 引用；相关源码列出 RTL 文件与简析。点击文件引用可查看全文并高亮对应行段。
3. 点击失败用例，查看测试预期与规格预期、实际失败、归因、关联 Bug 和签名波形分析。

## 2. 启动波形预览

只需 **Python 3.9 或更新版本**。先进入报告文件夹，再运行：

```bash
cd bug_report
python3 serve.py
```

然后在浏览器打开 `http://127.0.0.1:8765/index.html`。端口被占用时可运行 `python3 serve.py --port 8766`，并打开对应端口的地址。保持命令运行，结束时按 `Ctrl+C`。

文字报告可直接用 `file://` 阅读；完整波形预览会从报告目录加载波形快照、JavaScript、WebAssembly 和 Worker。浏览器对 `file://` 下的这类跨文件请求有限制，当前预览入口也会明确拒绝 `file://`。`serve.py` 把这些文件作为同源静态资源提供，并设置 WebAssembly 类型和所需响应头。`127.0.0.1:8765` 只是默认本机地址与端口，不会把波形上传到外部服务，也不依赖 UCAgent 的动态波形接口。

## 3. 文件夹内容

```text
bug_report/                        报告文件夹；名称可更改
├── index.html                     总门户
├── serve.py                       独立的本地静态报告服务
├── workspace_raid_dec_top/
│   ├── report/                    当前公开报告；指向下方运行的 results/report/
│   │   ├── index.html             模块概况
│   │   ├── bugs/                 逐 Bug 详情
│   │   ├── cases/                失败用例详情
│   │   ├── sources/              文档和 RTL 全文预览
│   │   ├── surfer/               静态波形查看器
│   │   └── waveforms/            可预览的原波形快照
│   └── runs/
│       └── run-fcfc51397ec97dd4/
│           ├── .ucagent/         签名波形收据
│           └── results/
│               ├── review_index.json      本次复核索引
│               └── inputs/workspace_raid_dec_top/unity_test/
│                   ├── raid_dec_top_bug_analysis.md                原 Bug 详细分析
│                   ├── raid_dec_top_static_bug_analysis.md         静态 Bug 分析
│                   ├── raid_dec_top_functions_and_checks.md        功能与检查点
│                   └── raid_dec_top_test_summary.md                原测试总结
└── workspace_raid_enc_top/
    ├── report/                    编码器当前公开报告，结构同上
    └── runs/run-b2929c712ba3aee1/results/inputs/workspace_raid_enc_top/unity_test/
                                    编码器原始验证资料，文件类型同上
```

每个 `report/` 下的 
- `index.html` 是模块概况；
- `bugs/` 是逐 Bug 详情；
- `cases/` 是失败用例详情；`sources/` 是可高亮行段的文档和源码预览；
- `surfer/` 是静态波形查看器；`waveforms/` 是发布时仍存在的原波形快照；

原始验证资料保存在对应运行的 `results/inputs/<workspace>/unity_test/`。以下文件是本次报告的输入，便于对照复核结论与原始声明；最终裁决以模块报告为准。

| 原始资料 | RAID 解码器 | RAID 编码器 | 内容 |
| --- | --- | --- | --- |
| Bug 详细分析 | [dec 分析](bug_report/workspace_raid_dec_top/runs/run-fcfc51397ec97dd4/results/inputs/workspace_raid_dec_top/unity_test/raid_dec_top_bug_analysis.md) | [enc 分析](bug_report/workspace_raid_enc_top/runs/run-b2929c712ba3aee1/results/inputs/workspace_raid_enc_top/unity_test/raid_enc_top_bug_analysis.md) | 原报告的场景、测试点和 Bug 分析。 |
| 静态 Bug 分析 | [dec 静态分析](bug_report/workspace_raid_dec_top/runs/run-fcfc51397ec97dd4/results/inputs/workspace_raid_dec_top/unity_test/raid_dec_top_static_bug_analysis.md) | [enc 静态分析](bug_report/workspace_raid_enc_top/runs/run-b2929c712ba3aee1/results/inputs/workspace_raid_enc_top/unity_test/raid_enc_top_static_bug_analysis.md) | 静态检查发现的候选问题，不等同于本次动态复现结论。 |
| 功能与检查点 | [dec 检查点](bug_report/workspace_raid_dec_top/runs/run-fcfc51397ec97dd4/results/inputs/workspace_raid_dec_top/unity_test/raid_dec_top_functions_and_checks.md) | [enc 检查点](bug_report/workspace_raid_enc_top/runs/run-b2929c712ba3aee1/results/inputs/workspace_raid_enc_top/unity_test/raid_enc_top_functions_and_checks.md) | 功能、测试点与检查点的原始定义。 |
| 测试总结 | [dec 测试总结](bug_report/workspace_raid_dec_top/runs/run-fcfc51397ec97dd4/results/inputs/workspace_raid_dec_top/unity_test/raid_dec_top_test_summary.md) | [enc 测试总结](bug_report/workspace_raid_enc_top/runs/run-b2929c712ba3aee1/results/inputs/workspace_raid_enc_top/unity_test/raid_enc_top_test_summary.md) | 原验证环境的测试结果，须与本次重跑结果区分。 |
