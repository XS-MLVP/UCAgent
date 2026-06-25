# SbufferFlushBundle Specification Document

> This document describes the specification of the `SbufferFlushBundle` chip verification target. Keep the technical language precise, well-organized, and easy to reuse for verification. If an item does not exist, explicitly write "None" or "TBD"; do not delete the section.

## Introduction
- **Design Background**: SbufferFlushBundle defines a custom 2-wire handshake protocol for coordinating flush and drain operations between the Sbuffer (Store Buffer) module and an external flush initiator (typically the commit stage or pipeline controller). It is not a Module with sequential logic — it is a Chisel Bundle type that groups two Boolean signals (valid and empty) into a handshake pair. The handshake is used by Sbuffer at its `io.flush` port, instantiated as `Flipped(new SbufferFlushBundle)`, meaning the signal directions are reversed relative to the bundle's own direction annotations. Source: `SbufferFlushBundle.scala:1-4`, `engine_overview.txt:32-33`, `phase_01_types.txt:61-63`.
- **Design Goals**: (1) Provide a clear, minimal handshake for external agents to request a full pipeline flush. (2) Provide a completion signal that Sbuffer drives when all buffered entries have been drained. (3) Define direction semantics that map cleanly to Chisel `Flipped` port usage. (4) Enable the Sbuffer FSM to transition to drain-all state and back to idle based on the state of these two wires.

## Terms and Abbreviations in Chisel Code

| Abbreviation | Full Term | Description |
| ---- | ---- | ---- |
| valid | Valid (Flush Request) | Active-high Boolean signal. When asserted by the external flush initiator, Sbuffer must enter drain-all mode (x_drain_all). |
| empty | Empty (Flush Complete) | Active-high Boolean signal. When asserted by Sbuffer, indicates the store buffer has no active entries and the flush is complete. |
| Flipped | Chisel Flipped Wrapper | Chisel direction annotation that swaps Input/Output of the wrapped bundle. When Sbuffer uses `Flipped(new SbufferFlushBundle)`, `valid` becomes an input to Sbuffer (driven by external) and `empty` becomes an output from Sbuffer (driven by Sbuffer). |
| FSM | Finite State Machine | Sbuffer's 4-state controller that the flush handshake drives. |
| x_drain_all | Drain-All State | FSM state where Sbuffer drains both its buffer and the store queue. |
| x_idle | Idle State | FSM state where Sbuffer operates normally. |
| GatedValidRegNext | Gated Valid Register Next | A Chisel utility that holds a value across cycles for a registered output pulse. Used by Sbuffer when driving the `empty` signal. |

## Chisel Source Files

A single file defines the SbufferFlushBundle type.

File list:
- `SbufferFlushBundle.scala:1-4`: Bundle definition — two Boolean wires: `valid` (Output) and `empty` (Input). Extends Chisel `Bundle` directly (not SbufferBundle), so it does not inherit HasSbufferConst parameters.

## Top-Level Interface Overview
- **Module Name**: `SbufferFlushBundle`
- **Port List**:

  | Signal Name | Direction | Width/Type | Reset Value | Description |
  | ------ | ---- | -------- | ------ | ---- |
  | valid | Output | Bool() | N/A (driven by external initiator) | Flush request. External agent asserts this high to request that Sbuffer flush all entries. In the enclosing module (Sbuffer), this port is Flipped to become an Input. Source: `SbufferFlushBundle.scala:2`. |
  | empty | Input | Bool() | N/A (driven by Sbuffer) | Flush completion acknowledgment. Sbuffer asserts this high when the buffer is empty and flush is complete. In the enclosing module (Sbuffer), this port is Flipped to become an Output. Source: `SbufferFlushBundle.scala:3`. |

- **Clock and Reset Requirements**: SbufferFlushBundle is a passive wire bundle with no sequential elements (no registers, no state). It imposes no clock or reset requirements on its own. Clock and reset requirements are the responsibility of the instantiating module (Sbuffer), which uses a single clock domain with active-high synchronous reset. Source: `engine_overview.txt:22`.
- **External Dependencies**: The bundle itself has no dependencies on other modules. The handshake protocol it defines depends on:
  - The external flush initiator to drive `valid` and observe `empty`, following the handshake sequence.
  - The Sbuffer module to observe `valid` and drive `empty`, entering and exiting drain-all state in response.

