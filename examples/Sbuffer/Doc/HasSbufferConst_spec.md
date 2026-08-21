# HasSbufferConst Specification Document

> This document describes the specification of the `HasSbufferConst` chip verification target. Keep the technical language precise, well-organized, and easy to reuse for verification. If an item does not exist, explicitly write "None" or "TBD"; do not delete the section.

## Introduction
- **Design Background**: `HasSbufferConst` is a Chisel trait that computes and provides all parameter-derived constants used by the Sbuffer store buffer subsystem in the XiangShan high-performance RISC-V processor. It extends `HasXSParameter` (the XiangShan base parameter trait) to inherit base hardware configuration values such as `CacheLineSize`, `PAddrBits`, `VAddrBits`, `StoreBufferSize`, and `DataBytes`. From these base parameters, `HasSbufferConst` computes derived constants including cache geometry widths, address tag widths, timeout thresholds, index widths, and virtual word dimensions. Every Sbuffer module (`Sbuffer`, `SbufferData`) and Bundle type (via `SbufferBundle`) depends on `HasSbufferConst` for correct hardware width determination. Source: `HasSbufferConst.scala:1-27`, `engine_overview.txt:9, 34-48`, `phase_01_types.txt:101-116`.
- **Design Goals**: (1) Compute all Sbuffer-specific derived constants from the `HasXSParameter` base parameters at elaboration time. (2) Provide these constants as publicly readable members accessible through the Scala inheritance chain. (3) Guarantee that the same constant values are visible to all consuming modules and Bundles within a single elaboration context. (4) Compute derived constants using the formulas documented in the XiangShan architecture specification (address decomposition, cache geometry, entry indexing). (5) Enforce static invariants on configuration values (e.g., `EvictCycles` must be a power of 2).

## Terms and Abbreviations in Chisel Code

