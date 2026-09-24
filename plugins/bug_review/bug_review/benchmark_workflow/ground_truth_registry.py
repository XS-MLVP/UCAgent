"""Unified Ground Truth Registry for DUT RTL defects.

This module provides a centralized, authoritative database and API for managing
ground truth RTL defects across all DUT suites:
  - 14 Classical DUTs (e203_*, sd_*, aes_*)
  - 55+ XiangShan DUTs (bosc_*)
  - Interactive & Unit Test DUTs (adder, shiftreg, divider, etc.)

It guarantees:
  1. Centralized storage under configs/ground_truth_registry/duts/<dut>/.
  2. Automatic canonical naming resolution (e.g. 'dut_adder' <-> 'adder').
  3. Traceability: every admitted entry records admitted_at, admission_batch,
     admission_source, and admission_evidence.
  4. Seamless integration with the benchmark workflow: auto-load existing GTs
     when benchmarking, and auto-persist confirmed defects back to the registry.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from .paths import default_configs, repository_root
from typing import Any, Dict, List, Optional, Tuple


def get_default_registry_dir() -> Path:
    override = os.environ.get("BENCHMARK_GT_REGISTRY_DIR")
    if override and override.strip():
        return Path(override.strip()).resolve()
    return default_configs() / "ground_truth_registry"


def normalize_dut_name(dut_name: str) -> str:
    name = str(dut_name or "").strip()
    if name.lower().startswith("dut_"):
        name = name[4:]
    return name.strip()


def find_registered_ground_truth(
    dut_name: str,
    registry_dir: Optional[Path] = None,
) -> Optional[Path]:
    if not dut_name:
        return None
    root = registry_dir or get_default_registry_dir()
    duts_dir = root / "duts"
    if not duts_dir.is_dir():
        return None

    norm_name = normalize_dut_name(dut_name).lower()
    cand = duts_dir / norm_name / "ground_truth_rtl_defects.json"
    if cand.is_file():
        return cand

    cand_prefix = duts_dir / f"dut_{norm_name}" / "ground_truth_rtl_defects.json"
    if cand_prefix.is_file():
        return cand_prefix

    for entry in duts_dir.iterdir():
        if entry.is_dir():
            entry_norm = normalize_dut_name(entry.name).lower()
            if entry_norm == norm_name:
                cand_file = entry / "ground_truth_rtl_defects.json"
                if cand_file.is_file():
                    return cand_file

    return None


def register_or_update_dut_gt(
    dut_name: str,
    gt_payload: Dict[str, Any],
    category: str = "general",
    batch_id: str = "",
    source: str = "benchmark_run",
    registry_dir: Optional[Path] = None,
) -> Path:
    root = registry_dir or get_default_registry_dir()
    canonical_dut = normalize_dut_name(dut_name)
    target_dir = root / "duts" / canonical_dut
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / "ground_truth_rtl_defects.json"

    now_iso = datetime.now().astimezone().isoformat(timespec="seconds")
    batch = batch_id or os.environ.get("BENCHMARK_BATCH_ID") or f"batch_{datetime.now().strftime('%Y%m%d')}"

    defects = gt_payload.get("defects", []) or []
    updated_defects = []
    for defect in defects:
        d = dict(defect)
        d.setdefault("admitted_at", now_iso)
        d.setdefault("admission_batch", batch)
        d.setdefault("admission_source", source)
        d.setdefault("admission_evidence", "registered_adjudication")
        updated_defects.append(d)

    stored_payload = dict(gt_payload)
    stored_payload["dut"] = canonical_dut
    stored_payload["category"] = category
    stored_payload["last_registered_at"] = now_iso
    stored_payload["last_registered_batch"] = batch
    stored_payload["total_rtl_defects"] = len(updated_defects)
    stored_payload["defects"] = updated_defects

    target_file.write_text(json.dumps(stored_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_registry_manifest(registry_dir=root)
    return target_file


def update_registry_manifest(registry_dir: Optional[Path] = None) -> Path:
    root = registry_dir or get_default_registry_dir()
    duts_dir = root / "duts"
    duts_dir.mkdir(parents=True, exist_ok=True)

    duts_summary = {}
    total_defects = 0

    for dut_folder in sorted(duts_dir.iterdir()):
        if not dut_folder.is_dir():
            continue
        gt_file = dut_folder / "ground_truth_rtl_defects.json"
        if not gt_file.is_file():
            continue
        try:
            data = json.loads(gt_file.read_text(encoding="utf-8"))
            defect_count = len(data.get("defects", []))
            category = data.get("category", "general")
            last_updated = data.get("last_registered_at", "")
            batch = data.get("last_registered_batch", "")
            duts_summary[dut_folder.name] = {
                "dut": dut_folder.name,
                "category": category,
                "total_rtl_defects": defect_count,
                "last_registered_at": last_updated,
                "last_registered_batch": batch,
                "relative_path": f"duts/{dut_folder.name}/ground_truth_rtl_defects.json",
            }
            total_defects += defect_count
        except Exception:
            continue

    manifest = {
        "schema_version": "gt_registry_v1",
        "description": "Centralized Master Ground Truth Registry for all benchmark DUTs",
        "last_synced_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "total_registered_duts": len(duts_summary),
        "total_registered_defects": total_defects,
        "duts": duts_summary,
    }

    manifest_file = root / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_file


def migrate_all_existing_gts(registry_dir: Optional[Path] = None) -> Dict[str, int]:
    root = registry_dir or get_default_registry_dir()
    repo_root = repository_root()

    stats = {"14dut": 0, "xiangshan": 0, "wyy": 0, "initial_db": 0}

    init_db = repo_root / "DUT 级真值根因标注初版数据库"
    if init_db.is_dir():
        for item in init_db.iterdir():
            if item.is_dir():
                gt_path = item / "ground_truth_rtl_defects.json"
                if gt_path.is_file():
                    try:
                        data = json.loads(gt_path.read_text(encoding="utf-8"))
                        if data.get("defects"):
                            register_or_update_dut_gt(
                                item.name, data, category="14dut",
                                source="initial_annotated_db",
                                batch_id="baseline_initial_db",
                                registry_dir=root,
                            )
                            stats["initial_db"] += len(data.get("defects", []))
                    except Exception:
                        pass

    bm6_dir = repo_root / "outputs" / "benchmark_6"
    if bm6_dir.is_dir():
        for dut_dir in bm6_dir.iterdir():
            if dut_dir.is_dir() and (dut_dir / "data" / "ground_truth_rtl_defects.json").is_file():
                try:
                    gt_file = dut_dir / "data" / "ground_truth_rtl_defects.json"
                    data = json.loads(gt_file.read_text(encoding="utf-8"))
                    if data.get("defects"):
                        dut_name = data.get("dut") or dut_dir.name
                        existing_file = find_registered_ground_truth(dut_name, registry_dir=root)
                        existing_cnt = 0
                        if existing_file:
                            existing_cnt = len(json.loads(existing_file.read_text()).get("defects", []))
                        if len(data.get("defects", [])) >= existing_cnt:
                            register_or_update_dut_gt(
                                dut_name, data, category="14dut",
                                source="benchmark_6_adjudicated",
                                batch_id="baseline_bm6",
                                registry_dir=root,
                            )
                            stats["14dut"] += len(data.get("defects", []))
                except Exception:
                    pass

    xs_backup = repo_root / "backups" / "benchmark_xiangshan_ucagent_backup_20260910" / "benchmark_xiangshan_ucagent"
    if xs_backup.is_dir():
        for dut_dir in xs_backup.iterdir():
            if dut_dir.is_dir() and (dut_dir / "data" / "ground_truth_rtl_defects.json").is_file():
                try:
                    gt_file = dut_dir / "data" / "ground_truth_rtl_defects.json"
                    data = json.loads(gt_file.read_text(encoding="utf-8"))
                    if data.get("defects"):
                        dut_name = data.get("dut") or dut_dir.name
                        register_or_update_dut_gt(
                            dut_name, data, category="xiangshan",
                            source="xiangshan_backup_20260910",
                            batch_id="baseline_xiangshan_20260910",
                            registry_dir=root,
                        )
                        stats["xiangshan"] += len(data.get("defects", []))
                except Exception:
                    pass

    wyy_dir = repo_root / "outputs" / "wyy"
    if wyy_dir.is_dir():
        for comp_dir in wyy_dir.iterdir():
            if comp_dir.is_dir():
                for sub in comp_dir.iterdir():
                    if sub.is_dir() and (sub / "data" / "ground_truth_rtl_defects.json").is_file():
                        try:
                            gt_file = sub / "data" / "ground_truth_rtl_defects.json"
                            data = json.loads(gt_file.read_text(encoding="utf-8"))
                            if data.get("defects"):
                                dut_name = data.get("dut") or sub.name
                                register_or_update_dut_gt(
                                    dut_name, data, category="wyy",
                                    source="wyy_comparison",
                                    batch_id="baseline_wyy",
                                    registry_dir=root,
                                )
                                stats["wyy"] += len(data.get("defects", []))
                        except Exception:
                            pass

    update_registry_manifest(registry_dir=root)
    return stats
