"""Application service for v6 shadow scoring over frozen DUT payloads."""

from __future__ import annotations

from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, Mapping, Optional

from .root_centric_audit import audit_root_centric_result
from .root_centric_metrics import score_root_centric_dut
from .score_aggregation import aggregate_root_centric_model
from .functional_coverage_contract import FunctionalCoverageContractError, load_functional_coverage_inputs
from .task_manifest import stable_hash


def _contract_paths(
    contract_dir: Optional[Path], dut: str, revision: Mapping[str, Any],
) -> tuple[Optional[Path], Optional[Path], str]:
    if not contract_dir:
        return None, None, ""
    dut_dir = contract_dir / dut
    revision_id = str(revision.get("revision_id") or "")
    candidates = []
    if revision_id and "/" not in revision_id and revision_id not in {".", ".."}:
        candidates.append(dut_dir / revision_id)
    candidates.append(dut_dir)
    for candidate_dir in candidates:
        functional = candidate_dir / "functional_coverage_plan.json"
        if functional.exists():
            return functional, None, str(candidate_dir)
        plan = candidate_dir / "common_verification_plan.json"
        evidence = candidate_dir / "root_scenario_evidence.json"
        if plan.exists() or evidence.exists():
            return plan, evidence, str(candidate_dir)
    return None, None, ""


def prepare_root_centric_profiles(
    payloads: list[Dict[str, Any]], policy: Mapping[str, Any],
    *, contract_dir: Optional[Path] = None,
    contract_errors_as_missing: bool = False,
) -> Dict[str, Any]:
    models = sorted({str(model) for payload in payloads for model in payload.get("model_names", []) or []})
    profiles = {model: [] for model in models}
    contract_audit = []
    for payload in payloads:
        dut = str(payload.get("dut") or str(payload.get("_dut_dir") or "").removeprefix("dut_"))
        dut_models = sorted({str(model) for model in payload.get("model_names", []) or []})
        plan_path, evidence_path, resolved_contract_dir = _contract_paths(
            contract_dir, dut, payload.get("_benchmark_revision") or {},
        )
        contract_error = ""
        try:
            plan, evidence = load_functional_coverage_inputs(
                plan_path, evidence_path, expected_dut=dut, models=dut_models,
                expected_revision=payload.get("_benchmark_revision") or None,
            )
        except FunctionalCoverageContractError as exc:
            if not contract_errors_as_missing:
                raise
            plan, evidence = None, None
            contract_error = str(exc)
        contract_audit.append({
            "dut": dut, "functional_plan_available": plan is not None,
            "plan_hash": (plan or {}).get("plan_hash"),
            "evidence_hash": (evidence or {}).get("evidence_hash"),
            "functional_coverage_target_count": len((plan or {}).get("functional_coverage_targets", []) or []),
            "functional_coverage_evidence_count": len((evidence or {}).get("functional_coverage", []) or []),
            "revision_id": (plan or {}).get("revision_id"),
            "source_snapshot_hash": (plan or {}).get("source_snapshot_hash"),
            "contract_dir": resolved_contract_dir,
            "load_error": contract_error,
        })
        for model in dut_models:
            profiles[model].append(score_root_centric_dut(
                payload, model, policy, functional_plan=plan,
                functional_evidence=evidence,
            ))
    return {"profiles": profiles, "contracts": contract_audit,
            "policy_hash": policy["policy_hash"], "payload_hash": stable_hash(payloads)}


