---
name: multi-review-supervisor
description: 监管多个 Bug Review 模块并行复核：准备独立输入，给每个模块分配一个子 Agent，以 Claude Code 后端启动 UCAgent，定期检查阶段进度、异常与报告。
---


# 多模块复核监管

在 **UCAgent 工作流之外**使用本 Skill。你是监管 Agent，负责模块选择、输入就绪、任务分配、异常处理和最终汇总；每个子 Agent 只拥有一个 `workspace_<dut>` 的运行任务。不要让两个子 Agent 同时复核同一模块，也不要让监管 Agent 代替子 Agent 填写 case/Bug 证据。

## 准备与分配

1. 阅读插件根目录 `INPUTS.md`，列出本次要复核的模块。逐模块检查 `unity_test/tests/`、至少一份原 Bug 文档、规格/RTL、测试所需 DUT 包，以及目标 Python 环境可导入 DUT。缺少材料时使用 `input-preparation` Skill 整理；由你阅读原文决定文件清单和 Bug 声明，脚本只负责格式与复制。当前仓库优先使用绝对路径的 `.venv/bin/python`。DUT 导入报 `ModuleNotFoundError: xspcomm` 或 `symbol not found` 时，说明包由其他 Python 版本编译，用 `input-preparation` 的 `picker-package` 子命令针对当前解释器重打包（一条命令，自动备份旧包），通过后再分配子 Agent。
2. 只对本次选中的模块启动子 Agent。先确认 `claude` 命令可用、插件可由选定 Python 加载、`OUTPUT_ROOT` 可写。按机器可承受的仿真负载与可用子 Agent 名额决定并发数；默认先并行两个，余下排队。
3. 用宿主环境的子 Agent 工具逐个创建任务。给每个子 Agent 明确的模块名、输入目录、共享输出根目录和 Python 路径；它只负责该模块的 UCAgent 进程、阶段排障与最终报告。要求它把新运行目录、当前阶段、阻断原因和报告路径发回监管 Agent。监管 Agent 保留模块→子 Agent→运行目录的对应关系。

给子 Agent 的任务可按以下格式填写，保持模块边界明确：

```text
模块：workspace_<dut>
输入：<INPUT_ROOT>/workspace_<dut>
输出：<OUTPUT_ROOT>/workspace_<dut>
Python：<仓库根目录>/.venv/bin/python
运行单模块命令，保存首条 JSON 中的 run 目录；每次阶段变化和异常立即回报，阶段不变时每五分钟回报一次当前阶段与进程状态。只处理本模块的执行区；完成时给出退出码、报告状态与报告入口。
```

子 Agent 在 `plugins/bug_review/` 目录运行单模块命令；不要使用会依次重跑全部模块的 `make bug-review-analysis`：

```bash
make bug_review_<dut> \
  PYTHON=/absolute/path/UCAgent/.venv/bin/python \
  INPUT_ROOT=/absolute/path/UCAgent/plugins/bug_review/inputs \
  OUTPUT_ROOT=/absolute/path/UCAgent/plugins/bug_review/output \
  AGENT_ARGS='--backend claude --mcp-server --mcp-server-port -1 --loop --exit-on-completion'
```

`--mcp-server-port -1` 为每个进程选择可用端口。命令首条 JSON 输出中的 `workspace` 是本次 `run-<id>` 目录；保存它，后续检查和恢复均用该目录。每个子 Agent 保持自己的命令会话并记录退出码，长时间运行期间主动向监管 Agent 报告阶段变化和异常。

## 监控与恢复

监管 Agent 每 30–60 秒查看子 Agent 消息和进程状态，每 2–5 分钟核对一次阶段进度；长阶段不能仅因耗时较久就判失败。需要核实时，用以下只读命令查看指定运行的阶段状态，并结合最新命令输出、`results/review_index.json`、`results/diagnostics/` 判断是否前进：

```bash
PYTHONPATH=/absolute/path/UCAgent/plugins/bug_review/src:/absolute/path/UCAgent \
  /absolute/path/UCAgent/.venv/bin/python -m bug_review.workflow status \
  --workspace /absolute/path/to/output/workspace_<dut>/runs/run-<id>
```

发现非零退出、pytest 收集错误、DUT/依赖导入失败、MCP 连接或端口错误、阶段 Check 阻断、长时间没有日志及产物更新时，让**所属子 Agent**定位具体错误并回报处理结果。环境错误和测试失败分别记录；后者不能直接视为运行异常。可在原运行目录修复的情况，子 Agent 使用相同 `PYTHONPATH` 和解释器执行 `python -m bug_review.workflow launch --workspace <run-目录> --python <同一解释器> --ucagent-root <仓库根目录> -- --backend claude --mcp-server --mcp-server-port -1 --loop --exit-on-completion` 继续；重新执行 `make bug_review_<dut>` 会新建运行，须明确记录为另一次尝试。遇到相同的系统性错误时，暂停分配队列中剩余模块，先修复共同环境。

把失败分成三类再应对：**平台/环境限制**、**工具瞬时状态**、**真实测试失败**。确定性失败先定位根因（读工具与库源码）再决定应对，不要按可修复错误反复重试同一命令。macOS 上 picker DUT 同进程**并发**第二个实例会 FATAL「Dynamic multi-module is only supported in linux」；顺序的建→销毁→建不受限，函数级 fixture 的整包重放通常能跑通。同一命令重跑成功的先前失败按瞬时状态留档（记录两次命令行与时间戳），既不记为平台限制也不记为测试缺陷。监控读到阶段回退时先直接核实状态文件再上报——状态文件重写瞬间可能读到旧值。

## 收尾

对子 Agent 的每个成功运行，核对进程退出码、`workflow status` 为 complete、`<OUTPUT_ROOT>/workspace_<dut>/report/report_manifest.json` 的 `review_status` 和模块报告入口。完成判定以 status 与阶段 Check 为准；退出码非零时先区分阶段/发布失败与 wrapper 收尾遥测产物（例如各阶段全过、status complete 而 make 仍报 Error，按完成归档并在汇报中记录机制），不据此重跑。`review_status: incomplete` 是内容质量旗标而非失败——存在 suspected_dut 用例、未决 environment finding、collection error 或 not_run 用例都会触发；向使用者转述命中条件即可，不需要修复。统计产物数量与用例数不一致时，先排除先前失败运行残留的输出文件再下结论。如果阶段已经完成但进程仅在发布时失败，保留该运行并在此处串行补发布。所有子 Agent 结束后，按模块**顺序**使用相同 `PYTHONPATH` 和解释器执行 `python -m bug_review.workflow publish --workspace <run-目录> --output-root <共享输出根目录>`，让最后一次发布重建包含全部成功模块的 `<OUTPUT_ROOT>/index.html`；并发发布可能让总门户遗漏刚完成的模块。失败或未完成运行保留在各模块 `runs/` 中，不写成已完成报告。

向使用者汇报每个模块的输入准备情况、子 Agent/运行目录、当前或最终阶段、报告状态、报告入口及需要处理的异常。监管期间持续提供简短进度更新，直到全部模块完成或明确留下待处理阻断。