## Functional Description

### API — Test and Verification Interface

<FG-API>

- **Overview**: This functional group describes how a testbench drives and observes the SbufferFlushBundle handshake when connected to the enclosing Sbuffer module at its `io.flush` port. The testbench acts as the external flush initiator, driving `valid` and observing `empty`.
- **Execution Flow**: The testbench asserts `io.flush.valid` to request a flush. The testbench then monitors Sbuffer's FSM state (`sbuffer_state`) to verify transition to `x_drain_all`. When all entries are evicted, Sbuffer asserts `io.flush.empty`. The testbench must then deassert `io.flush.valid` to complete the handshake.
- **Boundaries and Exceptions**:
  - SbufferFlushBundle does not define a ready/valid protocol — there is no backpressure on `valid`. The external agent must hold `valid` asserted until `empty` is observed.
  - The handshake has no timeout; Sbuffer drains entries at the rate of DCache write acceptance, which may be arbitrarily slow.
  - `valid` has FSM transition priority over all other Sbuffer state transitions: assert in any state (including x_drain_sbuffer) forces transition to x_drain_all.
- **Performance and Constraints**: The handshake latency from `valid` assertion to `empty` assertion is dominated by the number of active Sbuffer entries times the DCache write pipeline latency. There is no minimum latency constraint.

#### Driving the Flush Request Signal

<FC-DRIVE-FLUSH-VALID>

The testbench drives `io.flush.valid` high to initiate a flush. The testbench must hold valid high until Sbuffer asserts `empty`, then deassert valid.

**Check points:**
- <CK-VALID-ASSERT-IDLE> Sbuffer FSM in x_idle. Testbench asserts `io.flush.valid`. Verify Sbuffer FSM transitions to x_drain_all on the next cycle.
- <CK-VALID-ASSERT-REPLACE> Sbuffer FSM in x_replace (eviction in progress). Testbench asserts `io.flush.valid`. Verify FSM transitions to x_drain_all, overriding the current eviction state.
- <CK-VALID-ASSERT-UARCH-DRAIN> Sbuffer FSM in x_drain_sbuffer (microarchitectural drain in progress). Testbench asserts `io.flush.valid`. Verify FSM transitions to x_drain_all.
- <CK-VALID-HOLD> Testbench asserts `io.flush.valid` and holds it through multiple cycles while Sbuffer drains. Verify Sbuffer remains in x_drain_all state.

#### Observing the Flush Completion Signal

<FC-OBSERVE-FLUSH-EMPTY>

The testbench monitors `io.flush.empty` to detect flush completion. Sbuffer asserts empty when all entries are drained and the store queue is empty.

**Check points:**
- <CK-EMPTY-ASSERT> Buffer has active entries. Testbench asserts `io.flush.valid`. Sbuffer drains all entries. When `sbuffer_empty` is true AND `io.sqempty` is true, verify `io.flush.empty` asserts to true.
- <CK-EMPTY-REMAINS> Buffer is empty, `io.flush.empty` is true, `io.flush.valid` still asserted. Verify `io.flush.empty` remains true until valid is deasserted.
- <CK-EMPTY-ON-RESET> After reset, Sbuffer is empty. Verify `io.flush.empty` is true (registered via GatedValidRegNext, asserting after reset propagation).

#### Completing the Handshake Cycle

<FC-HANDSHAKE-COMPLETE>

A full flush handshake cycle: valid asserted → drain → empty asserted → valid deasserted → empty deasserted → FSM returns to x_idle.

**Check points:**
- <CK-FULL-CYCLE> Sbuffer has entries, `io.flush.valid` asserted. Sbuffer drains all entries and asserts `io.flush.empty`. Testbench deasserts `io.flush.valid`. Verify on the next cycle `io.flush.empty` deasserts and FSM returns to x_idle.
- <CK-CYCLE-RESUME> Full handshake cycle completes, FSM in x_idle. Verify Sbuffer resumes normal operation: `io.in(0).ready` asserts and new enqueues are accepted.
- <CK-CYCLE-REPEAT> Full handshake cycle completes. Testbench immediately asserts `io.flush.valid` again. Verify second handshake cycle executes correctly from x_idle.

### Flush Handshake Protocol Definition

