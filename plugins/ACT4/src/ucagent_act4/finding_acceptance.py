"""Bind generation work to audited findings and inspect behavior within individual native testcases."""

from fnmatch import fnmatchcase
import hashlib
import json
from pathlib import Path
import re

import yaml

from .run_config import run_settings
from .xiangshan_bundle import safe_path


def instruction_sequence(source: str, label: str, steps: list[str]) -> bool:
    """Match ordered instruction/macro lines in one labeled block, never labels, data, or comments."""
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    lines = []
    guards = {}
    active = []
    macro_depth = 0
    for number, raw in enumerate(source.replace("\\\n", " ").splitlines()):
        directive = re.match(r"^\s*#\s*(if|ifdef|ifndef|else|elif|endif)\b(.*)", raw)
        if directive:
            keyword, expr = directive.groups()
            literal = expr.split("//")[0].strip().strip("() ")
            if keyword.startswith("if"):
                guards[number] = 0
                active.append((number, keyword == "if" and literal == "1", keyword == "if" and literal == "0"))
            elif active:
                group, taken, _ = active.pop()
                if keyword == "endif":
                    del guards[group]
                else:
                    guards[group] += 1
                    active.append((group, taken or keyword == "else" or literal == "1", taken or (keyword == "elif" and literal == "0")))
            continue
        if not any(disabled for _, _, disabled in active):
            line = raw.split("#", 1)[0].split("//", 1)[0].strip()
            if re.match(r"^\.macro\b", line):
                macro_depth += 1
            elif re.match(r"^\.endm\b", line):
                macro_depth = max(0, macro_depth - 1)
            elif not macro_depth and line:
                lines.append((line, guards.copy()))
    starts = [index for index, (line, _) in enumerate(lines) if line == label + ":"]
    if len(starts) != 1:
        return False
    states = {(0, tuple(lines[starts[0]][1].items()))}
    for line, conditions in lines[starts[0] + 1:]:
        if re.match(r"^[\w.$]+:", line) or re.match(r"^\.(?:section|pushsection|popsection|data|text|endm)\b", line):
            break
        states = {(index, tuple((group, arm) for group, arm in branch if group in conditions)) for index, branch in states}
        for index, branch in tuple(states):
            if not line.startswith(".") and all(conditions[group] == arm for group, arm in branch) and fnmatchcase(" ".join(line.split()), steps[index]):
                if index + 1 == len(steps):
                    return True
                states.add((index + 1, tuple(conditions.items())))
    return False


