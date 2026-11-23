"""Check author SVA bodies and elaborated generated Formal sources."""

import hashlib
import json
import re
from pathlib import Path


class PreflightError(ValueError):
    """Expose bounded, source-linked diagnostics to tools and stage checkers."""

    def __init__(self, layer, diagnostics):
        self.diagnostic = {
            "status": "error",
            "error_code": "formal_sva_preflight",
            "layer": layer,
            "diagnostic_total": len(diagnostics),
            "diagnostics": diagnostics[:32],
            "error": "SVA preflight found blocking diagnostics; correct the referenced CK or source.",
            "next_action": "Correct each named CK or source. Bind internal DUT values through spec.whitebox_signals and checker ports; then regenerate and retry.",
        }
        super().__init__(self.diagnostic["error"] + " " + str(diagnostics[:8]))

    def attach_candidate_sources(self, output, checker, wrapper):
        """Return the failing fragment while unpublished generated sources still exist."""
        lines = {f"{output}/tests/{file.name}": file.read_bytes().splitlines() for file in (checker, wrapper)}
        ck_ids = []
        for item in self.diagnostic["diagnostics"]:
            source = lines.get(item.get("path"))
            line = item.get("line", 0)
            if source is None or not 1 <= line <= len(source):
                continue
            raw = source[line - 1]
            at = min(len(raw), max(0, item.get("column", 1) - 1))
            start = max(0, at - 96)
            item["candidate_source"] = {"first_column": start + 1,
                                        "text": raw[start:at + 96].decode("utf-8", errors="replace")}
            if item.get("ck_id") and item["ck_id"] not in ck_ids:
                ck_ids.append(item["ck_id"])
        if any("candidate_source" in row for row in self.diagnostic["diagnostics"]):
            self.diagnostic["next_action"] = ("Read candidate_source at the reported line and column from this rejected render. "
                                               "The tests directory holds the last published files. Correct the current records and rerun.")
        if ck_ids:
            self.diagnostic["inspect_calls"] = [
                {"request": {"action": "inspect", "section": "spec", "query": ",".join(ck_ids[i:i + 10])}}
                for i in range(0, len(ck_ids), 10)]


def combined_unbounded_assume(expr):
    """Locate a property conjunction with unbounded operators in multiple branches."""
    from pyslang.syntax import SyntaxKind as Kind

    # A shared clock or implication consequent can still contain a conjunction.
    while expr.kind in {Kind.ParenthesizedPropertyExpr, Kind.ClockingPropertyExpr, Kind.ImplicationPropertyExpr}:
        expr = expr.right if expr.kind == Kind.ImplicationPropertyExpr else expr.expr
    if expr.kind != Kind.AndPropertyExpr:
        return None

    found = False

    def find_unbounded(node):
        """Recognize temporal operators with no finite upper bound."""
        nonlocal found
        kind = node.kind
        if kind == Kind.UnaryPropertyExpr:
            found |= node.op.rawText in {"eventually", "s_eventually"}
        elif kind == Kind.SimpleRangeSelect:
            found |= node.right.kind == Kind.WildcardLiteralExpression
        elif kind in {Kind.UntilPropertyExpr, Kind.UntilWithPropertyExpr, Kind.SUntilPropertyExpr, Kind.SUntilWithPropertyExpr}:
            found = True

    unbounded = 0
    branches = [expr]
    while branches:
        branch = branches.pop()
        while branch.kind == Kind.ParenthesizedPropertyExpr:
            branch = branch.expr
        if branch.kind == Kind.AndPropertyExpr:
            branches.extend((branch.right, branch.left))
            continue
        found = False
        branch.visit(find_unbounded)
        if found:
            unbounded += 1
            if unbounded == 2:
                return expr.op.location
    return None


def required_property_branches(expr):
    """Yield branches required on every enabled sample."""
    from pyslang.syntax import SyntaxKind as Kind

    branches = [expr]
    while branches:
        branch = branches.pop()
        while branch.kind in {Kind.ParenthesizedPropertyExpr, Kind.ClockingPropertyExpr}:
            branch = branch.expr
        if branch.kind == Kind.AndPropertyExpr:
            branches.extend((branch.right, branch.left))
        else:
            yield branch


def unguarded_until_assume(expr):
    """Find a required until branch that starts on every enabled sample."""
    from pyslang.syntax import SyntaxKind as Kind

    for branch in required_property_branches(expr):
        if branch.kind in {Kind.UntilPropertyExpr, Kind.UntilWithPropertyExpr, Kind.SUntilPropertyExpr, Kind.SUntilWithPropertyExpr}:
            return branch.op.location
    return None


