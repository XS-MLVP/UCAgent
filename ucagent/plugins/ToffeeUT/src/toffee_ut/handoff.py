"""Decide whether signed UT work can be handed off, independently of acceptance."""

import json
from pathlib import Path
import re

import yaml

from .audit import read_spec
from .checkers import ToffeeUTChecker
from .paths import digest, local_path
from .runner import RunSourceStale, archived_run, current_run
from .stage_checks.line_coverage import check_signed


def _text(row, field):
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing nonempty {field}")
    return value.strip()


def _archived_full(workspace, project, dut):
    """Find reusable evidence, never publish it as the latest run or pass a gate."""
    root = local_path(workspace, (Path(project) / "results").as_posix())
    for path in sorted(root.glob("*/receipt.json"), reverse=True):
        if path.is_symlink() or path.parent.is_symlink():
            continue
        try:
            record = json.loads(local_path(workspace, path.relative_to(workspace).as_posix()).read_text())
            if (record.get("full_selection") is True and record.get("dut") == dut
                    and record.get("run") == f"results/{path.parent.name}"):
                verified = archived_run(workspace, project, record["run"])["record"]
                if verified["dut"] == dut and verified["full_selection"]:
                    return verified["run"]
        except (ValueError, KeyError, TypeError, AttributeError, OSError):
            continue
    return None


def _read_tasks(workspace, path, dut, run, review_hash, gap_groups, *, native_review):
    table = read_spec(path, "handoff_inventory", dut)
    if type(table.get("schema_version")) is not int or table["schema_version"] != 1:
        raise ValueError("Inventory needs schema_version: 1")
    if table.get("run") != run:
        raise ValueError(f"Inventory run must exactly match the signed project-relative value: {run}")
    if table.get("native_review_sha256") != review_hash:
        raise ValueError("Inventory does not match the current native review")
    _text(table, "scope_review")
    if not isinstance(table.get("items"), list):
        raise ValueError("Inventory needs an explicit items list")
    tasks, claimed = {}, set()
    for row in table["items"]:
        if not isinstance(row, dict):
            raise ValueError("Each inventory item must be a mapping")
        item_id, state = _text(row, "id"), _text(row, "state")
        if item_id in tasks or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", item_id):
            raise ValueError(f"Duplicate or invalid StageWork id: {item_id}")
        if state not in {"ready", "stalled", "external", "done"}:
            raise ValueError(f"{item_id}: invalid state")
        source = _text(row, "source")
        evidence = local_path(workspace, source.split("#", 1)[0])
        if evidence.resolve() == path.resolve() or _text(row, "sha256") != digest(evidence):
            raise ValueError(f"{item_id}: evidence source changed or cites the inventory itself")
        _text(row, "observation")
        if state == "external":
            for field in ("owner", "missing_input", "impact"):
                _text(row, field)
        elif state == "done":
            _text(row, "result")
        else:
            _text(row, "next_action")
        # Index spans refer to gap dispositions in the exact hashed native review,
        # not RTL line numbers. A completed follow-up cannot dispose of a live gap.
        spans = row.get("native_gaps", [])
        if not isinstance(spans, list) or (state == "done" and spans):
            raise ValueError(f"{item_id}: invalid native gap spans")
        if state == "external" and spans and native_review is not None and evidence.samefile(native_review):
            raise ValueError(f"{item_id}: 不能用缺口编号所依据的同一份原生覆盖审阅证明外部依赖；"
                             "请提供独立证据，或把可继续处理的缺口留在验证侧")
        for span in spans:
            if (not isinstance(span, list) or len(span) != 2
                    or any(type(value) is not int for value in span)
                    or not 1 <= span[0] <= span[1] <= gap_groups):
                raise ValueError(f"{item_id}: invalid native gap span")
            numbers = range(span[0], span[1] + 1)
            if not claimed.isdisjoint(numbers):
                raise ValueError(f"{item_id}: overlapping native gap spans")
            claimed.update(numbers)
        tasks[item_id] = row
    return tasks, gap_groups - len(claimed)