| Abbreviation | Full Term | Description |
| ---- | ---- | ---- |
| HasSbufferConst | Sbuffer Constants Trait | A Chisel trait providing parameter-derived constants to all Sbuffer modules and Bundles. Source: `HasSbufferConst.scala:1`. |
| HasXSParameter | XiangShan Parameter Trait | The base trait providing architecture-level parameters (CacheLineSize, VLEN, StoreBufferSize, etc.). Extended by HasSbufferConst. |
| EvictCycles | Eviction Cycles | Coherence timeout threshold in cycles, computed as 1 << 20 (1,048,576 cycles). Source: `engine_overview.txt:57`. |
| SbufferReplayDelayCycles | Replay Delay Cycles | Replay delay timeout in cycles after DCache replay response = 16. Source: `HasSbufferConst.scala:3`. |
| EvictCountBits | Eviction Count Bits | Bit width of coherence timeout counter = log2Up(EvictCycles + 1). Source: `HasSbufferConst.scala:5`. |
| MissqReplayCountBits | Miss Queue Replay Count Bits | Bit width of replay timeout counter = log2Up(SbufferReplayDelayCycles) + 1. Source: `HasSbufferConst.scala:6`. |
| NumDcacheWriteResp | DCache Write Response Count | Number of parallel DCache write response sources = 1 (hardcoded). Source: `HasSbufferConst.scala:11`. |
| SbufferIndexWidth | Sbuffer Index Width | Bit width for store buffer entry indexing = log2Up(StoreBufferSize). Source: `HasSbufferConst.scala:13`. |
| CacheLineBytes | Cache Line Bytes | Number of bytes per cache line = CacheLineSize / 8. Source: `HasSbufferConst.scala:15`. |
| CacheLineWords | Cache Line Words | Number of data words per cache line = CacheLineBytes / DataBytes. Source: `HasSbufferConst.scala:16`. |
| OffsetWidth | Offset Width | Bit width of byte offset within a cache line = log2Up(CacheLineBytes). Source: `HasSbufferConst.scala:17`. |
| WordsWidth | Word Width | Bit width for cache line word indexing = log2Up(CacheLineWords). Source: `HasSbufferConst.scala:18`. |
| PTagWidth | Physical Tag Width | Physical address tag bit width = PAddrBits - OffsetWidth. Source: `HasSbufferConst.scala:19`. |
| VTagWidth | Virtual Tag Width | Virtual address tag bit width = VAddrBits - OffsetWidth. Source: `HasSbufferConst.scala:20`. |
| WordOffsetWidth | Word Offset Width | Bit width for word offset = PAddrBits - WordsWidth. Source: `HasSbufferConst.scala:21`. |
| CacheLineVWords | Cache Line Virtual Words | Number of VLEN-width virtual words per cache line = CacheLineBytes / VDataBytes. Source: `HasSbufferConst.scala:23`. |
| VWordsWidth | Virtual Words Width | Bit width for virtual word indexing = log2Up(CacheLineVWords). Source: `HasSbufferConst.scala:24`. |
| VWordWidth | Virtual Word Width | Bit width for per-virtual-word byte indexing = log2Up(VDataBytes). Source: `HasSbufferConst.scala:25`. |
| VWordOffsetWidth | Virtual Word Offset Width | Bit width for virtual word offset = PAddrBits - VWordWidth. Source: `HasSbufferConst.scala:26`. |
| VLEN | Vector Length | Vector register width in bits (inherited from HasXSParameter). VDataBytes = VLEN / 8. |
| CacheLineSize | Cache Line Size | Cache line size in bits (inherited from HasXSParameter). |
| PAddrBits | Physical Address Bits | Physical address width in bits (inherited from HasXSParameter). |
| VAddrBits | Virtual Address Bits | Virtual address width in bits (inherited from HasXSParameter). |
| DataBytes | Data Bytes | Number of bytes per data word = VLEN/8 (inherited from HasXSParameter). |
| VDataBytes | Vector Data Bytes | Number of bytes per VLEN-width word = VLEN / 8 (inherited from HasXSParameter). |
| StoreBufferSize | Store Buffer Size | Total number of store buffer entries (inherited from HasXSParameter). |
| Parameters | Parameter Context | The implicit configuration object from which all base parameters originate. |

## Chisel Source Files

A single file defines the HasSbufferConst trait. It contains pure compile-time constant definitions with no hardware instantiation.

File list:
- `HasSbufferConst.scala:1-27`: Trait defining all Sbuffer parameter-derived constants. Includes `EvictCycles`, `SbufferReplayDelayCycles`, `EvictCountBits`, `MissqReplayCountBits`, `NumDcacheWriteResp`, and cache/address geometry constants (SbufferIndexWidth, CacheLineBytes, CacheLineWords, OffsetWidth, WordsWidth, PTagWidth, VTagWidth, WordOffsetWidth, CacheLineVWords, VWordsWidth, VWordWidth, VWordOffsetWidth). Source: `HasSbufferConst.scala:1-27`.

## Top-Level Interface Overview
- **Module Name**: `HasSbufferConst` (Chisel trait — not a Chisel Module)
- **Port List**: None. HasSbufferConst is a compile-time constant provider with no hardware ports. All members are `val` integer constants resolved at elaboration time.

  | Signal Name | Direction | Width/Type | Reset Value | Description |
  | ------ | ---- | -------- | ------ | ---- |
  | (none) | N/A | N/A | N/A | HasSbufferConst has no hardware ports. All exposed members are Scala Int constants. |

- **Clock and Reset Requirements**: None. HasSbufferConst is a pure constant-definition trait with no sequential elements and no clock/reset dependency.
- **External Dependencies**: HasSbufferConst extends `HasXSParameter` and depends on it to provide the following base parameters: `CacheLineSize`, `StoreBufferSize`, `PAddrBits`, `VAddrBits`, `DataBytes`, `VDataBytes`. All derived constants are computed from these base parameters. The implicit `p: Parameters` object carried through `HasXSParameter` must be in scope at elaboration time. Source: `HasSbufferConst.scala:1`. Consumers of HasSbufferConst (Sbuffer, SbufferData, SbufferBundle subclasses) depend on all constants being non-zero, positive integers, with `EvictCycles` being a power of 2 as enforced by `require(isPow2(EvictCycles))`. Source: `HasSbufferConst.scala:4`.

