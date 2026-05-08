from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Union, Any

class CheckPoint(BaseModel):
    id: str
    style: str
    description: str
    sva_body: Optional[str] = Field(None, description="SVA code body, synced from .sv file")

class FunctionPoint(BaseModel):
    id: str
    description: str = ""
    check_points: List[CheckPoint] = []

class FunctionGroup(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    functions: List[FunctionPoint] = []

class FormalSpec(BaseModel):
    parameters: Optional[Dict[str, Union[int, str]]] = Field(None, description="Global parameters like WIDTH, NUM_PORTS")
    whitebox_signals: Optional[List[str]] = Field(None, description="Extra signal declarations for whitebox verification (e.g. 'logic [31:0] state_r')")
    function_groups: List[FunctionGroup] = []

class IterationEntry(BaseModel):
    timestamp: str
    pass_count: int
    fail_count: int
    tt_count: int
    cover_pass: int
    cover_fail: int

class RunResults(BaseModel):
    """Auto-collected layer: Automatically overwritten by Checker execution"""
    timestamp: str
    log_hash: str
    stats: Dict[str, int]
    failing_properties: List[str]
    tt_properties: List[str]
    uncovered_signals: List[str] = []
    iteration_history: List[IterationEntry] = []

class AnalysisEntry(BaseModel):
    """Manual analysis layer: Filled by LLM, Checker only appends, never overwrites"""
    id: str
    prop_name: str
    analysis: str = Field("[LLM-TODO]", description="Detailed analysis process")
    root_cause: Optional[str] = Field(None, description="TT: Analysis root cause")
    action: Optional[str] = Field(None, description="TT: Action: ACCEPTED, FIXED")
    action_detail: str = ""
    related_assume: Optional[str] = None
    prop_type: Optional[str] = None
    sva_code: Optional[str] = None
    resolution: Optional[str] = Field(None, description="FA: Resolution: RTL_BUG, ENV_FIXED, etc.")

class BugEntry(BaseModel):
    id: str
    property: str
    ck_id: str = "[LLM-TODO]"
    fg_id: str = "[LLM-TODO]"
    fc_id: str = "[LLM-TODO]"
    rtl_file: str = "[LLM-TODO]"
    rtl_line: int = 0
    description: str = "[LLM-TODO]"
    root_cause: str = "[LLM-TODO]"
    trigger: str = "[LLM-TODO]"
    expected: str = "[LLM-TODO]"
    actual: str = "[LLM-TODO]"
    fix: str = "[LLM-TODO]"
    severity: str = "[LLM-TODO]"
    confidence: str = "[LLM-TODO]"

class AnalysisData(BaseModel):
    tt_entries: List[AnalysisEntry] = []
    fa_entries: List[AnalysisEntry] = []

class FormalRecords(BaseModel):
    dut: str
    spec: Optional[FormalSpec] = None
    run_results: Optional[RunResults] = None  # 🔵 自动层：实时反映最近一次运行结果
    analysis: Optional[AnalysisData] = None   # 🟡 分析层：LLM 填写的持久化内容
    bugs: Optional[List[BugEntry]] = None
    extra_config: Optional[Dict[str, Any]] = Field(None, description="Extra config for tools, e.g. clock/reset settings")

