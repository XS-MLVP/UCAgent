
# Functional verification requirements

## Verification process requirements

This file constrains the generated API and tests rather than defining additional DUT behavior. Record these requirements in the design and test plan. Do not create ordinary FG/FC/CK function entries for this file; its physical lines may use reasoned `IGNORE` mappings that name the workflow artifact or stage responsible for enforcement.

## Executable API

Create one shared Python API whose public functions begin with `api_LowPrecisionMatMul2x2_`. Every API takes `env` as its first argument; calls that wait for a response take `max_cycles` as their final argument. The API must expose reset, one matrix transaction, result observation, and a convenience matrix-multiply operation while preserving the exact exception and timeout contract for Python and RTL backends.

### Backend-neutral environment

`conftest.py` shall select `--design-backend=python|rtl`, defaulting to `python`. The `env` fixture creates the executable Python reference adapter or the generated RTL adapter. Test functions are written once and run unchanged for both backends.

## Directed and boundary behavior

Implement tests linked to every applicable functional CK. Directed vectors shall cover identity matrices, zero matrices, signed values, mixed signs, and dense non-trivial products in both precisions. Boundary vectors shall cover every FP4 encoding and representative FP8 exponent/mantissa combinations, cancellation, underflow, overflow saturation, and reset during idle and between transactions.

### Sequence and reset

Test acceptance only when `valid_i && ready_o`, fixed two-cycle response latency, no output during reset, ready/valid transitions, and two transactions separated by idle cycles. A timeout must fail the test rather than silently returning a partial result.

### Random differential testing

Use deterministic random seeds for at least 32 FP4 and 32 FP8 matrix transactions. Compare every output element and the cycle-level handshake trace against the Python reference. Preserve seed and input trace in the test evidence.

## Coverage contract

Define toffee `CovGroup` points for precision mode, sign, zero, smallest/largest finite values, cancellation, saturation, reset, handshake acceptance, and two-cycle response. Every point must be explicitly marked by at least one test; missing coverage blocks completion.

### Common arithmetic vectors

At least one test must associate this CK with identity, zero, mixed-sign and dense matrices in both FP4 and FP8.

### Format boundaries

At least one test must associate this CK with all FP4 codes plus FP8 zero, normal, maximum finite and saturation cases.

### Timing and reset

At least one test must associate this CK with reset, acceptance, exact two-cycle latency, valid pulse width and idle re-arm.

### Differential random

At least one test must associate this CK with deterministic seeded random vectors and preserve the seed in the test evidence.
