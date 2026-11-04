
# 接口与时序合同

本文件定义公共顶层 `npu_pe_core`。内部可以包含 `pe_array`、单 PE 或共享算术模块，但仿真、综合和 PPA 必须使用相同的完整顶层。参数及数值定义见 `01_design_specification.md`。

## 1. 顶层端口

全部数据端口为无符号 packed vector；浮点符号位由数值解码处理。`ROW_W=max(1,ceil(log2(ARRAY_M)))`。

| 端口 | 方向 | 位宽 | 含义 |
|---|---|---|---|
| `clk` | I | 1 | 唯一时钟，上升沿采样 |
| `rst_n` | I | 1 | 低有效异步复位，外部同步释放 |
| `cfg_wr_en` | I | 1 | 空闲时配置写使能 |
| `cfg_addr` | I | 6 | 字节地址，合法寄存器按 4-byte 对齐 |
| `cfg_wdata` | I | 32 | 配置写数据 |
| `cfg_rdata` | O | 32 | 当前地址的组合读数据 |
| `start` | I | 1 | 新事务请求 valid |
| `start_ready` | O | 1 | 可以接受新事务 |
| `busy` | O | 1 | 已接受 start，尚未交付全部结果行 |
| `done` | O | 1 | 最后一行输出被接受后置高一个周期 |
| `data_valid` | I | 1 | 完整 A/B/scale 输入包有效 |
| `data_ready` | O | 1 | 可以原子接受完整输入包 |
| `a_in` | I | `32*ARRAY_M` | 每行一个 32-bit A 字 |
| `b_in` | I | `32*ARRAY_N` | 每列一个 32-bit B 字 |
| `sa_in` | I | `8*ARRAY_M` | 每行 E8M0 scale，仅块首包有意义 |
| `sb_in` | I | `8*ARRAY_N` | 每列 E8M0 scale，仅块首包有意义 |
| `psum_out` | O | `32*ARRAY_N` | 一行的 FP32 结果 |
| `psum_row` | O | `ROW_W` | 当前输出行号 |
| `psum_out_valid` | O | 1 | 当前结果行有效 |
| `psum_out_ready` | I | 1 | 下游可以接受当前结果行 |

默认 4×4 下 A/B 各 128 bit，SA/SB 各 32 bit，结果行 128 bit。公共顶层只包含本表端口，不要求暴露单 PE 的透传接口、内部累加器、scan 或外部 skew 信号。

### 1.1 唯一测试可见边界

以上引脚是所有 DUT 测试唯一可见的输入输出，名称、大小写、方向、位宽公式和含义均固定。Python 与 RTL backend 的 adapter 必须逐项提供相同接口，不得增加 Python 专用完成标志、直接矩阵计算入口或隐藏状态读取接口供测试使用。

测试可以根据已驱动输入独立计算 expected，也可以维护由引脚握手构成的 scoreboard；不得通过层次访问、内部计数器、累加器数组、模块名、Python 对象私有成员、DPI 后门或调试文件获取 DUT 状态。API 的配置、启动、等待、读结果和超时必须最终落实到这些引脚的读写和时钟推进。

波形可以包含内部信号以定位故障或供 PPA 工具统计活动，但功能断言、功能覆盖命中、性能的事务 / 周期计数和通过判据仅依赖顶层引脚。禁止以内部 `local_acc`、`main_acc`、pipeline valid、PE 数量或 skew 深度作为验收条件。

### 1.2 完整端口声明

下面是公共接口声明，不规定模块内部结构。Verilog 和 Chisel 导出电路均应与其一致：

```verilog
module npu_pe_core #(
    parameter integer ARRAY_M = 4,
    parameter integer ARRAY_N = 4
) (
    input  wire clk,
    input  wire rst_n,
    input  wire cfg_wr_en,
    input  wire [5:0] cfg_addr,
    input  wire [31:0] cfg_wdata,
    output wire [31:0] cfg_rdata,
    input  wire start,
    output wire start_ready,
    output wire busy,
    output wire done,
    input  wire data_valid,
    output wire data_ready,
    input  wire [32*ARRAY_M-1:0] a_in,
    input  wire [32*ARRAY_N-1:0] b_in,
    input  wire [8*ARRAY_M-1:0] sa_in,
    input  wire [8*ARRAY_N-1:0] sb_in,
    output wire [32*ARRAY_N-1:0] psum_out,
    output wire [((ARRAY_M <= 1) ? 1 : $clog2(ARRAY_M))-1:0] psum_row,
    output wire psum_out_valid,
    input  wire psum_out_ready
);
    // Implementation is generated in the selected output directory.
endmodule
```

端口声明中的 `wire` 表示接口连线，不限制内部输出采用寄存器实现。所有控制信号高有效，只有 `rst_n` 低有效。无三态引脚、隐式 signed 数据端口、额外时钟或独立 scale 握手。

