# IntegerDivider 架构文档

## 1. 模块概述

IntegerDivider是一个符合RISC-V 32M标准的整数除法器实现,采用基4 SRT(Sweeney, Robertson, Tocher)除法算法。该模块支持有符号和无符号除法运算,能够计算商和余数,并正确处理除零、溢出等特殊情况。

### 主要特点:
- 采用Radix-4 SRT算法,每个周期选择商位数字{-2, -1, 0, 1, 2}
- 使用进位保留加法器(Carry-Save Adder)进行部分余数更新
- 采用在线转换(On-the-Fly Conversion)将冗余商表示转换为常规二进制形式
- 支持有符号和无符号32位整数除法
- 可配置输出商或余数
- 具有流水线控制和刷新机制

## 2. 总体架构

IntegerDivider由以下主要模块组成:

```
IntegerDivider (顶层)
├── PreProcess (预处理模块)
├── DivStage (迭代计算模块)
│   ├── SelectTable (商选择表)
│   └── CarrySaveAdder (进位保留加法器)
└── PostProcess (后处理模块)
    └── DivConverter (在线转换器)
```

### 2.1 PreProcess (预处理模块)
负责除法运算的初始化工作:
- 将有符号数转换为绝对值
- 对被除数和除数进行归一化(前导零计数和左移)
- 计算所需的迭代周期数
- 检测特殊情况(除零、溢出、被除数小于除数)

### 2.2 DivStage (迭代计算模块)
执行Radix-4 SRT除法的核心迭代:
- 根据部分余数和除数选择商位数字
- 使用进位保留加法器更新部分余数
- 维护进位保留形式的部分余数

### 2.3 PostProcess (后处理模块)
完成最终结果的修正和输出:
- 将进位保留形式的余数转换为常规形式
- 根据符号信息调整商和余数
- 处理特殊情况的结果输出

## 3. 整体工作流程

### 3.0 初始化阶段

为了让模块完成初始化，需要先把 `reset` 拉高 5 个周期，随后再拉低 `reset` 1个周期。


### 3.1 启动阶段

当io_ready为高(模块处于IDLE状态)、io_valid有效且io_flush无效时:
1. startDiv信号置为高电平(startDiv = io_ready && io_valid && !io_flush)
2. PreProcess模块接收被除数和除数,进行预处理
3. 如果PreProcess检测到特殊情况(`pre_io_special`有效),直接跳转到DONE状态
4. 否则,将迭代周期数`pre_io_cycle`加载到计数器,进入BUSY状态

### 3.2 迭代计算阶段
在BUSY状态下:
1. DivStage模块每个周期执行一次迭代:
   - SelectTable根据部分余数的高8位和除数的高3位选择商位数字
   - 根据选择的商位数字,通过CarrySaveAdder计算新的部分余数
   - 部分余数以进位保留形式(sum和carry)存储
   - DivConverter同步进行在线转换,逐步构建最终商

2. 计数器每周期递减1
3. 如果`io_flush`信号有效,立即返回IDLE状态
4. 当计数器减至0时,进入DONE状态

### 3.3 结果输出阶段
在DONE状态下:
1. PostProcess模块完成最终处理:
   - 将进位保留形式的部分余数相加
   - 根据余数符号判断是否需要修正(加/减除数)
   - 对余数进行符号调整和反归一化(右移)
   - 根据被除数和除数的符号调整商的符号
   - 处理特殊情况的输出

2. 根据`io_useRem`信号选择输出商或余数
3. `io_done`信号置为高电平一个周期
4. 下一周期返回IDLE状态

### 3.4 状态转换条件

**IDLE状态下的startDiv生成:**
- 条件: `io_ready && io_valid && !io_flush`
- 说明: 
  - `io_ready`在IDLE状态下为高
  - `io_valid`表示有新的除法请求
  - `!io_flush`确保没有刷新请求
  - 三个条件同时满足时生成`startDiv`脉冲