## Functional Description

### API — Test and Verification Interface

<FG-API>

- **Overview**: This functional group describes how a testbench verifies that HasSbufferConst correctly computes all derived constants from the base parameters inherited through HasXSParameter. Since HasSbufferConst is a compile-time trait with no runtime behavior, verification focuses on elaboration-time constant resolution: for a known set of base parameter values, every derived constant must equal the expected value computed from the documented formulas.
- **Execution Flow**: The testbench instantiates a concrete Chisel Module that mixes in HasSbufferConst (or any Sbuffer module that inherits it). The testbench supplies a known `Parameters` configuration with specific values for all HasXSParameter base parameters. During Chisel elaboration, the testbench reads each HasSbufferConst constant from the module instance and compares it against the expected value computed from the formulas documented in this spec. The test passes when all constants match and no elaboration error occurs.
- **Boundaries and Exceptions**:
  - HasSbufferConst delegates base parameter resolution to HasXSParameter. If HasXSParameter provides incorrect base parameter values, the derived constants will reflect those errors, but the formulas themselves must be correct.
  - The implicit `p: Parameters` must be in scope. Absence causes a Scala compile-time error.
  - HasSbufferConst has no runtime behavior — verification is elaboration-time only.
  - The `require(isPow2(EvictCycles))` assertion at `HasSbufferConst.scala:4` must not fire: `EvictCycles` (1 << 20) must be a power of 2. This is a static guarantee for all valid configurations.
- **Performance and Constraints**: All constant computation occurs at Scala compile time. HasSbufferConst introduces zero runtime (hardware) cost. Constants become literal values in generated Verilog.

#### Constant Value Verification

<FC-CONSTANT-VALUE-VERIFY>

Verify that each HasSbufferConst constant equals the expected value computed from the documented formula using the supplied base parameters.

**Check points:**
- <CK-EVICT-CYCLES-VALUE> With a valid Parameters object, verify `EvictCycles` = 1 << 20 (1,048,576). Verify `isPow2(EvictCycles)` is true.
- <CK-REPLAY-DELAY-VALUE> Verify `SbufferReplayDelayCycles` = 16.
- <CK-EVICT-COUNT-BITS-VALUE> Verify `EvictCountBits` = log2Up(EvictCycles + 1). With EvictCycles = 1 << 20, expected value = 21.
- <CK-MISSQ-REPLAY-COUNT-BITS-VALUE> Verify `MissqReplayCountBits` = log2Up(SbufferReplayDelayCycles) + 1. With SbufferReplayDelayCycles = 16, expected value = 6.
- <CK-NUM-DCACHE-WRITE-RESP-VALUE> Verify `NumDcacheWriteResp` = 1.

#### Cache Geometry Constant Verification

<FC-CACHE-GEOMETRY>

Verify that all cache-line and address geometry constants are computed from the correct formulas based on `CacheLineSize`, `PAddrBits`, `VAddrBits`, and `DataBytes` inherited from HasXSParameter.

