"""Matrix enrichment for the Bug Review workflow."""
from typing import Dict, List


def attach_matrix_record_evidence(benchmark_payload: Dict[str, object]) -> Dict[str, object]:
    record_index = {}
    for record in benchmark_payload.get("benchmark_records", []):
        if not isinstance(record, dict):
            continue
        record_index[(record.get("canonical_bug"), record.get("model"))] = record

    for row in benchmark_payload.get("matrix", []):
        if not isinstance(row, dict):
            continue
        canonical_bug = row.get("canonical_bug")
        per_model = row.get("per_model", {})
        if not isinstance(per_model, dict):
            continue
        for model_name, details in per_model.items():
            if not isinstance(details, dict):
                continue
            record = record_index.get((canonical_bug, model_name), {})
            artifact_evidence = record.get("artifact_evidence", []) if isinstance(record, dict) else []
            waveform_observations = _extract_waveform_observations(artifact_evidence)
            details["waveform_observations"] = waveform_observations
            details["waveform_observation_count"] = len(waveform_observations)
            details["waveform_observation_preview"] = [
                _format_waveform_observation(item)
                for item in waveform_observations[:3]
            ]
    return benchmark_payload


def _extract_waveform_observations(artifact_evidence: object) -> List[Dict[str, object]]:
    if not isinstance(artifact_evidence, list):
        return []
    observations: List[Dict[str, object]] = []
    for item in artifact_evidence:
        if not isinstance(item, dict):
            continue
        for observation in item.get("waveform_observations", []):
            if isinstance(observation, dict):
                observations.append(observation)
    return observations


def _format_waveform_observation(observation: Dict[str, object]) -> str:
    signal = observation.get("signal") or "n/a"
    window = observation.get("window") or "n/a"
    pattern = observation.get("pattern") or "n/a"
    return f"{signal}@{window}={pattern}"
