"""Plan-bound SVA templates, bounded first attempts and a distinct slow-proof worklist."""

import hashlib
import json
import math
import re
import time

from .skills.lib.formal_tools import _ck_to_sv_names


CASE_COUNT = 10
WALL_SECONDS = 20 * 60
IMPLEMENT = "implement_formal_case_batches"
COVERAGE = "coverage_analysis_and_optimization"
SLOW = "slow_property_review"


def case_templates(records, plan):
    """Derive non-executable templates from the accepted plan in stable FC order."""
    templates = []
    for group in records.spec.function_groups:
        for fc in sorted(group.functions, key=lambda f: f.review_order or math.inf):
            for ck in fc.check_points:
                if ck.id not in plan:
                    continue
                intent = plan[ck.id]
                symbol, label, kind = _ck_to_sv_names(ck.id, ck.style)
                declaration = f"property {symbol};\n  [LLM-TODO]\nendproperty\n{label}: {kind} property ({symbol});"
                templates.append({"ck_id": ck.id, "fg_id": group.id, "fc_id": fc.id,
                                  "style": ck.style, "requirement": intent["description"],
                                  "source": f"formal_runs/plan_scope.json#/checkpoints/{ck.id}",
                                  "parent_ck_id": ck.parent_ck_id,
                                  "sva_label": label, "sva_template": declaration,
                                  "sva_body": "[LLM-TODO]"})
    if set(plan) != {t["ck_id"] for t in templates}:
        raise ValueError("The current CK list must include every accepted Stage 4 template.")
    return {"dut": records.dut, "case_count": CASE_COUNT, "templates": templates}


def case_binding_context(workspace, output, dut, spec, rows):
    """Resolve literal identifiers named by this planning page, once per distinct signal."""
    from .interface import inspect_interface
    from .skills.lib.formal_tools import build_whitebox_signal_context, whitebox_decl_to_input_decl

    if not rows:
        return {}
    interface = inspect_interface(str(workspace), output, dut, spec.get("parameters"), include_signals=True)
    declared = {s["name"]: whitebox_decl_to_input_decl(s["declaration"]).split()
                for s in build_whitebox_signal_context(spec.get("whitebox_signals"))}
    by_name = {s["name"]: s for s in [*interface["signals"], *interface["ports"]]}
    used = {}
    for row in rows:
        requirement = (row.get("template") or {}).get("requirement") or row["description"]
        identifiers = re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", requirement)
        names = list(dict.fromkeys(name for name in identifiers if name in by_name))
        if names:
            row["named_signals"] = names
            used.update({name: by_name[name] for name in names})
    bindings = []
    for name, symbol in list(used.items())[:32]:
        info = {key: symbol[key] for key in ("name", "width", "source", "line") if key in symbol}
        if "direction" in symbol:
            info["direction"] = symbol["direction"]
        else:
            declaration = symbol["whitebox_declaration"]
            info["direction"] = "internal"
            info["declared_in_checker"] = bool(declaration and declared.get(name) == whitebox_decl_to_input_decl(declaration).split())
        bindings.append(info)
    return {"items": bindings, "total": len(used), "omitted": len(used) - len(bindings)}


def case_page(batches, templates):
    """Retain each ten-CK page until every member has a current disposition."""
    pending = {}
    for fc in batches:
        for key in ("unimplemented_ck_ids", "ready_ck_ids"):
            pending.update({ck: (key, fc["fc_id"]) for ck in fc[key]})
        for key in ("needs_review", "slow_review"):
            pending.update({row["ck_id"]: (key, fc["fc_id"]) for row in fc[key]})
    order = [t["ck_id"] for t in templates if t["style"].lower() != "assume"]
    planned = set(order)
    order.extend(ck for ck in pending if ck not in planned)
    for start in range(0, len(order), CASE_COUNT):
        page = [ck for ck in order[start:start + CASE_COUNT] if ck in pending]
        if page:
            return {"page": start // CASE_COUNT + 1, "ck_ids": page,
                    "unimplemented_ck_ids": [ck for ck in page if pending[ck][0] == "unimplemented_ck_ids"],
                    "ready_ck_ids": [ck for ck in page if pending[ck][0] == "ready_ck_ids"],
                    "review_ck_ids": [ck for ck in page if pending[ck][0] == "needs_review"],
                    "fc_ids": list(dict.fromkeys(pending[ck][1] for ck in page))}
    return {"ck_ids": []}