**Check points:**
- <CK-CACHE-LINE-BYTES> With CacheLineSize = CLS, verify `CacheLineBytes` = CLS / 8.
- <CK-CACHE-LINE-WORDS> With CacheLineBytes = CLB and DataBytes = DB, verify `CacheLineWords` = CLB / DB.
- <CK-OFFSET-WIDTH> With CacheLineBytes = CLB, verify `OffsetWidth` = log2Up(CLB). With CLB=64, OffsetWidth = 6.
- <CK-WORDS-WIDTH> With CacheLineWords = CLW, verify `WordsWidth` = log2Up(CLW).
- <CK-PTAG-WIDTH> With PAddrBits = P and OffsetWidth = O, verify `PTagWidth` = P - O.
- <CK-VTAG-WIDTH> With VAddrBits = V and OffsetWidth = O, verify `VTagWidth` = V - O.
- <CK-WORD-OFFSET-WIDTH> With PAddrBits = P and WordsWidth = W, verify `WordOffsetWidth` = P - W.

#### Virtual Word Geometry Constant Verification

<FC-VIRTUAL-WORD-GEOMETRY>

Verify that virtual word and index constants are computed from `CacheLineBytes` and `VDataBytes` (inherited from HasXSParameter).

**Check points:**
- <CK-CACHE-LINE-VWORDS> With CacheLineBytes=C and VDataBytes=D, verify `CacheLineVWords` = C / D. With C=64, D=16, value = 4. With C=64, D=8, value = 8.
- <CK-VWORDS-WIDTH> With CacheLineVWords=VW, verify `VWordsWidth` = log2Up(VW). With VW=4, value = 2. With VW=8, value = 3.
- <CK-VWORD-WIDTH> With VDataBytes=D, verify `VWordWidth` = log2Up(D). With D=16, value = 4.
- <CK-VWORD-OFFSET-WIDTH> With PAddrBits=P and VWordWidth=V, verify `VWordOffsetWidth` = P - V.

#### Sbuffer Index Width Verification

<FC-SBUF-INDEX-WIDTH>

Verify that `SbufferIndexWidth` is computed as log2Up(StoreBufferSize) from the `StoreBufferSize` base parameter.

**Check points:**
- <CK-SBUF-INDEX-MIN> With StoreBufferSize=1, verify `SbufferIndexWidth` = 0.
- <CK-SBUF-INDEX-TYPICAL> With StoreBufferSize=16, verify `SbufferIndexWidth` = 4. With StoreBufferSize=8, verify `SbufferIndexWidth` = 3.
- <CK-SBUF-INDEX-POWER-OF-TWO> With StoreBufferSize=32, verify `SbufferIndexWidth` = 5.

#### Elaboration-Time Invariant Enforcement

<FC-ELABORATION-INVARIANTS>

Verify that HasSbufferConst enforces static invariants at elaboration time. The `require(isPow2(EvictCycles))` check must pass for the default EvictCycles value (1 << 20), and all derived constants must be non-negative integers.

**Check points:**
- <CK-EVICT-IS-POW2> Verify that `require(isPow2(EvictCycles))` does not fire during elaboration with default EvictCycles = 1 << 20.
- <CK-ALL-CONSTANTS-NON-NEGATIVE> Enumerate all HasSbufferConst constants. Verify every constant is >= 0. In particular, `PTagWidth`, `VTagWidth`, and `WordOffsetWidth` must be non-negative (implying PAddrBits >= OffsetWidth, VAddrBits >= OffsetWidth, PAddrBits >= WordsWidth). Verify that `CacheLineWords` and `CacheLineVWords` are >= 1.

#### Consistency Across Consumers

<FC-CONSTANT-CONSISTENCY>

Verify that all HasSbufferConst constants have identical values when accessed from different consuming modules and Bundles within the same elaboration context (same `p: Parameters`).

**Check points:**
- <CK-CROSS-MODULE-CONSISTENT> Instantiate Sbuffer and SbufferData with the same Parameters. Verify that `StoreBufferSize`, `CacheLineVWords`, `VDataBytes`, and all other shared constants have identical values in both instances.
- <CK-CROSS-BUNDLE-CONSISTENT> Instantiate DataWriteReq and MaskFlushReq with the same Parameters. Verify `StoreBufferSize` is identical in both Bundle instances.
- <CK-IMMUTABLE> Read a constant from one instance, then read it again from the same or another instance. Verify the value is unchanged (constants are `val`, not `var`).

