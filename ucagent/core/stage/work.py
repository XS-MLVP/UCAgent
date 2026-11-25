"""A durable list of independent work inside an opt-in verification workflow."""

import json
import hashlib
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from ucagent.util.log import info, warning


class StageWork:
    """Track work without approving stages or changing verification results."""

    def __init__(self, workspace, dut):
        if not dut or Path(dut).name != dut or dut in {".", ".."}:
            raise ValueError("StageWork requires a single DUT name, not a path")
        self.root = Path(workspace) / ".ucagent" / "stage-work" / dut

    def _read(self, index, name):
        path = self.root / f"{index:02}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"stage": name, "items": {}, "review": None}
        if data["stage"] != name:
            raise ValueError(f"Stage work file does not match the current workflow: {path}")
        return data

    def _save(self, index, data):
        self.root.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.root, delete=False) as output:
            path = Path(output.name)
            try:
                json.dump(data, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.close()
                path.replace(self.root / f"{index:02}.json")
            finally:
                path.unlink(missing_ok=True)

    def view(self, stages, index):
        """Include unresolved items from reached stages; never repeat completed work in tips."""
        rows = {state: [] for state in ("ready", "human", "stalled")}
        states = []
        inventory = []
        scoped = [(i, stage.name) for i, stage in enumerate(stages)
                  if not stage.is_skipped() and (i == index or stage.is_reached())]
        # Work on the current stage first, then any previously reached stages.
        for i, name in sorted(scoped, key=lambda stage: (stage[0] != index, stage[0])):
            data = self._read(i, name)
            for item_id, item in data["items"].items():
                state = item["state"]
                states.append((i, item_id, state))
                inventory.append((i, item_id, item))
                if state in rows:
                    rows[state].append({"stage": i, "id": item_id, **item})
        # Review covers content across stages; progress still compares only item states.
        states.sort()
        fingerprint = hashlib.sha256(json.dumps(sorted(inventory), sort_keys=True,
                                               ensure_ascii=False).encode("utf-8")).hexdigest()
        review_index = index if index < len(stages) else max((i for i, _ in scoped), default=None)
        review = self._read(review_index, stages[review_index].name)["review"] if review_index is not None else None
        audited = bool(review and review.get("fingerprint") == fingerprint)
        return {**rows, "reviewed": audited, "states": states, "review_index": review_index,
                "fingerprint": fingerprint}

    @staticmethod
    def public(view):
        return {key: view[key] for key in ("ready", "human", "stalled", "reviewed")}

    def update(self, stages, index, action, item_id, detail, evidence):
        view = self.view(stages, index)
        if action == "show":
            return self.public(view)
        index = view["review_index"]
        if index is None:
            raise ValueError("There is no reached stage in scope.")
        if not evidence.strip():
            raise ValueError("Give concrete evidence: spec, Checker result, run, waveform or an exact missing input.")
        data = self._read(index, stages[index].name)
        if action == "review":
            if view["ready"] or view["stalled"]:
                raise ValueError("Unresolved AI work remains. Continue it or record its actual dependency; do not sign off the list.")
            data["review"] = {"evidence": evidence, "fingerprint": view["fingerprint"]}
        else:
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", item_id):
                raise ValueError("Use a stable item id (lowercase letters, digits, '.', '_' or '-').")
            previous = data["items"].get(item_id)
            if action == "ready" and previous and previous["state"] != "ready" and previous["evidence"] == evidence:
                raise ValueError("Reopen an item only with new evidence that enables a different next step.")
            if action == "human" and not detail.strip():
                raise ValueError("Name who is needed, exactly what they must supply/decide, and why.")
            if action == "done" and not previous:
                raise ValueError("Only a recorded item can be marked done.")
            if action == "ready" and not detail.strip():
                raise ValueError("State the next action and what evidence would finish it.")
            if previous and previous["state"] == "done" and action != "ready":
                raise ValueError("Completed work stays closed unless reopened with new evidence.")
            data["items"][item_id] = {"state": action, "detail": detail or previous["detail"], "evidence": evidence}
            if data["items"][item_id] != previous:
                data["review"] = None
        self._save(index, data)
        return self.public(self.view(stages, index))

    def park(self, stages, item, evidence):
        """Stop repeating this item, not the other items or the stage checker."""
        index = item["stage"]
        data = self._read(index, stages[index].name)
        data["items"][item["id"]].update(state="stalled", stalled_because=evidence)
        data["review"] = None
        self._save(index, data)


def stage_work_handoff_blocker(manager):
    """Ask active workflows to veto handoff without mutating work or check results."""
    for hook in getattr(manager, "runtime_hooks", ()):
        check = getattr(hook, "stage_work_handoff_blocker", None)
        if not callable(check):
            continue
        try:
            note = check(manager)
            if note is None:
                continue
            if not isinstance(note, str) or not note.strip():
                raise ValueError("Expected None or a nonempty continuation instruction")
            info(f"StageWork handoff deferred by {type(hook).__name__} at stage {manager.stage_index}")
            return note.strip()[:2000]
        except Exception as error:
            name = type(hook).__name__
            warning(f"StageWork handoff check {name} failed ({type(error).__name__})")
            return (f"Workflow {name} could not verify the handoff evidence. Check the current "
                    "evidence and run logs first; do not rerun unchanged or switch to waiting for a human.")
    return None


class StageWorkLoop:
    """Choose the next in-process round after the verification model yields."""

    def __init__(self, manager, limit):
        self.manager = manager
        self.work = manager.stage_work
        self.limit = max(3, limit)
        self.quiet = 0
        self.recovery = False

    def before_round(self):
        index = self.manager.stage_index
        return index, self.work.view(self.manager.stages, index)

    def after_round(self, before, stalled, validated):
        index, old = before
        index_now, new = self.before_round()
        check = self.manager.last_check_info
        failure = check.get("failure_summary") or {}
        diagnostic = tuple(str(failure.get(k, "")) for k in ("error_code", "location", "error"))
        # Tool calls and prose edits do not buy extra rounds.
        if (index != index_now or old["states"] != new["states"] or old["reviewed"] != new["reviewed"]
                or validated and check.get("progress_summary")):
            self.quiet = 0
            self.recovery = False
        else:
            self.quiet += 1
        exhausted = self.quiet >= self.limit or stalled and self.quiet > 0
        ready = new["ready"]
        if exhausted and ready:
            item = ready.pop(0)
            self.work.park(self.manager.stages, item, "No verified progress in consecutive rounds; "
                           + (" / ".join(value for value in diagnostic if value)[:1500] or "no Checker progress"))
            self.quiet = 0
            self.recovery = False
        if ready:
            item = ready[0]
            return None, (f"Continue the pending StageWork item: stage {item['stage']} / {item['id']}. "
                          f"{item['detail']}. If it belongs to another reached stage, call GoToStage first; "
                          "execute, verify the evidence, then update StageWork. Do not redo completed items, "
                          "and do not stop for a different missing-specification problem.")
        blocker = None
        if new["reviewed"] and not new["stalled"] and (
                index_now >= len(self.manager.stages) or new["human"] and (
                    exhausted or check.get("check_pass") is False and failure.get("stage_index") == index_now)):
            blocker = stage_work_handoff_blocker(self.manager)
            if blocker is None and new["human"]:
                return "human_input_required", None
        if exhausted:
            if self.recovery:
                return "checker_stall", None
            self.recovery = True
            self.quiet = 0
            return None, ((blocker + "\n" if blocker else "")
                          + "Do not repeat the previous check or rerun unchanged. Use StageWork(show) to "
                          "review the remaining items first, find one problem that can be handled independently "
                          "from the current evidence and mark it ready; if it can be done, do it. For items that "
                          "truly need an owner-supplied specification, permission, or decision, state exactly "
                          "what is missing and its impact. After reviewing the full remaining scope, record the "
                          "evidence with StageWork(review); if there is no new approach, keep the work incomplete.")
        return None, blocker
