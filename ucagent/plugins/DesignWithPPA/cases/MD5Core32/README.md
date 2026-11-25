
# MD5Core32

MD5Core32 是一个可综合、可验证的 MD5 哈希加速核心，支持不定长输入消息流式喂入并输出 32-bit 截断哈希值。它用于演示 DesignWithPPA 的单元模块 TDD 工作流在数据通路+迭代运算场景下的能力：工作流读取本 README 和 `spec/` 下的设计规格，在解析后的 `{OUT}` 中动态生成 Python 可执行规格、同套功能测试、选定语言的电路源码、性能测试波形、PPA 报告和版本性能曲线。

本目录是只读设计输入。请勿在此目录写入 RTL、Python 测试、波形、sidecar、PPA 报告、账本或工作流过程文档；这些产物必须落在 `{OUT}`。工作流应自动完成组合/时序性质判断，不要求使用者声明设计类型。

## 设计目标

实现 MD5 消息摘要算法的硬件加速核心，支持变长消息流式处理，输出 MD5 的第四个链式变量终值 `D` 作为 32-bit 哈希结果。用户通过 valid/ready 握手逐拍喂入 32-bit 数据字（小端打包），最后以 `last_i=1` 标记消息结束，并用 `byte_len_i`（0–3）指明最后一个数据字携带的有效字节数；总长度为 4 的倍数的消息把全部数据放在非 final 字中，再以一个 `byte_len_i=0` 的终止字结束（其 `data_i` 被忽略），空消息就是单独一个这样的终止字。核心在内部完成 MD5 padding、64 轮主循环和链式变量更新，最终输出截断的 32-bit 哈希。

Python reference 不是 mock：必须实现与标准 MD5 一致的 padding、四轮非线性函数、常量表加法、左移量、小端打包和初始链值。RTL 与 reference 的结果必须逐哈希一致。

### 规范参考向量

截断输出定义为第四个链式变量的终值 `D`（即 RFC 1321 摘要第 12–15 字节按小端解释的值），不是摘要字符串的其他切片：

- 空消息（0 字节）：MD5 = `d41d8cd98f00b204e9800998ecf8427e`，`D` = `0x7e42f8ec`。
- `"abc"`（3 字节）：MD5 = `900150983cd24fb0d6963f7d28e17f72`，`D` = `0x727fe128`。
- `"The quick brown fox jumps over the lazy dog"`：MD5 = `9e107d9d372bb6826bd81d3542a419d6`，`D` = `0xd619a442`。

这些向量是 normative examples；生成的 smoke 测试必须手工推导 expected，不能读取 DUT 输出后再赋给 `expected`。

## 工作流运行

在包含本案例目录的 workspace 中，使用 `MD5Core32` 作为 DUT 名称，并选择 `DesignWithPPA` 插件的 `unit-design-tdd` 工作流。默认至少尝试 5 个候选优化版本；可通过 `DESIGN_WITH_PPA_MIN_OPTIMIZATION_ITERATIONS` 设置最少轮数，通过 `DESIGN_WITH_PPA_MAX_OPTIMIZATION_ITERATIONS` 设置默认 1000 轮的安全上限，并通过 `DESIGN_WITH_PPA_NO_IMPROVEMENT_PATIENCE` 设置默认 3 次的连续无改善容忍次数。候选接受门禁默认只要求 performance 与 timing 两类指标不回退，即在不降低性能与频率/时序的前提下尽可能优化面积与功耗；可通过 `DESIGN_WITH_PPA_NO_REGRESSION_METRICS` 指定逗号分隔的类别子集（可选 performance、area、timing、power，设为全部四类即要求所有指标都不回退，设为空表示不设无回退保护，仅需至少一项指标改善即接受）。版本 0 是功能全通过的 base，后续 accepted/rejected 版本和相对 base 的改善曲线由工作流自动写入 `{OUT}`。

工作流最后应至少交付：

- 可综合的电路源码和完整功能回归通过的同套 Python/RTL 测试；
- 短消息、多块消息和长消息各自的 latency/throughput 性能 TC、独立波形和 sidecar；
- 可追溯的性能合同、base/final PPA 和每个评估版本的优化账本；
- `{OUT}/MD5Core32_performance_curve.json` 与 `{OUT}/MD5Core32_ppa_dashboard.html`，看板直接从 JSON 绘制各长度类别的性能以及 area、timing、power 的版本变化。

## 输入与输出边界

输入仅包括本 README 和 `spec/*.md`。所有生成文件写入 `{OUT}`；不得修改、删除或创建 `{DUT}` 下的文件。Spec 的物理行必须映射到 FG/FC/CK 或有理由的 `IGNORE`，性能指标必须在性能合同中保留 Spec 路径与行号。