### 1.3 采样与比较

输入握手、start 握手和结果消费均根据上升沿到来前稳定的 valid / ready 值判定；上升沿后的 busy、done、寄存器读数和新结果状态在组合逻辑稳定后读取。测试驱动器应在非采样边沿更新输入，避免与 DUT 上升沿更新发生竞争。

控制输出在复位完成后不得包含 X/Z；有效结果和寄存器读数据也必须确定。等待期间的数据稳定检查覆盖整个有效负载。不同候选的 ready / valid 时间可以不同；测试按引脚事件对齐事务，不把某一参考实现的逐周期轨迹固定为功能 expected。

## 2. 配置寄存器

### 2.1 读写规则

仅当 `rst_n=1 && busy=0 && cfg_wr_en=1` 时在上升沿写入。该周期 `start_ready=0`，配置写与 start 不在同一沿同时生效。busy 期间所有配置写均忽略，不能改变当前事务或偷偷预装下一事务。

`cfg_rdata` 始终组合读取 `cfg_addr` 对应的寄存器。未定义地址、非对齐地址读为零，写入忽略；只读寄存器写入忽略。所有保留位写入忽略、读为零。无需提供总线等待或应答信号。

### 2.2 寄存器表

| 地址 | 名称 | 位域 | 复位值 |
|---|---|---|---|
| `0x00` | `CTRL` | `[0] enable` | `0x00000000` |
| `0x04` | `FMT` | `[1:0] a_fmt`，`[3:2] b_fmt` | `0x00000005`，双 E4M3FN |
| `0x08` | `SCALE_CFG` | `[0] mx_enable`，0 表示 scale bypass | `0x00000001` |
| `0x14` | `ACT_FUNC` | `[1:0] act`：0=Bypass，1=ReLU，2=ReLU6，3=非法 | `0x00000000` |
| `0x18` | `BIAS` | `[31:0]` FP32 编码 | `0x00000000` |
| `0x1c` | `K_DIM` | `[15:0]` K 长度，有效范围 1..4096 | `0x00000020` |
| `0x24` | `STATUS` | 只读，定义如下 | `0x00000004` |

`STATUS` 的 `[0]=busy`，`[1]=sticky_done`，`[2]=config_valid`，`[3]=result_nan`，`[4]=result_inf`；其余位为零。

- `config_valid` 是组合判定：K、格式组合、激活模式均合法，与 `enable` 无关。
- `sticky_done` 在最后一行输出握手后置 1，保持到下一个 start 被接受或 reset。
- `result_nan` / `result_inf` 表示上一已完成 tile 的最终输出中是否出现 NaN / Inf，完成前保持零，最后一行握手后同时发布。它们不是中间运算异常标志，下一 start 或 reset 时清零。
- 读配置得到已存储的位域。非法 K、保留格式码或非法激活码按位域保留，以便读回诊断，但禁止启动。

### 2.3 启动条件

```text
start_ready = rst_n && !busy && !cfg_wr_en && CTRL.enable && config_valid
start_fire  = rst_n && start && start_ready
```

`start_fire` 的上升沿锁存所有事务配置、清空旧结果状态并进入 busy。该沿不接受数据包；最早从下一上升沿开始接受。`start` 是 ready/valid 请求，等待时应保持，发生握手后发送方撤下或改为下一请求。

非法配置或 `enable=0` 时 `start_ready=0`，不得启动、接受数据或产生结果。不存在 `accum_start`、`kblock_end` 等第二套外部控制源。

## 3. 输入包与块边界

### 3.1 原子握手

输入包仅在上升沿 `rst_n && data_valid && data_ready` 时被接受。A、B、SA、SB 使用同一握手，所有行和列对应同一逻辑 K 位置；不允许只接受 A 或只接受 B。

`data_valid=1 && data_ready=0` 时发送方保持 `data_valid` 和整个包不变，直到接受或复位取消。`data_valid=0` 时数据值不参与计算。接收方不能等待未来输入数据才能释放对当前包的反压。

空闲、复位和已收足 `ceil(K/L)` 个包时 `data_ready=0`。收数期间可随实现能力改变 ready，不规定 II=1；每次真正握手才推进计数。最后一个包后不再接受本事务的数据。

### 3.2 Packed 数据顺序

令 `p` 为从零开始的已接受包序号，`w=8`（FP8）或 `w=4`（FP4），`L=32/w`。包内 lane `l` 对应 `k=p*L+l`：

```text
a_in[32*i + w*l +: w] = A[i, p*L+l]
b_in[32*j + w*l +: w] = B[p*L+l, j]
sa_in[8*i +: 8]        = SA[i, floor(p*L/32)]
sb_in[8*j +: 8]        = SB[floor(p*L/32), j]
```

