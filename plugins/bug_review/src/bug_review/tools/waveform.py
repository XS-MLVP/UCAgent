"""Optional signed waveform analysis tools, absent from the default workflow."""

import re
from pathlib import Path
from typing import Type
from pydantic import BaseModel, Field

from .base import ReviewTool
from ..core.records import Record, Waveform, WaveEvent
from ..core.evidence import receipt_fields, wave_tool, event_value, event_window


class WaveArgs(Record):
    """Attach final native evidence and a concise sourced interpretation."""

    case_id: str = Field(description='Exact indexed Case ID.')
    invocation_id: str = Field(description='Imported RunTestCases invocation owning the waveform.')
    receipt_id: str = Field(description='Exact final WaveInfo receipt ID.')
    observation: str = Field(min_length=1, description='Observed behavior; do not equate a normal handshake with an error.')
    alignment: str = Field(min_length=1, description='Clock/transaction alignment, distinguishing raw wave time from log cycles.')
    source_refs: list[str] = Field(min_length=1, description='Applicable specification, test or RTL line references.')


class ApplyReceiptToCase(ReviewTool):
    """Attach evidence using signed machine fields rather than LLM transcription."""

    name: str = 'ApplyReceiptToCase'
    description: str = 'Attach final WaveInfo evidence to its exact Case and invocation, copying machine fields automatically.'
    args_schema: Type[BaseModel] = WaveArgs

    def perform(self, case_id, invocation_id, receipt_id, observation, alignment, source_refs):
        """Verify ownership and preserve any other attached windows."""
        for ref in source_refs:
            self.layout.source(ref, 1)
        fields = receipt_fields(self.layout, case_id, invocation_id, receipt_id, self.waveinfo)
        wave = Waveform(**fields, observation=observation, alignment=alignment, source_refs=source_refs)
        case = self.layout.case(case_id)
        case.waveforms = [w for w in case.waveforms if w.receipt_id != receipt_id] + [wave]
        self.layout.save_case(case)
        return {'case_id': case_id, 'receipt_id': receipt_id}


class EventArgs(Record):
    """Measure values from real waveforms; raw_value is intentionally not an argument."""

    case_id: str = Field(description='Exact indexed Case ID.')
    event_id: str = Field(pattern=r'^[A-Za-z0-9_-]+$', description='Stable identifier for this observation.')
    receipt_id: str = Field(description='Already attached receipt ID.')
    time: int = Field(ge=0, description='Raw waveform timestamp, not the software log cycle.')
    signal_path: str = Field(description='Exact signed full signal path without terminal packed range.')
    description: str = Field(min_length=1, description='Observed transaction and what this event demonstrates.')
    expected: str = Field(default='', description='Applicable expected value when discussing a deviation.')


class ApplyWaveformEvent(ReviewTool):
    """Record measured bits independently of semantic conclusions."""

    name: str = 'ApplyWaveformEvent'
    description: str = 'Read and save a real signal value from an attached receipt window. Never supply raw_value or infer error from a normal handshake.'
    args_schema: Type[BaseModel] = EventArgs

    def perform(self, case_id, **kwargs):
        """Validate exact signal/time before an atomic Case update."""
        case = self.layout.case(case_id)
        wave = next((w for w in case.waveforms if w.receipt_id == kwargs['receipt_id']), None)
        if wave is None:
            raise ValueError('attach receipt with ApplyReceiptToCase first')
        event_window(wave, kwargs['time'], kwargs['signal_path'])
        value = event_value(self.layout.workspace / wave.source_file, kwargs['time'], kwargs['signal_path'])
        event = WaveEvent(**kwargs, raw_value=value)
        case.events = [e for e in case.events if e.event_id != event.event_id] + [event]
        self.layout.save_case(case)
        return event.model_dump()


class NoteArgs(Record):
    """Explain why a Case needs no extra wave investigation or what blocks it."""

    case_id: str = Field(description='Exact indexed Case ID.')
    reason: str = Field(min_length=1, max_length=1200, description='Specific skip rationale or missing evidence and next action; not a manufactured receipt.')


class SetWaveformReviewNote(ReviewTool):
    """Allow selective investigation inside the optional waveform stage."""

    name: str = 'SetWaveformReviewNote'
    description: str = 'Record why waveform analysis is unnecessary or blocked for one Case. This does not confirm or refute its Bug.'
    args_schema: Type[BaseModel] = NoteArgs

    def perform(self, case_id, reason):
        """Store the reviewer selection without changing the test result."""
        case = self.layout.case(case_id)
        case.waveform_note = reason
        self.layout.save_case(case)
        return {'case_id': case_id}


class CatalogArgs(Record):
    """Filter real signals without loading their time series."""

    case_id: str = Field(description='Exact indexed Case ID.')
    contains: str = Field(default='', description='Case-insensitive substring filter.')
    offset: int = Field(default=0, ge=0, description='Page offset.')
    limit: int = Field(default=30, ge=1, le=100, description='Maximum signals returned.')


class ReviewSignalCatalog(ReviewTool):
    """Return actual full paths so the model need not guess hierarchy names."""

    name: str = 'ReviewSignalCatalog'
    description: str = 'Page actual VCD/FST signal paths and widths. Use these paths in signal_groups; put event expressions in WaveInfo pattern.'
    args_schema: Type[BaseModel] = CatalogArgs

    def perform(self, case_id, contains, offset, limit):
        """Read the current native Case-selected waveform catalog."""
        import wavekit
        tool = self.waveinfo or wave_tool(self.layout)
        name = self.layout.review().cases[case_id].waveform_test_case_name
        result = tool.analyze(test_case_name=name)
        relative = result.get('waveform_selection', {}).get('waveform_file', '')
        path = (self.layout.workspace / relative).resolve()
        if not relative or not path.is_relative_to(self.layout.work) or not path.is_file():
            return {'diagnostic': result, 'signals': []}
        reader_type = wavekit.FstReader if path.suffix == '.fst' else wavekit.VcdReader
        with reader_type(str(path)) as reader:
            signals = [{'path': re.sub(r'\[\d+:\d+\]$', '', s.full_name), 'width': s.width}
                       for s in reader.get_matched_signals('**').values() if contains.lower() in s.full_name.lower()]
            return {'signals': signals[offset:offset + limit], 'total': len(signals),
                    'time_range': [int(reader.begin_time), int(reader.end_time)]}
