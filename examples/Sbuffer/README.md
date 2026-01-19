# SBuffer 存储提交缓冲

本项目是对处理器中的存储提交缓冲模块（Store Buffer, SBuffer）进行验证。

## 1. 待测模块 (DUT) 说明

### 1.1 模块参数
| 参数名 | 说明 |
| :--- | :--- |
| EnsbufferWidth | SBuffer并发入队请求宽度 |
| StoreBufferSize | SBuffer条目深度 (默认为16) |
| LoadPipelineWidth | Load单元前递查询并发度 |
| hartIdLen | 硬件线程ID位宽 |

### 1.2 接口列表
| 端口名 | 方向 | 类型 | 说明 |
| :--- | :--- | :--- | :--- |
| io_hartId | input | UInt | 硬件线程ID |
| io_in | input | Vec | 来自StoreQueue的存储请求输入 |
| io_dcache | output | Bundle | 与DCache交互接口 (请求/响应) |
| io_forward | input | Vec | 来自Load单元的前递查询接口 |
| io_sqempty | input | Bool | StoreQueue空标志 |
| io_sbempty | output | Bool | SBuffer空标志 |
| io_flush | input | Bundle | Flush控制信号 |
| io_csrCtrl | input | Bundle | CSR控制接口 |
| io_store_prefetch | output | Vec | 存储预取请求 |
| io_memSetPattenDetected | input | Bool | 内存memset模式检测 |
| io_force_write | input | Bool | 强制写回信号 |
| io_diffStore | input | Bundle | 差分存储接口 |

### 1.3 功能描述
SBuffer 主要负责缓冲存储指令的数据，提高存储性能。核心功能包括：
1.  **入队管理**：接收 StoreQueue 请求，支持合并（Merge）操作，支持多级流水线处理。
2.  **出队管理**：将数据主动或被动写回 DCache，支持伪 LRU (PLRU) 替换策略。
3.  **前递 (Forwarding)**：响应 Load 单元的查询，提供最新的存储数据。
4.  **状态维护**：管理 Entry 的 valid, inflight, sameblock 等状态，维护数据一致性。

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
