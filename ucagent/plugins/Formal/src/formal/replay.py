"""Replay a bounded subset of clocked safety SVA against sealed FormalMC traces."""

from bisect import bisect_right
from hashlib import file_digest, sha256
import re

from .baseline import shared_contract
from .execution import property_evidence
from .skills.lib.formal_tools import _ck_to_sv_names
from .skills.lib.models import FormalRecords
from .trace import _waveform_module


class ReplayUnavailable(ValueError):
    """Explain why a trace cannot establish an offline replay observation."""


def parse_safety(body: str):
    """Parse the finite expression subset used for offline single-edge replay."""
    from pyslang.syntax import SyntaxKind as Kind, SyntaxTree

    if len(body) > 8192:
        raise ReplayUnavailable("The property exceeds the offline replay size limit.")
    tree = SyntaxTree.fromText("module replay; property p; " + body.strip().removesuffix(";") + "; endproperty endmodule")
    if list(tree.diagnostics) or tree.root.kind != Kind.ModuleDeclaration or len(tree.root.members) != 1:
        raise ReplayUnavailable("The SVA could not be parsed as a single property.")
    prop = tree.root.members[0].propertySpec
    if not prop.clocking or prop.clocking.kind != Kind.EventControlWithExpression:
        raise ReplayUnavailable("Replay requires one explicit posedge or negedge.")
    event = prop.clocking.expr
    if event.kind == Kind.ParenthesizedEventExpression:
        event = event.expr
    if (event.kind != Kind.SignalEventExpression or event.iffClause or event.expr.kind != Kind.IdentifierName
            or event.edge.rawText not in ("posedge", "negedge")):
        raise ReplayUnavailable("Replay requires one unqualified clock signal and one edge.")

    signals = set()
    binary = {Kind.LogicalAndExpression: "and", Kind.LogicalOrExpression: "or",
              Kind.EqualityExpression: "eq", Kind.InequalityExpression: "ne"}

    def compile_expr(node):
        """Translate expressions with defined finite replay semantics."""
        kind = node.kind
        if kind in (Kind.SimplePropertyExpr, Kind.ParenthesizedPropertyExpr):
            return compile_expr(node.expr)
        if kind == Kind.SimpleSequenceExpr and not node.repetition:
            return compile_expr(node.expr)
        if kind == Kind.ParenthesizedExpression:
            return compile_expr(node.expression)
        if kind == Kind.IdentifierName:
            name = node.identifier.rawText
            if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9$]*", name):
                signals.add(name)
                return ("signal", name)
        if kind == Kind.IntegerVectorExpression and re.fullmatch(r"1'[bB][01]", str(node).strip()):
            return ("bit", str(node).strip()[-1] == "1")
        if kind == Kind.UnaryLogicalNotExpression:
            return ("not", compile_expr(node.operand))
        if kind in binary:
            return (binary[kind], compile_expr(node.left), compile_expr(node.right))
        if kind == Kind.InvocationExpression and str(node.left).strip() == "$past":
            args = node.arguments.parameters
            if len(args) == 1 and args[0].kind == Kind.OrderedArgument:
                return ("past", compile_expr(args[0].expr))
        raise ReplayUnavailable(f"SVA syntax outside the finite replay subset: {kind.name}.")

    expr = prop.expr
    while expr.kind == Kind.ParenthesizedPropertyExpr:
        expr = expr.expr
    if expr.kind == Kind.ImplicationPropertyExpr and expr.op.rawText in ("|->", "|=>"):
        condition = compile_expr(expr.left)
        consequent = compile_expr(expr.right)
        delay = int(expr.op.rawText == "|=>")
    else:
        condition, consequent, delay = ("bit", True), compile_expr(expr), 0
    guard = compile_expr(prop.disable.expr) if prop.disable else None
    if guard and not (guard[0] == "signal" or guard[0] == "not" and guard[1][0] == "signal"):
        raise ReplayUnavailable("Replay supports disable iff on a single reset signal or its negation.")
    return event.expr.identifier.rawText, event.edge.rawText, signals, condition, consequent, delay, guard


