"""Generate passive, independent transaction observers for planned safety checks."""

import re


def transaction_body(ck, clock_edge: str) -> str:
    """Render the planned capacity or response-matching obligation."""
    if clock_edge not in {"posedge", "negedge"}:
        raise ValueError(f"{ck.id}: transaction_balance requires a configured clock edge")
    checks = []
    for index, rule in enumerate(ck.transaction_balance):
        name = f"uca_balance_{ck.id.replace('-', '_')}_{index}"
        if ck.style.lower() == "assume":
            bypass = f" || {name}_command" if rule.zero_cycle_when else ""
            checks.append(f"(!{rule.response_valid} || {name}_overflow || (|{name}_pending){bypass})")
            continue
        if rule.max_pending is not None:
            reuse = f" || {name}_retire" if rule.reuse_on_response else ""
            condition = f"!{name}_command || ({name}_pending < {rule.counter_bits}'d{rule.max_pending}){reuse}"
        else:
            exception = f" || ({name}_command && ({rule.zero_cycle_when}))" if rule.zero_cycle_when else ""
            condition = f"!{name}_response || (|{name}_pending){exception}"
        checks.append(f"(!{name}_overflow && ({condition}))")
    return f"@({clock_edge} clk) disable iff (!rst_n) " + " && ".join(checks) + ";"


def transaction_context(ck, clock_context, port_info, reserved_names, internal_signals=(), *, reset_assertion=None):
    """Validate planned endpoint roles and bind observers to the normalized clock and reset."""
    if not clock_context["has_clock"] or not clock_context["has_reset"]:
        raise ValueError(f"{ck.id}: transaction_balance requires a clock and reset")
    if ck.sva_body != transaction_body(ck, clock_context["clock_edge"]):
        raise ValueError(f"{ck.id}: use the generated transaction_balance body from prepare sva")
    if ck.style.lower() == "assume" and reset_assertion not in {"async", "sync"}:
        raise ValueError(f"{ck.id}: resolve reset_assertion for the environment transaction observer")
    ports = dict(port_info)
    rows = []
    for index, rule in enumerate(ck.transaction_balance):
        inbound, outbound = ("output", "input") if rule.binding == "egress" else ("input", "output")
        roles = ((rule.command_valid, inbound), (rule.command_ready, outbound),
                 (rule.response_valid, outbound), (rule.response_ready, inbound))
        if len({name for name, _ in roles}) != len(roles):
            raise ValueError(f"{ck.id}: transaction_balance requires distinct handshake ports")
        for name, direction in roles:
            if rule.binding == "internal":
                if name not in internal_signals:
                    raise ValueError(f"{ck.id}: expected {name} to be a bound scalar whitebox signal")
                continue
            if name in {clock_context["actual_clock"], clock_context["actual_reset"]} or not re.fullmatch(
                rf"{direction} logic(?: signed)?(?: \[(-?\d+):\1\])? {re.escape(name)}", ports.get(name, "")
            ):
                raise ValueError(f"{ck.id}: expected {name} to be a scalar {direction} handshake port")
        name = f"uca_balance_{ck.id.replace('-', '_')}_{index}"
        generated = {f"{name}_{suffix}" for suffix in ("pending", "overflow", "command", "response", "retire")}
        if generated & reserved_names:
            raise ValueError(f"{ck.id}: transaction observer names collide with checker declarations")
        reserved_names.update(generated)
        rows.append({"name": name, "synchronous_reset": ck.style.lower() == "assume" and reset_assertion == "sync",
                     **rule.model_dump()})
    return rows


def latest_transfer_body(ck, clock_edge):
    """Generate an assertion about every delivery, including deliveries before the first capture."""
    if clock_edge not in {"posedge", "negedge"}:
        raise ValueError(f"{ck.id}: latest_transfer needs a configured clock edge")
    rule = ck.latest_transfer
    prefix = "uca_latest_" + ck.id.replace("-", "_")
    observed = rule.observed
    if isinstance(observed, list):
        observed = "{" + ", ".join(f"({lane.valid} && {lane.ready})" for lane in reversed(observed)) + "}"
    elif not isinstance(observed, str):
        observed = f"({observed.valid_vector} & {observed.ready_vector})"
    match = f"({prefix}_seen && ({observed} == {prefix}_value))"
    if rule.simultaneous == "current":
        match = f"(({rule.capture_valid} && {rule.capture_ready}) ? ({observed} == {rule.captured}) : {match})"
    return (f"@({clock_edge} clk) disable iff (!rst_n) "
            f"({rule.delivery_valid} && {rule.delivery_ready}) |-> {match};")


def latest_transfer_context(ck, clock, widths, reserved, reset_assertion):
    """Validate explicitly bound checker inputs before declaring a passive observer."""
    rule = ck.latest_transfer
    if not clock["has_clock"] or not clock["has_reset"]:
        raise ValueError(f"{ck.id}: latest_transfer requires a resolved clock and reset")
    if reset_assertion in {"sync", "async"} and rule.reset_assertion != reset_assertion:
        raise ValueError(f"{ck.id}: latest_transfer reset_assertion disagrees with the configured reset")
    blocked = {clock[key] for key in ("env_clock", "env_reset", "actual_clock", "actual_reset")}
    controls = [rule.capture_valid, rule.capture_ready, rule.delivery_valid, rule.delivery_ready]
    if any(name in blocked or widths.get(name) != 1 for name in controls):
        raise ValueError(f"{ck.id}: latest_transfer handshake controls must be resolved one-bit data signals")
    if rule.capture_valid == rule.capture_ready or rule.delivery_valid == rule.delivery_ready:
        raise ValueError(f"{ck.id}: valid and ready must denote distinct signals for each handshake")
    width = widths.get(rule.captured)
    if isinstance(rule.observed, list):
        lanes = [(lane.valid, lane.ready) for lane in rule.observed]
        if (len(set(lanes)) != len(lanes) or any(valid == ready for valid, ready in lanes)
                or any(name in blocked or widths.get(name) != 1 or name == rule.captured for pair in lanes for name in pair)):
            raise ValueError(f"{ck.id}: each observed lane needs a distinct handshake of resolved scalar signals")
        observed_width = len(lanes)
        payloads = {rule.captured}
    elif isinstance(rule.observed, str):
        observed_width = widths.get(rule.observed)
        payloads = {rule.captured, rule.observed}
    else:
        valid, ready = rule.observed.valid_vector, rule.observed.ready_vector
        if len({rule.captured, valid, ready}) != 3 or not widths.get(valid) or widths[valid] != widths.get(ready):
            raise ValueError(f"{ck.id}: bind separate equal-width valid and ready vectors for the observed lanes")
        observed_width = widths[valid]
        payloads = {rule.captured, valid, ready}
    if (not width or width != observed_width or rule.captured == rule.observed
            or payloads & (blocked | set(controls))):
        raise ValueError(f"{ck.id}: bind distinct equal-width captured and observed payloads apart from handshake signals")
    name = "uca_latest_" + ck.id.replace("-", "_")
    generated = {f"{name}_seen", f"{name}_value"}
    if reserved & generated:
        raise ValueError(f"{ck.id}: latest_transfer observer name collides with a checker declaration")
    reserved.update(generated)
    return {"name": name, "width": width, **rule.model_dump()}
