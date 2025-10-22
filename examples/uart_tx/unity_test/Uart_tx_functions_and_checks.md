# Uart_tx 功能点与检测点描述

## DUT 整体功能描述

Uart_tx 是一个功能完备的通用异步收发器（UART）的发送部分模块，负责将 8 位并行数据转换为符合标准 UART 协议的串行数据帧输出。模块集成了 16 字节深的 FIFO 缓冲器，支持高度可配置的数据帧格式。

### 端口接口说明

**输入端口：**
- `PCLK`：系统主时钟，1 位，所有时序逻辑在其上升沿触发
- `PRESETn`：低电平有效的异步复位信号，1 位
- `PWDATA`：并行输入数据，8 位，在 `tx_fifo_push` 有效时写入 FIFO
- `tx_fifo_push`：FIFO 写入使能信号，1 位，高电平有效
- `LCR`：线控制寄存器，8 位，配置数据帧格式
  - `LCR[1:0]`：数据位宽（00=5位，01=6位，10=7位，11=8位）
  - `LCR[2]`：停止位（0=1位，1=1.5/2位）
  - `LCR[3]`：奇偶校验使能（0=禁用，1=启用）
  - `LCR[5:4]`：奇偶校验类型（00=偶校验，01=奇校验，10=固定1，11=固定0）
- `enable`：发送过程使能信号，1 位，控制发送状态机运行

**输出端口：**
- `TXD`：串行数据输出线，1 位，空闲时保持高电平
- `busy`：发送忙标志，1 位，高电平表示正在发送数据帧
- `tx_fifo_empty`：FIFO 空标志，1 位
- `tx_fifo_full`：FIFO 满标志，1 位
- `tx_fifo_count`：FIFO 数据计数，5 位（0-16）

### 关键特性

- **波特率生成**：每个串行位占用 16 个 PCLK 时钟周期
- **FIFO 容量**：16 字节 × 8 位
- **协议兼容**：完全兼容标准 UART 协议
- **数据传输**：LSB-first（最低位先发送）

## 功能分组与检测点

### DUT测试API

<FG-API>

测试API分组，提供DUT验证时需要用到的标准API接口。

#### FIFO写入API

<FC-FIFO-PUSH>

提供向FIFO写入数据的API接口，通过设置PWDATA和tx_fifo_push信号实现数据写入。

**检测点：**
- <CK-SINGLE> 单次写入：验证单个数据的写入功能
- <CK-MULTI> 多次写入：验证连续多次写入功能
- <CK-TIMING> 时序正确：验证写入时序符合要求

#### FIFO状态查询API

<FC-FIFO-STATUS>

提供查询FIFO状态的API接口，包括读取empty、full、count等状态信号。

**检测点：**
- <CK-EMPTY> 空标志读取：验证读取empty标志的功能
- <CK-FULL> 满标志读取：验证读取full标志的功能
- <CK-COUNT> 计数读取：验证读取count值的功能

#### 串行数据监控API

<FC-TXD-MONITOR>

提供监控TXD串行输出的API接口，用于捕获和解析串行数据帧。

**检测点：**
- <CK-CAPTURE> 数据捕获：验证捕获TXD串行数据的功能
- <CK-PARSE> 帧解析：验证解析UART帧格式的功能
- <CK-VERIFY> 数据验证：验证接收数据与发送数据一致性

#### 配置设置API

<FC-CONFIG-SET>

提供设置LCR配置寄存器的API接口，用于配置数据位宽、校验位、停止位等。

**检测点：**
- <CK-SET-WIDTH> 位宽设置：验证设置数据位宽的功能
- <CK-SET-PARITY> 校验设置：验证设置校验模式的功能
- <CK-SET-STOP> 停止位设置：验证设置停止位的功能

#### 控制操作API

<FC-CONTROL-OPS>

提供控制操作的API接口，包括enable控制、复位操作等。

**检测点：**
- <CK-ENABLE-CTRL> enable控制：验证控制enable信号的功能
- <CK-RESET-OP> 复位操作：验证执行复位的功能
- <CK-WAIT-IDLE> 等待空闲：验证等待发送完成的功能