def direct_known_output_assumes(expr, outputs):
    """Find direct knownness assumptions on DUT outputs, including concatenations."""
    from pyslang.syntax import ExpressionSyntax, SyntaxKind as Kind

    expressions = [branch.expr.expr for branch in required_property_branches(expr)
                   if branch.kind == Kind.SimplePropertyExpr and branch.expr.kind == Kind.SimpleSequenceExpr]
    while expressions:
        item = expressions.pop()
        if item.kind == Kind.ParenthesizedExpression:
            expressions.append(item.expression)
            continue
        if item.kind == Kind.LogicalAndExpression:
            expressions.extend((item.right, item.left))
            continue
        if item.kind != Kind.UnaryLogicalNotExpression:
            continue
        call = item.operand
        while call.kind == Kind.ParenthesizedExpression:
            call = call.expression
        if call.kind != Kind.InvocationExpression or call.left.kind != Kind.SystemName or call.left.systemIdentifier.rawText != "$isunknown":
            continue
        arguments = call.arguments.parameters
        if len(arguments) != 1 or arguments[0].kind != Kind.OrderedArgument:
            continue
        arg = arguments[0].expr
        if arg.kind != Kind.SimplePropertyExpr or arg.expr.kind != Kind.SimpleSequenceExpr:
            continue
        operands = [arg.expr.expr]
        while operands:
            target = operands.pop()
            if target.kind == Kind.ConcatenationExpression:
                operands.extend(row for row in target.expressions if isinstance(row, ExpressionSyntax))
            elif target.kind == Kind.ParenthesizedExpression:
                operands.append(target.expression)
            elif target.kind in {Kind.IdentifierName, Kind.IdentifierSelectName} and target.identifier.valueText in outputs:
                yield target.identifier.valueText, target.identifier.location


def until_assume_warning(ck_id, location: dict) -> dict:
    """Explain the proof scope of a continuously armed until obligation."""
    return {**location, "ck_id": ck_id, "code": "formal_unguarded_until_assume",
            "message": "This until obligation starts again on every enabled sample. An earlier event does not satisfy later instances.",
            "next_action": "If the rule starts only at reset release or a transaction event, add its specified trigger. Verify a legal delayed case is still reachable before relying on the updated shared environment."}


def planned_initial_reset(description: str, clock_reset: dict) -> bool:
    """Recognize an explicit initial value for the resolved DUT reset pin."""
    if not clock_reset or not (clock_reset.get("has_reset") and clock_reset.get("has_clock")):
        return False
    level = {"low": ("low", "低"), "high": ("high", "高")}.get(clock_reset["reset_active_level"])
    if level is None:
        return False
    pin = re.escape(clock_reset["actual_reset"])
    en = rf"(?i:(?:assume\s+(?:that\s+)?)?(?:initially|at (?:the )?first sample)\s*,?\s*)`?{pin}`?\s+(?i:is|must be)\s+(?i:{level[0]})"
    zh = rf"(?:假设)?(?:验证)?(?:初始(?:时刻|阶段)?|首个采样点)\s*`?{pin}`?\s*(?:为|必须为)\s*{level[1]}(?:电平)?"
    statement = re.split(r"[。.]|\n", description, maxsplit=1)[0]
    if re.search(r"\b(?:if|unless|when|except)\b|如果|若|当|除非|仅在|取决于", statement, re.I):
        return False
    return bool(re.match(rf"^\s*(?:{en}|{zh})\s*(?=$|[(（，,])", statement))


def initial_reset_conflict(description, spec, clock_reset):
    """Catch an unanchored eventuality in place of a planned first-sample constraint."""
    from pyslang.syntax import SyntaxKind as Kind

    expr = spec.expr
    while expr.kind in {Kind.ParenthesizedPropertyExpr, Kind.ClockingPropertyExpr}:
        expr = expr.expr
    if (expr.kind == Kind.UnaryPropertyExpr and expr.op.rawText in {"eventually", "s_eventually"}
            and planned_initial_reset(description, clock_reset)):
        return ("The accepted plan requires reset active on the first sample. A recurring eventual reset "
                "allows a later reset and can constrain operation after release. For this initial condition "
                "submit initial_reset=true in checkpoint_metadata and the generated initial_reset body together.")


def unparen(node):
    from pyslang.syntax import SyntaxKind as Kind

    while node.kind == Kind.ParenthesizedExpression:
        node = node.expression
    return node

