# MaskFlushReq Specification Document

> This document describes the specification of the `MaskFlushReq` chip verification target. Keep the technical language precise, well-organized, and easy to reuse for verification. If an item does not exist, explicitly write "None" or "TBD"; do not delete the section.

## Introduction
- **Design Background**: `MaskFlushReq` is a Chisel Bundle type that carries the mask flush command from the Sbuffer DCache response path into the `SbufferData` storage module. It is instantiated as `Flipped(ValidIO(new MaskFlushReq))` on each of the `NumDcacheWriteResp` mask flush ports of `SbufferData`. When DCache signals a write-hit completion for a store buffer entry, the parent Sbuffer drives `maskFlushReq` with the completed entry's one-hot wvec to clear all dirty-mask bits for that entry. Source: `engine_overview.txt:9`, `phase_01_types.txt:58-59`.
- **Design Goals**: (1) Carry a one-hot entry selector (`wvec`) of width `StoreBufferSize` to identify which store buffer entry's mask should be cleared. (2) Provide the minimal signaling needed for SbufferData to compute per-entry mask clear enables. (3) Support concurrent mask flush requests on multiple ports targeting different entries, with OR-reduction handling when multiple ports target the same entry.

## Terms and Abbreviations in Chisel Code

| Abbreviation | Full Term | Description |
| ---- | ---- | ---- |
| wvec | Write Vector | One-hot UInt of width StoreBufferSize selecting which store buffer entry's mask to clear. Exactly one bit must be asserted per transaction. |
| NumDcacheWriteResp | DCache Write Response Count | Number of parallel mask flush request ports. Hardcoded to 1 in the current configuration. Source: `phase_01_types.txt:107`. |
| SbufferBundle | Sbuffer Bundle Base | Base Chisel Bundle class that extends XSBundle with HasSbufferConst, providing parameter-derived constants to all Sbuffer bundle types. |
| mask | Dirty Mask | Per-byte boolean array stored in SbufferData indicating which bytes have been written (are "dirty"). The mask flush command clears all mask bits for the target entry to false. |

## Chisel Source Files

File list:
- `MaskFlushReq.scala:1-4`: Top-level MaskFlushReq Bundle definition. Single class with one field: wvec. Extends SbufferBundle for parameter inheritance.

## Top-Level Interface Overview
- **Module Name**: `MaskFlushReq` (Bundle type, not a Chisel Module)
- **Port List** (Bundle fields as consumed by SbufferData via `maskFlushReq` ValidIO ports):

  | Signal Name | Direction (from SbufferData) | Width/Type | Reset Value | Description |
  | ------ | ---- | -------- | ------ | ---- |
  | wvec | input (part of maskFlushReq.bits) | UInt(StoreBufferSize.W) | N/A | One-hot bitmask selecting the target store buffer entry whose mask should be cleared. SbufferData decodes this to compute the per-entry `line_mask_clean_flag`. Source: `MaskFlushReq.scala:3`. |

- **Clock and Reset Requirements**: N/A. MaskFlushReq is a Bundle type with no clock or reset. The `wvec` field is a combinatorial signal driven by the parent Sbuffer on the same cycle as `maskFlushReq(i).valid`.
- **External Dependencies**: MaskFlushReq extends `SbufferBundle`, which extends `XSBundle` with `HasSbufferConst`. This inheritance provides access to the `StoreBufferSize` parameter, which determines the `wvec` bit width. The Bundle is consumed exclusively by SbufferData, which expects `wvec` to have width `StoreBufferSize` bits and to carry a one-hot encoding.

## Functional Description

### Test and Verification Interface

<FG-API>

