
# Performance and optimization contract

## FG-PPA-1: Measurable performance

Performance tests must run the same deterministic workload on Python and RTL backends, but PPA measurement uses RTL simulation time, clock occurrences and accepted-word/completed-message counts. Pytest wall-clock duration is not a hardware metric. Each performance test writes its own VCD or FST and JSON sidecar without overwriting another test.

### FC-PPA-1.1: Message-class latency

Define stable metrics `short_latency_cycles` (55-byte single-block message) and `long_latency_cycles` (64-byte two-block message) with `kind: latency`, `unit: cycles`, `direction: min`, and `aggregation: max`. Measure from the acceptance clock edge of the final word (`last_i=1`) to the corresponding result-valid clock edge. The hard targets are at most 80 cycles for the single-block message and at most 144 cycles for the two-block message.

### FC-PPA-1.2: Streaming throughput

Define a stable metric `stream_throughput_words_per_cycle` with `kind: throughput`, `unit: words/cycle`, `direction: max`, and `aggregation: mean`. Feed a fixed 8-message sequence (192 bytes total) back-to-back and divide accepted 32-bit data words by the number of observed clock cycles in the fixed observation window. A message may not be counted unless its result-valid pulse corresponds to an accepted final word.

### FC-PPA-1.3: Required performance test set

Use exactly three performance pytest nodes, one for each stable metric: short latency, long latency and streaming throughput. Each node uses a fixed observation window, owns one unique sidecar and one unique waveform, and reports only its assigned metric. Latency nodes use fixed normative messages; the throughput node uses a deterministic message sequence containing all `byte_len_i` encodings and all length classes. The ordered node IDs, parameters, waveform scopes and input traces remain unchanged across optimization versions.

## FG-PPA-2: PPA and version evidence

Every fully evaluated version must have a PPA report containing area, power and timing/frequency-equivalent data derived from the selected-language circuit sources and the complete ordered short/long/stream performance waveform set. The version results must identify base and candidate status and show metric changes relative to base and the previous accepted version.

### FC-PPA-2.1: Comparable workloads

Every optimization round reruns the same ordered performance TC node IDs, parameters, seeds, stimulus hashes and top-level input traces as base. A changed workload is not comparable and cannot be accepted.

### FC-PPA-2.2: Strict Pareto improvement

An accepted candidate must not regress any comparable area, power, timing/frequency, latency or throughput metric and must strictly improve at least one. The final circuit source must equal the last accepted version; rejected candidates must never become the final delivery.

## FG-PPA-3: Optimization curve

The final delivery must include a machine-bound JSON curve and an HTML performance dashboard in `{OUT}`. The dashboard must draw short/long latency and streaming throughput together with area, power and timing/frequency-equivalent curves for base and every candidate with complete evidence. Positive normalized percentages mean improvement in the metric's declared direction. The summary must link to the dashboard and identify the final accepted iteration.