### Timeout Constant Configuration

<FG-TIMEOUT-CONFIGURATION>

- **Overview**: HasSbufferConst defines the coherence timeout threshold (`EvictCycles`) and the replay delay timeout (`SbufferReplayDelayCycles`), plus their derived counter bit widths (`EvictCountBits`, `MissqReplayCountBits`). The coherence timeout counter uses an `EvictCountBits`-bit counter per entry where the MSB signals timeout (at bit `EvictCountBits - 1` = `log2Up(EvictCycles+1) - 1` = 20, which asserts once the counter reaches `2^20 = EvictCycles`, i.e. after ~EvictCycles cycles). The replay counter uses a `MissqReplayCountBits`-bit counter triggering on MSB assertion.
- **Execution Flow**: These constants are consumed by the Sbuffer module to dimension `cohCount` and `missqReplayCount` register files. At elaboration time, `EvictCountBits` and `MissqReplayCountBits` set the register widths; `EvictCycles` and `SbufferReplayDelayCycles` define the timeout thresholds that the consuming logic uses for MSB-based timeout detection (counter bit width minus one determines the MSB position). Source: `HasSbufferConst.scala:2-6`.
- **Boundaries and Exceptions**:
  - `EvictCycles` must be a power of 2, enforced by `require(isPow2(EvictCycles))`. If this invariant is violated, Chisel elaboration fails.
  - The timeout detection logic in Sbuffer uses `cohCount(i)(EvictCountBits-1)` to detect timeout. Since `EvictCycles` is a power of 2, `EvictCountBits = log2Up(EvictCycles+1) = log2(EvictCycles)+1`, so the MSB (bit `EvictCountBits-1`) asserts when the counter reaches `2^(EvictCountBits-1) = EvictCycles`, i.e. after ~EvictCycles cycles.
  - SbufferReplayDelayCycles has no power-of-2 constraint. The replay counter width accommodates it: `MissqReplayCountBits = log2Up(SbufferReplayDelayCycles) + 1`.
- **Performance and Constraints**: Timeout thresholds are elaboration-time constants. There is no runtime reconfiguration of timeout values through HasSbufferConst.

#### Coherence Timeout Constant

<FC-COHERENCE-TIMEOUT>

Verify that `EvictCycles` equals 1 << 20 and `EvictCountBits` accommodates the full cycle count plus one (for the reset-zero state).

**Check points:**
- <CK-EVICT-CYCLES-DEFAULT> Verify `EvictCycles` = 1,048,576 (1 << 20).
- <CK-EVICT-COUNT-BITS-RANGE> Verify `EvictCountBits` = 21, so the counter MSB is bit 20. The counter counts from 0 to (2^20) - 1 = 1,048,575 cycles before the MSB asserts.

#### Replay Delay Constant

<FC-REPLAY-DELAY>

Verify that `SbufferReplayDelayCycles` equals 16 and `MissqReplayCountBits` correctly accommodates the timeout threshold.

**Check points:**
- <CK-REPLAY-DELAY-DEFAULT> Verify `SbufferReplayDelayCycles` = 16.
- <CK-REPLAY-COUNT-BITS-RANGE> Verify `MissqReplayCountBits` = 6. With 6 bits, the counter counts from 0 to 31, and the MSB (bit 5) asserts after 16 cycles (counter value reaches 16).

### Address Decomposition Constants

<FG-ADDRESS-DECOMPOSITION>