- **Overview**: This functional group describes the standard interfaces a testbench must implement to drive and inspect the MaskFlushReq Bundle as part of SbufferData mask flush verification.
- **Execution Flow**: The testbench drives the `wvec` field combinatorially on the same cycle as `maskFlushReq(i).valid`. The field must be driven with a one-hot encoding; non-one-hot values are a protocol violation. The consumer (SbufferData) reads `wvec` unconditionally when valid is asserted.
- **Boundaries and Exceptions**: The `wvec` field must be one-hot (exactly one bit asserted). The testbench must not drive non-one-hot `wvec`. Multiple `maskFlushReq` ports may fire in the same cycle; if they target the same entry, SbufferData's OR-reduction logic handles the collision correctly (the mask is cleared exactly once).
- **Performance and Constraints**: The `wvec` field is a combinatorial input with no pipeline latency or backpressure mechanism within the Bundle. The testbench must present a stable `wvec` value for the duration of the valid cycle.

#### Field Drive Interface

<FC-FIELD-DRIVE>

The testbench drives the single `wvec` field as part of a mask flush transaction. The field must conform to its declared bit width and one-hot encoding contract.

**Check points:**
- <CK-DRIVE-WVEC> Drive maskFlushReq with wvec=0b0001 (one-hot, selecting entry 0). Verify SbufferData clears mask for entry 0.
- <CK-DRIVE-WVEC-ALL-ENTRIES> For entry N in [0, StoreBufferSize-1], drive maskFlushReq with wvec having only bit N asserted. Verify only entry N mask is cleared.

#### Field Width Conformance

<FC-FIELD-WIDTH>

The `wvec` field must have the correct bit width as determined by the HasSbufferConst parameter `StoreBufferSize`.

**Check points:**
- <CK-WVEC-WIDTH> Verify wvec.getWidth equals StoreBufferSize bits. Source: `MaskFlushReq.scala:3`.

#### Field Encoding Contract

<FC-FIELD-ENCODING>

The `wvec` field must carry a one-hot encoding: exactly one bit asserted per legal transaction. SbufferData relies on this for correct per-entry mask clear computation.

**Check points:**
- <CK-WVEC-ONEHOT> Verify wvec has exactly one bit asserted per legal mask flush transaction.
- <CK-WVEC-MIN-VALUE> Verify wvec with value 0 (no bits asserted) results in no entry mask being cleared (no-ops when valid is asserted with zero wvec; behavior TBD based on implementation).

### Bundle Field Contract

<FG-BUNDLE-CONTRACT>

- **Overview**: MaskFlushReq defines a single combinatorial field (`wvec`) that forms a mask flush command to SbufferData. The field carries a one-hot entry selector that SbufferData decodes to identify which entry's dirty-mask bits to clear.
- **Execution Flow**: The parent Sbuffer asserts `maskFlushReq(i).valid` and simultaneously drives `wvec`. SbufferData decodes `wvec` to identify the target entry and computes `line_mask_clean_flag` for that entry. The OR-reduction across all `maskFlushReq` ports handles concurrent requests: `maskFlushReq.map(m => m.valid && m.bits.wvec).reduce(_ | _)`. Source: caller expectation from SbufferData.
- **Boundaries and Exceptions**:
  - `wvec` must be one-hot. The caller Sbuffer guarantees this; MaskFlushReq does not validate it.
  - Multiple `maskFlushReq` ports may fire in the same cycle targeting different entries. Each entry's mask clear flag is computed independently.
  - If multiple `maskFlushReq` ports target the same entry in the same cycle, the OR-reduction produces a single clear event. The mask is cleared exactly once.
  - The parent Sbuffer guarantees that `maskFlushReq` and `writeReq` do not simultaneously target the same entry in the same cycle. This constraint is enforced by Sbuffer pipeline timing, not by MaskFlushReq.
- **Performance and Constraints**: The `wvec` field is a combinatorial input driven in the same cycle as `maskFlushReq(i).valid`. The Bundle is transmitted over a ValidIO interface, meaning the consumer provides unconditional acceptance (no ready/backpressure).

#### Entry Selection via wvec

<FC-ENTRY-SELECTION>

The `wvec` field is a one-hot UInt of width `StoreBufferSize` that selects which store buffer entry receives the mask clear operation.

