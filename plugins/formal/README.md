# Formal

`Formal` 是面向 UCAgent 的可安装插件，提供基于 SystemVerilog Assertions 的形式化验证工作流：验证规划与功能规格（FG/FC/CK）、SVA 属性实现、验证环境渲染与调试、覆盖率分析、反例测试、Bug 报告与验证总结。工作流资产（`workflows/formal.yaml`、`templates/formal_test`、`skills/`、`Guide_Doc/`）随包分发，技能以 `ext/formal/<skill>` 进入工作区。

Python 发行包名为 `ucagent-formal`，插件 ID 为 `formal`，要求 Python 3.11 及以上。

## 构建与安装

从源码构建并安装：

```bash
cd plugins/formal
python3 -m pip install build
python3 -m build .
python3 -m pip install dist/ucagent_formal-0.1.0-py3-none-any.whl
ucagent --validate-plugin formal
```

## 选用方式

```bash
# 源码树内直接选择（本仓库示例运行方式，见 Makefile 的 formal_% 目标）
ucagent <workspace> <DUT> --plugin plugins/formal --plugin-workflow formal:formal --output formal_test

# 安装后按插件 ID 选择
ucagent <workspace> <DUT> --plugin formal --plugin-workflow formal:formal --output formal_test
```

也可以把 `ucagent/lang/zh/config/default.yaml`（或 `~/.ucagent/setting.yaml`）中的 `workflow` 指针改为本工作流，使其成为默认任务工作流（源码树用路径，安装后用 `formal_plugin:workflows/formal.yaml`）。
