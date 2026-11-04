# Constraints and verification

There is no clock, reset, latch, state, or handshake. Every output must have a
deterministic value for every 8-bit input and either value of `mode_i`; X/Z
simulation values are outside the legal binary input contract. No delays,
`initial`, `force`, `release`, or simulation-only system tasks are allowed.

The functional tests must cover at least:

1. zero, one, maximum, and overflow sums in add mode;
2. all-zero, all-one, alternating, and mixed XOR operands;
3. both mode values with the same operands;
4. carry clearing in XOR mode and parity for every selected result;
5. reuse of both named library modules and the required top-to-child hierarchy.

Each test must compare every public output with an independently calculated
expected value. A test that only checks that a value is present is insufficient.
