"""Canonical YAML models for Formal task inputs, typed results, and analysis."""

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing import Annotated, List, Optional, Dict, Union, Any, Literal

class TransactionBalance(BaseModel):
    """Handshake roles for one independent source of outstanding transactions."""

    model_config = ConfigDict(extra="forbid")
    command_valid: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    command_ready: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    response_valid: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    response_ready: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    counter_bits: int = Field(default=6, strict=True, ge=1, le=32)
    binding: Optional[Literal["ingress", "egress", "internal"]] = None
    max_pending: Optional[int] = Field(None, strict=True, ge=1, description="Check command acceptance below this outstanding limit")
    reuse_on_response: Optional[Literal[True]] = Field(None, description="Allow an accepted response to free a slot in the same sample")
    zero_cycle_when: Optional[str] = Field(
        None, max_length=2000, pattern=r"^[A-Za-z0-9_ `'~!&|^<>=():\[\]+*/%?.-]+$",
        description="Optional specification-backed Boolean guard for a same-cycle command and response.",
    )

    @field_validator("zero_cycle_when")
    @classmethod
    def validate_guard(cls, guard):
        """Keep the zero-cycle exception a single expression, without comments."""
        if guard is not None and (not guard.strip() or any(x in guard for x in ("//", "/*", "*/"))):
            raise ValueError("zero_cycle_when must be a Boolean expression without comments")
        return guard

    @model_validator(mode="after")
    def validate_capacity(self):
        """Keep capacity limits representable and reuse scoped to capacity checks."""
        if self.max_pending is not None and self.max_pending >= (1 << self.counter_bits):
            raise ValueError("max_pending must fit in counter_bits")
        if self.reuse_on_response and self.max_pending is None:
            raise ValueError("reuse_on_response requires max_pending")
        return self


SignalName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]


class TransferLane(BaseModel):
    """One transferred-bit observation, sampled on a lane's valid and ready."""

    model_config = ConfigDict(extra="forbid")
    valid: SignalName
    ready: SignalName


class PackedTransferLanes(BaseModel):
    """Corresponding bits in these vectors identify per-lane handshakes."""

    model_config = ConfigDict(extra="forbid")
    valid_vector: SignalName
    ready_vector: SignalName


class LatestTransfer(BaseModel):
    """Compare each delivered value against the latest accepted sample since reset."""

    model_config = ConfigDict(extra="forbid")
    capture_valid: SignalName
    capture_ready: SignalName
    captured: SignalName
    delivery_valid: SignalName
    delivery_ready: SignalName
    observed: SignalName | PackedTransferLanes | Annotated[list[TransferLane], Field(min_length=1, max_length=64)]
    simultaneous: Literal["previous", "current"]
    reset_assertion: Literal["sync", "async"]


class CheckPoint(BaseModel):
    id: str
    style: str
    description: str
    sva_body: Optional[str] = Field(None, description="SVA code body, synced from .sv file")
    parent_ck_id: Optional[str] = None
    transaction_balance: Optional[List[TransactionBalance]] = Field(None, min_length=1, max_length=16)
    latest_transfer: Optional[LatestTransfer] = None
    initial_reset: Optional[Literal[True]] = Field(None, description="An Assume requiring reset on the initial proof sample only")
    reset_stable_after_release: Optional[Literal[True]] = Field(None, description="An Assume requiring the primary reset to stay inactive after a sampled release")
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_monitor_style(self):
        """Require each verification-only monitor to have its supported check kind."""
        import re
        if self.transaction_balance:
            if self.style.lower() not in {"seq", "assume"} or not re.fullmatch(r"CK-[A-Za-z0-9_-]+", self.id):
                raise ValueError("transaction_balance requires a Seq or egress Assume CK with a valid identifier")
            if self.initial_reset or self.reset_stable_after_release:
                raise ValueError("Use a separate Assume CK for a reset rule and for transaction_balance")
            if self.style.lower() == "assume" and any(
                rule.binding != "egress" or rule.max_pending is not None or rule.zero_cycle_when not in {None, "1'b1"}
                for rule in self.transaction_balance
            ):
                raise ValueError("An environment transaction_balance requires public egress handshakes, no capacity constraint, "
                                 "and either no same-cycle exception or the explicitly allowed 1'b1")
        if self.latest_transfer and (self.transaction_balance or self.style.lower() != "seq" or not re.fullmatch(r"CK-[A-Za-z0-9_-]+", self.id)):
            raise ValueError("latest_transfer requires a distinct Seq CK with a valid identifier")
        if self.initial_reset and self.style.lower() != "assume":
            raise ValueError("initial_reset requires an Assume CK")
        if self.reset_stable_after_release and (self.initial_reset or self.style.lower() != "assume"):
            raise ValueError("reset_stable_after_release requires a separate Assume CK")
        return self


