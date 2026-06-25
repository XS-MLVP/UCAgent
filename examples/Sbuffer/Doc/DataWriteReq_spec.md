# DataWriteReq Specification Document

> This document describes the specification of the `DataWriteReq` chip verification target. Keep the technical language precise, well-organized, and easy to reuse for verification. If an item does not exist, explicitly write "None" or "TBD"; do not delete the section.

## Introduction
- **Design Background**: `DataWriteReq` is a Chisel Bundle type that carries write command fields from the Sbuffer enqueue pipeline into the `SbufferData` storage module. It is instantiated as `Flipped(ValidIO(new DataWriteReq))` on each of the `EnsbufferWidth` write request ports of `SbufferData`. The fields specify the target store buffer entry (via one-hot wvec), the byte-level write mask, the write data payload, the virtual word offset within the cache line, and a full-cache-line write flag. Source: `engine_overview.txt:9`, `phase_01_types.txt:51-56`.
- **Design Goals**: (1) Carry a one-hot entry selector (`wvec`) of width `StoreBufferSize` to identify which store buffer entry receives the write. (2) Carry a per-byte write mask (`mask`) of width `VLEN/8` to indicate which bytes within the VLEN-width data word should be written. (3) Carry the write data payload (`data`) of width `VLEN`. (4) Carry a virtual word offset (`vwordOffset`) of width `VWordOffsetWidth` to select which virtual-word segment within the cache line is targeted. (5) Carry a full-cache-line write flag (`wline`) that, when asserted, causes SbufferData to ignore `vwordOffset` and `mask` and write to all virtual word offsets within the entry.

## Terms and Abbreviations in Chisel Code

| Abbreviation | Full Term | Description |
| ---- | ---- | ---- |
| wvec | Write Vector | One-hot UInt of width StoreBufferSize selecting which store buffer entry to target. Exactly one bit must be asserted per transaction per the caller Sbuffer protocol. |
| mask | Byte Write Mask | Per-byte enable mask of width VLEN/8 bits. Each bit controls whether the corresponding byte in `data` is written at the specified `vwordOffset`. Ignored when `wline` is true. |
| data | Write Data | Full VLEN-width data payload. Individual bytes are extracted by the consumer (SbufferData) via `data(byte*8+7, byte*8)`. |
| vwordOffset | Virtual Word Offset | UInt of width VWordOffsetWidth (= log2Ceil(CacheLineVWords)) selecting which virtual-word segment within a cache line entry to target. Ignored when `wline` is true. |
| wline | Write Line | Boolean flag indicating a full cache line write. When true, the write applies to all CacheLineVWords virtual word offsets within the target entry, bypassing `mask` and `vwordOffset`. |
| VLEN | Vector Length | Vector register length in bits. Determines `mask` bit width (VLEN/8) and `data` bit width (VLEN). |
| VWordOffsetWidth | Virtual Word Offset Width | Width of the vwordOffset field, equal to log2Ceil(CacheLineVWords). |
| SbufferBundle | Sbuffer Bundle Base | Base Chisel Bundle class that extends XSBundle with HasSbufferConst, providing parameter-derived constants to all Sbuffer bundle types. |

## Chisel Source Files

File list:
- `DataWriteReq.scala:1-9`: Top-level DataWriteReq Bundle definition. Single class with five fields: wvec, mask, data, vwordOffset, wline. Extends SbufferBundle for parameter inheritance.

## Top-Level Interface Overview
- **Module Name**: `DataWriteReq` (Bundle type, not a Chisel Module)
- **Port List** (Bundle fields as consumed by SbufferData via `writeReq` ValidIO ports):

  | Signal Name | Direction (from SbufferData) | Width/Type | Reset Value | Description |
  | ------ | ---- | -------- | ------ | ---- |
  | wvec | input (part of writeReq.bits) | UInt(StoreBufferSize.W) | N/A | One-hot bitmask selecting the target store buffer entry. SbufferData decodes this to compute per-entry write enable `sbuffer_in_s1_line_wen`. Source: `DataWriteReq.scala:3`. |
  | mask | input (part of writeReq.bits) | UInt((VLEN/8).W) | N/A | Per-byte write mask. Each bit enables the corresponding data byte at the target `vwordOffset`. SbufferData uses this to qualify the per-byte `write_byte` condition when `wline` is false. Source: `DataWriteReq.scala:5`. |
  | data | input (part of writeReq.bits) | UInt(VLEN.W) | N/A | Write data payload. Full VLEN-width value. SbufferData extracts individual bytes via bit-range indexing. Source: `DataWriteReq.scala:6`. |
  | vwordOffset | input (part of writeReq.bits) | UInt(VWordOffsetWidth.W) | N/A | Virtual word offset within the cache line entry. Selects which CacheLineVWords segment to target. SbufferData compares this against loop indices to qualify the `write_byte` condition when `wline` is false. Source: `DataWriteReq.scala:7`. |
  | wline | input (part of writeReq.bits) | Bool() | N/A | Full cache line write flag. When true, SbufferData writes to all CacheLineVWords positions regardless of `mask` and `vwordOffset` values. Source: `DataWriteReq.scala:8`. |

