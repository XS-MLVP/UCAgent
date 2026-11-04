
# Interface and timing contract

## FG-IF-1: Transaction interface

The top module shall be named `MD5Core32` and expose exactly the ports listed below. All ports are unsigned unless explicitly stated.

| Port | Direction | Width | Meaning |
| :--- | :--- | ---: | :--- |
| `clk_i` | input | 1 | Rising-edge clock |
| `rst_ni` | input | 1 | Active-low synchronous reset |
| `valid_i` | input | 1 | Input data word is present |
| `ready_o` | output | 1 | Core can accept a data word |
| `data_i` | input | 32 | Message data word (little-endian) |
| `last_i` | input | 1 | This word is the final word of the message |
| `byte_len_i` | input | 2 | Valid bytes carried by the final word: 0, 1, 2 or 3 |
| `valid_o` | output | 1 | Hash result is present |
| `hash_o` | output | 32 | Truncated 32-bit MD5 hash |

### FC-IF-1.1: Handshake acceptance

An input data word is accepted on a rising edge when `rst_ni=1`, `valid_i=1` and `ready_o=1`. The transaction consists of `data_i`, `last_i`, and `byte_len_i` sampled on that edge. Data words must not change an accepted result afterward. `byte_len_i` is only meaningful when `last_i=1`; a nonzero `byte_len_i` on a non-final word is a protocol violation the adapter must reject. The total message length in bytes is `4 × (number of accepted non-final words) + byte_len_i of the final word`. An empty message is a single accepted final word with `byte_len_i=0`; a message whose length is a nonzero multiple of 4 sends all data in non-final words and then one final word with `byte_len_i=0` whose `data_i` is ignored.

### FC-IF-1.2: Backpressure and in-flight protection

This unit has no downstream backpressure port. `ready_o` is low while a hash is being computed and high again after the result cycle. The core may not overwrite an in-flight message; `ready_o` returns high only after `valid_o` is asserted and consumed.

## FG-IF-2: Reset and result timing

Reset is synchronous, active low, and sampled on the rising edge. While reset is asserted, `ready_o=1`, `valid_o=0`, `hash_o=0`, and all internal state is cleared to the initial chaining values. Deassertion does not itself create a transaction.

### FC-IF-2.1: Variable response latency

The response latency depends on the number of 512-bit blocks in the padded message. After `last_i=1` is accepted, `valid_o` shall assert within `N_blocks × 64 + C` cycles where `C ≤ 16` is a fixed design constant. The spec does not mandate a single exact cycle; it mandates an upper bound that the RTL must meet and the test API must verify.

### FC-IF-2.2: Invalid input rejection

The test API must include an invalid-input path for `data_i` with X/Z bits or a nonzero `byte_len_i` on a non-final word. The adapter must reject malformed values before driving RTL; the Python reference must raise the same typed exception for the same conditions. An empty message (a lone final word with `byte_len_i=0`) is valid input, not a rejection case.

### FC-IF-2.3: Multi-block message boundary

Messages ≥ 56 bytes require more than one 512-bit block due to padding. The core must correctly handle 1-block (0–55 bytes), 2-block (56–64 bytes padded), and multi-block messages. The adapter must not truncate or drop words at block boundaries.
