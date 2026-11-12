"""Evidence-backed FormalMC property scheduling with bounded, fair execution.

The controller runs independently of tool calls. Each property gets an isolated
FormalMC process and a short first turn before competing for slow-lane capacity.
Only tool-authored state and reports determine completion; decisions never turn
an unfinished proof into a proved property.
"""

from __future__ import annotations

import argparse
import collections
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid


FINAL_RESULTS = {"PROVEN", "FALSIFIED", "TRIVIALLY_TRUE", "TRIVIALLY_FALSE", "COVER_REACHED", "COVER_UNREACHABLE"}
RUN_POINTERS = {"full": "current.json", "selected": "selected.json"}
PROOF_MARKER = "# UCAGENT_PROOF_BEGIN"
ACTIVE_RUNS = {"PREPARING", "RUNNING", "CANCELLING"}
ROW = re.compile(r"^\s*(\d+)\s+(\S+)\s*:\s*(.*?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class ExecutionPolicy:
    """Validated resolved budgets; waiting and compilation do not consume proof turns."""

    first_pass_budget_s: int = 300
    analysis_threshold_s: int = 1200
    max_active_workers: int = 2
    slow_queue_max_workers: int = 1
    setup_timeout_s: int = 120
    stop_grace_s: int = 10
    max_review_rounds: int = 3
    property_cumulative_budget_s: int = 3600

    @classmethod
    def from_cfg(cls, cfg):
        """Read one canonical mapping from resolved cfg and reject ambiguous limits."""
        try:
            raw = cfg.get_value("runtime_options.formal_execution", {})
        except AttributeError:
            raw = {}
        if hasattr(raw, "as_dict"):
            raw = raw.as_dict()
        if not isinstance(raw, dict) or set(raw) - set(cls.__dataclass_fields__):
            raise ValueError("runtime_options.formal_execution contains invalid fields")
        values = {**asdict(cls()), **raw}
        if any(type(value) is not int or value < 1 for value in values.values()):
            raise ValueError("formal_execution limits must be positive integers")
        if values["analysis_threshold_s"] <= values["first_pass_budget_s"]:
            raise ValueError("analysis_threshold_s must exceed first_pass_budget_s")
        if values["slow_queue_max_workers"] > values["max_active_workers"]:
            raise ValueError("slow_queue_max_workers must not exceed max_active_workers")
        if values["property_cumulative_budget_s"] < values["analysis_threshold_s"]:
            raise ValueError("property_cumulative_budget_s must cover analysis_threshold_s")
        return cls(**values)


def atomic_json(path: Path, value) -> None:
    """Atomically publish a complete JSON object without exposing partial writes."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path):
    """Read one persisted machine record; malformed state must not be guessed."""
    return json.loads(path.read_text(encoding="utf-8"))


@contextmanager
def input_lock(output: Path):
    """Serialize generated input publication with snapshot creation."""
    path = output / ".formal_inputs.lock"
    with os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def read_run(root: Path, run_id: str | None = None, scope: str = "full"):
    """Read one exact run or a scope-specific pointer without recovering processes."""
    if scope not in RUN_POINTERS:
        raise ValueError("Formal run scope must be full or selected.")
    if root.is_symlink():
        raise ValueError("Invalid Formal run root")
    if run_id is None:
        pointer = root / RUN_POINTERS[scope]
        if pointer.is_symlink():
            raise ValueError("Invalid Formal run pointer")
        if not pointer.is_file():
            return None, None
        run_id = read_json(pointer)["run_id"]
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("Invalid Formal run ID")
    run_dir = root / run_id
    state_path = run_dir / "state.json"
    if run_dir.is_symlink() or state_path.is_symlink() or not state_path.is_file():
        raise ValueError("Formal run record is unavailable")
    state = read_json(state_path)
    if state.get("run_id") != run_id or state.get("scope", "full") != scope:
        raise ValueError("Formal run does not match the requested identity and scope")
    return run_dir, state


def take_worker_slot(root: Path, limit: int):
    """Reserve one work-directory slot shared by all controllers in this workspace."""
    for index in range(limit):
        path = root / f"worker-{index}.lock"
        slot = os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), "a+")
        try:
            fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return slot
        except BlockingIOError:
            slot.close()
    return None


def review_actions(item: dict, policy: ExecutionPolicy) -> list[str]:
    """Return the current actions for a genuinely unresolved proof target."""
    if item["result"] != "UNPROVEN":
        return []
    actions = []
    if (item["state"] in {"REVIEW", "ERROR", "CANCELLED", "NOT_EXECUTED"}
            and item["review_round"] < policy.max_review_rounds
            and item["execution_elapsed_s"] < policy.property_cumulative_budget_s):
        actions.append("retry")
    if item["state"] == "REVIEW" and item.get("disposition") != "DEFERRED":
        actions.append("defer")
    return actions


def apply_decisions(state: dict, decisions: list[dict]) -> None:
    """Apply already validated decisions to only their target properties."""
    for decision in decisions:
        item = state["properties"][decision["property"]]
        action = decision["action"]
        state["decisions"].append(decision)
        item["disposition"] = "DEFERRED" if action == "defer" else None
        if action == "retry":
            item["review_round"] += 1
            item["round_elapsed_s"] = 0.0
            item["state"] = "QUEUED_SLOW"


def tcl_word(value: str) -> str:
    """Quote one Tcl word without allowing substitution or command injection."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("[", "\\[").replace("]", "\\]").replace("\n", "\\n").replace("\r", "\\r") + '"'


def process_identity(pid: int) -> str:
    """Return the Linux process birth token, preventing PID-reuse cancellation."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return "" if fields[0] == "Z" else fields[19]
    except (OSError, IndexError):
        return ""


def group_members(pid: int) -> list:
    """Collect live birth identities for one isolated process group and session."""
    members = []
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = path.read_text().rsplit(")", 1)[1].split()
            if fields[0] != "Z" and int(fields[2]) == pid and int(fields[3]) == pid:
                members.append([int(path.parent.name), fields[19]])
        except (OSError, ValueError, IndexError):
            continue
    return members


def group_is_owned(pid: int, identity: str, members=()) -> bool:
    """Require the original leader or a recorded surviving member, never just a PGID."""
    current = process_identity(pid)
    if current:
        return current == identity
    actual = group_members(pid)
    return any(member in actual for member in members)


def stop_process(pid: int, identity: str, grace: float, members=()) -> None:
    """Terminate only the owned process group and escalate after a bounded grace."""
    if not identity or not group_is_owned(pid, identity, members):
        return
    members = list(members) + group_members(pid)
    try:
        os.killpg(pid, signal.SIGTERM)
        deadline = time.monotonic() + grace
        while group_is_owned(pid, identity, members) and time.monotonic() < deadline:
            time.sleep(0.05)
        if group_is_owned(pid, identity, members):
            os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def parse_properties(text: str, property_kind: str | None = None) -> dict:
    """Parse scoped FormalMC tables without deriving property kind from a label."""
    typed = list(re.finditer(r"^UCAGENT_(ASSERT|COVER)_BEGIN\r?\n(.*?)^UCAGENT_\1_END\r?$", text, re.MULTILINE | re.DOTALL))
    if typed:
        combined = {}
        for block in typed:
            rows = parse_properties(block.group(2), block.group(1).lower())
            if combined.keys() & rows.keys():
                raise ValueError("Duplicate property identity in FormalMC inventory")
            combined.update(rows)
        return combined
    result = {}
    for match in ROW.finditer(text):
        name, details = match.group(2), match.group(3)
        fields = [part.strip() for part in details.split("\t") if part.strip()]
        status = re.match(r"(NotRun|Undet|Undec|Pass|Fail|TrivT|TrivF|Covered|Uncoverable)\b", fields[0] if fields else "")
        if not status:
            raise ValueError(f"Unrecognized FormalMC property status for {name}: {fields[0] if fields else 'empty'}")
        raw = status.group(1)
        is_cover = property_kind == "cover"
        verdict = {"Pass": "COVER_REACHED" if is_cover else "PROVEN",
                   "Fail": "COVER_UNREACHABLE" if is_cover else "FALSIFIED",
                   "TrivT": "COVER_REACHED" if is_cover else "TRIVIALLY_TRUE",
                   "TrivF": "COVER_UNREACHABLE" if is_cover else "TRIVIALLY_FALSE", "Covered": "COVER_REACHED",
                   "Uncoverable": "COVER_UNREACHABLE"}.get(raw, "UNPROVEN")
        depth = re.search(r"\((\d+)\)", fields[0])
        if name in result:
            raise ValueError(f"Duplicate property identity in FormalMC table: {name}")
        result[name] = {"id": int(match.group(1)), "name": name, "kind": property_kind,
                        "result": verdict, "raw_status": fields[0],
                        "depth": int(depth.group(1)) if depth else None,
                        "engine": fields[1] if len(fields) > 1 else None,
                        "solver_reported_time_s": None, "reason": fields[3] if len(fields) > 3 else None}
        if len(fields) > 2:
            try:
                value = float(fields[2])
                if math.isfinite(value) and value >= 0:
                    result[name]["solver_reported_time_s"] = value
            except ValueError:
                pass
    return result


def choose_next(properties: dict, active: list[dict], policy: ExecutionPolicy):
    """Prefer untouched properties; bound slow occupancy while either queue has work."""
    fast = [name for name, item in properties.items() if item["state"] == "QUEUED_FAST"]
    slow = [name for name, item in properties.items() if item["state"] == "QUEUED_SLOW"]
    if fast:
        return fast[0]
    slow_active = sum(item["lane"] == "slow" for item in active)
    # Once all first turns have been assigned, unused fast slots can be borrowed.
    limit = policy.slow_queue_max_workers if any(item["lane"] == "fast" for item in active) else policy.max_active_workers
    return slow[0] if slow and slow_active < limit else None


def write_report(run_dir: Path, state: dict) -> None:
    """Render a complete derived report without concealing deferred proof gaps."""
    deferred = sum(item.get("disposition") == "DEFERRED" for item in state["properties"].values())
    complete = bool(state["properties"]) and all(item["result"] in FINAL_RESULTS for item in state["properties"].values())
    lines = ["", "# Formal execution report", "", "## Run", "",
             f"- Run: `{state['run_id']}`", f"- Scope: `{state.get('scope', 'full')}`", f"- State: `{state['status']}`",
             f"- Fingerprint: `{state['fingerprint']}`", f"- Proof complete: `{str(complete).lower()}`",
             f"- Deferred: {deferred}", "", "## Results", "",
             "| Property | Result | State | Active seconds | Disposition |",
             "| --- | --- | --- | ---: | --- |"]
    for name, item in state["properties"].items():
        lines.append(f"| `{name}` | {item['result']} | {item['state']} | {item['execution_elapsed_s']:.2f} | {item.get('disposition') or '-'} |")
    lines += ["", "## Decisions", ""]
    decisions = state.get("decisions", [])
    if not decisions:
        lines.append("No review decisions recorded.")
    for decision in decisions:
        lines.append(f"- `{decision['property']}`: {decision['action']} — {decision['reason']}; next: {decision['next_action']}")
    lines += ["", "## Evidence", "", "- `state.json`: current machine results and attempt references.",
              "- `snapshots/`: immutable checkpoint results.", "- `attempts/`: isolated FormalMC reports and logs.", ""]
    report = run_dir / "report.md"
    temporary = report.with_suffix(".tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    os.replace(temporary, report)


def property_evidence(run_dir: Path, state: dict, name: str, item: dict, *, observations=True) -> dict:
    """Bind one final result to its exact report and optional tool-generated witness."""
    if item["result"] not in FINAL_RESULTS or not item["attempts"]:
        raise ValueError(f"Property has no completed proof evidence: {name}")
    attempt = item["attempts"][-1]
    if attempt.get("running"):
        raise ValueError(f"Property evidence has not been finalized: {name}")
    console = run_dir / attempt["console"]
    if not console.resolve().is_relative_to(run_dir.resolve()) or console.is_symlink():
        raise ValueError("Invalid property evidence path")
    payload = console.read_bytes()
    report_hash = hashlib.sha256(payload).hexdigest()
    if report_hash != attempt.get("console_hash") or attempt.get("returncode") != 0:
        raise ValueError(f"Property report changed or execution was unsuccessful: {name}")
    text = payload.decode("utf-8", errors="replace")
    block = re.search(r"^UCAGENT_RESULT_BEGIN\r?\n(.*?)^UCAGENT_RESULT_END\r?$", text, re.MULTILINE | re.DOTALL)
    actual = parse_properties(block.group(1), item["kind"]).get(name) if block else None
    if not actual or actual["result"] != item["result"]:
        raise ValueError(f"Property conclusion does not match the tool report: {name}")
    witness = console.parent / "avis" / name / (name + ".tb.v")
    if not witness.resolve().is_relative_to(console.parent.resolve()) or witness.is_symlink():
        raise ValueError("Invalid property witness path")
    witness_hash = hashlib.sha256(witness.read_bytes()).hexdigest() if witness.is_file() else None
    if witness_hash != attempt.get("witness_hash"):
        raise ValueError(f"Property witness changed after execution: {name}")
    from formal.evidence import original_inputs, trace_observations
    trace = witness.with_name(name + ".vcd")
    if not trace.resolve().is_relative_to(console.parent.resolve()) or trace.is_symlink():
        raise ValueError("Invalid original observation path")
    trace_hash = None
    if trace.is_file():
        with trace.open("rb") as stream:
            trace_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    if trace_hash != attempt.get("trace_hash"):
        raise ValueError(f"Original trace changed after execution: {name}")
    return {**original_inputs(witness), "trace_observations": trace_observations(trace) if observations else None,
            "trace_artifact": str(trace.relative_to(Path(state["workspace"]))) if trace_hash else None,
            "trace_sha256": trace_hash,
            "run_id": state["run_id"], "attempt_console": str(console.relative_to(Path(state["workspace"]))),
            "raw_status": item["raw_status"], "result": item["result"], "depth": item.get("depth"),
            "witness_artifact": str(witness.relative_to(Path(state["workspace"]))) if witness_hash else None,
            "witness_sha256": witness_hash,
            "evidence_ref": {"run_id": state["run_id"], "input_fingerprint": state["fingerprint"],
                             "property": name, "report_sha256": report_hash, "witness_sha256": witness_hash, "trace_sha256": trace_hash}}


def query_run_trace(workspace: Path, run_dir: Path, state: dict, name: str, query, current_inputs) -> dict:
    """Resolve and verify one sealed trace for tool, skill and dashboard clients."""
    from formal.trace import trace_page

    item = state["properties"].get(name)
    if not item:
        raise ValueError(f"Exact property identity not found: {name}")
    evidence = property_evidence(run_dir, {**state, "workspace": str(workspace)}, name, item, observations=False)
    if not evidence["trace_artifact"]:
        raise ValueError("This attempt has no original VCD.")
    path = workspace / evidence["trace_artifact"]
    result = {}
    if query.mode != "artifact":
        result = trace_page(path, evidence["trace_sha256"], query)
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != evidence["trace_sha256"]:
                raise ValueError("Original trace changed during analysis.")
    return {**result, "run_id": state["run_id"], "scope": state.get("scope", "full"),
            "property": name, "trace_artifact": evidence["trace_artifact"],
            "evidence_ref": evidence["evidence_ref"], "current_inputs": current_inputs}


class FormalExecution:
    """Control one current run per output directory using atomic records and locks."""

    def __init__(self, workspace: str, output_dir: str, dut: str, cfg, write_dirs=None, un_write_dirs=None):
        """Store resolved context; do not scan inputs while constructing a tool."""
        self.workspace = Path(workspace).resolve()
        self.output_dir, self.dut = output_dir, dut
        self.policy = ExecutionPolicy.from_cfg(cfg)
        self.write_dirs, self.un_write_dirs = write_dirs, un_write_dirs

    def _paths(self, create: bool = True):
        """Validate resolved workspace paths and policy before any artifact writes."""
        from ucagent.util.file_policy import is_file_writeable, normalize_relative_path
        output = normalize_relative_path(self.output_dir)
        dut = normalize_relative_path(self.dut)
        if len(Path(dut).parts) != 1:
            raise ValueError("DUT must be a single workspace directory name")
        target = self.workspace / output
        source = self.workspace / dut
        for path in (target, source):
            if not path.resolve().is_relative_to(self.workspace):
                raise ValueError("Formal paths must remain inside workspace")
            if any(part.is_symlink() for part in (path, *path.parents) if part.is_relative_to(self.workspace)):
                raise ValueError("Formal paths must not contain symlinks")
        allowed, reason = is_file_writeable(output, self.un_write_dirs, self.write_dirs)
        if not allowed:
            raise ValueError(reason)
        root = target / "formal_runs"
        for planned in (root, target / "tests", target / ".formal_records.yaml", target / "tests" / "avis.log", target / "tests" / "avis" / "fanin.rep"):
            allowed, reason = is_file_writeable(str(planned.relative_to(self.workspace)), self.un_write_dirs, self.write_dirs)
            if not allowed:
                raise ValueError(reason)
        for destination in (root, target / "tests"):
            if destination.exists():
                for path in (destination, *destination.rglob("*")):
                    if path.is_symlink():
                        raise ValueError("Formal artifact paths must not contain symlinks")
                    allowed, reason = is_file_writeable(str(path.relative_to(self.workspace)), self.un_write_dirs, self.write_dirs)
                    if not allowed:
                        raise ValueError(reason)
        if create:
            root.mkdir(parents=True, exist_ok=True)
        return target, source, root

    def _inputs(self, create: bool = True):
        """Fingerprint actual input files, resolved execution policy, and executable identity."""
        target, source, root = self._paths(create=create)
        executable = shutil.which("FormalMC")
        if not executable:
            raise ValueError("Formal verification is unavailable; ask the operator to restore the tool and retry RunFormal.")
        files = list(source.rglob("*")) if source.is_dir() else []
        files = [path for path in files if path.is_file()]
        tests = target / "tests"
        files += [tests / f"{self.dut}_{suffix}" for suffix in ("checker.sv", "wrapper.sv", "formal.tcl")]
        if not files or not source.is_dir():
            raise ValueError("DUT source directory is missing or empty")
        manifest = {}
        for path in sorted(set(files)):
            if not path.resolve().is_relative_to(self.workspace) or path.is_symlink():
                raise ValueError("Formal input symlinks or paths outside workspace are not supported")
            if not path.is_file():
                raise ValueError(f"Missing formal input: {path.relative_to(self.workspace)}; generate the environment, then call RunFormal.")
            manifest[str(path.relative_to(self.workspace))] = hashlib.sha256(path.read_bytes()).hexdigest()
        records_path = target / ".formal_records.yaml"
        semantic = None
        if records_path.exists():
            if records_path.is_symlink():
                raise ValueError("Formal records must not be a symlink")
            import yaml
            records = yaml.safe_load(records_path.read_text(encoding="utf-8"))
            if not isinstance(records, dict):
                raise ValueError("Formal records must be a mapping")
            from formal.skills.lib.models import semantic_inputs
            semantic = semantic_inputs(records)
        tool = Path(executable).resolve()
        identity = {"path": str(tool), "size": tool.stat().st_size, "mtime_ns": tool.stat().st_mtime_ns}
        fingerprint = hashlib.sha256(json.dumps({"files": manifest, "semantic": semantic, "policy": asdict(self.policy), "tool": identity}, sort_keys=True).encode()).hexdigest()
        return target, root, executable, manifest, fingerprint

    def input_fingerprint(self) -> str:
        """Compute exact current input identity without creating artifacts or changing runs."""
        return self._inputs(create=False)[-1]

    def _load(self, root, run_id=None, scope="full"):
        """Resolve one run and recover only that run's interrupted controller."""
        run_dir, state = read_run(root, run_id, scope)
        if state is None:
            return None, None
        if state["status"] in ACTIVE_RUNS and state.get("controller_identity"):
            if process_identity(state["controller_pid"]) != state["controller_identity"]:
                inventory = state.get("inventory_process")
                if inventory:
                    stop_process(inventory["pid"], inventory["identity"], self.policy.stop_grace_s, inventory.get("members", []))
                for item in state["properties"].values():
                    for attempt in item["attempts"]:
                        if attempt.get("running"):
                            stop_process(attempt["pid"], attempt["identity"], self.policy.stop_grace_s, attempt.get("members", []))
                            attempt["running"] = False
                            item["state"] = "ERROR"
                state["status"] = "INTERRUPTED"
                state["error"] = "Execution controller stopped; call RunFormal review with retry after inspecting the report."
                atomic_json(run_dir / "state.json", state)
        return run_dir, state

    def _launch(self, run_dir, state):
        """Start a controller whose lifetime is independent of a single tool request."""
        with (run_dir / "controller.log").open("ab") as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", str(run_dir)],
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True, close_fds=True)
        threading.Thread(target=process.wait, daemon=True).start()
        state["controller_pid"] = process.pid
        state["controller_identity"] = process_identity(process.pid)
        atomic_json(run_dir / "state.json", state)
        # The controller waits for this publication before reading state.
        (run_dir / "ready").touch()

    def run(self, property_names: list[str] | None = None) -> dict:
        """Start current immutable inputs once, or return the existing current run."""
        if property_names is not None and (
            not property_names or len(property_names) != len(set(property_names))
            or any(not isinstance(name, str) or not name.strip() for name in property_names)
        ):
            raise ValueError("Selected proof requires unique, exact property names.")
        selected = sorted(property_names) if property_names is not None else []
        scope = "selected" if selected else "full"
        target, _, root = self._paths()
        with input_lock(target), (root / "control.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            target, root, executable, files, fingerprint = self._inputs()
            previous_dir, previous = self._load(root, scope=scope)
            if (previous and previous["fingerprint"] == fingerprint and previous.get("selected_properties", []) == selected
                    and previous["status"] not in {"ERROR", "INTERRUPTED", "CANCELLED"}):
                return self._summary(previous_dir, previous)
            if previous and previous["status"] in ACTIVE_RUNS:
                raise ValueError("A different input revision is still running. Cancel it before starting the current revision.")
            run_id = uuid.uuid4().hex
            run_dir = root / run_id
            run_dir.mkdir()
            inputs = run_dir / "inputs"
            for relative, expected_hash in files.items():
                destination = inputs / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                content = (self.workspace / relative).read_bytes()
                if hashlib.sha256(content).hexdigest() != expected_hash:
                    raise ValueError("Formal inputs changed while freezing the run; retry RunFormal.")
                destination.write_bytes(content)
            frozen_tests = inputs / self.output_dir / "tests"
            tcl = frozen_tests / f"{self.dut}_formal.tcl"
            script = tcl.read_text(encoding="utf-8")
            if script.count(PROOF_MARKER) != 1:
                raise ValueError("Generate the current formal environment before RunFormal; proof boundary is missing.")
            setup = script.split(PROOF_MARKER)[0]
            (frozen_tests / "setup.tcl").write_text(setup, encoding="utf-8")
            checker_text = (frozen_tests / f"{self.dut}_checker.sv").read_text(encoding="utf-8")
            expected_labels = re.findall(r"\b([A-Za-z_][A-Za-z_0-9]*)\s*:\s*(?:assert|cover)\s+property\b", checker_text)
            semantic_inputs = None
            records_path = target / ".formal_records.yaml"
            if records_path.exists():
                import yaml
                records = yaml.safe_load(records_path.read_text(encoding="utf-8"))
                from formal.skills.lib.models import semantic_inputs as canonical_inputs
                semantic_inputs = canonical_inputs(records)
                archived = inputs / self.output_dir / ".formal_records.yaml"
                archived.write_bytes(records_path.read_bytes())
            receipt = target / "tests" / "sva_preflight.json"
            if receipt.is_file():
                preflight = read_json(receipt)
                semantic_hash = hashlib.sha256(json.dumps(semantic_inputs, sort_keys=True).encode()).hexdigest()
                generated = {Path(path).name: digest for path, digest in files.items()
                             if Path(path).parent == Path(self.output_dir) / "tests"}
                if semantic_hash != preflight["semantic_sha256"] or generated != preflight["generated"]:
                    raise ValueError("Generated Formal inputs changed after preflight; render them again before proof.")
            if self._inputs()[-1] != fingerprint:
                raise ValueError("Formal inputs changed while freezing the run; retry RunFormal.")
            state = {"run_id": run_id, "fingerprint": fingerprint, "status": "PREPARING",
                     "scope": scope, "selected_properties": selected,
                     "semantic_inputs": semantic_inputs,
                     "expected_labels": expected_labels,
                     "workspace": str(self.workspace), "output_dir": self.output_dir, "dut": self.dut,
                     "executable": executable, "policy": asdict(self.policy), "created_at": time.time(),
                     "files": files, "properties": {}, "decisions": [], "checkpoints": [], "error": None}
            atomic_json(run_dir / "state.json", state)
            write_report(run_dir, state)
            atomic_json(root / RUN_POINTERS[scope], {"run_id": run_id})
            self._launch(run_dir, state)
            return self._summary(run_dir, state)

    def status(self, wait_s: int = 0, *, run_id=None, scope="full") -> dict:
        """Return progress, optionally waiting for a new checkpoint without busy LLM polling."""
        if type(wait_s) is not int or not 0 <= wait_s <= 1200:
            raise ValueError("wait_s must be an integer between 0 and 1200")
        if wait_s:
            initial = self.status(run_id=run_id, scope=scope)
            if initial["status"] in ACTIVE_RUNS:
                _, _, root = self._paths()
                deadline = time.monotonic() + wait_s
                while time.monotonic() < deadline:
                    with (root / "control.lock").open("a+") as lock:
                        fcntl.flock(lock, fcntl.LOCK_EX)
                        _, latest = self._load(root, initial["run_id"], scope)
                    if latest["status"] != initial["status"] or len(latest["checkpoints"]) != initial["checkpoint_total"]:
                        break
                    time.sleep(min(0.5, max(0, deadline - time.monotonic())))
                return self.status(run_id=initial["run_id"], scope=scope)
            return initial
        _, root, _, _, fingerprint = self._inputs()
        with (root / "control.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            run_dir, state = self._load(root, run_id, scope)
            if state is None:
                return {"status": "NOT_STARTED", "next_action": "Call RunFormal action=run."}
            result = self._summary(run_dir, state)
            result["current_inputs"] = state["fingerprint"] == fingerprint
            if not result["current_inputs"]:
                result["next_action"] = "Call RunFormal action=run for the changed inputs; cancel the old run first if active."
            return result

    def cancel(self, *, run_id=None, scope="full") -> dict:
        """Request controller-owned cleanup rather than killing an arbitrary persisted PID."""
        _, _, root = self._paths()
        with (root / "control.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            run_dir, state = self._load(root, run_id, scope)
            if not state:
                return {"status": "NOT_STARTED"}
            if state["status"] in ACTIVE_RUNS:
                (run_dir / "cancel").touch()
                return {"status": "CANCELLING", "run_id": state["run_id"], "scope": scope, "next_action": "Call RunFormal action=status after cleanup."}
            return self._summary(run_dir, state)

    def review(self, property_names: list[str], action: str, reason: str, next_action: str = "", *, run_id=None, scope="full") -> dict:
        """Record bounded batch decisions; deferral preserves UNPROVEN and retry is capped."""
        if action not in {"defer", "retry"} or not reason.strip() or not next_action.strip():
            raise ValueError("review requires defer/retry, a reason, and a concrete next_action")
        if not property_names or len(set(property_names)) != len(property_names):
            raise ValueError("review requires a nonempty unique property_names list")
        if len(reason) > 2000 or len(next_action) > 2000:
            raise ValueError("Review reason and next_action must each be at most 2000 characters")
        _, root, _, _, fingerprint = self._inputs()
        with (root / "control.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            run_dir, state = self._load(root, run_id, scope)
            if not state or state["fingerprint"] != fingerprint:
                raise ValueError("Review requires results for current inputs; call RunFormal action=run.")
            active = state["status"] in ACTIVE_RUNS
            pending_path = run_dir / "review_requests.json"
            pending = read_json(pending_path) if pending_path.is_file() else []
            if active and ((run_dir / "closing").exists() or (run_dir / "cancel").exists()):
                raise ValueError("The batch is finishing; refresh its status before reviewing.")
            pending_names = {row["property"] for row in pending} if active else set()
            decisions = []
            for name in property_names:
                item = state["properties"].get(name)
                if not item or item["result"] in FINAL_RESULTS or item["result"] == "NOT_EXECUTED":
                    raise ValueError(f"Property is missing or already resolved: {name}")
                if name in pending_names:
                    raise ValueError(f"A decision is already pending: {name}")
                if action not in review_actions(item, self.policy):
                    if action == "defer":
                        raise ValueError(f"Only unreviewed budget-exhausted UNPROVEN properties can be deferred: {name}")
                    raise ValueError(f"Retry budget exhausted or property is still running: {name}")
                decisions.append({"property": name, "action": action, "reason": reason.strip(),
                                  "next_action": next_action.strip(), "timestamp": time.time()})
            if active:
                atomic_json(pending_path, pending + decisions)
                return {**self._summary(run_dir, state), "review_pending": True}
            apply_decisions(state, decisions)
            state["status"] = "RUNNING" if action == "retry" else "AWAITING_REVIEW"
            atomic_json(run_dir / "state.json", state)
            write_report(run_dir, state)
            if action == "retry":
                for marker in ("ready", "cancel", "closing", "review_requests.json"):
                    (run_dir / marker).unlink(missing_ok=True)
                self._launch(run_dir, state)
            return self._summary(run_dir, state)

    def _summary(self, run_dir, state) -> dict:
        """Return aggregate progress with a bounded queue and an exact report location."""
        properties = state["properties"]
        policy = ExecutionPolicy(**state.get("policy", {}))
        pending_path = run_dir / "review_requests.json"
        try:
            pending = {row["property"] for row in read_json(pending_path)}
        except FileNotFoundError:
            pending = set()
        queue = [{"property": name, "state": item["state"], "active_s": round(item["execution_elapsed_s"], 2),
                  "depth": item.get("depth"), "engine": item.get("engine"), "raw_status": item.get("raw_status"),
                  "reason": item.get("error") or item.get("reason"), "error_code": item.get("error_code"), "disposition": item.get("disposition")}
                 for name, item in properties.items() if item["result"] == "UNPROVEN"]
        for row in queue:
            item = properties[row["property"]]
            row["actions"] = [] if row["property"] in pending else review_actions(item, policy)
            row["remaining_s"] = max(0, policy.property_cumulative_budget_s - row["active_s"])
            row["attempts"] = len(item["attempts"])
        ready = [row for row in queue if row["state"] == "REVIEW" and row["disposition"] != "DEFERRED"]
        scope = state.get("scope", "full")
        executed = [item for item in properties.values() if item["result"] != "NOT_EXECUTED"]
        resolved = bool(executed) and all(item["result"] in FINAL_RESULTS for item in executed)
        return {"run_id": state["run_id"], "status": state["status"], "scope": scope,
                "selected_properties": state.get("selected_properties", []),
                "input_fingerprint": state["fingerprint"],
                "selected_complete": scope == "selected" and resolved,
                "full_complete": scope == "full" and resolved, "counts": dict(collections.Counter(item["result"] for item in properties.values())),
                "states": dict(collections.Counter(item["state"] for item in properties.values())), "total": len(properties),
                "proof_complete": scope == "full" and resolved,
                "deferred_total": sum(item.get("disposition") == "DEFERRED" for item in properties.values()),
                "deferred_properties": [name for name, item in properties.items() if item.get("disposition") == "DEFERRED"][:20],
                "review_queue": (ready + [row for row in queue if row not in ready])[:20],
                "review_queue_total": len(queue), "needs_review": len(ready),
                "error": state.get("error"), "error_code": state.get("error_code"),
                "report": str((run_dir / "report.md").relative_to(self.workspace)),
                "state_artifact": str((run_dir / "state.json").relative_to(self.workspace)),
                "coverage_artifact": str((run_dir / "inventory" / "avis" / "fanin.rep").relative_to(self.workspace)) if (run_dir / "inventory" / "avis" / "fanin.rep").is_file() else None,
                "checkpoints": state["checkpoints"][-10:], "checkpoint_total": len(state["checkpoints"]),
                "next_action": (
                    "Wait for progress using RunFormal action=status; do not restart active work." if state["status"] in ACTIVE_RUNS else
                    "Preserve the original properties. Inspect the named attempt reports and ask the operator to repair the tool/environment; only retry after repair. Do not replace proof goals to evade an execution error."
                    if state["status"] in {"ERROR", "NEEDS_OPERATOR", "INTERRUPTED", "CANCELLED"} else
                    "Review current results through the optional ext/formal/data Skill or ordinary file tools. RunFormal action=evidence provides original evidence for analysis. For budget-exhausted UNPROVEN targets, record reason and next_action with review; deferred never means proved."
                )}

    def inventory(self, *, run_id=None, scope="full") -> dict:
        """List exact Assert/Cover identities from one enumerated batch."""
        _, _, root = self._paths(create=False)
        _, state = read_run(root, run_id, scope)
        if not state:
            return {"status": "NOT_STARTED", "properties": []}
        return {"run_id": state["run_id"], "scope": scope, "status": state["status"],
                "properties": [{"name": name, "kind": item["kind"], "result": item["result"]}
                               for name, item in state["properties"].items()]}

    def evidence(self, property_names: list[str], *, run_id=None, scope="full", trace_query=None) -> dict:
        """Return bounded original proof witnesses; never invent or minimize trace inputs."""
        if not property_names or len(property_names) > 20 or len(set(property_names)) != len(property_names):
            raise ValueError("evidence requires between 1 and 20 unique exact property_names")
        if trace_query is not None:
            if len(property_names) != 1:
                raise ValueError("A trace query requires one exact property.")
            _, _, root = self._paths(create=False)
            run_dir, state = read_run(root, run_id, scope)
            if not state:
                raise ValueError("Proof batch is unavailable.")
            current = None
            try:
                current = state["fingerprint"] == self.input_fingerprint()
            except (ValueError, OSError):
                pass
            return query_run_trace(self.workspace, run_dir, state, property_names[0], trace_query, current)
        _, root, _, _, fingerprint = self._inputs()
        with (root / "control.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            run_dir, state = self._load(root, run_id, scope)
            if not state or state["fingerprint"] != fingerprint or state["status"] in ACTIVE_RUNS:
                raise ValueError("Evidence requires current stopped inputs; inspect RunFormal status first")
            items = []
            for name in property_names:
                if name not in state["properties"]:
                    raise ValueError(f"Exact property identity not found: {name}")
                item = state["properties"][name]
                evidence = property_evidence(run_dir, state, name, item)
                items.append({"property": name, **evidence,
                              "next_action": "Use the original recorded input and signal observations with the stated specification. The last stored sample is not necessarily the failure cycle; no expected behavior or alternate example has been computed."})
            return {"run_id": state["run_id"], "items": items,
                    "verification_scope": "tool_report_and_original_witness_only; intended specification semantics remain to be reviewed"}

    def check(self) -> tuple[bool, dict]:
        """Gate current evidence without starting a proof or treating a deferred item as Pass."""
        result = self.status()
        ready = result.get("current_inputs") and result["status"] not in ACTIVE_RUNS | {"INTERRUPTED", "ERROR", "NEEDS_OPERATOR", "CANCELLED"} and result.get("total", 0) > 0
        _, _, root = self._paths()
        run_dir, state = self._load(root, result.get("run_id"))
        if ready:
            inventory = parse_properties((run_dir / "inventory" / "console.log").read_text(encoding="utf-8", errors="replace"))
            if set(inventory) != set(state["properties"]):
                ready = False
            for name, item in state["properties"].items():
                if not item["attempts"]:
                    ready = False
                    continue
                attempt = item["attempts"][-1]
                relative = Path(attempt["console"])
                evidence = run_dir / relative
                if relative.is_absolute() or ".." in relative.parts or not evidence.resolve().is_relative_to(run_dir.resolve()):
                    raise ValueError("Invalid Formal evidence path")
                if not evidence.is_file():
                    ready = False
                    continue
                payload = evidence.read_bytes()
                if hashlib.sha256(payload).hexdigest() != attempt.get("console_hash"):
                    ready = False
                block = re.search(r"^UCAGENT_RESULT_BEGIN\r?\n(.*?)^UCAGENT_RESULT_END\r?$", payload.decode("utf-8", errors="replace"), re.MULTILINE | re.DOTALL)
                observed = parse_properties(block.group(1), inventory.get(name, {}).get("kind")).get(name) if block else None
                if item["result"] not in FINAL_RESULTS:
                    if item["state"] != "REVIEW" or item.get("disposition") != "DEFERRED":
                        ready = False
                    if not (observed and observed["result"] == "UNPROVEN") and attempt.get("forced") != "PROOF_TIMEOUT":
                        ready = False
                elif not observed or observed["result"] != item["result"]:
                    ready = False
                else:
                    try:
                        property_evidence(run_dir, state, name, item)
                    except ValueError:
                        ready = False
        if ready:
            self.export_results(expected_run_id=state["run_id"])
            if self._inputs()[-1] != state["fingerprint"]:
                return False, {"error_code": "formal_inputs_changed_during_check", "error": "Formal inputs changed while validating evidence.",
                               "next_action": "Inspect the changed task inputs and run the current revision before completing the stage."}
            return True, result
        return False, {**result, "error_code": "formal_execution_pending", "error": "Current formal results require execution or review.",
                       "next_action": result.get("next_action", "Call RunFormal action=run, then Check.")}

    def export_results(self, *, expected_run_id=None) -> None:
        """Publish only the current stopped full result under the snapshot lock."""
        from formal.skills.lib.formal_tools import load_records, save_records, update_records_run_results

        target, _, root = self._paths()
        with input_lock(target), (root / "control.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            target, root, _, _, fingerprint = self._inputs()
            run_dir, state = self._load(root)
            if (not state or state["fingerprint"] != fingerprint or state["status"] in ACTIVE_RUNS
                    or expected_run_id is not None and state["run_id"] != expected_run_id):
                raise ValueError("Only current, stopped full results can be published")
            parsed = {key: [] for key in ("pass", "trivially_true", "false", "cover_pass", "cover_fail")}
            mapping = {"PROVEN": "pass", "TRIVIALLY_TRUE": "trivially_true", "FALSIFIED": "false", "TRIVIALLY_FALSE": "false", "COVER_REACHED": "cover_pass", "COVER_UNREACHABLE": "cover_fail"}
            lines = []
            for number, (name, item) in enumerate(state["properties"].items(), 1):
                if item["result"] in mapping:
                    parsed[mapping[item["result"]]].append(name)
                status = {"PROVEN": "Pass", "TRIVIALLY_TRUE": "TrivT", "TRIVIALLY_FALSE": "TrivF", "FALSIFIED": "Fail", "COVER_REACHED": "Pass", "COVER_UNREACHABLE": "Fail"}.get(item["result"], "Undec")
                lines.append(f" {number} {name} : {status}\tunknown\t{item['execution_elapsed_s']:.2f}\t(-)")
            log = target / "tests" / "avis.log"
            log.write_text("\n".join(lines) + "\n", encoding="utf-8")
            records = load_records(str(target / ".formal_records.yaml"))
            if records:
                if not records.run_results or records.run_results.run_id != state["run_id"] or records.run_results.log_hash != hashlib.sha256(log.read_bytes()).hexdigest():
                    update_records_run_results(records, parsed, str(log))
                # Rebuild every machine field even if a task writer kept the old run/log IDs.
                records.run_results.assert_failing_properties = parsed["false"]
                records.run_results.cover_failing_properties = parsed["cover_fail"]
                records.run_results.failing_properties = parsed["false"] + parsed["cover_fail"]
                records.run_results.tt_properties = parsed["trivially_true"]
                records.run_results.run_id = state["run_id"]
                records.run_results.input_fingerprint = state["fingerprint"]
                records.run_results.property_kinds = {name: item["kind"] for name, item in state["properties"].items()}
                records.run_results.property_evidence = {name: property_evidence(run_dir, state, name, item)
                                                       for name, item in state["properties"].items() if item["result"] in FINAL_RESULTS}
                records.run_results.stats = {"pass_count": len(parsed["pass"]), "tt_count": len(parsed["trivially_true"]),
                                            "fail_count": len(parsed["false"]), "cover_pass_count": len(parsed["cover_pass"]),
                                            "cover_fail_count": len(parsed["cover_fail"]),
                                            "trivially_false_count": sum(item["result"] == "TRIVIALLY_FALSE" for item in state["properties"].values())}
                save_records(str(target / ".formal_records.yaml"), records)
            coverage = run_dir / "inventory" / "avis" / "fanin.rep"
            if coverage.exists():
                destination = target / "tests" / "avis" / "fanin.rep"
                destination.parent.mkdir(exist_ok=True)
                shutil.copyfile(coverage, destination)

def controller(run_dir: Path) -> None:
    """Own all children, assign fair turns, publish checkpoints, and clean up on exit."""
    deadline = time.monotonic() + 10
    while not (run_dir / "ready").exists():
        if time.monotonic() > deadline:
            return
        time.sleep(0.05)
    state = read_json(run_dir / "state.json")
    policy = ExecutionPolicy(**state["policy"])
    active = []
    inventory_child = None
    inventory_log = None
    inventory_slot = None
    interrupted = False

    def handle_stop(signum, frame):
        """Turn termination signals into bounded controller-owned child cleanup."""
        nonlocal interrupted
        interrupted = True

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)
    setup = run_dir / "inputs" / state["output_dir"] / "tests" / "setup.tcl"
    try:
        if not state["properties"]:
            inventory = run_dir / "inventory"
            inventory.mkdir(exist_ok=True)
            script = inventory / "inventory.tcl"
            script.write_text(f"source {tcl_word(str(setup))}\n"
                              "puts UCAGENT_ASSERT_BEGIN\nshow_prop -only_assert -time -engine -reason\nputs UCAGENT_ASSERT_END\n"
                              "puts UCAGENT_COVER_BEGIN\nshow_prop -only_cover -time -engine -reason\nputs UCAGENT_COVER_END\n"
                              "fanin -cover -list -dump\nexit\n", encoding="utf-8")

            while inventory_slot is None:
                if interrupted or (run_dir / "cancel").exists():
                    state["status"] = "CANCELLED"
                    return
                inventory_slot = take_worker_slot(run_dir.parent, policy.max_active_workers)
                if inventory_slot is None:
                    time.sleep(0.1)
            console = (inventory / "console.log").open("w")
            process = subprocess.Popen([state["executable"], "-f", str(script), "-override", "-work_dir", str(inventory)],
                                       stdout=console, stderr=subprocess.STDOUT, start_new_session=True,
                                       pass_fds=(inventory_slot.fileno(),))
            inventory_child, inventory_log = process, console
            token = process_identity(process.pid)
            state["inventory_process"] = {"pid": process.pid, "identity": token, "members": group_members(process.pid)}
            atomic_json(run_dir / "state.json", state)
            started = time.monotonic()
            member_check = started
            while process.poll() is None:
                if time.monotonic() - member_check >= 1:
                    state["inventory_process"]["members"] = group_members(process.pid)
                    atomic_json(run_dir / "state.json", state)
                    member_check = time.monotonic()
                if interrupted or (run_dir / "cancel").exists() or time.monotonic() - started > policy.setup_timeout_s:
                    stop_process(process.pid, token, policy.stop_grace_s, state["inventory_process"].get("members", []))
                    process.wait()
                    break
                time.sleep(0.1)
            console.close()
            inventory_slot.close()
            state.pop("inventory_process", None)
            content = (inventory / "console.log").read_text(encoding="utf-8", errors="replace")
            if interrupted or (run_dir / "cancel").exists():
                state["status"] = "CANCELLED"
                return
            if process.returncode != 0 or re.search(r"blackboxes\s*:\s*[1-9]|^\s*(?:Error:|Error-|Fatal)", content, re.M):
                state["error_code"] = "formal_tool_compile_error"
                raise ValueError("Formal environment preparation failed; inspect inventory/console.log and repair inputs before retrying.")
            parsed = parse_properties(content)
            if not parsed:
                raise ValueError("No properties were enumerated; inspect inventory/console.log and the generated environment.")
            observed = collections.Counter(name.rsplit(".", 1)[-1] for name in parsed)
            missing = [label for label in state.get("expected_labels", []) if observed[label] != 1]
            if missing:
                raise ValueError(f"Expected checker properties missing or ambiguous in inventory: {missing[:20]}")
            selected = set(state.get("selected_properties", []))
            unknown = sorted(selected - parsed.keys())
            if unknown:
                raise ValueError(f"Unknown or non-Assert/Cover property names: {unknown[:20]}")
            for name, result in parsed.items():
                included = not selected or name in selected
                state["properties"][name] = {**result,
                    "state": "QUEUED_FAST" if included else "NOT_EXECUTED",
                    "result": "UNPROVEN" if included else "NOT_EXECUTED",
                    "execution_elapsed_s": 0.0, "round_elapsed_s": 0.0,
                    "review_round": 1, "attempts": [], "disposition": None}
        state["status"] = "RUNNING"
        started_batch = time.monotonic()
        checkpoint_due = list(sorted(set((policy.first_pass_budget_s, policy.analysis_threshold_s))))
        while True:
            if interrupted or (run_dir / "cancel").exists():
                state["status"] = "CANCELLED"
                break
            now = time.monotonic()
            for worker in list(active):
                now = time.monotonic()
                process = worker["process"]
                item = state["properties"][worker["name"]]
                attempt = item["attempts"][-1]
                if now - worker["member_check"] >= 1:
                    attempt["members"] = group_members(process.pid)
                    worker["member_check"] = now
                with worker["console_path"].open("r", encoding="utf-8", errors="replace") as stream:
                    stream.seek(worker["output_offset"])
                    console = stream.read()
                    worker["output_offset"] = stream.tell()
                console = worker["output_tail"] + console
                worker["output_tail"] = console[-256:]
                if worker["proof_start"] is None and "UCAGENT_PROOF_STARTED" in console:
                    worker["proof_start"] = now
                    marker = re.search(r"^UCAGENT_PROOF_STARTED (\d+)\r?$", console, re.MULTILINE)
                    if marker:
                        lag = max(0.0, time.time() - int(marker.group(1)) / 1000)
                        worker["proof_start"] = max(worker["start"], now - lag)
                    attempt["proof_started_at"] = time.time() - (now - worker["proof_start"])
                elapsed = now - worker["proof_start"] if worker["proof_start"] is not None else 0.0
                forced = None
                if process.poll() is None:
                    if worker["proof_start"] is None and now - worker["start"] >= policy.setup_timeout_s:
                        forced = "SETUP_TIMEOUT"
                    elif worker["proof_start"] is not None and elapsed >= worker["budget"] + policy.stop_grace_s:
                        forced = "PROOF_TIMEOUT"
                    if forced:
                        stop_process(process.pid, attempt["identity"], policy.stop_grace_s, attempt.get("members", []))
                        process.wait()
                    else:
                        item["execution_elapsed_s"] = worker["base_elapsed"] + elapsed
                        continue
                worker["log"].close()
                worker["slot"].close()
                console = worker["console_path"].read_text(encoding="utf-8", errors="replace")
                result_block = re.search(r"^UCAGENT_RESULT_BEGIN\r?\n(.*?)^UCAGENT_RESULT_END\r?$", console, re.MULTILINE | re.DOTALL)
                final, parse_error = None, None
                if result_block:
                    try:
                        final = parse_properties(result_block.group(1), item["kind"]).get(worker["name"])
                    except ValueError as exc:
                        parse_error = str(exc)
                # Count active wall time, not queue time or summed parallel CPU times.
                charged = elapsed
                markers = re.search(r"^UCAGENT_PROOF_STARTED (\d+)\r?$.*?^UCAGENT_PROOF_FINISHED (\d+)\r?$", console, re.MULTILINE | re.DOTALL)
                if markers:
                    duration = (int(markers.group(2)) - int(markers.group(1))) / 1000
                    if 0 <= duration <= now - worker["start"] + 1:
                        charged = duration
                if worker["proof_start"] is None:
                    charged = 0.0
                item["execution_elapsed_s"] = worker["base_elapsed"] + charged
                item["round_elapsed_s"] += charged
                witness = worker["console_path"].parent / "avis" / worker["name"] / (worker["name"] + ".tb.v")
                if not witness.resolve().is_relative_to(worker["console_path"].parent.resolve()) or witness.is_symlink():
                    parse_error = "Invalid tool witness path"
                    witness_hash = None
                else:
                    witness_hash = hashlib.sha256(witness.read_bytes()).hexdigest() if witness.is_file() else None
                trace = witness.with_name(worker["name"] + ".vcd")
                if not trace.resolve().is_relative_to(worker["console_path"].parent.resolve()) or trace.is_symlink():
                    parse_error = "Invalid original observation path"
                    trace_hash = None
                else:
                    trace_hash = hashlib.sha256(trace.read_bytes()).hexdigest() if trace.is_file() else None
                attempt.update({"running": False, "ended_at": time.time(), "active_s": charged,
                                "trace_hash": trace_hash,
                                "witness_hash": witness_hash,
                                "console_hash": hashlib.sha256(worker["console_path"].read_bytes()).hexdigest(),
                                "returncode": process.returncode, "forced": forced})
                valid = (final and final["raw_status"].split("(")[0].strip() != "NotRun"
                         and "UCAGENT_PROOF_FINISHED" in console and process.returncode == 0
                         and not re.search(r"^\s*(?:Error:|Error-|Fatal)", console, re.MULTILINE))
                if parse_error:
                    item["state"] = "ERROR"
                    item["error_code"] = "formal_tool_result_unsupported"
                    item["error"] = parse_error
                elif valid and final["result"] in FINAL_RESULTS:
                    item.update(final)
                    item["state"] = "RESOLVED"
                    item["error"] = None
                elif valid or forced == "PROOF_TIMEOUT":
                    if valid:
                        item.update(final)
                    item["result"] = "UNPROVEN"
                    item["state"] = "QUEUED_SLOW" if worker["lane"] == "fast" and item["execution_elapsed_s"] < policy.property_cumulative_budget_s else "REVIEW"
                    item["error"] = None
                else:
                    item["state"] = "ERROR"
                    item["error_code"] = "formal_attempt_failed"
                    item["error"] = "Attempt failed or did not produce a complete property report; inspect its console.log."
                active.remove(worker)
                snapshot(run_dir, state, f"property-{worker['index']}-{worker['lane']}")
            while len(active) < policy.max_active_workers:
                name = choose_next(state["properties"], active, policy)
                if name is None:
                    break
                item = state["properties"][name]
                lane = "fast" if item["state"] == "QUEUED_FAST" else "slow"
                limit = policy.first_pass_budget_s if lane == "fast" else policy.analysis_threshold_s - item["round_elapsed_s"]
                budget = min(limit, policy.property_cumulative_budget_s - item["execution_elapsed_s"])
                if budget <= 0:
                    item["state"] = "REVIEW"
                    continue
                slot = take_worker_slot(run_dir.parent, policy.max_active_workers)
                if slot is None:
                    break
                index = sum(len(prop["attempts"]) for prop in state["properties"].values()) + 1
                directory = run_dir / "attempts" / f"{index:06d}"
                directory.mkdir(parents=True)
                script = directory / "prove.tcl"
                script.write_text(f"source {tcl_word(str(setup))}\nset_opt -timeout {max(1, math.ceil(budget))}s\nset_opt -bfd on\n"
                                  f"puts [list UCAGENT_PROOF_STARTED [clock milliseconds]]\nflush stdout\nprove {tcl_word(name)}\n"
                                  "puts [list UCAGENT_PROOF_FINISHED [clock milliseconds]]\nflush stdout\nputs UCAGENT_RESULT_BEGIN\nshow_prop -time -engine -reason\nputs UCAGENT_RESULT_END\nexit\n", encoding="utf-8")
                console_path = directory / "console.log"
                log = console_path.open("w")
                process = subprocess.Popen([state["executable"], "-f", str(script), "-override", "-work_dir", str(directory)],
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                           pass_fds=(slot.fileno(),))
                item["attempts"].append({"pid": process.pid, "identity": process_identity(process.pid), "running": True,
                                         "members": group_members(process.pid),
                                         "lane": lane, "budget_s": budget, "started_at": time.time(),
                                         "console": str(console_path.relative_to(run_dir))})
                item["state"] = "RUNNING_FAST" if lane == "fast" else "RUNNING_SLOW"
                active.append({"name": name, "lane": lane, "index": index, "process": process, "log": log,
                               "console_path": console_path, "output_offset": 0, "output_tail": "", "slot": slot,
                               "start": time.monotonic(), "member_check": time.monotonic(), "proof_start": None,
                               "budget": budget, "base_elapsed": item["execution_elapsed_s"]})
                atomic_json(run_dir / "state.json", state)
            with (run_dir.parent / "control.lock").open("a+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                requests = run_dir / "review_requests.json"
                if requests.is_file():
                    apply_decisions(state, read_json(requests))
                    atomic_json(run_dir / "state.json", state)
                    requests.unlink()
                if not active and not any(item["state"].startswith("QUEUED") for item in state["properties"].values()):
                    (run_dir / "closing").touch()
                    if any(item["state"] == "ERROR" for item in state["properties"].values()):
                        state["status"] = "NEEDS_OPERATOR"
                        state["error"] = "Some property attempts need tool or environment repair; preserve the verification goals."
                    else:
                        unresolved = any(item["result"] not in FINAL_RESULTS | {"NOT_EXECUTED"}
                                         for item in state["properties"].values())
                        state["status"] = "AWAITING_REVIEW" if unresolved else "COMPLETED"
                    break
            while checkpoint_due and now - started_batch >= checkpoint_due[0]:
                snapshot(run_dir, state, f"batch-{checkpoint_due.pop(0)}s")
            atomic_json(run_dir / "state.json", state)
            write_report(run_dir, state)
            time.sleep(0.1)
    except Exception as exc:
        state["status"] = "ERROR"
        state.setdefault("error_code", "formal_preparation_or_controller_failed")
        state["error"] = str(exc)
    finally:
        with (run_dir.parent / "control.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            (run_dir / "closing").touch()
            (run_dir / "review_requests.json").unlink(missing_ok=True)
        if inventory_child is not None:
            inventory_record = state.get("inventory_process", {})
            stop_process(inventory_child.pid, inventory_record.get("identity", ""), policy.stop_grace_s, inventory_record.get("members", []))
            inventory_child.wait()
        if inventory_slot is not None:
            inventory_slot.close()
        if inventory_log is not None:
            inventory_log.close()
        for worker in active:
            attempt = state["properties"][worker["name"]]["attempts"][-1]
            stop_process(worker["process"].pid, attempt["identity"], policy.stop_grace_s, attempt.get("members", []))
            worker["process"].wait()
            worker["log"].close()
            worker["slot"].close()
            attempt["running"] = False
            state["properties"][worker["name"]]["state"] = "CANCELLED" if state["status"] == "CANCELLED" else "ERROR"
        for item in state["properties"].values():
            if item["state"].startswith("QUEUED"):
                item["state"] = "NOT_EXECUTED"
                item["error_code"] = "formal_batch_stopped"
                item["error"] = "The batch stopped before this property was executed; restore execution before review."
        snapshot(run_dir, state, "final")
        atomic_json(run_dir / "state.json", state)
        write_report(run_dir, state)


def snapshot(run_dir: Path, state: dict, label: str) -> None:
    """Persist immutable observations and retain their exact sampling timestamps."""
    directory = run_dir / "snapshots"
    directory.mkdir(exist_ok=True)
    name = f"{len(state['checkpoints']):04d}-{label}.json"
    atomic_json(directory / name, {"sampled_at": time.time(), "label": label, "properties": state["properties"]})
    state["checkpoints"].append(str(Path("snapshots") / name))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, required=True)
    controller(parser.parse_args().worker.resolve())
