
# Fixed-point SoftMax algorithm

## FG-FP-1: Q4.4 input format and max subtraction

Each of the eight input lanes is an 8-bit two's-complement Q4.4 fixed-point number: the signed integer code divided by 16, range `[-8.0, +7.9375]`. Lane `k` occupies byte `k` of `x_i` with lane 0 in the least-significant byte. For example `0x00` is 0.0, `0x7f` is +7.9375, `0x80` is -8.0, and `0xf0` is -1.0. The whole 64-bit input is one transaction; lanes are independent inputs to the algorithm below.

### FC-FP-1.1: Mode-dependent grouping

`mode_i=0` (vector) forms one normalization group of all eight lanes. `mode_i=1` (matrix) forms two independent groups from the 2×4 row-major matrix: row 0 is lanes 0–3 and row 1 is lanes 4–7. Normalization never crosses a group boundary; each group computes its own maximum, sum, and probabilities. The grouping is part of the accepted transaction and may not change while a transaction is in flight.

### FC-FP-1.2: Group maximum and code distance

For each group, let `c_max` be the maximum lane code and `c_i` each lane code, both as signed integers in `[-128, 127]`. The distance for lane `i` is the integer `d_i = c_max - c_i ∈ [0, 255]`; one distance unit is 1/16 in value. Every group contains at least one lane with `d=0` (any lane at the maximum; multiple tied maxima all take `d=0`). The reference and RTL must compute `d` as an exact 9-bit-safe integer subtraction, never through decoded floating-point values.

## FG-FP-2: Exponential lookup table

### FC-FP-2.1: Normative 256-entry table

Each lane's exponent is `e_i = LUT[d_i]` where `LUT[i] = round-half-up(exp(-i/16) × 1024)` for `i = 0..255`. The table below is normative; the reference and the RTL must embed exactly these values, in this order. Rows list 16 consecutive entries ascending left-to-right: row 0 starts at `i=0`, row 1 at `i=16`, and so on. Spot checks: `LUT[0]=1024`, `LUT[16]=377`, `LUT[121]=1`, `LUT[122]=0` and every entry from `i=122` through `i=255` is 0.

```text
 1024  962  904  849  797  749  704  661  621  583  548  515  484  454  427  401
  377  354  332  312  293  276  259  243  228  215  202  189  178  167  157  148
  139  130  122  115  108  101   95   89   84   79   74   70   65   61   58   54
   51   48   45   42   40   37   35   33   31   29   27   26   24   23   21   20
   19   18   17   16   15   14   13   12   11   11   10    9    9    8    8    7
    7    6    6    6    5    5    5    4    4    4    4    3    3    3    3    3
    3    2    2    2    2    2    2    2    2    1    1    1    1    1    1    1
    1    1    1    1    1    1    1    1    1    1    0    0    0    0    0    0
    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0
    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0
    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0
    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0
    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0
    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0
    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0
    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0
```

### FC-FP-2.2: Positivity and underflow

Each group contains at least one `d=0` lane, so its sum always satisfies `S ≥ LUT[0] = 1024`; the normalization divisor is never zero. Lanes with `d ≥ 122` contribute `e=0` and therefore probability 0; this underflow is the defined behavior, not an error. Entries fit in 11 unsigned bits (`0..1024`).

## FG-FP-3: Normalization and output format

### FC-FP-3.1: Integer normalization formula

For each group, `S = Σ e_i` (at most `8 × 1024 = 8192`, 14 unsigned bits) and each lane's probability is the exact integer division

```text
p_i = floor((e_i × 65535 + floor(S / 2)) / S)
```

computed with sufficient width: `e_i × 65535` needs at least 27 bits before adding `floor(S/2)`; intermediate truncation is a functional error. The identity case `e_i = S` yields exactly `p_i = 65535`. Both backends must evaluate this formula in integer arithmetic; floating-point division followed by conversion is not an equivalent implementation.

### FC-FP-3.2: Output packing and group-sum property

`p_o` packs eight 16-bit probabilities: lane `k`'s probability occupies bits `[16k+15:16k]`, lane 0 in the least-significant halfword. Probabilities are Q0.16 with full scale 65535 representing 1.0, so `p_i ∈ [0, 65535]`. Rounding may shift the group sum by at most half a unit per lane: `|Σ p_i − 65535| ≤ group_size/2` for every group (4 for vector mode, 2 per matrix row). An exact group sum is not mandated and must not be forced by post-adjusting any lane.
