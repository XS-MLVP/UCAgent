# SbufferBundle Specification Document

> This document describes the specification of the `SbufferBundle` chip verification target. Keep the technical language precise, well-organized, and easy to reuse for verification. If an item does not exist, explicitly write "None" or "TBD"; do not delete the section.

## Introduction
- **Design Background**: `SbufferBundle` is the base Chisel Bundle class for all Sbuffer-specific Bundle types in the XiangShan high-performance RISC-V processor. It extends `XSBundle` (the XiangShan base Bundle class) and mixes in `HasSbufferConst` (the trait providing parameter-derived constants for the store buffer subsystem). Every Sbuffer Bundle type — `DataWriteReq`, `MaskFlushReq`, and `SbufferEntryState` — extends `SbufferBundle` to inherit field width parameters and the implicit `Parameters` context. Source: `SbufferBundle.scala:1`, `engine_overview.txt:9`, `phase_01_types.txt:40-42`.
- **Design Goals**: (1) Provide a single inheritance point that combines the XiangShan Bundle base (`XSBundle`) with the Sbuffer parameter trait (`HasSbufferConst`), so that all Sbuffer Bundle subtypes automatically receive both. (2) Carry the implicit `Parameters` argument from the Chisel elaboration context through the inheritance chain into every Sbuffer Bundle subclass. (3) Guarantee that every Sbuffer Bundle subclass can reference `HasSbufferConst` constants (e.g., `StoreBufferSize`, `VLEN`, `VWordOffsetWidth`) without separately declaring the `HasSbufferConst` mixin or `implicit p: Parameters`. (4) Serve as the type anchor for wire-level parameter resolution — the parameter values available through `SbufferBundle` determine the bit widths of fields in all subclass Bundles at elaboration time.

## Terms and Abbreviations in Chisel Code

| Abbreviation | Full Term | Description |
| ---- | ---- | ---- |
| SbufferBundle | Sbuffer Bundle Base | The base Chisel Bundle class that all Sbuffer-specific Bundles extend. Combines XSBundle and HasSbufferConst. Source: `SbufferBundle.scala:1`. |
| XSBundle | XiangShan Bundle Base | The base Bundle class for all XiangShan hardware types. Provides the `p: Parameters` constructor argument and standard Chisel Bundle behavior. |
| HasSbufferConst | Sbuffer Constants Trait | A Chisel trait that computes and provides parameter-derived constants used by all Sbuffer modules and Bundles. Mixed into SbufferBundle so that every Sbuffer Bundle subclass can reference these constants. |
| Parameters | Chisel Parameter Context | An implicit parameter object carrying the full hardware configuration (cache size, VLEN, StoreBufferSize, etc.) from the XiangShan top-level config. Propagated through the inheritance chain. |
| StoreBufferSize | Store Buffer Size | The number of entries in the store buffer. Determines `wvec` bit width in DataWriteReq and MaskFlushReq. Source: `engine_overview.txt:52`. |
| VLEN | Vector Length | Vector register length in bits. Determines `data` bit width and `mask` bit width (VLEN/8) in DataWriteReq. Source: `engine_overview.txt:40`. |
| VWordOffsetWidth | Virtual Word Offset Width | Width of the vwordOffset field, computed as log2Ceil(CacheLineVWords) by HasSbufferConst. Determines `vwordOffset` bit width in DataWriteReq. Source: `phase_01_types.txt:56`. |
| EvictCycles | Eviction Cycles | Coherence timeout threshold, computed as `1 << 20` cycles. Source: `engine_overview.txt:57`. |
| SbufferIndexWidth | Sbuffer Index Width | Bit width for indexing into the store buffer, computed as log2Up(StoreBufferSize). Source: `phase_01_types.txt:108`. |
| OffsetWidth | Offset Width | Bit width of the byte offset within a cache line, computed as log2Up(CacheLineBytes). Source: `phase_01_types.txt:111`. |
| CacheLineVWords | Cache Line Virtual Words | Number of VLEN-width virtual words per cache line, computed as CacheLineBytes / VDataBytes. Source: `phase_01_types.txt:115`. |

## Chisel Source Files

A single file defines the SbufferBundle class. This is a pure class declaration with no fields, no methods, and no instantiations.

File list:
- `SbufferBundle.scala:1`: Class declaration of `SbufferBundle`, extending `XSBundle` with `HasSbufferConst`, carrying `implicit p: Parameters`. One-line definition with no body content. Source: `SbufferBundle.scala:1`.

