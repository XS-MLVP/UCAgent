
# 性能测量与优化合同

保持功能、公共引脚、数值结果和性能 workload 不变，探索内部结构和不同 PPA 取舍。使用完整 `npu_pe_core` 顶层、默认 4×4 配置，按 `02_interface_and_timing.md` 的引脚事件测量。

## 1. 指标与观察窗口

设 `c_start` 为首个 `start && start_ready` 握手的上升沿编号，`c_last` 为最后一个目标 tile 的最后一行 `psum_out_valid && psum_out_ready` 握手沿编号。测量窗口为 `(c_start,c_last]`，周期数 `C=c_last-c_start`，不添加额外的首尾周期。

| 稳定 metric ID | workload | kind / unit | direction / aggregation |
|---|---|---|---|
| `fp4_tile_latency_cycles` | E2M1×E2M1，K=32，1 tile | latency / cycles | min / max |
| `fp8_tile_latency_cycles` | E4M3FN×E4M3FN，K=32，1 tile | latency / cycles | min / max |
| `fp4_stream_macs_per_cycle` | E2M1×E2M1，K=1024，8 tiles | throughput / MAC/cycle | max / mean |
| `fp8_stream_macs_per_cycle` | E4M3FN×E4M3FN，K=1024，8 tiles | throughput / MAC/cycle | max / mean |
| `fp8_mixed_stream_macs_per_cycle` | E4M3FN×E5M2，K=1024，8 tiles | throughput / MAC/cycle | max / mean |
| `fp4_zero_block_macs_per_cycle` | E2M1×E2M1，K=1024，8 tiles，指定零块 | throughput / MAC/cycle | max / mean |

latency 的值为 `C`。throughput 的值为 `8*ARRAY_M*ARRAY_N*K/C`，默认配置的分子为 131072 个逻辑 MAC。只有对应输入已被接受、结果逐 bit 正确并交付全部行的 tile 才能计入；未完成就超时必须失败，不得只统计一个高吞吐子窗口。

逻辑 MAC 数包含零值输入对应的数学工作量，零块 workload 不能被表述为实际切换的乘法器操作数。三个普通长 K workload 均为稠密非零输入，避免只针对稀疏数据得到优势。

这六项指标不设固定周期、吞吐或 FP4/FP8 比值门槛。生成性能合同时使用 `target: null`、`hard_requirement: false`；实际前进性与测试超时仍必须通过。不要求达到主规格的工艺预算、理论带宽峰值或指定流水拍数。

## 2. 固定 workload

### 2.1 有限输入码表

下列有序表用于确定性生成输入，不调用 backend 私有随机数生成器：

```text
FP4  = [0x1,0x2,0x3,0x4,0x5,0x6,0x7,0x9,0xa,0xb,0xc,0xd,0xe,0xf]
E4M3 = [0x28,0x30,0x38,0x40,0x48,0x50,0xa8,0xb0,0xb8,0xc0,0xc8,0xd0]
E5M2 = [0x34,0x38,0x3c,0x40,0x44,0x48,0xb4,0xb8,0xbc,0xc0,0xc4,0xc8]
```

对第 t 个 tile（t 从 0 开始）、行 i、列 j、元素 k、块 q：

```text
A[i,k] = a_table[(3*i + 5*k + t) % len(a_table)]
B[k,j] = b_table[(7*j + 3*k + 2*t + 1) % len(b_table)]
SA[i,q] = 125 + ((i + q + t) % 5)
SB[q,j] = 125 + ((2*j + q + 2*t) % 5)
```

所有节点均 `mx_enable=1`、Bias=+0、activation=Bypass。格式决定 a_table / b_table。短 K 节点使用 t=0，长 K 节点依次使用 t=0..7。零块节点仅将偶数 q 中全部 A 元素改为 FP4 +0，保留原 B 和所有有限 scale；不能用 NaN scale 代表零块。

### 2.2 驱动计划

复位和配置写在计量窗口之前完成。`psum_out_ready` 全程为 1；输入从 start 后首个允许的周期起持续 valid，无主动气泡；当前包直到握手才切换下一包。下一事务在引脚允许的最早时机发起，采用相同配置，无人为 cooldown。

对于相同节点，所有版本使用同一个有序包序列、scale、配置、重置过程、主机发送规则和 10 ns 仿真时钟。输入包被反压时的重复保持周期、实际完成周期及相应 ready / valid 输出允许随实现变化，它们是测量结果。

