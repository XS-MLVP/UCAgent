"""Canonical YAML models for Formal task inputs, typed results, and analysis."""

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
    run_id: Optional[str] = None
    input_fingerprint: Optional[str] = None
    property_kinds: Dict[str, str] = Field(default_factory=dict)
    property_evidence: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str
    log_hash: str
    stats: Dict[str, int]
    failing_properties: List[str]
    tt_properties: List[str]
    assert_failing_properties: Optional[List[str]] = None
    cover_failing_properties: Optional[List[str]] = None
    uncovered_signals: List[str] = []
    iteration_history: List[IterationEntry] = []

class AnalysisEntry(BaseModel):
    """Manual analysis layer: Filled by LLM, Checker only appends, never overwrites"""
    id: str
    prop_name: str
    evidence_ref: Optional[Dict[str, Any]] = None
    analysis: str = Field("[LLM-TODO]", description="Detailed analysis process")
    root_cause: Optional[str] = Field(None, description="TT: Analysis root cause")
    action: Optional[str] = Field(None, description="TT: Action: ACCEPTED, FIXED")
    action_detail: str = ""
    related_assume: Optional[str] = None
    prop_type: Optional[str] = None
    sva_code: Optional[str] = None
    resolution: Optional[str] = Field(None, description="FA: Resolution: RTL_BUG, ENV_FIXED, etc.")

class BugEntry(BaseModel):
    """One property observation linked to an explicit shared root-cause identity."""

    root_cause_id: str = ""
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
    """Current-input analysis keyed by exact machine property identities."""

    source_fingerprint: Optional[str] = None
    tt_entries: List[AnalysisEntry] = []
    fa_entries: List[AnalysisEntry] = []

class FormalRecords(BaseModel):
    dut: str
    planning: Optional[Dict[str, Any]] = None
    basic_info: Optional[Dict[str, Any]] = None
    spec: Optional[FormalSpec] = None
    run_results: Optional[RunResults] = None  # 🔵 自动层：实时反映最近一次运行结果
    analysis: Optional[AnalysisData] = None   # 🟡 分析层：LLM 填写的持久化内容
    bugs: Optional[List[BugEntry]] = None
    extra_config: Optional[Dict[str, Any]] = Field(None, description="Extra config for tool execution, e.g. TCL timeout/commands")
    summary: Optional[Dict[str, Any]] = None


def semantic_inputs(records: Union[Dict[str, Any], FormalRecords]) -> Dict[str, Any]:
    """Canonicalize proof inputs before fingerprinting, ignoring generated and review state."""
    model = records if isinstance(records, FormalRecords) else FormalRecords.model_validate(records)
    values = model.model_dump(exclude_none=True)
    return {key: values.get(key) for key in ("dut", "basic_info", "spec", "extra_config")}


def _normalize_value(schema: Dict[str, Any], value: Any, location: str) -> Any:
    """Validate a JSON-schema-shaped author value and fill declared optional defaults."""
    import copy
    expected = schema.get("type")
    types = expected if isinstance(expected, list) else [expected]
    matches = {"object": isinstance(value, dict), "array": isinstance(value, list),
               "string": isinstance(value, str), "integer": type(value) is int,
               "boolean": type(value) is bool, "null": value is None}
    if expected is not None and not any(matches.get(kind, False) for kind in types):
        raise ValueError(f"{location} must be {expected}")
    if isinstance(value, dict) and "object" in types:
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            raise ValueError(f"{location} contains unsupported author fields: {sorted(set(value) - set(properties))}; see Guide_Doc/formal_data.md for the current author contract")
        result = copy.deepcopy(value)
        for key, child in properties.items():
            if key not in result and "default" in child:
                result[key] = copy.deepcopy(child["default"])
            if key in result:
                result[key] = _normalize_value(child, result[key], f"{location}.{key}")
        return result
    if isinstance(value, list) and "array" in types:
        return [_normalize_value(schema["items"], item, f"{location}[{index}]") for index, item in enumerate(value)]
    if type(value) is int and "minimum" in schema and value < schema["minimum"]:
        raise ValueError(f"{location} must be at least {schema['minimum']}")
    return copy.deepcopy(value)


