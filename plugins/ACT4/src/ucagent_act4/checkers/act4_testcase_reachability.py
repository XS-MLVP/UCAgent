"""Conservative checks of ACT testcase labels before and after preprocessing.

Only compiler-provided XLEN and literal expressions are evaluated. Other
macros remain unknown; this is not a replacement for the C preprocessor or
an execution coverage measurement.
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


_DESCRIPTOR = re.compile(
    r'^\s*([A-Za-z_][\w$]*)_str:\s*\.string\s+.*?\bcp:\s*[^;\"]+;\s*bin:',
    re.MULTILINE,
)
_LABEL = re.compile(r"^\s*([A-Za-z_][\w$]*):")
_DIRECTIVE = re.compile(r"^\s*#\s*(if|ifdef|ifndef|elif|else|endif|define|undef)\b(.*)")
_COMMENTS = re.compile(r'"(?:\\.|[^"\\])*"|/\*.*?\*/|//[^\n]*', re.DOTALL)


def _and(left: bool | None, right: bool | None) -> bool | None:
    if left is False or right is False:
        return False
    return True if left is True and right is True else None


def _or(left: bool | None, right: bool | None) -> bool | None:
    if left is True or right is True:
        return True
    return False if left is False and right is False else None


def _not(value: bool | None) -> bool | None:
    return None if value is None else not value


def _expression(text: str, xlen: int | None) -> bool | None:
    """Return a proved truth value, or unknown for unsupported/macro values."""
    if any(token in text for token in ("?", ":", '"', "'")):
        return None
    depth = 0
    for char in text:
        depth += (char == "(") - (char == ")")
        if depth < 0:
            return None
    if depth:
        return None
    text = re.sub(r"\bdefined\s*(?:\(\s*(\w+)\s*\)|(\w+))", "__unknown_defined", text)
    text = re.sub(r"\b(0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]+\b", r"\1", text)
    identifiers = set(re.findall(r"\b[A-Za-z_]\w*\b", text))
    if identifiers - {"__riscv_xlen", "__unknown_defined"}:
        # An unknown macro can expand into operators, not just a scalar.
        # Never prove a contradiction by assuming its expansion precedence.
        return None
    # Parenthesize C logical operands before using Python's expression parser:
    # C's ! has different precedence from Python's 'not'.
    def split_operator(value: str, operator: str) -> list[str]:
        depth, start, parts, index = 0, 0, [], 0
        while index < len(value):
            if value[index] == "(":
                depth += 1
            elif value[index] == ")":
                depth -= 1
            elif depth == 0 and value.startswith(operator, index):
                parts.append(value[start:index])
                index += len(operator)
                start = index
                continue
            index += 1
        return [*parts, value[start:]]

    def evaluate(value: str) -> int | None:
        value = value.strip()
        # Strip only parentheses enclosing the entire expression.
        while value.startswith("(") and value.endswith(")"):
            depth = 0
            for index, char in enumerate(value):
                depth += (char == "(") - (char == ")")
                if depth == 0:
                    break
            if index != len(value) - 1:
                break
            value = value[1:-1].strip()
        for operator, combine, initial in (("||", _or, False), ("&&", _and, True)):
            parts = split_operator(value, operator)
            if len(parts) > 1:
                result: bool | None = initial
                for part in parts:
                    result = combine(result, truth(evaluate(part)))
                return result
        # Do not approximate unsupported arithmetic/ternary or C precedence.
        if value.startswith("!") and not value.startswith("!="):
            rest = value[1:].strip()
            if re.fullmatch(r"!?[A-Za-z_]\w*|[0-9]+", rest) or (
                rest.startswith("(") and rest.endswith(")")
            ):
                return _not(truth(evaluate(rest)))
            return None
        try:
            node = ast.parse(value, mode="eval").body
        except (SyntaxError, ValueError, RecursionError):
            return None

        def scalar(item: ast.AST) -> int | None:
            if isinstance(item, ast.Constant) and type(item.value) is int and 0 <= item.value < (1 << 31):
                return item.value
            if isinstance(item, ast.Name) and item.id == "__riscv_xlen":
                return xlen
            if isinstance(item, ast.UnaryOp) and isinstance(item.op, ast.UAdd):
                return scalar(item.operand)
            # Negative/large integers need C signedness and conversion rules.
            return None

        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right = scalar(node.left), scalar(node.comparators[0])
            if left is None or right is None:
                return None
            op = node.ops[0]
            if isinstance(op, ast.Eq):
                return left == right
            if isinstance(op, ast.NotEq):
                return left != right
            if isinstance(op, ast.Lt):
                return left < right
            if isinstance(op, ast.LtE):
                return left <= right
            if isinstance(op, ast.Gt):
                return left > right
            if isinstance(op, ast.GtE):
                return left >= right
        return scalar(node)

    def truth(value: int | None) -> bool | None:
        return None if value is None else bool(value)

    try:
        return truth(evaluate(text))
    except RecursionError:
        return None


def inspect_source(text: str) -> dict[str, Any]:
    """Associate ACT *_str descriptors with labels and their conditional paths."""
    # C splices continuations before removing comments. Preserve original
    # starting line numbers for actionable diagnostics.
    lines, line_numbers, logical, start = [], [], "", 1
    for number, physical in enumerate(text.splitlines(), 1):
        if not logical:
            start = number
        logical += physical[:-1] if physical.endswith("\\") else physical
        if physical.endswith("\\"):
            continue
        lines.append(logical)
        line_numbers.append(start)
        logical = ""
    dangling_continuation = bool(logical)
    text = "\n".join(lines)
    # Keep strings and line numbers; drop comments before matching directives.
    text = _COMMENTS.sub(
        lambda match: match.group() if match.group().startswith('"') else
        " " + "\n" * match.group().count("\n"), text,
    )
    descriptors = set(_DESCRIPTOR.findall(text))
    labels: dict[str, list[dict[str, Any]]] = {name: [] for name in descriptors}
    states: dict[int, bool | None] = {32: True, 64: True}
    stack: list[dict[str, Any]] = []
    issues: list[str] = []
    xlen_known = True
    for start, line in zip(line_numbers, text.splitlines()):
        directive = _DIRECTIVE.match(line)
        if directive:
            kind, expression = directive.group(1), directive.group(2).strip()
            if kind in ("define", "undef"):
                if re.match(r"__riscv_xlen\b", expression):
                    xlen_known = False
                continue
            values = {x: _expression(expression, x if xlen_known else None) for x in states}
            if kind in ("ifdef", "ifndef"):
                values = {x: (kind == "ifdef") if expression == "__riscv_xlen" and xlen_known else None
                          for x in states}
            if kind in ("if", "ifdef", "ifndef"):
                stack.append({"parent": states.copy(), "taken": values.copy(), "else": False,
                              "line": start, "condition": line.strip()})
                states = {x: _and(states[x], values[x]) for x in states}
            elif not stack:
                issues.append(f"line {start}: unmatched #{kind}")
            elif kind == "endif":
                states = stack.pop()["parent"]
            else:
                frame = stack[-1]
                if frame["else"]:
                    issues.append(f"line {start}: #{kind} after #else")
                branch = {x: _and(_not(frame["taken"][x]), values[x]) if kind == "elif"
                          else _not(frame["taken"][x]) for x in states}
                states = {x: _and(frame["parent"][x], branch[x]) for x in states}
                frame["taken"] = {x: _or(frame["taken"][x], values[x]) for x in states}
                frame["else"] = kind == "else"
                frame["condition"] = line.strip()
                frame["line"] = start
            continue
        label = _LABEL.match(line)
        if label and label.group(1) in labels:
            labels[label.group(1)].append({"line": start, "states": states.copy(),
                                          "conditions": [{"line": f["line"], "text": f["condition"]}
                                                         for f in stack]})
    if stack or dangling_continuation:
        issues.append("unterminated preprocessor conditional or continuation")
    impossible = []
    linked = set()
    conditional_unverified = []
    for label, occurrences in labels.items():
        if not occurrences:
            continue
        linked.add(label)
        if not issues and all(all(value is False for value in item["states"].values()) for item in occurrences):
            impossible.append({"testcase": label, "occurrences": occurrences})
        elif any(None in item["states"].values() for item in occurrences):
            conditional_unverified.append(label)
    return {"descriptor_count": len(descriptors), "linked_labels": sorted(linked),
            "unresolved_descriptors": sorted(descriptors - linked),
            "conditional_unverified_labels": sorted(conditional_unverified),
            "impossible": sorted(impossible, key=lambda item: item["testcase"]), "parse_issues": issues}


def find_nm(executable: str | None) -> str | None:
    candidates = [executable] if executable else ["riscv64-unknown-elf-nm", "llvm-nm", "nm"]
    return next((path for candidate in candidates if (path := shutil.which(candidate))), None)


def inspect_elf(path: Path, labels: list[str], nm: str) -> dict[str, Any]:
    """Count actual text symbols, without interpreting them as execution hits."""
    command = [nm, "-P", "--defined-only", str(path)]
    result: dict[str, Any] = {"file": str(path), "command": command, "compiled_testcases": None}
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {**result, "limitation": str(exc)}
    result["returncode"] = proc.returncode
    if proc.returncode:
        return {**result, "limitation": (proc.stderr or proc.stdout)[:1000]}
    symbols = {}
    for line in proc.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 3 and re.fullmatch(r"[0-9a-fA-F]+", fields[2]):
            symbols[fields[0]] = fields[1]
    if not symbols:
        return {**result, "limitation": "ELF has no readable symbol table (possibly stripped)"}
    compiled = sorted(name for name in labels if symbols.get(name) in {"t", "T"})
    # A table without either known testcase labels or descriptors cannot be
    # distinguished from one whose local symbols were stripped.
    if not compiled and not any(name + "_str" in symbols for name in labels):
        return {**result, "limitation": "ELF does not retain recognizable testcase symbols"}
    return {**result, "compiled_testcases": len(compiled), "compiled_labels": compiled,
            "excluded_labels": sorted(set(labels) - set(compiled))}
