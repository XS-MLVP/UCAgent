---
name: replay-review
description: Selectively rerun only cases associated with reported Bugs, review test correctness, and update replay evidence in the canonical Bug Review JSON.
---

# Replay Review

## Goal

Use each workspace's `bug_review.json` to select relevant test cases. The prepared test root contains the UnityTest test files, shared test helpers and importable DUT runtime package; it does not contain a full copy of the source workspace. Never edit those copied or original test, fixture, Spec, RTL or model files.

## Actions

Read the original test, fixture and Spec files using the paths recorded in `bug_review.json` and its `source_files`. Select the smallest useful set of cases that directly checks each claim; unrelated tests do not need to run. For each workspace, call UCAgent `RunTestCases` once with `target` containing the selected `replay_target` values separated by spaces (each target is relative to `{OUT}/tests`) and a suitable timeout. A single invocation keeps selected failures in the same current waveform session. Record the tool's exact report node ID in each case's `waveform_test_case_name`, preserving the complete `{OUT}/tests/...::test_name` identity required by default WaveInfo.

Immediately update the selected cases in `{OUT}/workspaces/<workspace>/bug_review.json`. For each case, store the exact `nodeid`, `invocation_success`, `test_count`, `failed_count`, actual result and `status` (`reproduced`, `passed`, `not_collected` or `execution_error`). Keep test execution separate from `test_review`: independently derive Spec expectation, inspect the test assertion, exact input and actual result, then assess driver, fixture, reset and sampling timing. Set `classification` to `suspected_dut_bug` only when the test is correct; distinguish testbench and environment failures. A replay failure alone is not Bug confirmation.

Add newly discovered failures to the same `cases` object and add a corresponding `origin: discovered` entry to `suspected_bugs` only when the case is a plausible DUT defect. Update `stage_status.replay` to `complete` after all selected cases have results and correctness reviews. Run Check, record the stage journal and Complete.
