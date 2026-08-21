# SbufferEntryState Specification Document

> This document describes the specification of the `SbufferEntryState` chip verification target. Keep the technical language precise, well-organized, and easy to reuse for verification. If an item does not exist, explicitly write "None" or "TBD"; do not delete the section.

## Introduction
- **Design Background**: SbufferEntryState is a Chisel Bundle type that defines the per-entry state vector for the Sbuffer (Store Buffer) module in the XiangShan high-performance RISC-V processor. It encodes four orthogonal Boolean flags that track the lifecycle of each store buffer entry: allocation status, DCache write-in-flight status, replay-wait status, and same-cache-block inflight dependency. The Sbuffer module instantiates `stateVec` as a `RegInit(Vec(StoreBufferSize, new SbufferEntryState))` register file, using these fields to control enqueue, eviction, forwarding, and timeout logic. By extracting the Bundle from Sbuffer, this type is testable in isolation as a combinatorial logic unit. Source: `SbufferEntryState.scala:1-12`, `Sbuffer.scala:31`, `phase_01_types.txt:43-49`, `engine_overview.txt:7-18`.
- **Design Goals**: (1) Define four independent Boolean state flags per Sbuffer entry: `state_valid` (allocated), `state_inflight` (being written to DCache), `w_timeout` (waiting for replay resend), `w_sameblock_inflight` (blocked by same-block inflight entry). (2) Provide five combinatorial helper methods (`isInvalid`, `isValid`, `isActive`, `isInflight`, `isDcacheReqCandidate`) that derive entry classification from the field values. (3) Serve as the element type for the `stateVec` register file that the Sbuffer FSM, enqueue pipeline, eviction pipeline, and forward pipeline all reference. (4) Guarantee that the helper methods produce correct classifications for every possible combination of the four Boolean fields — the methods are pure combinational functions of their inputs with no hidden state.

## Terms and Abbreviations in Chisel Code

| Abbreviation | Full Term | Description |
| ---- | ---- | ---- |
| state_valid | State Valid | Boolean flag: entry is allocated (has been inserted) and holds valid store data. Set on insert (`Sbuffer.scala:246`). Cleared when state_inflight is cleared on DCache hit response. |
| state_inflight | State Inflight | Boolean flag: Sbuffer is actively writing this entry's data to DCache. Set on eviction stage s0 (`Sbuffer.scala:490`). Cleared on DCache hit response (`Sbuffer.scala:524-526`). |
| w_timeout | Wait Timeout | Boolean flag: entry received a replay response from DCache and is waiting for the replay delay counter to expire before re-eviction. Set on DCache replay response (`Sbuffer.scala:556-558`). Cleared on re-eviction. |
| w_sameblock_inflight | Wait Same-Block Inflight | Boolean flag: another entry sharing the same physical tag is currently inflight to DCache. Set on insert when `haveSameBlockInflight` is true (`Sbuffer.scala:249-251`). Cleared 1 cycle after the blocking entry's DCache hit response (`Sbuffer.scala:538-547`). |
| isInvalid | Is Invalid | Combinational method: returns `!state_valid`. True when the entry is free and can be allocated. |
| isValid | Is Valid | Combinational method: returns `state_valid`. True when the entry has been allocated (whether active, inflight, or waiting). |
| isActive | Is Active | Combinational method: returns `state_valid && !state_inflight`. True when the entry holds data but is not currently being written to DCache. Active entries are eligible for forwarding with priority. |
| isInflight | Is Inflight | Combinational method: returns `state_inflight`. True when the entry is being written to DCache. Inflight entries are eligible for forwarding at lower priority than active entries. |
| isDcacheReqCandidate | DCache Request Candidate | Combinational method: returns `state_valid && !state_inflight && !w_sameblock_inflight`. True when the entry can be selected as an eviction candidate for DCache writeback. |
| FSM | Finite State Machine | Sbuffer's 4-state controller that uses stateVec entry classifications to drive behavior. |
| PLRU | Pseudo Least Recently Used | Replacement policy that selects eviction candidates from entries where isDcacheReqCandidate is true. |
| stateVec | State Vector Register File | The Sbuffer's `Reg(Vec(StoreBufferSize, new SbufferEntryState))` holding one SbufferEntryState per buffer entry. |

