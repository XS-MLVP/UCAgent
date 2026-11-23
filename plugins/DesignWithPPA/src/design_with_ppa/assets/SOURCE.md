

# Bundled Liberty Assets

## ASAP7: Default Reference Technology

`asap7sc7p5t_28_RVT_TT_nldm_merged.lib` is a locally merged single-library
artifact from the OpenROAD ASAP7 7.5-track revision-28 standard-cell family.
It is selected by `pdk.name: asap7sc7p5t_28` and
`pdk.corner: RVT_TT_0p7V_25C` when no Liberty override is supplied.

- Upstream project: [The-OpenROAD-Project/asap7](https://github.com/The-OpenROAD-Project/asap7)
- Standard-cell repository: [The-OpenROAD-Project/asap7sc7p5t_28](https://github.com/The-OpenROAD-Project/asap7sc7p5t_28)
- Source directory: [OpenROAD-flow-scripts ASAP7 NLDM libraries](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/tree/master/flow/platforms/asap7/lib/NLDM)
- Characterization: RVT, TT, 0.7 V, 25°C, NLDM
- Content: 202 unique cells with timing, internal-power and leakage models
- Liberty units: `1ps`, `1pW`, capacitance `(1,ff)`; OpenSTA converts reports to ns and W
- Size: 46,154,226 bytes
- SHA-256: `5d5d792741a15885a918cb1634de8124f0256e3f6d5b1f5a4d3c8a358e8597a0`
- Exact source URLs, decompressed source hashes and cell counts:
  [merge manifest](asap7sc7p5t_28_RVT_TT_nldm_merged.manifest.json)

The input families are AO (42 cells), INVBUF (37), OA (34), SEQ (33), and
SIMPLE (56). This file is a local merge, not an upstream premerged release.
Source URLs refer to a moving branch; the manifest hashes identify the exact
input content without claiming a pinned upstream revision.

The merge retains every cell and table, deduplicates equal library-global
definitions, and keeps both combinational and sequential table-template
families. The first source supplies library date/comment metadata and the
library default maximum transition of 320 ps. SIMPLE instead inherits 4000 ps;
the merge adds explicit `max_transition: 4000` to its 58 affected pins that
lack an explicit value, preserving their original limit. Conflicting global
definitions other than these documented metadata/default differences were
rejected during the merge.

The Liberty file retains its original 2020 copyright and BSD-3-Clause notice.
[LICENSE-ASAP7.txt](LICENSE-ASAP7.txt) additionally preserves the standard-cell
repository's 2022 BSD-3-Clause license, obtained from its
[LICENSE](https://github.com/The-OpenROAD-Project/asap7sc7p5t_28/blob/main/LICENSE).
These notices accompany both source and binary plugin distributions.

ASAP7 is a predictive 7nm research model. This standard-cell Liberty supports
relative pre-layout PPA experiments; it is not a complete physical PDK and does
not provide foundry signoff or manufacturing qualification. Compare candidates
under the same library, corner, constraints, tool versions and workload.

## Nangate45: Explicit Alternative

`NangateOpenCellLibrary_typical.lib` is the Nangate Open Cell Library typical
corner available for pre-layout PPA via `pdk.name: nangate45` and
`pdk.corner: typical`.

- Upstream repository: `The-OpenROAD-Project/OpenROAD-flow-scripts`
- Upstream revision: `a7de7c42f960d6109adb0688d48186ab9499840d`
- Upstream path: `flow/platforms/nangate45/lib/NangateOpenCellLibrary_typical.lib`
- SHA-256: `8d540a4d4cf6d09d27c87ad067857a9c0c2eeb023ab7a56e058cd3113db4e9b1`
- Characterization corner: typical, 1.10 V, 25 C

The library file retains its original Nangate copyright and license notice.
The OpenROAD flow repository states that platforms and libraries retain their
individual licenses; its BSD-3-Clause build-script license does not replace the
terms embedded in this asset.

This reference library is intended for reproducible comparison and analysis.
It is not a manufacturable PDK and its results are not signoff data.