def author_section_contract(section: str) -> Dict[str, Any]:
    """Return one complete public schema, completion checklist, and minimal author shape."""
    import copy
    text = {"type": "string", "default": ""}
    scalar = {"type": ["string", "integer", "boolean", "null"], "default": ""}
    strings = {"type": "array", "items": text, "default": []}
    def mapping(properties, metadata=False):
        """Describe a named container; fact rows may retain domain-specific metadata."""
        return {"type": "object", "properties": properties, "additionalProperties": metadata, "default": {}}
    def rows(properties):
        """Describe a list of facts with typed known fields and extensible metadata."""
        return {"type": "array", "items": mapping(properties, True), "default": []}
    if section == "planning":
        schema = mapping({"project_overview": text,
            "design_spec_analysis": mapping({"parameters": rows({"name": text, "default": scalar, "range": text, "note": text}),
                                             "interfaces": rows({"name": text, "direction": text, "width": scalar, "note": text})}),
            "complexity": mapping({key: text for key in ("state_space", "arithmetic_complexity", "storage_complexity", "parameterization")}),
            "verification_scope": mapping({"included": strings, "excluded": strings}), "assumptions": strings,
            "strategy": strings, "deliverables": strings, "risks": rows({"risk": text, "mitigation": text}),
            "initial_bug_suspicions": strings})
        required = ["project_overview", "verification_scope.included", "strategy", "deliverables", "risks"]
        skeleton = {"project_overview": "", "verification_scope": {"included": [""], "excluded": []},
                    "strategy": [""], "deliverables": [""], "risks": [{"risk": "", "mitigation": ""}]}
    elif section == "basic_info":
        ports = rows({"name": text, "width": scalar, "signal_type": text, "desc": text, "potential_issue": text})
        schema = mapping({"module_type": text, "is_top": {"type": ["boolean", "null"], "default": None}, "design_type": text,
            "ports": mapping({"inputs": ports, "outputs": ports}),
            "parameters": rows({"name": text, "default": scalar, "range": text, "desc": text}),
            "core_functions": strings, "correctness_requirements": strings,
            "clock_reset": mapping({"clock_count": {"type": "integer", "minimum": 0, "default": 0},
                **{key: text for key in ("clock_signal", "clock_type", "cdc_note", "reset_signal", "reset_type", "reset_init_state")}}),
            "architecture": mapping({key: text for key in ("ascii_diagram", "datapath", "control_logic")}),
            "parameter_impact": strings,
            "special_units": mapping({key: rows({"unit_type": text, "exists": {"type": "boolean", "default": False}, "note": text}) for key in ("arithmetic", "storage")}),
            "env_config_notes": mapping({"clock_constraints": strings, "reset_sequence": text, "input_constraints": strings}), "conclusion": text})
        required = ["module_type", "ports.inputs", "ports.outputs", "core_functions", "correctness_requirements"]
        skeleton = {"module_type": "", "ports": {"inputs": [{"name": "", "width": "", "desc": ""}],
                                                "outputs": [{"name": "", "width": "", "desc": ""}]},
                    "core_functions": [""], "correctness_requirements": [""],
                    "clock_reset": {"clock_count": 0, "clock_signal": "", "reset_signal": ""}}
    elif section == "summary":
        schema = mapping({"core_function": text, "overall_result": text, "acceptance_conclusion": text,
                          "completeness": mapping({key: text for key in ("safety", "liveness", "cover")}),
                          "coi_assessment": mapping({"unreachable_notes": strings})})
        required = ["core_function", "overall_result", "acceptance_conclusion", "completeness.safety", "completeness.liveness", "completeness.cover"]
        skeleton = {"core_function": "", "overall_result": "", "acceptance_conclusion": "",
                    "completeness": {"safety": "", "liveness": "", "cover": ""}}
    else:
        raise ValueError(f"No author section contract for {section}")
    schema = copy.deepcopy(schema)
    schema.pop("default", None)
    defaults = _normalize_value(schema, {}, section)
    return {"json_schema": schema, "required_at_check": required,
            "update_skeleton": _normalize_value(schema, skeleton, section), "optional_defaults": defaults}


def normalize_author_section(section: str, value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate partial authored data without accepting derived fields or guessing aliases."""
    if value is None:
        value = {}
    if section == "summary" and isinstance(value, dict) and "severe_bugs" in value:
        raise ValueError("summary.severe_bugs is derived from current verified bugs; update the Bug records rather than authoring summary rows")
    return _normalize_value(author_section_contract(section)["json_schema"], value, section)


def missing_author_fields(section: str, value: Optional[Dict[str, Any]]) -> List[str]:
    """Return every missing required author field, including incomplete list items."""
    data = normalize_author_section(section, value)
    missing = []
    for dotted in author_section_contract(section)["required_at_check"]:
        item = data
        for name in dotted.split("."):
            item = item.get(name) if isinstance(item, dict) else None
        if item is None or item == "" or item == []:
            missing.append(dotted)
        elif isinstance(item, str) and (not item.strip() or "[LLM-TODO]" in item):
            missing.append(dotted)
        elif isinstance(item, list):
            for index, entry in enumerate(item):
                if isinstance(entry, str) and (not entry.strip() or "[LLM-TODO]" in entry):
                    missing.append(f"{dotted}[{index}]")
                if isinstance(entry, dict):
                    keys = ("risk", "mitigation") if dotted == "risks" else ("name",)
                    for key in keys:
                        if not str(entry.get(key, "")).strip() or "[LLM-TODO]" in str(entry.get(key, "")):
                            missing.append(f"{dotted}[{index}].{key}")
    if section == "basic_info" and data["clock_reset"]["clock_count"] > 0 and not data["clock_reset"]["clock_signal"].strip():
        missing.append("clock_reset.clock_signal")
    return missing


def normalize_summary(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize authored conclusions only; Bug rows and machine counts are derived."""
    return normalize_author_section("summary", value)
