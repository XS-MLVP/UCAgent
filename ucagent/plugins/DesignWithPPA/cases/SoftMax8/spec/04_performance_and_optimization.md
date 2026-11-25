
# Performance and optimization contract

## FG-PPA-1: Measurable performance

Performance tests must run the same deterministic workload on Python and RTL backends, but PPA measurement uses RTL simulation time, clock occurrences and accepted/completed transaction counts. Pytest wall-clock duration is not a hardware metric. Each performance test writes its own VCD or FST and JSON sidecar without overwriting another test.

### FC-PPA-1.1: Mode-specific latency

Define stable metrics `vec8_latency_cycles` and `mat2x4_latency_cycles` with `kind: latency`, `unit: cycles`, `direction: min`, and `aggregation: max`. Measure from the acceptance clock edge to the corresponding result-valid clock edge for one fixed transaction per metric. The hard target is at most 32 cycles for both modes.

### FC-PPA-1.2: Mode-specific throughput

Define stable metrics `vec8_throughput_txn_per_cycle` and `mat2x4_throughput_txn_per_cycle` with `kind: throughput`, `unit: txn/cycle`, `direction: max`, and `aggregation: mean`. Feed a fixed back-to-back sequence of 8 transactions in the selected mode and divide completed transactions by the number of observed clock cycles in the fixed observation window. A transaction may not be counted unless its result-valid pulse corresponds to an accepted input.

### FC-PPA-1.3: Required performance test set

Use exactly four performance pytest nodes, one for each stable metric: vector latency, vector throughput, matrix latency and matrix throughput. Each node uses a fixed observation window, owns one unique sidecar and one unique waveform, and reports only its assigned metric. Latency nodes use a fixed dense non-uniform vector spanning the full Q4.4 range. Throughput nodes use a deterministic sequence containing uniform, tied-maximum, skew and saturation vectors. The ordered node IDs, parameters, waveform scopes and input traces remain unchanged across optimization versions.

## FG-PPA-2: PPA and version evidence

Every fully evaluated version must have a PPA report containing area, power and timing/frequency-equivalent data derived from the selected-language circuit sources and the complete ordered vector/matrix performance waveform set. The version results must identify base and candidate status and show metric changes relative to base and the previous accepted version.

### FC-PPA-2.1: Comparable workloads

Every optimization round reruns the same ordered performance TC node IDs, parameters, seeds, stimulus hashes and top-level input traces as base. A changed workload is not comparable and cannot be accepted.

### FC-PPA-2.2: Strict Pareto improvement

An accepted candidate must not regress any comparable area, power, timing/frequency, latency or throughput metric and must strictly improve at least one. The final circuit source must equal the last accepted version; rejected candidates must never become the final delivery.

## FG-PPA-3: Optimization curve

The final delivery must include a machine-bound JSON curve and an HTML performance dashboard in `{OUT}`. The dashboard must draw vector and matrix latency/throughput together with area, power and timing/frequency-equivalent curves for base and every candidate with complete evidence. Positive normalized percentages mean improvement in the metric's declared direction. The summary must link to the dashboard and identify the final accepted iteration.
