# Formal

`Formal` 是面向 UCAgent 的可安装插件，提供基于 SystemVerilog Assertions 的形式化验证工作流：验证规划与功能规格（FG/FC/CK）、SVA 属性实现、验证环境渲染与调试、覆盖率分析、反例测试、Bug 报告与验证总结。工作流资产（`workflows/formal.yaml`、`templates/formal_test`、`skills/`、`Guide_Doc/`）随包分发，技能以 `ext/formal/<skill>` 进入工作区。

Python 发行包名为 `ucagent-formal`，插件 ID 为 `formal`，要求 Python 3.11 及以上。

## 构建与安装

从源码构建并安装：

```bash
cd ucagent/plugins/Formal
python3 -m pip install build
python3 -m build .
python3 -m pip install dist/ucagent_formal-0.1.0-py3-none-any.whl
ucagent --validate-plugin formal
```

## 选用方式

```bash
# 源码树内直接选择（本仓库示例运行方式，见 Makefile 的 formal_% 目标）
ucagent <workspace> <DUT> --plugin ucagent/plugins/Formal --plugin-workflow formal:formal --output formal_test

# 安装后按插件 ID 选择
ucagent <workspace> <DUT> --plugin formal --plugin-workflow formal:formal --output formal_test
```

也可以把 `ucagent/core/locales/zh.yaml`（或 `~/.ucagent/setting.yaml`）中的 `workflow` 指针改为本工作流，使其成为默认任务工作流（源码树用路径，安装后用 `formal:workflows/formal.yaml`）。

受管理证明的运行预算、慢属性处置和工具限制见[运行说明](docs/execution.md)。

## FlowCanvas 任务页

任务页前端位于 `src/formal/web/`，随 Formal 插件分发。工作台布局和目标操作沿用 [FlowCanvas 5bb2cda](https://github.com/Miical/UCAgent/tree/5bb2cda5f9f4758953108ffdc0d0664398c0f313/plugins/FlowCanvas) 及此前的 Formal 静态原型。对应的 Apache 2.0 许可和声明随前端资源附带。

- `workbench.html` 保留 FlowCanvas 的三栏结构，并在导航、工具栏、页签和对话区域沿用组件类名。
- `flowcanvas-ui.css` 和同名 JS 从上述版本提取基础组件。页签通过 `aria-controls` 绑定面板，已发任务卡接收调用方提供的标题、状态和正文。
- `formal-workbench.css` 负责 Formal 的布局和宿主控件适配。组件样式先加载，便于在更新 FlowCanvas 时单独核对 Formal 的差异。
- `flowcanvas-coverage-actions.js` 和同名 CSS 提供可复用的目标操作组件。它接受目标上下文和提交回调。
- `formal-workbench.js` 将组件接到当前任务的 FG／FC／CK、证明批次、阶段审阅、工具和 Chat。现有任务 API 负责访问工作区和执行。
- `workbench-entry.js` 是任务页的加载入口。从 Master 和命令服务直连打开时，资源与当前任务使用同一服务路径。
