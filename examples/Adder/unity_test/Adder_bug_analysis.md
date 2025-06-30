## 未测试通过检测点分析

<FG-ADD>

### 溢出加法功能 <FC-OVERFLOW>
- <CK-OVERFLOW_NO_CIN> 溢出加法：a + b，无进位输入，结果溢出。Bug置信度 99% <BUG-RATE-99>
- <CK-OVERFLOW_WITH_CIN> 带进位溢出加法：a + b + 1，结果溢出。Bug置信度 99% <BUG-RATE-99>

### 边界值加法功能 <FC-BOUNDARY>
- <CK-MAX_A> a为最大值：a = 2^64-1, b = 0。Bug置信度 95% <BUG-RATE-95>
- <CK-MAX_B> b为最大值：a = 0, b = 2^64-1。Bug置信度 95% <BUG-RATE-95>
- <CK-MAX_BOTH> a,b均为最大值：a = 2^64-1, b = 2^64-1。Bug置信度 99% <BUG-RATE-99>

## 缺陷根因分析

### sum 设计位宽错误

作为64位加法器，在其实现中，adder.v的第10行，sum 输出为 63 位 (WIDTH-2:0)，正确值应该为64为 (WIDTH-1:0)。adder.v与正确实现的diff如下：

```diff
10c10
<     output [WIDTH-2:0] sum,
---
>     output [WIDTH-1:0] sum,
```

由于sum只有63位，因此在测试过程中，sum结果64位为1的情况下，都会出错，从而导致 <FC-OVERFLOW>/<CK-OVERFLOW_NO_CIN>、<FC-OVERFLOW>/<CK-OVERFLOW_WITH_CIN>和 <FC-BOUNDARY>/<CK-MAX_A>、<FC-BOUNDARY>/<CK-MAX_B>、<FC-BOUNDARY>/<CK-MAX_BOTH>出错。