**IDLE → BUSY:**
- 条件: `io_ready && io_valid && !io_flush`(即`startDiv`有效) 且 `pre_io_special`无效
- 操作: 加载迭代周期数到计数器

**IDLE → DONE:**
- 条件: `io_ready && io_valid && !io_flush`(即`startDiv`有效) 且 `pre_io_special`有效
- 操作: 直接输出特殊情况结果

**BUSY → IDLE:**
- 条件: `io_flush`有效
- 操作: 中止当前运算

**BUSY → DONE:**
- 条件: 计数器减至0
- 操作: 完成迭代,准备输出结果

**DONE → IDLE:**
- 条件: 无条件转换
- 操作: 准备接收新的除法请求

## 4. 内部模块详细描述

### 4.1 PreProcess模块

#### 4.1.1 模块概览
PreProcess模块负责除法运算前的数据准备工作,包括符号处理、归一化和特殊情况检测。该模块采用组合逻辑和寄存器相结合的方式,在一个周期内完成预处理。

#### 4.1.2 功能流程

**符号处理:**
1. 根据`io_signed`信号判断是否为有符号除法
2. 检测被除数和除数的符号位,生成`negA`和`negB`信号
3. 将负数转换为绝对值:
   ```verilog
   posA = (negA ? ~io_dividend : io_dividend) + (negA ? 1 : 0)
   posB = (negB ? ~io_divisor : io_divisor) + (negB ? 1 : 0)
   ```

**归一化处理:**
1. 将32位数据扩展为33位(低位补0):
   ```verilog
   ifX = {posA, 1'b0}
   ifD = {posB, 1'b0}
   ```

2. 使用前导零计数器(CountLeadingZeroes)计算前导零个数:
   - `lzcA`: 被除数的前导零个数
   - `lzcB`: 除数的前导零个数

3. 左移归一化,使最高位为1:
   ```verilog
   normX = ifX << lzcA[4:0]
   normD = ifD << lzcB[4:0]
   ```

4. 计算除数归一化后需要的右移量:
   ```verilog
   shift = lzcB[5:0] + 1
   ```

**迭代周期计算:**
1. 计算前导零差值: `zeroDiff = lzcD - lzcX`
2. 判断被除数是否小于除数: `ALTB = (lzcD < lzcX)`
3. 计算结果位数: `resBits = 1 + (ALTB ? 0 : zeroDiff)`
4. 计算迭代周期数(每次迭代产生2位商):
   ```verilog
   cycle = resBits[5:1] + 1
   ```

**被除数调整:**
为了适应Radix-4算法,需要对被除数进行微调:
```verilog
rightShiftX = !resBits[0]  // 如果结果位数为奇数,需要右移1位
divXShifted = {3'b000, normX} >> rightShiftX
```

**特殊情况检测:**
1. 除零检测: `div0 = !(io_divisor.orR)`
2. 溢出检测: 
   ```verilog
   minX = io_dividend[31] && !(io_dividend[30:0].orR)  // 0x80000000
   overflow = io_signed && minX && io_divisor.andR      // 除以-1
   ```
3. 被除数小于除数: `ALTB`

#### 4.1.3 接口信号

**输入信号:**
- `io_valid`: 启动预处理
- `io_signed`: 有符号除法标志
- `io_dividend[31:0]`: 被除数
- `io_divisor[31:0]`: 除数

**输出信号:**
- `io_divX[35:0]`: 归一化并调整后的被除数(36位)
- `io_divD[35:0]`: 归一化后的除数(36位)
- `io_negX`: 被除数符号
- `io_negD`: 除数符号
- `io_shiftR[5:0]`: 余数反归一化右移量
- `io_cycle[4:0]`: 所需迭代周期数
- `io_special`: 特殊情况标志
- `io_div0`: 除零标志
- `io_ALTB`: 被除数小于除数标志
- `io_overflow`: 溢出标志

### 4.2 DivStage模块

