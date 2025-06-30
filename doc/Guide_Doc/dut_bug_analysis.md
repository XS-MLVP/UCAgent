
对于未通过的检测点，需要在 `{DUT}_bug_analysis.md`中进行标记说明

例如：

```markdown
## 未测试通过检测点分析

<FG-SIMPLE>

#### 加法 <FC-ADD>
- <CK-CIN-OVERFLOW> CK-CIN-OVERFLOW：在溢出时，未考虑CIN，Bug置信度 98% <BUG-RATE-98>

#### 减法  <FC-SUB>
- <CK-UN-COVERED> 忽略该检查点 <BUG-RATE-0>

<FG-HARD>

#### 位操作功能 <FC-BITOP>
- <CK-SHL> CK-SHL：左移操作不对，原因未知，Bug置信度 10% <BUG-RATE-10>


## 缺陷根因分析

### 溢出 bug
在进行加法操作中，忘记了进位，导致以下检测点不通过：
- FG-SIMPLE/FC-ADD/CK-CIN-OVERFLOW

### 左移操作bug

在设计中，left shift实现有误，少写了 ... 导致以下检测点不通过：

- FG-HARD/FC-BITOP/CK-SHL

#### 未知bug

由于未知bug，导致以下检测点不通过：

- FG-SIMPLE/FC-ADD/CK-UN-COVERED
...
```

注意：每个没有测试通过的检测点 `<CK-*>`都需要有一个 `<BUG-RATE-x>`与之对应，其中的x标识bug置信度，取值范围`0-100`。需要进行缺陷分析，分析是什么原因导致了什么样的`CK-*`通过不了，如果分析不出原因，需要把对于的`CK-*`列出来。在缺陷分析章节，不需要用标签，而直接用名字，例如：`FG-SIMPLE/FC-ADD/CK-CIN-OVERFLOW`，而不是 `<FG-SIMPLE>/<FC-ADD>/<CK-CIN-OVERFLOW>`