def evaluate_replay(parsed, traces: dict, first_tick: int, last_tick: int) -> dict:
    """Sample before clock transitions and respect asynchronous disable intervals."""
    from unit_test.waveform_formats.sampling import is_clock_edge

    clock, edge, _, condition, consequent, delay, guard = parsed

    def width(node):
        """Accept vectors only in equal-width comparisons, independent of signedness."""
        operation, *operands = node
        if operation == "bit":
            return 1
        if operation == "signal":
            return traces[operands[0]].width
        widths = [width(operand) for operand in operands]
        if operation == "past":
            return widths[0]
        if operation in {"eq", "ne"}:
            if widths[0] != widths[1]:
                raise ReplayUnavailable("Replay requires equal-width operands for equality comparisons.")
        elif any(bits != 1 for bits in widths):
            raise ReplayUnavailable("Replay requires one-bit operands for Boolean expressions.")
        return 1

    if traces[clock].width != 1 or any(width(node) != 1 for node in (condition, consequent, guard) if node):
        raise ReplayUnavailable("Replay requires a one-bit clock, reset, trigger, and outcome.")
    waveform = traces[clock]
    if any(value.x_mask or value.z_mask for value in waveform.states):
        raise ReplayUnavailable("The recorded clock contains an unknown interval.")
    ticks = [value.wave_step for old, value in zip(waveform.states, waveform.states[1:])
             if is_clock_edge(old, value, "rising" if edge == "posedge" else "falling", 1)]
    if not ticks or len(ticks) > 2000:
        raise ReplayUnavailable("Replay requires 1 to 2000 recorded clock edges.")

    def known(sample):
        """Keep missing or unknown four-state values distinct from zero."""
        return None if sample is None or sample.x_mask or sample.z_mask else sample.value

    def value(node, cycle):
        """Evaluate one restricted expression using pre-edge samples."""
        operation, *operands = node
        if operation == "bit":
            return operands[0]
        if operation == "signal":
            trace = traces[operands[0]]
            sample = known(trace.value_at(ticks[cycle] - 1))
            return bool(sample) if sample is not None and trace.width == 1 else sample
        if operation == "past":
            return value(operands[0], cycle - 1) if cycle > 0 else None
        left = value(operands[0], cycle)
        if operation == "not":
            return None if left is None else not left
        right = value(operands[1], cycle)
        if left is None or right is None:
            return None
        return {"and": left and right, "or": left or right, "eq": left == right, "ne": left != right}[operation]

    reset = traces[guard[1][1] if guard[0] == "not" else guard[1]] if guard else None
    unknown = False
    triggered = 0
    checked = 0
    for cycle, tick in enumerate(ticks):
        check = ticks[cycle + delay] if cycle + delay < len(ticks) else None
        if reset:
            through = check if check is not None else last_tick
            first = bisect_right(reset.wave_steps, tick)
            end = bisect_right(reset.wave_steps, through)
            states = [reset.value_at(tick), *reset.states[first:end]]
            guard_bits = [known(state) for state in states]
            disabled = False if guard[0] == "not" else True
            if disabled in guard_bits:
                continue
            if None in guard_bits:
                unknown = True
                continue
        fires = value(condition, cycle)
        if not fires:
            unknown |= fires is None
            continue
        triggered += 1
        outcome = value(consequent, cycle + delay) if check is not None else None
        if outcome is False:
            return {"status": "still_fails", "trigger_tick": str(tick), "check_tick": str(check),
                    "triggered": triggered, "checked": checked + 1}
        if outcome is True:
            checked += 1
        unknown |= outcome is None
    status = "insufficient_evidence" if unknown or first_tick > 0 else "triggered_no_failure_in_trace" if checked else "not_triggered"
    return {"status": status, "triggered": triggered, "checked": checked}