#### 4.2.1 模块概览
DivStage模块是Radix-4 SRT除法的核心迭代单元,每个周期选择一个商位数字并更新部分余数。该模块使用进位保留形式存储部分余数,以提高运算速度。

#### 4.2.2 功能流程

**商位数字选择:**
1. 提取部分余数的高8位:
   ```verilog
   msBitsS = pSum[35:28]
   msBitsC = pCarry[35:28]
   ```

2. 提取除数的高3位:
   ```verilog
   msBitsD = io_divD[31:29]
   ```

3. SelectTable模块根据这些位选择商位数字,输出独热编码的`qsm`:
   - `qsm = 4'b1000`: 选择+2
   - `qsm = 4'b0100`: 选择+1
   - `qsm = 4'b0010`: 选择-1
   - `qsm = 4'b0001`: 选择-2
   - `qsm = 4'b0000`: 选择0

**部分余数更新:**
1. 根据商位数字选择加数:
   ```verilog
   case(qsm)
     4'b1000: addIn = ~(io_divD << 1)  // -2D
     4'b0100: addIn = ~io_divD         // -D
     4'b0010: addIn = io_divD          // +D
     4'b0001: addIn = io_divD << 1     // +2D
     default: addIn = 0                // 0
   endcase
   ```

2. 确定进位输入:
   ```verilog
   carryIn = qsm[3] || qsm[2]  // 选择-2或-1时需要进位
   ```

3. 使用CarrySaveAdder计算新的部分余数:
   ```verilog
   {nextCarry, nextSum} = CSA(pSum, pCarry, addIn, carryIn)
   ```

4. 左移2位为下一次迭代准备:
   ```verilog
   pSum <= nextSum << 2
   pCarry <= nextCarry << 2
   ```

**初始化:**
当`io_valid`有效时:
```verilog
pSum <= io_divX
pCarry <= 0
```

#### 4.2.3 时序说明
- 每个时钟周期完成一次迭代
- 商位数字选择和CSA运算在同一周期内完成
- 部分余数寄存器在时钟上升沿更新

#### 4.2.4 接口信号

**输入信号:**
- `io_valid`: 初始化信号
- `io_divX[35:0]`: 初始被除数
- `io_divD[35:0]`: 归一化除数

**输出信号:**
- `io_sum[35:0]`: 部分余数的和部分
- `io_carry[35:0]`: 部分余数的进位部分
- `io_qsm[3:0]`: 商位数字选择掩码

### 4.3 SelectTable模块

#### 4.3.1 模块概览
SelectTable实现了Radix-4 SRT除法的商选择逻辑,根据部分余数和除数的高位快速确定下一个商位数字。该模块采用查找表方法,使用预先计算的阈值进行比较。

#### 4.3.2 选择算法

**部分余数估计:**
```verilog
sum = io_sum + io_carry
p = sum[7:1]  // 取高7位作为估计值
```

**阈值表:**
模块维护4组阈值,对应商位数字{-2, -1, 0, 1, 2}的边界:
```
thresholds[0] = {-13, -14, -16, -17, -18, -20, -22, -23}  // -1的下界
thresholds[1] = {-4, -4, -6, -6, -6, -6, -8, -8}          // 0的下界
thresholds[2] = {4, 4, 6, 6, 6, 6, 8, 8}                  // 1的下界
thresholds[3] = {12, 14, 16, 17, 18, 20, 22, 23}          // 2的下界
```

**选择逻辑:**
1. 根据除数高3位`io_divD`索引阈值表
2. 将部分余数估计值`p`与阈值比较:
   ```verilog
   mask[i] = (p >= thresholds[i][io_divD])
   ```

3. 根据比较结果确定商位数字:
   ```verilog
   if (mask[3])      qsm = 4'b1000  // +2
   else if (mask[2]) qsm = 4'b0100  // +1
   else if (mask[1]) qsm = 4'b0000  // 0
   else if (mask[0]) qsm = 4'b0010  // -1
   else              qsm = 4'b0001  // -2
   ```

