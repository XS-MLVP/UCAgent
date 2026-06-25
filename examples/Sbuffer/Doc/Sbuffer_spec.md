# Sbuffer Specification Document

> This document describes the specification of the `Sbuffer` chip verification target. Keep the technical language precise, well-organized, and easy to reuse for verification. If an item does not exist, explicitly write "None" or "TBD"; do not delete the section.

## Introduction
- **Design Background**: The Sbuffer (Store Buffer) sits between the load-store unit (LSU) and the L1 data cache (DCache) in the XiangShan high-performance RISC-V processor. It buffers store requests to hide DCache write latency, enables store-to-load forwarding, and manages writeback ordering to DCache. Sbuffer is a layer-0 module that instantiates two sub-modules: SbufferData (byte-level storage array) and StorePfWrapper (optional store prefetcher). Source: `engine_overview.txt:3-18`, `Sbuffer.scala:1-18`.
- **Design Goals**: (1) Accept store enqueue requests from LSU on EnsbufferWidth (typically 2) parallel Decoupled ports. (2) Insert new entries or merge into existing entries sharing the same physical tag. (3) Provide store-to-load forwarding via CAM-based tag match on LoadPipelineWidth (typically 2) parallel query ports. (4) Evict entries to DCache using a 2-stage output pipeline, respecting same-block inflight constraints. (5) Support flush/drain through a custom handshake. (6) Track coherence timeout and replay timeout per entry, triggering eviction accordingly. (7) Enforce one-writer-per-cache-line invariant during DCache writeback.

## Terms and Abbreviations in Chisel Code

| Abbreviation | Full Term | Description |
| ---- | ---- | ---- |
| Sbuffer | Store Buffer | The top-level module buffering store requests between LSU and DCache |
| LSU | Load-Store Unit | The upstream unit that issues store requests into Sbuffer |
| DCache | L1 Data Cache | The downstream cache that Sbuffer writes back into |
| ptag | Physical Tag | Physical address tag: pa[PAddrBits-1 : PAddrBits-PTagWidth] |
| vtag | Virtual Tag | Virtual address tag: va[VAddrBits-1 : VAddrBits-VTagWidth] |
| wvec | Write Vector | One-hot UInt of width StoreBufferSize selecting which entry to target |
| VLEN | Vector Length | Vector register width in bits |
| VDataBytes | Vector Data Bytes | Number of bytes per VLEN-width word (= VLEN / 8) |
| CacheLineBytes | Cache Line Bytes | Number of bytes per cache line (= CacheLineSize / 8) |
| CacheLineVWords | Cache Line Virtual Words | Number of VDataBytes segments per cache line (= CacheLineBytes / VDataBytes) |
| OffsetWidth | Offset Width | Number of bits for byte offset within a cache line (= log2Up(CacheLineBytes)) |
| PTagWidth | Physical Tag Width | Physical tag bit width (= PAddrBits - OffsetWidth) |
| VTagWidth | Virtual Tag Width | Virtual tag bit width (= VAddrBits - OffsetWidth) |
| EnsbufferWidth | Enqueue Buffer Width | Number of concurrent enqueue ports (typically 2) |
| LoadPipelineWidth | Load Pipeline Width | Number of load forward query ports (typically 2) |
| StorePipelineWidth | Store Pipeline Width | Number of store pipeline ports for prefetch |
| StoreBufferSize | Store Buffer Size | Total number of store buffer entries |
| SbufferIndexWidth | Sbuffer Index Width | Bit width for entry index (= log2Up(StoreBufferSize)) |
| FSM | Finite State Machine | The 4-state controller governing sbuffer operation mode |
| PLRU | Pseudo Least Recently Used | Replacement policy for selecting eviction candidate |
| cohCount | Coherence Count | Per-entry counter tracking cycles since entry became active, for coherence timeout |
| missqReplayCount | Miss Queue Replay Count | Per-entry counter tracking replay delay cycles |
| Decoupled | Ready-Valid interface | Chisel standard handshake: transaction fires when valid && ready |
| ValidIO | Valid-only interface | Valid signal only, no backpressure; consumer must always accept |
| hit_resp | Hit Response | DCache write completion acknowledgment |
| replay_resp | Replay Response | DCache signals the write must be retried |
| wline | Write Line | Flag indicating a full cache line write |

## Chisel Source Files

The Sbuffer module and its supporting types are defined across several files in the extracted source directory.

File list:
- `Sbuffer.scala:1-913`: Top-level Sbuffer module definition — enqueue pipeline, eviction pipeline, forward pipeline, FSM, coherence/replay tracking, difftest, and performance counters.
- `SbufferData.scala:1-93`: Submodule providing byte-level data array and per-byte mask array with registered write and mask-flush ports.
- `SbufferEntryState.scala:1-12`: Bundle defining the 4-bit entry state vector (state_valid, state_inflight, w_timeout, w_sameblock_inflight) with helper methods.
- `DataWriteReq.scala:1-9`: Bundle for SbufferData write commands (wvec, mask, data, vwordOffset, wline).
- `MaskFlushReq.scala:1-4`: Bundle for SbufferData mask-flush commands (wvec only).
- `SbufferFlushBundle.scala:1-4`: Bundle for flush handshake (valid=Output, empty=Input).
- `SbufferBundle.scala:1`: Base bundle type extending XSBundle with HasSbufferConst.
- `HasSbufferConst.scala:1-27`: Trait defining parameter-derived constants (EvictCycles, EvictCountBits, PTagWidth, VTagWidth, OffsetWidth, CacheLineVWords, etc.).

## Top-Level Interface Overview
- **Module Name**: `Sbuffer`
- **Port List**:

  | Signal Name | Direction | Width/Type | Reset Value | Description |
  | ------ | ---- | -------- | ------ | ---- |
  | clock | input | Clock | N/A | Clock signal. Single clock domain. |
  | reset | input | Reset | N/A | Active-high synchronous reset. |
  | hartId | input | UInt(hartIdLen.W) | N/A | Hardware thread ID for difftest attribution. Source: `Sbuffer.scala:6`. |
  | in | Vec input (Flipped Decoupled) | Vec(EnsbufferWidth, Flipped(Decoupled(DCacheWordReqWithVaddrAndPfFlag))) | valid=0, ready=N/A | Store enqueue ports from LSU. Carries addr, data, mask, vaddr, wline, vecValid, prefetch flags. Source: `Sbuffer.scala:7`. |
  | dcache | Flipped bundle | Flipped(DCacheToSbufferIO) | See sub-fields | Interface to L1 DCache. Contains req (Decoupled output), hit_resps (Vec ValidIO input), main_pipe_hit_resp (ValidIO input), refill_hit_resp (ValidIO input), replay_resp (ValidIO input). Source: `Sbuffer.scala:8`. |
  | dcache.req.valid | output | Bool() | 0 | DCache write request valid. Source: `Sbuffer.scala:502`. |
  | dcache.req.ready | input | Bool() | N/A | DCache write request ready. |
  | dcache.req.bits.cmd | output | MemoryOpConstants | N/A | Write command (M_XWR). Source: `Sbuffer.scala:504`. |
  | dcache.req.bits.addr | output | UInt(PAddrBits.W) | N/A | Physical address constructed from evicted entry's ptag. Source: `Sbuffer.scala:505`. |
  | dcache.req.bits.vaddr | output | UInt(VAddrBits.W) | N/A | Virtual address constructed from evicted entry's vtag. |
  | dcache.req.bits.data | output | UInt(CacheLineBytes*8.W) | N/A | Cache-line-wide data read from SbufferData. Source: `Sbuffer.scala:507`. |
  | dcache.req.bits.mask | output | UInt(CacheLineBytes.W) | N/A | Cache-line-wide byte mask read from SbufferData. Source: `Sbuffer.scala:508`. |
  | dcache.req.bits.id | output | UInt | N/A | Evicted entry index. Source: `Sbuffer.scala:509`. |
  | dcache.hit_resps | Vec input (ValidIO) | Vec(NumDcacheWriteResp, ValidIO) | valid=0 | DCache write completion. bits.id identifies the completed entry, bits.replay and bits.miss indicate status. Source: `Sbuffer.scala:523-548`. |
  | dcache.replay_resp | ValidIO input | ValidIO | valid=0 | DCache signals retry needed. Sbuffer sets w_timeout on the entry. Source: `Sbuffer.scala:556-563`. |
  | forward | Vec Flipped bundle | Vec(LoadPipelineWidth, Flipped(LoadForwardQueryIO)) | valid=0 | Load forwarding query ports. Input: vaddr, paddr, valid. Output per port: forwardMask, forwardData, forwardMaskFast, matchInvalid, dataInvalid, addrInvalid. Source: `Sbuffer.scala:9, 592-660`. |
  | sqempty | input | Bool() | N/A | Store queue is empty signal from LSU. Used for flush completion detection. Source: `Sbuffer.scala:10`. |
  | sbempty | output | Bool() | 1 (after reset, when buffer empty) | Store buffer is empty. Registered via GatedValidRegNext from empty condition. Source: `Sbuffer.scala:11, 360`. |
  | flush | Flipped bundle | Flipped(SbufferFlushBundle) | valid=0, empty=1 | Flush handshake. valid is Output (external drives), empty is Input (Sbuffer drives). When valid asserted, Sbuffer enters drain mode and asserts empty when done. Source: `Sbuffer.scala:12, 361`. |
  | csrCtrl | Flipped bundle | Flipped(CustomCSRCtrlIO) | N/A | CSR control interface including sbuffer_threshold for eviction triggering. |
  | store_prefetch | Vec Decoupled output | Vec(StorePipelineWidth, DecoupledIO(StorePrefetchReq)) | valid=0 | Prefetch requests to DCache. Fields: paddr, vaddr. Source: `Sbuffer.scala:14, 214-231`. |
  | memSetPattenDetected | input | Bool() | N/A | Memory set pattern detected signal fed to store prefetcher. Source: `Sbuffer.scala:15, 233`. |
  | force_write | input | Bool() | N/A | Force writeback — lowers eviction threshold by SbufferBase. Source: `Sbuffer.scala:16, 354`. |
  | diffStore | input | Flipped(DiffStoreIO) | N/A | Differential testing store event input from commit stage. Source: `Sbuffer.scala:17`. |