def replay_counterexample(execution, run_dir, state: dict, name: str) -> dict:
    """Reproduce the sealed safety counterexample before evaluating the current CK."""
    import yaml

    result = {"mode": "replay", "run_id": state["run_id"], "scope": state.get("scope", "full"),
              "property_name": name, "input_fingerprint": state["fingerprint"]}
    try:
        item = state["properties"].get(name)
        if not item or item["kind"] != "assert" or item["result"] != "FALSIFIED":
            raise ReplayUnavailable("Select a failed assertion with a recorded counterexample.")
        evidence = property_evidence(run_dir, {**state, "workspace": str(execution.workspace)}, name, item, observations=False)
        if not evidence["trace_artifact"]:
            raise ReplayUnavailable("The failed attempt has no recorded waveform.")
        result["trace_artifact"] = evidence["trace_artifact"]
        old = FormalRecords.model_validate(state.get("semantic_inputs"))
        target, source, _ = execution._paths(create=False)
        current_file = target / ".formal_records.yaml"
        current_bytes = current_file.read_bytes()
        current = FormalRecords.model_validate(yaml.safe_load(current_bytes))
        if not old.spec or not current.spec or shared_contract(old) != shared_contract(current):
            raise ReplayUnavailable("The shared clock, reset, bindings, parameters or assumptions changed.")
        if ((old.extra_config or {}).get("tcl") or {}).get("extra_commands"):
            raise ReplayUnavailable("Replay cannot validate the environment effects of custom Tcl commands.")
        tests = f"{state['output_dir']}/tests/{state['dut']}"
        manifest = {relative: digest for relative, digest in state["files"].items() if relative != tests + "_checker.sv"}
        if {str(path.relative_to(execution.workspace)) for path in source.rglob("*") if path.is_file()} != {
                path for path in manifest if path.startswith(state["dut"] + "/")}:
            raise ReplayUnavailable("The recorded RTL source set changed.")
        for relative, expected in manifest.items():
            path = execution.workspace / relative
            if not path.resolve().is_relative_to(execution.workspace) or sha256(path.read_bytes()).hexdigest() != expected:
                raise ReplayUnavailable("The recorded RTL or generated environment changed.")

        original = [ck for fg in old.spec.function_groups for fc in fg.functions for ck in fc.check_points
                    if _ck_to_sv_names(ck.id, ck.style)[1] == name.rsplit(".", 1)[-1]]
        if len(original) != 1 or not original[0].sva_body:
            raise ReplayUnavailable("The original assertion does not resolve to one implemented CK.")
        ck_id = original[0].id
        target_ck = [ck for fg in current.spec.function_groups for fc in fg.functions for ck in fc.check_points
                     if ck.id == ck_id and ck.style == original[0].style]
        if len(target_ck) != 1 or not target_ck[0].sva_body:
            raise ReplayUnavailable("The current CK is missing or has a different assertion kind.")
        result.update(ck_id=ck_id, current_sva_sha256=sha256(target_ck[0].sva_body.encode()).hexdigest())
        before = parse_safety(original[0].sva_body)
        after = parse_safety(target_ck[0].sva_body)
        if before[:2] != after[:2]:
            raise ReplayUnavailable("The assertion clock or edge changed.")
        signals = before[2] | after[2] | {before[0]}
        if len(signals) > 32:
            raise ReplayUnavailable("The assertion requires more than 32 signals for replay.")
        path = execution.workspace / evidence["trace_artifact"]
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ReplayUnavailable("The original waveform exceeds the offline analysis limit.")

        waveform = _waveform_module()
        from unit_test.waveform_formats.sampling import load_signal_trace

        wrapper = (execution.workspace / (tests + "_wrapper.sv")).read_text()
        instance = name.rpartition(".")[0]
        checker_ports = re.search(r"\bu_checker\s*\((.*?)\);", wrapper, re.S)
        wrapper_scope = f"{state['dut']}_wrapper"
        if instance not in ("u_checker", f"{wrapper_scope}.u_checker") or not checker_ports:
            raise ReplayUnavailable("The assertion does not belong to the generated checker instance.")
        bindings = dict(re.findall(r"\.([A-Za-z_0-9$]+)\s*\(\s*([A-Za-z_0-9$]+)\s*\)", checker_ports[1]))
        paths = {}
        traces = {}
        with waveform.open_waveform_reader(path, backend_priority={"vcd": ["wavekit"]}) as reader:
            for signal in sorted(signals):
                candidates = [f"{wrapper_scope}.u_checker.{signal}"]
                if binding := bindings.get(signal):
                    candidates.append(f"{wrapper_scope}.{binding}")
                for full_name in candidates:
                    candidates_page = reader.get_matched_signals(full_name, limit=2)
                    declaration = re.compile(re.escape(full_name) + r"(?:\[-?\d+:-?\d+\])?")
                    matches = [row for row in candidates_page["signals"].values() if declaration.fullmatch(row.full_name)]
                    if len(matches) == 1 and candidates_page["total"] == 1 and 1 <= matches[0].width <= 4096:
                        match = matches[0]
                        traces[signal] = load_signal_trace(reader, match)
                        paths[signal] = match.full_name
                        break
                if signal not in traces:
                    raise ReplayUnavailable(f"Missing unique, supported checker signal: {signal}.")
            observed = evaluate_replay(before, traces, reader.begin_time, reader.end_time)
            if observed["status"] != "still_fails":
                raise ReplayUnavailable("Offline sampling did not reproduce the original failure.")
            outcome = evaluate_replay(after, traces, reader.begin_time, reader.end_time)
        with path.open("rb") as stream:
            if file_digest(stream, "sha256").hexdigest() != evidence["trace_sha256"]:
                raise ReplayUnavailable("The original trace changed during replay.")
        if current_file.read_bytes() != current_bytes:
            raise ReplayUnavailable("The current specification changed during replay.")
        return {**result, **outcome, "original_failure": observed, "signals": paths,
                "trace_sha256": evidence["trace_sha256"],
                "next_action": "Review the observed trace, then use RunFormal for current proof evidence."}
    except ImportError:
        return {**result, "status": "insufficient_evidence", "reason": "Offline waveform analysis is unavailable.",
                "next_action": "Use a selected RunFormal batch for the current CK."}
    except (OSError, ValueError, RecursionError) as exc:
        return {**result, "status": "insufficient_evidence", "reason": str(exc),
                "next_action": "Use a selected RunFormal batch for the current CK."}