## Top-Level Interface Overview
- **Module Name**: `SbufferBundle` (Chisel Bundle base class — not a Chisel Module)
- **Port List**: None. SbufferBundle is a base Bundle class with no IO ports of its own. It is a pure inheritance convenience class that carries the `XSBundle` base type and `HasSbufferConst` parameter mixin. Individual ports are defined by subclasses (DataWriteReq, MaskFlushReq, SbufferEntryState) that extend SbufferBundle.

  | Signal Name | Direction | Width/Type | Reset Value | Description |
  | ------ | ---- | -------- | ------ | ---- |
  | (none) | N/A | N/A | N/A | SbufferBundle has no ports. It is a parameter-carrier class. |

- **Clock and Reset Requirements**: N/A. SbufferBundle is a passive wire Bundle base class with no sequential elements. Clock and reset requirements are the responsibility of subclasses and instantiating modules.
- **External Dependencies**: SbufferBundle depends on two parent types:
  - `XSBundle`: The XiangShan base Bundle class. This provides the standard Chisel `Bundle` behavior (wire grouping, direction assignment via `Flipped`, port connection semantics) and accepts the implicit `p: Parameters` constructor argument.
  - `HasSbufferConst`: A Chisel trait that computes and makes available all Sbuffer parameter-derived constants. These constants include but are not limited to: `StoreBufferSize`, `VLEN`, `VWordOffsetWidth`, `EvictCycles`, `SbufferReplayDelayCycles`, `SbufferIndexWidth`, `CacheLineBytes`, `OffsetWidth`, `PTagWidth`, `VTagWidth`, `CacheLineVWords`, `VWordsWidth`, `EvictCountBits`, `MissqReplayCountBits`, `NumDcacheWriteResp`, `EnsbufferWidth`, `StorePipelineWidth`, `LoadPipelineWidth`.

  Every Sbuffer Bundle subclass (DataWriteReq, MaskFlushReq, SbufferEntryState) depends on SbufferBundle to provide both the `XSBundle` base type and the `HasSbufferConst` constants. Each subclass uses one or more of these constants to determine its field bit widths. Source: `DataWriteReq.scala:1-9`, `MaskFlushReq.scala:1-4`, `SbufferEntryState.scala:1-12`.

## Functional Description

### API — Test and Verification Interface

<FG-API>

- **Overview**: This functional group describes how a testbench verifies that SbufferBundle correctly provides parameter-derived constants to its subclasses. Since SbufferBundle is a compile-time parameter-carrier class with no runtime behavior, verification focuses on elaboration-time constant resolution: all HasSbufferConst constants must be accessible from any Bundle that extends SbufferBundle, and constant values must be consistent with the Parameters object passed at elaboration.
- **Execution Flow**: The testbench instantiates a concrete SbufferBundle subclass (e.g., DataWriteReq) by passing a known `Parameters` configuration object. The testbench then reads the constant values inherited through SbufferBundle (StoreBufferSize, VLEN, VWordOffsetWidth, etc.) from the instantiated Bundle or a companion object. The testbench verifies each constant matches the expected value derived from the input Parameters.
- **Boundaries and Exceptions**:
  - SbufferBundle delegates all constant computation to HasSbufferConst. If HasSbufferConst produces an incorrect constant, the error appears in the subclass's field widths, not in SbufferBundle itself.
  - The implicit `p: Parameters` argument must be in scope at the point of instantiation. Absence of the implicit causes a Chisel elaboration failure (compile-time error).
  - SbufferBundle has no runtime behavior, so testbench cannot exercise it at runtime — verification is compile-time / elaboration-time only.
- **Performance and Constraints**: SbufferBundle introduces zero runtime overhead. All constant resolution occurs at Chisel elaboration time. The class adds no additional port logic, no wire, and no gate delay.

#### Parameter Constant Inheritance

<FC-PARAM-INHERITANCE>

The primary function of SbufferBundle is to ensure that every subclass can access HasSbufferConst constants through the normal Scala/Chisel inheritance mechanism. Any Bundle extending SbufferBundle must have all HasSbufferConst constants in scope without requiring a separate `with HasSbufferConst` declaration.