<FG-FLUSH-PROTOCOL>

- **Overview**: SbufferFlushBundle defines a 2-phase handshake protocol: (1) request phase — external agent asserts `valid` to request flush; (2) acknowledgment phase — Sbuffer asserts `empty` to confirm completion. This is distinct from the Decoupled (ready-valid) protocol because there is no backpressure on `valid` and no per-cycle handshake — the handshake spans multiple cycles across the entire drain operation.
- **Execution Flow**: 
  1. External initiator asserts `valid` (active-high).
  2. Sbuffer observes `valid`, FSM transitions to x_drain_all.
  3. Sbuffer selects and evicts all active entries to DCache, one at a time.
  4. When buffer is empty AND store queue is empty, Sbuffer asserts `empty` (active-high, via GatedValidRegNext for registered output pulse).
  5. External initiator observes `empty`, deasserts `valid`.
  6. Sbuffer observes `valid` deasserted, deasserts `empty`.
  7. Sbuffer FSM transitions back to x_idle.
  Source: `Sbuffer.scala:360-361`, `engine_overview.txt:32-33`.
- **Boundaries and Exceptions**:
  - SbufferFlushBundle has no ready signal. The external initiator must not deassert `valid` before `empty` is asserted — doing so aborts the flush mid-drain, and the FSM behavior in this case is TBD (depends on Sbuffer FSM transition rules when valid deasserts during drain).
  - The bundle has no error or timeout signals. The external initiator must implement its own timeout mechanism if needed.
  - After the handshake completes, SbufferFlushBundle returns to quiescent state with `valid` low and `empty` low.
- **Performance and Constraints**: The handshake has no minimum or maximum duration constraints imposed by the bundle itself. Duration is governed by the number of entries to drain and DCache write pipeline acceptance rate.

#### Valid Signal Semantics

<FC-VALID-SEMANTICS>

The `valid` signal is defined as `Output(Bool())` within the bundle, meaning the signal flows out of the bundle. When instantiated as `Flipped(new SbufferFlushBundle)` in Sbuffer, the direction is reversed — `valid` flows INTO Sbuffer (driven by the external initiator). The bundle defines the wire direction; the enclosing module defines the driver/receiver roles.

**Check points:**
- <CK-VALID-DIRECTION> Bundle instantiated without Flipped: `valid` is an Output (module drives it externally). Bundle instantiated as `io.flush = Flipped(new SbufferFlushBundle)`: `valid` is an Input to Sbuffer, driven by external logic.
- <CK-VALID-LEVEL> `valid` is active-high. High level means "flush requested." Low level means "no flush requested." No edge-triggered semantics — the level is sampled each cycle.
- <CK-VALID-STABLE> The bundle imposes no stability constraint on `valid`. The external initiator may pulse `valid` for a single cycle, but the handshake protocol requires holding it until `empty` is observed.

#### Empty Signal Semantics

<FC-EMPTY-SEMANTICS>

The `empty` signal is defined as `Input(Bool())` within the bundle, meaning the signal flows into the bundle. When instantiated as `Flipped(new SbufferFlushBundle)` in Sbuffer, the direction is reversed — `empty` flows OUT of Sbuffer (driven by Sbuffer). Sbuffer drives `empty` using `GatedValidRegNext` for a registered output pulse.

**Check points:**
- <CK-EMPTY-DIRECTION> Bundle instantiated without Flipped: `empty` is an Input (external logic sees it as driven by the module). Bundle instantiated as `io.flush = Flipped(new SbufferFlushBundle)`: `empty` is an Output from Sbuffer, observed by external logic.
- <CK-EMPTY-LEVEL> `empty` is active-high. High level means "buffer is empty, flush complete." Low level means "buffer not yet empty or no flush in progress."
- <CK-EMPTY-CONDITION> Sbuffer asserts `empty` only when BOTH conditions hold: (a) all Sbuffer entries are invalid (sbuffer_empty), AND (b) `io.sqempty` is true (store queue empty). Source: `Sbuffer.scala:361`.

### Subcomponent Description

(no subcomponents) — SbufferFlushBundle is a Chisel Bundle type containing only two Boolean wires (valid and empty). It does not instantiate any submodules, inherit from any Module class, or depend on any other hardware unit.

