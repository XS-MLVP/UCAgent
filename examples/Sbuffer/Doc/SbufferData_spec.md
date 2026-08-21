# SbufferData Specification Document

> This document describes the specification of the `SbufferData` chip verification target. Keep the technical language precise, well-organized, and easy to reuse for verification. If an item does not exist, explicitly write "None" or "TBD"; do not delete the section.

## Introduction
- **Design Background**: `SbufferData` is a byte-level storage array instantiated by the `Sbuffer` module. It provides write data and per-byte dirty mask storage for each store buffer entry, organized as [entry][virtual word offset][byte]. Sbuffer reads `dataOut` and `maskOut` for DCache eviction data/mask generation and store-to-load forwarding. Source: `SbufferData.scala:1-3`, `engine_overview.txt:9`.
- **Design Goals**: (1) Accept write commands on EnsbufferWidth parallel ValidIO ports, storing data and per-byte masks at the specified entry and virtual word offset. (2) Accept mask flush commands on NumDcacheWriteResp parallel ValidIO ports, clearing all mask bits for a completed entry. (3) Provide combinational read access to the stored data and mask arrays. (4) Support full cache line write via the `wline` flag, bypassing per-offset addressing. (5) Provide unconditional acceptance of all ValidIO transactions — no backpressure.

## Terms and Abbreviations in Chisel Code

| Abbreviation | Full Term | Description |
| ---- | ---- | ---- |
| wvec | Write Vector | One-hot UInt of width StoreBufferSize selecting which entry to target |
| vwordOffset | Virtual Word Offset | Index selecting which CacheLineVWords segment within an entry |
| VDataBytes | Vector Data Bytes | Number of bytes per VLEN-width word (= VLEN/8) |
| CacheLineVWords | Cache Line Virtual Words | Number of VDataBytes segments per cache line (= CacheLineBytes / VDataBytes) |
| wline | Write Line | Flag indicating a full cache line write (all virtual word offsets) |
| ValidIO | Valid-only interface | Valid signal only, no backpressure; consumer must accept unconditionally |
| NumDcacheWriteResp | DCache Write Response Count | Number of parallel mask flush ports (hardcoded to 1) |
| GatedValidRegNext | Gated Valid Register Next | Chisel utility registering a valid signal and gating its next value when high |

## Chisel Source Files

File list:
- `SbufferData.scala:1-93`: Top-level SbufferData module — data Reg array, mask RegInit array, 2-cycle write pipeline (GatedValidRegNext), 2-cycle mask flush pipeline, dataOut/maskOut combinational outputs.

## Top-Level Interface Overview
- **Module Name**: `SbufferData`
- **Port List**:

  | Signal Name | Direction | Width/Type | Reset Value | Description |
  | ------ | ---- | -------- | ------ | ---- |
  | clock | input | Clock | N/A | Clock signal. Single clock domain, shared with parent Sbuffer. |
  | reset | input | Reset | N/A | Active-high synchronous reset. |
  | writeReq | input (Flipped ValidIO Vec) | Vec(EnsbufferWidth, ValidIO(DataWriteReq)) | valid=0 | Write data and mask commands from enqueue pipeline. Each port carries wvec, mask, data, vwordOffset, and wline. No ready backpressure. Source: `SbufferData.scala:4`. |
  | maskFlushReq | input (Flipped ValidIO Vec) | Vec(NumDcacheWriteResp, ValidIO(MaskFlushReq)) | valid=0 | Mask flush commands from DCache response path. Each port carries wvec only. No ready backpressure. Source: `SbufferData.scala:6`. |
  | dataOut | output | Vec(StoreBufferSize, Vec(CacheLineVWords, Vec(VDataBytes, UInt(8.W)))) | All zeros (after reset) | Read-only combinational data array, indexed by [entry][virtual word offset][byte]. Source: `SbufferData.scala:7, 91`. |
  | maskOut | output | Vec(StoreBufferSize, Vec(CacheLineVWords, Vec(VDataBytes, Bool()))) | All false (after reset) | Read-only combinational mask array, indexed by [entry][virtual word offset][byte]. Source: `SbufferData.scala:8, 92`. |

