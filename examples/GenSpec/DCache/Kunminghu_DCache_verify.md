|     |     |
| --- | --- |
| 文档编号 |     |
| 文档版本 |     |
| 文档管控 | 内部公开 |
| 存档日期 |     |

XX项目XX模块AS

|     |     |
| --- | --- |
| 编 写： |     |
| 校 对： |     |
| 审 核： |     |
| 批 准： |     |

南湖V2项目

2022年XX月XX日

文档修订记录

|     |     |     |     |     |     |
| --- | --- | --- | --- | --- | --- |
| **序号** | **版本编号** | **变化状态** | **变更说明** | **作者** | **日期** |
| 1   | V0.1 | C   |     |     |     |
|     |     |     |     |     |     |
| 3   |     |     |     |     |     |
|     |     |     |     |     |     |

\*变化状态：C—创建，A—增加，M—修改，D—删除

文档审批信息

|     |     |     |     |     |
| --- | --- | --- | --- | --- |
| **版本** | **审核** | **会签** | **批准** | **备注** |
| V1.0 |     |     |     |     |
|     |     |     |     |     |

目 录

[1 简介 1](#_Toc107389929)

[1.1 文档介绍 1](#_Toc107389930)

[1.2 参考文档 1](#_Toc107389931)

[1.3 术语说明 1](#_Toc107389932)

[1.4 技术背景 1](#_Toc107389933)

[2 设计规格 2](#_Toc107389934)

[3 功能描述 2](#_Toc107389935)

[4 总体设计 2](#_Toc107389936)

[4.1 整体框图 2](#_Toc107389937)

[4.2 接口列表 3](#_Toc107389938)

[4.3 接口时序 3](#_Toc107389939)

[4.4 时钟复位 4](#_Toc107389940)

[4.5 寄存器配置 4](#_Toc107389941)

[4.6 补充说明 5](#_Toc107389942)

[5 模块设计 5](#_Toc107389943)

[5.1 二级模块LoadPipe 6](#_Toc107389944)

[5.1.1 功能 6](#_Toc107389945)

[5.1.2 整体框图 6](#_Toc107389946)

[5.1.3 接口列表 6](#_Toc107389947)

[5.1.4 接口时序 6](#_Toc107389948)

[5.1.5 关键电路 6](#_Toc107389949)

[5.1.6 三级模块设计 6](#_Toc107389950)

[5.2 二级模块MainPipe 6](#_Toc107389951)

[5.3 关键电路 6](#_Toc107389952)

[5.3.1 时钟切换电路 6](#_Toc107389953)

[6 PPA优化设计 7](#_Toc107389954)

[7 验证关注点 7](#_Toc107389955)

[8 Floorplan 建议 7](#_Toc107389956)

[9 遗留问题 8](#_Toc107389957)

## 简介

### 文档介绍

_概述本文档的目的、用途、适用人群、在整体项目中的位置等_

_例如：_

本文当是XXX的AS文档，描述XXX架构设计。

本文档主要用于指导芯片模块的详细设计及验证。

### 参考文档

_列出相关的参考文档。_

1.  XXXX
2.  XXXX

### 术语说明

_列出本文档的关键术语说明。_

表1.1 术语说明

|     |     |     |
| --- | --- | --- |
| **缩写** | **全称** | **描述** |
| CRU | Clock Reset Unit | 时钟复位单元 |
|     |     |     |
|     |     |     |
|     |     |     |

### 技术背景

_可选项。简要介绍本模块的技术背景，比如协议说明、应用范围等。如果不需要则直接删除本小节。注意要根据模块特性进行提炼，不要大段的复制黏贴。_

## 设计规格

_如果是模块的AS需要列出本模块支持的规格，如果是总体AS可忽略_

_规格中包含功能、性能、PPA规格。_

1\. DCache大小最高支持128KB，目前流片版本的大小为64KB

2\. 支持数据存储，缓存结构为组相联，每个缓存数据块大小为64B，为支持更高的并发度分为8个bank，Set数为256，DCache大小为64KB时，way数配置为4路，大小为128KB时，共8路。

3\. 支持核内访存模块对一级缓存数据的读、写。读操作宽度为 64 bit，支持两个并行的读操作。写操作宽度为 512 bit，不支持并行的写操作

4\. 支持向L2 Cache请求缺失数据并重填

5\. 支持Probe请求的处理及替换数据块写回

6\. 支持原子请求的处理

7\. 支持PLRU替换算法

8\. 支持与L2配合处理缓存别名问题

9\. 支持 SMS、Stride 和 Stream 硬件预取，详见 Prefetch 验证文档

## 功能描述

- - 1.  _进行功能概述。（从输入、处理、输出几个方面概述设计实现了什么功能）_
        2.  _按特性，每条特性分步骤进行详细描述_

_注意:要描述清楚对于异常的输入的处理，比如是支持纠错（怎么纠正），还是上报异常或中断，还是不处理错误但保证不死机，还是直接忽略等。_

_例：_

DCache模块接收来自核内访存流水线MemBlock的数据访存请求，根据请求类型与命中情况用不同流水线完成对缓存数据的读写和替换，并通过TileLink总线协议和L2 Cache交互完成数据块的写回、重填操作以及Probe请求。

在开启 ECC 的情况下，如果通过校验检测到缓存数据产生错误，DCache会将error从MemBlock上报给XSL1_beu (bus errors unit)，并触发access fault 来实现精确异常。

### 功能详述

#### Load请求处理

对于普通的Load请求，DCache从Load Queue 接收一条load指令后（实现的Load流水线有两条，可以并行处理两个load请求），根据计算得到的地址查询tagArray和metaArray，比较判断是否命中：若命中缓存行则返回数据响应；若缺失则分配MSHR (miss queue) 项，将请求交给Miss Queue处理，Miss Queue负责向L2 Cache发送 Acquire 请求取回重填的数据，并等待L2 Cache返回的hint信号。当l2_hint到达后，向MainPipe发起回填请求，进行替换路的选取并将重填数据块写入存储单元，同时把取回的重填数据转发给Load Queue完成响应；若被替换的块需要写回，则在Writeback Queue中向L2发送Release请求将其写回。

如果缺失的请求分配MSHR项失败，DCache会反馈一个MSHR分配失败的信号，由load保留站随后重新调度该load请求。

#### Store请求处理

对于普通的Store请求，DCache从StoreBuffer接收一条store指令后，使用Main Pipe流水线计算地址查询tag和meta，判断是否命中，若命中缓存行则直接更新DCache数据并返回应答；若缺失则分配MSHR将请求交给Miss Queue，向L2请求要回填到Dcache的原目标数据行，并等待L2 Cache返回的hint信号。当l2_hint到达后，向MainPipe发起回填请求，进行替换路的选取并将重填数据块写入DCache存储单元，在完成对该数据的store操作后向StoreBuffer返回应答；若被替换的块需要写回，则在Writeback Queue中向L2发送Release请求将其写回。

如果缺失的请求分配MSHR项失败，DCache会反馈一个MSHR分配失败的信号，由store buffer随后重新调度该store请求。

#### 原子指令处理

对于原子指令，由DCache的MainPipe流水线完成指令运算及读写操作，并返回响应。若数据缺失则同样向MissQueue发起请求，取回数据后继续执行该原子指令；对于AMO指令先完成运算操作, 再将结果写入；对于LR/SC指令，会设置/检查其 reservation set queue。在原子指令执行期间，核内不会向DCache发出其他请求（参见Memblock文档）。

#### Probe请求处理

对于Probe请求，DCache从L2 Cache接收Probe请求后，使用Main Pipe流水线修改被Probe的数据块的权限，命中后下一拍返回应答。

#### 替换与写回

DCache采用write-back和write-allocate的写策略，由一个replacer模块计算决定请求缺失后被替换的块，可配置random、lru、plru替换策略，默认选择使用plru策略；选出替换块后将其放入writeback queue队列中，向L2 Cache发出Release请求；而缺失的请求则从L2读取目标数据块后填入对应cache_line。

## 总体设计

_总体设计的标准：对设计进行分解，完成子模块划分、顶层接口定义、接口时序、数据流、控制流的设计。_

_总体设计面向的对象：顶层集成人员、验证人员、软件人员、设计人员_

### 整体框图

_此节画整体框图并配上文字说明。图可以不只1个，要体现模块划分、模块之间的关系、整体流水线设计等。_

_图中不同属性的信号要注意区分开，比如控制信号与数据信号、一般信号与时钟复位信号等。_

_控制流(代表控制关系的信号组流向)和数据流（设计各个环节处理的数据信号组流向）可用数字标明按照处理顺序上的先后关系。_

_简洁起见，图中可以使用代号标记信号组，然后在后文中详细说明每组信号组成，标准总线接口可不展开描述，比如使用axi_m_sig代表AXI master接口的所有信号。_

_文字描述要简洁清晰，重点是描述模块外部接口、内部各子模块功能、模块之间的关系。_

图4.1 DCache模块整体框图

### 接口列表

_如有专门的的接口列表文档，本章节可忽略，附上对应的接口列表名称路径即可_

_描述本模块所有的输入输出接口。接口列表是顶层集成的重要依据，需要准确清晰，并说明注意事项。_

_其中：_

1.  _源/目的一栏描述源头模块和目的地模块_
2.  _描述一栏需要列举信号每bit含义描述、取值范围、跟其他信号之间的约束（比如Xdata在Xvalid为高时有效、Xmode为2时signalA取值只能为1、2等等））_

表4.1 DCacheIO接口列表

|     |     |     |     |     |     |     |
| --- | --- | --- | --- | --- | --- | --- |
| **信号** | **方向** | **源** | **目的** | **信号组名** | **位宽** | **描述** |
| clock | input |     |     |     | 1   | 时钟信号 |
| reset | input |     |     |     | 1   | 异步复位信号 |
| auto_client_out_a_ready | input | l2cache | dcache | auto_client_out | 1   | DCache与L2Cache交互的Tilelink A通道是否可以接收请求 |
| auto_client_out_a_valid | output | dcache | l2cache | auto_client_out | 1   | DCache向下发出的A通道请求是否有效 |
| auto_client_out_a_bits_opcode | output | dcache | l2cache | auto_client_out | 3   | 操作码，表示A通道携带消息的类型 |
| auto_client_out_a_bits_param | output | dcache | l2cache | auto_client_out | 3   | 消息相关参数 |
| auto_client_out_a_bits_size | output | dcache | l2cache | auto_client_out | 3   | 操作数大小的对数n（2ˆn个字节） |
| auto_client_out_a_bits_source | output | dcache | l2cache | auto_client_out | 6   | 每条链路源master的id |
| auto_client_out_a_bits_address | output | dcache | l2cache | auto_client_out | 36  | 操作的目标地址，以字节为单位，且按a_bits_size对齐 |
| auto_client_out_a_bits_user_alias | output | dcache | l2cache | auto_client_out | 2   | 当前缓存的别名号 |
| auto_client_out_a_bits_user_needHint | output | dcache | l2cache | auto_client_out | 1   |     |
| auto_client_out_a_bits_mask | output | dcache | l2cache | auto_client_out | 32  | 对目标数据的字节选择码，高有效 |
| auto_client_out_bX |     |     |     | auto_client_out |     | DCache与L2交互的B通道 |
| auto_client_out_c_X |     |     |     | auto_client_out |     | DCache与L2交互的C通道 |
| auto_client_out_d_X |     |     |     | auto_client_out |     | DCache与L2交互的D通道 |
| auto_client_out_e_X |     |     |     | auto_client_out |     | DCache与L2交互的E通道 |
| io_hartId | input | MemBlock | dcache |     | 8   | 核心标签，用于标记请求来自哪个CPU核心，取值从0～255。 |
| io_lsu_load_0_req_ready | output | dcache | LoadUnit | io_lsu | 1   | DCache中的LoadPipe是否可以接收load请求，高有效 |
| io_lsu_load_0_req_valid | input | LoadUnit | dcache | io_lsu | 1   | MemBlock中的LoadUnit请求是否有效 |
| io_lsu_load_0_req_bits_cmd | input | LoadUnit | dcache | io_lsu | 5   | 访存操作命令类型（详见src/main/scala/xiangshan/cache/CacheConstants.scala M_XRD/M_XWR/M_PFR...) |
| io_lsu_load_0_req_bits_addr | input | LoadUnit | dcache | io_lsu | 36  | load请求地址 |
| io_lsu_load_0_req_bits_instrtype | input | LoadUnit | dcache | io_lsu | 2   | 访存指令类型（Load/ Store/AMO） |
| io_lsu_load_0_resp_valid | output | dcache | LoadUnit | io_lsu | 1   | DCache返回load响应有效 |
| io_lsu_load_0_resp_bits_bank_data_X | output | dcache | LoadUnit | io_lsu | 64  | 返回目标数据，X=0～7 |
| io_lsu_load_0_resp_bits_bank_oh | output | dcache | LoadUnit | io_lsu | 8   | 独热码选择返回数据的bank |
| io_lsu_load_0_resp_bits_miss | output | dcache | LoadUnit | io_lsu | 1   | 数据在dcache中是否命中 |
| io_lsu_load_0_resp_bits_replay | output | dcache | LoadUnit | io_lsu | 1   | 是否需要重新执行当前指令 |
| io_lsu_load_0_resp_bits_tag_error | output | dcache | LoadUnit | io_lsu | 1   | load请求tag错误 |
| io_lsu_load_0_resp_bits_error_delayed | output | dcache | LoadUnit | io_lsu | 1   | 报错信息延迟一拍 |
| io_lsu_load_0_s1_kill | input | LoadUnit | dcache | io_lsu | 1   | loadpipe各级流水线状态控制信息 |
| io_lsu_load_0_s2_kill | input | LoadUnit | dcache | io_lsu | 1   |
| io_lsu_load_0_s1_paddr | input | LoadUnit | dcache | io_lsu | 36  |
| io_lsu_load_0_s1_hit_way | output | dcache | LoadUnit | io_lsu | 8   |
| io_lsu_load_0_s1_disable_fast_wakeup | output | dcache | LoadUnit | io_lsu | 1   |
| io_lsu_load_0_s1_bank_conflict | output | dcache | LoadUnit | io_lsu | 1   |
| io_lsu_load_0_s2_hit | output | dcache | LoadUnit | io_lsu | 1   |
| io_lsu_load_1_req_ready | output | dcache | LoadUnit | io_lsu | 1   | 第2条Load流水线接口 |
| io_lsu_load_1_req_valid | input | LoadUnit | dcache | io_lsu | 1   |
| io_lsu_load_1_req_bits_cmd | input | LoadUnit | dcache | io_lsu | 5   |
| io_lsu_load_1_req_bits_addr | input | LoadUnit | dcache | io_lsu | 36  |
| io_lsu_load_1_req_bits_instrtype | input | LoadUnit | dcache | io_lsu | 2   |
| io_lsu_load_1_resp_valid | output | dcache | LoadUnit | io_lsu | 1   |
| io_lsu_load_1_resp_bits_bank_data_X | output | dcache | LoadUnit | io_lsu | 64  |
| io_lsu_load_1_resp_bits_bank_oh | output | dcache | LoadUnit | io_lsu | 8   |
| io_lsu_load_1_resp_bits_miss | output | dcache | LoadUnit | io_lsu | 1   |
| io_lsu_load_1_resp_bits_replay | output | dcache | LoadUnit | io_lsu | 1   |
| io_lsu_load_1_resp_bits_tag_error | output | dcache | LoadUnit | io_lsu | 1   |
| io_lsu_load_1_resp_bits_error_delayed | output | dcache | LoadUnit | io_lsu | 1   |
| io_lsu_load_1_s1_kill | input | LoadUnit | dcache | io_lsu | 1   |
| io_lsu_load_1_s2_kill | input | LoadUnit | dcache | io_lsu | 1   |
| io_lsu_load_1_s1_paddr | input | LoadUnit | dcache | io_lsu | 36  |
| io_lsu_load_1_s1_hit_way | output | dcache | LoadUnit | io_lsu | 8   |
| io_lsu_load_1_s1_disable_fast_wakeup | output | dcache | LoadUnit | io_lsu | 1   |
| io_lsu_load_1_s1_bank_conflict | output | dcache | LoadUnit | io_lsu | 1   |
| io_lsu_load_1_s2_hit | output | dcache | LoadUnit | io_lsu | 1   |
| io_lsu_lsq_valid | output | dcache | LoadUnit | io_lsu | 1   | 需要refill的load操作给LoadQueue的响应是否有效 |
| io_lsu_lsq_bits_addr | output | dcache | LoadUnit | io_lsu | 36  |     |
| io_lsu_lsq_bits_data | output | dcache | LoadUnit | io_lsu | 256 |     |
| io_lsu_store_req_ready | output | dcache | Sbuffer | io_lsu | 1   | DCache中的MainPipe是否可以接收store请求，高有效 |
| io_lsu_store_req_valid | input | Sbuffer | dcache | io_lsu | 1   |     |
| io_lsu_store_req_bits_vaddr | input | Sbuffer | dcache | io_lsu | 39  | 虚拟地址，用于获取extra index bits |
| io_lsu_store_req_bits_addr | input | Sbuffer | dcache | io_lsu | 36  | 实地址，用于正常索引缓存 |
| io_lsu_store_req_bits_data | input | Sbuffer | dcache | io_lsu | 512 |     |
| io_lsu_store_req_bits_mask | input | Sbuffer | dcache | io_lsu | 64  |     |
| io_lsu_store_req_bits_id | input | Sbuffer | dcache | io_lsu | 64  |     |
| io_lsu_store_main_pipe_hit_resp_valid | output | dcache | Sbuffer | io_lsu | 1   | store请求命中后向Sbuffer返回的响应是否有效 |
| io_lsu_store_main_pipe_hit_resp_bits_id | output | dcache | Sbuffer | io_lsu | 64  |     |
| io_lsu_store_refill_hit_resp_valid | output | dcache | Sbuffer | io_lsu | 1   | miss的store请求完成refill之后向Sbuffer返回的响应是否有效 |
| io_lsu_store_refill_hit_resp_bits_id | output | dcache | Sbuffer | io_lsu | 64  |     |
| io_lsu_store_replay_resp_valid | output | dcache | Sbuffer | io_lsu | 1   | store请求重新执行后向Sbuffer返回的响应是否有效 |
| io_lsu_store_replay_resp_bits_id | output | dcache | Sbuffer | io_lsu | 64  |     |
| io_lsu_atomics_req_ready | output | dcache | atomicsUnit | io_lsu | 1   | DCache接收的原子请求 |
| io_lsu_atomics_req_valid | input | atomicsUnit | dcache | io_lsu | 1   |
| io_lsu_atomics_req_bits_cmd | input | atomicsUnit | dcache | io_lsu | 5   |
| io_lsu_atomics_req_bits_addr | input | atomicsUnit | dcache | io_lsu | 36  |
| io_lsu_atomics_req_bits_data | input | atomicsUnit | dcache | io_lsu | 64  |
| io_lsu_atomics_req_bits_mask | input | atomicsUnit | dcache | io_lsu | 8   |
| io_lsu_atomics_req_bits_vaddr | input | atomicsUnit | dcache | io_lsu | 39  |
| io_lsu_atomics_resp_ready | input | atomicsUnit | dcache | io_lsu | 1   |
| io_lsu_atomics_resp_valid | output | dcache | atomicsUnit | io_lsu | 1   | 原子请求完成后向atomics Unit返回的响应 |
| io_lsu_atomics_resp_bits_data | output | dcache | atomicsUnit | io_lsu | 64  |
| io_lsu_atomics_resp_bits_id | output | dcache | atomicsUnit | io_lsu | 64  |
| io_lsu_atomics_resp_bits_error | output | dcache | atomicsUnit | io_lsu | 1   |
| io_lsu_release_valid | output | dcache | Lsq | io_lsu | 1   | 写回release操作完成后向Lsq返回的消息是否有效（在lsq中用于标记对应load data是否已经被dcache给release） |
| io_lsu_release_bits_paddr | output | dcache | Lsq | io_lsu | 36  |     |
| io_csr_ distribute_csr_wvalid | input | csrCtrl | dcache | io_csr | 1   | 基于csr自定义的缓存操作写缓存指令寄存器有效 |
| io_csr_distribute_csr_waddr | input | csrCtrl | dcache | io_csr | 12  | 缓存指令寄存器号 |
| io_csr_distribute_csr_wdata | input | csrCtrl | dcache | io_csr | 64  |     |
| io_csr_update_wvalid | output | dcache | csrUpdate | io_csr | 1   | 自定义缓存操作完成后更新的csr寄存器结果写有效 |
| io_csr_update_waddr | output | dcache | csrUpdate | io_csr | 12  |     |
| io_csr_update_wdata | output | dcache | csrUpdate | io_csr | 64  |     |
| io_error_source_tag | output | MemBlock | dcache | io_error | 1   | dcache报错信息，tag错误 |
| io_error_source_data | output | MemBlock | dcache | io_error | 1   | data错误 |
| io_error_source_l2 | output | MemBlock | dcache | io_error | 1   | 来自l2的数据块本身就出错 |
| io_error_opType_fetch | output | MemBlock | dcache | io_error | 1   | 错误类型 |
| io_error_opType_load | output | MemBlock | dcache | io_error | 1   |
| io_error_opType_store | output | MemBlock | dcache | io_error | 1   |
| io_error_opType_probe | output | MemBlock | dcache | io_error | 1   |
| io_error_opType_release | output | MemBlock | dcache | io_error | 1   |
| io_error_opType_atom | output | MemBlock | dcache | io_error | 1   |
| io_error_paddr | output | MemBlock | dcache | io_error | 36  |
| io_error_report_to_beu | output | MemBlock | dcache | io_error | 1   | 将错误报告给beu |
| io_error_valid | output | MemBlock | dcache | io_error | 1   | 错误有效 |

### 接口时序

_顶层接口时序图_

1.  _非标准接口需要有关键信号的时序示意图_
2.  _标准接口说明使用的接口协议即可（如AXI、APB等）_

_例:_

1.  L2 Cache与DCache交互接口：使用TileLink总线协议
2.  Lsu请求接口时序示例
3.  图4.2展示了load请求发出到响应的信号变化，DCache可以同时接收两条load指令并处理，load_0 hit，load_1 replay。req0从Lsu的load_0接口请求缓存行line0，经过两拍查找比对后命中，返回目标数据和响应信息；req1从Lsu的load_1接口请求缓存行line1，虽然命中但由于line1和line0缓存行在同一bank中，同时读取会产生冲突，因此返回给Lsu的状态为miss，需要重新执行。

图4.2 Lsu Load请求时序

1.  图4.3展示了load miss的情形，会首先经过两拍查找对比返回miss响应告知LoadUnit，然后为miss的请求分配MSHR，等从L2 Cache读回目标数据完成refill之后，再返回lsu_lsq系列信号，包括对应的请求地址以及目标数据（图中所示为lsu_load_0_resp_miss拉高之后的第13拍，完成refill）。

图4.3 Lsu Load请求miss时序

1.  图4.4展示了store请求hit从发出到响应的信号变化，store_buffer连续发来三个store请求均命中，直接修改缓存行内容后在req_valid拉高的第四拍返回对应的写有效响应。

图4.4 Lsu Store hit请求时序

1.  图4.5展示了store miss的情形，req_id为0的store_req被Dcache接收后，由于查找不命中，先不返回任何响应，DCache会向L2发出Acquire请求获取缺失的数据块进行重填，后续req_id为1的store请求可以继续被DCache接收并命中，返回对应的hit_resp；等到从L2读回目标数据并完成refill操作之后，DCache向store_buffer返回refill_hit_resp响应信号，完成store操作。

图4.5 Lsu Store miss请求时序

1.  图4.6展示了原子指令命中的情况下发出到响应的接口时序，req为AMO请求中的M_XA_ADD，DCache接收请求后经过8拍，先查询访问缓存行数据，命中后停留两拍完成运算操作后再将结果写回到缓存行中，完成上述所有操作之后在req_valid拉高的第9拍返回响应。

图4.6 Lsu Atomics hit请求时序

### 时钟复位

_描述时钟相关设计：时钟域划分、时钟信号来源、时钟频率、时钟门控等。_

_描述复位相关设计：复位信号来源、异步复位还是同步复位、复位过程、解复位过程。_

_描述时钟信号与复位信号的对应关系，例如：_

|     |     |     |
| --- | --- | --- |
| Module | Clock | Reset |
| Core | Clk_core | rst_core_logic_n<br><br>rst_core_cfg_n |
|     | Clk_iref (apb_slave) | rst_iref_n |
| DDRC/P | Clk_ddr_c_p | Rst_ddrc_n<br><br>Rst_ddrp_n |
|     | Clk_ddr_axi | Rst_ddri_n |

### 寄存器配置

_如果模块涉及寄存器配置（包括状态信息、统计信息通过寄存器上报软件）需要简要描述相关的寄存器，描述可使用表格，格式如下。_

_总体AS可忽略此节_

表4.2 XXXX寄存器说明

|     |     |     |     |     |
| --- | --- | --- | --- | --- |
| **寄存器** | **地址** | **复位值** | **属性** | **描述** |
| cfg_fetch_en | 0X0 | 32’d0 | RW  | bit31-1: 保留<br><br>bit0: fetch_en寄存器配置信号 |
| cfg_clk_sel | 0X 4 | 32’d0 | RW  | bit31-1: 保留<br><br>bit0: 时钟动态切换信号<br><br>0：选择晶振时钟<br><br>1：选择PLL时钟 |
| pll_lock | 0X 8 | 32’d0 | RO  | bit31-1: 保留<br><br>bit0: PLL锁定信号<br><br>0：PLL未锁定<br><br>1：PLL锁定 |
|     |     |     |     |     |

_注：RO——只读寄存器；RW——可读可写寄存器_

### 补充说明

_可选项。按照模块特点，根据4.1整体框图的划分，补充部分核心模块、关键电路、关键信号信号的说明。_

## 模块设计

_模块设计的标准：能用于指导RTL代码的编写。理想情况下，RTL代码是对设计方案的翻译。_

_模块设计面向的对象：模块设计人员、模块验证人员_

_本模块下面各级子模块的详细设计说明。包括模块功能概述、模块IO、模块的设计框图、关键设计（流水线、memory（ram、fifo、寄存器组等）、主控制电路（包含不限于状态机、仲裁、关键握手时序等））。_

_对于关键设计描述要求：_

1.  _Memory（ram、寄存器组、fifo等）：宽度、深度、接口含义、读写时序、data的详细描述、data在memory中存放的格式等信息_
2.  _流水：有流水线框图、每一级流水线描述_
3.  _仲裁：仲裁策略、优先级处理等_
4.  _状态机：有状态机设计图，需要有每个状态描述、状态之间的跳转条件、复位状态等。_

_例如：_

### 二级模块LoadPipe

#### 功能

用流水线控制Load请求的处理，与Load访存流水线紧耦合，经过4级流水线读出目标数据或返回miss/replay响应。

#### 整体框图

#### 接口列表

_写到 接口文档模板V1.0.xlsx 里_

【腾讯文档】io.miss.req.valid

https://docs.qq.com/sheet/DUUZxaHVqeFVFUEZE?tab=t6row6

#### 接口时序

如下图所示，req1第一拍被loadpipe接收，读meta和tag；第二拍进行tag比较判断miss；第三拍向lsu返回响应，lsu_resp_miss拉高表示没有命中，暂时无法返回数据，同时向miss queue发出miss请求；第四拍检查报告是否有ecc错误，并更新replacer替换算法中的状态。req2和req3紧接着req1发出，同样在stage_0被接收，读meta和tag；第二拍发现命中，发出data读请求；第三拍获得data，向lsu返回带load数据的响应；第四拍更新PLRU，报告ecc错误。

#### 关键电路

LoadPipe 各级流水线功能：

Stage 0: 接收 LoadUnit 中流水线计算得到的虚拟地址：根据地址读tag 和 meta ;

Stage 1: 获得对应的 tag 和 meta 的查询结果；从load unit接收物理地址，进行tag比较判断是否命中；根据地址读data；检查l2_error；

Stage 2: 获得对应data结果；如果load miss则向miss queue发送miss请求，尝试分配MSHR项；向Load Unit返回load请求的响应；校验tag_error；

Stage 3: 更新替换算法状态；向bus error unit上报1-bit ecc校验错误（包括dcache发现的data错误，dcache发现的tag错误，以及从L2获取数据块时已经存在的错误）。

### 二级模块MissQueue

#### 功能

负责处理miss的load、store和原子请求，包含16项Miss Entry, 每一项负责一个请求，通过一组状态寄存器控制其处理流程。

对于miss的load请求，Miss Queue为它分配一项空的Miss Entry，并且可以在一定条件下合并请求或拒绝请求，分配后在Miss Entry中记录相关信息。Miss Entry在接收到有效请求后会向 L2 发送 Acquire 请求，如果是对整个 block 的覆盖写则发送 AcquirePerm (L2 将会省去一次 sram 读操作)，否则发送 AcquireBlock；等待 L2 返回权限 (Grant) 或者数据加权限 (GrantData)；在收到 GrantData 每一个 beat 后要将数据转发给 Load Queue；在收到 Grant / GrantData 第一个 beat 后向 L2 返回 GrantAck；在向下级缓存Acquire数据块的过程中，会在接收到数据前先接收到一个对应的l2_hint信号（由L2 Cache在发送回填数据的前三拍生成），在收到hint信号后，向MainPipe提前发送refill请求；在收到Grant/GrantData的最后一个beat后，通过端口refill_info将回填数据前递到MainPipe的s2，并等待应答，完成数据回填；最后释放Miss Entry。

对于miss 的store请求，和load的流程基本一致, 区别在于不需要把回填的数据转发给 Load Queue，而是在最终完成回填后由 MainPipe向 Store Buffer 返回应答, 表示 store 已完成。

对于miss的原子指令，在 Miss Queue 中分配一项空的 Miss Entry, 并在 Miss Entry 中记录相关信息；向 L2 发送 AcquireBlock 请求；等待 L2 返回 GrantData；在收到 GrantData 第一个 beat 后向 L2 返回 GrantAck；与普通miss的回填流程一致，会在收到GrantData前先收到l2_hint，向MainPipe发送请求，随后在MainPipe中完成替换和回填，完成后向Miss Entry返回应答；最后释放Miss Entry。

#### 整体框图

#### 接口列表

_写到 接口文档模板V1.0.xlsx 里_

#### 接口时序

下图展示了一个load miss请求进入MissQueue之后的接口时序。请求到达后分配miss entry，下一拍向L2发送acquire请求，第二拍再向main pipe发送replace请求；接收到grant数据的第一个beat之后，向ldq返回load响应，接收到grant数据的最后一个beat之后，下一拍向refill pipe发出回填请求。

#### 关键电路

介绍 MissQueue 的入队（alloc/merge/reject 等等）逻辑及其响应逻辑；介绍 MSHR 给 LoadUnit 的数据前递逻辑；介绍预取相关信号的逻辑等。

1\. MissQueue 入队处理：

MissQueue对于新入队请求，总的操作可分为响应和拒绝，而响应又可以分为分配和合并。Miss Queue 支持一定程度的请求合并, 从而提高 miss 请求处理的效率。

- 空项分配：如果新的miss请求不符合合并或者拒绝条件，则为该请求分配新的 Miss Entry。
- 请求合并条件：当已分配的 Miss Entry (请求 A) 和新的 miss 请求 B 的块地址相同时，在下述两种情况下可以将请求B合并：

1． 向L2的Acquire 请求还没有握手, 且 A 是 load 请求, B 是 load 或 store 请求，即A还未成功发起对L2的读请求前可以合并B，一起发送Acquire；

2． 向 L2 的 Acquire 已经发送出去，但是还没有收到 Grant(Data)，或收到 Grant(Data) 但还没有转发给 Load Queue，且 A 是 load 或 store 请求，B 是 load 请求，即新来的load请求可以在refill前合并，而store请求只能在acquire握手前合并。

- 请求拒绝条件：下述两种情况下需要将新的miss请求拒绝，该请求会在一定时间后重新发出：

1.  新的 miss 请求和某个 Miss Entry 中请求的块地址相同, 但是不满足请求合并条件；
2.  Miss Queue已满

2\. MSHR给LoadUnit数据前递：

MissQueue支持数据前递，如果，lsq重发信号有效（具体重发逻辑请参考LoadQueueReplay部分，选出最合适的最老指令），在loadUnit的stage1，前递指定的mshrid以及地址，MissQueue拿到前递信息后，去比对，如果匹配，直接将重填的数据在LoadUnits的stage2传给LoadUnit，通过前递的方式更快地获得先前请求的数据，以减少加载指令的等待时间。

1.  MissQueue 预取处理：

1.  Miss Queue 中发出的回填请求：

为了提高数据回填流程的效率，同时保持PLRU替换算法更新的时效性，MissQueue会在收到l2_hint信号后向MainPipe发出回填请求。虽然此时真正的回填数据还未到达，但是可以先在MainPipe中进行meta和tag的读取、tag的比对以及访问PLRU算法进行替换路的选取。MissQueue中数据到达后，通过refill_info前传至MainPipe的s2流水段进行回填数据的合并，然后进行后续数据的写入与替换块向下release的操作。

#### 三级模块 MissEntry

##### 功能

##### 整体框图

##### 接口列表

##### 接口时序

##### 关键电路

1.  Miss Entry 分配、合并、拒绝：

- 空项分配：如果新的miss请求不符合合并或者拒绝条件，则为该请求分配新的 Miss Entry。
- 请求合并条件：当已分配的 Miss Entry (请求 A) 和新的 miss 请求 B 的块地址相同时，在下述两种情况下可以将请求B合并：

1． 向L2的Acquire 请求还没有握手, 且 A 是 load 请求, B 是 load 或 store 请求，即A还未成功发起对L2的读请求前可以合并B，一起发送Acquire；

2． 向 L2 的 Acquire 已经发送出去，但是还没有收到 Grant(Data)，或收到 Grant(Data) 但还没有转发给 Load Queue，且 A 是 load 或 store 请求，B 是 load 请求，即新来的load请求可以在refill前合并，而store请求只能在acquire握手前合并。

- 请求拒绝条件：下述两种情况下需要将新的miss请求拒绝，该请求会在一定时间后重新发出：

1． 新的 miss 请求和某个 Miss Entry 中请求的块地址相同, 但是不满足请求合并条件；

2．Miss Queue已满。

1.  Miss Queue 状态设计：

Miss Entry由一系列状态寄存器控制操作的执行, 以及这些操作之间的顺序。s_\* 寄存器表示需要调度的请求是否发送，w_\* 寄存器表示要等待的应答是否返回，这些寄存器在初始状态下被置为 true.B, 在为请求分配一项 Miss Entry 时，会将相应的 s_\* 和 w_\* 寄存器置为 false.B，这表示请求还没有发出去，以及要等待的响应没有握手。

下面的图和表格展示了各个寄存器的含义描述以及执行的先后顺序：

|     |     |
| --- | --- |
| **状态** | **描述** |
| s_acquire | 向 L2 发送 AcquireBlock / AcquirePerm请求 |
| w_grantfirst | 等待接收到 GrantData 的第一个 beat，拉高表示接收到 |
| w_grantlast | 等待接收到 GrantData 的最后一个 beat，拉高表示接收到 |
| s_grantack | 在收到 L2 的数据后向 L2 返回应答, 在收到 Grant 的第一个 beat 时就可以返回 GrantAck |
| s_mainpipe_req | 向Main Pipe发送回填请求，将数据回填到 DCache |
| w_mainpipe_resp | 表示将原子请求发送到 Main Pipe 回填入DCache 后, 接收到 Main Pipe 的应答 |
| w_refill_resp | 表示一般的回填请求已完成，可以释放Miss Entry |
| w_l2hint | 表示当前miss请求已收到l2_hint信号，可以唤醒 |

1.  MissEntry 别名处理
2.  l2_hint不准确带来的特殊情况处理

由于一些原因的存在（通道阻塞等），可能会导致部分的回填请求无法收到准确的l2_hint信号，导致mainpipe_req发出后的三拍未收到回填的数据，需要进行重发。对于这些请求，在MainPipe的s2阶段会判断回填数据的有效性（详见MainPipe中的解释），数据无效则会向对应的MissEntry发出replay信号，MissEntry收到replay信号后会重置状态s_mainpipe_req，重新进行回填请求的发送。

另一种特殊情况为一次数据的回填流程中未收到对应l2_hint，对于这部分请求不会经历状态w_l2hint，而是在接收所有回填beat后向MainPipe发起回填请求。

介绍 MissEntry 状态机 DAG；介绍 cache 别名有关的处理。

### 二级模块 ProbeQueue

#### 功能

负责接收并处理来自L2的一致性请求，包含 16 项 Probe Entry，每一项负责一个Probe 请求, 将 Probe 请求转成内部信号后发送到 Main Pipe, 由 Main Pipe 修改被 Probe 块的权限，等Main Pipe返回应答后释放Probe Entry。

#### 整体框图

ProbeQueue只和L2通过B通道交互，以及与MainPipe互连。内部由16项entry组成，每一项通过一组状态寄存器控制请求信号的接收、转换以及发送。

#### 接口列表

#### 接口时序

下图展示了Probe Queue处理一个probe请求的接口时序，Probe Queue首先收到来自L2的probe请求，转换成内部请求并为其分配一项空的Probe Entry；经过一拍的状态转换可以向 Main Pipe 发送 probe 请求, 但由于时序考虑该请求会再被延迟一拍（probe queue里选择一项有一个arbiter， mainpipe入口也有一个arbiter选择各来源的请求，两次仲裁在一拍完成比较困难，因此在这里先锁存一拍），因此两拍后pipe_req_valid拉高；再下一拍即认为MainPipe返回了应答（这里实际上不需要等mainpipe返回resp），直接释放Probe Entry。

#### 关键电路

1\. 别名问题：

KunMingHu架构采用了32KB的VIPT cache，从而引入了 cache 别名问题。为解决别名问题，L2 Cache的目录会维护在DCache中保存的每一个物理块对应的别名位。当DCache在某个物理地址上想要获取另一别名位的块时，L2 Cache会发起Probe请求，将DCache中原有的别名块probe下来，并且在TileLink B通道中记录其别名位。Probe Queue收到请求后会将别名位和页偏移部分进行拼接，转成内部信号发送到 Main Pipe, 由 Main Pipe 访问DCache存储模块读取数据。

2\. 由原子指令引发的阻塞：

由于原子操作 (包括 lr-sc) 在 DCache 中完成，执行 LR 指令时会保证目标地址已经在 DCache 中，此时为了简化设计， LR 在 Main Pipe 中会注册一个 reservation set，记录 LR 的地址, 并阻塞对该地址的 Probe。为了避免带来死锁, Main Pipe 会在等待 SC 一定时间后不再阻塞 Probe (由参数 LRSCCycles 和 LRSCBackOff 决定), 此时再收到 SC 指令则均被视为 SC fail. 因此, 在 LR 注册 reservation set 后等待 SC 配对的时间里需要阻塞 Probe 请求对 DCache 进行操作。

介绍别名有关的处理；介绍 LR/SC 有关的阻塞逻辑

#### 三级模块 ProbeEntry

##### 功能  
Probe Queue中的子项，每一项对应负责一个Probe 请求, 接收 Probe Queue 生成的内部请求，在内部维护Probe过程中的状态, 等待 Main Pipe 完成对应数据块的修改返回应答后释放Probe Entry。

##### 整体框图

##### 接口列表

##### 接口时序

##### 关键电路  
1\. Probe Entry状态机的设计  
Probe Entry由一系列状态寄存器进行控制，由一个状态机进行Probe事务的执行。下面的表格中展示了每个Entry中包含的三个状态寄存器的含义以及状态机设计图：

|     |     |
| --- | --- |
| **状态** | **描述** |
| s_invalid | 复位状态，该Probe Entry为空项 |
| s_pipe_req | 已分配Probe请求，正在发送Main Pipe请求 |
| s_wait_resp | 已完成Main Pipe请求的发送，等待Main Pipe的应答 |

  

介绍 Probe 处理状态机

### 二级模块 MainPipe

#### 功能

用流水线控制Store, Probe, Replace以及原子操作的执行（即所有需要争用writeback queue向下层cache发起请求/写回数据的指令）。

#### 整体框图

#### 接口列表

#### 接口时序

接口时序如下图所示，req1为store请求，第一拍读meta和tag，第二拍进行tag比较发现请求miss，根据替换算法选出要替换的路，第三拍将miss请求发送给miss queue，第四拍因为miss，不会向store buffer返回响应。req2为probe请求，第一拍读meta和tag，第二拍读data，第三拍获取probe数据块结果，第四拍根据probe命令更新meta，并向writeback queue发起wb请求，返回probeAck应答。req3是amo指令，第一拍读meta和tag，第二拍进行tag比较命中，发出data读请求，第三拍获得data结果，第四拍和第五拍都处于stage_3流水级，第四拍执行指令运算，第五拍发出data写操作更新原数据块内容，并向atomic unit返回响应。

req4为req1对应的refill请求，miss queue发来refill_req的第一拍读meta，由于此时req2正在进行meta写，而metaArray写优先于读，req4在stage_0停留一拍，下一拍才能成功握手；第三拍stage_1读data，同时获得 PLRU 提供的替换选择结果，由于此时req3正在进行data写，再在stage_1停留一拍；第五拍stage_2获取要被替换的数据块data，同时从MissQueue获得前递过来的回填数据；第六拍stage_3向writeback queue发起wb请求，尝试让替换块进入wb队列，同时将回填的数据写入存储单元，并向miss queue返回refill完成响应。

#### 关键电路

1.  MainPipe 各级流水线完成的功能：

Stage 0：仲裁传入的 Main Pipeline 请求选出优先级最高者；根据请求信息判断请求所需的资源是否就位；发出 tag, meta 读请求

Stage 1：获得 tag, meta 读请求的结果；进行 tag 匹配检查, 判断是否命中；如果需要替换, 获得 PLRU 提供的替换选择结果；根据读出的 meta 进行权限检查；提前判断是否需要执行 miss queue 访问

Stage 2：获得读 data 的结果, 与要写入的数据拼合；如果 miss, 尝试将这次请求信息写入 miss queue；检查tag_error和l2_error

Stage 3：根据操作的结果, 更新 meta, data, tag；如果命中则向lsu返回store响应；如果指令需要向下层 cache 发起访问/写回数据, 则在这一级生成 writeback queue 访问请求, 并尝试写 writeback queue；检查data_error；对原子指令的特殊支持：AMO 指令在这一级停留两拍, 先完成 AMO 指令的运算操作, 再将结果写回到 dcache并返回响应；LR/SC 指令会在这里设置/检查其 reservation set queue。

1.  mainpipe争用和阻塞：

Main Pipeline 的争用存在以下优先级: probe_req > refill_req > store_req > atomic_req

一个请求只有在其所请求的资源全部就绪, 不存在 set 冲突, 且没有比它优先级更高的请求的情况下才会被接受. 来自 committed store buffer 的写请求由于时序原因, 拥有单独的检查逻辑。

1.  set阻塞逻辑：

确保并行执行的指令不会同时访问到同一个set中的不同行，以维护数据一致性和正确性即防止s3（或者s1,s2）处理的数据还没写完，s0进来的数据没读对这类情况发生。在各个阶段valid有效的情况下，MainPipe的set冲突要比对 s0和s1的，s0和s1，s0和s2的地址索引是否一致，如果一致则是出发了set冲突。阻塞s0。

1.  meta更新

meta的更新在s3中进行，Main Pipe中四种不同类型的请求中都需要在MainPipe中更新对应cache line的meta data。几种请求都通过端口meta_write进行更新，但具体的行为不同。

Probe请求在s3中根据请求中携带的probe_param参数生成需要写入的meta_coh，对应本次Probe请求希望进行的权限修改。特殊的，如果对应数据块本次的权限修改为TtoB且该数据块存在于Writeback Queue中，此时在Main Pipe中会直接将对应块的meta_coh写入Nothing，以保持和L2中缓存行状态的一致性。

对于命中的Store和AMO请求，在s1获取对应数据块的coh，在s2生成本次访问后的new_coh，在s3中对比二者决定本次是否需要进行meta的写入，如果需要进行写入则更新为s2中生成的new_coh。

对于第一次请求时发生miss，后续由MissQueue回填重新进入Main Pipe的请求，在s3中根据MissQueue回填请求中携带的L2 Acquire数据块相关的参数生成本次回填访问需要更新的miss_new_coh，进行meta的写入。

1.  AMO指令处理

AMO请求经过优先级的争用后进入MainPipe，在前两个流水级与其他几个类型指令的执行流程基本一致，在s1获的tag，meta读请求的结果，进行tag的匹配检查与meta的权限检查，判断是否amo_hit，决定该条AMO请求是否需要进入MissQueue。如果当前的AMO请求未命中缓存，则在s2阶段将这次请求信息写入 MissQueue；若本次AMO请求命中，则会在s2获取读data的结果，然后继续进入s3。进入s3后AMO指令会在这一级停留两拍，第一拍先执行AMO指令的运算操作，第二拍将对结果的修改更新写回dcache，向原子指令处理单元返回响应。

对于LR/SC指令，会在s3阶段设置/检查其reservation set queue，对lrsc_count的计数进行更新，维护执行的正确性，防止执行过程中被打断或死锁情况的出现。

1.  MainPipe写回

MainPipe的写回请求在s3发起，对于需要向下层L2 Cache发起访问/写回数据的指令，通过向Writeback Queue发起写回请求，后续经Writeback Queue处理后完成真正完成向L2 Cache的写入，MainPipe中需要进行写回的请求共三类。

对于MissQueue发回的refill请求，如果回填的数据需要替换的数据块当前在dcache中为一个有效的数据块（非Nothing），则该数据块需要被release到L2 Cache，在s3会被尝试写入wbq。

对于Probe请求，需要向下级缓存返回ProbeAck，因此需要向wbq写入请求；如果被Probe的数据块中含有脏数据的话，需要将其写回下级L2 Cache，回复ProbeAckData，也需要向wbq发送写回请求。

对于miss的AMO请求，需要进行写回操作的情形与refill的流程类似，miss的AMO请求在回填后重新进入MainPipe流水线，此时如果回填的数据块需要替换掉一个有效的数据块时，该数据块需要被release到下级cache中，会在s3生成向wbq的写回请求。

1.  MainPipe回填数据异常处理

当前所有的回填请求均由MissQueue接收到hint信号后向MainPipe提前发起，数据在MainPipe处理请求至s2时通过refill_info前递获得。因此可能出现由于l2_hint与回填数据间隔异常的现象，导致请求进入s2后对应的MSHR并未能前传有效的回填数据，对于这种异常情况采取下面的两种处理措施。

为了保证回填的效率，减少replay的次数，在s2阶段允许额外一拍数据未到达的容错，当回填请求进入s2阶段后若检查refill_info无效（s2_req_miss_without_data），则可以额外阻塞一拍，等待下一拍回填数据到达进行后续流程。

若阻塞一拍后，仍未能收到有效的回填数据，则通过s2_replay_to_mq通知对应的MSHR进行refill_req的重发，当前请求退出MainPipe，不再进行后续的数据操作。

介绍各级流水线的关键设计点，包括不限于：

介绍各级流水线的功能

介绍 s0 的请求仲裁逻辑

介绍 s0 的 set 阻塞逻辑，并介绍阻塞的原因

介绍 s3 不同请求分别如何更新 meta

介绍 LR/SC 与 AMO 指令的处理

介绍写回逻辑，那些请求需要进入 wbq

### 二级模块WritebackQueue

#### 功能

Writeback Queue包含18项WritebackEntry，负责通过TL-C的C通道向L2 Cache写回替换块(Release)，以及对Probe请求做出应答 (ProbeAck)，且支持Release和ProbeAck之间相互合并以减少请求数目并优化时序。

#### 整体框图

#### 接口列表

#### 接口时序

#### 关键电路

1\. Writeback Queue空项分配、合并与拒绝：

为了时序考虑, 在 wbq 满的时候无论新请求是否能被合并都会被拒绝; 而当 wbq 不满的时候所有请求都会被接收, 此时或者为新请求分配空项, 或者将新请求合并到已有的 Writeback Entry 中, 后面在状态维护部分将会看到 Writeback Entry 任何时候都可以合并进新的 Release 或 ProbeAck 请求。因此 NanHu 架构中判断写回队列能否入队只需要看队列有没有空项即可。

2\. 请求阻塞条件：

TileLink 手册对并发事务的限制要求如果 master 有 pending Grant (即还没有发送 GrantAck), 则不能发送相同地址的 Release. 因此所有 miss 请求在进入 Miss Queue 时如果发现和 Writeback Queue 中某一项有相同地址, 则该 miss 请求会被阻塞.

5\. WritebackQueue 项数必须大于 MissQueue 项数，因为每一个miss的请求通常对应一个需要writeback的替换块，而wb_queue除了写回替换块之外，还需要对probe请求做出应答。为了避免请求在wbq造成拥堵，wbq的项数需要大于missqueue项数。

包括不限于：

介绍 wbq 入队逻辑（alloc/merge/reject）

1.  介绍对 Probe TtoB 请求的额外检查
2.  介绍 wbq 项数要求（必须大于 MissQueue 项数）及其原因

#### 三级模块 WritebackEntry

##### 功能

##### 整体框图

##### 接口列表

##### 接口时序

##### 关键电路

状态设计：Writeback Entry中的状态机设计如下图表所示：

|     |     |
| --- | --- |
| **状态** | **描述** |
| s_invalid | 复位状态，该 Writeback Entry 为空项 |
| s_sleep | 准备发送Release请求, 但暂时sleep并等待refill请求唤醒 |
| s_release_req | 正在发送 Release 或者 ProbeAck 请求 |
| s_release_resp | 等待ReleaseAck请求 |

介绍状态机，包括一般情况下的 ProbeAck 与 Release 处理流程，以及各种请求之间合并的处理流程。

### 关键电路

_例如：_

#### 时钟切换电路

上述CRG框图中，紫色粗框内的clock_mux是动态时钟切换模块，在用户程序配置PLL之后，通过配置寄存器cfg_clk_sel=1将系统时钟从晶振动态切换到PLL时钟。

为了保证时钟动态切换不会导致系统出错，需要使用无毛刺时钟切换电路，电路图如下：

图 2 无毛刺时钟切换电路图

上图中，下面两个寄存器的复位值为1，上面两个寄存器的复位值为0。复位时，clk_out默认选择clk0时钟。

对于两级同步寄存器，同步器的第一级采用时钟上升沿触发，第二级采用时钟下降沿触发。

## PPA

_内容包含:_

1.  _Power_

_描述功耗设计目标_

_详细描述设计的功耗预估情况_

1.  _Performance_

_详细描述设计的性能目标数据_

_详细描述性能的预估情况_

1.  _Area_

_详细描述设计的面积目标数据_

_详细描述面积的预估情况_

_4.为优化PPA做的一些关键设计点（例如为了时序收敛做的一些面积/功耗/性能上的折中）_

## 验证关注点

_从设计角度列举需要验证人员特别关注的测试点。_

_不涉及填“NA”_

## Floorplan 建议

_芯片的floorplan考虑，依据数据流向，IO排布，模块大小进行芯片布局摆放设计_

_不涉及填“NA”_

## 遗留问题

_需要跟踪的遗留问题_

_不涉及填“NA”_