### FIFO管理功能

<FG-FIFO>

FIFO缓冲器管理功能，包括数据写入、读取、状态监控和指针管理。负责缓存待发送的数据，支持16字节的数据存储。

#### FIFO写入操作

<FC-WRITE>

通过tx_fifo_push和PWDATA信号向FIFO写入数据，包括单次写入和连续写入。

**检测点：**
- <CK-SINGLE-WRITE> 单次写入：验证单个数据写入的正确性
- <CK-CONTINUOUS-WRITE> 连续写入：验证连续多次写入的正确性
- <CK-DATA-INTEGRITY> 数据完整性：验证写入数据保持不变
- <CK-POINTER-INC> 指针递增：验证写指针正确递增

#### FIFO内部读取

<FC-READ>

状态机从FIFO内部读取数据进行发送，涉及pop信号和数据输出。

**检测点：**
- <CK-POP-SIGNAL> pop信号：验证pop信号在正确时机产生
- <CK-DATA-OUTPUT> 数据输出：验证读出的数据正确
- <CK-READ-POINTER-INC> 读指针递增：验证读指针正确递增
- <CK-READ-THROUGH> 读穿透：验证读指针更新后数据立即可见

#### FIFO空标志

<FC-EMPTY-FLAG>

tx_fifo_empty信号指示FIFO为空状态，当count为0时标志为高。

**检测点：**
- <CK-INIT-EMPTY> 初始为空：验证复位后FIFO为空
- <CK-EMPTY-WHEN-ZERO> count为0时为空：验证count=0时empty=1
- <CK-NOT-EMPTY-WHEN-DATA> 有数据时非空：验证count>0时empty=0
- <CK-EMPTY-TRANSITION> 空状态转换：验证empty标志正确转换

#### FIFO满标志

<FC-FULL-FLAG>

tx_fifo_full信号指示FIFO已满状态，当count为16时标志为高。

**检测点：**
- <CK-FULL-WHEN-16> count为16时满：验证count=16时full=1
- <CK-NOT-FULL-WHEN-SPACE> 有空间时非满：验证count<16时full=0
- <CK-FULL-TRANSITION> 满状态转换：验证full标志正确转换
- <CK-FULL-BOUNDARY> 满边界：验证第16个数据写入后标志正确

#### FIFO计数器

<FC-COUNT>

tx_fifo_count信号实时显示FIFO中的数据量（0-16）。

**检测点：**
- <CK-INIT-ZERO> 初始为0：验证复位后count为0
- <CK-INC-ON-WRITE> 写入递增：验证写入时count加1
- <CK-DEC-ON-READ> 读出递减：验证读出时count减1
- <CK-COUNT-RANGE> 计数范围：验证count在0-16范围内
- <CK-COUNT-ACCURACY> 计数准确：验证count值与实际数据量一致

#### FIFO指针管理

<FC-POINTER>

内部写指针ip_count和读指针op_count的管理，包括指针递增和回绕处理。

**检测点：**
- <CK-WRITE-PTR-INC> 写指针递增：验证写入时ip_count递增
- <CK-READ-PTR-INC> 读指针递增：验证读出时op_count递增
- <CK-WRITE-PTR-WRAP> 写指针回绕：验证ip_count从15到0的回绕
- <CK-READ-PTR-WRAP> 读指针回绕：验证op_count从15到0的回绕
- <CK-POINTER-INIT> 指针初始化：验证复位后指针清零

### 串行发送功能

<FG-TRANSMISSION>

串行数据发送功能，包括起始位、数据位、校验位、停止位的生成和串行输出。负责将FIFO中的数据按照UART协议转换为串行数据流。

#### 起始位发送

<FC-START-BIT>

生成并发送UART帧的起始位（逻辑0），持续16个时钟周期。

**检测点：**
- <CK-START-LEVEL> 起始位电平：验证起始位为逻辑0
- <CK-START-DURATION> 起始位时长：验证起始位持续16个时钟周期
- <CK-START-TIMING> 起始位时机：验证起始位在正确时机发送

#### 数据位发送

