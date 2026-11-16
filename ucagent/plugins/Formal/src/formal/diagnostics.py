"""Run bounded native FormalMC diagnostics on a frozen verification snapshot."""

import hashlib
import os
import re
import shutil
import signal
import subprocess
import uuid

from ucagent.util.file_policy import is_file_writeable

from .execution import PROOF_MARKER, parse_properties, property_evidence, read_run, take_worker_slot, tcl_word


def analyze(execution, run_id: str, mode: str, property_name: str | None, depth: int | None) -> dict:
    """Collect native observations without changing the source run or its results."""
    _, _, root = execution._paths(create=False)
    run_dir, state = read_run(root, run_id, scope=None)
    if not run_dir:
        raise ValueError("Select an existing Formal run for analysis.")
    if depth is not None and mode not in {"overconstraint", "bounded_search"}:
        raise ValueError("Depth is available for overconstraint and bounded_search.")
    if mode == "replay":
        from .replay import replay_counterexample
        if not property_name:
            raise ValueError("Use the exact original failed assertion for replay.")
        return replay_counterexample(execution, run_dir, state, property_name)
    if mode in {"sanity", "fanin", "unreachable", "bounded_search"}:
        item = state["properties"].get(property_name)
        if not item or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.$:]*", property_name):
            raise ValueError("Use one exact Assert/Cover name from this run's inventory without wildcard syntax.")
        if mode in {"fanin", "bounded_search"} and item["kind"] != "assert":
            raise ValueError("Use an Assert from this run for this diagnostic.")
        if mode == "unreachable":
            if item["kind"] != "cover" or item["result"] != "COVER_UNREACHABLE":
                raise ValueError("Select a Cover with a completed unreachable result.")
            property_evidence(run_dir, {**state, "workspace": str(execution.workspace)}, property_name, item, observations=False)
    elif property_name is not None:
        raise ValueError("This diagnostic does not take a property_name.")

    commands = {
        "environment": {"clock": "clk_ana", "reset": "rst_ana", "constraints": "show_cons"},
        "overconstraint": {"overconstraint": f"check_overcons -depth {depth or 10}"},
        "sanity": {"sanity": f"prop_sanity -vac2 {tcl_word(property_name or '')}"},
        "fanin": {"fanin": f"fanin -assertion {tcl_word(property_name or '')} -list -disp"},
        "unreachable": {"reconfirm": f"set_opt -timeout 30s\nset_opt -bfd on\nprove {tcl_word(property_name or '')}\nshow_prop -only_cover -reason",
                        "unreachable": f"analyze_unreachable {tcl_word(property_name or '')} -preserve_pin_constraint"},
        "bounded_search": {"bounded_search": f"set_opt -engine bmc -depth {depth or 20} -timeout 30s\n"
                           f"prove {tcl_word(property_name or '')}\nshow_prop -only_assert -time -engine -reason"},
    }[mode]
    executable = shutil.which("FormalMC")
    if not executable:
        raise ValueError("FormalMC is unavailable. Ask the operator to restore it and retry AnalyzeFormal.")
    inputs = run_dir / "inputs"
    for relative, expected in state["files"].items():
        path = inputs / relative
        if not path.resolve().is_relative_to(inputs) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("The archived Formal inputs have changed. Select a run with intact inputs.")
    tcl = inputs / state["output_dir"] / "tests" / f"{state['dut']}_formal.tcl"
    setup = tcl.with_name("setup.tcl")
    if (str(tcl.relative_to(inputs)) not in state["files"] or setup.is_symlink()
            or setup.read_text() != tcl.read_text().split(PROOF_MARKER, 1)[0]):
        raise ValueError("The archived Formal setup does not match the input snapshot.")

    limits = execution.policy
    slot = take_worker_slot(root, limits.max_active_workers)
    result = {"run_id": run_id, "scope": state.get("scope", "full"), "input_fingerprint": state["fingerprint"],
              "mode": mode, "property_name": property_name}
    if mode in {"overconstraint", "bounded_search"}:
        result["requested_depth"] = depth or (10 if mode == "overconstraint" else 20)
    if mode == "overconstraint":
        result["search_depth"] = result["requested_depth"]
    if slot is None:
        return {**result, "status": "busy", "next_action": "Retry after a Formal worker slot becomes free."}
    with slot:
        directory = run_dir / f"diagnostic-{uuid.uuid4().hex}"
        script = directory / "analyze.tcl"
        log = directory / "console.log"
        for path in (directory, script, log):
            allowed, reason = is_file_writeable(str(path.relative_to(execution.workspace)),
                                                execution.un_write_dirs, execution.write_dirs)
            if not allowed:
                raise ValueError(reason)
        directory.mkdir()
        tcl_commands = [f"source {tcl_word(str(setup))}"]
        for name, command in commands.items():
            tcl_commands.extend([f"puts UCAGENT_DIAG_BEGIN_{name}", command, f"puts UCAGENT_DIAG_END_{name}"])
        script.write_text("\n".join([*tcl_commands, "exit", ""]), encoding="utf-8")
        with log.open("w", encoding="utf-8") as stream, subprocess.Popen(
            [executable, "-f", str(script), "-override", "-work_dir", str(directory)],
            cwd=directory, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
            start_new_session=True, pass_fds=(slot.fileno(),),
        ) as child:
            try:
                returncode = child.wait(timeout=min(limits.setup_timeout_s, 60))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
                return {**result, "status": "timeout", "log": str(log.relative_to(execution.workspace)),
                        "next_action": "Inspect the partial log; for overconstraint, try a smaller search depth."}

    sections = {name: {"command": command, "lines": [], "complete": False, "truncated": False}
                for name, command in commands.items()}
    current = None
    errors = []
    license_required = None
    signals = []
    signals_truncated = False
    verdict_row = None
    with log.open(encoding="utf-8", errors="replace") as stream:
        for raw in stream:
            line = raw.strip()
            if match := re.match(r"Error: checkout license for ([\w.-]+)", line):
                license_required = match[1]
            if line.startswith(("Error:", "Error-", "Fatal")) and len(errors) < 6:
                errors.append(line[:400])
            if line.startswith("UCAGENT_DIAG_BEGIN_"):
                current = sections.get(line.removeprefix("UCAGENT_DIAG_BEGIN_"))
            elif current is not None and line.startswith("UCAGENT_DIAG_END_"):
                current["complete"] = True
                current = None
            elif current is not None and line:
                if len(current["lines"]) < 18:
                    current["lines"].append(line[:400])
                else:
                    current["truncated"] = True
                if len(line) > 400:
                    current["truncated"] = True
                if mode == "fanin" and (match := re.fullmatch(r"(Input|Output|Dff|Latch|Net|Undriven|Cut)\s*:\s+(\S+)", line)):
                    if len(signals) < 64:
                        signals.append({"kind": match[1].lower(), "signal": match[2]})
                    else:
                        signals_truncated = True
                if current in (sections.get("reconfirm"), sections.get("bounded_search")) and re.match(
                    r"^\d+\s+" + re.escape(property_name or "") + r"\s*:", line
                ):
                    verdict_row = line
    result["log"] = str(log.relative_to(execution.workspace))
    if license_required:
        next_action = ("Check the trigger with a specification-backed Cover, or ask the operator to enable the vacuity diagnostic."
                       if mode == "sanity" else "Ask the operator to enable this FormalMC diagnostic.")
        return {**result, "status": "unavailable", "error_code": "formal_diagnostic_license_unavailable",
                "required_feature": license_required, "next_action": next_action}
    if mode == "fanin":
        result.update(signals=signals, signals_truncated=signals_truncated)
    complete = returncode == 0 and not errors and all(section["complete"] for section in sections.values())
    if mode == "unreachable" and complete:
        try:
            verdict = parse_properties(verdict_row or "", "cover").get(property_name, {}).get("result")
        except ValueError:
            verdict = None
        if verdict != "COVER_UNREACHABLE":
            return {**result, "status": "inconclusive", "observed_cover_result": verdict,
                    "next_action": "The diagnostic did not reconfirm unreachability within its budget. Inspect the log."}
        result["observed_cover_result"] = verdict
    if mode == "bounded_search" and complete:
        try:
            observed = parse_properties(verdict_row or "", "assert").get(property_name, {})
        except ValueError:
            observed = {}
        verdict = observed.get("result")
        result.update(raw_status=observed.get("raw_status"), reported_depth=observed.get("depth"),
                      search_outcome="counterexample" if verdict == "FALSIFIED" else
                      "no_counterexample_reported" if verdict in {"UNPROVEN", "PROVEN", "TRIVIALLY_TRUE"} else "inconclusive")
        if verdict == "FALSIFIED":
            trace = directory / "avis" / property_name / (property_name + ".vcd")
            if trace.is_file() and trace.resolve().is_relative_to(directory):
                result["trace_artifact"] = str(trace.relative_to(execution.workspace))
    return {**result, "status": "completed" if complete else "error", "observations": sections,
            "diagnostics": errors,
            "next_action": ("Use the native observations to guide review of the archived inputs."
                            if complete else "Inspect the diagnostic log for an unsupported command or setup failure.")}
