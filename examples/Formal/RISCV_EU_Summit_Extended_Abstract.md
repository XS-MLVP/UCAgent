# Automated Formal Verification of RISC-V Designs Using an LLM-Driven Agent

**Extended Abstract — RISC-V European Summit Poster Submission**

---

## Abstract

Formal verification offers mathematical completeness guarantees that simulation cannot match, yet its widespread adoption in processor and SoC design flows is still limited by the high barrier of expertise required to write SystemVerilog Assertions (SVA) and configure model-checking environments. This paper presents **Formal Agent**, an LLM-driven automated formal verification agent built on top of the UCAgent (UnityChip Verification Agent) framework, which orchestrates the entire formal verification lifecycle — from RTL analysis to SVA generation, tool execution, and bug reporting — with minimal human intervention.

## Motivation

RISC-V designs, ranging from simple arithmetic units to complex pipeline controllers, share a common verification challenge: ensuring functional correctness across all reachable states. Traditional simulation-based approaches provide incomplete coverage, while formal methods, though complete, demand significant manual effort to author assertions, constrain the environment, and interpret counterexamples. As RISC-V cores grow in complexity, scalable automation of formal verification becomes increasingly critical.

## Approach

Formal Agent decomposes the verification problem into a structured eight-stage pipeline, each driven by an LLM acting as a formal verification architect:

1. **Requirement Analysis & Planning** — Identifies the design scope and formulates a verification plan.
2. **DUT Function Understanding** — Parses RTL interfaces, clock domains, and internal structure via `pyslang`.
3. **Functional Specification Analysis** — Decomposes design intent into a hierarchical taxonomy of Functional Groups (`<FG>`), Function Points (`<FC>`), and Check Points (`<CK>`), each annotated with a property style (`Comb`, `Seq`, `Assume`, `Cover`).
4. **Environment Generation** — Generates a synthesizable **Checker** (`_checker.sv`) and a transparent **Wrapper** (`_wrapper.sv`) by automatic RTL port extraction, creating white-box visibility into internal signals such as state-machine registers, pointers, and flags.
5. **SVA Property Generation** — Translates every `<CK>` annotation into corresponding SVA code, enforcing safety invariants, liveness (`s_eventually`), and reachability (`cover property`) with symbolic indexing (`fv_idx`) for array-heavy designs.
6. **Script Generation** — Auto-generates model-checker TCL scripts (targeting FormalMC / Avi) via the `GenerateFormalScript` tool.
7. **Environment Debugging** — Iteratively detects and eliminates `TRIVIALLY_TRUE` properties caused by over-constrained assumptions, guided by log parsing and LLM root-cause analysis.
8. **Bug Analysis & Reporting** — Classifies `FALSE` properties as confirmed RTL defects, produces structured bug reports with counterexample analysis, root-cause localization, and fix suggestions.

## Key Technical Contributions

- **Style-Annotated Specification Language**: A structured `<FG>/<FC>/<CK>` tagging system guides the LLM to generate syntactically correct and semantically precise SVA without ambiguity.
- **Symbolic Indexing Protocol**: Enforces three mandatory `fv_idx` constraints (`STABLE`, `VALID`, `KNOWN`) to prevent false positives in array-based structures such as RISC-V register files and FIFOs.
- **Automated Vacuity Prevention**: Coverage properties are automatically inserted for all critical states (Full, Empty, Hit) to guarantee the verification environment is not over-constrained.
- **White-Box Extraction**: Internal signals are surfaced through a generated wrapper, enabling proofs that reference pipeline registers, arbitration state machines, and control flags directly.
- **MCP Integration**: The agent exposes its tools via the Model Context Protocol (MCP), enabling seamless collaboration with external Code Agents (e.g., OpenHands, Claude Code, Copilot, Qwen-Code).

## Demonstration

We demonstrate Formal Agent on a traffic-light controller that intentionally contains a state-transition bug (a `RED → RED` self-loop in the highway control FSM). Without any manual assertion authoring, the agent correctly:
- Generated 29 SVA properties across 5 functional groups (Safety, Control, Liveness, Coverage, API);
- Identified and resolved TRIVIALLY_TRUE environment issues autonomously;
- Proved all safety and reachability properties (`PASS`);
- Captured the liveness violation (`A_CK_LIVE_HWY_GREEN`, `A_CK_LIVE_FARM_GREEN`) via `s_eventually` and localized the defect to `traffic.v:178`.

The complete workflow, from raw RTL to a verified bug report, required zero hand-written SVA and zero manual tool invocation.

## Conclusion & Outlook

Formal Agent demonstrates that LLMs can serve as effective formal verification engineers when guided by structured, style-annotated specifications. By combining automatic RTL parsing, constraint-aware SVA generation, and iterative debugging, the framework removes the principal barrier to adopting formal methods in RISC-V design flows. Future work will extend Formal Agent to multi-clock designs, parameterized cores, and integration with a RISC-V instruction-set formal model for end-to-end ISA compliance checking.

---

*UCAgent / Formal Agent is open-source: https://github.com/XS-MLVP/UCAgent*

---

# 基于大语言模型驱动 Agent 的 RISC-V 设计自动化形式化验证

