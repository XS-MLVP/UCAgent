
# Master 模式

Master 用于创建、启动和监控多个验证任务。浏览器面板负责创建工作区、上传和编译 RTL、下发任务以及查看日志。

## 4.1 启动 Master

源码仓库中：

```bash
# 临时 Master 工作区
make as_master

# 指定或使用默认持久化工作区（默认 /tmp/ucagent_master）
make as_master_persist
```

不使用 Makefile 时：

```bash
ucagent --as-master --export-cmd-api
ucagent --as-master-persist --as-master
```

`--as-master-persist` 必须和 `--as-master` 一起使用。默认 Master 地址来自 `master_api` 配置，通常是 `http://127.0.0.1:8800`；需要保护面板时加 `--as-master-password <password>`，需要限制客户端注册时加 `--as-master-key <key>`。

## 4.2 创建并编译任务

1. 在浏览器打开 Master 地址，进入 **Launch**。
2. 创建工作区并上传 RTL、README 或其他需求文件。
3. 标记一个 **Main RTL**（也可以提供 filelist），标记验证需求文件为 **Verification Needs**。
4. 选择顶层模块，点击 **Compile**。编译由 picker 完成，语法或参数错误需要根据 Compile Console 修复。

标签和页面字段会随版本变化；以当前页面的必填提示和命令预览为准。编译成功只表示 DUT 包生成成功，不代表验证已经完成。

## 4.3 启动子 Agent

在 **Launch Settings** 中选择：

- **Config Path**：通常选择 `UT`，对应默认单元测试流程；也可以选择配置中提供的 Formal、Vibe 或 Increment。
- **Backend**：默认来自 `launch.default_args.backend`，当前为 `opencode`；也可以选择 `langchain`、`codex` 等已配置后端。
- **Launch Mode**：默认 `process`，也支持 Docker、Docker Swarm 和 Kubernetes（需要相应环境）。
- **CLI Flags**：按需开启 TUI、流式输出或完成后退出。

把模型相关环境变量填入 **Environment Variables**。子 Agent 的配置方式见 [Web Master 使用指南](../02_usage/07_web_master.md)。点击 **Launch Task** 后，Master 拉起子 Agent 并等待其通过 `--master` 注册。

## 4.4 监控和复盘

- **Dashboard**：查看 Agent 在线状态、进度和离线任务。
- **Task**：查看启动命令、stdout/stderr、任务状态，停止或删除托管任务。
- **Agent**：查看阶段、文件和 Diff，可批量切换 HM、Skip、LFail、LPass。
- **Web Terminal**：进入子 Agent 的终端；是否可与本地终端并行取决于子 Agent 启动参数。

最终是否有 Bug、波形或覆盖率报告取决于工作流、测试结果和配置。请以工作区的真实产物、Checker 返回值和 `uc_test_report/` 为准，不要把页面显示的完成状态当作 DUT 正确性的证明。

更多页面能力、代理和访问控制见 [Web Master 使用指南](../02_usage/07_web_master.md)。
