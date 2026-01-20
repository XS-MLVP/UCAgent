# SBuffer 存储提交缓冲

本项目是对处理器中的存储提交缓冲模块（Store Buffer, SBuffer）进行验证。

## 1. 待测模块 (DUT) 说明

### 1.1 模块参数
| 参数名 | 说明 |
| :--- | :--- |
| EnsbufferWidth | SBuffer并发入队请求宽度 (实例化为2，对应io_in_0和io_in_1) |
| StoreBufferSize | SBuffer条目深度 (默认为16) |
| LoadPipelineWidth | Load单元前递查询并发度 (实例化为2，对应io_forward_0和io_forward_1) |

### 1.2 接口列表
| 端口名 | 方向 | 类型 | 说明 |
| :--- | :--- | :--- | :--- |
| clock | input | Clock | 时钟信号 |
| reset | input | Reset | 复位信号 |
| io_in_0 | input | Decoupled | 来自StoreQueue的存储请求输入通道0 (ready/valid/bits) |
| io_in_0_bits_addr | input | UInt<36> | 通道0物理地址 |
| io_in_0_bits_data | input | UInt<64> | 通道0存储数据 |
| io_in_0_bits_mask | input | UInt<8> | 通道0字节掩码 |
| io_in_0_bits_vaddr | input | UInt<39> | 通道0虚拟地址 |
| io_in_0_bits_wline | input | Bool | 通道0写整行标志 |
| io_in_1 | input | Decoupled | 来自StoreQueue的存储请求输入通道1 (ready/valid/bits) |
| io_in_1_bits_addr | input | UInt<36> | 通道1物理地址 |
| io_in_1_bits_data | input | UInt<64> | 通道1存储数据 |
| io_in_1_bits_mask | input | UInt<8> | 通道1字节掩码 |
| io_in_1_bits_vaddr | input | UInt<39> | 通道1虚拟地址 |
| io_in_1_bits_wline | input | Bool | 通道1写整行标志 |
| io_dcache_req | output | Decoupled | 向DCache发送的写请求 (ready/valid/bits) |
| io_dcache_req_bits_vaddr | output | UInt<39> | DCache请求虚拟地址 |
| io_dcache_req_bits_addr | output | UInt<36> | DCache请求物理地址 |
| io_dcache_req_bits_data | output | UInt<512> | DCache请求数据 (64字节缓存行) |
| io_dcache_req_bits_mask | output | UInt<64> | DCache请求字节掩码 |
| io_dcache_req_bits_id | output | UInt<6> | DCache请求ID |
| io_dcache_main_pipe_hit_resp | input | Valid | DCache主流水线命中响应 |
| io_dcache_main_pipe_hit_resp_bits_id | input | UInt<6> | 主流水线响应ID |
| io_dcache_refill_hit_resp | input | Valid | DCache重填命中响应 |
| io_dcache_refill_hit_resp_bits_id | input | UInt<6> | 重填响应ID |
| io_dcache_replay_resp | input | Valid | DCache重放响应 |
| io_dcache_replay_resp_bits_id | input | UInt<6> | 重放响应ID |
| io_forward_0 | input/output | Bundle | Load单元前递查询接口通道0 |
| io_forward_0_vaddr | input | UInt<39> | 通道0查询虚拟地址 |
| io_forward_0_paddr | input | UInt<36> | 通道0查询物理地址 |
| io_forward_0_valid | input | Bool | 通道0查询有效信号 |
| io_forward_0_forwardMask | output | UInt<8> | 通道0前递掩码 (8位，每位对应一个字节) |
| io_forward_0_forwardData | output | UInt<64> | 通道0前递数据 (8个字节，每个8位) |
| io_forward_0_matchInvalid | output | Bool | 通道0匹配无效标志 |
| io_forward_1 | input/output | Bundle | Load单元前递查询接口通道1 |
| io_forward_1_vaddr | input | UInt<39> | 通道1查询虚拟地址 |
| io_forward_1_paddr | input | UInt<36> | 通道1查询物理地址 |
| io_forward_1_valid | input | Bool | 通道1查询有效信号 |
| io_forward_1_forwardMask | output | UInt<8> | 通道1前递掩码 (8位，每位对应一个字节) |
| io_forward_1_forwardData | output | UInt<64> | 通道1前递数据 (8个字节，每个8位) |
| io_forward_1_matchInvalid | output | Bool | 通道1匹配无效标志 |
| io_sqempty | input | Bool | StoreQueue空标志 |
| io_flush_valid | input | Bool | Flush请求有效信号 |
| io_flush_empty | output | Bool | SBuffer空标志 (flush完成) |
| io_csrCtrl_sbuffer_threshold | input | UInt<4> | SBuffer阈值控制 |
| io_perf_0~16_value | output | UInt<6> | 性能计数器输出 (共17个) |

### 1.3 功能描述
SBuffer 主要负责缓冲存储指令的数据，提高存储性能。核心功能包括：
1.  **入队管理**：接收 StoreQueue 请求，支持合并（Merge）操作，采用3级流水线处理（S0/S1/S2）。S0阶段将数据存入2-entry FIFO队列，S1阶段更新元数据并准备写使能信号，S2阶段使用缓存行级缓冲器更新数据和掩码。
2.  **出队管理**：采用2级流水线（S0/S1）将数据写回 DCache。支持伪LRU替换策略选择victim entry，触发条件包括：ActiveCount达到阈值、缓冲区满、一致性计数器超时（EvictCycles=2^20周期）、重试计数器超时（16周期）等。
3.  **前递 (Forwarding)**：响应 Load 单元的查询，提供最新的存储数据。使用vtag进行初筛，ptag进行精确匹配。检测到tag不匹配时设置matchInvalid标志，优先返回active entry的数据，其次是inflight entry的数据。
4.  **状态维护**：管理 Entry 的 state_valid、state_inflight、w_timeout、w_sameblock_inflight 等状态，维护数据一致性。使用cohCount一致性计数器和missqReplayCount重试计数器。
5.  **状态机控制**：包含4个状态：x_idle（空闲）、x_replace（替换）、x_drain_all（排空SQ+SBuffer）、x_drain_sbuffer（仅排空SBuffer），根据flush请求、阈值条件、tag不匹配等触发状态转换。

## 2. 验证需求 (Verification Requirements)

### 2.1 验证目标
验证 RTL 代码是否正确实现了 SBuffer 的核心逻辑，重点关注：
*   **存储请求处理**：入队、合并逻辑的正确性。
*   **数据通路**：数据写入、读取、掩码处理的准确性。
*   **前递机制**：Load 查询时能否正确返回最新数据或 Miss 信号。
*   **写回机制**：与 DCache 交互协议的正确性及替换算法的有效性。

注意：
- 验证重点在于逻辑功能正确性，不需要关注波形 dump、时序违例等其他内容。
- 把Sbuffer当成一个黑盒去验证其整体功能，不要尝试验证其中的子模块。

### 2.2 验证计划结构
为了便于管理，请按照 UCAgent 标签规范组织测试点。详细功能点与检测点可参考 `Sbuffer_functions_and_checks.md`。

## 3. 其他说明

*   **文档语言**: 所有的验证文档、测试计划、Bug分析和代码注释都必须使用**中文**编写。
*   **代码风格**: Python 测试代码应符合 PEP8 规范。

## 4. Bug 分析

如果在运行测试时发现 failures，请参考源码 `Sbuffer.scala` 及相关设计文档进行调试。
发现 bug 按照 UCAgent 的 bug 记录规范进行记录。
