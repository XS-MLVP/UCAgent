<FG-CTRL>

#### 控制功能 <FC-FSM>
- <CK-FSM-GUARD> FSM跳转缺少保护；置信度：高 <BG-STATIC-001-GUARD>
  - <LINK-BUG-[BG-TBD]>
    - <FILE-rtl/DUT.v:13>
- <CK-FSM-RESET> FSM复位缺少同步；置信度：中 <BG-STATIC-002-RESET>
  - <LINK-BUG-[BG-TBD]>
    - <FILE-rtl/DUT.v:11-12>

<FG-DATA>

#### 数据功能 <FC-PIPE>
- <CK-PIPE-WIDTH> 数据通路位宽可能不足；置信度：低 <BG-STATIC-003-WIDTH>
  - <LINK-BUG-[BG-TBD]>
    - <FILE-rtl/DUT.v:7>