def build_root_centric_shadow_result(
    payloads: list[Dict[str, Any]], policy: Mapping[str, Any],
    *, contract_dir: Optional[Path] = None, benchmark_dir: Optional[Path] = None,
    contract_errors_as_missing: bool = False,
    benchmark_set_manifest: Optional[Path] = None,
    benchmark_set_id: str = "", benchmark_set_manifest_hash: str = "",
    payload_variant: str = "finalized",
    prepared_profiles: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    prepared = prepared_profiles if prepared_profiles is not None else prepare_root_centric_profiles(
        payloads, policy, contract_dir=contract_dir,
        contract_errors_as_missing=contract_errors_as_missing,
    )
    if prepared.get("policy_hash") != policy["policy_hash"] or prepared.get("payload_hash") != stable_hash(payloads):
        raise ValueError("prepared DUT metrics do not match the frozen payloads and policy")
    profiles, contract_audit = prepared["profiles"], prepared["contracts"]
    results = [aggregate_root_centric_model(model, rows, policy) for model, rows in profiles.items()]
    results.sort(key=lambda item: (
        item.get("normalized_score") is None,
        -float(item.get("normalized_score") or 0), item["model"],
    ))
    result = {
        "schema_version": "overall_model_score.v6.shadow",
        "status": "transition_observation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_dir": str(benchmark_dir.resolve()) if benchmark_dir else "",
        "input_scope": {
            "mode": (
                "benchmark_set_manifest" if benchmark_set_manifest
                else "directory_scan"
            ),
            "benchmark_set_manifest": (
                str(benchmark_set_manifest.resolve()) if benchmark_set_manifest else ""
            ),
            "benchmark_set_id": benchmark_set_id,
            "benchmark_set_manifest_hash": benchmark_set_manifest_hash,
            "payload_variant": payload_variant,
        },
        "policy_version": policy["policy_version"],
        "policy_hash": policy["policy_hash"],
        "policy_status": policy.get("status", "frozen"),
        "dimension_weights": policy["dimension_weights"],
        "duts": [item["dut"] for item in contract_audit],
        "contracts": contract_audit,
        "models": results,
        "ranking_policy": "rank deterministic normalized scores when input and arithmetic validation pass",
    }
    result["cutover_audit"] = audit_root_centric_result(result)
    if not result["cutover_audit"]["ready"]:
        for model in result["models"]:
            model["ranking_score"] = None
    ranked_models = sorted(
        (
            model for model in result["models"]
            if model.get("ranking_score") is not None
        ),
        key=lambda model: (-float(model["ranking_score"]), str(model["model"])),
    )
    result["ranking"] = [
        {
            "rank": rank,
            "model": model["model"],
            "score": model["ranking_score"],
        }
        for rank, model in enumerate(ranked_models, 1)
    ]
    return result


def root_centric_shadow_markdown(result: Mapping[str, Any]) -> str:
    dimensions = list(result.get("dimension_weights", {}))
    lines = [
        "# Root-Centric Overall Model Score (v6 Shadow)", "",
        "> V6 transition result. It reuses finalized v5 facts and adds only common functional coverage.", "",
        f"Policy: `{result.get('policy_version')}`  ",
        f"Policy hash: `{result.get('policy_hash')}`", "",
        "| Model | Qualification | Earned / Available | Score | Ranking | Completeness |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for model in result.get("models", []):
        normalized = "n/a" if model.get("normalized_score") is None else f"{model['normalized_score']:.2f}"
        lines.append(
            f"| {model['model']} | {model['qualification']} | {model['earned_points']:.2f} / "
            f"{model['available_points']:.2f} | {normalized} | "
            f"{model.get('ranking_score') if model.get('ranking_score') is not None else 'n/a'} | "
            f"{model['data_completeness']:.1%} |"
        )
    lines += ["", "## Dimension Profile", ""]
    for model in result.get("models", []):
        lines += [f"### {model['model']}", "", "| Dimension | Weight | Value | Points | Scoreable DUTs |", "|---|---:|---:|---:|---:|"]
        for key in dimensions:
            item = model["dimensions"][key]
            value = f"{item['value']:.3f}" if item["available"] else "n/a"
            lines.append(
                f"| {key} | {result['dimension_weights'][key]:.0f} | {value} | "
                f"{item['weighted_points']:.2f} | {item['applicable_dut_count']}/{item['total_dut_count']} |"
            )
        lines.append("")
    comparison = result.get("legacy_v5_comparison") or {}
    if comparison:
        lines += [
            "## Legacy v5 Comparison", "",
            "| Model | v5 official | v6 shadow normalized |",
            "|---|---:|---:|",
        ]
        for item in comparison.get("models", []):
            lines.append(
                f"| {item['model']} | {item.get('v5_score', 'n/a')} | "
                f"{item.get('v6_shadow_normalized_score', 'n/a')} |"
            )
        lines += ["", comparison.get("note", ""), ""]
    audit = result.get("cutover_audit") or {}
    lines += [
        "## Cutover Audit", "",
        f"Ready: `{str(bool(audit.get('ready'))).lower()}`  ",
        f"Errors: `{len(audit.get('errors', []))}`  ",
        f"Warnings: `{len(audit.get('warnings', []))}`", "",
    ]
    for item in audit.get("errors", []) + audit.get("warnings", []):
        lines.append(f"- `{item.get('code')}`: {item.get('message')}")
    lines.append("")
    lines += [
        "GT-root-normalized symptom coverage and all non-functional dimensions read finalized payload facts directly.",
        "N/A dimensions are excluded from available points. Warnings are notices and do not block ranking.",
        "",
    ]
    return "\n".join(lines)


def write_root_centric_shadow_outputs(
    result: Mapping[str, Any], output_dir: Path,
) -> Dict[str, str]:
    """Write the stable machine and review artifacts for one shadow result."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "overall_model_score.v6.shadow.json"
    markdown_path = output_dir / "overall_model_score.v6.shadow.md"
    html_path = output_dir / "overall_model_score.v6.shadow.html"
    def atomic_write(path: Path, content: str) -> None:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=output_dir, delete=False,
        ) as handle:
            handle.write(content)
            temporary = Path(handle.name)
        os.replace(temporary, path)

    atomic_write(json_path, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    atomic_write(markdown_path, root_centric_shadow_markdown(result))
    rows = []
    for model in result.get("models", []):
        cells = "".join(
            f"<td>{float((model.get('dimensions', {}).get(key) or {}).get('value', 0)):.3f}</td>"
            if (model.get("dimensions", {}).get(key) or {}).get("available") else "<td>n/a</td>"
            for key in result.get("dimension_weights", {})
        )
        rows.append(
            "<tr><th>{}</th><td class='score'>{:.2f}</td>{}</tr>".format(
                html.escape(str(model.get("model") or "")),
                float(model.get("normalized_score") or 0), cells,
            )
        )
    headers = "".join(
        f"<th>{html.escape(str(key))}<br>{float(weight):g}</th>"
        for key, weight in result.get("dimension_weights", {}).items()
    )
    notices = "".join(
        f"<li>{html.escape(str(item.get('code') or ''))}: {html.escape(str(item.get('message') or ''))}</li>"
        for item in (result.get("cutover_audit") or {}).get("warnings", [])
    ) or "<li>None</li>"
    atomic_write(html_path,
        "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
        "content='width=device-width'><title>Root-Centric Model Score v6</title>"
        "<style>body{font:14px system-ui;margin:28px;background:#f8fafc;color:#17202a}"
        "main{max-width:1500px;margin:auto;background:white;padding:24px;border:1px solid #dbe3ea}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #dbe3ea;padding:8px;text-align:right}"
        "th:first-child{text-align:left}.score{font-size:18px;font-weight:700;color:#0f766e}"
        "code{background:#eef4f8;padding:2px 4px}</style></head><body><main>"
        "<h1>Root-Centric Overall Model Score v6</h1>"
        f"<p>Policy <code>{html.escape(str(result.get('policy_version') or ''))}</code>; "
        f"benchmark set <code>{html.escape(str((result.get('input_scope') or {}).get('benchmark_set_id') or 'single-DUT'))}</code>.</p>"
        f"<table><thead><tr><th>Model</th><th>Score</th>{headers}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table><h2>Notices</h2><ul>{notices}</ul>"
        "</main></body></html>",
    )
    return {"json": str(json_path), "markdown": str(markdown_path), "html": str(html_path)}