## Chisel Source Files

A single file defines the SbufferEntryState Bundle type and its helper methods.

File list:
- `SbufferEntryState.scala:1-12`: Bundle class definition — four Boolean fields (`state_valid`, `state_inflight`, `w_timeout`, `w_sameblock_inflight`) and five helper methods (`isInvalid`, `isValid`, `isActive`, `isInflight`, `isDcacheReqCandidate`). Extends `SbufferBundle` (which extends `XSBundle` with `HasSbufferConst`), so it inherits parameter-derived constants for bit-width context, though it uses no parameterized widths itself — all fields are single-bit `Bool()`.

## Top-Level Interface Overview
- **Module Name**: `SbufferEntryState`
- **Field List**:

  | Field Name | Type | Reset Value | Description |
  | ------ | ---- | ------ | ---- |
  | state_valid | Bool() | false | Entry is allocated and holds valid store data. Source: `SbufferEntryState.scala:2`. |
  | state_inflight | Bool() | false | Sbuffer is actively writing this entry to DCache. Source: `SbufferEntryState.scala:3`. |
  | w_timeout | Bool() | false | Entry received replay response from DCache, waiting for replay delay timeout before re-eviction. Source: `SbufferEntryState.scala:4`. |
  | w_sameblock_inflight | Bool() | false | Another entry with the same physical tag is inflight to DCache, blocking this entry's eviction. Source: `SbufferEntryState.scala:5`. |

- **Method List**:

  | Method Name | Return Type | Parameters | Combinational Expression | Description |
  | ------ | ---- | ---- | ---- | ---- |
  | isInvalid | Bool() | None | `!state_valid` | Returns true when the entry is free and available for allocation. Source: `SbufferEntryState.scala:7`. |
  | isValid | Bool() | None | `state_valid` | Returns true when the entry has been allocated. Source: `SbufferEntryState.scala:8`. |
  | isActive | Bool() | None | `state_valid && !state_inflight` | Returns true when the entry holds valid data and is not currently being written to DCache. Active entries are eligible for forwarding with priority. Source: `SbufferEntryState.scala:9`. |
  | isInflight | Bool() | None | `state_inflight` | Returns true when the entry is being written to DCache. Source: `SbufferEntryState.scala:10`. |
  | isDcacheReqCandidate | Bool() | None | `state_valid && !state_inflight && !w_sameblock_inflight` | Returns true when the entry can be selected for eviction to DCache. Excludes entries blocked by same-block inflight. Source: `SbufferEntryState.scala:11`. |

- **Clock and Reset Requirements**: SbufferEntryState is a passive wire Bundle with no sequential elements (no registers, no flip-flops). It imposes no clock or reset requirements on its own. Clock and reset behavior is the responsibility of the instantiating register — in Sbuffer, `stateVec` is a `RegInit` that resets all fields to `false`. Source: `Sbuffer.scala:31`.
- **External Dependencies**: SbufferEntryState extends `SbufferBundle`, which extends `XSBundle` with `HasSbufferConst`. The `HasSbufferConst` trait provides parameter-derived constants (EvictCycles, SbufferIndexWidth, PTagWidth, VTagWidth, etc.) but none of these constants affect the four Boolean fields or the five helper method expressions. The Bundle has no dependency on any other module or hardware unit.

## Functional Description

### API — Test and Verification Interface

<FG-API>

