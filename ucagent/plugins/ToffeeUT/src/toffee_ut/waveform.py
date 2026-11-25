"""Read run-bound waveforms and persist verifiable, bounded signal observations."""

from bisect import bisect_right
import hmac
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from ucagent.core.tools.uctool import UCTool

from .paths import digest, local_path, write_json
from .runner import _signature, archived_run, current_run


class SignalGroups(BaseModel):
    """Declare the signal roles needed to reason about a real DUT response."""

    model_config = ConfigDict(extra="forbid")
    clocks: list[str] = Field(default_factory=list, description="Exact DUT clock signals; empty for combinational analysis.")
    inputs: list[str] = Field(min_length=1, description="Exact relevant DUT input signals.")
    outputs: list[str] = Field(min_length=1, description="Exact relevant DUT output signals.")
    internal: list[str] = Field(default_factory=list, description="Exact internal signals needed to distinguish root-cause hypotheses.")


class WaveArgs(BaseModel):
    """Inspect one executed case or read an explicit, bounded signal window."""

    model_config = ConfigDict(extra="forbid")
    test_case_name: str = Field(description="Exact executed pytest node ID, without a TC- prefix.")
    waveform: str | None = Field(default=None, description="Select a project-relative waveform from this case's recorded waveforms; required when more than one exists.")
    signal_query: str = Field(default="**", description="Signal catalog query when signal_groups is omitted.")
    signal_offset: int = Field(default=0, ge=0, description="Catalog result offset.")
    signal_limit: int = Field(default=100, ge=1, le=200, description="Maximum catalog entries.")
    signal_groups: SignalGroups | None = Field(default=None, description="Relevant clocks, inputs, outputs and optional internal signals for final observations.")
    begin_time: int | None = Field(default=None, ge=0, description="Inclusive waveform timestamp, not a test log cycle count.")
    end_time: int | None = Field(default=None, ge=1, description="Exclusive waveform timestamp; final evidence requires an explicit window.")
    run: str | None = Field(default=None, min_length=1, description="Read an exact signed results/<run-id> for current inputs without updating latest.")


def inspect_waveform(workspace, project, dut, args):
    """Return real signal changes; only complete explicit windows produce receipts."""
    checked = (current_run(workspace, project) if args.run is None
               else archived_run(workspace, project, args.run))
    if checked["record"]["dut"] != dut:
        raise ValueError("The signed run belongs to another DUT")
    case = checked["cases"]["cases"].get(args.test_case_name)
    if not case or case["selftest"]:
        raise ValueError("Choose an actually executed DUT case, not a selftest or unknown node ID")
    from .layout import project_layout
    expected = "DUT" + project_layout(workspace, dut, project)["export_name"]
    waves = [row for row in case.get("waveforms", []) if row["native_dut"]["class"] == expected]
    if args.waveform is not None:
        waves = [row for row in waves if row["path"] == args.waveform]
    if len(waves) != 1:
        raise ValueError(f"Select one recorded waveform for this case: {[row['path'] for row in case.get('waveforms', [])]}; "
                         f"capture errors: {case.get('waveform_errors', [])[:3]}. "
                         "If none exists, register the native DUT before advancing it and call RunToffee(waveforms=true)")
    wave = waves[0]
    root = local_path(workspace, project, allow_root=True)
    path = local_path(root, wave["path"])
    run = local_path(root, checked["record"]["run"])
    if not path.is_relative_to(run) or digest(path) != checked["record"].get("waveforms", {}).get(wave["path"]):
        raise ValueError("The selected waveform is not part of this signed run")
    # Inspect content, not an arbitrary extension used by a generated package.
    import wavekit
    with path.open("rb") as stream:
        header = stream.read(256).lstrip()
    reader_class = wavekit.VcdReader if header.startswith(b"$") else wavekit.FstReader
    with reader_class(str(path)) as reader:
        if args.signal_groups is None:
            matches = reader.get_matched_signals(args.signal_query)
            signals = sorted({signal.full_name: signal.width for signal in matches.values()}.items())
            return {"ok": True, "run": checked["record"]["run"],
                    "test_case_name": args.test_case_name, "waveform": wave["path"],
                    "begin_time": int(reader.begin_time), "end_time": int(reader.end_time),
                    "signals": [{"name": name, "width": width} for name, width in signals[args.signal_offset:args.signal_offset + args.signal_limit]],
                    "total": len(signals), "note": "Catalog inspection is not final waveform evidence."}
        if args.begin_time is None or args.end_time is None or args.begin_time >= args.end_time:
            raise ValueError("Final observations require begin_time < end_time and explicit signal_groups")
        if args.begin_time < reader.begin_time or args.end_time > reader.end_time + 1:
            raise ValueError(f"Requested window is outside the waveform: {reader.begin_time}..{reader.end_time}")
        groups = args.signal_groups.model_dump()
        names = list(dict.fromkeys(name for entries in groups.values() for name in entries))
        if not names or len(names) > 32 or any(not name.strip() for name in names):
            raise ValueError("Choose 1..32 exact relevant signal paths")
        columns, timestamps = {}, {args.begin_time}
        for name in names:
            signal = reader.get_signal(name)
            rows = []
            # Keep X and Z separately rather than silently turning unknowns into zero.
            for mapping in ({"0": 0, "1": 1, "x": 0, "z": 0},
                            {"0": 0, "1": 0, "x": 1, "z": 0},
                            {"0": 0, "1": 0, "x": 0, "z": 1}):
                rows.append(reader._load_value_changes(signal, mapping, begin_time=args.begin_time, end_time=args.end_time))
            times = [int(row[0]) for row in rows[0]]
            if any([int(row[0]) for row in values] != times for values in rows):
                raise ValueError(f"Signal value and unknown masks do not align: {name}")
            values = []
            for value, unknown_x, unknown_z in zip(*rows, strict=True):
                number, xmask, zmask = int(value[1]), int(unknown_x[1]), int(unknown_z[1])
                values.append("".join("x" if xmask & (1 << bit) else "z" if zmask & (1 << bit)
                                      else str((number >> bit) & 1) for bit in reversed(range(signal.width))))
            timestamps.update(time for time in times if args.begin_time <= time < args.end_time)
            columns[name] = (times, values)
        if len(timestamps) > 512:
            raise ValueError("Window exceeds 512 signal events; narrow the window or signal selection, then retry WaveInfo")
        timeline = []
        for time in sorted(timestamps):
            snapshot = {}
            for name, (times, values) in columns.items():
                index = bisect_right(times, time) - 1
                snapshot[name] = values[index] if index >= 0 else None
            timeline.append({"time": time, "values": snapshot})
        if any(value is None for row in timeline for value in row["values"].values()):
            raise ValueError("A selected signal has no value in the window; choose an initialized window")
    if digest(path) != checked["record"]["waveforms"][wave["path"]]:
        raise ValueError("Waveform changed during analysis; retry after the run has finished")
    evidence = {"schema_version": 1, "dut": dut, "project": project,
                "run": checked["record"]["run"], "run_signature": checked["record"]["signature"],
                "nodeid": args.test_case_name, "waveform": wave["path"],
                "waveform_sha256": checked["record"]["waveforms"][wave["path"]], "signal_groups": groups,
                "begin_time": args.begin_time, "end_time": args.end_time, "timeline": timeline}
    evidence["signature"] = _signature(workspace, evidence)
    reference = f"results/waveform-evidence/{uuid4().hex}.json"
    write_json(local_path(root, reference), evidence)
    return {"ok": True, "receipt": reference, **{key: value for key, value in evidence.items() if key != "signature"},
            "note": "Signal observations are real; root-cause interpretation must still be justified against the independent requirement."}