- **Clock and Reset Requirements**: Single clock domain (shared with Sbuffer parent). Active-high synchronous reset. After reset assertion: all `dataOut` entries read 0x00, all `maskOut` entries read false. Source: `SbufferData.scala:13-19`.
- **External Dependencies**: SbufferData depends on `HasSbufferConst` trait for parameter-derived constants (StoreBufferSize, EnsbufferWidth, CacheLineVWords, VDataBytes, NumDcacheWriteResp). No other submodule instantiations. The parent Sbuffer guarantees: wvec is always one-hot, no concurrent writes to the same entry on multiple writeReq ports, and no simultaneous writeReq and maskFlushReq targeting the same entry in the same cycle.

## Functional Description

### Test and Verification Interface

<FG-API>

- **Overview**: This functional group describes the standard interfaces a testbench must implement to drive and observe the SbufferData DUT. Covers write request drivers, mask flush drivers, data/mask monitors, and reset verification.
- **Execution Flow**: Testbench drives `writeReq(i).valid` with a DataWriteReq payload (wvec, mask, data, vwordOffset, wline). Transaction fires on the same cycle valid is asserted — SbufferData provides unconditional acceptance. Testbench drives `maskFlushReq(i).valid` with a MaskFlushReq payload (wvec). Transaction fires unconditionally. Testbench samples `dataOut` and `maskOut` to verify stored state.
- **Boundaries and Exceptions**: 
  - wvec must be one-hot (exactly one bit set). The testbench must not drive non-one-hot wvec.
  - Data must be provided on the same cycle as valid assertion (ValidIO has no ready for holding).
  - Concurrent writeReq to the same entry on multiple ports is not expected to occur under Sbuffer's protocol.
- **Performance and Constraints**: Write acceptance is unconditional on every cycle (pipeline processes up to EnsbufferWidth concurrent writes). Mask flush acceptance is unconditional on every cycle (up to NumDcacheWriteResp concurrent flushes).

#### Write Request Driver Interface

<FC-WRITE-DRIVER>

The testbench drives `writeReq(i).valid` and `writeReq(i).bits` with a full DataWriteReq payload: one-hot `wvec` selecting a single entry, `mask` (VLEN/8 bits) specifying which bytes to write, `data` (VLEN bits) carrying the write data, `vwordOffset` selecting the virtual word position within the cache line, and `wline` flag indicating whether all virtual word offsets should be written. Writes are unconditional — the testbench does not need to check a ready signal.

**Check points:**
- <CK-DRIVE-WRITE-SINGLE-PORT> Drive writeReq(0) with valid=true, wvec=entry E, mask byte j set, data byte j=0xAB. Verify dataOut(E)(vwordOffset)(j) reads 0xAB two cycles later and maskOut(E)(vwordOffset)(j) reads true two cycles later.
- <CK-DRIVE-WRITE-BOTH-PORTS> Drive writeReq(0) with valid=true for entry A and writeReq(1) with valid=true for entry B (A != B) in the same cycle. Verify both writes propagate independently.
- <CK-DRIVE-WRITE-WLINE> Drive writeReq(0) with wline=true, wvec=entry E. Verify dataOut(E)(*) and maskOut(E)(*) update at all CacheLineVWords virtual word offsets.

#### Mask Flush Driver Interface

<FC-FLUSH-DRIVER>

The testbench drives `maskFlushReq(i).valid` with a one-hot `wvec` to clear the mask for a completed entry. The mask flush is unconditional — the testbench does not need to check a ready signal.

**Check points:**
- <CK-DRIVE-FLUSH-WITH-DATA> Entry E has stored data and mask=true at multiple positions. Drive maskFlushReq(0) valid with wvec=entry E. Verify maskOut(E)(*)(*) reads false two cycles later.
- <CK-DRIVE-FLUSH-ISOLATION> Drive maskFlushReq(0) valid with wvec=entry E. Verify maskOut of entries other than E are unchanged.

#### Data and Mask Monitor Interface

<FC-DATA-MONITOR>

The testbench samples `dataOut` and `maskOut` combinational outputs to verify stored state. After a write, the updated data/mask becomes visible two clock cycles later (two-cycle write-to-readable latency, via the s1 capture + s2 register-write pipeline). After a mask flush, the cleared mask becomes visible two cycles later.

