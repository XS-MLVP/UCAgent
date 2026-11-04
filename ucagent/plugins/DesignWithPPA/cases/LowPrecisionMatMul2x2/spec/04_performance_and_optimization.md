
# Performance and optimization contract

## FG-PPA-1: Measurable performance

Performance tests must run the same deterministic workload on Python and RTL backends, but PPA measurement uses RTL simulation time, clock occurrences and accepted/completed transaction counts. Pytest wall-clock duration is not a hardware metric. Each performance test writes its own VCD or FST and JSON sidecar without overwriting another test.

### FC-PPA-1.1: Precision-specific latency

Define stable metrics `fp4_latency_cycles` and `fp8_latency_cycles` with `kind: latency`, `unit: cycles`, `direction: min`, and `aggregation: max`. Measure from the acceptance clock edge to the corresponding result-valid clock edge for a fixed matrix transaction. The hard target is at most 2 cycles for both precisions.

### FC-PPA-1.2: Precision-specific throughput

Define stable metrics `fp4_throughput_matrices_per_cycle` and `fp8_throughput_matrices_per_cycle` with `kind: throughput`, `unit: matrices/cycle`, `direction: max`, and `aggregation: mean`. Measure accepted matrix transactions divided by the number of observed clock cycles in the fixed observation window. A result may not be counted unless its valid pulse corresponds to an accepted input.

### FC-PPA-1.3: Required performance test set

Use exactly four performance pytest nodes, one for each stable metric: FP4 latency, FP4 throughput, FP8 latency and FP8 throughput. Each node uses a fixed observation window, owns one unique sidecar and one unique waveform, and reports only its assigned metric. Latency vectors use dense signed matrices. Throughput vectors use a deterministic sequence containing dense, sparse, zero and boundary-valued matrices. The ordered node IDs, parameters, waveform scopes and input traces remain unchanged across optimization versions.

## FG-PPA-2: PPA and version evidence

Every fully evaluated version must have a PPA report containing area, power and timing/frequency-equivalent data derived from the selected-language circuit sources and the complete ordered FP4/FP8 performance waveform set. The version results must identify base and candidate status and show metric changes relative to base and the previous accepted version.

### FC-PPA-2.1: Comparable workloads

Every optimization round reruns the same ordered performance TC node IDs, parameters, seeds, stimulus hashes and top-level input traces as base. A changed workload is not comparable and cannot be accepted.

### FC-PPA-2.2: Strict Pareto improvement

An accepted candidate must not regress any comparable area, power, timing/frequency, latency or throughput metric and must strictly improve at least one. The final circuit source must equal the last accepted version; rejected candidates must never become the final delivery.

## FG-PPA-3: Optimization curve

The final delivery must include a machine-bound JSON curve and an HTML performance dashboard in `{OUT}`. The dashboard must draw FP4 and FP8 latency/throughput together with area, power and timing/frequency-equivalent curves for base and every candidate with complete evidence. Positive normalized percentages mean improvement in the metric's declared direction. The summary must link to the dashboard and identify the final accepted iteration.