**Check points:**
- <CK-WVEC-ENTRY-0> Drive maskFlushReq with wvec=0b0001 (entry 0 selected). Verify only entry 0 mask register is cleared.
- <CK-WVEC-ENTRY-ISOLATION> Write to entries A and B, then flush entry A. Verify entry A mask is cleared and entry B mask is unchanged.
- <CK-WVEC-MULTI-PORT> If NumDcacheWriteResp > 1: drive maskFlushReq(0) with wvec targeting entry A and maskFlushReq(1) with wvec targeting entry B (A != B) in the same cycle. Verify both entries are flushed independently.
- <CK-WVEC-SAME-ENTRY> If NumDcacheWriteResp > 1: drive both maskFlushReq ports targeting the same entry in the same cycle. Verify the entry is flushed exactly once (no double-clearing side effects).

### Subcomponent Description

(no submodules) — MaskFlushReq is a leaf Bundle type with no child module instantiations. It extends SbufferBundle and contains only a single combinatorial field declaration.

### State Machines and Timing
- **State Machine List**: None. MaskFlushReq is a Bundle type with no state.
- **State Transition Conditions**: N/A.
- **Key Timing**: N/A. The `wvec` field is a combinatorial signal driven on the same cycle as the `maskFlushReq.valid` assertion. The Bundle itself introduces zero cycles of latency.

### Configuration Registers and Storage
| Register Name/Address | Access Attribute | Bit Field | Default | Description | Read/Write Side Effects |
| ------------- | -------- | ---- | ------ | ---- | ---------- |
| None | N/A | N/A | N/A | MaskFlushReq is a combinatorial Bundle with no internal storage registers. | N/A |

- **Register Map Base Address**: No bus interface. MaskFlushReq is a wire-level Bundle type.
- **Configuration Flow**: N/A. No runtime configuration. Field width is fixed at elaboration time by HasSbufferConst parameters.

### Reset and Error Handling
- **Reset Behavior**: N/A. Bundle types have no reset behavior. The `wvec` field is combinatorial.
- **Error Reporting**: None. MaskFlushReq has no error detection or reporting mechanism.
- **Self-Recovery Strategy**: None. Error handling for protocol violations (e.g., non-one-hot wvec) is the caller Sbuffer's responsibility.

### Parameterization and Configurable Features
- **Module Parameters**:

  | Parameter Name | Type/Range | Default | Functional Effect |
  | ------ | ------------- | ------ | -------- |
  | StoreBufferSize | Int | Config-dependent | Determines `wvec` bit width. Width = StoreBufferSize bits. Source: `MaskFlushReq.scala:3`. |

- **Runtime Configuration**: None.
- **Compile Macros/Generation Options**: None.

## Verification Requirements and Coverage Suggestions
- **Functional Coverage Points**: All `CK-*` check points defined in each functional group constitute coverage targets. Additional cross-coverage scenarios:
  - Mask flush on every entry index [0, StoreBufferSize-1].
  - Concurrent write and mask flush to different entries (coverage of the protocol constraint that write and flush never target the same entry simultaneously).
  - Verify dataOut is preserved after mask flush (only mask is cleared, not data).
  - Flush an entry that has been written with wline=true: verify all mask bits across all virtual word offsets are cleared.
- **Constraints and Assumptions**:
  - `wvec` must be one-hot (exactly one bit asserted). Testbench must not inject non-one-hot wvec.
  - The `wvec` field must be driven combinatorially on the same cycle as `maskFlushReq(i).valid`.
  - The field value must be stable for the duration of the valid cycle.
  - Single clock domain, synchronous reset context (inherited from parent SbufferData/Sbuffer).
  - `maskFlushReq` and `writeReq` must not target the same entry in the same cycle (protocol constraint enforced by Sbuffer).
- **Test Interfaces**:
  - **Field Driver**: Drive the single `wvec` field with valid one-hot values covering all entry indices. Verify mask clearing behavior via SbufferData's `maskOut`.
  - **Multi-Port Driver**: When `NumDcacheWriteResp > 1`, drive multiple `maskFlushReq` ports concurrently with different and identical wvec targets.
  - **Reference Model**: Track per-entry mask state. On mask flush to entry E, clear all mask bits for entry E. Compare against `maskOut` after pipeline latency.
