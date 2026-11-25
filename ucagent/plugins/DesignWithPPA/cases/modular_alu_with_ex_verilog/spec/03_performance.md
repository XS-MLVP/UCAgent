# Performance measurement

This combinational design has no clock. Performance tests must use more than
one distinct test case and use the prefix
`test_modular_alu_with_ex_verilog_performance_`. Each performance test must apply a
deterministic batch of operands, record its input trace, wait for combinational
settling, and write an independent waveform and JSON sidecar.

The primary timing metric is the measured combinational critical delay (or its
equivalent maximum frequency) from input transaction change to stable output.
Area and power are measured by the PPA tool. Use at least these performance
scenarios:

- `test_modular_alu_with_ex_verilog_performance_add`: dense add-mode vectors including
  overflow and saturation;
- `test_modular_alu_with_ex_verilog_performance_xor`: dense XOR-mode vectors including
  alternating bit patterns.

The two tests must have stable node identities, different deterministic input
traces, and must never overwrite one another's waveform or sidecar.