**扩展摘要 — RISC-V 欧洲峰会海报投稿**

---

## 摘要

形式化验证能够提供仿真无法企及的数学完备性保证，然而其在处理器与 SoC 设计流程中的广泛普及仍受制于较高的专业门槛——尤其是编写 SystemVerilog 断言（SVA）和配置模型检查环境。本文提出 **Formal Agent**，一款构建于 UCAgent（UnityChip Verification Agent）框架之上的大语言模型（LLM）驱动自动化形式化验证代理，能够以极少的人工干预完整编排验证生命周期——涵盖从 RTL 分析、SVA 生成、工具执行直至缺陷报告的全流程。

## 研究动机

RISC-V 设计从简单的算术单元到复杂的流水线控制器，均面临共同的验证挑战：在所有可达状态下保证功能正确性。基于仿真的传统方法覆盖率有限，而形式化方法虽然完备，却需要大量手工劳动来编写断言、约束验证环境并解读反例。随着 RISC-V 内核复杂度的持续增长，形式化验证的规模化自动化变得愈发迫切。

## 方法

Formal Agent 将验证问题分解为结构化的八阶段流水线，每个阶段由一个扮演形式化验证架构师角色的 LLM 驱动：

1. **需求分析与验证规划** — 明确设计范围，制定验证计划。
2. **DUT 功能理解** — 通过 `pyslang` 解析 RTL 接口、时钟域与内部结构。
3. **功能规格分析** — 将设计意图分解为层次化分类体系：功能分组（`<FG>`）、功能点（`<FC>`）、检测点（`<CK>`），每个检测点均标注属性风格（`Comb`、`Seq`、`Assume`、`Cover`）。
4. **验证环境生成** — 通过自动 RTL 端口提取，生成可综合的 **Checker**（`_checker.sv`）和透明 **Wrapper**（`_wrapper.sv`），实现对状态机寄存器、指针和标志位等内部信号的白盒可见性。
5. **SVA 属性生成** — 将每个 `<CK>` 标注转化为对应的 SVA 代码，对阵列密集型设计（如寄存器堆）强制采用符号化索引（`fv_idx`），覆盖安全性不变量、活性（`s_eventually`）和可达性（`cover property`）。
6. **脚本生成** — 通过 `GenerateFormalScript` 工具自动生成模型检查器 TCL 脚本（适配 FormalMC / Avi）。
7. **环境调试** — 解析工具日志，迭代检测并消除由过度约束导致的 `TRIVIALLY_TRUE` 属性，由 LLM 进行根因分析并修正。
8. **缺陷分析与报告** — 将 `FALSE` 属性分类为已确认的 RTL 缺陷，生成包含反例分析、根因定位与修复建议的结构化缺陷报告。

## 核心技术贡献

- **风格标注规格语言**：结构化的 `<FG>/<FC>/<CK>` 标签系统引导 LLM 无歧义地生成语法正确、语义精确的 SVA。
- **符号化索引协议**：强制添加三条必要的 `fv_idx` 约束（`STABLE`、`VALID`、`KNOWN`），防止 RISC-V 寄存器堆、FIFO 等阵列型结构产生假阳性错误。
- **自动化空证明防御**：为所有关键状态（Full、Empty、Hit 等）自动插入覆盖率属性，确保验证环境不过度约束设计空间。
- **白盒信号提取**：通过自动生成的 Wrapper 将流水线寄存器、仲裁状态机和控制标志等内部信号引出，使证明能够直接引用内部状态。
- **MCP 协议集成**：代理通过模型上下文协议（MCP）暴露工具接口，可与外部 Code Agent（如 OpenHands、Claude Code、Copilot、Qwen-Code）无缝协作。

## 实验验证

我们以一个内置状态转换 Bug 的交通灯控制器为案例进行演示（高速公路控制 FSM 中存在 `RED → RED` 自环缺陷）。在无任何手工断言编写的前提下，Formal Agent 自动完成了以下工作：

- 在 5 个功能组（Safety、Control、Liveness、Coverage、API）下生成 **29 条 SVA 属性**；
- 自主识别并修复环境过约束导致的 TRIVIALLY_TRUE 问题；
- 证明所有安全性与可达性属性（`PASS`）；
- 通过 `s_eventually` 捕获活性违例（`A_CK_LIVE_HWY_GREEN`、`A_CK_LIVE_FARM_GREEN`），并精准定位缺陷至 `traffic.v:178`。

从原始 RTL 到完整缺陷报告的全流程，**无需手写任何 SVA，无需手动调用任何工具**。

## 结论与展望

Formal Agent 证明了大语言模型在结构化、风格标注规格的引导下，能够胜任形式化验证工程师的工作。通过将自动化 RTL 解析、约束感知的 SVA 生成与迭代式调试相结合，该框架消除了 RISC-V 设计流程采用形式化方法的主要障碍。未来工作将向多时钟域设计、参数化内核扩展，并计划与 RISC-V 指令集形式化模型集成，实现端到端的 ISA 合规性检查。

---

*UCAgent / Formal Agent 开源地址：https://github.com/XS-MLVP/UCAgent*
