
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