- **Clock and Reset Requirements**: Single clock domain. Active-high synchronous reset. After reset assertion: all stateVec entries are invalid (state_valid = false), all cohCount and missqReplayCount entries are zero, FSM is x_idle, sbempty deasserted (buffer empty), enbufferSelReg is false, all waitInflightMask entries are zero, dcache.req.valid deasserted, flush.empty asserted. Source: `Sbuffer.scala:31, 33, 46, 174`.
- **External Dependencies**: 
  - Upstream LSU must obey Decoupled protocol on `io.in`: hold valid/addr/data/mask/vaddr stable until ready is asserted, deassert valid after fire.
  - Downstream DCache must obey Decoupled protocol on `io.dcache.req` and drive hit_resps, main_pipe_hit_resp, refill_hit_resp, replay_resp with proper ValidIO semantics.
  - Load forwarding query consumers must provide paddr, vaddr, and valid on `io.forward` query ports.
  - Flush initiator must assert `io.flush.valid` and deassert after Sbuffer reports `io.flush.empty`.
  - Sbuffer asserts PopCount(sameBlockInflightMask) ≤ 1 via assertion at `Sbuffer.scala:404`.

## Functional Description

### API — Test and Verification Interface

<FG-API>

- **Overview**: This functional group describes the standard interfaces a testbench must implement to drive and observe the Sbuffer DUT. Covers store enqueue drivers, DCache response drivers/monitors, load forward query drivers, flush drivers, and internal state monitors.
- **Execution Flow**: Testbench drives `io.in(i).valid` with request data, waits for `io.in(i).ready` to fire, then deasserts valid or presents next request. For eviction verification, testbench drives `io.dcache.req.ready` and `io.dcache.hit_resps(i).valid`/`io.dcache.replay_resp.valid` to simulate DCache write completion or replay. For forward verification, testbench drives `io.forward(i).valid` with vaddr/paddr and observes `io.forward(i).forwardMask`, `io.forward(i).forwardData`, and `io.forward(i).matchInvalid`.
- **Boundaries and Exceptions**: 
  - Testbench must not drive `io.in(i).valid` when `sbuffer_state === x_drain_sbuffer`, as `io.in(0).ready` is deasserted in drain state (only drains, no enqueue).
  - Testbench must respect Decoupled protocol: must not change valid/bits on cycles where valid=1 but ready=0.
  - `io.dcache.req.ready` must not depend on `io.dcache.req.valid` in the same cycle.
- **Performance and Constraints**: Enqueue bandwidth up to EnsbufferWidth transactions per cycle (when buffer not full). Forward query bandwidth up to LoadPipelineWidth queries per cycle. Eviction throughput limited by DCache write pipeline acceptance rate.

#### Store Enqueue Driver Interface

<FC-STORE-ENQUEUE-DRIVER>

The testbench drives `io.in(i)` with store requests following the Decoupled protocol. A store request fires when `io.in(i).valid && io.in(i).ready` in the same cycle. The testbench must drive `io.in(i).bits.addr` (physical address), `io.in(i).bits.vaddr` (virtual address), `io.in(i).bits.data` (VLEN-width data), `io.in(i).bits.mask` (VLEN/8 bits per-byte mask), `io.in(i).bits.vecValid` (vector valid flag), `io.in(i).bits.wline` (full-cache-line write flag), and `io.in(i).bits.prefetch` (prefetch trigger flag).

**Check points:**
- <CK-DRIVE-VALID-READY> Assert `io.in(0).valid` with valid store request data; when `io.in(0).ready` is also asserted, transaction fires. Verify `io.in(0).fire` is true for that cycle.
- <CK-DRIVE-BACKPRESSURE> Assert `io.in(0).valid` while `io.in(0).ready` is deasserted; verify `io.in(0).fire` is false and bits held stable.
- <CK-DRIVE-VEC-INVALID> Assert `io.in(0).valid` with `io.in(0).bits.vecValid=false`; transaction fires with io.in(0).ready asserted but no SbufferData write or metadata update occurs (vecValid gates enqueue effects).
- <CK-DRIVE-FORCE-WRITE> Assert `io.force_write` to lower eviction threshold; verify eviction fires at lower occupancy.

#### DCache Response Monitor Interface

<FC-DCACHE-RESP-MONITOR>

The testbench monitors DCache write responses to verify eviction completion. When `io.dcache.hit_resps(i).fire` (valid asserted), the testbench must check that the corresponding entry's state_inflight deasserts, state_valid deasserts, and mask is flushed via SbufferData. When `io.dcache.replay_resp.fire`, the entry's w_timeout must be set and missqReplayCount reset to zero.

**Check points:**
- <CK-MONITOR-HIT-RESP> Drive `io.dcache.hit_resps(0).valid` with `bits.id=E` and `bits.replay=false`, `bits.miss=false`; verify on next cycle `stateVec(E).state_inflight` is false and `stateVec(E).state_valid` is false.
- <CK-MONITOR-REPLAY-RESP> Drive `io.dcache.replay_resp.valid` with `bits.id=E` and `bits.replay=true`; verify `stateVec(E).w_timeout` is set and `missqReplayCount(E)` is zero.
- <CK-MONITOR-MASK-FLUSH> After hit response for entry E fires, verify `maskFlushReq(0).valid` asserts and `maskFlushReq(0).bits.wvec` equals one-hot for entry E. Verify SbufferData mask for entry E clears on subsequent cycle.

#### Internal State Monitor Interface

<FC-INTERNAL-STATE-MONITOR>

The testbench monitors internal state for verification: `sbuffer_state` (FSM state), `stateVec` (entry states), `activeMask`, `validMask`, `inflightMask`, `cohCount`, `missqReplayCount`, `ptag`/`vtag` arrays, `sbempty`, `flush.empty`. Testbench reads `dataModule.io.dataOut` and `dataModule.io.maskOut` through the Sbuffer's `data`/`mask` wires for data integrity checks.

**Check points:**
- <CK-MONITOR-FSM> Read `sbuffer_state` at any cycle; verify value is one of {x_idle, x_replace, x_drain_all, x_drain_sbuffer}.
- <CK-MONITOR-EMPTY> With no entries active, verify `sbempty === true` and `flush.empty === true`.
- <CK-MONITOR-ENTRY-COUNT> Verify `PopCount(activeMask)` plus `PopCount(inflightMask)` plus `PopCount(invalidMask)` equals `StoreBufferSize`.
- <CK-MONITOR-COH-COUNT> For an active entry E, verify `cohCount(E)` increments by 1 each cycle until cohTimeOutMask(E) asserts or entry state changes.

### Store Enqueue Pipeline

<FG-STORE-ENQUEUE>

- **Overview**: The enqueue pipeline accepts store requests from LSU on EnsbufferWidth parallel Decoupled ports, determines whether each request merges into an existing entry (same physical tag match) or allocates a new entry (invalid entry), and updates metadata and data in a 3-stage pipeline (s0/s1/s2). Stage s0 buffers the request in a 2-entry FIFO. Stage s1 updates metadata (ptag, vtag, state) and prepares pipeline registers for data write. Stage s2 writes data/mask into SbufferData. Source: `Sbuffer.scala:108-122`.
- **Execution Flow**:
  1. **Merge vs. Insert Decision**: For each enqueue port i, compute `mergeMask(i)` = one-hot mask of entries with matching ptag (ptag equals inptags(i) AND entry is active). If `mergeMask(i)` is non-zero, the request merges; otherwise, a new entry is allocated at an even/odd interleaved insert position. Source: `Sbuffer.scala:141-146`.
  2. **Insert Position Selection**: Insert positions alternate between even and odd indices via `enbufferSelReg` (toggles on port 0 valid). Port 0 gets the current parity's first invalid entry. Port 1 gets: (a) the same insert index as port 0 if both ports share the same physical tag (`sameTag`), or (b) the opposite parity's first invalid entry otherwise. Source: `Sbuffer.scala:164-193`.
  3. **New Entry Allocation** (`wordReqToBufLine`): Sets `stateVec(entryIdx).state_valid = true`, writes ptag and vtag, resets `cohCount` to 0, sets `w_sameblock_inflight` if any entry with the same ptag is already inflight to DCache, and records blocking entry in `waitInflightMask`. Source: `Sbuffer.scala:235-258`.
  4. **Merge** (`mergeWordReq`): Resets `cohCount` to 0. Triggers microarchitectural drain (`merge_need_uarch_drain`) if the new request's vtag differs from the existing entry's vtag. Source: `Sbuffer.scala:260-279`.
  5. **Data Write** (stage s2): Drives `writeReq(i).valid`, `writeReq(i).bits.wvec` (one-hot insert or merge vector), `writeReq(i).bits.vwordOffset` (from vword extraction), `writeReq(i).bits.mask`, `writeReq(i).bits.data`, and `writeReq(i).bits.wline` to SbufferData. Source: `Sbuffer.scala:281-319`.
