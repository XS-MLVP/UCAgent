# Interface and behavior

The design is a purely combinational unsigned datapath. The top module name is
`modular_alu_with_ex_verilog` and it has exactly these public ports:

| Port | Direction | Width | Meaning |
| --- | --- | --- | --- |
| `a_i` | input | 8 | First unsigned operand, range 0..255 |
| `b_i` | input | 8 | Second unsigned operand, range 0..255 |
| `mode_i` | input | 1 | `0` selects saturating add; `1` selects XOR |
| `result_o` | output | 8 | Selected result |
| `carry_o` | output | 1 | Add overflow flag; always 0 in XOR mode |
| `parity_o` | output | 1 | Reduction XOR of `result_o` |

For `mode_i == 0`, `result_o = min(a_i + b_i, 255)` and `carry_o` is one when
the mathematical sum is greater than 255. For `mode_i == 1`,
`result_o = a_i ^ b_i` and `carry_o = 0`. `parity_o` equals the XOR reduction
of all eight result bits for both modes.

The child datapath module must instantiate and reuse the library modules
`ex_saturating_add8` and `ex_xor_reduce8` from `lib/ex_common.v`. The top module
must instantiate the child module; do not flatten the design into one file.