### State Machines and Timing
- **State Machine List**: None. SbufferFlushBundle is a combinational wire bundle with no sequential elements. The state machine tracking flush progress resides in the instantiating module (Sbuffer FSM).
- **State Transition Conditions**: None.
- **Key Timing**:
  - SbufferFlushBundle wires are combinational — no pipeline registers, no cycle delay through the bundle itself.
  - Sbuffer registers the `empty` output via `GatedValidRegNext`, adding 1 cycle of delay between the internal `empty` condition becoming true and `io.flush.empty` asserting. Source: `Sbuffer.scala:361`.
  - Sbuffer samples `valid` on each clock edge (FSM transition logic reads the wire combinatorially).

### Configuration Registers and Storage
None — SbufferFlushBundle is a passive wire bundle with no registers, memory, or configurable storage elements.

- **Register Map Base Address**: No bus interface — SbufferFlushBundle is an internal wire bundle.
- **Configuration Flow**: N/A.

### Reset and Error Handling
- **Reset Behavior**: N/A — SbufferFlushBundle has no reset-able state. After Sbuffer reset, the `valid` wire is driven by external logic (value is externally determined) and the `empty` wire is driven by Sbuffer (after reset propagation, Sbuffer is empty so `empty` asserts to true via GatedValidRegNext).
- **Error Reporting**: None. SbufferFlushBundle defines no error signals. Error conditions during flush (e.g., Sbuffer failure to drain) must be detected by the testbench through FSM state monitoring and timeout mechanisms.
- **Self-Recovery Strategy**: None. SbufferFlushBundle has no recovery mechanism. The external initiator may re-assert `valid` to retry a flush that did not complete as expected.

### Parameterization and Configurable Features
- **Module Parameters**: None. SbufferFlushBundle extends `Bundle` directly with no constructor parameters and no parameterized widths or capacities. Both signals are single-bit Bool().
- **Runtime Configuration**: None. The bundle has no configurable behavior at runtime.
- **Compile Macros/Generation Options**: None.

## Verification Requirements and Coverage Suggestions
- **Functional Coverage Points**: All `CK-*` check points above constitute coverage targets. Key cross-coverage scenarios:
  - Flush assertion in each of the 4 Sbuffer FSM states (x_idle, x_replace, x_drain_all, x_drain_sbuffer).
  - Flush with buffer fully empty (immediate empty assertion).
  - Flush with buffer at maximum capacity (maximum drain latency).
  - Flush while DCache is backpressuring (verify empty not asserted until all evictions complete).
  - Rapid repeated flush handshake cycles (back-to-back flush requests).
  - Premature valid deassertion (before empty asserted) — verify FSM behavior.
  - Simultaneous flush request and enqueue — verify enqueue blocked, flush proceeds.
- **Constraints and Assumptions**:
  - The testbench must drive `valid` as an external signal (not driven by the DUT). When testing Sbuffer with `io.flush = Flipped(new SbufferFlushBundle)`, the testbench connects to `io.flush.valid` as an input driving it and observes `io.flush.empty` as an output.
  - The bundle's direction annotations (Output/Input) are relative to the bundle itself, not the enclosing module. Verification testbenches must account for Flipped direction reversal.
  - No timing constraint on valid assertion relative to the clock edge — Sbuffer samples valid combinatorially through the FSM next-state logic.
- **Test Interfaces**:
  - **Flush Driver**: Drive `io.flush.valid` high/low to control flush initiation and release. Wait for `io.flush.empty` to complete the handshake.
  - **Flush Monitor**: Observe `io.flush.valid` and `io.flush.empty` states. Cross-reference with Sbuffer FSM state (`sbuffer_state`) and entry state vectors (`stateVec`) to verify the protocol sequence: valid high → x_drain_all → entries drained → empty high → valid low → empty low → x_idle.
  - **Reference Model**: A simple finite state machine tracking the handshake phase: IDLE → (valid asserted) → DRAINING → (all entries drained) → DONE_EMPTY_ASSERTED → (valid deasserted) → DONE_EMPTY_DEASSERTED → IDLE.
  - **Assertion Monitor**: Assertion that `empty` is never asserted when active entries remain in Sbuffer stateVec. Assertion that FSM is in x_drain_all whenever `valid` is high and the handshake is in progress.