def constant_sample(node, pins):
    """Determine a Boolean expression only where assigned pins force its value."""
    from pyslang.syntax import SyntaxKind as Kind

    node = unparen(node)
    if node.kind == Kind.ParenthesizedPropertyExpr or node.kind == Kind.SimplePropertyExpr:
        return constant_sample(node.expr, pins)
    if node.kind == Kind.SimpleSequenceExpr and not node.repetition:
        return constant_sample(node.expr, pins)
    if node.kind == Kind.IdentifierName:
        return pins.get(node.identifier.valueText)
    if node.kind == Kind.UnaryLogicalNotExpression:
        value = constant_sample(node.operand, pins)
        return None if value is None else not value
    if node.kind == Kind.InvocationExpression and str(node.left).strip() in {"$onehot", "$onehot0"}:
        args = list(node.arguments.parameters)
        if len(args) == 1 and args[0].kind == Kind.OrderedArgument:
            arg = args[0].expr
            if arg.kind == Kind.SimplePropertyExpr and arg.expr.kind == Kind.SimpleSequenceExpr:
                value = constant_sample(arg.expr.expr, pins)
                if value is not None:
                    return bool(value) if str(node.left).strip() == "$onehot" else True
    if node.kind in {Kind.EqualityExpression, Kind.InequalityExpression}:
        left, right = constant_sample(node.left, pins), constant_sample(node.right, pins)
        if left is not None and right is not None:
            return (left == right) if node.kind == Kind.EqualityExpression else (left != right)
    if node.kind in {Kind.LogicalOrExpression, Kind.LogicalAndExpression}:
        values = (constant_sample(node.left, pins), constant_sample(node.right, pins))
        controlling = node.kind == Kind.LogicalOrExpression
        if controlling in values:
            return controlling
        if None not in values:
            return not controlling
    return None


def stability_assume_conflict(description, spec, observations, data_inputs, clock_reset):
    """Find a separate pin-level exclusion inside a planned stall/hold assumption."""
    from itertools import product
    from pyslang.syntax import SyntaxKind as Kind

    # A fixed pin assignment always satisfies a hold-only obligation, even while stalled.
    # Only inspect a standalone requirement. A separate, explicitly planned protocol
    # rule can legitimately restrict the current sample.
    intent = description.strip().rstrip(".。")
    signal = r"`?[a-zA-Z_][a-zA-Z0-9_$]*`?"
    fields = rf"{signal}(?:\s*(?:,|/|\band\b|和|及)\s*{signal})*"
    hold = rf"(?:keep {fields} stable|{fields} (?:must (?:stay|remain)|stays?|remains?) stable)"
    stall = r"while (?:backpressured|stalled)"
    english = rf"(?:{hold} {stall}|{stall},? {hold})"
    during_stall = rf"(?:{signal}\s*高且)?(?:未握手|背压|反压|阻塞)(?:期间|时)"
    hold_fields = rf"(?:下一拍)?(?:保持有效且\s*)?{fields}\s*(?:保持)?稳定"
    chinese = rf"{during_stall}[，,]\s*{hold_fields}(?:（不得(?:撤回|改变)[^（）。，；]+）)?"
    if not (re.fullmatch(english, intent, re.I) or re.fullmatch(chinese, intent)):
        return None

    if spec.disable:
        guard = spec.disable.expr
        reset_names = {(clock_reset or {}).get(key) for key in ("env_reset", "actual_reset")}
        if guard.kind == Kind.UnaryLogicalNotExpression:
            guard = guard.operand
        if not ((guard.kind == Kind.IdentifierName and guard.identifier.valueText in reset_names)
                or str(spec.disable.expr).strip().lower() == "1'b0"):
            return None

    for branch in required_property_branches(spec.expr):
        if branch.kind != Kind.SimplePropertyExpr or branch.expr.kind != Kind.SimpleSequenceExpr or branch.expr.repetition:
            continue
        parts = [branch.expr.expr]
        while parts:
            part = unparen(parts.pop())
            if part.kind == Kind.LogicalAndExpression:
                parts.extend((part.right, part.left))
                continue
            if part.kind != Kind.LogicalOrExpression:
                continue
            names = set()
            def collect(node):
                if node.kind in {Kind.IdentifierName, Kind.IdentifierSelectName}:
                    names.add(node.identifier.valueText)
            part.visit(collect)
            if (not 2 <= len(names) <= 6 or not names.intersection(observations) or not names.intersection(data_inputs)
                    or not names.issubset(set(observations) | set(data_inputs))):
                continue
            for values in product((False, True), repeat=len(names)):
                pins = dict(zip(sorted(names), values))
                if constant_sample(part, pins) is False:
                    sample = ", ".join(f"{key}={int(value)}" for key, value in pins.items())
                    return (f"The planned stall stability rule admits constant signals ({sample}). "
                            "An independent combinational clause here rejects those constant values. "
                            "Keep the original hold obligation. Put any independent protocol restriction "
                            "in its own CK with its specification source and verify that legal transactions remain possible.")
    return None


