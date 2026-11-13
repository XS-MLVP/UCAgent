"""Default pre-layout analysis using Yosys and OpenSTA."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import math
import re
import shutil

from ucagent.util.log import info
from ..backend import PPABackend, PPAContext, PPARequest, PPAResult
from ..common import _diagnostic, _tail
from ..activity import _port_bits, _convert_fst_to_vcd, _parse_vcd_activity, _aggregate_tc_activity
from ..parsers import (_load_json_file, _load_opensta_json, _classify_design, _module_stats, _power_totals, _power_rows, _timing_paths, _timing_summary, _parse_sta_metric)


class YosysOpenSTABackend(PPABackend):
    """Measure pre-layout PPA with Liberty-mapped Yosys and OpenSTA."""

    name = "yosys_opensta"
    version = "2"

    def analyze(self, request: PPARequest, context: PPAContext) -> PPAResult:
        """Return independent timing/power results and bounded tool evidence."""

        if request.options:
            raise ValueError("yosys_opensta does not accept backend_options")
        libraries = request.pdk.files.get("liberty", ())
        if len(libraries) != 1:
            raise ValueError("yosys_opensta requires exactly one pdk.files.liberty file")
        self._context = context
        self._pdk = request.pdk
        arguments = request.arguments
        rtl_files = list(request.rtl_files)
        waveform_files = list(request.waveform_files)
        liberty = libraries[0]
        sdc = request.sdc_file
        rtl_systemverilog = request.systemverilog
        run_dir = context.run_dir
        deadline = context.deadline
        result = PPAResult()
        report = result.model_dump()
        report["provenance"] = {"tools": {}, "waveform_files": list(request.waveform_provenance), "waveform_scope": arguments.waveform_scope}
        diagnostics = report["diagnostics"]
        context.progress("PPA: synthesizing and technology-mapping RTL with Yosys")
        info("[AnalyzePPA] Phase 1/4: Yosys synthesis + technology mapping (this is the longest step)...")
        synthesis = self._synthesize(
            rtl_files,
            arguments.top_module,
            liberty,
            run_dir,
            deadline,
            systemverilog=rtl_systemverilog,
        )
        report["provenance"]["tools"]["yosys"] = {
            "executable": synthesis["executable"],
            "version": next(
                (
                    line.strip()
                    for line in synthesis["stdout"].splitlines()
                    if line.strip().startswith("Yosys ")
                ),
                None,
            ),
            "log_excerpt": _tail(synthesis["stdout"] + synthesis["stderr"], 2000),
        }
        design_type, classification = _classify_design(
            synthesis["generic_stats"],
            synthesis["generic_json"],
            arguments.top_module,
        )
        report["summary"]["design_type"] = design_type
        report["details"]["classification"] = classification
        area = self._area_summary(
            synthesis["mapped_stats"], arguments.top_module
        )
        report["summary"]["area"] = area
        info(
            f"[AnalyzePPA] Phase 1/4 done: {area.get('cell_count', '?')} cells, "
            f"area={area.get('total', '?')} {area.get('unit', '')}"
        )
        mapped_stats = _module_stats(
            synthesis["mapped_stats"], arguments.top_module
        )
        report["details"]["area_by_cell_type"] = mapped_stats.get(
            "num_cells_by_type", {}
        )
        input_bits = _port_bits(synthesis["mapped_json"], arguments.top_module)
        context.progress(
            f"PPA: aggregating {len(waveform_files)} independent TC waveforms"
        )
        tc_activity = []
        waveform_errors = False
        resolved_waveform_scope: str | None = None
        input_port_names = {bit.port for bit in input_bits}
        for label, waveform in zip(arguments.waveform_files, waveform_files):
            try:
                parse_path = waveform
                if waveform.suffix.lower() == ".fst":
                    parse_path = run_dir / f"waveform-{len(tc_activity)}.vcd"
                    _convert_fst_to_vcd(
                        waveform, parse_path, wanted_ports=input_port_names
                    )
                tc_info, activity = _parse_vcd_activity(
                    parse_path, label, arguments.waveform_scope, input_bits
                )
                detected_scope = tc_info.get("waveform_scope")
                if not isinstance(detected_scope, str) or not detected_scope:
                    raise ValueError("waveform parser returned no resolved scope")
                if resolved_waveform_scope is None:
                    resolved_waveform_scope = detected_scope
                    report["provenance"]["waveform_scope"] = detected_scope
                elif detected_scope != resolved_waveform_scope:
                    raise ValueError(
                        "performance waveforms resolve to different DUT scopes: "
                        f"{resolved_waveform_scope} and {detected_scope}"
                    )
                provenance = next(
                    item
                    for item in report["provenance"]["waveform_files"]
                    if item["path"] == label
                )
                tc_info.update(
                    {
                        "format": provenance["format"],
                        "sha256": provenance["sha256"],
                        "weight": None,
                        "status": "valid",
                    }
                )
                tc_activity.append((tc_info, activity))
            except Exception as exc:
                waveform_errors = True
                tc_info = {"path": label, "status": "invalid", "error": str(exc)}
                diagnostics.append(
                    _diagnostic(
                        "waveform_aggregation",
                        "invalid_tc_waveform",
                        f"Waveform '{label}' cannot contribute reliable activity: {exc}",
                        "Regenerate this exact performance TC waveform with the common DUT scope and all top-level input ports, then rerun AnalyzePPA with the full TC list.",
                        artifact=label,
                    )
                )
            report["waveform_aggregation"]["test_cases"].append(tc_info)
        if tc_activity:
            total_duration = sum(tc["duration_seconds"] for tc, _ in tc_activity)
            for tc, _ in tc_activity:
                tc["weight"] = tc["duration_seconds"] / total_duration
            merged_activity = _aggregate_tc_activity(tc_activity)
            report["waveform_aggregation"]["merged_input_bits"] = merged_activity
            report["waveform_aggregation"]["total_duration_seconds"] = total_duration
            report["waveform_aggregation"]["reliable"] = not waveform_errors
        else:
            merged_activity = []
        context.progress("PPA: running independent OpenSTA timing analysis")
        try:
            info("[AnalyzePPA] Phase 2/4: OpenSTA static timing analysis...")
            timing_run = self._run_opensta(
                mode="timing",
                netlist=synthesis["netlist"],
                top_module=arguments.top_module,
                liberty=liberty,
                activity=[],
                sdc_file=sdc,
                clock_port=arguments.clock_port,
                clock_period_ns=arguments.clock_period_ns,
                max_paths=arguments.max_timing_paths,
                max_instances=arguments.max_power_instances,
                mapped_cell_count=area["cell_count"],
                run_dir=run_dir,
                deadline=deadline,
            )
            # Count mapped registers from Liberty semantics, independently of
            # foundry cell naming and of the number of bits in each cell.
            area.update(self._area_summary(
                synthesis["mapped_stats"], arguments.top_module,
                timing_run["sequential_cell_count"],
            ))
            constrained_paths = _timing_paths(timing_run["timing_json"])
            unconstrained_paths = _timing_paths(
                timing_run["unconstrained_timing_json"]
            )
            clock_names = set(timing_run["clock_names"])
            unconstrained_paths = [
                path
                for path in unconstrained_paths
                if str(path.get("startpoint", "")) not in clock_names
            ]
            paths = constrained_paths + unconstrained_paths
            unique_paths = []
            seen_paths = set()
            for path in paths:
                identity = (
                    path.get("type"),
                    path.get("path_group"),
                    path.get("startpoint"),
                    path.get("endpoint"),
                    path.get("path_type"),
                )
                if identity not in seen_paths:
                    seen_paths.add(identity)
                    unique_paths.append(path)
            paths = unique_paths[: arguments.max_timing_paths]
            timing = _timing_summary(paths)
            info("[AnalyzePPA] Phase 2/4 done.")
            exact_wns = _parse_sta_metric(timing_run["wns"], "wns")
            exact_tns = _parse_sta_metric(timing_run["tns"], "tns")
            if exact_wns is not None:
                timing["wns_ns"] = exact_wns
            if exact_tns is not None:
                timing["tns_ns"] = exact_tns
            clocks = self._parse_clock_period(timing_run["clock_min_period"])
            timing["clocks"] = clocks
            if clocks and any(item["maximum_frequency_hz"] for item in clocks):
                timing["metric_kind"] = "minimum_clock_period"
                timing["maximum_frequency_hz"] = min(
                    item["maximum_frequency_hz"]
                    for item in clocks
                    if item["maximum_frequency_hz"] is not None
                )
            else:
                timing["maximum_frequency_hz"] = timing[
                    "equivalent_max_frequency_hz"
                ]
            timing_available = (
                timing["critical_path_delay_ns"] is not None
                and timing["critical_path_delay_ns"] > 0
            ) or timing["maximum_frequency_hz"] is not None
            report["summary"]["timing"] = timing if timing_available else None
            report["details"]["timing_paths"] = paths[: arguments.max_timing_paths]
            report["hotspots"]["timing_paths"] = paths[: arguments.max_timing_paths]
            if not timing_available:
                diagnostics.append(
                    _diagnostic(
                        "timing",
                        "timing_metric_unavailable",
                        "OpenSTA found no positive critical data-path delay or finite minimum clock period.",
                        "Add complete timing constraints and ensure the synthesized design contains a valid data path; infinity is intentionally reported as null.",
                        observed={"clocks": clocks, "path_count": len(paths)},
                    )
                )
            if timing["wns_ns"] is not None and timing["wns_ns"] < 0:
                report["hotspots"]["findings"].append(
                    {
                        "kind": "negative_slack",
                        "value_ns": timing["wns_ns"],
                        "location": timing["limiting_path"],
                    }
                )
            report["provenance"]["tools"]["opensta_timing"] = {
                "executable": timing_run["executable"],
                "version": self._tool_version(
                    timing_run["executable"], run_dir, deadline
                ),
                "log_excerpt": _tail(
                    timing_run["stdout"] + timing_run["stderr"], 2000
                ),
            }
        except Exception as exc:
            diagnostics.append(
                _diagnostic(
                    "timing",
                    "opensta_timing_failed",
                    str(exc),
                    "Inspect the bounded OpenSTA diagnostic, fix the netlist/Liberty/SDC or clock constraint mismatch, and rerun AnalyzePPA.",
                )
            )
        if not merged_activity:
            diagnostics.append(
                _diagnostic(
                    "power",
                    "no_valid_waveform_activity",
                    "No waveform supplied a complete set of valid top-level input activities.",
                    "Fix every invalid TC waveform diagnostic and rerun AnalyzePPA with the complete performance-test waveform list.",
                )
            )
        else:
            context.progress("PPA: running OpenSTA with merged TC activity")
            try:
                info("[AnalyzePPA] Phase 3/4: OpenSTA power analysis (activity from waveforms)...")
                power_run = self._run_opensta(
                    mode="power",
                    netlist=synthesis["netlist"],
                    top_module=arguments.top_module,
                    liberty=liberty,
                    activity=merged_activity,
                    sdc_file=sdc,
                    clock_port=arguments.clock_port,
                    clock_period_ns=arguments.clock_period_ns,
                    max_paths=arguments.max_timing_paths,
                    max_instances=arguments.max_power_instances,
                    mapped_cell_count=area["cell_count"],
                    run_dir=run_dir,
                    deadline=deadline,
                )
                power, groups = _power_totals(power_run["power_json"])
                info("[AnalyzePPA] Phase 3/4 done.")
                report["summary"]["power"] = power
                report["details"]["power_groups"] = groups
                instance_rows = []
                instance_json = power_run.get("instance_power_json")
                if instance_json is not None:
                    instance_rows = _power_rows(instance_json)

                    def instance_total(row: dict[str, Any]) -> float:
                        """Return a sortable total for one OpenSTA instance row."""

                        for key in ("total", "total_power"):
                            try:
                                return float(row.get(key, 0.0))
                            except (TypeError, ValueError):
                                pass
                        return sum(
                            float(row.get(key, 0.0) or 0.0)
                            for key in ("internal", "switching", "leakage")
                        )

                    instance_rows = sorted(
                        (
                            row
                            for row in instance_rows
                            if str(row.get("group", row.get("name", ""))).lower()
                            != "total"
                        ),
                        key=instance_total,
                        reverse=True,
                    )[: arguments.max_power_instances]
                report["hotspots"]["power_instances"] = instance_rows
                if power_run.get("instance_power_omitted"):
                    diagnostics.append(
                        _diagnostic(
                            "power",
                            "power_instance_breakdown_unavailable",
                            "OpenSTA produced total/group power but could not produce the requested native top-instance breakdown for this large design.",
                            "Use the retained group totals and cell-area breakdown to narrow the block, or run a compatible OpenSTA build for instance ranking.",
                            observed=power_run["instance_power_omitted"],
                        )
                    )
                report["provenance"]["tools"]["opensta_power"] = {
                    "executable": power_run["executable"],
                    "version": self._tool_version(
                        power_run["executable"], run_dir, deadline
                    ),
                    "log_excerpt": _tail(
                        power_run["stdout"] + power_run["stderr"], 2000
                    ),
                }
            except Exception as exc:
                diagnostics.append(
                    _diagnostic(
                        "power",
                        "opensta_power_failed",
                        str(exc),
                        "Inspect the bounded OpenSTA diagnostic, verify Liberty pin models and waveform input coverage, then rerun AnalyzePPA.",
                    )
                )
        if report["summary"]["area"]["total"] is None:
            diagnostics.append(
                _diagnostic(
                    "area",
                    "area_metric_unavailable",
                    "Yosys mapped the design but the selected Liberty did not yield a finite total cell area.",
                    "Verify that every mapped cell has an area in liberty_file, then rerun AnalyzePPA.",
                )
            )
        if report["summary"]["design_type"] == "unknown":
            diagnostics.append(
                _diagnostic(
                    "classification",
                    "design_type_unknown",
                    "Yosys evidence contains unresolved blackboxes or is insufficient for a combinational/sequential decision.",
                    "Resolve every blackbox and rerun synthesis; do not supply a manual circuit classification.",
                    observed=classification,
                )
            )
        tools = report.pop("provenance")
        report["tools"] = tools["tools"]
        report["waveform_scope"] = tools["waveform_scope"]
        return PPAResult.model_validate(report)

    @staticmethod
    def _trim_instance_power(path: Path, limit: int | None) -> None:
        """Keep only the top ``limit`` instances by total power in the JSON.

        The guarded ``-instances [get_cells *]`` fallback lists every mapped
        cell; sorting here keeps the artifact the same size the ranking flag
        would have produced.
        """

        if not limit or not path.is_file():
            return
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(rows, list) or len(rows) <= limit:
            return

        def total(row):
            """Rank a native instance row by its total power."""

            for key in ("total", "Total", "total_power"):
                value = row.get(key) if isinstance(row, dict) else None
                if isinstance(value, (int, float)):
                    return value
                if isinstance(value, dict):
                    for sub in value.values():
                        if isinstance(sub, (int, float)):
                            return sub
            return 0.0

        rows.sort(key=total, reverse=True)
        path.write_text(
            json.dumps(rows[:limit], indent=2), encoding="utf-8"
        )

    @staticmethod
    def _yosys_quote(value: str) -> str:
        """Quote one string for a Yosys command script."""

        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    @staticmethod
    def _tcl_brace(value: str) -> str:
        """Quote one value as a Tcl brace word."""

        escaped = value.replace("\\", "\\\\")
        escaped = escaped.replace("{", "\\{").replace("}", "\\}")
        return "{" + escaped + "}"

    def _tool_version(self, executable: str, run_dir: Path, deadline: float) -> str | None:
        """Return a bounded external-tool version without failing completed analysis."""

        try:
            completed = self._context.run_process(
                [executable, "-version"], run_dir, deadline
            )
        except Exception:
            return None
        version = completed.stdout.strip() or completed.stderr.strip()
        return version if completed.returncode == 0 and version else None

    def _synthesize(
        self,
        rtl_files: list[Path],
        top_module: str,
        liberty: Path,
        run_dir: Path,
        deadline: float,
        *,
        systemverilog: bool = False,
    ) -> dict[str, Any]:
        """Run Yosys and return mapped/generic structured artifacts and logs."""

        script = run_dir / "synth.ys"
        lines = [
            "read_verilog "
            + ("-sv " if systemverilog else "")
            + " ".join(self._yosys_quote(str(path)) for path in rtl_files),
            f"hierarchy -check -top {top_module}",
            # Keep the analysis bounded for generated arithmetic cones.  The
            # default resource-sharing and fraig/scorr ABC script can spend
            # tens of minutes on a small RTL function with exhaustive
            # encoders; PPA still uses Liberty mapping, while OpenSTA remains
            # the timing authority below.
            f"synth -top {top_module} -noabc -noshare",
            'tee -o "generic_stats.json" stat -json',
            'write_json "generic.json"',
            f"dfflibmap -liberty {self._yosys_quote(str(liberty))}",
            f"abc -liberty {self._yosys_quote(str(liberty))} "
            # Keep the useful Liberty mapper while avoiding the expensive
            # fraig/scorr passes.  Semicolons are encoded as comma-separated
            # script tokens and preserve the ABC network-flow mapping steps.
            "-script +strash,dc2,dretime,strash,;&get,-n,;&dch,-f,;&nf,;&put",
            "clean -purge",
            # Map constant nets to dedicated tie cells so the emitted netlist
            # contains no constant-driver `assign` statements, and rename all
            # internal $-prefixed objects to driver-derived public names so
            # no escaped identifiers remain.  OpenSTA's Verilog reader rejects
            # both constructs.
            *([
                "hilomap " + " ".join(
                    f"{flag} {cell.cell} {cell.port}"
                    for flag, cell in (("-hicell", self._pdk.config.tie_high), ("-locell", self._pdk.config.tie_low))
                    if cell is not None
                )
            ] if self._pdk.config.tie_high or self._pdk.config.tie_low else []),
            "autoname",
            f'tee -o "mapped_stats.json" stat -json -liberty {self._yosys_quote(str(liberty))}',
            'write_verilog -noattr -noexpr -nodec "mapped.v"',
            'write_json "mapped.json"',
        ]
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        yosys = shutil.which("yosys")
        if yosys is None:
            raise FileNotFoundError("yosys was not found on PATH")
        info("[AnalyzePPA] Yosys running synthesis script...")
        completed = self._context.run_process([yosys, "-s", str(script)], run_dir, deadline)
        if completed.returncode != 0:
            raise RuntimeError(
                "Yosys synthesis failed\n"
                f"stdout:\n{_tail(completed.stdout)}\n"
                f"stderr:\n{_tail(completed.stderr)}"
            )
        return {
            "generic_stats": _load_json_file(run_dir / "generic_stats.json"),
            "generic_json": _load_json_file(run_dir / "generic.json"),
            "mapped_stats": _load_json_file(run_dir / "mapped_stats.json"),
            "mapped_json": _load_json_file(run_dir / "mapped.json"),
            "netlist": run_dir / "mapped.v",
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "executable": yosys,
        }

    def _constraints_tcl(
        self,
        sdc_file: Path | None,
        clock_port: str | None,
        clock_period_ns: float | None,
    ) -> list[str]:
        """Return OpenSTA timing-constraint commands for the selected API branch."""

        if sdc_file is not None:
            return [f"read_sdc {self._tcl_brace(str(sdc_file))}"]
        if clock_port is not None and clock_period_ns is not None:
            return [
                f"create_clock -name {self._tcl_brace(clock_port)} "
                f"-period {clock_period_ns:.12g} "
                f"[get_ports {self._tcl_brace(clock_port)}]"
            ]
        return []

    def _run_opensta(
        self,
        *,
        mode: str,
        netlist: Path,
        top_module: str,
        liberty: Path,
        activity: list[dict[str, Any]],
        sdc_file: Path | None,
        clock_port: str | None,
        clock_period_ns: float | None,
        max_paths: int,
        max_instances: int,
        mapped_cell_count: int,
        run_dir: Path,
        deadline: float,
    ) -> dict[str, Any]:
        """Run an independent OpenSTA timing or power analysis script."""

        script = run_dir / f"{mode}.tcl"
        lines = [
            f"read_liberty {self._tcl_brace(str(liberty))}",
            f"read_verilog {self._tcl_brace(str(netlist))}",
            f"link_design {self._tcl_brace(top_module)}",
            "set_cmd_units -time ns -capacitance pF -resistance kOhm "
            "-voltage V -current mA -power W -distance um",
            *self._constraints_tcl(sdc_file, clock_port, clock_period_ns),
        ]
        power_setup_lines: list[str] = []
        if mode == "timing":
            lines.extend(
                [
                    f"report_checks -path_delay max -group_path_count {max_paths} "
                    f"-endpoint_path_count {max_paths} -format json > "
                    f"{self._tcl_brace(str(run_dir / 'timing.json'))}",
                    f"report_checks -unconstrained -path_delay max -group_path_count {max_paths} "
                    f"-endpoint_path_count {max_paths} -format json > "
                    f"{self._tcl_brace(str(run_dir / 'unconstrained_timing.json'))}",
                    f"report_clock_min_period > {self._tcl_brace(str(run_dir / 'clock_min_period.txt'))}",
                    f"report_worst_slack -max -digits 6 > {self._tcl_brace(str(run_dir / 'wns.txt'))}",
                    f"report_tns -max -digits 6 > {self._tcl_brace(str(run_dir / 'tns.txt'))}",
                    f"set ppa_clock_file [open {self._tcl_brace(str(run_dir / 'clock_names.txt'))} w]",
                    "foreach ppa_clock [get_clocks *] { puts $ppa_clock_file [get_name $ppa_clock] }",
                    "close $ppa_clock_file",
                    f"set ppa_register_file [open {self._tcl_brace(str(run_dir / 'sequential_cell_count.txt'))} w]",
                    "puts $ppa_register_file [llength [all_registers -cells]]",
                    "close $ppa_register_file",
                ]
            )
        elif mode == "power":
            for item in activity:
                density_per_ns = float(item["density_hz"]) * 1e-9
                lines.append(
                    "set_power_activity -input_ports "
                    f"[get_ports {self._tcl_brace(item['input_bit'])}] "
                    f"-density {density_per_ns:.17g} "
                    f"-duty {float(item['duty_cycle']):.17g}"
                )
            power_setup_lines = list(lines)
            lines.append(
                f"report_power -format json > {self._tcl_brace(str(run_dir / 'power.json'))}"
            )
        else:
            raise ValueError(f"unsupported OpenSTA mode: {mode}")
        lines.append("exit")
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sta = shutil.which("sta") or shutil.which("opensta")
        if sta is None:
            raise FileNotFoundError("OpenSTA executable 'sta' was not found on PATH")
        info(f"[AnalyzePPA] OpenSTA running: {Path(script).name}")
        completed = self._context.run_process([sta, "-no_splash", str(script)], run_dir, deadline)
        combined_log = f"{completed.stdout}\n{completed.stderr}"
        if completed.returncode != 0 or re.search(r"(?m)^Error:", combined_log):
            raise RuntimeError(
                f"OpenSTA {mode} analysis failed\n"
                f"stdout:\n{_tail(completed.stdout)}\n"
                f"stderr:\n{_tail(completed.stderr)}"
            )
        result = {
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "executable": sta,
        }
        if mode == "timing":
            result["sequential_cell_count"] = int(
                (run_dir / "sequential_cell_count.txt").read_text(encoding="utf-8").strip()
            )
            result["timing_json"], result["report_warnings"] = _load_opensta_json(
                run_dir / "timing.json", allow_empty=True
            )
            (
                result["unconstrained_timing_json"],
                result["unconstrained_report_warnings"],
            ) = _load_opensta_json(
                run_dir / "unconstrained_timing.json", allow_empty=True
            )
            min_period = run_dir / "clock_min_period.txt"
            result["clock_min_period"] = (
                min_period.read_text(encoding="utf-8", errors="replace")
                if min_period.is_file()
                else ""
            )
            clock_names = run_dir / "clock_names.txt"
            result["clock_names"] = (
                [
                    line.strip()
                    for line in clock_names.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                    if line.strip()
                ]
                if clock_names.is_file()
                else []
            )
            for metric in ("wns", "tns"):
                metric_path = run_dir / f"{metric}.txt"
                result[metric] = (
                    metric_path.read_text(encoding="utf-8", errors="replace")
                    if metric_path.is_file()
                    else ""
                )
        else:
            result["power_json"], result["report_warnings"] = _load_opensta_json(
                run_dir / "power.json"
            )
            instance_script = run_dir / "power_instances.tcl"
            instance_path = run_dir / "instance_power.json"
            instance_lines = list(power_setup_lines)
            if mapped_cell_count <= 25000:
                instance_lines.extend(
                    [
                        "set ppa_cells [get_cells *]",
                        "report_power -instances $ppa_cells -format json > "
                        f"{self._tcl_brace(str(instance_path))}",
                    ]
                )
            elif max_instances and mapped_cell_count <= 100000:
                # Some OpenSTA builds advertise -highest_power_instances in help
                # but reject the flag at parse time, dropping sta into its
                # interactive prompt mid-script.  Emit both forms in guarded
                # blocks: the ranking flag when supported, otherwise the full
                # per-instance report which Python filters to the top N.
                instance_lines.extend(
                    [
                        "if {[catch {report_power -highest_power_instances "
                        f"{max_instances} -format json > "
                        f"{self._tcl_brace(str(instance_path))}"
                        "} ppa_rank_error]} {",
                        f"  report_power -instances [get_cells *] -format json > "
                        f"{self._tcl_brace(str(instance_path))}",
                        "}",
                    ]
                )
            elif max_instances:
                # OpenSTA's instance ranking is quadratic-ish on very large
                # flattened netlists and can outlive the total-power report.
                # Group totals remain complete; make the optional detail
                # explicitly diagnostic instead of blocking the PPA result.
                result["instance_power_omitted"] = (
                    "instance power ranking omitted for a netlist with "
                    f"{mapped_cell_count} cells (limit: 100000)"
                )
            if instance_lines:
                instance_lines.append("exit")
                instance_script.write_text(
                    "\n".join(instance_lines) + "\n", encoding="utf-8"
                )
                try:
                    instance_completed = self._context.run_process(
                        [sta, "-no_splash", str(instance_script)], run_dir, deadline
                    )
                    instance_log = (
                        f"{instance_completed.stdout}\n{instance_completed.stderr}"
                    )
                    # The fallback -instances form lists every cell; trim it to
                    # the requested top-N ranking by total power.
                    if instance_path.is_file():
                        self._trim_instance_power(instance_path, max_instances)
                    if instance_completed.returncode != 0 or re.search(
                        r"(?m)^Error:", instance_log
                    ):
                        raise RuntimeError(_tail(instance_log, 1000))
                    (
                        result["instance_power_json"],
                        result["instance_report_warnings"],
                    ) = _load_opensta_json(instance_path)
                except Exception as exc:
                    result["instance_power_omitted"] = _tail(str(exc), 1000)
        return result

    @staticmethod
    def _area_summary(
        mapped_stats: dict[str, Any], top_module: str,
        sequential_cell_count: int | None = None,
    ) -> dict[str, Any]:
        """Combine Yosys area/counts and OpenSTA's mapped register-cell count.

        The count split remains unknown until OpenSTA supplies Liberty-based
        register evidence; technology cell names are never classification rules.
        """

        stats = _module_stats(mapped_stats, top_module)
        cell_types = stats.get("num_cells_by_type", {})
        total = stats.get("area")
        total_value = float(total) if isinstance(total, (int, float)) else None
        cell_count = int(stats.get("num_cells", sum(cell_types.values())) or 0)
        if sequential_cell_count is not None and not 0 <= sequential_cell_count <= cell_count:
            raise ValueError("OpenSTA register-cell count is outside the mapped cell-count range")
        sequential_area = stats.get("sequential_area")
        sequential_area_value = (
            float(sequential_area)
            if isinstance(sequential_area, (int, float))
            else None
        )
        return {
            "total": total_value,
            "sequential": sequential_area_value,
            "combinational": (
                total_value - sequential_area_value
                if total_value is not None and sequential_area_value is not None
                else None
            ),
            "cell_count": cell_count,
            "sequential_cell_count": sequential_cell_count,
            "combinational_cell_count": (
                cell_count - sequential_cell_count if sequential_cell_count is not None else None
            ),
            "unit": "liberty_area_unit",
        }

    @staticmethod
    def _parse_clock_period(text: str) -> list[dict[str, Any]]:
        """Parse bounded per-clock minimum period/frequency evidence from OpenSTA text."""

        clocks: list[dict[str, Any]] = []
        pattern = re.compile(
            r"(?P<clock>\S+)\s+period_min\s*=\s*(?P<period>[-+0-9.eE]+)\s+"
            r"fmax\s*=\s*(?P<fmax>[-+0-9.eE]+|inf)",
            re.I,
        )
        for match in pattern.finditer(text):
            period = float(match.group("period"))
            fmax_text = match.group("fmax")
            reported_fmax = (
                None if fmax_text.lower() == "inf" else float(fmax_text)
            )
            maximum_frequency_hz = (
                reported_fmax * 1e6
                if reported_fmax is not None and math.isfinite(reported_fmax)
                else None
            )
            clocks.append(
                {
                    "clock": match.group("clock"),
                    "minimum_period_ns": (
                        1e9 / maximum_frequency_hz
                        if maximum_frequency_hz is not None
                        and maximum_frequency_hz > 0
                        else None
                    ),
                    "maximum_frequency_hz": (
                        maximum_frequency_hz
                    ),
                    "opensta_reported_minimum_period_ns": (
                        period if period > 0 and math.isfinite(period) else None
                    ),
                    "opensta_reported_fmax_mhz": (
                        reported_fmax
                        if reported_fmax is not None and math.isfinite(reported_fmax)
                        else None
                    ),
                }
            )
        return clocks