def next_window(state, now):
    """Advance to a new wall-clock window only after all active attempts have stopped."""
    props = state["properties"]
    windows = state.setdefault("case_windows", [])
    earlier = windows[-1] if windows else None
    if earlier and "ended_at" not in earlier:
        names = earlier["properties"]
        active = any(props[n]["state"].startswith("RUNNING") for n in names)
        queued = any(props[n]["state"].startswith("QUEUED") for n in names)
        if active or queued and now < earlier["proof_deadline"]:
            return earlier
        earlier.update(ended_at=now, reason="wall_limit" if queued or now >= earlier["deadline"] else "finished")
    names = [name for name, item in props.items() if item["state"].startswith("QUEUED")][:CASE_COUNT]
    if not names:
        return None
    start = now if windows else state["created_at"]
    policy = state.get("policy", {})
    cleanup = min(WALL_SECONDS / 4, 1 + policy.get("max_active_workers", 1) * (1 + policy.get("stop_grace_s", 10)))
    window = {"properties": names, "started_at": start, "deadline": start + WALL_SECONDS,
              "proof_deadline": start + WALL_SECONDS - cleanup}
    windows.append(window)
    return window


def record_timeout(state, name, item):
    """Carry only the unresolved status and a verifiable origin into slow-property review."""
    attempt = item["attempts"][-1]
    decision = {"property": name, "action": "defer", "origin": "first_attempt_timeout",
                "reason": f"Unresolved after a managed proof attempt ({attempt['active_s']:.2f} solver seconds).",
                "next_action": "Review the original target, environment and strategy in Stage 8.",
                "timestamp": time.time()}
    state["decisions"].append(decision)
    item.update(state="REVIEW", result="UNPROVEN", disposition="DEFERRED")


def valid_carried_gap(root, state, name):
    """Recheck the sealed source of a scheduling gap without importing an old proof verdict."""
    ref = state.get("prior_local_deferrals", {}).get(name) or {}
    rid = ref.get("run_id", "")
    if not re.fullmatch(r"[0-9a-f]{32}", rid):
        return False
    try:
        src = root / rid
        old = json.loads((src / "state.json").read_bytes())
        item = old["properties"][name]
        attempt = item["attempts"][-1]
        log = src / attempt["console"]
        if (src.is_symlink() or (src / "state.json").is_symlink() or log.is_symlink()
                or not log.resolve().is_relative_to(src.resolve()) or not log.is_file()):
            return False
        label = name.rsplit(".", 1)[-1]
        def target(batch):
            spec = batch["semantic_inputs"]["spec"]
            matches = [(g["id"], f["id"], ck) for g in spec["function_groups"] for f in g["functions"]
                       for ck in f["check_points"] if _ck_to_sv_names(ck["id"], ck["style"])[1] == label]
            return matches[0] if len(matches) == 1 else None
        text = log.read_bytes()
        from .execution import parse_properties
        block = re.search(rb"^UCAGENT_RESULT_BEGIN\r?\n(.*?)^UCAGENT_RESULT_END\r?$", text, re.M | re.S)
        observed = parse_properties(block[1].decode(errors="replace"), item["kind"]).get(name) if block else None
        attempted = (attempt.get("forced") == "PROOF_TIMEOUT" or
                     observed and observed["result"] == "UNPROVEN" and not observed["raw_status"].startswith("NotRun"))
        return bool(old["run_id"] == rid and old["fingerprint"] == ref["input_fingerprint"]
                    and old["batch_context"] == state["batch_context"] and target(old) and target(old) == target(state)
                    and item["result"] == "UNPROVEN" and item["disposition"] == "DEFERRED"
                    and attempted and attempt.get("proof_started_at") is not None and not attempt.get("running")
                    and hashlib.sha256(text).hexdigest() == ref["report_sha256"] == attempt["console_hash"])
    except (KeyError, IndexError, OSError, ValueError, TypeError):
        return False