def planned_assume_conflicts(description, spec, clock_reset, observations, data_inputs):
    for code, message in (
        ("formal_initial_reset_scope", initial_reset_conflict(description, spec, clock_reset)),
        ("formal_stability_assume_scope", stability_assume_conflict(description, spec, observations, data_inputs, clock_reset)),
    ):
        if message:
            yield {"code": code, "message": message, "requirement": description}


def post_plan_response_conflict(description, expr, data_inputs, design_observations):
    """Check a new history-based input contract constraining responses by present DUT pins."""
    from pyslang.syntax import SyntaxKind as Kind

    if not re.search(r"响应必须对应已接受的命令|不得自发响应|no unsolicited responses?|"
                     r"each response must correspond to (?:an|a previously) accepted (?:command|request)", description, re.I):
        return None
    if expr.kind != Kind.SimplePropertyExpr or expr.expr.kind != Kind.SimpleSequenceExpr or expr.expr.repetition:
        return None
    names = set()
    temporal = False
    def observe(node):
        nonlocal temporal
        if node.kind in {Kind.IdentifierName, Kind.IdentifierSelectName}:
            names.add(node.identifier.valueText)
        elif node.kind == Kind.InvocationExpression:
            temporal = True
    expr.expr.expr.visit(observe)
    if (not temporal and names & set(data_inputs) and names & set(design_observations)
            and names <= (set(data_inputs) | set(design_observations))):
        return ("This new Assume describes responses to accepted requests, but its Boolean expression uses only "
                "present DUT or interface signals. A current command or decode is not an independent record of "
                "earlier handshakes. Use a specification-backed egress transaction_balance Assume for the "
                "external channel. Check a delayed response and an unsolicited response. If the protocol is "
                "undecided, retain the original failure with a SPEC_GAP and continue.")
    return None


def check_bodies(bodies: dict, source: str, *, assume_ids=(), plan=None, outputs=(), data_inputs=(),
                 clock_reset=None, internal_signals=(), captured_signals=None, new_assume_descriptions=None) -> list[dict]:
    """Validate one property fragment without requiring its declarations or macros."""
    import pyslang as slang

    diagnostics, warnings = [], []
    for ck, body in bodies.items():
        if not isinstance(body, str) or not body.strip() or "[LLM-TODO]" in body:
            continue
        # Active preprocessing and macro expansion require the ordered source unit.
        if "`" in re.sub(r"/\*.*?\*/|//[^\n]*", "", body, flags=re.DOTALL):
            continue
        manager = slang.SourceManager()
        engine = slang.DiagnosticEngine(manager)
        text = f"module __formal_probe;\nproperty p;\n{body}\nendproperty\nA: assert property(p);\nendmodule\n"
        tree = slang.syntax.SyntaxTree.fromText(text, manager)
        errors = [diag for diag in tree.diagnostics if diag.isError()]
        body_end_line = 3 + body.count("\n")
        for diag in errors:
            line = manager.getLineNumber(diag.location)
            column = manager.getColumnNumber(diag.location)
            item = {"ck_id": ck, "path": source, "body_line": max(1, line - 2), "column": column,
                    "message": engine.formatMessage(diag)}
            if diag.code == slang.Diags.ExpectedToken and diag.args in (["endproperty"], [")"]) and 3 <= line <= body_end_line:
                remaining = manager.getSourceText(diag.location.buffer).encode()[diag.location.offset:]
                token = remaining.lstrip()[:2]
                operator = {b"&&": "and", b"||": "or"}.get(token)
                if operator:
                    item["hint"] = f"Use the SVA property operator '{operator}' if combining temporal properties here. Keep '{token.decode()}' inside Boolean expressions."
            diagnostics.append(item)
        if errors:
            continue
        if (
            tree.root.kind != slang.syntax.SyntaxKind.ModuleDeclaration
            or [item.kind for item in tree.root.members] != [
                slang.syntax.SyntaxKind.PropertyDeclaration, slang.syntax.SyntaxKind.ConcurrentAssertionMember
            ]
        ):
            diagnostics.append({"ck_id": ck, "path": source, "body_line": 1,
                                "message": "Expected a single property body."})
        elif ck in assume_ids:
            spec = tree.root.members[0].propertySpec
            description = ((plan or {}).get(ck) or {}).get("description") or ""
            note = post_plan_response_conflict((new_assume_descriptions or {}).get(ck, ""), spec.expr,
                                               data_inputs, set(outputs) | set(internal_signals))
            if note:
                diagnostics.append({"path": source, "ck_id": ck, "body_line": 1, "code": "formal_environment_response_history", "message": note})
            for conflict in planned_assume_conflicts(description, spec, clock_reset, set(outputs) | set(internal_signals), data_inputs):
                diagnostics.append({"path": source, "ck_id": ck, "body_line": 1, **conflict})
            loc = unguarded_until_assume(spec.expr)
            if loc is not None:
                warnings.append(until_assume_warning(ck, {"path": source, "body_line": manager.getLineNumber(loc) - 2,
                                                          "column": manager.getColumnNumber(loc)}))
        elif plan and ck in plan:
            description = plan[ck].get("description") or ""
            spec = tree.root.members[0].propertySpec
            if hint := eventual_response_warning(description, spec):
                warnings.append({"path": source, "ck_id": ck, "body_line": 1, "code": "formal_response_matching",
                                 "message": hint, "requirement": description})
            for message in direct_plan_conflicts(description, spec, outputs, data_inputs, (captured_signals or {}).get(ck),
                                                 internal_signals):
                diagnostics.append({"path": source, "ck_id": ck, "body_line": 1,
                                    "code": "formal_planned_observation", "message": message,
                                    "requirement": description})
    if diagnostics:
        raise PreflightError("property_body", diagnostics)
    return warnings[:32]