最低位是 row / column 0 的 lane 0。A 按行、B 按列传输，B 的第 j 个字包含不同 k 的 `B[k,j]`，不是一整行 B。

`p*L+l >= K` 的尾 lane 被忽略；无需额外 lane mask。测试必须用非零、NaN / Inf 填充未使用位置，证明它们不参与计算。

### 3.3 Scale 更新

当 `p*L mod 32 = 0` 时，该包携带新块的所有 scale，在同一次数据握手中锁存。非块首包的 scale 位被忽略，测试可改变它们以检查 scale 保持行为。

FP8 每 8 个被接受的包进入下一块，FP4 每 4 个包进入下一块；这些是握手计数，不是时钟周期。气泡、缓存和反压都不能推进块序号。尾块沿用其首包锁存的 scale，只处理实际 K 元素。

### 3.4 确定性打包例子

默认 4×4，FP4 全 1 的一个输入包：

```text
a_in  = 0x22222222222222222222222222222222
b_in  = 0x22222222222222222222222222222222
sa_in = 0x7f7f7f7f
sb_in = 0x7f7f7f7f
```

K=32 时接受 4 个这样的包，每个输出元素是 FP32 的 32。双 E4M3FN 用每字 `0x38383838`、双 E5M2 用每字 `0x3c3c3c3c`，K=32 时各需要 8 个包。

用于检验行列方向的 K=1、FP4 向量：`A[:,0]=[1,2,3,4]`、`B[0,:]=[1,-1,2,-2]`；高位未使用 lane 置零，则：

```text
a_in = 0x00000006000000050000000400000002
b_in = 0x0000000c000000040000000a00000002
SA = SB = 1
D = [[1,-1,2,-2], [2,-2,4,-4], [3,-3,6,-6], [4,-4,8,-8]]
row 0 psum_out = 0xc000000040000000bf8000003f800000
```

## 4. 结果输出与完成

从最后一个输入包被接受之后的上升沿起，DUT 可以任意合法延迟产生结果。结果按 `psum_row=0,1,...,ARRAY_M-1` 顺序输出，每行一次，不能在收足输入之前输出。

`psum_out[32*j +: 32]` 为 `D[psum_row,j]`。每个上升沿的 `rst_n && psum_out_valid && psum_out_ready` 消费一行。下游可提前置 ready，DUT 不得等 ready 才首次声明 valid。

`psum_out_valid=1 && psum_out_ready=0` 时，valid、row 和整行数据必须保持，不能重复消费、覆盖或撤回。行间允许气泡，也允许连续周期输出；无 valid 时 row / data 除复位要求外不作数值约束。

最后一行握手的上升沿完成事务，该沿之后 `busy=0`、`done=1`、`psum_out_valid=0`，并发布 sticky 状态；下一上升沿之后 `done=0`。同一完成沿不能接受下一 start；最快在紧随其后的上升沿接受。后续 start 清除 sticky 状态，无需重新写入未改变的合法配置。

只声明最后一行 valid 而未握手不算完成，busy 必须保持。除被复位取消外，每个 accepted start 最终恰好产生一个完整 tile 和一次 done。

## 5. 复位与前进性

`rst_n=0` 时异步取消所有待处理输入、块状态和未交付结果，配置恢复复位值；`busy=done=data_ready=start_ready=psum_out_valid=0`，`psum_row=psum_out=0`。`cfg_rdata` 按复位后的寄存器和当前地址读取，不要求固定为零。

复位优先于配置写、start、输入和输出握手。部分已交付的行也视为整个事务取消，不允许恢复后补发剩余行或旧 done。外部保证复位释放同步于 clk 且满足采样要求；在释放后的首个上升沿可以写配置，合法配置就绪后可重新启动。

不规定精确流水延迟或固定填充 / 排空拍数。实现必须给出有限的输入服务间隔和完成延迟上界，写入生成的架构合同；当上游持续提供包、下游持续 ready 时不得永久停顿。测试使用明确的 `max_cycles` 超时，超时必须失败，不能返回部分结果。等待主机提供尚缺的数据或释放输出反压的时间不属于 DUT 无故停顿。

## 6. 非法输入与验证 API

高层 API 对超宽 / 负的 packed 值、矩阵维度错误、scale 数量错误、非法 K / 格式组合 / 激活和 X/Z 输入，在驱动前抛出 `ValueError`，Python 与 RTL backend 一致。合法的 NaN、Inf、subnormal 及所有 FP4 编码不是 API 错误。

同时保留低层配置读写 API，允许测试把非法字段写到寄存器并验证 `config_valid=0`、启动受阻、读回正确；不要让高层拒绝路径代替 RTL 的非法配置测试。主机违反 valid 保持规则不属于有效事务，DUT 不要求提供专用报错端口。