- **Clock and Reset Requirements**: N/A. DataWriteReq is a Bundle type with no clock or reset. Its fields are combinatorial signals driven by the parent Sbuffer on the same cycle as `writeReq(i).valid`.
- **External Dependencies**: DataWriteReq extends `SbufferBundle`, which extends `XSBundle` with `HasSbufferConst`. This inheritance provides access to parameter-derived constants: `StoreBufferSize` (sets `wvec` width), `VLEN` (sets `data` and `mask` widths), and `VWordOffsetWidth` (sets `vwordOffset` width). The Bundle is consumed exclusively by SbufferData, which expects all fields to have bit widths consistent with these parameters.

## Functional Description

### Test and Verification Interface

<FG-API>

- **Overview**: This functional group describes the standard interfaces a testbench must implement to drive and inspect the DataWriteReq Bundle as part of SbufferData write request verification.
- **Execution Flow**: The testbench drives all DataWriteReq fields combinatorially on the same cycle as `writeReq(i).valid`. All fields must be driven simultaneously; partial or staged field updates are not supported. The consumer (SbufferData) reads all fields unconditionally when valid is asserted.
- **Boundaries and Exceptions**: The `wvec` field must be one-hot (exactly one bit asserted). The testbench must not drive non-one-hot `wvec`. When `wline` is true, the `mask` and `vwordOffset` fields are semantically ignored by SbufferData but must still be driven with legal values.
- **Performance and Constraints**: All fields are combinatorial inputs with no pipeline latency or backpressure mechanism within the Bundle. The testbench must present stable field values for the duration of the valid cycle.

#### Field Drive Interface

<FC-FIELD-DRIVE>

The testbench drives all five DataWriteReq fields (wvec, mask, data, vwordOffset, wline) simultaneously as part of a write request transaction. Each field must conform to its declared bit width and encoding contract.

**Check points:**
- <CK-DRIVE-ALL-FIELDS> Drive writeReq with wvec=1 (one-hot), mask=0xFF (all bytes), data=0xDEADBEEF, vwordOffset=0, wline=false. Verify SbufferData accepts and processes the write.
- <CK-DRIVE-WLINE-TRUE> Drive writeReq with wline=true, wvec=entry E, data=D. Verify SbufferData writes to all CacheLineVWords offsets regardless of mask and vwordOffset values.
- <CK-DRIVE-WLINE-FALSE> Drive writeReq with wline=false, mask with sparse bits set, vwordOffset=1. Verify SbufferData writes only bytes matching both mask bits and vwordOffset=1.

#### Field Width Conformance

<FC-FIELD-WIDTH>

Each field must have the correct bit width as determined by the HasSbufferConst parameters. Width mismatches would cause Chisel elaboration failures.

**Check points:**
- <CK-WVEC-WIDTH> Verify wvec.getWidth equals StoreBufferSize bits. Source: `DataWriteReq.scala:3`.
- <CK-MASK-WIDTH> Verify mask.getWidth equals VLEN/8 bits. Source: `DataWriteReq.scala:5`.
- <CK-DATA-WIDTH> Verify data.getWidth equals VLEN bits. Source: `DataWriteReq.scala:6`.
- <CK-VWORDOFFSET-WIDTH> Verify vwordOffset.getWidth equals VWordOffsetWidth (= log2Ceil(CacheLineVWords)) bits. Source: `DataWriteReq.scala:7`.
- <CK-WLINE-TYPE> Verify wline is of Chisel type Bool. Source: `DataWriteReq.scala:8`.

#### Field Encoding Contract

<FC-FIELD-ENCODING>

Each field carries a specific encoding that the consumer (SbufferData) relies on for correct operation.

