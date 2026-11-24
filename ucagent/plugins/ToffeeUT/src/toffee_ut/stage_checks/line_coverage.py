"""Check native coverage without confusing stale records with uncovered behavior."""

from ..runner import RunSourceStale, current_run


def _failure(kind, error, action, **observed):
    return {"ok": False, "phase": "line_coverage", "error_code": "UT_STAGE_EVIDENCE_MISSING",
            "error": str(error)[:2000], "next_action": action, "issue_kind": kind,
            "observed": observed}


def check(workspace, dut, project):
    """Read only current evidence and return one bounded, actionable diagnosis."""
    try:
        checked = current_run(workspace, project)
    except RunSourceStale as error:
        return _failure("run_required", error,
                        "First check the listed fingerprinted inputs. Keep run IDs and observations in docs/reviews, "
                        "not in signed docs/spec. Finish necessary test/spec edits together before running the full "
                        "selection with RunToffee once; then update the review only.",
                        changed_inputs=list(error.changed[:12]), changed_total=len(error.changed))
    except FileNotFoundError as error:
        return _failure("run_required", error,
                        "First check for an existing signed full run for these inputs. If no reusable full evidence "
                        "exists, run the complete selection with RunToffee once, then review it.")
    except (ValueError, KeyError, TypeError, OSError) as error:
        return _failure("run_invalid", error,
                        "Inspect the named receipt or artifact before scheduling a new run. Preserve the failed evidence.")
    return check_signed(workspace, dut, project, checked)


def check_signed(workspace, dut, project, checked):
    """Reuse the exact checker on a receipt already validated by the caller."""
    from ..coverage import coverage_data

    run = checked["record"]["run"]
    data = coverage_data(workspace, project, dut, checked)
    review = data["review"]
    if review["state"] == "complete":
        return {"ok": True, "phase": "line_coverage",
                "note": "Structural evidence checked; a passing gate alone does not prove behavioral correctness."}
    kind = review.get("issue_kind", "review_invalid")
    actions = {
        "review_missing": "Create the review for this run in the permitted review document. Reuse the signed counters.",
        "review_stale": "Compare this run's zero points with the review. Update the review, not the receipt. No rerun is needed for the document change.",
        "selector_mismatch": "Use CoverageInfo to resolve the named selector against the current build. Change a path only when it maps uniquely to the same points.",
        "review_incomplete": "Review the remaining zero-point groups in batches. Keep any unproven group as a gap.",
        "coverage_gaps": "Use the signed coverage points and independent scenarios to choose a batch of feasible tests. Keep unresolved gaps and revisit this stage after revalidation.",
    }
    result = _failure(kind, review.get("error", "Native coverage still has required gaps"),
                      actions.get(kind, "Inspect the first invalid field or source in the review; keep current signed counters."),
                       run=run, unreviewed=review.get("unreviewed_by_metric", {}),
                       gap_points=review.get("gap_points"), gap_groups=len(review.get("gaps", ())))
    where = review.get("location")
    if where:
        result["location"] = where
    return result