<FC-DATA-BITS>

按LSB-first顺序发送数据位，根据LCR配置发送5/6/7/8位数据。

**检测点：**
- <CK-LSB-FIRST> LSB优先：验证从最低位开始发送
- <CK-BIT-VALUE> 位值正确：验证每个数据位值正确
- <CK-BIT-ORDER> 位顺序：验证数据位发送顺序正确
- <CK-BIT-DURATION> 位时长：验证每个数据位持续16个时钟周期

#### 校验位发送

<FC-PARITY-BIT>

根据LCR配置生成并发送校验位（奇校验、偶校验或固定值）。

**检测点：**
- <CK-PARITY-VALUE> 校验值：验证校验位值计算正确
- <CK-PARITY-TIMING> 校验时机：验证校验位在数据位后发送
- <CK-PARITY-DURATION> 校验时长：验证校验位持续16个时钟周期

#### 停止位发送

<FC-STOP-BIT>

生成并发送停止位（逻辑1），根据LCR配置发送1位或2位停止位。

**检测点：**
- <CK-STOP-LEVEL> 停止位电平：验证停止位为逻辑1
- <CK-STOP-DURATION> 停止位时长：验证停止位持续16个时钟周期
- <CK-STOP-COUNT> 停止位数量：验证停止位数量符合配置

#### 串行输出

<FC-TXD-OUTPUT>

通过TXD引脚输出串行数据，空闲时保持高电平。

**检测点：**
- <CK-IDLE-HIGH> 空闲高电平：验证空闲时TXD为高
- <CK-OUTPUT-STABLE> 输出稳定：验证TXD输出在位周期内稳定
- <CK-OUTPUT-TRANSITION> 输出转换：验证TXD在正确时机转换

#### 位时序控制

<FC-BIT-TIMING>

bit_counter控制每个位的发送时序，每位持续16个时钟周期。

**检测点：**
- <CK-COUNTER-RANGE> 计数范围：验证bit_counter在0-15范围
- <CK-COUNTER-INC> 计数递增：验证bit_counter每周期递增
- <CK-COUNTER-RESET> 计数复位：验证计数到15后清零
- <CK-TIMING-ACCURACY> 时序精度：验证每位精确16个周期

#### 状态机转换

<FC-STATE-TRANS>

控制发送状态机在IDLE、START、BIT0-BIT7、PARITY、STOP1、STOP2之间转换。

**检测点：**
- <CK-IDLE-TO-START> IDLE到START：验证从IDLE正确转到START
- <CK-START-TO-BIT> START到BIT：验证从START转到BIT0
- <CK-BIT-TO-BIT> BIT间转换：验证数据位间转换
- <CK-BIT-TO-PARITY> BIT到PARITY：验证转到PARITY状态
- <CK-BIT-TO-STOP> BIT到STOP：验证跳过PARITY直接到STOP
- <CK-STOP-TO-IDLE> STOP到IDLE：验证完成后返回IDLE
- <CK-STATE-CONDITION> 转换条件：验证状态转换条件正确

#### 发送缓冲锁存

<FC-TX-BUFFER>

从FIFO读取数据并锁存到tx_buffer寄存器，在整个帧发送期间保持。

**检测点：**
- <CK-LATCH-TIMING> 锁存时机：验证在正确时机锁存数据
- <CK-BUFFER-HOLD> 数据保持：验证发送期间tx_buffer不变
- <CK-BUFFER-VALUE> 缓冲值：验证tx_buffer值与FIFO输出一致

### 数据位宽配置功能

<FG-DATA-WIDTH>

数据位宽配置功能，支持5、6、7、8位数据位宽的配置。通过LCR[1:0]进行配置，影响每个数据帧的数据位数量。

#### 5位数据配置

<FC-WIDTH-5BIT>

LCR[1:0]=00时，配置为5位数据位宽，发送BIT0-BIT4。

**检测点：**
- <CK-5BIT-COUNT> 5位数量：验证只发送5个数据位
- <CK-5BIT-SEQUENCE> 5位顺序：验证发送BIT0到BIT4
- <CK-5BIT-TRANSITION> 5位转换：验证BIT4后转到PARITY或STOP