- **Overview**: This functional group describes how a testbench drives the four Boolean fields of SbufferEntryState and observes the five helper method outputs. Since SbufferEntryState is a combinational Bundle, verification consists of exhaustive or directed coverage of the 16 possible field-value combinations (2^4 = 16) and verification that every method produces the correct Boolean output for every combination. The testbench directly writes all four fields through the Chisel Bundle assignment and reads the method return values combinatorially.
- **Execution Flow**: The testbench assigns values to `state_valid`, `state_inflight`, `w_timeout`, and `w_sameblock_inflight` on each cycle (or holds them stable). The testbench samples each of the five method return values: `isInvalid()`, `isValid()`, `isActive()`, `isInflight()`, `isDcacheReqCandidate()`. Since methods are combinational, the outputs update in the same cycle as the field assignments. The testbench compares observed method outputs against expected Boolean values computed from the field assignment expressions.
- **Boundaries and Exceptions**:
  - All 16 field-value combinations are legal inputs. The Bundle imposes no cross-field constraints — any combination of the four flags is a valid state. However, in the context of Sbuffer's usage, certain combinations are unreachable under correct operation (e.g., `state_inflight=true` with `state_valid=false` would indicate a bug in Sbuffer's state management). The testbench for the Bundle itself must still verify method correctness for all combinations, including illegal-in-context combinations.
  - The methods are pure combinational functions with no internal state. There is no pipelining, no registered output, and no cycle-to-cycle dependency beyond the field values themselves.
  - The Bundle fields are `Bool()` with no `Decoupled` or `ValidIO` protocol — they are raw wires. Direction (Input/Output) is determined by how the instantiating register file (stateVec) is used in Sbuffer.
- **Performance and Constraints**: All five methods are single-level Boolean expressions with no arithmetic, no loops, and no complex logic depth. Propagation delay is one logic level (NOT gate for `isInvalid`, AND gate for `isActive` and `isDcacheReqCandidate`, wire for `isValid` and `isInflight`).

#### Driving All Four Fields for Exhaustive Coverage

<FC-DRIVE-FIELDS>

The testbench drives all four Boolean fields of SbufferEntryState across all 16 possible combinations. For each combination, the testbench observes the five method outputs and verifies they match the expected Boolean expressions.

**Check points:**
- <CK-ALL-ZERO> All fields false (`state_valid=false, state_inflight=false, w_timeout=false, w_sameblock_inflight=false`). Verify: `isInvalid=true`, `isValid=false`, `isActive=false`, `isInflight=false`, `isDcacheReqCandidate=false`.
- <CK-VALID-ONLY> `state_valid=true`, all others false. Verify: `isInvalid=false`, `isValid=true`, `isActive=true`, `isInflight=false`, `isDcacheReqCandidate=true`.
- <CK-INFLIGHT-ONLY> `state_inflight=true`, all others false. Verify: `isInvalid=true`, `isValid=false`, `isActive=false`, `isInflight=true`, `isDcacheReqCandidate=false`.
- <CK-VALID-AND-INFLIGHT> `state_valid=true, state_inflight=true`, `w_timeout=false, w_sameblock_inflight=false`. Verify: `isInvalid=false`, `isValid=true`, `isActive=false`, `isInflight=true`, `isDcacheReqCandidate=false`.
- <CK-VALID-AND-SAME-BLOCK> `state_valid=true, w_sameblock_inflight=true`, `state_inflight=false, w_timeout=false`. Verify: `isInvalid=false`, `isValid=true`, `isActive=true`, `isInflight=false`, `isDcacheReqCandidate=false`.
- <CK-ALL-TRUE> All fields true. Verify: `isInvalid=false`, `isValid=true`, `isActive=false` (state_inflight is true), `isInflight=true`, `isDcacheReqCandidate=false` (state_inflight is true).

#### Observing Combinational Method Latency

<FC-METHOD-LATENCY>

All five methods are combinational — their outputs reflect the current field values in the same simulation cycle without any pipeline delay.

**Check points:**
- <CK-COMB-IMMEDIATE> Assert `state_valid=true` in cycle N with all other fields false. Verify `isActive()` returns true in the same cycle N (not N+1).
- <CK-COMB-TRANSITION> Change `state_inflight` from false to true in cycle N with `state_valid=true`. Verify `isActive()` transitions from true to false in the same cycle N and `isInflight()` transitions from false to true in the same cycle N.
- <CK-COMB-STABLE> Hold all fields constant across 10 cycles. Verify all method outputs remain stable across all 10 cycles.

### Field Semantics and Lifecycle Encoding

<FG-FIELD-SEMANTICS>

