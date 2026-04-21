# 文档补丁包：Web Master 与近期功能增量

本文档用于审查后再手工改原文。所有建议补丁集中在一个文件内。

- 目标：补齐手册对近期新增能力的覆盖
- 范围：README、02_usage、03_develop、04_case、导航
- 使用方式：按小节复制粘贴到对应文件

---

## Patch 1: README.zh 增补章节

目标文件：README.zh.md
建议位置：现有“通过Web界面交互”章节之后

~~~md
## Web Master 新增能力（近期）

以下能力已在近期版本中上线，建议结合本文其他章节使用：

1. Launch 页面：可在浏览器内完成工作区创建、文件导入/上传、模块解析、编译与启动参数预览。
2. Task 页面：支持托管任务筛选、分页、详情与日志查看，以及停止/删除操作。
3. Agent 页面增强：支持阶段多选与批量开关（HM/Skip/LFail/LPass），并支持阶段产物文件内容与 Diff 复盘。
4. 统一代理访问：Master 可统一代理 task/agent 的 cmd、terminal、web-console 路径，减少跨地址跳转。
5. Web Terminal 增强：支持多会话访问（不同 URL）。

建议阅读：docs/content/02_usage/07_web_master.md
~~~

---

## Patch 2: README.en 增补章节

目标文件：README.en.md
建议位置：现有 Web interaction 相关段落后

~~~md
## Recent Web Master Enhancements

The following capabilities were added recently and are now available in Web Master workflows:

1. Launch page: create workspace, upload/import files, parse modules, compile, and preview launch command.
2. Task page: filter, paginate, inspect task details/logs, and stop/delete managed tasks.
3. Enhanced Agent page: stage multi-select and bulk toggles (HM/Skip/LFail/LPass), plus stage artifact content/diff review.
4. Unified proxy access: Master proxies cmd/terminal/web-console paths for both task and agent entries.
5. Improved Web Terminal: multiple terminal sessions across different URLs.

See also: docs/content/02_usage/07_web_master.md
~~~

---

## Patch 3: 参数文档补充“页面能力映射”

目标文件：docs/content/02_usage/03_option.md
建议位置：在“--web-console 与 --web-terminal 区别”小节之后

~~~md
### Web 页面能力映射（补充）

参数用于开启入口，页面用于完成操作。推荐映射如下：

1. --as-master / --as-master-persist
   - 打开 Master Dashboard（总览）
   - 可进入 Launch 与 Task 页面
2. --master
   - 将 Agent 连接到指定 Master
   - 在 Master 页面统一查看与管理
3. --export-cmd-api
   - 为托管任务暴露 CMD API
   - Task 页面可查看命令与日志，Agent 页面可通过代理访问
4. --web-console
   - 提供 Web 控制页面（独立浏览器交互）
5. --web-terminal
   - 提供 Web 终端访问，并允许本地终端同时操作

页面级新增能力（非独立 CLI 参数）：

1. Launch：工作区创建、文件管理、模块解析、编译与命令预览
2. Task：任务筛选、分页、详情、日志、停止/删除
3. Agent：阶段批量开关（HM/Skip/LFail/LPass）与阶段产物 Diff 复盘
~~~

---

## Patch 4: TUI 文档补充“与 Web 协同”

目标文件：docs/content/02_usage/04_tui.md
建议位置：文末新增小节

~~~md
## 与 Web Master 协同使用

TUI 与 Web 并非互斥，推荐按场景组合：

1. TUI 适合本地快速调试与细粒度命令输入。
2. Web Master 适合集群化观察、托管任务运维与远程协作。

协同建议：

1. 用 Launch 页面完成文件准备与编译启动。
2. 用 Task 页面跟踪启动与日志。
3. 进入 Agent 页面执行阶段批量控制与结果复盘。
4. 需要本地即时修复时，切回 TUI 或本地终端。

注意：

1. 启用 web-terminal 时，可与本地终端并行。
2. 多终端会话场景建议用不同 URL 或页签区分任务。
~~~

---

## Patch 5: 人机协同文档补充“页面操作等价命令”

目标文件：docs/content/02_usage/02_assit.md
建议位置：命令清单后新增小节

~~~md
## Web Agent 页面与命令等价关系

在 Agent 页面可直接完成以下等价操作：

1. HM 开关：等价于阶段人工审核开关调整。
2. Skip/Unskip：等价于阶段跳过状态切换。
3. LFail/LPass：等价于阶段 LLM Fail/Pass 建议开关。
4. 多选批量操作：等价于对多个阶段重复执行同类命令。

建议流程：

1. 先在页面批量设置策略。
2. 再执行检查与推进。
3. 对失败阶段进入文件与 Diff 视图复盘。
~~~

---

## Patch 6: 架构文档补充“Master 三页面 + 统一代理”

目标文件：docs/content/03_develop/02_architecture.md
建议位置：核心架构章节后新增小节