#### 4.3.3 接口信号

**输入信号:**
- `io_sum[7:0]`: 部分余数和的高8位
- `io_carry[7:0]`: 部分余数进位的高8位
- `io_divD[2:0]`: 除数的高3位

**输出信号:**
- `io_qsm[3:0]`: 商位数字选择掩码(独热编码)
- `io_p[6:0]`: 部分余数估计值(用于调试)

### 4.4 CarrySaveAdder模块

#### 4.4.1 模块概览
CarrySaveAdder是一个3-2进位保留加法器,能够在一个周期内将三个36位数相加,输出和与进位两部分,避免进位传播延迟。

#### 4.4.2 运算原理

**基本运算:**
对于三个输入x, y, z,计算:
```verilog
sum = x ^ y ^ z
cout[i] = (x[i-1] & (y[i-1] | z[i-1])) | (y[i-1] & z[i-1])
```

**进位处理:**
- 低35位的进位输出左移1位作为高35位的进位
- 最低位的进位由外部输入`io_cin`提供:
```verilog
cout = {(low_x & (low_y | low_z)) | (low_y & low_z), io_cin}
```

其中`low_x`, `low_y`, `low_z`为输入的低35位。

#### 4.4.3 接口信号

**输入信号:**
- `io_x[35:0]`: 第一个加数
- `io_y[35:0]`: 第二个加数
- `io_z[35:0]`: 第三个加数
- `io_cin`: 最低位进位输入

**输出信号:**
- `io_sum[35:0]`: 和输出
- `io_cout[35:0]`: 进位输出

### 4.5 DivConverter模块

#### 4.5.1 模块概览
DivConverter实现了在线转换(On-the-Fly Conversion)算法,将冗余商表示{-2, -1, 0, 1, 2}逐步转换为常规二进制补码形式。该模块维护两个寄存器Q和Q-1,每次迭代根据新的商位数字更新这两个值。

#### 4.5.2 转换算法

**商位数字解码:**
从独热编码的`io_qsm`提取符号和数值信息:
```verilog
s = io_qsm[1] | io_qsm[0]   // 符号位: -2或-1时为1
m1 = io_qsm[3] | io_qsm[0]  // 绝对值高位: 2或-2时为1
m0 = io_qsm[2] | io_qsm[1]  // 绝对值低位: 1或-1时为1
```

**转换位生成:**
```verilog
a = {(s | m1), m0}  // Q的新增2位
b = {(~m1 & (~m0 | s)), ~m0}  // Q-1的新增2位
```

**移位控制:**
```verilog
shiftA = !s      // Q是否左移
shiftB = s | (~m0 & ~m1)  // Q-1是否左移
loadA = !shiftA  // Q是否从Q-1加载
loadB = !shiftB  // Q-1是否从Q加载
```

**寄存器更新:**
```verilog
fullA = {(loadA ? B[29:0] : A[29:0]), a}
fullB = {(loadB ? A[29:0] : B[29:0]), b}
A <= fullA[31:0]
B <= fullB[31:0]
```

#### 4.5.3 工作流程
1. 初始化时,A和B都清零
2. 每次迭代:
   - 根据商位数字生成新的2位
   - 根据控制信号决定是否交换A和B的低30位
   - 将新的2位拼接到低位
   - 取结果的低32位更新寄存器

3. 迭代结束后,A包含最终商Q,B包含Q-1

#### 4.5.4 接口信号

**输入信号:**
- `io_valid`: 初始化信号
- `io_qsm[3:0]`: 商位数字选择掩码

**输出信号:**
- `io_q[31:0]`: 商Q
- `io_qm[31:0]`: 商减1 (Q-1)

### 4.6 PostProcess模块

#### 4.6.1 模块概览
PostProcess模块完成除法运算的最后处理,包括余数和商的符号修正、反归一化以及特殊情况处理。该模块分为余数处理和商处理两个主要部分。

#### 4.6.2 余数处理流程

