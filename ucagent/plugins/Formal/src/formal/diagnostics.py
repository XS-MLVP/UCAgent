"""Run bounded native FormalMC diagnostics on a frozen verification snapshot."""

import fcntl
import hashlib
import os
import re
import shutil
import signal
import subprocess
import uuid

from ucagent.util.file_policy import is_file_writeable

from .execution import PROOF_MARKER, atomic_json, input_lock, parse_properties, property_evidence, read_json, read_run, take_worker_slot, tcl_word

RESET_RELEASE = "u_checker.C_UCAGENT_DIAGNOSTIC_RESET_RELEASE"


def reset_release_verdict(console):
    """Parse only the complete native report for the tool-owned observation."""
    text = console.decode("utf-8", errors="replace")
    parts = re.findall(r"^UCAGENT_DIAG_BEGIN_reset_release\r?\n(.*?)^UCAGENT_DIAG_END_reset_release\r?$", text, re.M | re.S)
    if len(parts) != 1 or re.search(r"^\s*(?:Error:|Error-|Fatal)", text, re.M):
        return None
    try:
        return parse_properties(parts[0], "cover").get(RESET_RELEASE, {}).get("result")
    except ValueError:
        return None


def reset_release_gate(root, state):
    """Check a native receipt from the current shared setup before accepting proof results."""
    context = state.get("batch_context") or {}
    shared = context.get("shared_environment") or {}
    if not shared.get("reset_release_required"):
        return None
    checker = f"{state['output_dir']}/tests/{state['dut']}_checker.sv"
    extra_commands = ((shared.get("extra_config") or {}).get("tcl") or {}).get("extra_commands")
    result = {"status": "pending", "error_code": "formal_reset_release_pending",
              "analyze_call": {"mode": "reset_release", "run_id": state["run_id"]},
              "next_action": "Run the supplied AnalyzeFormal call before accepting proofs under this shared environment."}
    for path in root.glob("*/reset_release.json"):
        if not re.fullmatch(r"[a-f0-9]{32}", path.parent.name) or path.parent.is_symlink() or path.is_symlink():
            continue
        try:
            receipt = read_json(path)
            source, owner = read_run(root, path.parent.name, scope=None)
            if (not owner or owner.get("scope") not in {"selected", "full"}
                    or owner.get("batch_context") != context
                    or receipt["input_fingerprint"] != owner["fingerprint"]
                    or extra_commands and owner["files"].get(checker) != state["files"].get(checker)):
                continue
            relative = receipt["log"]
            if not re.fullmatch(r"diagnostic-[a-f0-9]{32}/console\.log", relative):
                continue
            log = source / relative
            if log.is_symlink() or log.parent.is_symlink():
                continue
            console = log.read_bytes()
            if hashlib.sha256(console).hexdigest() != receipt["log_sha256"]:
                continue
            verdict = reset_release_verdict(console)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if verdict == "COVER_UNREACHABLE":
            return {"status": "unreachable", "error_code": "formal_reset_release_unreachable",
                    "log": f"{state['output_dir']}/formal_runs/{log.relative_to(root).as_posix()}",
                    "next_action": "Reset release is unreachable under these inputs. Repair the shared reset setup or Assume checks, then rerun verification for the current inputs."}
        if verdict == "COVER_REACHED":
            result = {"status": "reachable", "log": f"{state['output_dir']}/formal_runs/{log.relative_to(root).as_posix()}"}
    return result


def reset_probe_setup(inputs, directory, setup, state, clock):
    """Compile the frozen official environment with one isolated reachability cover."""
    snapshot = directory / "inputs"
    for relative in state["files"]:
        destination = snapshot / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(inputs / relative, destination)
    probe_setup = snapshot / setup.relative_to(inputs)
    shutil.copyfile(setup, probe_setup)
    checker = probe_setup.with_name(f"{state['dut']}_checker.sv")
    body = checker.read_text(encoding="utf-8")
    endings = list(re.finditer(r"^\s*endmodule\b", body, re.MULTILINE))
    if len(endings) != 1 or RESET_RELEASE.rsplit(".", 1)[-1] in body:
        raise ValueError("Reset release diagnosis requires a single generated Formal checker.")
    name = RESET_RELEASE.rsplit(".", 1)[-1]
    cover = f"{name}: cover property (@({clock['clock_edge']} {clock['env_clock']}) $rose({clock['env_reset']}));"
    index = endings[0].start()
    checker.write_text(body[:index] + "\n  " + cover + "\n" + body[index:], encoding="utf-8")
    return probe_setup