**Check points:**
- <CK-MONITOR-WRITE-VISIBLE> Write to entry E offset O: verify dataOut(E)(O) and maskOut(E)(O) reflect the written values two cycles after the writeReq valid cycle.
- <CK-MONITOR-FLUSH-VISIBLE> Mask flush to entry E: verify maskOut(E)(*)(*) is all false two cycles after the maskFlushReq valid assertion.
- <CK-MONITOR-UNWRITTEN-ZERO> Entry E offset O never written: verify dataOut(E)(O)(*) reads 0x00 and maskOut(E)(O)(*) reads false after reset.

### Write Pipeline — Data and Mask Storage

<FG-WRITE-STORAGE>

- **Overview**: SbufferData accepts write commands on EnsbufferWidth parallel ValidIO ports. Each write command specifies a target entry (via one-hot wvec), byte-level mask (VLEN/8 bits), data (VLEN bits), virtual word offset within the cache line, and an optional full-cache-line write flag (wline). The write pipeline has 2 cycles of latency from valid assertion to data/mask visibility on dataOut/maskOut. Source: `SbufferData.scala:37-65`.
- **Execution Flow**:
  1. On the cycle `writeReq(i).valid` is asserted, SbufferData captures the write command. The entry-level write enable `sbuffer_in_s1_line_wen` is asserted for the entry selected by `wvec`. Source: `SbufferData.scala:40`.
  2. The write data, wline flag, byte mask, and vwordOffset are registered via GatedValidRegNext (producing `sbuffer_in_s2_line_wen`) for pipeline stage 2. Source: `SbufferData.scala:41-45`.
  3. On the cycle when `sbuffer_in_s2_line_wen` is asserted (one cycle after writeReq valid), the per-byte write condition `write_byte` evaluates to true for each byte where: (a) the byte mask bit is set AND the vwordOffset matches the current word index, OR (b) the wline flag is true. Source: `SbufferData.scala:54-57`.
  4. When `write_byte` is true, the corresponding data byte is written to the data register and the mask bit is set to true. Source: `SbufferData.scala:58-61`.
- **Boundaries and Exceptions**:
  - SbufferData provides unconditional backpressure-free acceptance: there is no ready signal on writeReq. The module must accept writes on any cycle `writeReq(i).valid` is asserted.
  - When wline is true, the write applies to all CacheLineVWords virtual word positions within the target entry, regardless of vwordOffset and byte mask values. Source: `SbufferData.scala:56`.
  - When wline is false, writes apply only at the specified vwordOffset for bytes whose mask bit is set. Source: `SbufferData.scala:55`.
  - The caller Sbuffer guarantees wvec is always one-hot. SbufferData does not validate this internally.
  - Concurrent writes to the same entry on different ports in the same cycle produce undefined behavior and are not expected under the Sbuffer protocol.
- **Performance and Constraints**: Maximum EnsbufferWidth concurrent writes per cycle (one per port). Write latency: 2 cycles from writeReq.valid assertion to dataOut/maskOut reflecting the write (one cycle for s1 pipeline capture + one cycle for s2 register write). Source: `SbufferData.scala:41, 58-61`.

#### Per-Entry Data Write

<FC-DATA-WRITE>

When a write command fires on a writeReq port, the byte-level data at the specified entry, virtual word offset, and byte position is updated. The stored data persists until overwritten by a subsequent write to the same position or until reset.