**Check points:**
- <CK-STORE-BUFFER-SIZE-ACCESSIBLE> Instantiate a subclass Bundle (e.g., DataWriteReq) extending SbufferBundle with a known Parameters config where StoreBufferSize=16. Verify that `StoreBufferSize` is accessible from the Bundle instance and equals 16.
- <CK-VLEN-ACCESSIBLE> With a Parameters config where VLEN=128, verify that `VLEN` is accessible and equals 128. Verify that the derived constant `VLEN/8` equals 16.
- <CK-VWORD-OFFSET-WIDTH-ACCESSIBLE> With a Parameters config where CacheLineBytes=64 and VDataBytes=16 (CacheLineVWords=4), verify that `VWordOffsetWidth` is accessible and equals log2Ceil(4) = 2.
- <CK-ALL-CONSTANTS-ACCESSIBLE> Verify that all HasSbufferConst constants (StoreBufferSize, VLEN, VWordOffsetWidth, EvictCycles, SbufferIndexWidth, CacheLineBytes, OffsetWidth, PTagWidth, VTagWidth, CacheLineVWords, VWordsWidth, EvictCountBits, MissqReplayCountBits, NumDcacheWriteResp) are accessible from any Bundle extending SbufferBundle.

#### XSBundle Base Behavior Inheritance

<FC-XSBUNDLE-INHERITANCE>

SbufferBundle extends XSBundle, so any Bundle subclass of SbufferBundle must also exhibit standard Chisel Bundle behavior: wire grouping, direction assignment via `Flipped`, port connection semantics, and acceptance of the implicit `p: Parameters` constructor argument.

**Check points:**
- <CK-FLIPPED-WORKS> Instantiate a Vec containing `Flipped(ValidIO(new DataWriteReq))` (where DataWriteReq extends SbufferBundle). Verify that the Bundle can be direction-reversed via Flipped and used in a ValidIO wrapper without elaboration error.
- <CK-PARAMETERS-IMPLICIT> Verify that the implicit `p: Parameters` propagates from SbufferBundle's constructor to the subclass constructor. Instantiate a subclass with an explicit `p` and verify the constants resolve correctly.
- <CK-IS-BUNDLE> Verify via Chisel reflection that an instance of a subclass of SbufferBundle is recognized as a `chisel3.Bundle` at elaboration time (it passes `isInstanceOf[Bundle]`).

#### Constant Consistency Across Subclasses

<FC-CONSTANT-CONSISTENCY>

All SbufferBundle subclasses within the same elaboration context (same `p: Parameters`) must see the same constant values. There is no per-subclass override or mutation of HasSbufferConst constants.

**Check points:**
- <CK-CONSISTENT-STORE-BUFFER-SIZE> Instantiate DataWriteReq and MaskFlushReq (both extending SbufferBundle) with the same Parameters object. Verify `StoreBufferSize` is identical in both instances.
- <CK-CONSISTENT-VLEN> Instantiate DataWriteReq and SbufferEntryState with the same Parameters object. Verify `VLEN` is identical in both.
- <CK-NO-MUTATION> In a testbench that creates multiple instances of the same subclass, verify that reading a constant from one instance does not change the value read from another instance.

### Parameter Provision for Field Width Determination

<FG-PARAM-PROVISION>

- **Overview**: SbufferBundle's primary observable contract is that it makes all HasSbufferConst constants available to subclass Bundles so they can determine their field bit widths. Each subclass uses a specific subset of these constants: DataWriteReq uses StoreBufferSize (wvec width), VLEN (data and mask widths), and VWordOffsetWidth (vwordOffset width); MaskFlushReq uses StoreBufferSize (wvec width); SbufferEntryState uses no parameterized widths (all fields are Bool) but requires the constants to be in scope for Chisel elaboration correctness.
- **Execution Flow**: At Chisel elaboration time, when a subclass Bundle (e.g., `new DataWriteReq`) is instantiated, the Scala constructor chain calls SbufferBundle's constructor, which triggers HasSbufferConst initialization. HasSbufferConst reads the implicit `p: Parameters` and computes all derived constants. These constants are then available as inherited members of the subclass instance. The subclass's field declarations (e.g., `val wvec = UInt(StoreBufferSize.W)`) resolve `StoreBufferSize` via the inherited scope.
- **Boundaries and Exceptions**:
  - If the implicit `p: Parameters` is not in scope at instantiation time, Chisel elaboration fails with a compile-time error. This is a static guarantee, not a runtime failure.
  - SbufferBundle does not validate that its constants are non-zero or within legal ranges — this validation is the responsibility of the caller config or HasSbufferConst itself.
  - Parameter values are fixed at elaboration time and cannot change at runtime. There is no dynamic reconfiguration mechanism through SbufferBundle.