~~~md
## Web Master 架构补充

近期版本在 Master 侧形成三页面协同架构：

1. Dashboard（master.html）
   - Agent 汇总、过滤、排序、分页、离线策略
2. Launch（launch.html）
   - 工作区准备、文件导入、模块解析、编译、启动编排
3. Task（task.html）
   - 托管任务列表、状态与日志运维

统一代理层：

1. 对 task/agent 提供 cmd 代理路径
2. 对 task/agent 提供 terminal 代理路径
3. 对 task/agent 提供 web-console 代理路径
4. 支持 WebSocket 转发与重连增强
~~~

---

## Patch 7: 工作流文档补充“阶段复盘”

目标文件：docs/content/03_develop/03_workflow.md
建议位置：阶段控制说明段后新增小节

~~~md
## 阶段复盘（Web 视角）

除命令行与 TUI 方式外，可在 Agent 页面进行阶段级复盘：

1. 查看阶段产物文件清单
2. 预览文件内容
3. 切换 Diff 视图分析改动
4. 配合阶段开关（HM/Skip/LFail/LPass）快速迭代

建议：

1. 对连续失败阶段优先查看 Diff 与错误日志。
2. 对风险阶段先启用 HM 或 LFail，再继续推进。
~~~

---

## Patch 8: 多任务案例补充“Dashboard 运维动作”

目标文件：docs/content/04_case/01_multirun.md
建议位置：并发运行说明后新增小节

~~~md
## Web Master 运维建议（多任务场景）

当并发任务数量较多时，建议通过 Dashboard 提升运维效率：

1. 使用状态过滤快速定位异常 Agent。
2. 使用排序（last_seen/progress）识别卡住任务。
3. 使用分页避免单页过载。
4. 启用离线自动清理，保持列表整洁。
~~~

---

## Patch 9: 批量案例补充“Task 页面闭环”

目标文件：docs/content/04_case/02_batchrun.md
建议位置：批量执行脚本说明后新增小节

~~~md
## 通过 Task 页面做批量任务闭环

批量任务启动后，建议在 Task 页面完成闭环运维：

1. 按 DUT 或关键字过滤任务。
2. 按状态聚焦 failed/stopped 任务。
3. 进入任务详情查看 command 与日志。
4. 必要时 stop 后修复配置并重启任务。
~~~

---

## Patch 10: 新增专页（全文）

目标文件：docs/content/02_usage/07_web_master.md
建议动作：若文件不存在则新建；若已存在则按需替换为下列模板骨架

~~~md
# Web Master 使用指南

## 1. 功能概览

1. Dashboard：总览、筛选、排序、分页、离线策略
2. Launch：工作区创建、文件导入、模块解析、编译、命令预览
3. Task：托管任务列表、详情、日志、停止/删除
4. Agent：阶段批量开关与阶段产物 Diff 复盘
5. Web Terminal：在线终端并行访问

## 2. 快速开始

~~~bash
ucagent --as-master-persist --as-master
~~~

访问地址：

~~~text
http://localhost:8800
~~~

## 3. Dashboard

1. 搜索、过滤、排序、分页
2. 批量删除与离线自动清理

## 4. Launch

1. 创建工作区
2. 上传/导入文件
3. 解析模块与编译
4. 预览命令并启动任务

## 5. Task

1. 筛选与分页
2. 查看详情与日志
3. 停止或删除任务

## 6. Agent

1. 阶段快捷开关：HM/Skip/LFail/LPass
2. 多选批量设置
3. 阶段文件内容与 Diff 复盘

## 7. 代理与网络排障

1. 页面可访问但子路径失败：检查代理与鉴权
2. WebSocket 波动：检查网关是否放通 WS
3. 远程访问异常：检查监听地址与端口暴露

## 8. 安全建议

1. 共享网络务必启用密码保护
2. 对外暴露建议加 TLS 与网关鉴权
~~~

---

## Patch 11: 导航接入

目标文件：docs/mkdocs.yml
建议位置：nav 下 02_usage 分组

~~~yaml
- 使用:
  - 00_mcp: content/02_usage/00_mcp.md
  - 01_direct: content/02_usage/01_direct.md
  - 02_assit: content/02_usage/02_assit.md
  - 03_option: content/02_usage/03_option.md
  - 04_tui: content/02_usage/04_tui.md
  - 05_faq: content/02_usage/05_faq.md
  - 06_llm_check: content/02_usage/06_llm_check.md
  - 07_web_master: content/02_usage/07_web_master.md
~~~

---

## 审查清单

1. 术语统一：Web Master、Launch、Task、Agent、Web Terminal。
2. 中英文一致：README.zh 与 README.en 同步。
3. 参数与行为解耦：参数页说明入口，专页说明操作流。
4. 案例可执行：案例中加入页面化运维闭环。
5. 导航可达：07_web_master 已在 mkdocs 导航中可见。
