"""Evaluate bounded integer reference expressions against exact current evidence."""

from __future__ import annotations

import ast
import hashlib
import json


MAX_EXPRESSION_CHARS = 2048
MAX_AST_NODES = 128
MAX_BINDINGS = 20
MAX_CALCULATIONS = 10
MAX_INTEGER_BITS = 4096
MAX_SHIFT = 4096
REFERENCE_CONTRACT = {
    "entry_fields": ["id", "expression", "bindings"],
    "binding": {"source": ["initial", "sample"], "signal": "exact name from returned evidence"},
    "operators": "+ - * // % << >> & | ^ and unary + - ~",
    "semantics": "Mathematical integers, not implicit HDL width/signed arithmetic. Source values are unsigned bit patterns; explicitly express masks or signed reinterpretation. Initial and stored samples are distinct contexts, neither claims the failure cycle.",
    "limits": {"calculations": MAX_CALCULATIONS, "bindings": MAX_BINDINGS, "expression_chars": MAX_EXPRESSION_CHARS,
               "syntax_nodes": MAX_AST_NODES, "integer_bits": MAX_INTEGER_BITS, "shift": MAX_SHIFT},
    "ownership": "Submit expressions and evidence bindings, never numeric answers. Results check the expression, not whether it is the intended specification.",
}
BINARY_OPERATORS = {
    ast.Add: lambda left, right: left + right,
    ast.Sub: lambda left, right: left - right,
    ast.Mult: lambda left, right: left * right,
    ast.FloorDiv: lambda left, right: left // right,
    ast.Mod: lambda left, right: left % right,
    ast.LShift: lambda left, right: left << right,
    ast.RShift: lambda left, right: left >> right,
    ast.BitAnd: lambda left, right: left & right,
    ast.BitOr: lambda left, right: left | right,
    ast.BitXor: lambda left, right: left ^ right,
}
UNARY_OPERATORS = {ast.UAdd: lambda value: value, ast.USub: lambda value: -value, ast.Invert: lambda value: ~value}


def _bounded_integer(value: int, location: str) -> int:
    """Reject pathological intermediate/result widths before returning an integer."""
    if type(value) is not int or value.bit_length() > MAX_INTEGER_BITS:
        raise ValueError(f"{location} exceeds the supported {MAX_INTEGER_BITS}-bit integer range")
    return value