**Check points:**
- <CK-WRITE-SINGLE-BYTE> writeReq(0).valid=true, wvec selects entry 0, vwordOffset=0, mask byte 0 set, data byte 0=0xAB: after 2 cycles, dataOut(0)(0)(0) reads 0xAB and maskOut(0)(0)(0) reads true.
- <CK-WRITE-MULTI-BYTE> writeReq(0).valid=true, mask bytes 0-7 set, data bytes 0-7 = 0x00 through 0x07: after 2 cycles, all 8 bytes in dataOut(0)(vwordOffset) match and all 8 mask bits in maskOut(0)(vwordOffset) are true.
- <CK-WRITE-DIFFERENT-OFFSET> Write to entry 0 at vwordOffset=0 with data D0, then write to same entry at vwordOffset=1 with data D1: data at offset 0 remains D0, data at offset 1 becomes D1.
- <CK-WRITE-WLINE-ALL-OFFSETS> writeReq with wline=true to entry 0 with data D: after 2 cycles, dataOut(0)(*)(*) reflects D at ALL virtual word offsets, maskOut(0)(*)(*) is all true.
- <CK-WRITE-CONCURRENT-DIFFERENT-ENTRIES> writeReq(0) writes entry A and writeReq(1) writes entry B in the same cycle (A != B): both writes complete independently, dataOut(A) and dataOut(B) reflect respective writes.
- <CK-WRITE-OVERWRITE> Write to entry 0 offset 0 with data D1, then write to same position with data D2: after second write completes, dataOut reads D2 (not D1).

#### Per-Entry Mask Update

<FC-MASK-UPDATE>

The per-byte mask bit is set to true whenever a byte is written. The mask indicates which bytes have been written (are "dirty"). When the wline flag is set, all mask bits across all virtual word offsets are set to true. When wline is false, only mask bits corresponding to set mask bits at the matching vwordOffset are set to true.

**Check points:**
- <CK-MASK-SET-ON-WRITE> Write to entry 0 offset 0 byte 3 with mask bit 3 set: after 2 cycles, maskOut(0)(0)(3) is true.
- <CK-MASK-UNWRITTEN-FALSE> Write to entry 0 offset 0 byte 3 with mask bit 3 set, mask bit 4 clear: after 2 cycles, maskOut(0)(0)(3) is true, maskOut(0)(0)(4) remains false (if not previously written).
- <CK-MASK-WLINE-ALL-TRUE> Write with wline=true to entry 0: after 2 cycles, maskOut(0)(*)(*) is true for all offsets and all bytes.
- <CK-MASK-PARTIAL-OFFSET> Write to entry 0 offset 1 with mask byte 0 set: maskOut(0)(0)(0) unchanged, maskOut(0)(1)(0) is true. Verify vwordOffset isolation.

### Mask Flush Pipeline

<FG-MASK-FLUSH>

- **Overview**: SbufferData accepts mask flush commands on NumDcacheWriteResp parallel ValidIO ports. When DCache signals a write hit completion for an entry, the parent Sbuffer drives maskFlushReq with the completed entry's one-hot wvec. SbufferData clears all mask bits for that entry to false. The mask flush pipeline has 2 cycles of latency from valid assertion to maskOut reflecting the cleared state. Source: `SbufferData.scala:22-34`.
- **Execution Flow**:
  1. On any cycle where `maskFlushReq` fires (valid asserted), SbufferData computes `line_mask_clean_flag` for each entry: this flag is true when any maskFlushReq port targets that entry. Source: `SbufferData.scala:23-25`.
  2. The flag is registered via GatedValidRegNext, producing the actual mask-clear enable one cycle later. Source: `SbufferData.scala:23-25`.
  3. When `line_mask_clean_flag` is true (one cycle after maskFlushReq valid), all mask bits for that entry are set to false across all virtual word offsets and all byte positions. Source: `SbufferData.scala:27-33`.
- **Boundaries and Exceptions**:
  - Mask flush only clears the mask register; the data register is not affected. Source: `SbufferData.scala:30` (only `mask(line)(word)(byte) := false.B`).
  - Multiple maskFlushReq ports targeting different entries may fire in the same cycle.
  - Multiple maskFlushReq ports targeting the same entry in the same cycle: OR reduction of all valid+wvec signals, so the flush happens exactly once. Source: `SbufferData.scala:24`.
  - The parent Sbuffer guarantees maskFlushReq and writeReq do not simultaneously target the same entry. This constraint is enforced by the Sbuffer pipeline timing.
- **Performance and Constraints**: Up to NumDcacheWriteResp (typically 1) concurrent mask flushes per cycle. Flush latency: 2 cycles from maskFlushReq.valid assertion to maskOut cleared.

#### Clear Mask on DCache Completion

<FC-CLEAR-MASK>

