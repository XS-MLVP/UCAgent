
# Swarm stage review

The authenticated CMD API exposes `GET /api/swarm/review`, returning the current
mission, check readiness, a review token and the latest 100 operation receipts.
A stage is review-ready only when its checks passed and human review is pending.
The ordinary HM flag alone is not a completed-check signal.

`POST /api/swarm/review` applies HM flag changes immediately, allowing an active
stage to enable review, and queues continue/feedback commands. Swarm sends a
single `swarm_review <JSON>` PDB command with `action` (`enable_hm`,
`continue`, `feedback`), `stage_index`, `review_token`, `operation_id`, and
`feedback`. The command validates the stage and check evidence when consumed,
not just when enqueued. Continue passes HM then resumes; feedback fails HM,
invalidates the prior check and resumes correction in the same stage.

Repeated identical operation IDs cannot repeat a transition. Changed payloads,
old stage tokens and approvals from a previous process are rejected. Receipts
are process-local; a restart invalidates the approval epoch instead of replaying
uncertain actions. Queue admission is not an applied receipt. The platform
persists observed status changes in its own conversation history.

This interface does not bypass CMD authentication, execute caller-supplied shell
commands, or migrate workspaces. Existing general HM commands retain their
interactive semantics. Test the stage guard with
`python3 tests/test_swarm_review.py`.


## Creation-time review gates

`runtime_options.human_review_stage_names` defaults to an empty string. Swarm supplies semicolon-delimited stable stage names through a controlled CLI override, for example `functional_specification_refine;create_test_case_templates;verification_review_and_summary`. It is persisted in the nonsecret resolved runtime config snapshot. It adds HM requirements and never disables a workflow's existing human checkers.

After actual stages and saved progress resolve, before stage initialization commands, all selected names must resolve exactly once, remain unskipped (including CLI skip/unskip selections), and be at or after the starting stage. Otherwise initialization fails with the affected name. Ordinary recovery retains already completed stages. A forced-stage rerun must choose only gates it will execute. This selection does not imply approval: real Complete/check evidence still gates the pause, and existing stage-bound review commands continue or return feedback to that same stage. Empty selection preserves existing workflow behavior.

Focused regression: `pytest tests/test_stage_manager.py tests/test_swarm_review.py`.