**Check points:**
- <CK-WVEC-ONEHOT> Verify wvec has exactly one bit asserted per legal write transaction. Non-one-hot wvec is a caller protocol violation.
- <CK-MASK-PER-BYTE> Verify each mask bit corresponds to one byte within the VLEN-width data word. mask(i) controls data(8*i+7 downto 8*i).
- <CK-VWORDOFFSET-RANGE> Verify vwordOffset is always in range [0, CacheLineVWords-1]. Values outside this range are undefined.
- <CK-WLINE-MASK-RELATION> When wline=true, verify SbufferData ignores mask and vwordOffset; when wline=false, verify SbufferData uses both mask and vwordOffset.

### Bundle Field Contracts

<FG-BUNDLE-CONTRACTS>

- **Overview**: DataWriteReq defines five combinatorial fields that together form a write command to SbufferData. Each field carries a specific contract regarding width, encoding, and interaction with other fields.
- **Execution Flow**: The parent Sbuffer asserts `writeReq(i).valid` and simultaneously drives all five DataWriteReq fields. SbufferData decodes `wvec` to identify the target entry, evaluates `wline` to determine write scope (full-cache-line vs. offset-specific), and uses `mask` and `vwordOffset` (when `wline` is false) to qualify per-byte writes.
- **Boundaries and Exceptions**: 
  - `wvec` must be one-hot. The caller Sbuffer guarantees this; DataWriteReq does not validate it.
  - When `wline` is true, `mask` and `vwordOffset` are semantically ignored by the write qualification logic. They must still be driven with legal values but their content does not affect the write outcome.
  - When `wline` is false, only bytes with the corresponding `mask` bit set at the specified `vwordOffset` are written. Bytes with mask bits clear are not written.
  - Concurrent writes to the same entry on multiple `writeReq` ports in the same cycle produce undefined behavior and are not expected under the Sbuffer protocol.
- **Performance and Constraints**: All fields are combinatorial inputs provided in the same cycle as `writeReq(i).valid`. No pipelining exists within the Bundle itself. The Bundle is transmitted over a ValidIO interface, meaning the consumer provides unconditional acceptance (no ready/backpressure).

#### Entry Selection via wvec

<FC-ENTRY-SELECTION>

The `wvec` field is a one-hot UInt of width `StoreBufferSize` that selects which store buffer entry receives the write. Exactly one bit must be asserted per transaction. SbufferData decodes `wvec` to generate per-entry write enables.

**Check points:**
- <CK-WVEC-ENTRY-0> Drive writeReq with wvec=0b0001 (entry 0 selected). Verify only entry 0 data/mask registers are updated.
- <CK-WVEC-ENTRY-N> For entry N in [0, StoreBufferSize-1], drive writeReq with wvec having only bit N asserted. Verify only entry N data/mask registers are updated.
- <CK-WVEC-ISOLATION> Write to entry A, then write to entry B. Verify entry A data/mask are unchanged by the write to entry B.

#### Data and Mask Pairing

<FC-DATA-MASK-PAIRING>

The `data` and `mask` fields work in tandem: each `mask` bit controls whether the corresponding byte of `data` is written. When `wline` is false, only bytes with `mask` bit set at the matching `vwordOffset` are written.

**Check points:**
- <CK-MASK-ALL-BYTES> Drive mask=0xFF (all bytes enabled), data=0xAABBCCDD. Verify all bytes are written and mask bits are set for all bytes.
- <CK-MASK-SPARSE> Drive mask with only bits 0 and 7 set, data with byte0=0xAA, byte7=0xBB. Verify only bytes 0 and 7 are written; other bytes and their mask bits are unchanged.
- <CK-MASK-ZERO> Drive mask=0x00 (no bytes enabled). Verify no data bytes are written and no mask bits are changed.

#### Virtual Word Offset Addressing

<FC-VWORDOFFSET>

The `vwordOffset` field selects which virtual-word segment within the cache line entry to target. When `wline` is false, writes are constrained to the single vwordOffset position.

**Check points:**
- <CK-OFFSET-0> Drive vwordOffset=0, mask byte 0 set, data byte 0=0xCC. Verify dataOut(entry)(0)(0) reads 0xCC and dataOut(entry)(1)(0) is unchanged.
- <CK-OFFSET-1> Drive vwordOffset=1 with the same mask/data as offset-0 test. Verify dataOut(entry)(1) is updated and dataOut(entry)(0) is unchanged.
- <CK-OFFSET-BOUNDARY> Drive vwordOffset=CacheLineVWords-1 (maximum legal offset). Verify write occurs at the last virtual word offset without overflow.

#### Full Cache Line Write via wline

<FC-WLINE>

