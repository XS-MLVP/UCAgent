---
name: ucv4xs-workflow
description: 仅在已有 ucv4xs 工程中判断基线、配方、完整 RTL/闭包、构建与 UT 的责任边界，保留项目特有的发布和证据经验；独立 UT 不强加香山目录，不用 Skill 替代 ucv 或 ToffeeUT 自动化。
metadata:
  source: ucv4xs/skills/ucv4xs-workflow/SKILL.md
  source_sha256: 3c6e03541e4437fe79ffd8f4d085c6f58231a61acb70645227e68653ffa1716f
  license: MPL-2.0
---

<!-- Adapted from XS-MLVP/ucv4xs. SPDX-License-Identifier: MPL-2.0. License: https://mozilla.org/MPL/2.0/ -->

# 已有 ucv4xs 工程的基线与验证边界

## 适用范围和输入

仅当用户指定的真实工程属于 ucv4xs 时使用。仓库身份由实际根 ucv.json、pyproject.toml、
src/ucv/ 与工程配方共同确认；没有这些条件就回到独立 ToffeeUT 工作流，不创建香山外层
目录，不安装 ucv 来凑结构。本 Skill 不授权升级依赖、修改 RTL、发布或删除文件。

先看当前任务的实际资料和项目维护约定。历史阶段状态、旧 PASS 数及源码基线是三种不同
信息，不能从“结构交付”推断当前硬件已经验收。

## 按任务选已有自动化，不在 Skill 重造

| 当前工作 | 用什么完成机械操作 | 仍需判断什么 |
|---|---|---|
| 盘点/接入本次 UT | UTProject inspect/scaffold；已有工程按 workspace.json 映射 | DUT 层级、资料版本、是否已有可用规格 |
| 查看继承、基线、实际 top/导出类 | 工程已有 ucv list/info 与配方 | 是否覆盖本次参数和配置，不猜默认值 |
| 只读源码/写规格 | 工程已有 source-only 入口或已提供的源码 | 不为阅读启动全量生成、安装或编译 |
| 生成 RTL、求 DUT 闭包、复杂构建 | 工程已有 prepare/build 配方 | 完整生成与 DUT 闭包的来源是否一致 |
| 实际 UT 与本工作流验收 | RunToffee、UTProject audit/summary | 与工程自有 doctor/check/report 的验收范围区分 |
| 工程资料生成和只读审计 | 已有 ucv docs/check、布局与资源审计 | 原生执行、结构一致性、语义正确性分别陈述 |

命令参数以当前工程和版本的 help/配方为准，不照搬其他 DUT、固定并发数或机器路径。
RunToffee 不等于已经调用了 ucv 的基线/布局门禁；需要这些结果时必须真实运行并保留输出。
脚本能够查到的版本、清单、哈希、计数，不让 Skill 手工模拟。

## 基线、生成与构建

1. 保持实际工程的“完整配置的香山 → RTL → DUT 闭包 → Picker → UT”来源链。不能为省事
   私自加单 DUT 源码/配置 override，或用一个独立生成小例子代替本次 DUT。
2. 原工程有统一命名基线与继承约束时，按原配方保留；根、分组、工程的选择共同决定输入。
   缓存里的命令、参数和 hash 不一致时先查来源，不改生成物绕过核验。
3. release 导入与本机生成分别记录，不能给下载文件伪造本机生成收据；已有构建 PASS
   不能成为新源码、新工具链或新 ABI 的证据。
4. 工具升级可能改变构建缓存身份和重建范围。只有任务明确授权才改变锁和环境，并让操作
   留在选定的同一个 venv；不修改用户原有 ucv4xs 环境，不建立宿主/runner 双运行环境。
5. 缺工具或原生重建未做，照实写未执行/未验证。只读配置检查不默认升级成各工程全量仿真。

## Toffee 能力和项目补充

使用锁定的 uc-toffee（导入 toffee）及对应文档，先查框架，再写工程端口/事务/模型。
不能把分发名、导入名、源码 tag 混为一谈，也不能仅凭 API 名存在认证全部行为。
实现分层见[package-layout](../package-layout/SKILL.md)。

源码断言可能在生成时被裁掉；需要被动不变量检查时，明确替代了哪些性质、遗漏什么。
Monitor 非消费式快照、DUT 加载、特殊多接口装配等能力先核对当前公开 API，再说明工程
补充差异。原生覆盖的原始计数与 HTML/LCOV 展示口径分别核实，不从行覆盖推断全部分支
或 toggle，也不声称 first/last metadata 是完整逐例归因。

## 工程和资料接入

- 保留 ucv.json、workspace.json、真实 top、导出类与 suites.* 命名空间；按 testbench
  显式映射共享参数化实现，不根据文件路径隐式选择模型。
- 规格归 docs/spec，问题归 docs/bugs，README 为入口。稳定 ID 与历史命令、路径、日期、
  hash、判定保留原义，不为了术语或目录整理重写历史。
- DUT 与 shared 同用 env、transactions、model、checker、coverage、tests 六职责，按需
  单文件或包；shared 无独立 DUT/top，不能成为任意跨目录文件的垃圾桶。
- 根 conftest.py 统一注册；DUT 专用参数生成在其 tests，通用插件在 shared/env，离线审计
  在 tools。原工程有封闭白名单时使用通用规则，不为单个 DUT 加目录豁免。
- 整理、清理前先确认用途与活动状态，保留必要归档，未经授权不删除。引脚别名不代表
  typed transaction、独立采样或比较已经完成。
- 修改验证语义时，按[完备性入口](../verification-completeness/SKILL.md)核对来源映射、
  类别 × 结果域、未分类项与可执行自检；资料检查通过不等于功能覆盖提升。

## 仅在明确授权发布完整 RTL 时

这些是原项目特有的发布边界，不是所有 UT 的默认任务：

1. 发布某 commit 的完整香山 RTL，不从单 DUT 闭包拼装整芯片；确认 baseline 与真实生成
   命令。模块 UT 结果只是这份 RTL 的一条记录，不改变发布范围。
2. 保留生成器给出的权威 filelist、依赖顺序和原路径语义，不用通配替换或手改原件。
3. 附真实 commit、子模块、design/生成参数、工具版本、完整命令、许可与逐文件校验和。
4. 说明源码断言层是否保留，以及条件编译的 difftest 等外部依赖边界，不能暗示独立编译
   已验证全部集成功能。
5. 与上游生成命令的差异逐项核对，不能把另一个生成目标的后处理归给当前产物。
6. 打包、解压、校验、lint 与发布后下载比对交给已有脚本；只陈述实际执行的检查。
7. 发布身份跟随实际设计基线，不用工具仓库版本号替代。远端写入必须另有用户授权。

## 待审参考、历史来源和退出

[待审索引](references/pending/README.md)保留四篇升级/迁移经验，但不是默认启用的 Skill 或
新的强制验收标准；按实际任务和授权试用。[来源记录](references/SOURCES.md)说明实际读取
快照和适配范围，源目录含未提交修订，不能把内容全说成某个 commit 的正式发布。

分别报告构建、实际用例判定、覆盖、范围残余。真实 FAIL 留下，不修改模型对齐 RTL 或
扩大 XFAIL。文档、模型自检、原生回归是不同证据层级；本入口不声称替用户运行过它们。