When a mask flush command fires, all mask bits for the target entry are cleared to false. The data register is not modified. The cleared state is visible on maskOut on the cycle following the GatedValidRegNext pipeline stage.

**Check points:**
- <CK-FLUSH-CLEAR-ALL-OFFSETS> Entry 0 has mask bits set at multiple offsets and byte positions after writes. Drive maskFlushReq(0) with wvec selecting entry 0. After 2 cycles, verify maskOut(0)(*)(*) reads false for all virtual word offsets and all byte positions.
- <CK-FLUSH-ISOLATED> Entry 0 mask flushed, entry 1 has mask bits set. Verify maskOut(1) is unchanged after flush of entry 0.
- <CK-FLUSH-DATA-PRESERVED> Write data D0 to entry 0, then mask flush entry 0. Verify dataOut(0) still reads D0 after flush (only mask is cleared).
- <CK-FLUSH-MULTIPLE-PORTS> If NumDcacheWriteResp > 1: drive maskFlushReq(0) targeting entry A and maskFlushReq(1) targeting entry B in the same cycle. Verify both entries' masks are cleared.

### Subcomponent Description

(no submodules) — SbufferData instantiates no child modules. It uses Chisel Reg, RegInit, and GatedValidRegNext primitives directly.

### State Machines and Timing
- **State Machine List**: None. SbufferData has no architecturally visible finite state machine. It operates as a pure storage array with pipelined write and flush combinational-to-registered paths.
- **State Transition Conditions**: N/A.
- **Key Timing**:
  - Write pipeline latency: 2 cycles from `writeReq(i).valid` assertion to `dataOut`/`maskOut` update. Stage 1: valid captured via `sbuffer_in_s1_line_wen`, data/mask/offset/wline registered via RegEnable. Stage 2: GatedValidRegNext produces `sbuffer_in_s2_line_wen`, register write occurs. Source: `SbufferData.scala:40-61`.
  - Mask flush pipeline latency: 2 cycles from `maskFlushReq` valid assertion to `maskOut` cleared. Stage 1: OR reduction of flush requests. Stage 2: GatedValidRegNext produces `line_mask_clean_flag`, mask register cleared. Source: `SbufferData.scala:23-33`.
  - Read latency: 0 cycles (combinational). `dataOut` and `maskOut` are direct wire connections to the internal `data` and `mask` registers. Source: `SbufferData.scala:91-92`.
  - Concurrent write and read: A write that fires on cycle N is visible on `dataOut`/`maskOut` starting at cycle N+2 (registered). A read on cycle N+1 sees the pre-write value.

### Configuration Registers and Storage
| Register Name/Address | Access Attribute | Bit Field | Default | Description | Read/Write Side Effects |
| ------------- | -------- | ---- | ------ | ---- | ---------- |
| data | internal (Reg) | Vec(StoreBufferSize, Vec(CacheLineVWords, Vec(VDataBytes, UInt(8.W)))) | All zeros (uninitialized, reset sets to 0) | Byte-level storage array for write data per entry per virtual word offset. Source: `SbufferData.scala:11`. | Written on `write_byte` condition (pipeline stage s2). Read combinational via dataOut. |
| mask | internal (RegInit) | Vec(StoreBufferSize, Vec(CacheLineVWords, Vec(VDataBytes, Bool()))) | All false | Per-byte dirty mask array per entry per virtual word offset. Source: `SbufferData.scala:13-19`. | Set to true on write (pipeline stage s2). Cleared to false on mask flush (pipeline stage s2). Read combinational via maskOut. |

- **Register Map Base Address**: No direct bus interface. Internal register file only.
- **Configuration Flow**: All storage resets to zero/false. No runtime configuration registers. All behavior is determined by the data and mask array state driven by writeReq and maskFlushReq commands.

### Reset and Error Handling
- **Reset Behavior**: After active-high synchronous reset assertion:
  - All `mask` register entries are reset to false at all virtual word offsets and all byte positions (via RegInit). Source: `SbufferData.scala:13-19`.
  - The `data` register is a plain Reg (not RegInit) and resets to all zeros (Chisel Reg semantics). Source: `SbufferData.scala:11`.
  - `dataOut` combinational outputs read 0x00 for all entries, offsets, and bytes.
  - `maskOut` combinational outputs read false for all entries, offsets, and bytes.