def eventual_response_warning(description, spec):
    """Flag an eventual match when the plan calls for a particular request's response."""
    from pyslang.syntax import SyntaxKind as Kind

    if not re.search(r"其(?:最终|首个|对应)?响应|首笔.{0,8}响应|(?:its|first|corresponding) response", description, re.I):
        return None
    expr = spec.expr
    while expr.kind == Kind.ParenthesizedPropertyExpr:
        expr = expr.expr
    if expr.kind != Kind.ImplicationPropertyExpr:
        return None
    consequence = expr.right
    while consequence.kind == Kind.ParenthesizedPropertyExpr:
        consequence = consequence.expr
    if consequence.kind == Kind.UnaryPropertyExpr and consequence.op.rawText in {"s_eventually", "eventually"}:
        return ("An eventual match can select a later delivery. Check the original request boundary, the first corresponding "
                "response and the fields on that delivery. For tagged or multi-beat traffic, verify the association or "
                "terminal-beat condition against the interface contract before accepting this implementation.")
    return None


def necessary_input_literals(expr, data_inputs):
    """Return primary data input literals required by a conjunction-only trigger."""
    from pyslang.syntax import SyntaxKind as Kind

    if expr.kind != Kind.SimplePropertyExpr or expr.expr.kind != Kind.SimpleSequenceExpr:
        return []
    literals = []
    todo = [expr.expr.expr]
    while todo:
        part = todo.pop()
        while part.kind == Kind.ParenthesizedExpression:
            part = part.expression
        if part.kind == Kind.LogicalAndExpression:
            todo.extend((part.right, part.left))
        else:
            if part.kind == Kind.UnaryLogicalNotExpression:
                part = part.operand
            if part.kind == Kind.IdentifierName and part.identifier.valueText in data_inputs:
                literals.append(part.identifier.valueText)
    return sorted(set(literals))


