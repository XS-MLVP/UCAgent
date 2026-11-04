# modular_alu_with_ex_verilog

`modular_alu_with_ex_verilog` is a small combinational Verilog design used to exercise
multi-file RTL generation and read-only library reuse in the DesignWithPPA
workflow.

The target module accepts two unsigned 8-bit operands and a mode bit. In add
mode it returns an 8-bit saturating sum and the carry indication. In XOR mode it
returns the bitwise XOR and clears the carry indication. The output parity is
the reduction XOR of the selected result in either mode.

The implementation must be split across at least two authored output files:

- `modular_alu_with_ex_verilog.v` is the top module and owns the public interface.
- `modular_alu_with_ex_verilog_lane.v` is a child module that selects the operation.

The input directory also contains `lib/ex_common.v`. This is a read-only,
pre-existing Verilog library and is part of the case contract. It provides
`ex_saturating_add8` and `ex_xor_reduce8`. The generated RTL must instantiate
these library modules instead of re-implementing their logic. The workflow
configures `modular_alu_with_ex_verilog/lib` as the RTL library path; do not copy,
rename, modify, or emit this library under `{OUT}/rtl`.

All public behavior, invalid-input policy, and performance measurement rules
are defined by the files under `spec/`. The case input is read-only. The
workflow writes generated Python DUTs, shared tests, RTL, waveforms, reports,
and optimization history only to its resolved output workspace.