#### 6位数据配置

<FC-WIDTH-6BIT>

LCR[1:0]=01时，配置为6位数据位宽，发送BIT0-BIT5。

**检测点：**
- <CK-6BIT-COUNT> 6位数量：验证只发送6个数据位
- <CK-6BIT-SEQUENCE> 6位顺序：验证发送BIT0到BIT5
- <CK-6BIT-TRANSITION> 6位转换：验证BIT5后转到PARITY或STOP

#### 7位数据配置

<FC-WIDTH-7BIT>

LCR[1:0]=10时，配置为7位数据位宽，发送BIT0-BIT6。

**检测点：**
- <CK-7BIT-COUNT> 7位数量：验证只发送7个数据位
- <CK-7BIT-SEQUENCE> 7位顺序：验证发送BIT0到BIT6
- <CK-7BIT-TRANSITION> 7位转换：验证BIT6后转到PARITY或STOP

#### 8位数据配置

<FC-WIDTH-8BIT>

LCR[1:0]=11时，配置为8位数据位宽，发送BIT0-BIT7。

**检测点：**
- <CK-8BIT-COUNT> 8位数量：验证发送8个数据位
- <CK-8BIT-SEQUENCE> 8位顺序：验证发送BIT0到BIT7
- <CK-8BIT-TRANSITION> 8位转换：验证BIT7后转到PARITY或STOP

#### 高位清零处理

<FC-HIGH-BIT-CLEAR>

在发送少于8位数据时，tx_buffer中未使用的高位应被清零，确保不影响校验计算。

**检测点：**
- <CK-CLEAR-TIMING> 清零时机：验证在正确时机清零高位
- <CK-CLEAR-BITS> 清零位数：验证清零正确的位
- <CK-PARITY-CORRECT> 校验正确：验证清零后校验计算正确

### 校验位配置功能

<FG-PARITY>

奇偶校验位配置功能，支持无校验、奇校验、偶校验、固定1、固定0等多种校验模式。通过LCR[3]和LCR[5:4]进行配置。

#### 无校验模式

<FC-PARITY-NONE>

LCR[3]=0时，禁用校验位，数据位后直接发送停止位。

**检测点：**
- <CK-NO-PARITY-STATE> 无PARITY状态：验证不进入PARITY状态
- <CK-NO-PARITY-BIT> 无校验位：验证数据位后直接发停止位

#### 偶校验模式

<FC-PARITY-EVEN>

LCR[3]=1且LCR[5:4]=00时，启用偶校验，校验位使数据位和校验位中1的个数为偶数。

**检测点：**
- <CK-EVEN-CALC> 偶校验计算：验证校验位计算使1的总数为偶数
- <CK-EVEN-VALUE> 偶校验值：验证校验位值正确

#### 奇校验模式

<FC-PARITY-ODD>

LCR[3]=1且LCR[5:4]=01时，启用奇校验，校验位使数据位和校验位中1的个数为奇数。

**检测点：**
- <CK-ODD-CALC> 奇校验计算：验证校验位计算使1的总数为奇数
- <CK-ODD-VALUE> 奇校验值：验证校验位值正确

#### 固定1校验

<FC-PARITY-STICK1>

LCR[3]=1且LCR[5:4]=10时，校验位固定为1。

**检测点：**
- <CK-STICK1-VALUE> 固定1值：验证校验位始终为1
- <CK-STICK1-INDEPENDENT> 固定1独立：验证不受数据位影响

#### 固定0校验

<FC-PARITY-STICK0>

LCR[3]=1且LCR[5:4]=11时，校验位固定为0。

**检测点：**
- <CK-STICK0-VALUE> 固定0值：验证校验位始终为0
- <CK-STICK0-INDEPENDENT> 固定0独立：验证不受数据位影响

#### 校验位计算

<FC-PARITY-CALC>

根据tx_buffer中的有效数据位计算校验位值（^tx_buffer）。

**检测点：**
- <CK-XOR-CALC> 异或计算：验证使用异或运算计算校验位
- <CK-VALID-BITS-ONLY> 仅有效位：验证只对有效数据位计算
- <CK-CALC-TIMING> 计算时机：验证在正确时机计算校验位