- **Overview**: The four Boolean fields encode the lifecycle stage of a store buffer entry: unallocated → allocated (active) → inflight (DCache write in progress) → completed (cleared). Two auxiliary flags (`w_timeout`, `w_sameblock_inflight`) indicate temporary blocking conditions that modify eviction eligibility without changing allocation status. All four fields are independently readable and writable; there are no write-side-effect rules enforced by the Bundle itself — the instantiating module (Sbuffer) is responsible for maintaining field consistency. Source: `SbufferEntryState.scala:2-5`, `phase_01_types.txt:43-49`.
- **Execution Flow**:
  1. **Reset / Unallocated**: All four fields are false. Entry is free.
  2. **Allocation** (Insert): `state_valid` set to true. `state_inflight` remains false. `w_timeout` remains false. `w_sameblock_inflight` may be set to true if another entry with the same physical tag is already inflight to DCache.
  3. **Active** (Ready for eviction): `state_valid=true, state_inflight=false, w_sameblock_inflight=false`. Entry holds data and is a candidate for PLRU eviction. Active entries have highest priority for store-to-load forwarding.
  4. **Eviction Started** (Inflight): `state_inflight` set to true. `state_valid` remains true. Entry is being written to DCache. Inflight entries are eligible for forwarding at lower priority than active entries.
  5. **Eviction Replay**: DCache signals replay. `w_timeout` set to true. `state_inflight` remains true. Entry waits for replay delay timeout before re-eviction.
  6. **Eviction Completed**: DCache signals hit. `state_inflight` cleared to false. `state_valid` cleared to false. Both `w_timeout` and `w_sameblock_inflight` are cleared (by Sbuffer, not by the Bundle itself). Entry returns to unallocated.
  Source: `Sbuffer.scala:238-258, 482-530, 556-563`.
- **Boundaries and Exceptions**:
  - The Bundle itself enforces no field invariants. Any combination of the four fields is syntactically valid. Architectural invariants (e.g., `state_inflight` should not be true when `state_valid` is false) are enforced by the instantiating Sbuffer module through its state transition logic and assertions.
  - Field assignments are edge-agnostic — the Bundle does not detect or require specific transition sequences. All fields can change independently on any clock edge.
  - There is no self-clearing behavior. When `state_inflight` is cleared on DCache hit response, `state_valid` and `w_sameblock_inflight` must be cleared by separate logic in Sbuffer — the Bundle does not cascade field changes.
- **Performance and Constraints**: Each field is a single Boolean wire with zero propagation delay through the Bundle. The instantiating register file (`Reg(Vec(StoreBufferSize, new SbufferEntryState))`) imposes 1 cycle of write-to-read latency.

#### State Valid Field — Allocation Flag

<FC-STATE-VALID>

The `state_valid` field indicates whether the entry has been allocated and holds valid store data. When false, the entry is free and available for allocation. When true, the entry occupies a buffer slot and its data and metadata are valid.