窗口结束条件固定为规定数量的 tile 全部交付，窗口实际时长允许变化，不通过固定一个偏向某候选的时间片筛选结果。共享测试超时在建立 base 前设定，不能对候选临时放宽；架构必须声明能够满足该测试预算的有限服务上界。

### 2.3 性能节点与证据

在 `{OUT}/tests/test_npu_pe_core_performance.py` 中生成六个 pytest 节点，分别使用以下函数名，与第 1 节表格逐行对应：

```text
test_npu_pe_core_performance_fp4_latency
test_npu_pe_core_performance_fp8_latency
test_npu_pe_core_performance_fp4_throughput
test_npu_pe_core_performance_fp8_throughput
test_npu_pe_core_performance_fp8_mixed_throughput
test_npu_pe_core_performance_fp4_zero_block
```

每个节点仅报告其对应 metric，具有独立 VCD/FST 和 JSON sidecar；节点顺序固定为上述顺序。功能也必须在 Python reference 上验证，硬件性能与 PPA 使用 RTL 波形。额外探索 workload 可以单独报告，不能替换或改变这六项。

`stimulus_manifest` 使用现有性能工具支持的字段，`deterministic=true`、`seed=null`。`parameters` 记录阵列、格式、K、目标 tile 数、时钟和驱动策略；`input_trace` 记录稳定的配置写及有序输入包、tile / 包索引、预设 ready 策略。不能将反压导致的重复等待周期或候选完成时刻放入用于比较的输入身份。

sidecar 的 `transaction_count` 是实际完整交付的 tile 数；`start_time/end_time` 是上述引脚事件的仿真时间。带时间戳的真实引脚变化保存在波形中，用于复核握手、周期与结果，不能以稳定的逻辑输入列表代替真实波形。

## 3. 公平 PPA 比较

每个完整评估版本使用同一顶层、阵列参数、工艺库、工具选项、时钟 / IO 约束、相同六份 workload 及其固定聚合方式。PPA 范围包括配置、输入缓存、控制、计算、结果缓存和必要互联，不能仅分析一个算术子模块。

记录面积、时序 / 等效最高频率和活动功耗及其单位、来源、库与电压假设。功能仿真时钟、STA 可达频率、硬件周期数和 pytest 墙钟时间是不同量，不能互相替代。估算功耗不是实测芯片功耗；更换工艺库或约束需重新建立基线，不应继续同一改善曲线。

`GFLOP/s = 2 * measured_MACs_per_cycle * frequency_hz / 1e9` 仅可作为派生指标，频率必须标明使用共同分析频率还是实际 STA 结果。不得把输入有效拍数量当作完成的工作量，或把稀疏跳过标成密集吞吐。

## 4. 优化与接受策略

base 必须先通过全部功能回归，再记录六项性能指标和 PPA。后续每个候选都先证明功能等价，再测量相同 workload；候选不得修改规格、oracle、断言、节点、输入向量或编码含义。

可探索共享 / 专用乘法器、物理并行度、流水深度、缓存、广播 / 脉动结构、块归约表示、FP32 加法实现、时钟使能和操作数隔离。每轮说明改动、预期改善方向、可能代价以及实测结论，不预设某种结构一定更好。

按当前任务已确定的候选接受策略判定 accepted / rejected，在同一比较序列中保持策略不变，不得为保留某个候选调整策略。本 case 不额外要求所有 PPA 维度同时不退化；功能、数值和协议要求始终强制，各项性能与 PPA 的改善及代价必须如实记录。

失败或被拒绝的候选不覆盖最终交付源码。最终源码必须对应最后一个 accepted 版本，并具有完整同套测试和当前 PPA 证据。没有测到改善时保留已验证的 base，不能编造候选收益。

## 5. 最终交付

在 `{OUT}` 交付 performance contract、六项性能结果及独立波形、base / final PPA、候选账本、`npu_pe_core_performance_curve.json` 和 `npu_pe_core_ppa_dashboard.html`。曲线呈现六项指标、面积、时序 / 频率及功耗的实际版本变化，并标识 accepted / rejected 状态。

总结说明最终架构、最终 accepted 版本、相对 base 的改善及代价，链接完整证据。对未运行的物理实现、FPGA、大阵列和扩展功能明确其未验证状态，不能从小 tile 仿真或理论峰值推导已经达标。
