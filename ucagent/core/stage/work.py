"""A durable list of independent work inside an opt-in verification workflow."""

import json
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
        scoped = [(i, stage.name) for i, stage in enumerate(stages)
                  if not stage.is_skipped() and (i == index or stage.is_reached())]
        # Work on the current stage first, then any previously reached stages.
        for i, name in sorted(scoped, key=lambda stage: (stage[0] != index, stage[0])):
            data = self._read(i, name)
            for item_id, item in data["items"].items():
                state = item["state"]
                states.append((i, item_id, state))
                if state in rows:
                    rows[state].append({"stage": i, "id": item_id, **item})
        # A review is valid only for this inventory. Editing prose does not count as work progress.
        states.sort()
        review_index = index if index < len(stages) else max((i for i, _ in scoped), default=None)
        review = self._read(review_index, stages[review_index].name)["review"] if review_index is not None else None
        audited = bool(review and review["states"] == [list(state) for state in states])
        return {**rows, "reviewed": audited, "states": states, "review_index": review_index}

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
            data["review"] = {"evidence": evidence, "states": [list(state) for state in view["states"]]}
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
            return f"工作流 {name} 未能核对交接证据。先检查现有证据和运行日志；不要原样重跑或改为等人工。"
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
            return None, (f"继续本工作流的待办：阶段 {item['stage']} / {item['id']}。{item['detail']}。"
                          "如果在别的已达阶段，先用 GoToStage；执行、核对证据，再更新 StageWork。"
                          "不要重做已完成项，也不要为另一个缺规格的问题停下。")
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
                          + "不要重复刚才的检查或原样重跑。先用 StageWork(show) 核对剩余事项，"
                          "从现有证据找一个能独立处理的问题并登记为 ready，能做就直接做。"
                          "确实需要负责人提供规格、权限或决定的，写清缺什么和影响。"
                          "已核对全部剩余范围后用 StageWork(review) 记录证据；没有新办法就保留未完成。")
        return None, blocker
