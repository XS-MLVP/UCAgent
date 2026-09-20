
# Numeric formats and arithmetic

## FG-FP-1: Precision selection

`precision_i=0` selects FP4 and `precision_i=1` selects FP8 for the complete transaction. A one-bit RTL pin has no other binary encoding. Malformed host values and X/Z handling follow the interface contract; represent that shared rejection behavior with one CK carrying both Spec sources, not duplicate CKs.

### FC-FP-1.1: FP4 E2M1 encoding

The low four bits of each element encode a finite E2M1 value: bit 3 is sign, bits 2:1 are an unsigned exponent with bias 1, and bit 0 is the mantissa. The unsigned magnitude codes `000` through `111` represent exactly `0`, `0.5`, `1`, `1.5`, `2`, `3`, `4` and `6`. The sign bit negates a non-zero magnitude and distinguishes negative zero from positive zero. The reference and RTL must use this exact lookup table for all 16 codes; do not derive a different mapping from shifts or from observed DUT output. For example, positive `1.0` is the 4-bit code `0b0010` (`0x2`), negative `1.0` is `0b1010` (`0xa`), and positive `2.0` is `0b0100` (`0x4`). Each matrix element still occupies one 8-bit byte, so a row-major matrix `[[1, 0], [0, 0]]` is packed as bytes `[0x02, 0x00, 0x00, 0x00]`, or `0x00000002`; `0x00200020` instead contains bytes `[0x20, 0x00, 0x20, 0x00]`. The upper four bits of an FP4 input are ignored but must be preserved in the input trace; each FP4 output has its upper four bits set to zero.

### FC-FP-1.2: FP8 E4M3 encoding

All eight bits encode a finite E4M3 value: bit 7 is sign, bits 6:3 are an unsigned exponent with bias 7, and bits 2:0 are the mantissa. For exponent 0, the magnitude is `mantissa × 2^-9`, including signed zero when mantissa is zero. Exponents 1 through 14 use `(1 + mantissa/8) × 2^(exponent-7)`. Every exponent-15 code is a finite saturating encoding of magnitude 240, the exponent-14/mantissa-7 maximum. The reference and RTL must agree for every code, including signed zero, subnormal values and maximum finite values.

## FG-FP-2: Exact accumulation contract

Each output is the sum of two products: `C[i][j] = A[i][0]×B[0][j] + A[i][1]×B[1][j]`. Both formats are exactly representable as a signed fixed-point integer with 9 fractional bits. The implementation shall use at least 19 signed bits for each decoded operand, at least 38 signed bits for each Q18 product, and at least 40 signed bits for the sum before output conversion. No intermediate product may be rounded before accumulation.

### FC-FP-2.1: Deterministic output conversion

Convert each accumulated value back to the selected format using round-to-nearest, ties-to-even. Values larger than the selected finite maximum saturate to that maximum with the accumulated sign. Values whose magnitude is below the smallest representable non-zero value round to signed zero. The result bits must be stable across runs and independent of host floating-point locale.

### FC-FP-2.2: Signed zero and cancellation

Positive and negative zero are accepted inputs. Exact cancellation returns positive zero. A negative non-zero result that underflows returns negative zero. Tests must cover cancellation, signed-zero inputs, smallest non-zero values, largest finite values, and saturation.

For the canonical packed vectors, element 0 is the least-significant byte and element 2
(`m10`) is bits 16:23. Use `A=0x00000a02` and `B=0x00020002` for cancellation:
`A=[+1,-1,0,0]`, `B=[+1,0,+1,0]`, so `c00=+1*+1 + -1*+1 = 0` and every other
output accumulation is also zero. Use `A=0x00000009` and `B=0x00000001` for negative
underflow: `-0.5*+0.5=-0.25`; this is below the FP4 minimum non-zero magnitude and,
at the exact half-way point, ties-to-even produces signed-zero byte `0x08`. These
vectors are normative examples for generated tests; `0x02020002` and `0x80000000`
are not equivalent encodings.