- **Boundaries and Exceptions**:
  - Enqueue is blocked when `sbuffer_state === x_drain_sbuffer` (`firstCanInsert` depends on `sbuffer_state =/= x_drain_sbuffer`). Source: `Sbuffer.scala:189`.
  - Port 1 ready depends on port 0 ready: `io.in(1).ready := secondCanInsert && io.in(0).ready`. Source: `Sbuffer.scala:200`.
  - Sbuffer asserts `PopCount(mergeMask(i).asUInt) <= 1` when enqueue fires — at most one active entry with the same ptag may exist. Source: `Sbuffer.scala:145`.
  - Sbuffer asserts `PopCount(insertVec) <= 1` when enqueue fires — insert vector is one-hot. Source: `Sbuffer.scala:289`.
  - Sbuffer asserts `UIntToOH(insertIdx) === insertVec` — insert index matches vector. Source: `Sbuffer.scala:243`.
  - When `io.in(i).bits.vecValid` is false, the enqueue fires but no SbufferData write or metadata update occurs — the request is consumed without side effects beyond Decoupled handshake. Source: `Sbuffer.scala:282-298`.
- **Performance and Constraints**: 
  - Up to EnsbufferWidth enqueues per cycle when both ports ready.
  - Same-tag enqueues on both ports: port 1 uses same insert position as port 0 (shared entry allocation, both requests map to same entry).
  - `require(EnsbufferWidth <= StorePipelineWidth)` — enqueue width must not exceed store pipeline width. Source: `Sbuffer.scala:341`.

#### Insert New Entry — Allocate Fresh Buffer Slot

<FC-INSERT-NEW-ENTRY>

When a store request fires on port i with `canMerge(i)` false (no existing entry with matching ptag), the Sbuffer allocates a new entry at the insert position determined by `enbufferSelReg` parity and availability. The new entry's state_valid is set, ptag and vtag are written, cohCount is reset to zero, and w_sameblock_inflight is set if any inflight entry shares the same ptag.

**Check points:**
- <CK-INSERT-EMPTY-BUFFER> Buffer is empty (all entries invalid). Enqueue store to address A on port 0: entry inserted at the even-parity first invalid position. Verify `stateVec(entry).state_valid = true`, `ptag(entry) = getPTag(A)`, `vtag(entry) = getVTag(A)`, `cohCount(entry) = 0`.
- <CK-INSERT-ALTERNATING-PARITY> Insert entry E0 on port 0 (even parity), then entry E1 on port 0 again: E1 inserted at odd-parity position. Verify `enbufferSelReg` toggles on port 0 valid.
- <CK-INSERT-BOTH-PORTS-DIFFERENT-TAG> Port 0 and port 1 fire in same cycle with different physical tags: both ports allocate at their respective parity positions. Verify two distinct entries created.
- <CK-INSERT-BOTH-PORTS-SAME-TAG> Port 0 and port 1 fire in same cycle with same physical tag: port 1 uses the same insert position as port 0. Verify only one entry created, both requests target same entry.
- <CK-INSERT-SAME-BLOCK-INFLIGHT> Entry E is inflight to DCache with ptag T. Enqueue new request with ptag T to entry N: verify `stateVec(N).w_sameblock_inflight = true` and `waitInflightMask(N)` encodes entry E.

#### Merge Into Existing Entry

<FC-MERGE-EXISTING-ENTRY>

When a store request fires on port i with `canMerge(i)` true, the Sbuffer merges into the existing active entry with matching ptag (identified by `mergeIdx(i)`). The cohCount of the merged entry resets to zero. If the request's vtag differs from the entry's vtag, a microarchitectural drain (`merge_need_uarch_drain`) is triggered.

**Check points:**
- <CK-MERGE-SAME-VTAG> Entry E active with ptag T, vtag V. Enqueue store with ptag T, vtag V: merge to entry E. Verify `cohCount(E)` reset to 0, `writeReq.wvec` selects entry E, no drain triggered.
- <CK-MERGE-DIFFERENT-VTAG> Entry E active with ptag T, vtag V1. Enqueue store with ptag T, vtag V2 (V1 != V2): merge triggers `merge_need_uarch_drain`. Verify `do_uarch_drain` is true and FSM transitions to x_drain_sbuffer after pipeline delay.
- <CK-MERGE-COH-COUNT-RESET> Entry E has cohCount=C. Merge into E: verify cohCount(E) reset to 0 on merge cycle.
- <CK-MERGE-METADATA-PRESERVED> Entry E has ptag T, vtag V. Merge into E with same ptag T, vtag V: verify ptag(E) and vtag(E) unchanged after merge.
- <CK-MERGE-WVEC> Merge into entry E on port 0: verify `writeReq(0).bits.wvec` is one-hot selecting entry E.

#### Enqueue Backpressure

<FC-ENQUEUE-BACKPRESSURE>

Sbuffer controls enqueue acceptance through the `io.in(i).ready` signal. Port 0 ready depends on the first insert position availability and FSM state. Port 1 ready depends on the second insert position availability, FSM state, AND port 0's ready. Neither port accepts enqueue during x_drain_sbuffer state.

**Check points:**
- <CK-BLOCK-FULL-BUFFER> Fill all Sbuffer entries (no invalid entries remain). Verify `io.in(0).ready = false` and `io.in(1).ready = false`.
- <CK-BLOCK-DRAIN-STATE> Force FSM to x_drain_sbuffer. Verify `io.in(0).ready = false` regardless of buffer occupancy.
- <CK-BLOCK-PORT1-DEPENDENCY> Deassert `io.in(0).ready`. Verify `io.in(1).ready = false` even if insert position for port 1 is available.
- <CK-BLOCK-ONLY-EVEN-AVAILABLE> Only even-parity entries are invalid (odd entries all valid), `enbufferSelReg = false` (targeting even). Verify `io.in(0).ready = true`. After port 0 valid toggles selReg, verify ready state updates correctly for the new parity.

### DCache Eviction Pipeline

<FG-DCACHE-EVICTION>

- **Overview**: The eviction pipeline selects a candidate entry and sends it as a write request to the L1 DCache via a 2-stage pipeline (s0/s1) with an extra stage for response handling. Eviction is triggered by: buffer occupancy above threshold, coherence timeout, buffer full, drain request, or microarchitectural drain. The candidate selection follows a fixed priority: miss queue replay timeout > drain > coherence timeout > replacement (PLRU). Source: `Sbuffer.scala:412-553`.
- **Execution Flow**:
  1. **Candidate Selection** (`sbuffer_out_s0_evictionIdx`): Priority-ordered selection. If `missqReplayHasTimeOut`, select the replay-timed-out entry. Else if `needDrain`, select the lowest-index active entry (drainIdx). Else if `cohHasTimeOut`, select the coherence-timed-out entry. Else select the PLRU replacement candidate (`replaceIdx`). Source: `Sbuffer.scala:436-444`.
  2. **Eviction Valid Condition** (`sbuffer_out_s0_valid`): True if replay timeout OR (selected entry is a DCache-req candidate AND (need drain OR coherence timeout OR need replace)). Source: `Sbuffer.scala:448-450`.
  3. **Stage s0**: When `sbuffer_out_s0_fire` (valid && cango), read ptag/vtag/data/mask for the selected entry, set `state_inflight = true`, `w_timeout = false`. Pipeline addr/data/mask/id to stage s1 via RegEnable. Source: `Sbuffer.scala:482-500`.
  4. **Stage s1**: When `sbuffer_out_s1_valid && !blockDcacheWrite && io.dcache.req.ready`, fire `io.dcache.req` with cmd=M_XWR, addr from ptag, vaddr from vtag, data from SbufferData dataOut, mask from SbufferData maskOut, and entry index as id. Source: `Sbuffer.scala:502-509`.
  5. **Response Handling (extra stage)**: On DCache hit response fire: clear `state_inflight` and `state_valid` of the target entry, trigger mask flush via `maskFlushReq`. On replay response fire: set `w_timeout = true`, reset `missqReplayCount` to 0. Source: `Sbuffer.scala:523-563`.