- **Overview**: HasSbufferConst computes the address decomposition constants that define how physical and virtual addresses are split into tag and offset portions. The physical address `paddr = {ptag, offset}`, where `ptag = pa[PAddrBits-1 : OffsetWidth]` and `offset = pa[OffsetWidth-1 : 0]`. The virtual tag analogously uses `VTagWidth`. The word offset uses `WordsWidth` to index cache-line words, and the virtual word offset uses `VWordWidth` to index VLEN-width virtual words. Source: `HasSbufferConst.scala:13-26`, `phase_01_types.txt:90-99`, `engine_overview.txt:42-44`.
- **Execution Flow**: At elaboration time, `OffsetWidth`, `PTagWidth`, `VTagWidth`, `WordOffsetWidth`, and `VWordOffsetWidth` are computed from the base address width and cache line size parameters. These constants are consumed by the Sbuffer module for address extraction (`getPTag`, `getVTag`, `getVWordOffset`, etc.) and for ptag/vtag register file widths. The consuming hardware uses these widths to slice physical/virtual addresses into tags and offsets.
- **Boundaries and Exceptions**:
  - The address decomposition must be self-consistent: `PTagWidth + OffsetWidth = PAddrBits` and `VTagWidth + OffsetWidth = VAddrBits`. Violation indicates a mismatch between HasXSParameter base values and the decomposition formulas.
  - `WordOffsetWidth + WordsWidth = PAddrBits` must hold.
  - `VWordOffsetWidth + VWordWidth = PAddrBits` must hold.
  - All computed widths must be non-negative, implying `PAddrBits >= OffsetWidth`, `VAddrBits >= OffsetWidth`, `PAddrBits >= WordsWidth`, `PAddrBits >= VWordWidth`.
- **Performance and Constraints**: All constants are elaboration-time. Address decomposition formulas are static.

#### Physical and Virtual Tag Widths

<FC-TAG-WIDTHS>

Verify that physical and virtual tag widths partition their respective address spaces correctly.

**Check points:**
- <CK-PTAG-WIDTH-PARTITION> With PAddrBits=P and OffsetWidth=O, verify `PTagWidth` = P - O. Verify PTagWidth + OffsetWidth = PAddrBits.
- <CK-VTAG-WIDTH-PARTITION> With VAddrBits=V and OffsetWidth=O, verify `VTagWidth` = V - O. Verify VTagWidth + OffsetWidth = VAddrBits.
- <CK-TAG-WIDTHS-NON-NEGATIVE> Verify PTagWidth >= 0 and VTagWidth >= 0.

#### Word and Virtual Word Offset Widths

<FC-WORD-OFFSET-WIDTHS>

Verify that word-level and virtual-word-level offset widths partition the physical address space.

**Check points:**
- <CK-WORD-OFFSET-CONSISTENT> With PAddrBits=P and WordsWidth=W, verify `WordOffsetWidth` = P - W. Verify WordOffsetWidth + WordsWidth = PAddrBits.
- <CK-VWORD-OFFSET-CONSISTENT> With PAddrBits=P and VWordWidth=V, verify `VWordOffsetWidth` = P - V. Verify VWordOffsetWidth + VWordWidth = PAddrBits.
- <CK-OFFSET-WIDTH-CONSISTENT> With CacheLineBytes=CLB, verify `OffsetWidth` = log2Up(CLB). For CLB=64, OffsetWidth=6.

### Subcomponent Description

(no submodules) — HasSbufferConst is a pure Chisel trait with no instantiated child modules, no hardware units, and no internal components. It extends `HasXSParameter` as a parent trait, but `HasXSParameter` is a trait (not a Module) providing base parameters. All members of HasSbufferConst are compile-time `val` integer constants. Source: `HasSbufferConst.scala:1-27`.

### State Machines and Timing
- **State Machine List**: None. HasSbufferConst is a compile-time trait with no sequential elements, no state machine, and no state registers.
- **State Transition Conditions**: N/A.
- **Key Timing**: N/A. HasSbufferConst introduces zero cycles of latency. All constant computation occurs at Scala compilation / Chisel elaboration time. At the hardware level, constants become literal values in the generated Verilog with no gate-level impact.

### Configuration Registers and Storage
None — HasSbufferConst defines no registers, memory, or configurable storage elements. All members are immutable `val` Scala integer constants.

