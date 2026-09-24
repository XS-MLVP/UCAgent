"""Minimal common functional-coverage contract with legacy-file migration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from .scoring_policy import canonical_hash


class FunctionalCoverageContractError(ValueError):
    """Raised when the common functional-coverage contract is invalid."""


def _load_object(path: Path | str) -> Dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise FunctionalCoverageContractError(f"{path} must contain a JSON object")
    return value


def _identity(value: Mapping[str, Any]) -> Dict[str, str]:
    return {
        key: str(value.get(key) or "")
        for key in ("revision_id", "source_snapshot_hash")
    }


def validate_functional_coverage_contract(
    contract: Mapping[str, Any], *, expected_dut: str = "",
    models: Iterable[str] = (),
    expected_revision: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    if contract.get("schema_version") != "functional_coverage_plan.v1":
        raise FunctionalCoverageContractError("unsupported functional coverage contract schema")
    dut = str(contract.get("dut") or "")
    if not dut or (expected_dut and dut != expected_dut):
        raise FunctionalCoverageContractError(
            f"functional coverage DUT mismatch: expected {expected_dut}, got {dut}"
        )
    if expected_revision:
        expected = _identity(expected_revision)
        actual = _identity(contract)
        for key, value in expected.items():
            # Only enforce if contract explicitly sets a non-empty revision/snapshot hash
            if value and actual[key] and actual[key] != value:
                raise FunctionalCoverageContractError(
                    f"functional coverage {key} mismatch: expected {value}, got {actual[key]}"
                )

    targets = contract.get("targets")
    observations = contract.get("observations")
    if not isinstance(targets, list) or not isinstance(observations, list):
        raise FunctionalCoverageContractError("functional coverage contract needs targets and observations lists")
    target_ids = set()
    normalized_targets = []
    for item in targets:
        target_id = str(item.get("target_id") or "") if isinstance(item, dict) else ""
        if not target_id or target_id in target_ids:
            raise FunctionalCoverageContractError(f"missing or duplicate functional target: {target_id}")
        if float(item.get("weight", 1.0)) <= 0:
            raise FunctionalCoverageContractError(f"functional target {target_id} needs positive weight")
        if not all(str(item.get(key) or "").strip() for key in (
            "coverage_definition", "sampling_rule", "oracle_definition",
        )):
            raise FunctionalCoverageContractError(
                f"functional target {target_id} needs definition, sampling rule, and Oracle"
            )
        collection_status = str(item.get("collection_status") or "scoreable")
        if collection_status not in {"scoreable", "benchmark_unavailable"}:
            raise FunctionalCoverageContractError(f"functional target {target_id} has invalid collection status")
        if collection_status == "benchmark_unavailable" and not str(
            item.get("unavailable_reason") or ""
        ).strip():
            raise FunctionalCoverageContractError(
                f"functional target {target_id} needs unavailable_reason"
            )
        target_ids.add(target_id)
        normalized_targets.append({**item, "target_id": target_id})

    known_models = {str(model) for model in models}
    observation_ids = set()
    normalized_observations = []
    for item in observations:
        if not isinstance(item, dict):
            raise FunctionalCoverageContractError("functional observations must be objects")
        model = str(item.get("model") or "")
        target_id = str(item.get("target_id") or "")
        identity = (model, target_id)
        if not model or target_id not in target_ids or identity in observation_ids:
            continue
        # Skip history models not participating in current run
        if known_models and model not in known_models:
            continue
        status = str(item.get("status") or "")
        if status not in {
            "hit", "miss", "pending", "model_caused_missing", "benchmark_unavailable",
        }:
            raise FunctionalCoverageContractError(f"invalid functional coverage status: {status}")
        if status in {"hit", "miss", "pending"}:
            for field in ("attempted", "sampled", "oracle_valid"):
                if not isinstance(item.get(field), bool):
                    raise FunctionalCoverageContractError(
                        f"functional coverage {status} needs boolean {field}"
                    )
            attempted, sampled, oracle_valid = (
                item["attempted"], item["sampled"], item["oracle_valid"]
            )
            if sampled and not attempted:
                raise FunctionalCoverageContractError("functional coverage cannot be sampled before attempt")
            if oracle_valid and not sampled:
                raise FunctionalCoverageContractError("functional Oracle cannot be valid without sample")
            if status == "hit" and not (attempted and sampled and oracle_valid):
                raise FunctionalCoverageContractError("functional hit needs attempt, sample, and valid Oracle")
            if status == "pending" and not attempted:
                raise FunctionalCoverageContractError("pending functional coverage needs an attempted execution")
            if attempted and not (
                item.get("test_nodeids") and str(item.get("evidence_source") or "").strip()
            ):
                raise FunctionalCoverageContractError(
                    "attempted functional coverage needs test nodeids and evidence_source"
                )
        observation_ids.add(identity)
        normalized_observations.append(dict(item))

    scoreable_targets = {
        item["target_id"] for item in normalized_targets
        if str(item.get("collection_status") or "scoreable") == "scoreable"
    }
    if known_models and scoreable_targets:
        expected_matrix = {
            (model, target_id) for model in known_models for target_id in scoreable_targets
        }
        missing = expected_matrix - observation_ids
        # Auto-fallback unmapped models to 'miss' rather than crashing the entire contract
        for model, target_id in sorted(missing):
            observation_ids.add((model, target_id))
            normalized_observations.append({
                "model": model,
                "target_id": target_id,
                "status": "miss",
                "attempted": False,
                "sampled": False,
                "oracle_valid": False,
                "test_nodeids": [],
                "evidence_source": "benchmark_auto_fallback_unmapped",
            })

    validated = dict(contract)
    validated["targets"] = normalized_targets
    validated["observations"] = normalized_observations
    validated["contract_hash"] = canonical_hash({
        key: value for key, value in validated.items() if key != "contract_hash"
    })
    return validated


def _legacy_contract(plan: Mapping[str, Any], evidence: Mapping[str, Any]) -> Dict[str, Any]:
    if str(plan.get("dut") or "") != str(evidence.get("dut") or ""):
        raise FunctionalCoverageContractError("legacy functional plan/evidence DUT mismatch")
    if _identity(plan) != _identity(evidence):
        raise FunctionalCoverageContractError("legacy functional plan/evidence revision mismatch")
    return {
        "schema_version": "functional_coverage_plan.v1",
        "dut": plan.get("dut"),
        "revision_id": plan.get("revision_id", ""),
        "source_snapshot_hash": plan.get("source_snapshot_hash", ""),
        "status": plan.get("status", "legacy_migrated"),
        "targets": plan.get("functional_coverage_targets", []) or [],
        "observations": evidence.get("functional_coverage", []) or [],
    }


def load_functional_coverage_contract(
    path: Path | str, *, expected_dut: str = "", models: Iterable[str] = (),
    expected_revision: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    return validate_functional_coverage_contract(
        _load_object(path), expected_dut=expected_dut, models=models,
        expected_revision=expected_revision,
    )


def load_functional_coverage_inputs(
    plan_path: Optional[Path], evidence_path: Optional[Path], *, expected_dut: str = "",
    models: Iterable[str] = (), expected_revision: Optional[Mapping[str, Any]] = None,
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Load the new one-file contract, or migrate the old two-file shape."""
    if plan_path is None:
        return None, None
    if plan_path.name == "functional_coverage_plan.json":
        contract = load_functional_coverage_contract(
            plan_path, expected_dut=expected_dut, models=models,
            expected_revision=expected_revision,
        )
    else:
        if evidence_path is None or not evidence_path.exists():
            raise FunctionalCoverageContractError("legacy functional evidence file is missing")
        contract = validate_functional_coverage_contract(
            _legacy_contract(_load_object(plan_path), _load_object(evidence_path)),
            expected_dut=expected_dut, models=models,
            expected_revision=expected_revision,
        )
    plan = {
        "dut": contract["dut"], "revision_id": contract.get("revision_id", ""),
        "source_snapshot_hash": contract.get("source_snapshot_hash", ""),
        "status": contract.get("status", ""),
        "functional_coverage_targets": contract["targets"],
        "plan_hash": contract["contract_hash"],
    }
    evidence = {
        "dut": contract["dut"], "revision_id": contract.get("revision_id", ""),
        "source_snapshot_hash": contract.get("source_snapshot_hash", ""),
        "status": contract.get("status", ""),
        "functional_coverage": contract["observations"],
        "evidence_hash": contract["contract_hash"],
    }
    return plan, evidence
