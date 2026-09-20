
# Functional verification requirements

## Verification process requirements

This file constrains the generated API and tests rather than defining additional DUT behavior. Record these requirements in the design and test plan. Do not create ordinary FG/FC/CK function entries for this file; its physical lines may use reasoned `IGNORE` mappings that name the workflow artifact or stage responsible for enforcement.

## Executable API

Create one shared Python API whose public functions begin with `api_SoftMax8_`. Every API takes `env` as its first argument; calls that wait for a response take `max_cycles` as their final argument. The API must expose reset, one transaction with mode selection, result observation, and a convenience whole-vector/whole-matrix softmax operation while preserving the exact exception and timeout contract for Python and RTL backends.

### Backend-neutral environment

`conftest.py` shall select `--design-backend=python|rtl`, defaulting to `python`. The `env` fixture creates the executable Python reference adapter or the generated RTL adapter. Test functions are written once and run unchanged for both backends.

## Directed and boundary behavior

Implement tests linked to every applicable functional CK. Directed vectors shall cover the four normative README vectors: the all-zero vector (every lane `p=0x2000`), the `[0,-1..-7]` skew vector, the `0x7f80808080808080` saturation/underflow vector (`p=[0xffff,0,...,0]`), and the matrix-mode vector `0x0000000000f0e0d0` (row 0 all `0x4000`, row 1 `[0xa4c4,0x3ca9,0x165e,0x0835]`). Boundary vectors shall cover tied maxima with different tie counts (two through eight lanes at the maximum), minimum and maximum Q4.4 codes (`0x80`, `0x7f`), lanes at the LUT zero boundary (`d=121` vs `d=122`), both modes on identical input data showing group-size dependence, all-negative groups, and reset during idle and between transactions.

### Sequence and reset

Test acceptance only when `valid_i && ready_o`, `ready_o` low while a transaction is in flight, `valid_o` pulse width of one cycle, latency within the 32-cycle bound, no output during reset, and two transactions separated by idle cycles. A timeout must fail the test rather than silently returning a partial result.

### Group-sum property

At least one directed test per mode must assert `|Σ p_i − 65535| ≤ group_size/2` for every group across the directed vectors and a deterministic sample of random vectors.

### Random differential testing

Use deterministic random seeds for at least 32 vector-mode and 32 matrix-mode transactions with codes spanning the full Q4.4 range including tied maxima and far-below-maximum lanes. Compare all eight probabilities and the cycle-level handshake trace against the Python reference. Preserve seed and input trace in the test evidence.

## Coverage contract

Define toffee `CovGroup` points for both mode encodings, tied maxima with at least two lanes at the maximum, an underflow lane (`d ≥ 122`), the saturation probability 65535, the identity division case `e_i = S`, LUT boundary indices 0, 121, 122 and 255, reset, handshake acceptance, and the bounded-latency window. Every point must be explicitly marked by at least one test; missing coverage blocks completion.

### Common reference vectors

At least one test must associate this CK with the four normative README vectors and their hand-derived expected probabilities in the correct packing.

### Format boundaries

At least one test must associate this CK with tied maxima, Q4.4 endpoint codes, LUT boundary distances, and both modes on identical data.

### Timing and reset

At least one test must associate this CK with reset, acceptance, in-flight `ready_o` deassertion, `valid_o` pulse width, latency bound and idle re-arm.

### Differential random

At least one test must associate this CK with deterministic seeded random transactions in both modes and preserve the seed in the test evidence.