def verified_setup(run_dir, state):
    """Locate a matching native setup and authenticate all of its frozen inputs."""
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
    return inputs, setup


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
    if mode == "coverage":
        if state.get("scope") != "full":
            raise ValueError("Coverage recovery requires the current full proof batch.")
        ready, current = execution.check()
        if not ready or current["run_id"] != run_id:
            raise ValueError("Coverage recovery requires reviewed proof evidence from the current stopped full batch. Review its status before retrying.")
        if current["coverage"]["status"] == "verified":
            return {"mode": mode, "run_id": run_id, "status": "completed", "coverage": current["coverage"],
                    "next_action": "Use this current structural coverage report for Check."}

    clock = None
    if mode == "reset_release":
        from .skills.lib.formal_tools import build_clock_reset_alias_context
        from .skills.lib.models import FormalRecords

        if state.get("scope") == "preflight" or not state.get("semantic_inputs"):
            raise ValueError("Reset release diagnosis requires a frozen official run with its actual Assume checks.")
        clock = build_clock_reset_alias_context(FormalRecords.model_validate(state["semantic_inputs"]))
        if not clock["has_clock"] or not clock["has_reset"]:
            return {"run_id": run_id, "mode": mode, "status": "not_applicable",
                    "next_action": "This run has no declared clocked reset. Review the scenarios in its specification."}

    commands = {
        "environment": {"clock": "clk_ana", "reset": "rst_ana", "constraints": "show_cons"},
        "overconstraint": {"overconstraint": f"check_overcons -depth {depth or 10}"},
        "sanity": {"sanity": f"prop_sanity -vac2 {tcl_word(property_name or '')}"},
        "fanin": {"fanin": f"fanin -assertion {tcl_word(property_name or '')} -list -disp"},
        "unreachable": {"reconfirm": f"set_opt -timeout 30s\nset_opt -bfd on\nprove {tcl_word(property_name or '')}\nshow_prop -only_cover -reason",
                        "unreachable": f"analyze_unreachable {tcl_word(property_name or '')} -preserve_pin_constraint"},
        "bounded_search": {"bounded_search": f"set_opt -engine bmc -depth {depth or 20} -timeout 30s\n"
                           f"prove {tcl_word(property_name or '')}\nshow_prop -only_assert -time -engine -reason"},
        "reset_release": {"reset_release": f"set_opt -timeout 20s\nprove {tcl_word(RESET_RELEASE)}\nshow_prop -only_cover -reason"},
        "coverage": {"coverage": "fanin -cover -list -dump"},
    }[mode]
    executable = shutil.which("FormalMC")
    if not executable:
        raise ValueError("FormalMC is unavailable. Ask the operator to restore it and retry AnalyzeFormal.")
    inputs, setup = verified_setup(run_dir, state)

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
        diagnostic_setup = reset_probe_setup(inputs, directory, setup, state, clock) if clock else setup
        tcl_commands = [f"source {tcl_word(str(diagnostic_setup))}"]
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
        next_action = ("Review the original result with the CK and source. For a conditional goal, check its trigger with a "
                       "specification-backed Cover. For an unconditional invariant, cite the structural relation that holds "
                       "for the allowed inputs. Use the current review if the available evidence is sufficient."
                       if mode == "sanity" else "Ask the operator to enable this FormalMC diagnostic.")
        return {**result, "status": "unavailable", "error_code": "formal_diagnostic_license_unavailable",
                "required_feature": license_required, "next_action": next_action}
    if mode == "fanin":
        result.update(signals=signals, signals_truncated=signals_truncated)
    complete = returncode == 0 and not errors and all(section["complete"] for section in sections.values())
    if mode == "coverage" and complete:
        from .coi import COI_RECEIPT, COI_REPORT, coverage_snapshot, seal_coverage

        receipt = run_dir / COI_RECEIPT
        allowed, reason = is_file_writeable(str(receipt.relative_to(execution.workspace)), execution.un_write_dirs, execution.write_dirs)
        if not allowed:
            raise ValueError(reason)
        output, _, _ = execution._paths(create=False)
        with input_lock(output), (root / "control.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            _, latest = read_run(root)
            if (not latest or latest["run_id"] != run_id or latest["status"] != state["status"]
                    or latest["properties"] != state["properties"] or execution._inputs(create=False)[-1] != state["fingerprint"]):
                raise ValueError("Formal inputs or proof state changed during coverage recovery. Use the current stopped full batch.")
            verified_setup(run_dir, state)
            try:
                seal_coverage(run_dir, state, (directory.relative_to(run_dir) / COI_REPORT).as_posix())
            except (OSError, ValueError) as exc:
                return {**result, "status": "error", "error_code": "formal_coverage_invalid",
                        "next_action": "Inspect the native coverage log and restore report generation.", "diagnostics": [str(exc)]}
            coverage, _ = coverage_snapshot(run_dir, state)
        return {**result, "status": "completed", "coverage": coverage,
                "next_action": "Use this current structural coverage report for Check."}
    if mode == "unreachable" and complete:
        try:
            verdict = parse_properties(verdict_row or "", "cover").get(property_name, {}).get("result")
        except ValueError:
            verdict = None
        if verdict != "COVER_UNREACHABLE":
            return {**result, "status": "inconclusive", "observed_cover_result": verdict,
                    "next_action": "The diagnostic did not reconfirm unreachability within its budget. Inspect the log."}
        result["observed_cover_result"] = verdict
    if mode == "reset_release" and complete:
        payload = log.read_bytes()
        verdict = reset_release_verdict(payload)
        if verdict not in {"COVER_REACHED", "COVER_UNREACHABLE"}:
            return {**result, "status": "inconclusive", "observed_cover_result": verdict,
                    "next_action": "Inspect the native report before drawing a conclusion about reset reachability."}
        receipt = run_dir / "reset_release.json"
        allowed, reason = is_file_writeable(str(receipt.relative_to(execution.workspace)),
                                            execution.un_write_dirs, execution.write_dirs)
        if not allowed or receipt.is_symlink():
            raise ValueError(reason or "Reset release receipt must be an ordinary file.")
        atomic_json(receipt, {"input_fingerprint": state["fingerprint"], "log": log.relative_to(run_dir).as_posix(),
                              "log_sha256": hashlib.sha256(payload).hexdigest()})
        return {**result, "status": "completed", "observed_cover_result": verdict,
                "next_action": ("Review shared clock, reset and Assume inputs before closing FCs that require reset release."
                                if verdict == "COVER_UNREACHABLE" else "Use this reachability evidence with the current shared environment.")}
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
