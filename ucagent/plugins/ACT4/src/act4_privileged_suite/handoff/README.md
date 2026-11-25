
# @@SUITE@@：Kunminghu V3 测试资产操作指南

交付状态：**@@STATUS@@**。@@SUMMARY@@

目标：`@@TARGET@@`，单 hart，共 @@COUNT@@ 个 ACT 程序。
适用于整核 SimTop；不能直接作为独立向量、CSR 或 LSU 的接口 testbench。

## 1. 先看什么

本文件是唯一操作指南。`TESTS.md` 是唯一测试索引，按原始 ACT 程序、testcase、
`covergroup/coverpoint` 和 norm rule 组织，提供程序总表、逐用例设计和覆盖点反向查询。
香山功能分类仅辅助导航，不重命名、拆分或替代 ACT 用例。

`src/` 中每个程序开头说明前置条件、初始化、激励过程、结果检查和限制；
各 testcase 前说明测试意图、激励和预期结果。ELF 内有不加载的描述 note，
可运行 `python3 handoff.py describe elf/<原ACT路径>.elf` 读取，不另附逐 ELF 报告。

这里的映射表示静态设计关系，不能当作已测得的覆盖率，也不承诺覆盖完整手册。
`built_not_run` 表示已编译但未在香山运行；`emulator_passed` 表示在所提供 emu 上通过，
其硬件身份仍需双方确认；`emulator_failed` 表示存在失败或超时；`source_only` 不可直接运行。

## 2. 文件与环境

```text
README.md          操作指南
TESTS.md           测试索引和设计说明
src/               保留 ACT 相对路径的运行源码
elf/               最终自检查 ELF
bin/               从同一 ELF 导出的裸二进制
disass/            从同一 ELF 导出的反汇编
config/            test_config.yaml、udb.yaml、sail.json、link.ld、rvmodel_macros.h
framework/         匹配的 ACT 构建依赖、覆盖点定义和规范引用
Makefile           常用命令
handoff.py         独立交付入口
act4_driver.py     ACT 构建和运行支持
manifest.json      文件校验、目标和工具信息，供脚本读取
```

同一程序在 src/elf/bin/disass 下具有相同的 ACT 路径和基本文件名。
没有成功构建时不提供编译产物。交付包不包含生产时的日志、signature、中间 ELF、
AI 记录、重复报告或构建缓存；这些保存在交付方插件输出中。
接收方执行命令后产生的日志和中间结果统一放在 `local/`，不修改交付产物。

直接运行只需 Python 3.11+ 和匹配的 Kunminghu V3 SimTop `emu`。
工具版本和实际硬件配置应与交付方核对；本包不编译香山模拟器。

本次构建记录的工具版本：

@@VERSIONS@@

重新编译还需要 uv、匹配的 RISC-V 编译器及 binutils、Sail 和 ACT/UDB 所需依赖。
先检查，再按需准备：

```bash
make verify
make doctor
make setup TIMEOUT=3600
```

`setup` 复用匹配版本的现有工具，缺失工具按交付的安装配方安装到 `local/tools/`，
无需 UCAgent，不改系统目录。安装可能需要网络、主机架构匹配和现有基础命令；
没有安装配方或探测不通过时，查看 `local/setup/` 的具体诊断，把团队提供的工具加入 PATH 后重试。
ACT 的 Python 依赖通过锁文件在重建时同步。只检查 emu 可用性可用
`make doctor EMU=/path/to/emu`；此检查不证明硬件版本或测试执行通过。

## 3. 直接运行

```bash
make list
make run TEST=@@EXAMPLE@@ EMU=/path/to/emu
make run EMU=/path/to/emu TIMEOUT=14400
```

省略 TEST 运行全部交付程序。TEST 使用 `make list` 中完整的 ACT `.S` 路径，
不是 coverpoint ID，也不是内部 testcase ID。一个程序内的 ACT 测试序列保持完整。
脚本向 emu 传入 `-i ELF --no-diff -C 周期上限`，按 ACT 自检查和 GOOD TRAP 判定，
不运行 NEMU 差分。非零退出、BAD TRAP、SIGRUN、超时或周期上限均不会被当作通过。

运行摘要写入 `local/run-result.json`，其中逐程序记录结果和相应日志路径。
可用 `CYCLES=...` 调整单程序周期上限，`TIMEOUT=...` 调整整次运行时间预算。
本包默认运行 ELF；使用 bin 的其他加载器需按 manifest 中该程序的
`binary_load_address` 和 `entry` 设置加载与入口，并匹配启动状态、内存和退出约定。
bin 不携带 ELF 描述、符号和入口元数据。

## 4. 批量或单程序重建

```bash
make build TEST=@@EXAMPLE@@ JOBS=1
make all JOBS=4 TIMEOUT=14400
make run TEST=@@EXAMPLE@@ EMU=/path/to/emu LOCAL=1
```

每次重建都会在独立副本中按原生 ACT 流程生成中间 ELF、运行 Sail 得到预期值、
再编译最终自检查 ELF，同时导出 bin 和反汇编。不要把 `.sig.elf` 用作最终测试。
产物位于 `local/elf/`、`local/bin/`、`local/disass/`；最新构建结果为 `local/build-result.json`。
`LOCAL=1` 只运行最新成功重建包含的程序，失败时不会回退到旧 ELF。
不加 LOCAL 始终指原始交付产物。`make disass TEST=...` 也通过重建导出对应反汇编。

## 5. 修改和定位问题

定位顺序：在 TESTS.md 找到失败程序及 coverpoint → 阅读 src 中对应 testcase 的设计 →
查看 local/run-result.json 指向的日志 → 对照 disass 中的 PC/指令和 config 中的平台设置 →
只重跑相关程序。构建失败先查看 local/build-result.json 的 errors 和 log，环境失败先看 local/setup。

需要修改输入数据、测试或配置时，先保留原始包，再修改 src/ 或 config/，执行：

```bash
make build TEST=@@EXAMPLE@@ MODIFIED=1
make run TEST=@@EXAMPLE@@ EMU=/path/to/emu LOCAL=1
```

MODIFIED 仅允许源码和配置变更，仍保持原 ACT 程序选择，不支持任意增加新程序或修改框架。
修改后重新生成参考结果，并标记原始说明、规范映射和运行证据需要复核；不能沿用原来的通过结论。
不要删除源码末尾的描述 note；其内容会在工作副本中标记为待复核。
构建后再改源码或配置，LOCAL 运行会要求重新构建。
不要通过削弱断言或修改预期结果把失败变成通过。

反馈问题时请提供：原 ACT 程序路径、失败 testcase/coverpoint（若已定位）、
emu 的提交与配置、实际命令、失败日志和本地修改。启动、平台配置、工具或测试自身问题
都可能造成失败，不能仅凭一次失败断言是 RTL 缺陷。尚未执行的测试请保留未运行状态。

## 6. 本次限制

@@LIMITATIONS@@