def check_finding_plan(checker, plan: dict, review_dir: str, verify: bool, freeze: bool) -> tuple[dict, dict]:
    """Freeze per-finding acceptance at plan completion and recheck the current native sources thereafter."""
    workspace = Path(checker.workspace).resolve()
    review = safe_path(workspace, review_dir)
    snapshot = safe_path(review, "review-accepted.json")
    state = checker.smanager_get_value(f"act4_review:{review_dir}:{checker.suite}", {})
    content = snapshot.read_bytes() if snapshot.is_file() else b""
    if not content or hashlib.sha256(content).hexdigest() != state.get("audit_snapshot"):
        raise ValueError("Use the accepted audit before planning finding checks")
    findings = {item["id"] for item in json.loads(content)["review"]["findings"] if item["classification"] != "not_a_defect"}
    contracts = plan.get("finding_checks")
    if not isinstance(contracts, dict) or set(contracts) != set(findings):
        raise ValueError(f"finding_checks must cover the exact accepted non-dismissed finding IDs: {sorted(findings)}")
    items = {item["id"]: item for item in plan["items"]}
    basis = {}
    hashes = {}
    sources = {}
    dedicated = set()
    checks = {}
    native = None
    if verify and contracts:
        native = yaml.safe_load(safe_path(review.parent, "asset_contract.yaml").read_bytes())
        if not isinstance(native, dict) or native.get("suite") != checker.suite:
            raise ValueError("Verify finding checks against this suite's native asset_contract.yaml")
    partial = (run_settings(getattr(checker, "cfg", None)) or {}).get("accepted_partial_findings", [])
    unmet = {}
    for identity, contract in contracts.items():
        if not isinstance(contract, dict) or set(contract) != {"item", "kind", "configs", "cases"}:
            raise ValueError(f"{identity}: specify item, kind, configs and cases")
        item = items.get(contract["item"])
        kind, cases, configs = contract["kind"], contract["cases"], contract["configs"]
        if not item or kind not in {"behavior", "artifact", "execution"} or not isinstance(cases, list) or (kind == "behavior") != bool(cases):
            raise ValueError(f"{identity}: bind an existing plan item and supply same-case witnesses for behavior only")
        if (item["area"] in {"stimulus", "observation", "generator"} and item["action"] == "generate" and kind != "behavior"):
            raise ValueError(f"{identity}: generated stimulus or observation requires a behavioral witness")
        if (not isinstance(configs, list) or not all(isinstance(name, str) and re.fullmatch(r"config/[\w-]+/[\w.-]+/test_config\.yaml", name) for name in configs)
                or len(set(configs)) != len(configs) or (not configs and kind != "artifact")):
            raise ValueError(f"{identity}: name the applicable configurations")
        if native is not None and set(configs) - set(native.get("validation_configs", [])):
            raise ValueError(f"{identity}: configuration is not in asset_contract.validation_configs: {configs}")
        if item["action"] not in {"reuse", "generate", "external_input"} or (kind == "behavior" and item["action"] == "external_input"):
            raise ValueError(f"{identity}: do not exclude locally generatable behavior")
        if kind != "behavior":
            if contract["item"] in dedicated:
                raise ValueError(f"{identity}: use a dedicated {kind} acceptance item and check its specific result")
            dedicated.add(contract["item"])
        basis[identity] = {"contract": contract, "item": {key: item[key] for key in ("area", "action", "scope")}}
        if kind != "behavior":
            checks[identity] = sorted({json.dumps(command, sort_keys=True) for command in item["checks"]})
        for case in cases:
            if not isinstance(case, dict) or set(case) != {"source", "label", "stimulus", "observation"}:
                raise ValueError(f"{identity}: case requires source, label, stimulus and observation")
            path = safe_path(workspace, case["source"])
            label = case["label"]
            if not path.is_relative_to(workspace / "riscv-arch-test/tests") or path.suffix != ".S" or not isinstance(label, str) or not re.fullmatch(r"[A-Za-z_.$][\w.$]*", label):
                raise ValueError(f"{identity}: select a native generated tests/*.S file and exact testcase label")
            if native is not None and path.parent.name not in native.get("native_suites", [checker.suite]):
                raise ValueError(f"{identity}: select a test belonging to an accepted native suite")
            for field in ("stimulus", "observation"):
                if not isinstance(case[field], list) or not case[field] or not all(isinstance(step, str) and re.fullmatch(r"[A-Za-z_][\w.]*([ (][^:#\n]*)?", step) for step in case[field]):
                    raise ValueError(f"{identity}: {field} needs ordered mnemonic or macro patterns with literal operation names")
            if verify:
                if path not in sources:
                    if not path.is_file():
                        unmet.setdefault(identity, f"Regenerate missing {case['source']}")
                        continue
                    content = path.read_bytes()
                    sources[path] = content.decode("utf-8")
                    hashes[case["source"]] = hashlib.sha256(content).hexdigest()
                steps = case["stimulus"] + case["observation"]
                if not instruction_sequence(sources[path], label, steps):
                    unmet.setdefault(identity, f"Repair the generator and regenerate {case['source']}:{label}; expected in order: {steps}")
    key = f"act4_finding_plan:{review_dir}"
    signature = hashlib.sha256(json.dumps([state["audit_snapshot"], basis], sort_keys=True).encode()).hexdigest()
    frozen = checker.smanager_get_value(key, None)
    if (verify or frozen is not None) and (not frozen or frozen["digest"] != signature):
        raise ValueError("Finding acceptance changed after planning; restore the accepted criteria before verification")
    if frozen and any(set(required) - set(checks[identity]) for identity, required in frozen["checks"].items()):
        raise ValueError("Restore the accepted artifact/execution checks; add new checks without removing the originals")
    if freeze and not frozen:
        checker.smanager_set_value(key, {"digest": signature, "path": checker.plan_file, "checks": checks})
    if unmet:
        unresolved = set(unmet) - set(partial)
        if unresolved:
            raise ValueError("; ".join(f"{identity}: {unmet[identity]}" for identity in sorted(unresolved)[:12]))
    return hashes, unmet


def check_finding_closure(findings: list[dict], missing: dict) -> None:
    """Allow a missing witness only for an explicitly open disposition, never fixed or dismissed."""
    pending = {item["id"] for item in findings if item["status"] in {"deferred", "not_fixed"}}
    if set(missing) - pending:
        raise ValueError(f"Missing behavioral witnesses cannot be reported as closed: {sorted(set(missing) - pending)}")


def finding_outcome(findings: list[dict]) -> dict:
    """Summarize accepted dispositions without interpreting successful execution as complete scope."""
    pending = [item for item in findings if item["status"] in {"deferred", "not_fixed"}]
    external = [item["id"] for item in pending if item["blocker"]["stop_reason"] == "external_dependency"]
    return {"finding_scope": "partial" if pending else "complete", "local_pending": [item["id"] for item in pending if item["id"] not in external],
            "external_pending": external, "fixed": sum(item["status"] == "fixed" for item in findings)}