- **Performance and Constraints**: All constant resolution is static (compile-time). SbufferBundle introduces zero gates, zero wires, and zero critical path at the hardware level. The constants become literal values in the generated Verilog.

#### Store Buffer Size Provision

<FC-STORE-BUFFER-SIZE-PROVISION>

The `StoreBufferSize` constant determines the bit width of the `wvec` one-hot field in DataWriteReq and MaskFlushReq. SbufferBundle guarantees this constant is available with the correct value derived from the Parameters object.

**Check points:**
- <CK-SBUF-SIZE-WVEC-MATCH> With StoreBufferSize=S, instantiate DataWriteReq and verify `wvec.getWidth` equals S bits. Source: `DataWriteReq.scala:3`.
- <CK-SBUF-SIZE-MASK-FLUSH-WVEC-MATCH> With StoreBufferSize=S, instantiate MaskFlushReq and verify `wvec.getWidth` equals S bits. Source: `MaskFlushReq.scala:3`.

#### VLEN and Derived Width Provision

<FC-VLEN-PROVISION>

The `VLEN` constant determines the bit width of the `data` and `mask` fields in DataWriteReq (mask width = VLEN/8). SbufferBundle guarantees VLEN is available with the correct value.

**Check points:**
- <CK-VLEN-DATA-MATCH> With VLEN=V, instantiate DataWriteReq and verify `data.getWidth` equals V bits. Source: `DataWriteReq.scala:6`.
- <CK-VLEN-MASK-MATCH> With VLEN=V, instantiate DataWriteReq and verify `mask.getWidth` equals V/8 bits. Source: `DataWriteReq.scala:5`.

#### Virtual Word Offset Width Provision

<FC-VWORD-OFFSET-WIDTH-PROVISION>

The `VWordOffsetWidth` constant determines the bit width of the `vwordOffset` field in DataWriteReq. SbufferBundle guarantees this constant is available with the correct value, computed as log2Ceil(CacheLineVWords).

**Check points:**
- <CK-VWORD-OFFSET-WIDTH-MATCH> With CacheLineBytes=C and VDataBytes=D (so CacheLineVWords = C/D), verify `VWordOffsetWidth` equals log2Ceil(C/D). Instantiate DataWriteReq and verify `vwordOffset.getWidth` equals `VWordOffsetWidth`. Source: `DataWriteReq.scala:7`.

### Subcomponent Description

(no subcomponents) — SbufferBundle is a pure inheritance base class with no internal submodules, no instantiated hardware units, and no child components. It extends two parent types (`XSBundle` as a class extension, `HasSbufferConst` as a trait mixin), neither of which is a Chisel Module or hardware unit. The class body is empty — it contains no field declarations, no method definitions, no module instantiations, and no wire/register assignments. Source: `SbufferBundle.scala:1`.

### State Machines and Timing
- **State Machine List**: None. SbufferBundle is a passive Bundle base class with no sequential elements, no state machine, and no state register.
- **State Transition Conditions**: N/A.
- **Key Timing**: N/A. SbufferBundle introduces zero cycles of latency. It is an elaboration-time construct only — all constant resolution occurs at compile time. At the hardware level, SbufferBundle contributes no gates or wires.

### Configuration Registers and Storage
None — SbufferBundle is a parameter-carrier class with no registers, memory, or configurable storage elements.

- **Register Map Base Address**: No bus interface. SbufferBundle is a wire-level Bundle base class with no addressable registers.
- **Configuration Flow**: N/A. The `Parameters` object is passed at elaboration time through the implicit constructor argument; there is no runtime configuration through SbufferBundle. All HasSbufferConst constants are statically computed from this Parameters object and are immutable after elaboration.

### Reset and Error Handling
- **Reset Behavior**: N/A. SbufferBundle has no sequential elements and thus no reset behavior. Reset is the responsibility of the instantiating module or register file that uses subclasses of SbufferBundle.
- **Error Reporting**: None. SbufferBundle has no error detection or reporting mechanism. The only possible error is a Chisel elaboration failure if the implicit `p: Parameters` is not in scope at instantiation time — this is a compile-time error caught by the Scala/Chisel compiler, not a runtime error.
- **Self-Recovery Strategy**: None.

