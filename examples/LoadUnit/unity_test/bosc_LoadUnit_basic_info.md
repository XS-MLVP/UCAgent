# bosc_LoadUnit 基础信息

## 1. 芯片定位

`bosc_LoadUnit` 是 LSU 中的 Load 指令执行单元。它接收来自发射队列、重放队列、MisalignBuffer、预取器等不同来源的请求，在内部 4 级流水中完成地址翻译、DCache 查询、前递判断、违例检查、异常整合、重放决策与最终写回。

从 `README` 可以确认该模块的核心职责包括：

- 接收标量 load、向量 load、MMIO load、NC load、非对齐 load、预取请求。
- 向 TLB、DCache、LSQ、StoreQueue、SBuffer 等模块发起查询或交互。
- 将执行结果写回后端、LoadQueue 和 ROB。
- 在合适阶段向后端发送 wakeup、feedback、rollback、redirect 等控制信号。

模块支持 128bit 数据宽度的数据通路，但标量写回 `ldout` 的数据宽度为 64bit，向量写回 `vecldout` 的数据宽度为 128bit。

## 2. Python 仿真接口定义

`bosc_LoadUnit/__init__.py` 定义了仿真封装类 `DUTbosc_LoadUnit`，它是后续所有 toffee/pytest 验证代码直接操作的 DUT 接口。

### 2.1 DUT 类结构

- `DUTbosc_LoadUnit.__init__()` 内部实例化 `DutUnifiedBase`
- 使用 `xsp.XClock` 管理时钟推进
- 使用 `xsp.XPort` 管理 DUT 端口
- 将所有顶层端口展开为 `self.io_*` 形式的 `XPin`
- 支持覆盖率文件和波形文件配置

### 2.2 关键用户 API

`__init__.py` 中提供了后续验证必须使用的仿真控制接口：

- `InitClock(name)`：将某个引脚注册为时钟
- `Step(i=1)`：推进 `i` 个周期
- `StepRis(callback)`：在上升沿推进并执行回调
- `StepFal(callback)`：在下降沿推进并执行回调
- `SetWaveform(filename)`：设置波形文件
- `SetCoverage(filename)`：设置覆盖率文件
- `Finish()`：结束 DUT

这说明后续测试环境应通过 `DUTbosc_LoadUnit` 统一管理时钟、端口和采样回调，而不是直接操作底层库。

### 2.3 端口封装形式

`__init__.py` 会把 Verilog/Chisel 中的大量 Bundle 展开成扁平化引脚，例如：

- 标量请求端口展开为 `io_ldin_valid`、`io_ldin_ready`、`io_ldin_bits_*`
- 标量写回端口展开为 `io_ldout_valid`、`io_ldout_ready`、`io_ldout_bits_*`
- 向量请求/写回、misalign、dcache、tlb、lsq 等接口也采用同样方式展开

因此后续 Env 层应自行把这些扁平引脚重新封装成更高层的事务接口，降低测试代码复杂度。

## 3. 输入输出端口分析

由于端口数量非常多，后续验证不应逐个位级独立处理，而应按功能分组理解。

### 3.1 输入端口分组

#### 3.1.1 时钟与控制类

- `clock`：主时钟
- `reset`：复位
- `io_redirect_*`：刷流水/重定向控制
- `io_csrCtrl_ldld_vio_check_enable`
- `io_csrCtrl_hd_misalign_ld_enable`

作用：控制流水线有效性、违例检查开关和非对齐处理开关。

#### 3.1.2 标量 load 发射输入

- `io_ldin_valid`
- `io_ldin_ready`
- `io_ldin_bits_uop_*`
- `io_ldin_bits_src_0`

作用：接收普通标量 load 指令及其 uop 元信息、源地址/偏移相关输入。

#### 3.1.3 向量 load 输入

- `io_vecldin_valid`
- `io_vecldin_ready`
- `io_vecldin_bits_vaddr`
- `io_vecldin_bits_mask`
- `io_vecldin_bits_reg_offset`
- `io_vecldin_bits_uop_*`

作用：接收向量 load 请求以及向量相关掩码、元素索引、寄存器偏移等信息。

#### 3.1.4 MisalignBuffer 输入

- `io_misalign_ldin_valid`
- `io_misalign_ldin_ready`
- `io_misalign_ldin_bits_*`

作用：接收已经判定为非对齐 load 的拆分/重发请求。

#### 3.1.5 replay / fast replay / uncache / nc 输入

- `io_replay_*`
- `io_fast_rep_in_*`
- `io_lsq_uncache_*`
- `io_lsq_nc_ldin_*`

作用：接收由于 miss、前递失败、队列压力或 NC 流程产生的重发请求。

#### 3.1.6 存储系统返回与查询相关输入

- `io_tlb_*`
- `io_pmp_*`
- `io_dcache_req_ready`
- `io_dcache_resp_bits_*`
- `io_dcache_s2_bank_conflict`
- `io_dcache_s2_mq_nack`
- `io_sbuffer_*`
- `io_ubuffer_*`
- `io_forward_mshr_*`
- `io_tl_d_channel_*`
- `io_l2_hint_*`
- `io_tlb_hint_*`

作用：模拟地址翻译、PMP 检查、DCache 返回、前递网络和 miss/forward 辅助通路。

#### 3.1.7 违例、快路径与预取相关输入

