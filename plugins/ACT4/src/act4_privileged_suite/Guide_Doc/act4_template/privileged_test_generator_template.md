<!-- SPDX-License-Identifier: Apache-2.0 -->

# ACT4 Privileged Test Generator 设计模板

适用阶段：04_generator；生成源码和运行证据在 05_build 检查。
先读[模板说明](README.md)、[VM 模板](privileged_vm_resource_template.md)与
[验证交付模板](privileged_validation_handoff_template.md)。

## 1. 冻结接口与写入边界

逐项读取本轮 ACT4 HEAD 中的：
- `docs/DeveloperGuide.md` 的 privileged generator 章节；
- `generators/testgen/src/testgen/priv/registry.py`；
- `data/state.py`、`data/test_chunk.py`、`generate/priv.py` 和实际 writer；
- `constants.py` 中 `TESTCASES_PER_PRIV_FILE`；
- 同版本相似 generator、目标配置与被使用宏的 define/include/undef 顺序。

data、generate 和 constants 路径相对 `generators/testgen/src/testgen/`；registry 项已写完整路径。
记录 callable 返回类型和 chunk lifecycle；源码与文档不一致时报告差异。

仅新建 `riscv-arch-test/generators/testgen/src/testgen/priv/extensions/{DUT}.py`，
并迭代本次新建文件。若基线已存在同名 generator/coverage/mapping，按工作流阻塞，
不能覆盖。registry、writer、template、tests/env、target config 等仍受保护。

## 2. 注册参数

| 参数 | 填写依据 | 审查点 |
| --- | --- | --- |
| suite key | CTP 精确名称 | 大小写与路径一致 |
| required_extensions | 每条实际指令/CSR 和目标配置 | 使用当前 registry 参数类型 |
| march_extensions | 当前 API 的 MARCH 派生规则 | 只补充实际需要的 ISA |
| params | 当前 registry API | 不照搬旧版参数结构 |
| extra_defines | 已审计 suite opt-in 原生入口 | 不伪造 `*_SUPPORTED` 或 `RVTEST_SELFCHECK` |
| testcases_per_file | 冻结 constants 源码及 testcase 成本 | 显式正整数，不高于当前上限 |

不要按 H 扩展名推测“启用 H”的宏。UDB capability、编译 ISA、公共 trap 服务和
参考模型/RVVI 能力分别核实。BOOT_TO_* 等 opt-in 仅在审计允许后使用。

## 3. TestChunk 生命周期

下面只展示控制结构，是伪代码，不是可注册运行的测试；省略号必须换成实际激励与观测。
当前 API 接受 `Sequence[TestChunk]`，可具体返回 `list[TestChunk]` 或 tuple；限定模块名和字符串形式的类型注解也合法。
同一 suite 可注册多个不同生成函数，各 entry 保留自己的 metadata。静态解析无法追踪的 helper
或类型别名作为待复核项，通过原生生成验证，不以“未看见”直接推断实现错误。

```python
from collections.abc import Sequence
from testgen.data.state import TestData
from testgen.data.test_chunk import TestChunk
from testgen.priv.registry import add_priv_test_generator

# 填入已审计的 suite key、required_extensions、testcases_per_file 等参数。
# @add_priv_test_generator(...)
def make_suite(test_data: TestData) -> Sequence[TestChunk]:
    test_chunks: list[TestChunk] = []
    tc = test_data.begin_test_chunk()
    label = test_data.add_testcase(
        bin_name="operation_variant",
        coverpoint="cp_operation_context",
        covergroup="suite_cg",
    )
    tc.code.append(label)
    # tc.code.extend(...): 保存状态、建立 profile、操作、观测、signature、恢复。
    # tc.raw_data.extend(...): 仅放本 profile 实际消费的 suite-local 数据。
    test_chunks.append(test_data.end_test_chunk())
    return test_chunks
```

`add_testcase` 需要先有 active chunk；它产生描述符、计数并返回 label 行，返回值要写入
code。不能只调用它以满足静态 linkage。begin/end 会保存 signature/data pointer 寄存器
分配快照，供 writer 在拆分后恢复。

`new_test_chunk(test_chunks, split_name=None)` 会结束并追加已有 chunk，再开始新 chunk；
不要额外追加同一个结束结果。遍历完成后仅 end/append 最后的 active chunk。
`split_name` 只在不同组确需独立环境或命名时使用，保持连续且不复用。

## 4. 按 target/profile 实现完整序列

每个 helper 前写 comment_banner，并在设计记录中填下表：

| Target / profile / variant | 前置状态 | 实际操作 | 正常/异常观测 | Signature 内容 | 恢复及最终模式 |
| --- | --- | --- | --- | --- | --- |
| 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |

实现要求：
1. 使用当前 register allocator，按实际可用数量申请并释放；不硬编码临时 xN。
2. CSR 和 signature 优先使用同版本现有 helper。核对返回 str 还是 list[str]，分别
   append/extend；`_csrr/_csrw/_csrs/_csrc` 等返回字符串不能裸调用丢弃。
3. CSR 字段更新须等价于 `(old & ~mask) | (field & mask)`。保存 old 的寄存器/内存不得
   被待写 field 覆盖。逐项列出 CSR、save location、restore 指令、异常路径和生成 .S 证据。
4. 可能 trap 的指令后补 `nop` 或 `c.nop`；预期异常须检查 cause、trap 路由、返回 PC、
   返回模式和后续进度，不能把任意 trap 视为预期成功。
5. 用 Python 展开重复激励，不生成汇编运行循环。所有标签包括数据/handler 标签在
   拼接后的文件内唯一；只给 testcase label 加 mode 后缀并不自动保证辅助标签唯一。
6. CSR 字段扫描必须依据 CSR 自身访问位宽和规范允许的字段范围。RV32 下高半 CSR
   仍按其自身宽度处理；不能统一生成 64 个 bit testcase，再用互斥 XLEN 条件隐藏非法值。
   生成后应确认 `_str` 描述符对应的入口标签在适用 XLEN 下可达。
7. 不生成 writer 负责的 YAML header、RVTEST_BEGIN 或 CODE_END；不手工修改 .S。
8. 每个不可分割 chunk 应构成完整 setup/teardown 单元。跨文件不得依赖上一个文件的
   CSR/页表初始化。优先细分超大 chunk；原生分文件不拆开单个 chunk，确实不可拆时
   在既有审查项说明，派生阈值检查记 warning。显式配置的硬性文件上限仍可报错。

## 5. VM 与公共服务

AI 在编写 generator 时依据 contract 选择并落实 profile，不从 suite 名推测 Sv39 或 guest execution。
contract 是设计和审查输入；ACT4 generator 不得读取或探测它、JSON projection、
AI review、manifest 或 `unity_test/`，也不得导入 ITGen、UCAgent 或 `act4_privileged_suite`。
文件缺失时跳过的可选加载同样不允许。必要参数和序列写入 generator，审查状态、契约 hash
和一致性检查保留在 suite 的审查资产中。
允许 ACT4 原生 API、仓库资源及注册参数；profile 注释由测试语义确定。
在不含 ITGen 和插件资料的独立 ACT4 副本中用相同参数生成并比较 `.S`，记录到已有审查项。
生成器必须独立于私有导入、文件访问、导入路径注入及 `ITGEN_*`、`UCAGENT_*`、
`ACT4_MANUAL_ROOT` 环境变量；ACT4 原生资源、普通 JSON/YAML 和追踪注释仍可使用。

按 resource_mode 实现：
- bare_or_csr_only：不建页表，明确 satp/vsatp/hgatp Bare 或未使用。
- single_stage：按 s_stage 描述使用 satp、页表和 sfence.vma。
- g_stage_only：按 g_stage 描述使用 hgatp 和相应 fence。
- two_stage：分别生成 VS/G 两套资源、写 vsatp/hgatp 并按 contract 激活/恢复。

地址来自链接符号，PPN 由符号计算，根表对齐依据目标模式。
explicit_guest_memory_access 只映射 page-walk 和 payload 的直接依赖；
guest_execution 才额外要求 guest code、trap vector/stack 等实际消费的资源。
保存/恢复状态、页表资源和控制流须在生成 .S 与最终 ELF 中复核。

公共 H trap/setup guard 关闭时，先分析 suite-local 数据/汇编、正向子集、已审计入口、
generation-vs-validation scope。只有直接依赖且无法替代的子场景 blocked。
允许独立 suite-local 流程时必须完整进入/返回并恢复框架收尾模式。
实验内容只写 experimental 目录，不注册到正式 generator。

## 6. 检查与交付

阶段 04 精确 required check names：
`generator_api`、`testcase_linkage`、`privileged_state`、`vm_profile_binding`、
`switch_capability_consistency`、`file_manifest_update`、`framework_integrity`。

在上述检查下分别提供 TestChunk API、automatic source splitting、CSR/trap 和 VM 的证据；
不能仅新增相近 check 名替代配置必需项。静态 AST 通过仅说明可见结构符合规则，
实际返回对象、helper 数据流、模式和目标语义仍需执行与审查。

记录 native testgen 命令、每个输出 .S 的 testcase 数、chunk/split 归属及完整 header/footer。
首次贡献写入后检查 protected integrity；05_build 完成后补齐
.sig.elf -> .sig -> .results -> 最终 .elf 的证据。修改 generator 后重新生成和构建，
旧 JSON 只证明旧文件版本，复查新版本时应明确引用对应的新证据。