### Parameterization and Configurable Features
- **Module Parameters**:

  | Parameter Name | Type/Range | Default | Functional Effect |
  | ------ | ------------- | ------ | -------- |
  | p (implicit) | Parameters | Config-dependent | The XiangShan hardware configuration object. Carried as `implicit p: Parameters` through SbufferBundle's constructor into all subclasses. All HasSbufferConst constants are derived from this object. |
  | StoreBufferSize | Int | Config-dependent | Determines `wvec` bit width in DataWriteReq and MaskFlushReq. Width = StoreBufferSize bits. |
  | VLEN | Int | Config-dependent | Determines `data` bit width (VLEN) and `mask` bit width (VLEN/8) in DataWriteReq. |
  | VWordOffsetWidth | Int | log2Ceil(CacheLineVWords) | Determines `vwordOffset` bit width in DataWriteReq. |
  | EvictCycles | Int | 1 << 20 | Coherence timeout threshold in cycles. Available to all subclasses. |
  | SbufferReplayDelayCycles | Int | 16 | Replay delay timeout in cycles. Available to all subclasses. |
  | NumDcacheWriteResp | Int | 1 | Number of DCache write response ports. Determines the Vec size for maskFlushReq in SbufferData. |
  | SbufferIndexWidth | Int | log2Up(StoreBufferSize) | Bit width for store buffer entry indexing. |
  | CacheLineBytes | Int | CacheLineSize / 8 | Number of bytes per cache line. |
  | OffsetWidth | Int | log2Up(CacheLineBytes) | Bit width of byte offset within cache line. |
  | PTagWidth | Int | PAddrBits - OffsetWidth | Bit width of physical tag. |
  | VTagWidth | Int | VAddrBits - OffsetWidth | Bit width of virtual tag. |
  | CacheLineVWords | Int | CacheLineBytes / VDataBytes | Number of VLEN-width virtual words per cache line. |
  | VWordsWidth | Int | log2Up(CacheLineVWords) | Bit width for virtual word indexing. |
  | EvictCountBits | Int | log2Up(EvictCycles + 1) | Bit width of coherence counter registers. |
  | MissqReplayCountBits | Int | log2Up(SbufferReplayDelayCycles) + 1 | Bit width of replay counter registers. |

  All parameters are derived from the implicit `p: Parameters` configuration object by the HasSbufferConst trait. SbufferBundle itself defines no additional parameters.

- **Runtime Configuration**: None. All constants are fixed at elaboration time.
- **Compile Macros/Generation Options**: None. SbufferBundle has no conditional compilation or generation options beyond what HasSbufferConst provides.

## Verification Requirements and Coverage Suggestions
- **Functional Coverage Points**: All `CK-*` check points defined in each functional group constitute coverage targets. SbufferBundle is an elaboration-time construct, so coverage is focused on compile-time constant resolution correctness:
  - All HasSbufferConst constants accessible from every SbufferBundle subclass.
  - Constant values consistent with the input Parameters object.
  - Field widths in subclass Bundles match the declared constants.
  - Subclass Bundles recognized as legal Chisel Bundles (Flipped, ValidIO wrapping, etc.).
- **Constraints and Assumptions**:
  - The testbench must provide a valid `Parameters` object in the implicit scope when instantiating SbufferBundle subclasses.
  - Verification is compile-time (elaboration-time) — test passes when Chisel elaboration succeeds and field width assertions hold.
  - The testbench assumes HasSbufferConst is correctly implemented and produces correct constant values from the Parameters object. SbufferBundle's contract is to expose those constants to subclasses, not to compute them.
  - Single implicit Parameters context per testbench. Constants are not expected to vary across instances within a single elaboration.
- **Test Interfaces**:
  - **Parameter Inspector**: Instantiate one or more SbufferBundle subclasses using a known Parameters object. Read all HasSbufferConst constants from the subclass instance. Compare each constant against expected values computed from the Parameters object.
  - **Field Width Checker**: For each subclass (DataWriteReq, MaskFlushReq, SbufferEntryState), create an instance and use Chisel's `getWidth` or reflection API to verify that each field's bit width matches the expected constant-derived value.
  - **Elaboration Success Check**: Verify that Chisel elaboration (FIRRTL generation) completes without error when a SbufferBundle subclass is instantiated with a valid implicit Parameters. This confirms that all constants resolve correctly through the inheritance chain.
  - **Cross-Subclass Consistency Check**: Create multiple subclass instances (DataWriteReq, MaskFlushReq, SbufferEntryState) from the same Parameters object. Verify that all shared constants (e.g., StoreBufferSize, VLEN) have identical values across all instances.