### 停止位配置功能

<FG-STOP-BITS>

停止位配置功能，支持1位或1.5/2位停止位配置。通过LCR[2]进行配置，影响数据帧的停止位长度。

#### 1位停止位

<FC-STOP-1BIT>

LCR[2]=0时，配置为1位停止位，在STOP1状态发送16个时钟周期后返回IDLE。

**检测点：**
- <CK-1BIT-DURATION> 1位时长：验证停止位持续16个周期
- <CK-1BIT-TO-IDLE> 1位后IDLE：验证STOP1后返回IDLE
- <CK-NO-STOP2> 无STOP2：验证不进入STOP2状态

#### 2位停止位

<FC-STOP-2BIT>

LCR[2]=1时，配置为1.5/2位停止位，在STOP1后进入STOP2状态，再发送16个时钟周期。

**检测点：**
- <CK-2BIT-DURATION> 2位时长：验证两个停止位各持续16周期
- <CK-STOP1-TO-STOP2> STOP1到STOP2：验证正确进入STOP2
- <CK-STOP2-TO-IDLE> STOP2后IDLE：验证STOP2后返回IDLE

### 控制信号功能

<FG-CONTROL>

控制信号处理功能，包括enable信号的暂停/恢复控制、复位功能、状态机控制等。

#### enable信号控制

<FC-ENABLE>

enable信号控制发送过程的运行，高电平有效，低电平时bit_counter停止计数。

**检测点：**
- <CK-ENABLE-HIGH> enable高有效：验证enable=1时正常运行
- <CK-ENABLE-LOW> enable低停止：验证enable=0时停止计数
- <CK-COUNTER-PAUSE> 计数器暂停：验证enable=0时bit_counter不变

#### 暂停功能

<FC-PAUSE>

enable拉低时暂停当前发送过程，保持当前状态和TXD电平不变。

**检测点：**
- <CK-STATE-HOLD> 状态保持：验证暂停时状态机状态不变
- <CK-TXD-HOLD> TXD保持：验证暂停时TXD电平不变
- <CK-PAUSE-TIMING> 暂停时机：验证在任意状态可暂停

#### 恢复功能

<FC-RESUME>

enable重新拉高后，从暂停处继续发送，bit_counter恢复计数。

**检测点：**
- <CK-RESUME-CONTINUE> 恢复继续：验证恢复后从暂停处继续
- <CK-COUNTER-RESUME> 计数器恢复：验证bit_counter恢复递增
- <CK-NO-DATA-LOSS> 无数据丢失：验证暂停恢复后数据完整

#### 异步复位

<FC-RESET>

PRESETn低电平触发异步复位，清除所有状态寄存器、FIFO、计数器等。

**检测点：**
- <CK-ASYNC-RESET> 异步复位：验证复位立即生效不依赖时钟
- <CK-RESET-ALL> 全部复位：验证所有状态清零
- <CK-RESET-TIMING> 复位时机：验证在任意时刻可复位

#### 复位后初始化

<FC-RESET-INIT>

复位后TXD恢复高电平，busy为低，FIFO清空，状态机返回IDLE。

**检测点：**
- <CK-TXD-HIGH> TXD高电平：验证复位后TXD=1
- <CK-BUSY-LOW> busy低电平：验证复位后busy=0
- <CK-FIFO-CLEAR> FIFO清空：验证复位后count=0
- <CK-STATE-IDLE> 状态IDLE：验证复位后状态为IDLE

### 状态指示功能

<FG-STATUS>

状态指示功能，包括busy标志、FIFO空满标志、FIFO计数器等状态输出信号的管理。

#### busy信号指示

<FC-BUSY>

busy信号指示发送状态，从START到最后一个STOP位期间为高，IDLE时为低。

**检测点：**
- <CK-BUSY-HIGH> busy高指示：验证发送时busy=1
- <CK-BUSY-LOW> busy低指示：验证空闲时busy=0
- <CK-BUSY-RANGE> busy范围：验证busy在START到STOP期间为高
- <CK-BUSY-TIMING> busy时机：验证busy在正确时机变化