def has_sva_body(body: str | None) -> bool:
    """Distinguish an implemented body from pending author work."""
    return isinstance(body, str) and bool(body.strip()) and "[LLM-TODO]" not in body

class FunctionPoint(BaseModel):
    id: str
    title: Optional[str] = None
    description: str = ""
    review_order: Optional[int] = Field(None, strict=True, gt=0)
    check_points: List[CheckPoint] = []

    @field_validator("title")
    @classmethod
    def validate_title(cls, title: Optional[str]) -> Optional[str]:
        if title is None:
            return None
        lines = title.splitlines()
        title = title.strip()
        if len(lines) != 1 or not title or len(title) > 60:
            raise ValueError("FC title must be one nonempty line of at most 60 characters")
        return title

class FunctionGroup(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    functions: List[FunctionPoint] = []

    @field_validator("functions")
    @classmethod
    def validate_review_order(cls, functions: List[FunctionPoint]) -> List[FunctionPoint]:
        orders = set()
        for function in functions:
            order = function.review_order
            if order is None:
                continue
            if order in orders:
                raise ValueError(f"{function.id}: review_order {order} is already used in this FG")
            orders.add(order)
        return functions

class FormalSpec(BaseModel):
    parameters: Optional[Dict[str, Union[int, str]]] = Field(None, description="Global parameters like WIDTH, NUM_PORTS")
    whitebox_signals: Optional[List[str]] = Field(None, description="Extra signal declarations for whitebox verification (e.g. 'logic [31:0] state_r')")
    function_groups: List[FunctionGroup] = []

    @model_validator(mode="after")
    def validate_checkpoint_parents(self):
        """Require every proof decomposition link to have an existing acyclic parent."""
        checks = [ck for fg in self.function_groups for fc in fg.functions for ck in fc.check_points]
        if sum(ck.initial_reset is True for ck in checks) > 1:
            raise ValueError("Only one initial_reset Assume may define the initial proof sample")
        parents = {ck.id: ck.parent_ck_id for ck in checks}
        for child, parent in parents.items():
            seen = {child}
            while parent is not None:
                if parent not in parents or parent in seen:
                    raise ValueError(f"{child}: invalid or cyclic parent_ck_id {parent}")
                seen.add(parent)
                parent = parents[parent]
        return self


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

class SpecificationGap(BaseModel):
    """Open decision about a requirement tied to a current tool result."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    requirement_ref: str = Field(min_length=1, max_length=1000, description="The exact specification or planned CK whose meaning is incomplete")
    question: str = Field(min_length=1, max_length=1000, description="The concrete behavior that needs a specification decision")
    follow_up: str = Field(min_length=1, max_length=1000, description="What decision is needed and when to revalidate the property")

    @field_validator("requirement_ref", "question", "follow_up")
    @classmethod
    def reject_placeholders(cls, value: str) -> str:
        if "[LLM-TODO" in value:
            raise ValueError("Record a concrete specification gap and follow-up.")
        return value


def validate_specification_gap(gap, result: str, evidence: dict) -> SpecificationGap:
    """Require a current abnormal result and its native evidence before deferring a decision."""
    if result not in {"FALSIFIED", "TRIVIALLY_FALSE", "COVER_UNREACHABLE"} or not evidence.get("report_sha256"):
        raise ValueError("SPEC_GAP requires a current failed assertion or unreachable Cover and its native report.")
    if result == "FALSIFIED" and not evidence.get("trace_sha256"):
        raise ValueError("SPEC_GAP for a dynamic failure requires the original native counterexample trace.")
    return SpecificationGap.model_validate(gap)


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
    resolution: Optional[str] = Field(None, description="FA: Resolution: RTL_BUG, SPEC_GAP, ENV_PENDING, COVER_EXPECTED_FAIL")
    spec_gap: Optional[SpecificationGap] = None
    expected_requirement: str = Field("", description="FA RTL_BUG author-provided specification requirement; not machine-proven")
    reference_calculations: List[Dict[str, Any]] = Field(default_factory=list, description="FA optional evidence-bound integer expressions")
    reference_results: List[Dict[str, Any]] = Field(default_factory=list, description="Machine-derived results for this FA review")

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
    description: str = Field("[LLM-TODO]", description="Machine-derived current property observation; not an impact-range claim")
    impact_assessment: str = Field("", description="Optional author impact-range hypothesis, not established by one counterexample")
    root_cause: str = "[LLM-TODO]"
    trigger: str = "[LLM-TODO]"
    expected_requirement: str = Field("[LLM-TODO]", description="Derived from the current FA review; not Bug-authored")
    reference_calculations: List[Dict[str, Any]] = Field(default_factory=list, description="Copied from current FA review")
    expected: str = Field("[LLM-TODO]", description="Machine-derived projection separating intended requirement from evidence-bound arithmetic")
    reference_results: List[Dict[str, Any]] = Field(default_factory=list, description="Machine-derived reference expression results and provenance")
    actual: str = "[LLM-TODO]"
    fix: str = "[LLM-TODO]"
    severity: str = "[LLM-TODO]"
    confidence: str = "[LLM-TODO]"

class AnalysisReviewDraft(BaseModel):
    """Prior author notes retained for review against a different proof batch."""

    source_fingerprint: str
    run_id: Optional[str] = None
    analysis: str
    expected_requirement: str = ""
    decision: str = ""
    spec_gap: Optional[SpecificationGap] = None


class AnalysisData(BaseModel):
    """Current-input analysis keyed by exact machine property identities."""

    source_fingerprint: Optional[str] = None
    tt_entries: List[AnalysisEntry] = []
    fa_entries: List[AnalysisEntry] = []
    previous_reviews: Dict[str, AnalysisReviewDraft] = Field(default_factory=dict)

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
    for group in (values.get("spec") or {}).get("function_groups", []):
        for function in group["functions"]:
            function.pop("title", None)
            function.pop("review_order", None)
            for check in function["check_points"]:
                # Parent links document proof intent, independently of the expression.
                check.pop("parent_ck_id", None)
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
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{location} must be one of {schema['enum']}")
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
            "clock_reset": mapping({"clock_count": {"type": ["integer", "null"], "minimum": 0, "default": None},
                "reset_active_level": {"type": "string", "enum": ["", "low", "high"], "default": ""},
                "reset_assertion": {"type": "string", "enum": ["", "sync", "async"], "default": ""},
                "reset_release": {"type": "string", "enum": ["", "sync", "async"], "default": ""},
                **{key: text for key in ("clock_signal", "clock_type", "cdc_note", "reset_signal", "reset_type", "reset_init_state")}}),
            "architecture": mapping({key: text for key in ("ascii_diagram", "datapath", "control_logic")}),
            "parameter_impact": strings,
            "special_units": mapping({key: rows({"unit_type": text, "exists": {"type": "boolean", "default": False}, "note": text}) for key in ("arithmetic", "storage")}),
            "env_config_notes": mapping({"clock_constraints": strings, "reset_sequence": text, "input_constraints": strings}), "conclusion": text})
        required = ["module_type", "ports.inputs", "ports.outputs", "core_functions", "correctness_requirements", "clock_reset.clock_count"]
        skeleton = {"module_type": "", "ports": {"inputs": [{"name": "", "width": "", "desc": ""}],
                                                "outputs": [{"name": "", "width": "", "desc": ""}]},
                    "core_functions": [""], "correctness_requirements": [""],
                    "clock_reset": {"clock_count": None, "clock_signal": "", "reset_signal": ""}}
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
    # The request skeleton is deliberately smaller than render defaults: optional
    # fact tables belong in their owning stage, not in every author response.
    return {"json_schema": schema, "required_at_check": required,
            "update_skeleton": copy.deepcopy(skeleton), "optional_defaults": defaults}


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
    if section == "basic_info":
        count = data["clock_reset"]["clock_count"]
        if count is not None and count > 0 and not data["clock_reset"]["clock_signal"].strip():
            missing.append("clock_reset.clock_signal")
    return missing


def normalize_summary(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize authored conclusions only; Bug rows and machine counts are derived."""
    return normalize_author_section("summary", value)
