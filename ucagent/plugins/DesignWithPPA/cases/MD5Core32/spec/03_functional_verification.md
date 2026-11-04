
# Functional verification requirements

## Verification process requirements

This file constrains the generated API and tests rather than defining additional DUT behavior. Record these requirements in the design and test plan. Do not create ordinary FG/FC/CK function entries for this file; its physical lines may use reasoned `IGNORE` mappings that name the workflow artifact or stage responsible for enforcement.

## Executable API

Create one shared Python API whose public functions begin with `api_MD5Core32_`. Every API takes `env` as its first argument; calls that wait for a response take `max_cycles` as their final argument. The API must expose reset, one streamed message feed (word-by-word with last/byte_len), result observation, and a convenience whole-message hash operation while preserving the exact exception and timeout contract for Python and RTL backends.

### Backend-neutral environment

`conftest.py` shall select `--design-backend=python|rtl`, defaulting to `python`. The `env` fixture creates the executable Python reference adapter or the generated RTL adapter. Test functions are written once and run unchanged for both backends.

## Directed and boundary behavior

Implement tests linked to every applicable functional CK. Directed vectors shall cover the three normative README vectors: the empty message (`0x7e42f8ec`), `"abc"` (`0x727fe128`), and the quick-brown-fox sentence (`0xd619a442`). Boundary vectors shall cover every `byte_len_i` encoding on the final word (the 0-byte terminator, 1B, 2B and 3B partial words), messages of 4 bytes (multiple-of-4 terminator path), 55 bytes (single block with padding exactly fitting), 56 bytes (two blocks forced by padding), and 64 bytes (two blocks), partial words with mixed preceding full words, back-to-back messages with no idle cycle between `valid_o` consumption and the next `valid_i`, and reset during idle and between messages.

### Sequence and reset

Test acceptance only when `valid_i && ready_o`, `ready_o` low while a message is in flight, no output during reset, `valid_o` pulse semantics, and two messages separated by idle cycles. A timeout must fail the test rather than silently returning a partial result.

### Random differential testing

Use deterministic random seeds for at least 32 random messages of varied length classes: 0–55 bytes, 56–64 bytes, and ≥ 65 bytes spanning three or more blocks. Compare the final hash and the cycle-level handshake trace against the Python reference. Preserve seed and input trace in the test evidence.

## Coverage contract

Define toffee `CovGroup` points for each `byte_len_i` encoding, message length class (single-block, two-block, multi-block), each of the four round groups reaching at least once per block processed, reset, handshake acceptance, in-flight backpressure, and result-valid observation. Every point must be explicitly marked by at least one test; missing coverage blocks completion.

### Common reference vectors

At least one test must associate this CK with the three normative README vectors and their hand-derived expected hashes.

### Format boundaries

At least one test must associate this CK with every `byte_len_i` encoding and the 55/56/64-byte block-boundary lengths.

### Timing and reset

At least one test must associate this CK with reset, acceptance, in-flight `ready_o` deassertion, `valid_o` pulse width and idle re-arm.

### Differential random

At least one test must associate this CK with deterministic seeded random messages of all length classes and preserve the seed in the test evidence.