#### 空闲状态维护

<FC-IDLE-STATE>

IDLE状态下TXD保持高电平，busy为低，等待FIFO非空且enable有效。

**检测点：**
- <CK-IDLE-TXD-HIGH> IDLE时TXD高：验证IDLE状态TXD=1
- <CK-IDLE-BUSY-LOW> IDLE时busy低：验证IDLE状态busy=0
- <CK-IDLE-WAIT> IDLE等待：验证等待FIFO非空和enable

#### 状态同步更新

<FC-STATUS-UPDATE>

所有状态信号在时钟上升沿同步更新，确保状态一致性。

**检测点：**
- <CK-SYNC-UPDATE> 同步更新：验证状态在时钟上升沿更新
- <CK-CONSISTENT> 状态一致：验证各状态信号一致性

### 边界条件处理

<FG-BOUNDARY>

边界条件和异常场景处理，包括FIFO满时写入、FIFO空时读取、数据位宽边界、时序边界等特殊情况的处理。

#### FIFO满时写入

<FC-FULL-WRITE>

当FIFO已满（count=16）时继续写入，数据应被丢弃，count保持不变。

**检测点：**
- <CK-DROP-DATA> 丢弃数据：验证满时写入数据被丢弃
- <CK-COUNT-UNCHANGED> count不变：验证count保持为16
- <CK-NO-OVERFLOW> 无溢出：验证不会超出FIFO容量

#### FIFO空时读取

<FC-EMPTY-READ>

当FIFO为空（count=0）时尝试读取，指针和count应保持不变。

**检测点：**
- <CK-POINTER-HOLD> 指针保持：验证空时读取指针不变
- <CK-COUNT-ZERO> count为0：验证count保持为0
- <CK-NO-UNDERFLOW> 无下溢：验证不会出现负数

#### 空到非空转换

<FC-EMPTY-TO-NONEMPTY>

FIFO从空变为非空时，状态机应正确检测并启动发送。

**检测点：**
- <CK-DETECT-NONEMPTY> 检测非空：验证检测到FIFO非空
- <CK-START-TX> 启动发送：验证启动发送过程
- <CK-TRANSITION-TIMING> 转换时机：验证转换在正确时机

#### 满到非满转换

<FC-FULL-TO-NOTFULL>

FIFO从满变为非满时，full标志应及时更新。

**检测点：**
- <CK-FULL-CLEAR> full清除：验证full标志及时清除
- <CK-ACCEPT-WRITE> 接受写入：验证非满后可继续写入

#### bit_counter边界

<FC-BIT-COUNTER-BOUND>

bit_counter在0-15之间循环，达到15后状态转换且计数器清零。

**检测点：**
- <CK-COUNTER-MAX> 计数最大值：验证计数器最大到15
- <CK-COUNTER-WRAP> 计数器回绕：验证15后清零
- <CK-STATE-AT-15> 15时转换：验证计数到15时状态转换

#### 数据位边界

<FC-DATA-BIT-BOUND>

发送5/6/7位数据时，在对应BIT状态后正确跳转到PARITY或STOP状态。

**检测点：**
- <CK-5BIT-JUMP> 5位跳转：验证BIT4后跳转
- <CK-6BIT-JUMP> 6位跳转：验证BIT5后跳转
- <CK-7BIT-JUMP> 7位跳转：验证BIT6后跳转
- <CK-SKIP-UNUSED> 跳过未用位：验证不发送未用数据位

### 并发操作功能

<FG-CONCURRENT>

并发操作处理功能，包括FIFO同时读写、配置动态切换等并发场景的处理。

#### FIFO同时读写

<FC-SIMUL-RW>

当push和pop同时有效时，写入新数据，读出旧数据，count保持不变，指针同时递增。

**检测点：**
- <CK-SIMUL-WRITE> 同时写入：验证同时读写时写入成功
- <CK-SIMUL-READ> 同时读出：验证同时读写时读出成功
- <CK-COUNT-HOLD> count保持：验证同时读写时count不变
- <CK-BOTH-PTR-INC> 双指针递增：验证读写指针都递增