- `io_stld_nuke_query_*`
- `io_l2l_fwd_in_*`
- `io_ld_fast_match`
- `io_ld_fast_fuOpType`
- `io_ld_fast_imm`
- `io_prefetch_req_*`
- `io_correctMissTrain`

作用：支持 st-ld 违例检查、load-to-load 快路径和预取请求输入。

### 3.2 输出端口分组

#### 3.2.1 标量写回输出

- `io_ldout_valid`
- `io_ldout_ready`
- `io_ldout_bits_data`
- `io_ldout_bits_uop_*`
- `io_ldout_bits_debug_*`

作用：输出标量 load 的最终写回、异常向量、调试地址和重放标识。

#### 3.2.2 向量写回输出

- `io_vecldout_valid`
- `io_vecldout_bits_vecdata`
- `io_vecldout_bits_exceptionVec_*`
- `io_vecldout_bits_vecTriggerMask`
- `io_vecldout_bits_elemIdx*`

作用：输出向量 load 的最终写回结果。

#### 3.2.3 MisalignBuffer 反馈输出

- `io_misalign_ldout_*`
- `io_misalign_enq_*`

作用：向 MisalignBuffer 发送入队、重发或写回响应。

#### 3.2.4 TLB / DCache / LSQ / 前递网络输出

- `io_tlb_*`
- `io_dcache_req_*`
- `io_dcache_s1_kill`
- `io_dcache_s2_kill`
- `io_lsq_ldin_*`
- `io_lsq_forward_*`
- `io_lsq_ldld_nuke_query_*`
- `io_lsq_stld_nuke_query_*`
- `io_fast_rep_out_*`

作用：对外发起查询、更新 LoadQueue、传递 replay 信息和控制 kill。

#### 3.2.5 后端控制与状态输出

- `io_wakeup_*`
- `io_fast_uop_*`
- `io_feedback_fast_*`
- `io_feedback_slow_*`
- `io_ldCancel_*`
- `io_rollback_*`
- `io_s3_dly_ld_err`

作用：向后端发出快速唤醒、慢反馈、取消、回滚及延迟错误信息。

#### 3.2.6 预取与前端相关输出

- `io_prefetch_train_*`
- `io_prefetch_train_l1_*`
- `io_ifetchPrefetch_*`
- `io_canAcceptHighConfPrefetch`
- `io_canAcceptLowConfPrefetch`
- `io_s1_prefetch_spec`
- `io_s2_prefetch_spec`
- `io_s1_prefetch_spec_l1`
- `io_s2_prefetch_spec_l1`

作用：输出预取训练信息、ifetch prefetch 请求以及对不同置信度预取请求的受理状态。

## 4. 芯片类型判断

`bosc_LoadUnit` 是典型的时序电路，而不是组合电路，判断依据如下：

- 顶层存在显式 `clock` 和 `reset` 输入。
- `README` 明确描述了 stage 0 到 stage 3 的多级流水行为。
- `__init__.py` 提供了 `InitClock()`、`Step()`、`StepRis()`、`StepFal()` 等按周期推进的仿真接口。
- DUT 的大量行为依赖 ready/valid 握手和跨周期状态流动，例如 replay、kill、写回和 wakeup。

结论：后续测试必须初始化时钟并通过 `Step` 接口驱动，不允许把它当作组合逻辑一次性求值。

## 5. 功能大类分析

结合 `README`、`LoadUnit.scala` 与顶层端口，`bosc_LoadUnit` 的功能可以划分为以下 9 大类：

1. 标量 load 基本执行流水
2. stage 0 多源请求仲裁
3. replay / fast replay / queue-based replay
4. 向量 load 路径
5. MMIO load 路径
6. Non-cacheable load 路径
7. 非对齐 load 与 MisalignBuffer 交互
8. 前递、违例检查、kill/rollback/redirect 控制
9. 预取请求受理与训练输出

如果按“可独立验证的功能点”粗略估算，后续大约需要覆盖 25 到 35 个功能点，主要来源如下：

- 基础标量命中/背压/写回：3 到 4 个
- 多源仲裁优先级：4 到 6 个
- replay 原因与 kill：4 到 5 个
- 向量/MMIO/NC：6 到 8 个
- misalign：4 到 5 个
- 前递/违例/异常/redirect：4 到 5 个
- 预取受理与训练：2 到 3 个

这个估算适合后续拆解 `functions_and_checks` 文档和功能覆盖点。

## 6. 后续验证关注重点

从基础信息角度，后续最值得优先验证的内容包括：

- stage 0 多源仲裁是否严格符合优先级
- 标量 load 的基本命中路径是否能稳定写回
- replay、kill、redirect、rollback 的时序关系是否正确
- 向量、NC、MMIO、misalign 等特殊路径是否走到正确出口
- DCache 数据、前递数据、uncache 数据的选择是否正确
- 预取请求是否被正确受理并产生训练输出

## 7. 本阶段结论

`bosc_LoadUnit` 不是一个单入口单出口的简单 load 模块，而是一个带多入口、多类特殊路径、强依赖流水控制与重放机制的时序执行单元。后续验证工作必须围绕“接口分组驱动 + 周期级 checker + 特殊路径优先覆盖”的思路展开，尤其需要优先关注 replay、misalign、NC 和仲裁相关行为。