class ToffeeUTHandoff:
    """Read current evidence at the handoff boundary; never launch or record a run."""

    def stage_work_handoff_blocker(self, manager):
        """Return an actionable reason to continue, or no objection to handoff."""
        index, work = manager.stage_index, manager.stage_work
        phases = {checker.phase: checker for i, stage in enumerate(manager.stages)
                  if not stage.is_skipped() and (i == index or stage.is_reached())
                  for checker in stage.checker if isinstance(checker, ToffeeUTChecker)}
        native = phases.get("line_coverage")
        final = phases.get("final")
        checker = native or final
        if checker is None:
            return None
        if native and native.cfg is not None and not native.cfg.get_value("runtime_options.ut_line_coverage", True):
            native = None
            if final is None:
                return None
        workspace = Path(checker.workspace).resolve()
        dut, project = checker.dut, checker.project
        try:
            checked = current_run(workspace, project)
        except (FileNotFoundError, RunSourceStale):
            checked = None
        except (ValueError, KeyError, TypeError, OSError) as error:
            return (f"当前回执无法校验（{type(error).__name__}）。先定位签名、工件或路径问题，"
                    "保留旧原件；不盲目重跑，也不当作缺设计输入。")
        if checked is not None and checked["record"]["dut"] != dut:
            return "当前签名回执不属于此 DUT。核对项目路径和原件，不把设施问题交给设计。"
        if checked is None or not checked["record"]["full_selection"]:
            reusable = _archived_full(workspace, project, dut)
            if reusable:
                return (f"当前 latest 不是有效全量，但已有验证过且输入未变的全量 {reusable}。"
                        f"用 CoverageInfo(run={reusable!r}) 复用其原生覆盖，单独核对最近定向或中断。"
                        "不改 latest、不改签、不原样重跑、不把定向当作全量；正式阶段门禁不变。")
            return ("没有找到与当前输入匹配的签名全量。先查运行日志和输入变化；"
                    "确有必要且能执行时再用 RunToffee，不把未完成运行改列为缺设计输入。")
        run = checked["record"]["run"]
        review = None
        review_hash = None
        gap_groups = 0
        if native:
            review = local_path(workspace, (Path(project) / f"docs/reviews/{dut}-stage-evidence.md").as_posix())
            try:
                review_hash = digest(review)
            except FileNotFoundError:
                pass
            result = check_signed(workspace, dut, project, checked)
            kind = result.get("issue_kind")
            if not result["ok"] and kind != "coverage_gaps":
                return (f"{run} 原生覆盖复核：{kind}。{result.get('location', '')} "
                        f"{result['next_action']} 先处理验证侧证据，不为审阅重跑。")
            if digest(review) != review_hash:
                return f"{run} 的覆盖审阅在核对期间变化；先对当前审阅重新核对，不交接。"
            gap_groups = result.get("observed", {}).get("gap_groups", 0)

        relative = (Path(project) / f"docs/reviews/{dut}-handoff-inventory.md").as_posix()
        path = local_path(workspace, relative)
        try:
            tasks, unassigned = _read_tasks(workspace, path, dut, run, review_hash, gap_groups,
                                            native_review=review)
        except (ValueError, OSError, yaml.YAMLError) as error:
            reason = "未登记" if isinstance(error, FileNotFoundError) and error.filename == str(path) else str(error)[:300]
            return (f"{run} 的交接证据待核对（{reason}）：查当前报告、缺口清单和设施首错，"
                    f"在 {relative} 按 Guide_Doc/ut-coverage.md 分开登记。使用 Markdown 的单个 ```yaml 代码块，"
                    f"其中 kind: handoff_inventory；不要写成裸 YAML。不把 {gap_groups} 组缺口一概交人或重跑。")

        view = work.view(manager.stages, index)
        states = {}
        for _, item_id, state in view["states"]:
            states.setdefault(item_id, []).append(state)
        for item_id, row in tasks.items():
            if row["state"] == "ready":
                return (f"{run} 尚有验证侧事项 {item_id}（依据 {row['source']}）：{row['next_action']}。"
                        "若未登记或误列 human，用新证据登记 ready 并在本操作处理；不影响真实外部依赖。")
        for item_id, row in tasks.items():
            if row["state"] == "stalled":
                return (f"{run} 验证侧事项 {item_id} 尚停滞（{row['source']}）。"
                        f"未试过时可换办法：{row['next_action']}。没有新证据不要重试或改列 human。")
            expected = "human" if row["state"] == "external" else "done"
            if states.get(item_id) != [expected]:
                return f"{run} 的 {item_id} 与 StageWork 对不上；按当前证据核对，不凭报告销项。"
        for item in view["human"]:
            if tasks.get(item["id"], {}).get("state") != "external":
                return f"{run} 的 human 项 {item['id']} 缺少当前外部依赖证据；先核对是否实际上是验证侧待办。"
        if unassigned:
            return (f"{run} 仍有 {unassigned} 组已审阅的原生 gap 未归到具体事项；"
                    "按独立判据找可做的组，依赖与停滞分开，不能凭库存判定全都等人。")
        return None
