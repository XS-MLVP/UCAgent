"""Require exact, signed targeted evidence before a native coverage full rerun."""

from .coverage import native_points
from .runner import archived_run


def _identity(metric, row):
    return metric, row["build"], row["source"], row["line"], row.get("point")


def _observed(workspace, project, dut, checked, points):
    rows, _, builds = native_points(workspace, project, dut, checked)
    identities = ((_identity(metric, row), row["count"]) for metric, values in rows.items() for row in values)
    return ({key: count for key, count in identities if key in points},
            {item["build"]["build_id"] for item in builds.values()})


def check_coverage_batch(workspace, project, dut, seed, batch):
    """Preflight one declared batch. No run, pointer change, or coverage credit."""
    base = archived_run(workspace, project, batch.baseline, current=False)
    before = base["record"]
    if before["dut"] != dut or not before["full_selection"] or before["seed"] != seed or not before["line_coverage_required"]:
        raise ValueError("The baseline must be a signed native full selection for this DUT and seed")
    target = archived_run(workspace, project, batch.targeted)
    trial = target["record"]
    if (trial["dut"] != dut or trial["full_selection"] or trial["seed"] != seed
            or not trial["line_coverage_required"]):
        raise ValueError("Use a signed targeted native run for the current DUT, inputs and seed")
    if before["source_after"] == trial["source_after"]:
        raise ValueError(f"The signed full baseline {batch.baseline} already matches the inputs; reuse it instead of rerunning")

    cases = target["cases"]["cases"]
    selection = trial["selection"]
    if (selection["keyword"] or selection["markers"] or not cases
            or set(selection["targets"]) != set(cases) or any("::" not in node for node in cases)
            or not any(not row["selftest"] and row["native_duts"] for row in cases.values())
            or any(row["status"] != "PASS" for row in cases.values())):
        raise ValueError("Select the impacted exact pytest nodeids, including a real DUT case, and verify their PASS outcomes")

    hits = [_identity(row.metric, row.model_dump()) for row in batch.expect_hits]
    keep = [_identity(row.metric, row.model_dump()) for row in batch.retain_hits]
    requested = set(hits + keep)
    if len(requested) != len(hits) + len(keep):
        raise ValueError("Expected and retained native points must be distinct")
    old, old_builds = _observed(workspace, project, dut, base, requested)
    new, new_builds = _observed(workspace, project, dut, target, requested)
    if not old_builds or old_builds != new_builds:
        raise ValueError("Targeted and full evidence must use the same native builds")
    for index, key in enumerate(hits):
        if old.get(key) != 0 or not new.get(key, 0):
            raise ValueError(f"expect_hits[{index}] must be an exact baseline zero with a nonzero targeted count: {key[2]}:{key[3]}")
    for index, key in enumerate(keep):
        if not old.get(key, 0) or not new.get(key, 0):
            raise ValueError(f"retain_hits[{index}] must be nonzero in both runs: {key[2]}:{key[3]}")
    return trial["source_after"]