**余数符号判断:**
```verilog
sumR = io_sum + io_carry
negR = sumR[35]  // 最高位为符号位
```

**余数修正:**
1. 根据余数符号决定是否需要加/减除数:
   ```verilog
   D = (negR ? io_divD : 0) << 2
   ```

2. 将进位保留形式转换为常规形式:
   ```verilog
   csaSum = (io_negX ? ~io_sum : io_sum) + 
            (io_negX ? ~io_carry : io_carry) + 
            (io_negX ? 15 : 0)
   ```

3. 符号修正:
   ```verilog
   fixSign = csaSum + (io_negX ? ~D : D)
   ```

4. 右移2位(因为之前左移了2位):
   ```verilog
   fixed = fixSign >>> 2
   ```

5. 反归一化(右移恢复原始位置):
   ```verilog
   shifted = fixed >>> io_shiftR
   result = shifted[31:0]
   ```

**特殊情况处理:**
```verilog
reminder = (io_div0 | io_ALTB) ? io_dividend :
           (io_overflow ? 0 : result)
```

#### 4.6.3 商处理流程

**商选择:**
根据最终余数符号选择Q或Q-1:
```verilog
pre = negR ? conv_io_qm : conv_io_q
```

**符号调整:**
```verilog
negQ = io_negX ^ io_negD  // 异号则商为负
fixQ = (negQ ? ~pre : pre) + (negQ ? 1 : 0)
```

**特殊情况处理:**
```verilog
quotient = io_div0 ? 0xFFFFFFFF :      // 除零返回全1
           io_overflow ? io_dividend :  // 溢出返回被除数
           io_ALTB ? 0 :                // 被除数<除数返回0
           fixQ                         // 正常情况
```

#### 4.6.4 时序说明
- 余数的`fixed`和商的`result`经过寄存器延迟一拍输出
- 其他处理为组合逻辑

#### 4.6.5 接口信号

**输入信号:**
- `io_valid`: 请求有效信号
- `io_dividend[31:0]`: 原始被除数
- `io_divD[35:0]`: 归一化除数
- `io_negX`: 被除数符号
- `io_negD`: 除数符号
- `io_shiftR[5:0]`: 反归一化右移量
- `io_ALTB`: 被除数小于除数标志
- `io_div0`: 除零标志
- `io_overflow`: 溢出标志
- `io_qsm[3:0]`: 商位数字选择掩码
- `io_sum[35:0]`: 最终部分余数和
- `io_carry[35:0]`: 最终部分余数进位

**输出信号:**
- `io_reminder[31:0]`: 最终余数
- `io_quotient[31:0]`: 最终商

## 5. 顶层接口信号

### 5.1 输入信号
- `io_valid`: 启动除法运算
- `io_flush`: 刷新信号,中止当前运算
- `io_signed`: 有符号除法标志
- `io_useRem`: 输出选择,1为余数,0为商
- `io_dividend[31:0]`: 被除数
- `io_divisor[31:0]`: 除数
- `clk`: 时钟信号
- `reset`: 复位信号

### 5.2 输出信号
- `io_ready`: 模块空闲,可接受新请求
- `io_done`: 运算完成标志,高电平一个周期
- `io_result[31:0]`: 运算结果(商或余数)

### 5.3 时序约束
- `io_valid`应在`io_ready`为高时有效
- `io_done`有效时,`io_result`包含有效结果
- 从`io_valid`到`io_done`的延迟不超过`19`个时钟周期

# 验证目标

主要验证除法器功能的实现是否正确、并遵循 RISC-V32M 的要求，不需要验证其他功能，例如波形、接口时序等。

## 其他

所有的文档和注释都用中文编写

## bug分析

模块采用 spinalhdl 编写，源码位于 `IntegerDivider_RTL` 目录下的多个 scala 文件中；生成的 Verilog 位于 `IntegerDivider_RTL/IntegerDivider.v`。

在bug分析时，请参考源码进行分析。
