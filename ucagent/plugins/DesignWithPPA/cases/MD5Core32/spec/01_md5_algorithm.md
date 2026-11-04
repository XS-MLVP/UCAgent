
# MD5 algorithm and constants

## FG-FP-1: MD5 core arithmetic

The module implements the RFC 1321 MD5 message-digest algorithm. The public output is the low 32 bits of the standard 128-bit digest.

### FC-FP-1.1: Initial chaining values

The four 32-bit chaining variables are initialized to `A=0x67452301`, `B=0xefcdab89`, `C=0x98badcfe`, `D=0x10325476`. These constants are fixed and identical to RFC 1321. The reference must use these exact values; the RTL must not initialize from a different source.

### FC-FP-1.2: Four round functions

Each 512-bit block runs 64 rounds in four groups of 16. The nonlinear functions are:
- Rounds 1–16 (F): `(B & C) | (~B & D)`
- Rounds 17–32 (G): `(D & B) | (~D & C)`
- Rounds 33–48 (H): `B ^ C ^ D`
- Rounds 49–64 (I): `C ^ (B | ~D)`

All bitwise operations are 32-bit unsigned. The reference and RTL must produce identical intermediate values for each round given the same block input.

### FC-FP-1.3: Per-round constants and shifts

Round `i` (1-based) adds the constant `K[i] = floor(abs(sin(i)) × 2^32)` interpreted as an unsigned 32-bit integer, then rotates by the specified amount:
- Rounds 1–16: shifts `[7,12,17,22]` repeating
- Rounds 17–32: shifts `[5,9,14,20]` repeating
- Rounds 33–48: shifts `[4,11,16,23]` repeating
- Rounds 49–64: shifts `[6,10,15,21]` repeating

The message-word index schedule is:
- Rounds 1–16: `i` (identity)
- Rounds 17–32: `(5i + 1) mod 16`
- Rounds 33–48: `(3i + 5) mod 16`
- Rounds 49–64: `(7i) mod 16`

The reference must encode these tables as literal arrays; the RTL may use generate loops or lookup tables but must yield the same schedule.

### FC-FP-1.4: Round update formula

For each round, with `F` being the round function output and `M[i]` the scheduled message word:
```
A_new = D
B_new = B + leftrot((A + F + K[i] + M[i]), shift[i])
C_new = B_old
D_new = C_old
```
where `leftrot(x, n) = (x << n) | (x >> (32-n))`, all additions are modulo 2^32. After 64 rounds, the block result is `(A+A_prev, B+B_prev, C+C_prev, D+D_prev)` added modulo 2^32 into the running state.

## FG-FP-2: Message padding and packing

### FC-FP-2.1: MD5 padding

The input message bit string is padded so that its length ≡ 448 (mod 512): a single `1` bit is appended, then `0` bits, then the original bit length as a 64-bit little-endian integer. The padded message is an exact multiple of 512-bit blocks. The reference must implement this padding internally from the byte-stream input; the RTL may pre-compute padding in the adapter or implement it in hardware.

### FC-FP-2.2: Little-endian word packing

Each 512-bit block is divided into sixteen 32-bit words, where word `j` is composed of bytes `4j..4j+3` of the block in little-endian order: `word[j] = b[4j] | b[4j+1]<<8 | b[4j+2]<<16 | b[4j+3]<<24`. The reference and RTL must use the same packing; big-endian packing is a functional error.

### FC-FP-2.3: Truncated 32-bit output

The RFC 1321 digest is the 16-byte string formed by concatenating the little-endian encodings of the four chaining variables in the order A, B, C, D. The module outputs only `D` on `hash_o`: the final value of the fourth chaining variable, equal to digest bytes 12–15 interpreted little-endian. For example, the empty-message digest `d41d8cd98f00b204e9800998ecf8427e` yields `hash_o = 0x7e42f8ec`. The reference must compute the full 128-bit digest internally but present the same truncation on the public API, so any word-order or endianness mistake in the DUT is caught.