The `wline` field is a Boolean that, when true, causes SbufferData to write `data` to all CacheLineVWords virtual word offsets within the target entry. When true, `mask` and `vwordOffset` are semantically ignored for write qualification.

**Check points:**
- <CK-WLINE-ALL-OFFSETS> Drive wline=true, wvec=entry 0, data=D. Verify dataOut(0)(i) reflects D for all i in [0, CacheLineVWords-1] and maskOut(0)(i)(*) is all true.
- <CK-WLINE-IGNORES-MASK> Drive wline=true with mask=0x00 (no bytes). Verify all bytes are still written (wline overrides mask).
- <CK-WLINE-IGNORES-OFFSET> Drive wline=true with vwordOffset=0. Verify writes occur at all CacheLineVWords offsets, not just offset 0.
- <CK-WLINE-PARTIAL-OVERRIDE> Write with wline=true to entry 0, then write with wline=false to entry 0 at offset 1 with new data. Verify offset 0 retains wline data and offset 1 gets the new partial-write data.

### Subcomponent Description

(no submodules) — DataWriteReq is a leaf Bundle type with no child module instantiations. It extends SbufferBundle and contains only combinatorial field declarations.

### State Machines and Timing
- **State Machine List**: None. DataWriteReq is a Bundle type with no state.
- **State Transition Conditions**: N/A.
- **Key Timing**: N/A. DataWriteReq fields are combinatorial signals driven on the same cycle as the `writeReq.valid` assertion. The Bundle itself introduces zero cycles of latency.

### Configuration Registers and Storage
| Register Name/Address | Access Attribute | Bit Field | Default | Description | Read/Write Side Effects |
| ------------- | -------- | ---- | ------ | ---- | ---------- |
| None | N/A | N/A | N/A | DataWriteReq is a combinatorial Bundle with no internal storage registers. | N/A |

- **Register Map Base Address**: No bus interface. DataWriteReq is a wire-level Bundle type.
- **Configuration Flow**: N/A. No runtime configuration. Field widths are fixed at elaboration time by HasSbufferConst parameters.

### Reset and Error Handling
- **Reset Behavior**: N/A. Bundle types have no reset behavior. All fields are combinatorial.
- **Error Reporting**: None. DataWriteReq has no error detection or reporting mechanism.
- **Self-Recovery Strategy**: None. Error handling for protocol violations (e.g., non-one-hot wvec) is the caller Sbuffer's responsibility.

### Parameterization and Configurable Features
- **Module Parameters**:

  | Parameter Name | Type/Range | Default | Functional Effect |
  | ------ | ------------- | ------ | -------- |
  | StoreBufferSize | Int | Config-dependent | Determines `wvec` bit width. Width = StoreBufferSize bits. Source: `DataWriteReq.scala:3`. |
  | VLEN | Int | Config-dependent | Determines `mask` bit width (VLEN/8) and `data` bit width (VLEN). Source: `DataWriteReq.scala:5-6`. |
  | VWordOffsetWidth | Int | log2Ceil(CacheLineVWords) | Determines `vwordOffset` bit width. Source: `DataWriteReq.scala:7`. |

- **Runtime Configuration**: None.
- **Compile Macros/Generation Options**: None.

## Verification Requirements and Coverage Suggestions
- **Functional Coverage Points**: All `CK-*` check points defined in each functional group constitute coverage targets. Additional cross-coverage scenarios:
  - All combinations of wline (true/false) with mask patterns (all-zero, all-ones, sparse) and vwordOffset values.
  - All wvec one-hot positions covering every entry index [0, StoreBufferSize-1].
  - Sequential writes with alternating wline=true and wline=false to the same entry.
- **Constraints and Assumptions**:
  - `wvec` must be one-hot (exactly one bit asserted). Testbench must not inject non-one-hot wvec.
  - All fields must be driven combinatorially on the same cycle as `writeReq(i).valid`.
  - Field values must be stable for the duration of the valid cycle.
  - Single clock domain, synchronous reset context (inherited from parent SbufferData/Sbuffer).
- **Test Interfaces**:
  - **Field Driver**: Drive all five DataWriteReq fields (wvec, mask, data, vwordOffset, wline) as a complete transaction. Sweep legal values for each field independently and in combination.
  - **Field Monitor**: Confirm that SbufferData's dataOut and maskOut outputs reflect the correct interpretation of each DataWriteReq field per the contracts defined in this specification.
  - **Reference Model**: Maintain a software model of SbufferData's register file. For each writeReq transaction: decode wvec to identify entry, evaluate wline to determine write scope, and apply data/mask at the appropriate virtual word offsets.