- **Boundaries and Exceptions**:
  - Eviction is blocked when the selected entry shares the same ptag with an inflight entry (same-block inflight constraint). Assertion at `Sbuffer.scala:451-454` verifies this: if the selected entry is a DCache-req candidate, `noSameBlockInflight(selectedIdx)` must be true.
  - Eviction is blocked when SbufferData enqueue write targets the same entry (`shouldWaitWriteFinish` — read/write hazard). Source: `Sbuffer.scala:463-468`.
  - Same-block inflight mask enforces `PopCount(sameBlockInflightMask) <= 1` via assertion at `Sbuffer.scala:404`.
  - `replaceAlgoNotDcacheCandidate` assertion verifies PLRU selection is always valid when `candidateVec` has at least one true entry. Source: `Sbuffer.scala:89`.
- **Performance and Constraints**: 
  - Maximum one eviction inflight to DCache at a time (single `io.dcache.req` output port).
  - PLRU replacement may not be accurate when other requests in the same cache block are inflight (comment at `Sbuffer.scala:493-494`).

#### Eviction Candidate Selection Priority

<FC-EVICTION-PRIORITY>

The eviction candidate index is selected by a fixed priority encoder: (1) miss queue replay timeout, (2) drain (lowest active index), (3) coherence timeout, (4) PLRU replacement. Only one eviction is processed at a time. The priority ensures that time-critical entries (replay timeout, explicit drain requests) are serviced before opportunistic evictions.

**Check points:**
- <CK-PRIORITY-REPLAY> An entry E has `missqReplayTimeOutMask(E) = true`. Simultaneously, `cohHasTimeOut = true` for entry F and `candidateVec` has entries available for PLRU. Verify `sbuffer_out_s0_evictionIdx` selects E.
- <CK-PRIORITY-DRAIN> FSM in x_drain_all state, no replay timeout, no coherence timeout. Active entries exist. Verify `sbuffer_out_s0_evictionIdx` equals the lowest-index active entry (PriorityEncoder of activeMask).
- <CK-PRIORITY-COH-TIMEOUT> cohHasTimeOut for entry E, no replay timeout, no drain. Verify `sbuffer_out_s0_evictionIdx` selects entry E.
- <CK-PRIORITY-REPLACE> Buffer occupancy exceeds threshold, no replay timeout, no drain, no coherence timeout. Verify eviction fires using PLRU replacement candidate.
- <CK-PLRU-ACCESS> An entry is accessed (enqueued or merged), PLRU access is recorded via `accessIdx`. Verify subsequent PLRU eviction prefers less recently accessed entries.
- <CK-PLRU-CANDIDATE-MASK> Verify PLRU selection only considers entries where `isDcacheReqCandidate()` is true (state_valid && !state_inflight && !w_sameblock_inflight).

#### DCache Write Request Protocol

<FC-DCACHE-WRITE-REQUEST>

When stage s1 fires, Sbuffer sends a write request to DCache via `io.dcache.req` using the Decoupled protocol. The request carries the full cache line data and mask from SbufferData for the evicted entry.

**Check points:**
- <CK-WRITE-REQ-FIRE> Eviction fires through s0 and s1 stages, `io.dcache.req.ready = true`. Verify `io.dcache.req.valid = true`, `io.dcache.req.bits.cmd = M_XWR`, `io.dcache.req.bits.id` equals evicted entry index.
- <CK-WRITE-REQ-BACKPRESSURE> `io.dcache.req.ready = false`. Verify `io.dcache.req.valid` deasserted after s1 pipeline register loads (sbuffer_out_s1_valid stays high but valid is gated by blockDcacheWrite check). Verify addr, data, mask, id stable across backpressure cycles.
- <CK-WRITE-DATA-CORRECT> Insert entry E with known data D and mask M. Evict E to DCache. Verify `io.dcache.req.bits.data` matches D and `io.dcache.req.bits.mask` matches M for the full cache line.
- <CK-WRITE-ADDR-FROM-PTAG> Insert entry with ptag T. Verify `io.dcache.req.bits.addr` equals `Cat(T, 0.U(OffsetWidth.W))` when E is evicted.

#### DCache Hit Response Handling

<FC-HIT-RESPONSE-HANDLING>

When DCache signals a write hit completion via `io.dcache.hit_resps(i).fire`, Sbuffer clears `state_inflight` and `state_valid` on the corresponding entry, and issues a mask flush to SbufferData. The w_sameblock_inflight flag of other entries waiting on this inflight entry is cleared after one cycle delay.

**Check points:**
- <CK-HIT-RESP-CLEAR-STATE> Entry E is inflight to DCache. Drive `io.dcache.hit_resps(0).valid` with `bits.id=E`, `bits.replay=false`, `bits.miss=false`. Verify next cycle: `stateVec(E).state_inflight=false`, `stateVec(E).state_valid=false`.
- <CK-HIT-RESP-MASK-FLUSH> Hit response fire for entry E. Verify `dataModule.io.maskFlushReq(0).valid = true` and `dataModule.io.maskFlushReq(0).bits.wvec` is one-hot for entry E.
- <CK-HIT-RESP-ASSERTIONS> Hit response fires with replay=true or miss=true: verify assertion failure (assert(!resp.bits.replay), assert(!resp.bits.miss) at `Sbuffer.scala:528-529`).
- <CK-SAME-BLOCK-CLEAR> Entry A is active with `w_sameblock_inflight=true` waiting on inflight entry B. Hit response fires for entry B. Verify on the following cycle: `stateVec(A).w_sameblock_inflight` is cleared to false.
- <CK-HIT-RESP-INFLIGHT-ASSERT> Hit response fires but `stateVec(id).state_inflight !== true`: verify assertion failure at `Sbuffer.scala:530`.

#### DCache Replay Response Handling

<FC-REPLAY-RESPONSE-HANDLING>

When DCache signals a replay via `io.dcache.replay_resp.fire`, Sbuffer sets `w_timeout = true` on the target entry and resets `missqReplayCount` to zero. The entry remains inflight and will be re-evicted after the replay delay timeout (missqReplayCount reaches SbufferReplayDelayCycles).

**Check points:**
- <CK-REPLAY-SET-TIMEOUT> Entry E is inflight to DCache. Drive `io.dcache.replay_resp.valid` with `bits.id=E`, `bits.replay=true`. Verify `stateVec(E).w_timeout = true` and `missqReplayCount(E) = 0`.
- <CK-REPLAY-ASSERTION> Replay response fires but `resp.bits.replay !== true`: verify assertion failure at `Sbuffer.scala:561`.
- <CK-REPLAY-INFLIGHT-ASSERT> Replay response fires but `stateVec(id).state_inflight !== true`: verify assertion failure at `Sbuffer.scala:562`.
- <CK-REPLAY-COUNT-INCREMENT> After replay sets `w_timeout = true` on entry E, verify `missqReplayCount(E)` increments by 1 each cycle while `w_timeout && state_inflight && !timeoutBit`.
- <CK-REPLAY-TIMEOUT-TRIGGER> Entry E has w_timeout, `missqReplayCount(E)` reaches `SbufferReplayDelayCycles` (MSB set). Verify `missqReplayTimeOutMask(E) = true` and E becomes the eviction candidate.

#### Eviction Blocking Conditions

<FC-EVICTION-BLOCKING>

Eviction is blocked when: (1) the selected eviction candidate shares a ptag with an entry already inflight to DCache (same-block inflight), or (2) the selected eviction candidate is being written by the enqueue pipeline in the same cycle (read/write hazard).

**Check points:**
- <CK-BLOCK-SAME-BLOCK-INFLIGHT> Entry A is inflight to DCache with ptag T. Entry B is a DCache-req candidate with ptag T. Verify `sbuffer_out_s0_valid` is false for entry B (noSameBlockInflight(B) is false).
- <CK-BLOCK-WRITE-HAZARD> Enqueue port writes to entry E in stage s2. Simultaneously, E is selected as eviction candidate. Verify `shouldWaitWriteFinish = true` and `blockDcacheWrite = true`.
- <CK-UNBLOCK-AFTER-INFLIGHT-CLEAR> Entry A inflight with ptag T, entry B candidate with ptag T. Hit response clears entry A's inflight. Verify entry B becomes eligible for eviction on next cycle.

### Load Forwarding

<FG-LOAD-FORWARD>