def _evaluate(node: ast.AST, values: dict[str, int], location: str) -> int:
    """Evaluate only explicitly supported literal, name, unary, and binary nodes."""
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return _bounded_integer(node.value, location)
    if isinstance(node, ast.Name) and node.id in values:
        return values[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPERATORS:
        return _bounded_integer(UNARY_OPERATORS[type(node.op)](_evaluate(node.operand, values, location)), location)
    if isinstance(node, ast.BinOp) and type(node.op) in BINARY_OPERATORS:
        left, right = _evaluate(node.left, values, location), _evaluate(node.right, values, location)
        if isinstance(node.op, (ast.LShift, ast.RShift)) and not 0 <= right <= MAX_SHIFT:
            raise ValueError(f"{location} shift amount must be between 0 and {MAX_SHIFT}")
        if isinstance(node.op, (ast.FloorDiv, ast.Mod)) and right == 0:
            raise ValueError(f"{location} divides by zero")
        return _bounded_integer(BINARY_OPERATORS[type(node.op)](left, right), location)
    raise ValueError(f"{location} contains an unsupported expression node; use integer literals, names, unary + - ~, and + - * // % << >> & | ^")


def _evidence_signal(evidence: dict, source: str, name: str, calculation_id: str) -> dict:
    """Resolve one exact named signal from one explicitly selected evidence view."""
    if source == "initial":
        signals = evidence.get("initial_values", [])
        selected = [row for row in signals if row.get("signal") == name]
        if len(selected) != 1:
            raise ValueError(f"{calculation_id}: bindings.{name} must exactly match one original initial input")
        row = selected[0]
        raw, width = row.get("value"), row.get("width")
        if row.get("has_unknown") or row.get("value_truncated") or not isinstance(raw, str):
            raise ValueError(f"{calculation_id}: bindings.{name} is unknown, truncated, or unavailable")
    elif source == "sample":
        observation = evidence.get("trace_observations") or {}
        if observation.get("status") != "available":
            raise ValueError(f"{calculation_id}: bindings.{name} has no available original signal sample")
        signals = observation.get("signals", [])
        selected = [row for row in signals if row.get("name") == name]
        if len(selected) != 1:
            raise ValueError(f"{calculation_id}: bindings.{name} must exactly match one original sampled signal")
        row = selected[0]
        raw, width = row.get("value"), row.get("width")
        if row.get("available") is not True or not isinstance(raw, str) or row.get("unknown_mask") not in (None, "0x0") or row.get("z_mask") not in (None, "0x0"):
            raise ValueError(f"{calculation_id}: bindings.{name} is unknown or unavailable in the stored sample")
        if observation.get("truncated"):
            raise ValueError(f"{calculation_id}: original signal list is truncated; {name} cannot be verified safely")
    else:
        raise ValueError(f"{calculation_id}: bindings.{name}.source must be initial or sample")
    if type(width) is not int or not 0 < width <= MAX_INTEGER_BITS:
        raise ValueError(f"{calculation_id}: bindings.{name} has an invalid or unsupported width")
    try:
        value = int(raw, 16) if raw.lower().startswith("0x") else int(raw, 2) if source == "initial" else int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{calculation_id}: bindings.{name} is not a known integer value") from exc
    value = _bounded_integer(value, f"{calculation_id}: bindings.{name}")
    if not 0 <= value < (1 << width):
        raise ValueError(f"{calculation_id}: bindings.{name} is not an unsigned bit pattern of the stated width")
    observation = evidence.get("trace_observations") or {}
    return {"source": source, "signal": name, "width": width, "value": value,
            "display": raw, "sampled_time": observation.get("sampled_time") if source == "sample" else None,
            "time_unit": observation.get("time_unit") if source == "sample" else None,
            "time_magnitude": observation.get("time_magnitude") if source == "sample" else None,
            "sample_kind": observation.get("sample_kind") if source == "sample" else "original_initialization_not_failure_cycle"}


def calculate_references(requests: list, evidence: dict) -> list[dict]:
    """Calculate bounded integer expressions using exact evidence-bound aliases.

    Arithmetic is a machine-checked calculation of the supplied expression only;
    it does not prove that the expression is the DUT specification.
    """
    if not isinstance(requests, list) or len(requests) > MAX_CALCULATIONS:
        raise ValueError(f"reference_calculations must be a list of at most {MAX_CALCULATIONS} entries")
    if not isinstance(evidence, dict) or not isinstance(evidence.get("evidence_ref"), dict):
        raise ValueError("A current evidence_ref is required to bind reference calculations")
    output = []
    seen = set()
    for index, request in enumerate(requests):
        location = f"reference_calculations[{index}]"
        if not isinstance(request, dict) or set(request) != {"id", "expression", "bindings"}:
            raise ValueError(f"{location} requires exactly id, expression, and bindings")
        identifier, expression, bindings = request["id"], request["expression"], request["bindings"]
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            raise ValueError(f"{location}.id must be a unique nonempty string")
        seen.add(identifier)
        if not isinstance(expression, str) or not expression.strip() or len(expression) > MAX_EXPRESSION_CHARS:
            raise ValueError(f"{location}.expression must contain 1..{MAX_EXPRESSION_CHARS} characters")
        if not isinstance(bindings, dict) or len(bindings) > MAX_BINDINGS:
            raise ValueError(f"{location}.bindings must contain at most {MAX_BINDINGS} explicit aliases")
        aliases = {}
        values = {}
        for alias, binding in bindings.items():
            if not isinstance(alias, str) or not alias.isidentifier() or alias.startswith("__"):
                raise ValueError(f"{location}.bindings contains an invalid alias")
            if not isinstance(binding, dict) or set(binding) != {"source", "signal"} or not isinstance(binding["signal"], str):
                raise ValueError(f"{location}.bindings.{alias} requires exactly source and signal")
            resolved = _evidence_signal(evidence, binding["source"], binding["signal"], identifier)
            aliases[alias] = resolved
            values[alias] = resolved["value"]
        try:
            tree = ast.parse(expression, mode="eval")
        except (SyntaxError, ValueError) as exc:
            raise ValueError(f"{identifier}: expression is not valid arithmetic syntax") from exc
        if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
            raise ValueError(f"{identifier}: expression exceeds {MAX_AST_NODES} syntax nodes")
        result = _evaluate(tree.body, values, identifier)
        output.append({"id": identifier, "expression": expression, "value": result,
                       "decimal": str(result), "hex": hex(result), "bindings": aliases,
                       "evidence_ref": evidence["evidence_ref"],
                       "evidence_sha256": hashlib.sha256(json.dumps(evidence["evidence_ref"], sort_keys=True).encode()).hexdigest()})
    return output


def expectation_text(requirement: str, calculations: list[dict]) -> str:
    """Label authored requirement separately from checked arithmetic results."""
    requirement = requirement.strip()
    if not requirement or "[LLM-TODO]" in requirement:
        requirement_text = "[Human specification requirement pending; author review is required.]"
    else:
        requirement_text = "Specification interpretation (author-provided; not machine-proven): " + requirement
    rows = [requirement_text]
    for result in calculations:
        rows.append(f"Checked arithmetic ({result['id']}): {result['expression']} = {result['decimal']} ({result['hex']}). This checks only the supplied expression against its evidence bindings.")
    return "\n".join(rows)


def derive_expected(requirement: str, requests: list, evidence: dict) -> tuple[str, list[dict]]:
    """Derive report text and calculations without treating them as a spec oracle."""
    calculations = calculate_references(requests, evidence)
    return expectation_text(requirement, calculations), calculations
