"""Apply measured waveform events without model-authored raw bus values."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from ucagent.tools.uctool import UCTool
from ..core.evidence import case_waveforms, event_issues, read_event_value, signal_identity
from ..core.json_io import atomic_write_json
from ..core.layout import review_waveinfo
from ..core.records import BusField, ReviewEvent, load_record, source_root, within_output


class WaveformEventArgs(BaseModel):
    """Keep semantic interpretation separate from measured machine fields."""

    model_config = ConfigDict(extra="forbid")
    case_id: str
    event_id: str
    execution_id: str
    receipt_id: str
    time: int = Field(ge=0, description="Raw waveform timestamp, not a software log cycle.")
    signal_path: str = Field(description="Exact full path from signed viewer signals.")
    description: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    kind: Literal["trigger", "first_deviation", "assertion", "normal_reference"]
    expected: str = ""
    step_id: str = ""
    fields: list[BusField] = Field(default_factory=list)
    rtl_refs: list[str] = Field(default_factory=list)


class ApplyWaveformEvent(UCTool):
    """Read an attached signed snapshot and atomically upsert one validated event."""

    name: str = "ApplyWaveformEvent"
    description: str = (
        "Create or replace a case waveform event using the actual signal value. "
        "Supply exact case/receipt/execution, raw timestamp, signal and interpretation; "
        "never supply raw_value. Requires an unchanged signed source snapshot and an attached receipt."
    )
    args_schema: Any = WaveformEventArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="verification_review/analysis", exclude=True)
    waveinfo: Any = Field(default=None, exclude=True)

    def __init__(self, workspace: str, output_dir: str, **kwargs):
        """Bind the same signed receipt store as the current review."""
        super().__init__(workspace=workspace, output_dir=output_dir, **kwargs)
        self.waveinfo = review_waveinfo(workspace)

    def _run(self, **kwargs) -> dict:
        """Reject missing, stale, wrong-case or out-of-window evidence before writing."""
        output = Path(self.workspace).resolve() / self.output_dir
        try:
            args = WaveformEventArgs.model_validate(kwargs)
            index = load_record(output, "review_index.json", "index")
            entry = index.cases[args.case_id]
            case = load_record(output, entry.record_path, "case")
            if case.case_id != args.case_id:
                raise ValueError("indexed record identity differs from requested case_id")
            if args.receipt_id not in {wave.receipt_id for wave in case_waveforms(case)}:
                raise ValueError("receipt must first be attached using ApplyReceiptToCase")
            receipt = self.waveinfo.get_analysis_receipt(args.receipt_id)
            if not receipt or self.waveinfo.get_bug_document_evidence(args.receipt_id).get("success") is not True:
                raise ValueError("receipt is missing or not usable final evidence")
            if receipt.get("arguments", {}).get("test_case_name") != entry.waveform_test_case_name:
                raise ValueError("receipt belongs to a different indexed case")
            signed = receipt.get("result", {})
            attached = next(wave for wave in case_waveforms(case) if wave.receipt_id == args.receipt_id)
            if attached.viewer_url != (signed.get("waveform_viewer") or {}).get("url"):
                raise ValueError("attached viewer differs from the signed receipt; reapply the receipt")
            selection = signed.get("waveform_selection", {})
            root = source_root(output)
            relative = selection.get("waveform_file", "")
            path = (root / relative).resolve()
            if not relative or not path.is_relative_to(root) or not path.is_file():
                raise ValueError("signed source snapshot is unavailable; retain historical evidence without inventing values")
            stat = path.stat()
            if (stat.st_size, stat.st_mtime_ns) != (selection.get("size_bytes"), selection.get("modified_time_ns")):
                raise ValueError("source snapshot changed since receipt creation")
            values = args.model_dump(exclude={"case_id"})
            values["signal_path"] = signal_identity(args.signal_path)
            values["raw_value"] = read_event_value(path, SimpleNamespace(
                time=args.time, signal_path=values["signal_path"]))
            event = ReviewEvent(source_kind="waveform", **values)
            if sum(old.event_id == event.event_id for old in case.events) > 1:
                raise ValueError("duplicate event_id in current record; repair identities in a validated case draft")
            case.events = [event if old.event_id == event.event_id else old for old in case.events]
            if not any(old.event_id == event.event_id for old in case.events):
                case.events.append(event)
            # Validate the selected repair without requiring unrelated old events
            # to be correct first. The stage gate still checks the complete case.
            selected = case.model_copy(deep=True)
            selected.events = [event]
            issues = event_issues(selected, root, self.waveinfo)
            if issues:
                return {"success": False, "error_code": "WAVEFORM_EVENT_INVALID",
                        "issues": issues[:10], "total_issues": len(issues)}
            # Recheck source identity after reading, before the single record replacement.
            if path.stat().st_mtime_ns != stat.st_mtime_ns or path.stat().st_size != stat.st_size:
                raise ValueError("source snapshot changed during event extraction")
            atomic_write_json(within_output(output, entry.record_path), case.model_dump(mode="json", by_alias=True))
            return {"success": True, "case_id": args.case_id, "event_id": event.event_id,
                    "signal_path": event.signal_path, "time": event.time, "raw_value": event.raw_value}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {"success": False, "error_code": "WAVEFORM_EVENT_INVALID", "error": str(error)[:1200],
                    "next_action": "ResolveReviewCase and inspect the attached signed receipt; no record was written"}
