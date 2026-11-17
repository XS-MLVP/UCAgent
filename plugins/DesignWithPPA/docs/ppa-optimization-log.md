
# PPA 优化日志

两个 workflow 都会自动生成可直接在浏览器打开的 HTML 日志和内容相同的 Markdown 日志。
无需开启 Skill，也无需等待最终交付。日志文件不需要由用户或 Agent 手工维护。

## 查看入口

`OUT` 是工作区内配置的输出目录，`DUT` 是当前任务名。

| Workflow | HTML 日志（工作区相对路径） | Markdown 日志 |
| --- | --- | --- |
| `unit-design-tdd` | `{OUT}/{DUT}_optimization_log.html` | `{OUT}/{DUT}_optimization_log.md` |
| `repo-module-tdd` | `{OUT}/repo/reports/optimization_log.html` | `{OUT}/repo/reports/optimization_log.md` |

可以直接打开 HTML，也可以在 PPA 看板的 Reports 区域点击
**Optimization log / direction and changes**。命令行运行日志会输出本轮状态和 HTML 路径；
`RunRepoValidation` 的测量结果还会返回 `optimization_log` 字段。文件更新后刷新页面即可查看。
HTML 不依赖外部服务、JavaScript 库或网络资源。

## 每轮能看到什么

- 版本号、候选名、UTC 记录时间、接受/拒绝状态，以及当前最佳版本和停止原因。
- 优化方向与具体改动假设。单元设计流程还展示目标热点和预期指标；仓库模块流程展示接口版本。
- 通过版本文件内容身份比对得到的实际新增、修改、删除文件与前后身份；仓库模块流程同时比对文件权限。
- 可点击的源码 diff 和完整测量证据，便于核对具体修改。单元设计 diff 位于
  `reports/ppa/iterations/iteration-XXX.diff`；仓库模块 diff 位于 `repo/reports/{variant_id}.diff`。
  二进制或超过 2 MB 的单文件不展开内容 diff，日志保留文件身份，diff 明确说明省略。
- 面积、时序、功耗及功能性能指标的实测值、单位、相对比较版本与原始基线的百分比变化，
  以及每项指标的 improved、regressed 或 unchanged 判定。百分比是数值变化，改善方向由
  assessment 给出；例如面积下降是改善，频率下降是退化。
- PPA selection score、拒绝原因和比较版本。高诊断 score 不代表 rejected 候选可交付。

日志把“提出什么假设”与“实测得到什么”分别展示，不从假设推断优化成功。
所有 accepted/rejected 版本都保留，不只展示成功候选。单元设计中的功能失败版本保留方向、
文件变化和 diff；未获得的 PPA 指标明确标为 unavailable。

## 失败、重试与交付

仓库模块流程从正式测量启动时记录 `started_unmeasured`。它表示尚未记录完成结果，
进程中断后也不能把它当作已完成。构建、功能测试或分析失败时记录 `failed_unmeasured`
及有界错误原因；这些尝试不计入有效候选轮次，不影响原有停止和最佳版本选择规则。
修复后重试会保留失败尝试，成功测量再生成正式版本记录。
输入格式、冻结合同或重复候选等测量前校验失败由当前工具诊断报告，不创建测量尝试。

单元设计日志在基线登记和每轮候选接受/拒绝后更新，最终结果检查时重新生成；
前置构建或性能检查尚未完成时，以当前 Check 的诊断为准。仓库模块日志在测量启动、
结束及失败时更新，重复检查从已验证的记录重新生成，不追加重复的正式轮次，也不会为
显示日志再次运行测试。日志展示不改变任一 workflow 的接受规则或计数规则。

`repo-module-tdd` 交付包包含 `reports/optimization_log.html`、Markdown、逐轮证据及 diff，
`summary.md` 提供链接；复制交付包后相对链接仍可使用。输出目录下的日志是可重新生成的
展示文件，不能编辑它们来改变接受结论。代码、指南和模板更新后，应以新工作区启动 workflow。