- **Overview**: The forward pipeline provides store-to-load forwarding for LoadPipelineWidth (typically 2) parallel load query ports. Each port receives a virtual address (vaddr) and physical address (paddr) from the load unit. Sbuffer performs CAM-based tag matching against all entries' vtags and ptags, detects mismatches, and outputs per-byte forward mask and data. Active entries have priority over inflight entries for forwarding. Source: `Sbuffer.scala:589-660`.
- **Execution Flow**:
  1. **Tag Matching**: For each forward port i, compute `vtag_matches` (CAM: each entry's vtag equals vtag of forward.vaddr) and `ptag_matches` (registered ptag of each entry equals registered ptag of forward.paddr, both captured on forward.valid). Source: `Sbuffer.scala:593-595`.
  2. **Mismatch Detection**: If vtag_matches and ptag_matches differ for any active or inflight entry, a tag mismatch is detected (`tag_mismatch = true`). This triggers `forward_need_uarch_drain` and sets `forward.matchInvalid = true`. Source: `Sbuffer.scala:597-603, 642`.
  3. **Data/Mask Selection**: Forward mask and data candidates are registered from SbufferData on `forward.valid`, indexed by `getVWordOffset(forward.paddr)`. The registered candidates are then selected via Mux1H from matching entries: first from inflight entries, then overridden by valid (active) entries (active has higher priority). Source: `Sbuffer.scala:618-658`.
  4. **Per-Byte Forward Output**: For each byte j (0 to VDataBytes-1), `forward.forwardData(j)` contains the byte from the highest-priority matching entry, and `forward.forwardMask(j)` is true when a forward is present. Source: `Sbuffer.scala:643-658`.
- **Boundaries and Exceptions**:
  - When `tag_mismatch` is detected, `forward_need_uarch_drain` is set, which triggers FSM transition to x_drain_sbuffer after GatedValidRegNext pipeline delay. Source: `Sbuffer.scala:602, 196`.
  - `forward.matchInvalid` is set to `tag_mismatch` — the load unit must handle this by not using forward data.
  - `forward.dataInvalid` is always false (data in store line merge buffer is always valid when mask is set). Source: `Sbuffer.scala:641`.
  - `forward.addrInvalid` is DontCare (not driven by Sbuffer).
- **Performance and Constraints**: 
  - Up to LoadPipelineWidth forwarding queries per cycle.
  - Forwarding pipeline latency: 1 cycle from `forward.valid` assertion to forward data/mask output (via RegEnable).

#### Tag Matching and Mismatch Detection

<FC-TAG-MATCHING>

For each load forward query port, Sbuffer compares the query's vtag and ptag against all entries' vtags and ptags. A tag mismatch between vtag CAM and ptag CAM results for any valid (active or inflight) entry triggers a microarchitectural drain and invalidates the forward result.

**Check points:**
- <CK-TAG-MATCH-VALID> Entry E is active with vtag V and ptag P. Forward query with vaddr mapping to vtag V and paddr mapping to ptag P, with `forward.valid = true`. Verify `vtag_matches(E) = true` and `ptag_matches(E) = true`, `tag_mismatch = false`, `forward.matchInvalid = false`.
- <CK-TAG-MISMATCH-TRIGGER-DRAIN> Entry E is active with vtag V1 and ptag P. Forward query with vaddr mapping to vtag V2 (V2 != V1) and paddr mapping to ptag P. Verify `tag_mismatch = true`, `forward_need_uarch_drain = true`, `forward.matchInvalid = true`.
- <CK-TAG-MATCH-INFLIGHT> Entry E is inflight (not active) with vtag V and ptag P. Forward query matches both tags. Verify `inflight_tag_matches(E) = true`, `valid_tag_matches(E) = false`.
- <CK-TAG-INVALID-ENTRY-IGNORED> Entry E is invalid (not active, not inflight). Forward query vtag/paddr happen to match stored values. Verify mismatch detection ignores entry E (gated by `activeMask(w) || inflightMask(w)` at `Sbuffer.scala:598`).

#### Forward Data Priority

<FC-FORWARD-PRIORITY>

Active (valid, non-inflight) entries have higher forwarding priority than inflight entries. When both an active entry and an inflight entry match the query tags, the active entry's data is forwarded. The priority is implemented via Mux1H selection order: inflight data is selected first, then overwritten by valid data.

**Check points:**
- <CK-ACTIVE-OVER-INFLIGHT> Entry A is active (state_valid && !state_inflight) with matching tags, entry B is inflight with matching tags. Verify `forward.forwardMask` and `forward.forwardData` reflect entry A's data, not entry B's.
- <CK-INFLIGHT-ONLY> Only inflight entries match, no active entries match. Verify forward data is selected from inflight entries.
- <CK-NO-MATCH> No entries match tags. Verify `forward.forwardMask(j) = false` for all bytes j.
- <CK-MASK-BIT-WRITTEN> Entry E has mask bit j set at the queried vwordOffset. Forward query matches. Verify `forward.forwardMask(j) = true` and `forward.forwardData(j)` matches the data byte at that position.
- <CK-MASK-BIT-UNWRITTEN> Entry E has mask bit j clear at the queried vwordOffset. Forward query matches. Verify `forward.forwardMask(j) = false` (no forward for unwritten bytes — TBD: depends on Mux1H behavior when no entry has that mask bit set).

### Flush and Drain Operations

<FG-FLUSH-DRAIN>

- **Overview**: Sbuffer supports two drain modes through its FSM: `x_drain_all` (draining both store queue and Sbuffer) and `x_drain_sbuffer` (draining Sbuffer only, blocking new enqueues). Drain can be initiated by external flush request (`io.flush.valid`), microarchitectural drain from forward tag mismatch, or microarchitectural drain from merge vtag mismatch. The flush handshake uses `SbufferFlushBundle` with valid/empty signals. Source: `Sbuffer.scala:41-46, 363-394, 360-361`.
- **Execution Flow**:
  1. **Flush Initiation**: When `io.flush.valid` is asserted, the FSM transitions to `x_drain_all` from any state. Source: `Sbuffer.scala:365-366, 380, 386-387`.
  2. **Microarchitectural Drain Initiation**: When `forward_need_uarch_drain` or `merge_need_uarch_drain` is set, `do_uarch_drain` asserts after pipeline delay (GatedValidRegNext). FSM transitions to `x_drain_sbuffer` from x_idle or x_replace. Source: `Sbuffer.scala:196, 367-368, 388-389`.
  3. **Drain Execution**: In drain states, `needDrain(state) = true` (state(1) set). Eviction candidate selection uses the lowest-index active entry (`drainIdx`). New enqueues are blocked in x_drain_sbuffer (`firstCanInsert` condition). Source: `Sbuffer.scala:441, 189`.
  4. **Drain Completion**: In x_drain_all, FSM returns to x_idle when `empty` (Sbuffer empty AND store queue empty AND no incoming valid requests). In x_drain_sbuffer, FSM returns to x_idle when `sbuffer_empty` (Sbuffer empty, regardless of store queue or incoming requests). Source: `Sbuffer.scala:374-376, 379-383`.
- **Boundaries and Exceptions**:
  - Flush valid has highest FSM transition priority: asserted in any state, including drain states (x_drain_sbuffer transitions to x_drain_all). Source: `Sbuffer.scala:365-366, 380, 386-387`.
  - During x_drain_all, `empty` requires both `sbuffer_empty` AND `!any io.in.valid ORR`. Source: `Sbuffer.scala:346-347`.
  - During x_drain_sbuffer, completion only requires `sbuffer_empty` — the store queue may still have pending requests. Source: `Sbuffer.scala:381-382`.
  - `io.flush.empty` is asserted when `empty && io.sqempty` (Sbuffer empty AND store queue empty). Source: `Sbuffer.scala:361`.
- **Performance and Constraints**: Drain completes when all active entries have been evicted (maximum StoreBufferSize evictions). Each eviction requires DCache acceptance (backpressure-dependent).

#### External Flush Handshake

<FC-EXTERNAL-FLUSH>

An external agent (e.g., commit stage) initiates a full pipeline flush by asserting `io.flush.valid`. Sbuffer transitions to x_drain_all, evicts all active entries to DCache, and signals completion via `io.flush.empty`.

**Check points:**
- <CK-FLUSH-INITIATE> FSM in x_idle. Assert `io.flush.valid`. Verify FSM transitions to x_drain_all on next cycle.
- <CK-FLUSH-DRAIN-ALL> Flush active with entries in Sbuffer and `io.in(0).valid = true`. Verify all entries are evicted (eviction candiate uses drainIdx), and `io.flush.empty` asserts only when both Sbuffer and store queue are empty.
- <CK-FLUSH-COMPLETE> All entries drained, `io.sqempty = true`, `sbuffer_empty = true`. Verify `io.flush.empty = true` and FSM returns to x_idle.
- <CK-FLUSH-INTERRUPT-REPLACE> FSM in x_replace. Assert `io.flush.valid`. Verify FSM transitions to x_drain_all.
- <CK-FLUSH-UPGRADE-DRAIN> FSM in x_drain_sbuffer. Assert `io.flush.valid`. Verify FSM transitions to x_drain_all.

#### Microarchitectural Drain

<FC-UARCH-DRAIN>

When a forward tag mismatch or merge vtag mismatch is detected, Sbuffer initiates a microarchitectural drain (`x_drain_sbuffer`). This drains only the Sbuffer (not the store queue), blocking new enqueues but allowing existing in-flight operations outside Sbuffer to proceed.

**Check points:**
- <CK-UARCH-DRAIN-FORWARD> Forward tag mismatch detected. Verify `forward_need_uarch_drain = true`, `do_uarch_drain` asserts after pipeline delay, and FSM transitions to x_drain_sbuffer.
- <CK-UARCH-DRAIN-MERGE> Merge with differing vtag detected. Verify `merge_need_uarch_drain = true`, `do_uarch_drain` asserts after two GatedValidRegNext delays, FSM transitions to x_drain_sbuffer.
- <CK-UARCH-DRAIN-BLOCK-ENQUEUE> FSM in x_drain_sbuffer. Verify `io.in(0).ready = false` (firstCanInsert is false due to `sbuffer_state =/= x_drain_sbuffer` check).
- <CK-UARCH-DRAIN-COMPLETE> Sbuffer empty, no flush valid. Verify FSM returns to x_idle and enqueues resume.

### State Tracking and Timeout Management

<FG-STATE-TRACKING>

- **Overview**: Sbuffer tracks per-entry state through the `stateVec` register file, coherence timeout through `cohCount`, replay timeout through `missqReplayCount`, and inflight dependency through `waitInflightMask`. The coherence counter increments every cycle for active entries, triggering eviction when its MSB (bit `EvictCountBits-1`) is set. Since `EvictCountBits = log2Up(EvictCycles+1) = 21` for `EvictCycles = 1<<20`, the MSB is bit 20 and asserts once the counter reaches `2^20 = EvictCycles`, i.e. after ~EvictCycles cycles. The replay counter increments when w_timeout is set, triggering eviction when its MSB is set (after ~SbufferReplayDelayCycles cycles). Source: `Sbuffer.scala:31-33, 94-105, 566-573`.
- **Execution Flow**:
  1. **Coherence Count**: For each entry i where `activeMask(i) && !cohTimeOutMask(i)`, `cohCount(i)` increments by 1 each cycle. When `cohCount(i)(EvictCountBits-1)` (MSB) is true and entry is active, `cohTimeOutMask(i)` asserts. Source: `Sbuffer.scala:570-572, 98`.
  2. **Replay Count**: When `stateVec(i).w_timeout && stateVec(i).state_inflight && !missqReplayCount(i)(MissqReplayCountBits-1)`, `missqReplayCount(i)` increments by 1 each cycle. When the MSB is set, `missqReplayTimeOutMask(i)` asserts. Source: `Sbuffer.scala:567-569, 101`.
  3. **Inflight Wait Mask**: When a new entry is allocated with `w_sameblock_inflight`, `waitInflightMask(entryIdx)` records the one-hot mask of the blocking inflight entry. When that inflight entry's DCache hit response fires, the waiting entry's `w_sameblock_inflight` clears (1 cycle delay). Source: `Sbuffer.scala:249-251, 538-547`.
- **Boundaries and Exceptions**:
  - Coherence count is reset to 0 on insert (allocation) or merge. Source: `Sbuffer.scala:252, 271`.
  - Replay count is reset to 0 when replay response fires. Source: `Sbuffer.scala:558`.
  - Replay timeout uses GatedValidRegNext to hold the timeout state across cycles when another eviction is already in flight (`missqReplayHasTimeOut = GatedValidRegNext(missqReplayHasTimeOutGen) && !GatedValidRegNext(sbuffer_out_s0_fire)`). Source: `Sbuffer.scala:103`.
  - Assertion ensures `PopCount(sameBlockInflightMask) <= 1`. Source: `Sbuffer.scala:404`.
- **Performance and Constraints**: 
  - Coherence timeout threshold ≈ EvictCycles (the MSB, bit `EvictCountBits-1` = bit 20, of the 21-bit counter is checked; it asserts at count 2^20 = EvictCycles). For EvictCycles = 1 << 20, timeout occurs after ~1,048,576 cycles.
  - Replay timeout threshold = SbufferReplayDelayCycles. For default 16, timeout occurs after 16 cycles.

#### Entry State Lifecycle

<FC-ENTRY-LIFECYCLE>

Each Sbuffer entry progresses through a defined lifecycle: invalid → valid (active) → inflight (during DCache write) → invalid (after DCache hit response). The 4-bit state vector encodes: state_valid (allocated), state_inflight (being written to DCache), w_timeout (waiting for replay resend), w_sameblock_inflight (blocked by same-block inflight entry).

**Check points:**
- <CK-LIFECYCLE-ALLOCATE> Reset. Enqueue store to address A into entry E. Verify: `stateVec(E).state_valid = true`, `stateVec(E).state_inflight = false`, `stateVec(E).w_timeout = false`, `stateVec(E).w_sameblock_inflight` depends on same-block inflight.
- <CK-LIFECYCLE-EVICT> Entry E is active. Eviction fires for E. Verify: `stateVec(E).state_inflight = true`, `stateVec(E).state_valid = true`.
- <CK-LIFECYCLE-COMPLETE> Entry E is inflight. DCache hit response fires for E. Verify: `stateVec(E).state_inflight = false`, `stateVec(E).state_valid = false`.
- <CK-LIFECYCLE-REPLAY> Entry E is inflight. DCache replay response fires. Verify: `stateVec(E).w_timeout = true`, `stateVec(E).state_inflight = true` (remains inflight).
- <CK-LIFECYCLE-REPLAY-RESEND> Entry E has w_timeout, replay timeout triggers, E is re-evicted. Hit response clears E. Verify E returns to invalid state.

#### Coherence Timeout

<FC-COHERENCE-TIMEOUT>

Each active entry's coherence counter increments every cycle. When the counter's MSB asserts, the entry is flagged for coherence-timeout eviction. This ensures entries do not sit in the Sbuffer indefinitely, maintaining memory consistency.

**Check points:**
- <CK-COH-COUNT-INCREMENT> Entry E is active with no coherence timeout. Verify `cohCount(E)` increments by 1 on every cycle.
- <CK-COH-TIMEOUT-TRIGGER> Entry E active, `cohCount(E)(EvictCountBits-1) = true`. Verify `cohTimeOutMask(E) = true` and `cohHasTimeOut = true`.
- <CK-COH-COUNT-STOP> Entry E reaches coherence timeout (MSB set). Verify `cohCount(E)` stops incrementing (gated by `!cohTimeOutMask(E)` condition).
- <CK-COH-RESET-ON-MERGE> Entry E is active with cohCount=C. Merge into E. Verify `cohCount(E) = 0` after merge.

#### Replay Timeout

<FC-REPLAY-TIMEOUT>

When DCache signals a replay for an entry, the entry's w_timeout flag is set and missqReplayCount resets to zero. The counter increments each cycle until the MSB asserts, at which point the entry is eligible for priority eviction (above drain and coherence timeout).

**Check points:**
- <CK-REPLAY-COUNT-START> DCache replay response fires for entry E. Verify `missqReplayCount(E) = 0` and increments on subsequent cycles.
- <CK-REPLAY-COUNT-INCREMENT> Entry E has w_timeout, state_inflight, and MSB not set. Verify `missqReplayCount(E)` increments by 1 each cycle.
- <CK-REPLAY-COUNT-STOP> Entry E reaches replay timeout (MSB set). Verify counter stops incrementing.
- <CK-REPLAY-TIMEOUT-EVICT> Entry E has replay timeout. Verify E is selected as eviction candidate (highest priority in `sbuffer_out_s0_evictionIdx`).

### Subcomponent Description

#### Component SbufferData
SbufferData provides byte-level data and per-byte mask storage for all StoreBufferSize entries, organized as [entry][CacheLineVWords][VDataBytes]. Sbuffer writes to SbufferData through `writeReq` ports (ValidIO, no backpressure) during enqueue stage s2 and clears masks through `maskFlushReq` ports on DCache write completion. Sbuffer reads `dataOut` and `maskOut` combinatorially for DCache eviction data/mask generation and load forwarding. Sbuffer expects writes to be visible two cycles after the write request (2-cycle registered write pipeline), unconditional acceptance of ValidIO transactions, and all data/mask values reset to zero/false after reset. For details, refer to the document `SbufferData_spec.md`. Source: `Sbuffer.scala:20-21, 29-30, 281-306, 507-508, 550-553, 618-625`.

#### Component StorePfWrapper
StorePfWrapper is an optional store prefetch unit that trains on store address patterns observed during enqueue and issues speculative prefetch requests to warm the DCache. Sbuffer connects it conditionally based on compile-time parameters (`EnableStorePrefetchSPB`, `EnableStorePrefetchAtCommit`). When enabled, Sbuffer drives training events (`sbuffer_enq`) on enqueue fire and merges prefetcher output with immediate enqueue-triggered prefetch requests onto `io.store_prefetch`. When disabled, all ports are tied to DontCare and the prefetcher must not assert any `io.store_prefetch` request. The behavior Sbuffer relies on: StorePfWrapper consumes `sbuffer_enq` training events without backpressuring enqueue, and produces prefetch requests on its output port that Sbuffer forwards to `io.store_prefetch` under the Decoupled protocol. Source: `Sbuffer.scala:22, 202-233`.

### State Machines and Timing
- **State Machine List**: The Sbuffer FSM has 4 architecturally visible states (encoded as Enum(4)):
  - **x_idle** (0): Normal operation — accepts enqueues, may trigger eviction to x_replace. Source: `Sbuffer.scala:364-371`.
  - **x_replace** (1): Evicting entries to DCache. Transitions back to x_idle when eviction condition clears, or to drain states on flush/uarch-drain. Source: `Sbuffer.scala:385-393`.
  - **x_drain_all** (2): Draining both store queue and Sbuffer (full pipeline flush). Completes when `empty` (both Sbuffer empty and no pending store queue entries). Source: `Sbuffer.scala:373-377`.
  - **x_drain_sbuffer** (3): Draining Sbuffer only (microarchitectural drain). Blocks new enqueues. Completes when `sbuffer_empty`. Source: `Sbuffer.scala:378-384`.

- **State Transition Conditions**:
  - x_idle → x_drain_all: `io.flush.valid` asserted. Source: `Sbuffer.scala:365-366`.
  - x_idle → x_drain_sbuffer: `do_uarch_drain` asserted (forward or merge mismatch). Source: `Sbuffer.scala:367-368`.
  - x_idle → x_replace: `do_eviction` asserted (ActiveCount >= threshold OR near-full). Source: `Sbuffer.scala:369-371`.
  - x_drain_all → x_idle: `empty` (Sbuffer empty AND store queue empty AND no incoming valid). Source: `Sbuffer.scala:374-376`.
  - x_drain_sbuffer → x_idle: `sbuffer_empty`. Source: `Sbuffer.scala:381-382`.
  - x_drain_sbuffer → x_drain_all: `io.flush.valid` asserted — flush overrides uarch drain. Source: `Sbuffer.scala:380`.
  - x_replace → x_idle: `!do_eviction`. Source: `Sbuffer.scala:391`.
  - x_replace → x_drain_all: `io.flush.valid` asserted. Source: `Sbuffer.scala:386-387`.
  - x_replace → x_drain_sbuffer: `do_uarch_drain` asserted. Source: `Sbuffer.scala:388-389`.

- **Key Timing**:
  - **Enqueue pipeline latency**: 3 cycles from `io.in(i).fire` to data visible in SbufferData (s0 → s1 → s2). Source: `Sbuffer.scala:110-122`.
  - **Eviction pipeline latency**: 2 cycles from candidate selection to DCache req fire (s0 → s1), plus variable DCache response latency. Source: `Sbuffer.scala:416-429`.
  - **Forward pipeline latency**: 1 cycle from `forward.valid` to output data/mask (via RegEnable on forward.valid). Source: `Sbuffer.scala:618-625`.
  - **Coherence timeout**: ~EvictCycles cycles after entry becomes active (MSB, bit EvictCountBits-1, of the EvictCountBits-bit counter asserts at count 2^(EvictCountBits-1) = EvictCycles). Default EvictCycles = 1<<20 → timeout ~1,048,576 cycles. Source: `HasSbufferConst.scala:2, 5`.
  - **Replay timeout**: SbufferReplayDelayCycles after replay response. Default = 16 cycles. Source: `HasSbufferConst.scala:3, 6`.
  - **Same-block inflight clearance**: 1 cycle delay from hit response fire to w_sameblock_inflight clearance on waiting entries (uses `GatedValidRegNext(resp.fire)`). Source: `Sbuffer.scala:538-547`.
  - **Uarch drain delay**: `do_uarch_drain` asserts 1 cycle after forward mismatch (GatedValidRegNext), 2 cycles after merge mismatch (double GatedValidRegNext). Source: `Sbuffer.scala:196`.

### Configuration Registers and Storage
| Register Name/Address | Access Attribute | Bit Field | Default | Description | Read/Write Side Effects |
| ------------- | -------- | ---- | ------ | ---- | ---------- |
| sbuffer_state | internal | 2 bits | x_idle (0) | FSM state register. Encoded: 0=x_idle, 1=x_replace, 2=x_drain_all, 3=x_drain_sbuffer. | Written on state transitions per FSM rules. Reset to x_idle. |
| ptag | internal (Vec Reg) | Vec(StoreBufferSize, PTagWidth bits) | 0 | Physical address tags per entry. Written on insert. | Updated on insert only (not on merge). Holds previous value until next insert to same entry. |
| vtag | internal (Vec Reg) | Vec(StoreBufferSize, VTagWidth bits) | 0 | Virtual address tags per entry. Written on insert. | Updated on insert only (not on merge). |
| stateVec | internal (Vec RegInit) | Vec(StoreBufferSize, 4 bits) | all invalid | Per-entry state vector containing state_valid, state_inflight, w_timeout, w_sameblock_inflight. | Insert: state_valid=1. Eviction s0: state_inflight=1, w_timeout=0. Hit resp: state_inflight=0, state_valid=0. Replay resp: w_timeout=1. |
| cohCount | internal (Vec RegInit) | Vec(StoreBufferSize, EvictCountBits bits) | 0 | Coherence timeout counter per entry. Increments when entry is active and not timed out. | Reset to 0 on insert/merge. Stops incrementing at MSB set. |
| missqReplayCount | internal (Vec RegInit) | Vec(StoreBufferSize, MissqReplayCountBits bits) | 0 | Replay timeout counter per entry. Increments when w_timeout is set. | Reset to 0 on replay response. Stops incrementing at MSB set. |
| waitInflightMask | internal (Vec Reg) | Vec(StoreBufferSize, StoreBufferSize bits) | 0 | One-hot mask recording which inflight entry blocks this entry. | Written on insert when w_sameblock_inflight is set. Read on hit response to clear w_sameblock_inflight. |
| enbufferSelReg | internal (Reg) | 1 bit | false | Toggle register alternating enqueue position parity. | Toggles on `io.in(0).valid`. Reset to false. |
| plru | internal (ValidPseudoLRU) | StoreBufferSize-way PLRU | N/A | Pseudo-LRU replacement state tracking access recency. | Access recorded on enqueue merge/insert and eviction. |
| debug_mask | internal (Vec Reg) | Vec(StoreBufferSize, CacheLineWords, DataBytes, Bool) | N/A | Debug-only mask array (not used for functional behavior). | N/A |

- **Register Map Base Address**: No direct bus interface. Configuration is through constructor parameters and CSR control interface (`io.csrCtrl`).
- **Configuration Flow**: All state registers reset to zero/invalid state. The `sbuffer_state` FSM starts in x_idle. Runtime configuration via `io.csrCtrl.sbuffer_threshold` sets the eviction trigger occupancy threshold. The threshold is registered via `Constantin.createRecord`. Source: `Sbuffer.scala:348-349`.

### Reset and Error Handling
- **Reset Behavior**: After active-high synchronous reset assertion:
  - `sbuffer_state = x_idle` (0). Source: `Sbuffer.scala:46`.
  - All `stateVec` entries are invalid (state_valid=false, state_inflight=false, w_timeout=false, w_sameblock_inflight=false). Source: `Sbuffer.scala:31`.
  - All `cohCount` entries are 0. Source: `Sbuffer.scala:32`.
  - All `missqReplayCount` entries are 0. Source: `Sbuffer.scala:33`.
  - All `waitInflightMask` entries are 0. Source: `Sbuffer.scala:28`.
  - `enbufferSelReg = false`. Source: `Sbuffer.scala:174`.
  - `sbuffer_out_s1_valid = false`. Source: `Sbuffer.scala:470`.
  - `io.dcache.req.valid = false`.
  - `io.sbempty = true` (after GatedValidRegNext of empty condition, Sbuffer is empty at reset).
  - `io.flush.empty = true` (after GatedValidRegNext, empty && sqempty).
  - SbufferData resets to all data bytes 0 and all mask bits false.
  - All PLRU state resets to initial (determined by ValidPseudoLRU implementation).
  - All forward outputs (`forwardMask`, `forwardData`, `forwardMaskFast`, `matchInvalid`, `dataInvalid`) reset to appropriate initial values.
- **Error Reporting**: 
  - Sbuffer contains multiple assertions for invariant checking during simulation:
    - `PopCount(sameBlockInflightMask) <= 1` — at most one inflight entry per cache block. Source: `Sbuffer.scala:404`.
    - `!(candidateVec.asUInt.orR && replaceAlgoNotDcacheCandidate)` — PLRU selects valid candidate. Source: `Sbuffer.scala:89`.
    - `!((PopCount(mergeMask(i).asUInt) > 1.U) && io.in(i).fire && io.in(i).bits.vecValid)` — at most one active entry with same ptag. Source: `Sbuffer.scala:145`.
    - `!((PopCount(insertVec) > 1.U) && in.fire && in.bits.vecValid)` — insert vector is one-hot. Source: `Sbuffer.scala:289`.
    - `!(stateVec(idx).isDcacheReqCandidate() && !noSameBlockInflight(idx))` — eviction candidate has no same-block inflight. Source: `Sbuffer.scala:451-454`.
    - `UIntToOH(insertIdx) === insertVec` — insert index consistency. Source: `Sbuffer.scala:243`.
    - `UIntToOH(mergeIdx) === mergeVec` — merge index consistency. Source: `Sbuffer.scala:268`.
    - Hit response: `!resp.bits.replay` and `!resp.bits.miss`. Source: `Sbuffer.scala:528-529`.
    - Hit response: `stateVec(id).state_inflight === true`. Source: `Sbuffer.scala:530`.
    - Replay response: `resp.bits.replay` is true. Source: `Sbuffer.scala:561`.
    - Replay response: `stateVec(id).state_inflight === true`. Source: `Sbuffer.scala:562`.
    - `require(EnsbufferWidth <= StorePipelineWidth)`. Source: `Sbuffer.scala:341`.
    - `require((StoreBufferThreshold + 1) <= StoreBufferSize)`. Source: `Sbuffer.scala:356`.
    - `require(id.getWidth >= log2Up(StoreBufferSize))` in `id_to_sbuffer_id`. Source: `Sbuffer.scala:518`.
- **Self-Recovery Strategy**: 
  - **Replay recovery**: When DCache signals replay, Sbuffer sets w_timeout, waits for replay delay timeout, then re-evicts the entry with highest priority. No limit on number of replay attempts (counter saturates at MSB, but entry remains eligible for retry).
  - **Microarchitectural drain**: On tag mismatch detection, Sbuffer drains itself to x_idle by evicting all active entries, then resumes normal operation. This is the primary recovery mechanism for consistency issues.
  - **Flush recovery**: External flush forces drain of all entries (x_drain_all), providing a complete reset of buffered state without asserting hardware reset.
  - No timeout for eviction completion — eviction waits indefinitely for DCache acceptance (backpressure).

### Parameterization and Configurable Features
- **Module Parameters**:

  | Parameter Name | Type/Range | Default | Functional Effect |
  | ------ | ------------- | ------ | -------- |
  | StoreBufferSize | Int | Config-dependent | Total number of store buffer entries. Affects: ptag/vtag array size, stateVec width, cohCount/missqReplayCount array size, SbufferData storage depth, wvec width, waitInflightMask width, replacment policy ways. SbufferIndexWidth = log2Up(StoreBufferSize). |
  | EnsbufferWidth | Int | 2 | Number of concurrent enqueue ports. Affects: io.in Vec width, writeReq Vec width, mergeMask width, insert position logic. Must satisfy `EnsbufferWidth <= StorePipelineWidth`. Source: `Sbuffer.scala:7, 341`. |
  | StorePipelineWidth | Int | Config-dependent | Number of store pipeline ports. Affects: io.store_prefetch Vec width. Must be >= EnsbufferWidth. Source: `Sbuffer.scala:14, 341`. |
  | LoadPipelineWidth | Int | 2 | Number of load forward query ports. Affects: io.forward Vec width, forward mismatch computation width. Source: `Sbuffer.scala:9`. |
  | NumDcacheWriteResp | Int | 1 | Number of DCache write response sources. Affects: io.dcache.hit_resps Vec width, maskFlushReq Vec width. Hardcoded to 1. Source: `HasSbufferConst.scala:11`. |
  | EvictCycles | Int | 1 << 20 (1,048,576) | Coherence timeout threshold in cycles. Affects: EvictCountBits = log2Up(EvictCycles+1), cohCount bit width, coherence timeout trigger point (MSB of EvictCountBits-bit counter). |
  | SbufferReplayDelayCycles | Int | 16 | Replay delay cycles after DCache replay response. Affects: MissqReplayCountBits = log2Up(SbufferReplayDelayCycles)+1, missqReplayCount bit width, replay timeout trigger point. |
  | EnableStorePrefetchSPB | Boolean | Config-dependent | When true, Sbuffer drives training events to StorePfWrapper on enqueue fire. When false, training ports tied to false/DontCare. Source: `Sbuffer.scala:204-211`. |
  | EnableStorePrefetchAtCommit | Boolean | Config-dependent | When true, Sbuffer merges prefetcher output with immediate enqueue-triggered prefetch requests onto io.store_prefetch. When false, routing depends on EnableStorePrefetchSPB. Source: `Sbuffer.scala:214-229`. |
  | EnableAtCommitMissTrigger | Boolean | Config-dependent | When true, only prefetch-triggered enqueue requests generate io.store_prefetch valid. When false, all enqueue fires generate io.store_prefetch valid. Source: `Sbuffer.scala:215-219`. |
  | EnableDifftest | Boolean | Config-dependent | When true, differential testing infrastructure (DiffSbufferEvent, DiffStoreEvent) is instantiated for comparison with reference model (NEMU). Source: `Sbuffer.scala:575-587, 697-866`. |
  | StoreBufferThreshold | Int | 7 | Occupancy threshold (number of active entries) to trigger eviction. Registered via Constantin.createRecord. `require((StoreBufferThreshold + 1) <= StoreBufferSize)`. Source: `Sbuffer.scala:349, 356`. |
  | StoreBufferBase | Int | 4 | Base offset subtracted from threshold when `io.force_write` is asserted. `forceThreshold = Mux(io.force_write, threshold - base, threshold)`. Source: `Sbuffer.scala:351, 354`. |
  | CacheLineSize | Int (from XSParameter) | Config-dependent | Cache line size in bits. Determines CacheLineBytes, CacheLineWords, OffsetWidth. |
  | VLEN | Int (from XSParameter) | Config-dependent | Vector register length in bits. Determines VDataBytes = VLEN/8, VWordWidth. |
  | PAddrBits | Int (from XSParameter) | Config-dependent | Physical address bit width. Determines PTagWidth = PAddrBits - OffsetWidth. |
  | VAddrBits | Int (from XSParameter) | Config-dependent | Virtual address bit width. Determines VTagWidth = VAddrBits - OffsetWidth. |

- **Runtime Configuration**: 
  - `io.csrCtrl.sbuffer_threshold` — dynamically adjusts eviction threshold (registered via Constantin.createRecord).
  - `io.force_write` — lowers effective threshold by StoreBufferBase when asserted.
  - `io.flush.valid` — triggers immediate drain-all operation.
- **Compile Macros/Generation Options**: 
  - `env.EnableDifftest` gates differential testing infrastructure instantiation.
  - Store prefetch connectivity is gated by compile-time boolean parameters, with Chisel `if`/`else` conditional generation (not runtime mux).

## Verification Requirements and Coverage Suggestions
- **Functional Coverage Points**: All `CK-*` check points defined in each functional group constitute coverage targets. Key cross-coverage scenarios:
  - Concurrent enqueue on both ports while eviction is active.
  - Concurrent enqueue and forward query to the same entry.
  - Enqueue → merge → forward → evict → hit response full lifecycle.
  - Rapid enqueue/dequeue cycling through all StoreBufferSize entries.
  - Alternating parity insert pattern: fill even entries, then odd entries, verify fairness.
  - Dual-port same-tag enqueue: verify single entry handles both writes.
  - Replay → timeout → re-evict → hit response full cycle.
  - Microarchitectural drain from forward mismatch during active enqueue.
  - Microarchitectural drain from merge vtag mismatch.
  - External flush during x_replace state (eviction in progress).
  - External flush during x_drain_sbuffer state (uarch drain in progress).
  - Coherence timeout for multiple simultaneous timeouts.
  - Buffer full condition: verify no enqueue accepted, eviction triggers.
  - PLRU correctness: verify access order tracking and eviction of LRU entry.
  - Same-block inflight: allocate two entries with same ptag, verify second entry blocked until first completes.
  - Byte-level mask verification: insert with partial mask, verify forward returns only masked bytes.
  - wline write: insert with wline=true, verify all cache-line virtual word positions updated.
  - vecValid=false enqueue: verify no side effects beyond handshake consumption.
  - Store prefetch disabled: verify no spurious prefetch requests on io.store_prefetch.

- **Constraints and Assumptions**: 
  - Input timing: LSU must obey Decoupled protocol on `io.in`. Valid and bits must be held stable until ready is asserted.
  - DCache protocol: `io.dcache.req.ready` must not depend on `io.dcache.req.valid` in the same cycle (combinational loop prevention).
  - wvec one-hot guarantee: Sbuffer internally enforces wvec is always one-hot. Testbench must not inject non-one-hot wvec into SbufferData directly (only via Sbuffer's enqueue path).
  - Single clock domain: All logic operates on the same clock edge.
  - Synchronous reset: Reset is active-high synchronous. Testbench must hold reset for at least one cycle and release before driving transactions.
  - Store buffer size constraint: `(StoreBufferThreshold + 1) <= StoreBufferSize` — threshold must leave room for at least one entry below capacity.
  - EnsbufferWidth constraint: `EnsbufferWidth <= StorePipelineWidth` — enqueue width limited by store pipeline width.

- **Test Interfaces**: 
  - **Store Enqueue Driver**: Drive `io.in(i)` with randomized store requests (varying addr, data, mask, vecValid, wline, prefetch flags). Respect `io.in(i).ready` backpressure. Track expected Sbuffer state (entry allocation, merge, data content).
  - **DCache Emulator / Responder**: Drive `io.dcache.req.ready` to control writeback throughput. Drive `io.dcache.hit_resps`, `io.dcache.replay_resp` to simulate DCache write completion and replay scenarios. Verify eviction data/mask correctness.
  - **Load Forward Driver**: Drive `io.forward(i).valid`, `io.forward(i).vaddr`, `io.forward(i).paddr` with queries targeting entries at various lifecycle stages. Verify `forwardMask`, `forwardData`, and `matchInvalid` correctness.
  - **Flush Driver**: Assert `io.flush.valid` and wait for `io.flush.empty`. Verify entry state changes, FSM transitions, and buffer emptiness.
  - **Internal State Monitor**: Read `sbuffer_state`, `stateVec`, `activeMask`, `validMask`, `inflightMask`, `cohCount`, `missqReplayCount`, `ptag`, `vtag`, `data`, `mask`, and assertion signals. Cross-check against expected state from reference model.
  - **Reference Model**: Maintain a software model of Sbuffer state: entry-level ptag/vtag, per-byte data and mask, entry state (invalid/active/inflight/replay_wait), PLRU access order, coherence/replay counters. Update on every enqueue fire, eviction stage, and DCache response. Compare against DUT state at checkpoints.
  - **Assertion Monitor**: Monitor all Sbuffer internal assertions (`assert(...)`) for violations during randomized testing.