def direct_plan_conflicts(description, spec, outputs, data_inputs=(), captured_signal=None, internal_signals=()):
    """Identify explicit planned observations missing from direct signal expressions."""
    from pyslang import parsing
    from pyslang.syntax import SyntaxKind as Kind

    # A helper, hierarchical lookup or local sequence may observe the named port or
    # keep history indirectly. Its semantics require a separate review.
    identifiers = set()
    indirect = False

    def collect(node):
        nonlocal indirect
        if node.kind == parsing.TokenKind.Identifier:
            identifiers.add(node.valueText)
        elif node.kind == Kind.InvocationExpression:
            # These built-ins depend only on their operands at the current sample.
            if node.left.kind != Kind.SystemName or node.left.systemIdentifier.rawText not in {
                    "$onehot", "$onehot0", "$countones", "$isunknown"}:
                indirect = True
        elif node.kind in {Kind.ScopedName, Kind.MemberAccessExpression}:
            indirect = True

    if not re.search(r"复位释放后|after reset release|后下一拍|on the next|检查器跟踪|checker.track", description, re.I):
        return []
    spec.expr.visit(collect)
    messages = []
    expr = spec.expr
    while expr.kind == Kind.ParenthesizedPropertyExpr:
        expr = expr.expr
    for match in re.finditer(
            r"(?:^|[。；;])\s*(?:复位释放后\s*|after reset release\s*,?\s*)"
            r"([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:为[高低]|must be (?:high|low)\b)"
            r"(?=\s*(?:$|[。.;；]|[,，]\s*(?:且|and\b)))", description, re.I):
        signal = match[1]
        if signal in outputs and signal not in identifiers and not indirect:
            messages.append(f"The planned reset-release goal observes DUT output {signal}, which this property never references. "
                            f"Check {signal} at release and retain any separately planned idle behavior.")
        elif signal in outputs and expr.kind == Kind.SimplePropertyExpr:
            # An input that makes the entire Boolean encoding true also masks
            # the named output at release, even if other branches call $rose.
            wrong_level = bool(re.search(r"为低|\blow\b", match[0], re.I))
            for pin in sorted(set(data_inputs) & identifiers):
                hidden_by = next((v for v in (False, True) if constant_sample(expr, {signal: wrong_level, pin: v}) is True), None)
                if hidden_by is not None:
                    messages.append(f"The unconditional release requirement for {signal} is masked: {pin}={int(hidden_by)} "
                                    f"makes this expression true even with {signal}={int(wrong_level)} on the release sample.")
                    break
        elif signal in outputs and expr.kind == Kind.ImplicationPropertyExpr and not indirect:
            guards = necessary_input_literals(expr.left, data_inputs)
            if guards:
                messages.append(f"The release obligation for {signal} is unconditional. This implication can pass vacuously "
                                f"when the data-input guard on {', '.join(guards)} is false. Express release and idle as "
                                "independent obligations within the original CK; keep a legal coincident transaction.")
    if indirect:
        return messages
    # Match a concrete accepted two-signal handshake followed by a mandatory
    # next-sample observation. A general reference to timing in prose is insufficient.
    handshake = re.search(
        r"[（(]\s*([a-zA-Z_]\w*)\s*&&?\s*([a-zA-Z_]\w*)\s*(?:[,，][^()（）]*)?[）)]"
        r"\s*(?:后下一拍\s*[,，]|[, ]+on the next (?:clock )?(?:edge|cycle)\s*[,，])",
        description, re.ASCII | re.I)
    if handshake and expr.kind == Kind.SimplePropertyExpr and set(handshake.groups()) <= identifiers:
        for pin in handshake.groups():
            if constant_sample(expr, {pin: False}) is True:
                messages.append(f"The plan requires the next sample after an accepted handshake. With {pin}=0 on that "
                                "sample, this current-cycle expression accepts every output. Check the required transfer "
                                "on the following clock, including when a new request is absent.")
                break
    # A second conjunct may implement the missing temporal obligation. Only
    # diagnose same-sample drift if every required branch has that same timing.
    branches = list(required_property_branches(expr))
    for branch in branches:
        if (branch.kind != Kind.ImplicationPropertyExpr or branch.op.rawText != "|->"
                or any(side.kind != Kind.SimplePropertyExpr or side.expr.kind != Kind.SimpleSequenceExpr
                       or side.expr.repetition is not None for side in (branch.left, branch.right))):
            return messages
    if re.search(r"检查器跟踪|checker.tracks?", description, re.I):
        captured = re.search(r"(?:[（(]\s*([a-zA-Z_]\w*)\s*记录值|captured value of\s+`?([a-zA-Z_]\w*))",
                             description, re.ASCII | re.I)
        signal = next((name for name in captured.groups() if name), None) if captured else None
        # A conclusion consisting only of the delivery-valid pin checks that
        # a response exists; it cannot compare the identity of that response.
        delivery = re.search(r"[（(]\s*([A-Za-z_]\w*)\s*&&?\s*([A-Za-z_]\w*)\s*[）)]\s*(?:当拍|at delivery)", description, re.ASCII | re.I)
        handshake_only = delivery and all(
            unparen(branch.right.expr.expr).kind == Kind.IdentifierName
            and unparen(branch.right.expr.expr).identifier.valueText in delivery.groups()
            for branch in branches)
        observed = {captured_signal} if captured_signal else identifiers
        # Every identifier in a one-sample expression is a DUT pin here. No
        # independent capture state can distinguish different request histories.
        pins_only = not captured_signal and identifiers <= (set(outputs) | set(data_inputs) | set(internal_signals))
        if signal and (signal not in observed or handshake_only or pins_only):
            messages.append(f"The planned checker tracks the captured value of {signal}. Its implemented branches "
                            "compare only current samples and do not verify the captured identity at delivery. Compare the delivered "
                            "source to independent request history. If the plan specifies the most recent accepted value, use "
                            "FormalData draft_latest_transfer with the specified bindings and simultaneous-transfer priority.")
    if handshake:
        trigger = set()

        def trigger_signal(node):
            if node.kind == parsing.TokenKind.Identifier:
                trigger.add(node.valueText)

        for branch in branches:
            trigger.clear()
            branch.left.visit(trigger_signal)
            if set(handshake.groups()) <= trigger:
                messages.append("The Stage 4 plan checks the sample following the accepted handshake, but the implemented "
                                "branches compare only the handshake sample. Check the next sample against the accepted values.")
                break
    return messages


