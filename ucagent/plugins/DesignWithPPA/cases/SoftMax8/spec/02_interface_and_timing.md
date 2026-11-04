
# Interface and timing contract

## FG-IF-1: Transaction interface

The top module shall be named `SoftMax8` and expose exactly the ports listed below. All ports are unsigned unless explicitly stated.

| Port | Direction | Width | Meaning |
| :--- | :--- | ---: | :--- |
| `clk_i` | input | 1 | Rising-edge clock |
| `rst_ni` | input | 1 | Active-low synchronous reset |
| `valid_i` | input | 1 | Input transaction is present |
| `ready_o` | output | 1 | Unit can accept a transaction |
| `mode_i` | input | 1 | 0=vector mode (one group of 8), 1=matrix mode (2×4, row-wise) |
| `x_i` | input | 64 | Eight packed signed Q4.4 lanes, lane k in byte k |
| `valid_o` | output | 1 | Result transaction is present |
| `p_o` | output | 128 | Eight packed Q0.16 probabilities, lane k in bits [16k+15:16k] |

### FC-IF-1.1: Handshake acceptance

An input transaction is accepted on a rising edge when `rst_ni=1`, `valid_i=1` and `ready_o=1`. The transaction consists of `mode_i` and `x_i` sampled on that edge. Inputs must not change the accepted result afterward.

### FC-IF-1.2: Backpressure

This unit has no downstream backpressure port. `valid_o` is asserted for exactly one cycle when a result is available; `ready_o` is low while a transaction is in flight and high again after the result cycle. The unit may accept one transaction per idle interval and must not overwrite an in-flight transaction.

## FG-IF-2: Reset and latency

Reset is synchronous, active low, and sampled on the rising edge. While reset is asserted, `ready_o=1`, `valid_o=0`, `p_o=0`, and all internal state is cleared. Deassertion does not itself create a transaction.

### FC-IF-2.1: Bounded response latency

For every accepted transaction, `valid_o` shall assert no later than 32 rising clock edges after the acceptance edge. The result remains stable for the whole valid cycle. No spurious output is permitted without a preceding accepted input.

### FC-IF-2.2: Mode pin and invalid input

The one-bit mode selector has no illegal binary encoding. The test API must still include an invalid-input path for X/Z or malformed host values; the adapter must reject malformed values before driving RTL and the Python reference must raise the same typed exception.
