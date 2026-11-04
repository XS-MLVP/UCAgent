---
name: rtl-tdd-backend
description: Keep the shared Python and RTL test adapters synchronized while preserving one TDD API and pytest suite.
---

# RTL TDD Backend

Use the `DUT`, `OUT`, selected RTL language, and source glob shown by the current stage. Treat the input DUT directory as read-only and write source, adapter, API, and tests only below `OUT`.

Use README, Spec, architecture, and FG/FC/CK as the behavioral authority. The Python executable specification implements that authority but is not permanently frozen: when requirement or test evidence proves its function, state, reset, timing, invalid-input, or boundary behavior is wrong, repair the reference and affected shared artifacts, rerun the Python nodes, and then rerun RTL validation. When the Python reference already matches the authority and passes while RTL fails, preserve the reference and expected values and repair RTL or its adapter. Keep one adapter/API/fixture surface for the managed reference and RTL executions; the validation runtime selects the implementation, and the skill must not add or expose a backend CLI option. After each selected-language RTL source change, call `Check` or `Complete` to run the shared functional regression. Never weaken an assertion or retain a known functional failure.

For host API rejection, handshake acceptance, in-flight state, response, or reset events that cannot be represented by a legal post-transaction pin snapshot, use the adapter's read-only `last_event` and `last_event_data` contract from `Guide_Doc/python_dut_interface.md`. Store immutable operation/mode/precision/input identity with `_record_transaction_accepted`; add real post-refresh/post-step state with `_record_transaction_observation`; let `_record_response_observed` merge the accepted identity with timing and result evidence and retire the transaction. Acceptance, waiting/backpressure, arithmetic/conversion, and latency predicates must use their corresponding real fields. Do not reuse one generic predicate across CKs. If two CKs cannot be distinguished by real observable evidence, merge the duplicate behaviors in the functional contract instead of adding tautologies, timestamp-existence checks, arbitrary transaction-ID arithmetic, or synthetic events. Tests must not access `env._dut`, call any private event/transaction helper, inspect active transaction state, assign event fields, or drive an out-of-range pin to manufacture coverage.

Execute Python DUT behavior only through existing pytest cases with `RunTestCases`; its targets are relative to `{OUT}/tests`. Let `Check` or `Complete` perform RTL regression. Do not use `python -c`, a temporary Python script, or a direct import to execute the reference, adapter, coverage module, or tests.

During the shared RTL regression, use a short evidence loop rather than repeatedly running the whole suite:

1. Call `Check` without `test_target` to identify the first exact failing node.
2. Keep the test expected aligned with README, Spec, architecture, and FG/FC/CK. If those sources expose a reference defect, repair and revalidate the reference first; otherwise do not edit the reference or expected to match an RTL result.
3. Call `Check` with the exact `rtl_debug.targeted_check` object returned by the failure. That invocation checks the same node against the Python reference and current RTL.
4. When `rtl_debug.waveform_retained` is true, call `WaveInfo` with `rtl_debug.waveform_test_case_name`. Start with clock/reset, request/response handshake, packed inputs, packed output, and the state or data-path signals relevant to the first wrong value. Work in three steps: list the newest waveform inventory, read the signal catalog and query events with structured `pattern` entries, then narrow to an explicit `start_step`/`end_step` window or `logged_cycle` with an exact `clock_signal`. Prefer reading internal signals from the waveform catalog; never read them from `env._dut` or backend-private members, and do not modify shared tests or the adapter just to observe them.
5. Trace one value through unpack/decode, signed extension, multiplication, accumulation, rescaling, rounding/saturation, and packing as applicable. Write down the unit and binary point at each boundary before changing RTL.
6. Repeat the targeted Check until it passes, then call the full Check to find the next failure. Only `Complete` without a target produces final all-suite evidence.

Bounded temporary logs (for example Verilog `$display` with `$time`) surface in the failure `stdout_tail` and the targeted Check output; remove them once the defect is fixed. The full debugging loop, including WaveInfo windows and internal-signal rules, is the RTL debugging section of `Guide_Doc/rtl_backend.md`.

A passing targeted Check deliberately does not create the full regression report. Do not create that report by hand. A failed run retains only diagnostic waveform data; passing transient runs are cleaned automatically.

Follow `Guide_Doc/rtl_design_constraints.md`, the current stage's complete `RTL_CODING_GUIDE` path, and `Guide_Doc/rtl_backend.md`. If this Skill is unavailable, those files and the stage task provide the same complete path.

When a compact ordered RTL source/hash summary is useful, optionally call `RunSkillScript` with `commands=[["ext/design-with-ppa/rtl-tdd-backend", "summarize_rtl.py", ""]]`. `Check` and `Complete` remain the authoritative validation path.