- **Error Reporting**: None. SbufferData has no error detection, assertion, or reporting interface.
- **Self-Recovery Strategy**: None. SbufferData has no self-recovery mechanism. Correctness relies on the parent Sbuffer to manage entry lifecycle and ensure protocol constraints (one-hot wvec, no concurrent write/flush to same entry).

### Parameterization and Configurable Features
- **Module Parameters**:

  | Parameter Name | Type/Range | Default | Functional Effect |
  | ------ | ------------- | ------ | -------- |
  | StoreBufferSize | Int | Config-dependent | Number of entries in data and mask arrays. Width of first Vec dimension for dataOut/maskOut, writeReq wvec width. |
  | EnsbufferWidth | Int | 2 | Number of concurrent writeReq ports. Width of writeReq Vec. |
  | NumDcacheWriteResp | Int | 1 | Number of concurrent maskFlushReq ports. Width of maskFlushReq Vec. |
  | CacheLineVWords | Int | Config-dependent | Number of virtual word segments per cache line (= CacheLineBytes / VDataBytes). Width of second Vec dimension for dataOut/maskOut, per-entry word iteration bounds. |
  | VDataBytes | Int | VLEN/8 | Number of bytes per VLEN-width word. Width of third Vec dimension for dataOut/maskOut, byte mask width. |
  | VLEN | Int (from HasSbufferConst) | Config-dependent | Vector register length in bits. Determines VDataBytes = VLEN/8, writeReq.bits.mask width, writeReq.bits.data width. |

- **Runtime Configuration**: None.
- **Compile Macros/Generation Options**: None.

## Verification Requirements and Coverage Suggestions
- **Functional Coverage Points**: All `CK-*` check points defined in each functional group constitute coverage targets. Additional cross-coverage scenarios:
  - Concurrent write to one entry and mask flush to a different entry in overlapping pipeline cycles.
  - Sequential write, read, flush sequence for a single entry through all virtual word offsets.
  - Full buffer fill: write to every entry at every virtual word offset, verify all data and mask.
  - Partial byte mask: write with sparse mask (e.g., only bytes 0, 7, 15), verify only those bytes updated.
  - wline write followed by partial write to same entry: verify wline data persists at unwritten offsets.
  - Back-to-back writes to same entry same offset in consecutive cycles: verify second write overwrites first.
  - Reset in the middle of a write pipeline: verify pipeline state clears and data/mask reset.
- **Constraints and Assumptions**:
  - wvec must always be one-hot. Testbench must not inject non-one-hot wvec.
  - writeReq and maskFlushReq must not target the same entry in the same cycle. Testbench must honor the Sbuffer protocol constraint.
  - writeReq must not target the same entry on multiple ports in the same cycle.
  - All commands are accepted unconditionally (no backpressure). Testbench must provide valid data on the same cycle as valid assertion.
  - Single clock domain, synchronous reset. Hold reset for at least one cycle.
- **Test Interfaces**:
  - **Write Driver**: Drive `writeReq(i).valid` and `writeReq(i).bits` with legal one-hot wvec, VLEN-width data, VLEN/8-width mask, vwordOffset, and wline flag. Sweep all entry indices, virtual word offsets, byte positions, and mask patterns.
  - **Mask Flush Driver**: Drive `maskFlushReq(i).valid` and `maskFlushReq(i).bits.wvec` with legal one-hot wvec. Verify mask clearing across all entry indices.
  - **Data/Mask Monitor**: Sample `dataOut` and `maskOut` each cycle. Cross-check against expected state from reference model.
  - **Reference Model**: Maintain a software model of the register file: entry-level byte matrix, mask matrix. On writeReq fire: update data and mask at specified entry, offset, byte positions (per pipeline latency). On maskFlushReq fire: clear mask for target entry (per pipeline latency). On reset: clear all.
  - **Pipeline Tracker**: Track in-flight writes in a 2-deep queue to predict when dataOut/maskOut will update after each writeReq or maskFlushReq command.
