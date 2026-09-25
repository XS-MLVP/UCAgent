---
name: waveform-review
description: Analyze selected reproduced DUT failures with UCAgent's default WaveInfo and save signed transaction evidence in the canonical Bug Review JSON.
---

# Waveform Review

## Goal

For every case whose replay reproduced a failure and whose test review confirms a correct DUT-facing test, call the built-in `WaveInfo` tool directly. Do not use a Bug Review waveform wrapper.

## Actions

Use the exact `waveform_test_case_name` from the current RunTestCases report. First inspect the waveform inventory and signal catalog. Then make the final call with an explicit event `pattern` and `start_step`/`end_step` window or `logged_cycle`/`clock_signal` alignment.

The final `signal_groups` must describe the complete relevant context: actual clock and clocked mode for a sequential DUT, or `combinational` with no invented clocks; relevant input data, selectors and enables; output data, status and valid signals; actual request acceptance and response controls when present; and at least one functional selection, state or error propagation path. A case linked to multiple Bugs must cover the union of their required signals. The signed timeline and online viewer must show the same signal set. Align logs and waveforms by clock occurrence and transaction context; a numeric cycle/step match is not sufficient.

Update the same `{OUT}/workspaces/<workspace>/bug_review.json` case record. Preserve the exact `receipt_id` and complete returned WaveInfo result, including viewer and signed signal groups. Set `conclusion` to `dut_bug`, `not_dut_bug` or `inconclusive`; either decisive conclusion requires a real signed receipt. Record the event window, transaction alignment and source correlation. If no usable receipt is produced, retain the returned error/result and set the conclusion to `inconclusive`; never invent a receipt or viewer. Set `stage_status.waveform` to `complete` after every eligible case has an evidence result. Run Check, record the stage journal and Complete.