- **Register Map Base Address**: No bus interface. HasSbufferConst is a compile-time trait with no addressable registers.
- **Configuration Flow**: N/A. All constants are statically computed from the `HasXSParameter` base parameters at elaboration time. There is no runtime configuration mechanism.

### Reset and Error Handling
- **Reset Behavior**: N/A. HasSbufferConst has no sequential elements and thus no reset behavior.
- **Error Reporting**: The only error detection in HasSbufferConst is the `require(isPow2(EvictCycles))` assertion at `HasSbufferConst.scala:4`. This is a Chisel elaboration-time assertion — if `EvictCycles` is not a power of 2, Chisel elaboration fails with a runtime exception before Verilog is generated. `NumDcacheWriteResp` is hardcoded to 1; change requires source modification. No other assertions or error signals exist.
- **Self-Recovery Strategy**: None. Errors are compile-time only.

### Parameterization and Configurable Features
- **Module Parameters**:

  | Parameter Name | Type/Range | Default | Functional Effect |
  | ------ | ------------- | ------ | -------- |
  | EvictCycles | Int | 1 << 20 (1,048,576) | Coherence timeout threshold in cycles. Affects EvictCountBits and the coherence timeout trigger behavior in Sbuffer. Must be a power of 2 (enforced by require). Source: `HasSbufferConst.scala:2, 4`. |
  | SbufferReplayDelayCycles | Int | 16 | Replay delay cycles after DCache replay response. Affects MissqReplayCountBits and the replay timeout trigger behavior in Sbuffer. Source: `HasSbufferConst.scala:3`. |
  | EvictCountBits | Int | log2Up(EvictCycles + 1) ≈ 21 | Bit width of coherence timeout counter registers. Determines the MSB position for timeout detection (bit EvictCountBits - 1). Source: `HasSbufferConst.scala:5`. |
  | MissqReplayCountBits | Int | log2Up(SbufferReplayDelayCycles) + 1 ≈ 6 | Bit width of replay timeout counter registers. Determines the MSB position for replay timeout detection. Source: `HasSbufferConst.scala:6`. |
  | NumDcacheWriteResp | Int | 1 | Number of DCache write response input ports. Determines Vec width of hit_resps in DCache interface. Hardcoded; changing requires source modification. Source: `HasSbufferConst.scala:11`. |
  | SbufferIndexWidth | Int | log2Up(StoreBufferSize) | Bit width for store buffer entry indexing. Affects wvec one-hot width indirectly (StoreBufferSize bits, but index width for addressing). Source: `HasSbufferConst.scala:13`. |
  | CacheLineBytes | Int | CacheLineSize / 8 | Number of bytes per cache line. Affects OffsetWidth, CacheLineWords, CacheLineVWords. Source: `HasSbufferConst.scala:15`. |
  | CacheLineWords | Int | CacheLineBytes / DataBytes | Number of data words per cache line. Affects WordsWidth, data array second dimension. Source: `HasSbufferConst.scala:16`. |
  | OffsetWidth | Int | log2Up(CacheLineBytes) | Bit width of byte offset within a cache line. Affects PTagWidth, VTagWidth, address extraction hardware. Source: `HasSbufferConst.scala:17`. |
  | WordsWidth | Int | log2Up(CacheLineWords) | Bit width for word-level indexing within a cache line. Affects WordOffsetWidth. Source: `HasSbufferConst.scala:18`. |
  | PTagWidth | Int | PAddrBits - OffsetWidth | Physical address tag bit width. Affects ptag register file width, address reconstruction hardware. Source: `HasSbufferConst.scala:19`. |
  | VTagWidth | Int | VAddrBits - OffsetWidth | Virtual address tag bit width. Affects vtag register file width, forward CAM matching hardware. Source: `HasSbufferConst.scala:20`. |
  | WordOffsetWidth | Int | PAddrBits - WordsWidth | Bit width for word offset within cache line. Affects address extraction for word-level operations. Source: `HasSbufferConst.scala:21`. |
  | CacheLineVWords | Int | CacheLineBytes / VDataBytes | Number of VLEN-width virtual words per cache line. Affects SbufferData array dimensions, VWordsWidth, and per-entry write iteration bounds. Source: `HasSbufferConst.scala:23`. |
  | VWordsWidth | Int | log2Up(CacheLineVWords) | Bit width for virtual word indexing. Affects address extraction for virtual-word-level operations. Source: `HasSbufferConst.scala:24`. |
  | VWordWidth | Int | log2Up(VDataBytes) | Bit width for per-virtual-word byte indexing. Affects VWordOffsetWidth. Source: `HasSbufferConst.scala:25`. |
  | VWordOffsetWidth | Int | PAddrBits - VWordWidth | Bit width for virtual word offset within a cache line. Affects DataWriteReq.vwordOffset field width. Source: `HasSbufferConst.scala:26`. |

  All constants are derived from base parameters inherited through `HasXSParameter`. HasSbufferConst defines no additional constructor parameters beyond what `HasXSParameter` provides.

