
对于为通过的检测点，需要在 `{DUT}_bug_analysis.md`中进行标记说明

例如：

## 未测试通过检测点分析

<FG-SIMPLE>

#### 加法 <FC-ADD>
- <CK-CIN-OVERFLOW> CK-CIN-OVERFLOW：在溢出时，未考虑CIN，Bug置信度 98% <BUG-RATE-98>

#### 减法  <FC-SUB>
- <CK-UN-COVERED> 忽略该检查点 <BUG-RATE-0>

<FG-HARD>

#### 位操作功能 <FC-BITOP>
- <CK-SHL> CK-SHL：左移操作不对，原因未知，Bug置信度 10% <BUG-RATE-98>


每一个非通过的，检测点 `<CK-*>`都需要有一个 `<BUG-RATE-x>`与之对应，其中的x标识，bug置信度，取值范围`0-100`。