def validate_waveform_evidence(workspace, project, dut, checked, nodeids, entries):
    """Require run-bound receipts and event-level analysis for every claimed RTL failure."""
    if not isinstance(entries, list) or len(entries) != len(nodeids):
        raise ValueError("RTL classification needs waveform_evidence for every exact failing node; call WaveInfo")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("nodeid") not in nodeids or entry["nodeid"] in seen:
            raise ValueError("waveform_evidence must name each failing node exactly once")
        seen.add(entry["nodeid"])
        reference = entry.get("receipt")
        path = local_path(local_path(workspace, project, allow_root=True), reference)
        if not path.resolve().is_relative_to(local_path(workspace, (Path(project) / "results/waveform-evidence").as_posix()).resolve()):
            raise ValueError("Use a receipt returned by WaveInfo")
        evidence = json.loads(path.read_text())
        signature = evidence.pop("signature", "")
        if not hmac.compare_digest(signature, _signature(workspace, evidence)):
            raise ValueError("WaveInfo receipt is missing or changed; do not edit machine evidence")
        if (evidence["dut"] != dut or evidence["project"] != project or evidence["nodeid"] != entry["nodeid"]
                or evidence["run_signature"] != checked["record"]["signature"]):
            raise ValueError("WaveInfo receipt belongs to another DUT, node or signed run")
        if (not isinstance(entry.get("analysis"), str) or not entry["analysis"].strip()
                or type(entry.get("at_time")) is not int
                or not any(row["time"] == entry["at_time"] for row in evidence["timeline"])):
            raise ValueError("Explain the root-cause analysis and reference an actual timeline at_time returned by WaveInfo")


class WaveInfo(UCTool):
    """Expose actual signal catalogs and run-bound waveform observations."""

    name: str = "WaveInfo"
    description: str = "Inspect the waveform recorded for an exact executed DUT node, optionally from an exact signed archive for current inputs. Omit signal_groups to discover signals. Supply relevant signal_groups and an explicit timestamp window to obtain run-bound evidence for Bug review. This tool never runs tests or advances the DUT."
    args_schema: type[BaseModel] = WaveArgs
    workspace: str
    project: str
    dut: str
    cfg: Any

    def _run(self, test_case_name, waveform=None, signal_query="**", signal_offset=0, signal_limit=100,
             signal_groups=None, begin_time=None, end_time=None, run_manager=None, run=None):
        """Validate the request and write only a new evidence receipt, never the original run."""
        from .tools import require_writable
        try:
            args = WaveArgs(test_case_name=test_case_name, waveform=waveform, signal_query=signal_query,
                            signal_offset=signal_offset, signal_limit=signal_limit, signal_groups=signal_groups,
                            begin_time=begin_time, end_time=end_time, run=run)
            if args.signal_groups is not None:
                require_writable(self.workspace, self.cfg,
                                 [local_path(self.workspace, (Path(self.project) / "results/waveform-evidence").as_posix())], tree=True)
            return inspect_waveform(self.workspace, self.project, self.dut, args)
        except ImportError:
            return {"ok": False, "error_code": "UT_WAVEFORM_UNAVAILABLE",
                    "error": "Waveform analysis is unavailable in the current tool runtime.",
                    "next_action": "Preserve the actual failure and ask the operator to repair the waveform tool before retrying WaveInfo."}
        except (ValueError, KeyError, TypeError, OSError, RuntimeError) as error:
            return {"ok": False, "error_code": "UT_WAVEFORM_INVALID", "error": str(error)[:1800],
                    "next_action": "Use the exact executed node and recorded waveform. Inspect the catalog, then request a bounded signal window using Guide_Doc/ut-waveform.md. Ask the operator if the waveform reader is unavailable."}