- **Runtime Configuration**: None. All constants are fixed at elaboration time and cannot change at runtime.
- **Compile Macros/Generation Options**: None. HasSbufferConst has no conditional compilation or preprocessor macros beyond the standard Chisel/`require` elaboration checks.

## Verification Requirements and Coverage Suggestions
- **Functional Coverage Points**: All `CK-*` check points defined in each functional group constitute coverage targets. Key cross-coverage scenarios:
  - Constant values for minimum valid configuration (smallest StoreBufferSize, CacheLineSize, VLEN).
  - Constant values for maximum realistic configuration (large StoreBufferSize, VLEN=256).
  - Verify all derived constant formulas compute zero-width or minimum-width values when base parameters are at their minima (e.g., CacheLineBytes = DataBytes → CacheLineWords = 1, WordsWidth = 0).
  - Verify invariance: constants must not change across multiple reads from different consumer instances.
  - Verify `require(isPow2(EvictCycles))` passes for the default value and would fail for a non-power-of-2 value (negative test at elaboration time).
- **Constraints and Assumptions**:
  - A valid `Parameters` object must be in implicit scope providing all HasXSParameter base parameters (CacheLineSize, StoreBufferSize, PAddrBits, VAddrBits, DataBytes, VDataBytes).
  - Base parameter values are assumed to be consistent with XiangShan architecture constraints (e.g., CacheLineSize >= VLEN, PAddrBits >= log2Up(CacheLineBytes)).
  - Verification is elaboration-time: test passes when Chisel elaboration succeeds without assertion failures and all constant equality checks hold.
  - HasSbufferConst is an extension point for Sbuffer configuration. Verification should cover both default values and alternate configurations where base parameters differ.
- **Test Interfaces**:
  - **Constant Inspector**: Instantiate a Chisel Module or Bundle that mixes in HasSbufferConst. Read each constant as a Scala Int value. Compare against expected values computed from the base Parameter values using the formulas documented in this spec.
  - **Formula Verifier**: For each derived constant, programmatically compute the expected value from the documented formula and the base parameters. Assert equality with the actual constant value read from the trait instance.
  - **Elaboration Success Monitor**: Verify that Chisel elaboration (FIRRTL generation) completes without exception when HasSbufferConst is mixed into a valid module with legal base parameters. This confirms `require(isPow2(EvictCycles))` and all width computations succeed.
  - **Cross-Instance Consistency Checker**: Create two different modules or Bundles both mixing in HasSbufferConst from the same Parameters. Verify all constants are identical across instances.
  - **Edge Configuration Driver**: Supply edge-case Parameters (minimum cache size, minimum buffer size, VLEN=64) and verify all constants resolve to correct non-negative values without elaboration failure.