#### LCR动态切换

<FC-LCR-SWITCH>

在busy期间改变LCR，当前帧应使用旧配置，下一帧使用新配置。

**检测点：**
- <CK-CURRENT-FRAME> 当前帧旧配置：验证当前帧使用旧LCR
- <CK-NEXT-FRAME> 下一帧新配置：验证下一帧使用新LCR
- <CK-SWITCH-TIMING> 切换时机：验证配置在帧间切换

#### 连续发送

<FC-CONTINUOUS-TX>

FIFO中有多个数据时，连续发送多帧，帧间无额外间隔。

**检测点：**
- <CK-NO-GAP> 无间隔：验证帧间无额外间隔
- <CK-CONTINUOUS> 连续发送：验证连续发送多帧
- <CK-FIFO-DRAIN> FIFO排空：验证发送至FIFO为空

#### 发送中写入

<FC-TX-WHILE-PUSH>

在发送过程中向FIFO写入数据，FIFO和发送状态机应正确协同工作。

**检测点：**
- <CK-WRITE-DURING-TX> 发送中写入：验证发送时可写FIFO
- <CK-COORDINATION> 协同工作：验证FIFO和状态机协调
- <CK-NO-INTERFERENCE> 无干扰：验证写入不影响当前发送

### 协议符合性

<FG-PROTOCOL>

UART协议符合性验证，确保生成的串行数据帧完全符合标准UART协议规范。

#### 帧格式正确性

<FC-FRAME-FORMAT>

验证完整帧格式符合UART标准：起始位+数据位+校验位+停止位。

**检测点：**
- <CK-START-FIRST> 起始位在首：验证起始位在帧首
- <CK-DATA-MIDDLE> 数据位在中：验证数据位在起始位后
- <CK-PARITY-AFTER-DATA> 校验在数据后：验证校验位在数据位后
- <CK-STOP-LAST> 停止位在尾：验证停止位在帧尾
- <CK-COMPLETE-FRAME> 完整帧：验证帧完整无缺失

#### 位时序精度

<FC-BIT-TIMING-ACCURACY>

验证每个位精确持续16个时钟周期，符合波特率要求。

**检测点：**
- <CK-ALL-16-CYCLES> 全部16周期：验证所有位都是16周期
- <CK-NO-JITTER> 无抖动：验证时序稳定无抖动
- <CK-ACCURATE-BAUD> 波特率准确：验证波特率符合要求

#### LSB优先传输

<FC-LSB-FIRST>

验证数据位按LSB-first顺序发送，从最低位到最高位。

**检测点：**
- <CK-BIT0-FIRST> BIT0最先：验证最低位先发送
- <CK-ASCENDING-ORDER> 升序发送：验证按位序升序发送
- <CK-LSB-PROTOCOL> LSB协议：验证符合LSB-first协议

#### 空闲电平

<FC-IDLE-LEVEL>

验证空闲时和停止位时TXD保持高电平，符合UART协议。

**检测点：**
- <CK-IDLE-HIGH-LEVEL> 空闲高电平：验证空闲时TXD=1
- <CK-STOP-HIGH-LEVEL> 停止高电平：验证停止位TXD=1
- <CK-MARK-STATE> 标记状态：验证符合UART标记状态

#### 起始位电平

<FC-START-LEVEL>

验证起始位为低电平，且在正确时机发送。

**检测点：**
- <CK-START-LOW-LEVEL> 起始低电平：验证起始位TXD=0
- <CK-START-CORRECT-TIME> 起始正确时机：验证在正确时刻发送
- <CK-SPACE-STATE> 空格状态：验证符合UART空格状态

#### 帧间间隔

<FC-FRAME-INTERVAL>

验证连续帧之间的间隔符合协议要求。

**检测点：**
- <CK-STOP-TO-START> STOP到START：验证帧间转换正确
- <CK-MIN-INTERVAL> 最小间隔：验证至少有停止位时长
- <CK-BACK-TO-BACK> 背靠背：验证连续帧可背靠背发送