def check_generated(root: Path, output: str, dut: str, staged: Path, interface: dict, records) -> dict:
    """Elaborate the same ordered RTL, checker and wrapper used by FormalMC."""
    import pyslang as slang
    from .skills.lib.formal_tools import _ck_to_sv_names

    manager = slang.SourceManager()
    engine = slang.DiagnosticEngine(manager)
    for directory in interface["include_dirs"]:
        manager.addUserDirectories(str(root / directory))
    checker = staged / f"{dut}_checker.sv"
    wrapper = staged / f"{dut}_wrapper.sv"
    tree = slang.syntax.SyntaxTree.fromFiles(
        [str(root / relative) for relative in interface["source_files"]] + [str(checker), str(wrapper)], manager
    )
    options = slang.ast.CompilationOptions()
    top = f"{dut}_wrapper"
    options.topModules = {top}
    bag = slang.Bag()
    bag.compilationOptions = options
    compilation = slang.ast.Compilation(bag)
    compilation.addSyntaxTree(tree)

    checkpoints = {_ck_to_sv_names(ck.id, ck.style)[0]: ck for fg in records.spec.function_groups
                   for fc in fg.functions for ck in fc.check_points}
    ranges = []
    for match in re.finditer(r"^\s*property ([\w]+);.*?\bendproperty\b", checker.read_text(), re.M | re.S):
        text = match.string
        ck = checkpoints.get(match[1])
        ranges.append((text.count("\n", 0, match.start()) + 1, text.count("\n", 0, match.end()) + 1,
                       ck.id if ck else None))

    def location(loc):
        """Map generated positions back to stable output paths and CK identities."""
        loc = manager.getFullyOriginalLoc(loc)
        path = Path(manager.getFullPath(loc.buffer))
        line = manager.getLineNumber(loc)
        result = {"path": f"{output}/tests/{path.name}" if path in {checker, wrapper}
                  else str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
                  "line": line, "column": manager.getColumnNumber(loc)}
        if path == checker:
            result["ck_id"] = next((key for start, end, key in ranges if start <= line <= end), None)
        return result

    errors = []
    warnings = []
    for diag in compilation.getAllDiagnostics():
        row = {**location(diag.location), "code": str(diag.code), "message": engine.formatMessage(diag)}
        # A default timing directive in an RTL module need not be copied to
        # generated, delay-free checker and wrapper modules.
        if diag.isError() and str(diag.code) != "DiagCode(MissingTimeScale)":
            errors.append(row)
    if errors:
        raise PreflightError("generated_design", errors)

    outputs = {port["name"] for port in interface["ports"] if port["direction"] == "output"}

    from .baseline import require_planned_scope
    from .skills.lib.formal_tools import build_clock_reset_alias_context, build_whitebox_signal_context

    observations = outputs | {binding["name"] for binding in build_whitebox_signal_context(records.spec.whitebox_signals)}
    clock_reset = build_clock_reset_alias_context(records)
    clock_ports = {clock_reset[key] for key in ("actual_clock", "actual_reset", "env_clock", "env_reset")}
    data_inputs = {port["name"] for port in interface["ports"] if port["direction"] == "input"} - clock_ports
    plan = require_planned_scope(root / output / "formal_runs", records)

    def check_checker_property(node):
        """Validate compiled goals against the original plan and inspect Assume expressions."""
        if not isinstance(node, slang.syntax.PropertyDeclarationSyntax):
            return
        ck = checkpoints.get(node.name.rawText)
        if ck is None or manager.getFullPath(node.name.location.buffer) != checker:
            return
        if ck.style.lower() != "assume":
            if ck.id in plan and not ck.transaction_balance:
                description = plan[ck.id].get("description") or ""
                if hint := eventual_response_warning(description, node.propertySpec):
                    warnings.append({**location(node.name.location), "ck_id": ck.id,
                                     "code": "formal_response_matching", "message": hint})
                for message in direct_plan_conflicts(description, node.propertySpec, outputs, data_inputs,
                                                     ck.latest_transfer.captured if ck.latest_transfer else None, observations):
                    errors.append({**location(node.name.location), "ck_id": ck.id,
                                   "code": "formal_planned_observation", "requirement": description,
                                   "message": message, "next_action": "Repair this CK against the accepted plan and rerun it."})
            return
        description = (plan.get(ck.id) or {}).get("description") or ""
        if plan and ck.id not in plan and not ck.transaction_balance:
            note = post_plan_response_conflict(ck.description, node.propertySpec.expr, data_inputs, observations)
            if note:
                errors.append({**location(node.name.location), "ck_id": ck.id, "code": "formal_environment_response_history",
                               "message": note})
        for conflict in planned_assume_conflicts(description, node.propertySpec, clock_reset, observations, data_inputs):
            errors.append({**location(node.name.location), "ck_id": ck.id, **conflict})
        loc = combined_unbounded_assume(node.propertySpec.expr)
        if loc is not None:
            row = location(manager.getFullyExpandedLoc(loc))
            warnings.append({
                **row, "ck_id": ck.id, "code": "formal_combined_unbounded_assume",
                "message": "This Assume joins multiple unbounded branches with property-level 'and', which may increase solver cost.",
                "next_action": "Check the protocol. Use separate CKs for independent obligations and preserve any required joint behavior. See Guide_Doc/sva_property.md section 3.6.",
            })
        loc = unguarded_until_assume(node.propertySpec.expr)
        if loc is not None:
            warnings.append(until_assume_warning(ck.id, location(manager.getFullyExpandedLoc(loc))))
        for signal, loc in direct_known_output_assumes(node.propertySpec.expr, outputs):
            errors.append({**location(manager.getFullyExpandedLoc(loc)), "ck_id": ck.id, "signal": signal,
                           "code": "formal_assume_output_known",
                           "message": f"This Assume requires DUT output {signal} to be known.",
                           "next_action": "Bind environmental knownness to DUT inputs. If the specification requires an output to be known, verify it with an Assert."})

    tree.root.visit(check_checker_property)
    if errors:
        raise PreflightError("generated_design", errors)

    # Hierarchical lookups can resolve upward through the wrapper in the standard
    # elaborator while the proof engine rejects the same checker reference. Keep
    # checker inputs explicit; RTL and wrapper binding hierarchies remain valid.
    hierarchical = set()

    def check_checker_hierarchy(node):
        """Reject only elaborated external value references originating in the checker."""
        if not isinstance(node, slang.ast.HierarchicalValueExpression):
            return
        row = location(node.sourceRange.start)
        if row["path"] != f"{output}/tests/{checker.name}":
            return
        key = (row["line"], row["column"])
        if key in hierarchical:
            return
        hierarchical.add(key)
        errors.append({**row, "code": "formal_checker_hierarchy_unsupported",
                       "reference": str(node.syntax).strip() if node.syntax is not None else node.symbol.name,
                       "message": "Checker properties must use declared inputs instead of external hierarchical values.",
                       "next_action": "Expose the required value through a supported spec.whitebox_signals declaration and wrapper binding, then reference the checker input. Do not remove the verification goal or modify DUT RTL to bypass this error."})

    compilation.getRoot().visit(check_checker_hierarchy)
    if errors:
        raise PreflightError("generated_design", errors)

    operators = {"Equality", "Inequality", "CaseEquality", "CaseInequality", "WildcardEquality",
                 "WildcardInequality", "GreaterThan", "GreaterThanEqual", "LessThan", "LessThanEqual"}
    visited = set()

    def check_widths(node):
        """Report original operand widths for comparisons in generated properties."""
        if not isinstance(node, slang.ast.BinaryExpression) or node.op.name not in operators:
            return
        row = location(node.sourceRange.start)
        if not row.get("ck_id"):
            return
        operands = []
        for value in (node.left, node.right):
            while isinstance(value, slang.ast.ConversionExpression) and value.isImplicit:
                value = value.operand
            kind = value.type
            operands.append({"type": str(kind), "width": kind.bitWidth, "signed": kind.isSigned})
        key = (row["line"], row["column"])
        if key not in visited and all(item["width"] for item in operands) and operands[0]["width"] != operands[1]["width"]:
            visited.add(key)
            warnings.append({**row, "code": "formal_comparison_width", "operands": operands,
                             "message": "Comparison uses different original widths; confirm the intended extension or conversion."})

    compilation.getRoot().visit(check_widths)
    from .skills.lib.models import semantic_inputs
    digest = hashlib.sha256(json.dumps(semantic_inputs(records), sort_keys=True).encode()).hexdigest()
    return {"status": "passed", "warning_total": len(warnings), "warnings": warnings[:32],
            "semantic_sha256": digest,
            "generated": {item.name: hashlib.sha256(item.read_bytes()).hexdigest() for item in staged.iterdir()}}