**Check points:**
- <CK-VALID-FALSE-ENTRY-FREE> `state_valid=false`. Verify `isInvalid()` returns true, indicating the entry is free. The entry is eligible for allocation by Sbuffer's insert logic.
- <CK-VALID-TRUE-ENTRY-OCCUPIED> `state_valid=true`. Verify `isValid()` returns true, indicating the entry occupies a buffer slot. The entry is not eligible for new allocation (Sbuffer's insert logic selects only entries where `isInvalid` is true).
- <CK-VALID-INDEPENDENT> `state_valid` can be true or false regardless of the other three field values. Verify setting/clearing `state_valid` does not affect the other field values (no cross-field coupling within the Bundle).

#### State Inflight Field — DCache Write In Progress

<FC-STATE-INFLIGHT>

The `state_inflight` field indicates whether Sbuffer is actively writing this entry's data to DCache. When true, the entry is in the eviction pipeline and cannot be selected as a new eviction candidate. Inflight entries are eligible for load forwarding at a lower priority than active entries. Source: `SbufferEntryState.scala:3, 10`.

**Check points:**
- <CK-INFLIGHT-TRUE-BLOCKS-CANDIDATE> `state_inflight=true`. Verify `isDcacheReqCandidate()` returns false regardless of the other field values (the method expression requires `!state_inflight`).
- <CK-INFLIGHT-TRUE-IS-INFLIGHT> `state_inflight=true`. Verify `isInflight()` returns true.
- <CK-INFLIGHT-FALSE-IS-ACTIVE-CONDITION> `state_inflight=false, state_valid=true`. Verify `isActive()` returns true. The entry is active and eligible for forwarding with priority.

#### Wait Timeout Field — Replay Delay Flag

<FC-W-TIMEOUT>

The `w_timeout` field indicates the entry received a replay response from DCache and is waiting for the replay delay counter (`missqReplayCount`) to expire before re-eviction. This flag is set by Sbuffer on DCache replay response and is used to gate the replay counter increment and to prioritize re-eviction. Source: `SbufferEntryState.scala:4`, `phase_01_types.txt:47`.

**Check points:**
- <CK-W-TIMEOUT-TRUE-CANDIDATE> `w_timeout=true, state_valid=true, state_inflight=true, w_sameblock_inflight=false`. Verify `isDcacheReqCandidate()` returns false (blocked by `state_inflight=true`). The `w_timeout` field itself does not affect `isDcacheReqCandidate` — it is the `state_inflight` that blocks candidate status.
- <CK-W-TIMEOUT-INDEPENDENT> `w_timeout` can be true or false independent of the other fields. Verify no method's output depends on `w_timeout` — all five helper methods are functions of only `state_valid`, `state_inflight`, and `w_sameblock_inflight`. The `w_timeout` field is consumed directly by Sbuffer's replay logic (`Sbuffer.scala:567-569`), not through the Bundle's own methods.

#### Wait Same-Block Inflight Field — Eviction Blocking Flag

<FC-W-SAME-BLOCK-INFLIGHT>

The `w_sameblock_inflight` field indicates another entry sharing the same physical tag is currently inflight to DCache, blocking this entry from being evicted. This enforces the single-writer-per-cache-line invariant. The flag is set on insert when a same-block inflight entry exists, and cleared when the blocking entry's DCache hit response fires. Source: `SbufferEntryState.scala:5`, `phase_01_types.txt:48`, `engine_overview.txt:67`.

**Check points:**
- <CK-SAME-BLOCK-TRUE-BLOCKS-CANDIDATE> `w_sameblock_inflight=true, state_valid=true, state_inflight=false`. Verify `isDcacheReqCandidate()` returns false. The entry is not selectable for eviction even though it is active.
- <CK-SAME-BLOCK-FALSE-CANDIDATE> `w_sameblock_inflight=false, state_valid=true, state_inflight=false`. Verify `isDcacheReqCandidate()` returns true. The entry is a valid eviction candidate.
- <CK-SAME-BLOCK-DOES-NOT-AFFECT-ACTIVE> `w_sameblock_inflight=true, state_valid=true, state_inflight=false`. Verify `isActive()` returns true (same-block inflight does not affect active classification). The entry can still participate in forwarding.

### Derived State Classification Methods

<FG-DERIVED-CLASSIFICATION>

- **Overview**: The five helper methods provide combinational classification of the entry's lifecycle stage based on the four Boolean fields. These methods are pure functions with no side effects, no internal state, and no parameters. They are used by the Sbuffer module's FSM, enqueue pipeline (to find invalid entries for insertion), eviction pipeline (to build the candidate vector for PLRU), forward pipeline (to prioritize active over inflight entries), and replay/coherence timeout logic. Source: `SbufferEntryState.scala:7-11`.
- **Execution Flow**: Each method evaluates its Boolean expression using only the values of `state_valid`, `state_inflight`, and `w_sameblock_inflight` at the moment of invocation. The results are available combinatorially in the same cycle as the field values. No method modifies any field. No method depends on any external state.
- **Boundaries and Exceptions**:
  - All five methods are total functions — they return a valid Boolean for every possible combination of the four fields. There is no null, undefined, or error return.
  - Method calls have no side effects and can be invoked any number of times without changing behavior.
  - The methods do not check for architectural invariants (e.g., `state_inflight` true while `state_valid` false). They compute their expressions literally — the instantiating module is responsible for maintaining field consistency.
- **Performance and Constraints**: All methods are single-level logic expressions. `isInvalid` uses a NOT gate. `isValid` and `isInflight` are wire pass-throughs. `isActive` uses a 2-input AND. `isDcacheReqCandidate` uses a 3-input AND (two negated inputs). No method has a critical path longer than one gate delay.

#### IsInvalid Method — Entry Free for Allocation

<FC-IS-INVALID>

`isInvalid()` returns `!state_valid`. It is the primary signal used by the Sbuffer enqueue pipeline to find free entry slots for new store request insertion. When `isInvalid()` is true, the entry is available for allocation. Source: `SbufferEntryState.scala:7`.

**Check points:**
- <CK-INVALID-TRUE> `state_valid=false`. Verify `isInvalid()` returns true. The entry is free.
- <CK-INVALID-FALSE> `state_valid=true`. Verify `isInvalid()` returns false. The entry is occupied, regardless of the other three field values.
- <CK-INVALID-INVERSE> For all 16 field combinations, verify `isInvalid()` is the logical inverse of `isValid()`: `isInvalid() == !isValid()`. No combination exists where both return true or both return false.

#### IsValid Method — Entry Occupied

<FC-IS-VALID>

`isValid()` returns `state_valid`. It is used as a qualifier to identify entries that hold data (regardless of their inflight or blocking status) for operations such as metadata reads, coherence count tracking, and debug inspection. Source: `SbufferEntryState.scala:8`.

**Check points:**
- <CK-VALID-TRUE> `state_valid=true`. Verify `isValid()` returns true.
- <CK-VALID-FALSE> `state_valid=false`. Verify `isValid()` returns false.
- <CK-VALID-PASS-THROUGH> Verify `isValid()` always returns the same value as `state_valid` — it is a wire identity, not a computation.

#### IsActive Method — Entry Active (Forwarding Priority)

<FC-IS-ACTIVE>

`isActive()` returns `state_valid && !state_inflight`. Active entries hold valid data but are not currently being written to DCache. In Sbuffer's load forwarding pipeline (`Sbuffer.scala:650-658`), active entries are selected for forwarding with higher priority than inflight entries (Mux1H selects active data after inflight data, overwriting inflight results). Active entries also participate in coherence timeout counting and tag mismatch detection.

**Check points:**
- <CK-ACTIVE-TRUE> `state_valid=true, state_inflight=false`. Verify `isActive()` returns true.
- <CK-ACTIVE-FALSE-NOT-VALID> `state_valid=false, state_inflight=false`. Verify `isActive()` returns false.
- <CK-ACTIVE-FALSE-INFLIGHT> `state_valid=true, state_inflight=true`. Verify `isActive()` returns false.
- <CK-ACTIVE-INDEPENDENT-OF-BLOCKING> `state_valid=true, state_inflight=false, w_sameblock_inflight=true`. Verify `isActive()` returns true. The `w_sameblock_inflight` field does not affect active classification — only `state_valid` and `state_inflight` matter.
- <CK-ACTIVE-INDEPENDENT-OF-TIMEOUT> `state_valid=true, state_inflight=false, w_timeout=true`. Verify `isActive()` returns true. The `w_timeout` field does not affect active classification.

#### IsInflight Method — Entry in DCache Write Pipeline

<FC-IS-INFLIGHT>

`isInflight()` returns `state_inflight`. It identifies entries that are currently being written to DCache. In Sbuffer's load forwarding pipeline (`Sbuffer.scala:650-653`), inflight entries are selected for forwarding with lower priority than active entries. Inflight entries are excluded from eviction candidate selection (gated by `isDcacheReqCandidate`), and their inflight status gates the replay counter increment (`Sbuffer.scala:567`).

**Check points:**
- <CK-INFLIGHT-TRUE> `state_inflight=true`. Verify `isInflight()` returns true.
- <CK-INFLIGHT-FALSE> `state_inflight=false`. Verify `isInflight()` returns false.
- <CK-INFLIGHT-PASS-THROUGH> Verify `isInflight()` always returns the same value as `state_inflight` — it is a wire identity.

#### IsDcacheReqCandidate Method — Eviction Eligibility

<FC-IS-DCACHE-REQ-CANDIDATE>

`isDcacheReqCandidate()` returns `state_valid && !state_inflight && !w_sameblock_inflight`. It defines the set of entries eligible for selection as eviction candidates to DCache. In Sbuffer, the `candidateVec` is a `Vec(StoreBufferSize, Bool())` where each element is `stateVec(i).isDcacheReqCandidate()`. The PLRU replacement algorithm selects from these candidates. An assertion (`Sbuffer.scala:89`) verifies that PLRU does not select an entry outside the candidate vector.

**Check points:**
- <CK-CANDIDATE-TRUE> `state_valid=true, state_inflight=false, w_sameblock_inflight=false`. Verify `isDcacheReqCandidate()` returns true.
- <CK-CANDIDATE-FALSE-NOT-VALID> `state_valid=false`. Verify `isDcacheReqCandidate()` returns false regardless of the other fields.
- <CK-CANDIDATE-FALSE-INFLIGHT> `state_inflight=true`. Verify `isDcacheReqCandidate()` returns false regardless of the other fields.
- <CK-CANDIDATE-FALSE-SAME-BLOCK> `w_sameblock_inflight=true`. Verify `isDcacheReqCandidate()` returns false regardless of the other fields.
- <CK-CANDIDATE-EXHAUSTIVE> Enumerate all 16 field-value combinations. Verify that for every combination, `isDcacheReqCandidate()` is true if and only if all three conditions hold: `state_valid=true AND state_inflight=false AND w_sameblock_inflight=false`. This is exactly 2 combinations out of 16.

### Subcomponent Description

(no subcomponents) — SbufferEntryState is a Chisel Bundle type containing only four Boolean fields (`state_valid`, `state_inflight`, `w_timeout`, `w_sameblock_inflight`) and five combinational Boolean methods. It does not instantiate any submodules, inherit from any Module class, or depend on any other hardware unit. The parent class `SbufferBundle` provides parameter-derived constants via `HasSbufferConst`, but none of these constants affect the Bundle's fields or methods.

### State Machines and Timing
- **State Machine List**: None. SbufferEntryState is a combinational wire Bundle with no sequential elements, no registers, and no state machine. Each instance of the Bundle is a collection of four Boolean wires whose values are determined by the instantiating register file. The state machines that interpret these fields (Sbuffer FSM, enqueue pipeline stages, eviction pipeline stages) reside in the instantiating Sbuffer module.
- **State Transition Conditions**: None. The Bundle itself has no transitions. Field transitions are governed by the Sbuffer module:
  - `state_valid`: set to true on insert (`Sbuffer.scala:246`), cleared to false on DCache hit response (`Sbuffer.scala:524-526`).
  - `state_inflight`: set to true on eviction stage s0 (`Sbuffer.scala:490`), cleared to false on DCache hit response.
  - `w_timeout`: set to true on DCache replay response (`Sbuffer.scala:556-558`), cleared to false on re-eviction or hit response.
  - `w_sameblock_inflight`: set to true on insert when same-block inflight exists (`Sbuffer.scala:249-251`), cleared to false 1 cycle after blocking entry's hit response (`Sbuffer.scala:538-547`).
- **Key Timing**:
  - All five methods are combinational with zero-cycle latency — outputs are available in the same simulation cycle as field value changes.
  - When instantiated inside a register (`Reg(Vec(StoreBufferSize, new SbufferEntryState))`), field writes take effect on the next clock edge (registered behavior), so method outputs reflect the registered values with 1 cycle of write-to-read latency through the register, plus 0 cycles through the Bundle itself.

### Configuration Registers and Storage
None — SbufferEntryState is a passive wire Bundle with no registers, memory, or configurable storage elements. Each field is a `Bool()` wire; the storage is provided by the instantiating register file (`RegInit(Vec(StoreBufferSize, new SbufferEntryState))` in Sbuffer).

- **Register Map Base Address**: No bus interface — SbufferEntryState is an internal wire Bundle used within Sbuffer's stateVec register file.
- **Configuration Flow**: N/A.

### Reset and Error Handling
- **Reset Behavior**: N/A — SbufferEntryState has no reset-able state of its own. The Bundle fields reset to the value determined by the instantiating register file's reset initialization. In Sbuffer, `stateVec` is a `RegInit` that resets to all fields false (all entries invalid). Source: `Sbuffer.scala:31`.
- **Error Reporting**: None. SbufferEntryState defines no error signals, assertions, or exception-reporting mechanisms. Error detection (e.g., illegal field combinations indicating Sbuffer bugs) is the responsibility of the instantiating Sbuffer module through its assertions:
  - `stateVec(id).state_inflight === true` assertion on DCache hit response (`Sbuffer.scala:530`) — catch inflight mismatch.
  - `stateVec(id).state_inflight === true` assertion on replay response (`Sbuffer.scala:562`) — catch inflight mismatch.
- **Self-Recovery Strategy**: None. SbufferEntryState has no self-recovery mechanism. Recovery from illegal field combinations (e.g., entry stuck inflight indefinitely) is handled by Sbuffer's flush/drain mechanisms and coherence/replay timeout logic, which operate on the fields externally.

### Parameterization and Configurable Features
- **Module Parameters**: None. SbufferEntryState has no constructor parameters. All four fields are `Bool()` with no parameterized widths. The `HasSbufferConst` constants inherited through `SbufferBundle` (e.g., StoreBufferSize, EvictCycles) are not referenced by any field or method in this Bundle.
- **Runtime Configuration**: None. The Bundle has no configurable behavior at runtime. Field values are entirely determined by the instantiating module.
- **Compile Macros/Generation Options**: None.

## Verification Requirements and Coverage Suggestions
- **Functional Coverage Points**: All `CK-*` check points defined in each functional group constitute coverage targets. Key cross-coverage scenarios:
  - Exhaustive 16-combination coverage: verify all five methods produce correct outputs for all 2^4 = 16 field combinations.
  - Method orthogonality: verify each method's output depends only on its declared field dependencies (e.g., `isActive` depends only on `state_valid` and `state_inflight`, not on `w_timeout` or `w_sameblock_inflight`).
  - Method mutual consistency: verify logical relationships between methods — `isInvalid == !isValid`, `isActive` implies `isValid`, `isDcacheReqCandidate` implies `isActive`, `isInflight` and `isActive` are mutually exclusive when `state_valid` is true.
  - Transition coverage: verify method outputs update correctly on all single-field transitions (e.g., toggling `state_inflight` while holding other fields constant).
  - Integration context: verify that Sbuffer's stateVec register file correctly instantiates `StoreBufferSize` instances of SbufferEntryState with proper reset values (all false).
  - Timing: verify combinational latency (0 cycles from field change to method output change).
- **Constraints and Assumptions**:
  - The testbench may assign any Boolean value to any of the four fields independently. There is no architectural constraint on field combinations at the Bundle level.
  - Field values are sampled and driven on the same clock edge when instantiated inside a register. The Bundle itself imposes no timing constraint.
  - When verifying in isolation, the testbench should instantiate SbufferEntryState directly (not inside a register) to measure combinational behavior, or inside a `RegInit` to measure registered behavior.
  - The Bundle depends on the Chisel standard library for `Bool()` and `Bundle` types, and on `SbufferBundle` for the `HasSbufferConst` parameter mixin. These dependencies are assumed correct.
- **Test Interfaces**:
  - **Field Driver**: Directly assign `dut.state_valid`, `dut.state_inflight`, `dut.w_timeout`, `dut.w_sameblock_inflight` to Boolean values. Drive all 16 combinations in directed or randomized sequence.
  - **Method Monitor**: Sample `dut.isInvalid()`, `dut.isValid()`, `dut.isActive()`, `dut.isInflight()`, `dut.isDcacheReqCandidate()` each cycle. Compare against expected values computed from the field assignments.
  - **Reference Model**: A software function that computes each method's expected output: `ref_isInvalid = !state_valid`, `ref_isValid = state_valid`, `ref_isActive = state_valid && !state_inflight`, `ref_isInflight = state_inflight`, `ref_isDcacheReqCandidate = state_valid && !state_inflight && !w_sameblock_inflight`. Compare DUT method outputs against reference model outputs for all 16 field combinations.
  - **Assertion Monitor**: Assert logical relationships between methods: `isInvalid() === !isValid()`, `isActive() → isValid()`, `isDcacheReqCandidate() → isActive()`, `isInflight() && isValid() → !isActive()`. These assertions catch implementation errors in the method expressions.
