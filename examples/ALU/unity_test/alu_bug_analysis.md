
## 未测试通过检测点分析

<FG-SIMPLE>

#### 加法 <FC-ADD>
- <CK-CIN-OVERFLOW> CK-CIN-OVERFLOW：在溢出时，未考虑CIN，Bug置信度 98% <BUG-RATE-98>

#### 减法  <FC-SUB>
- <CK-UN-COVERED> 忽略该检查点 <BUG-RATE-0>

<FG-HARD>

#### 位操作功能 <FC-BITOP>
- <CK-SHL> CK-SHL：左移操作不对，原因未知，Bug置信度 10% <BUG-RATE-98>
