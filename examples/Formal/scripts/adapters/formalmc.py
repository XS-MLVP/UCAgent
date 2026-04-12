# -*- coding: utf-8 -*-
import os
import re
from typing import Dict, List, Optional
from ..formal_adapter import FormalToolAdapter

class FormalMCAdapter(FormalToolAdapter):
    def tool_name(self) -> str:
        return "formalmc"

    def tool_display_name(self) -> str:
        return "FormalMC (华大九天)"

    def log_filename(self) -> str:
        return "avis.log"

    def coverage_report_path(self, tests_dir: str) -> Optional[str]:
        return os.path.join(tests_dir, "avis", "fanin.rep")

    def build_command(self, tcl_path: str, exec_dir: str) -> List[str]:
        return ["FormalMC", "-f", tcl_path, "-override", "-work_dir", exec_dir]

    def parse_log(self, log_path: str) -> Dict[str, list]:
        result: Dict[str, list] = {
            "pass": [],
            "trivially_true": [],
            "false": [],
            "cover_pass": [],
            "cover_fail": [],
        }

        if not os.path.exists(log_path):
            return result

        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        def _is_cover(name: str) -> bool:
            return name.startswith("C_") or "COVER" in name.upper()

        def _record(prop: str, status: str) -> None:
            is_cov = _is_cover(prop)
            if status == "TrivT" or status == "TRIVIALLY_TRUE":
                if not is_cov:
                    result["trivially_true"].append(prop)
            elif status in ("Fail", "FALSE"):
                (result["cover_fail"] if is_cov else result["false"]).append(prop)
            elif status in ("Pass", "TRUE"):
                (result["cover_pass"] if is_cov else result["pass"]).append(prop)

        # Strategy 1: summary table (show_prop -summary output)
        table_re = re.compile(
            r"^\s*\d+\s+(checker_inst\.[\w.]+)\s*:\s*(TrivT|Fail|Pass|Undec)",
            re.MULTILINE,
        )
        for m in table_re.finditer(content):
            prop = m.group(1).split(".")[-1]
            _record(prop, m.group(2))

        # Strategy 2: fallback to Info-P016 per-line messages
        if not any(result[k] for k in ("pass", "trivially_true", "false")):
            p016_re = re.compile(
                r"Info-P016:\s*property\s+(checker_inst\.[\w.]+)\s+is\s+"
                r"(TRIVIALLY_TRUE|TRUE|FALSE)",
                re.IGNORECASE,
            )
            for m in p016_re.finditer(content):
                prop = m.group(1).split(".")[-1]
                _record(prop, m.group(2).upper())

        # Strategy 3: fallback to Info-P014 intermediate results
        if not any(result[k] for k in ("pass", "trivially_true", "false")):
            p014_re = re.compile(
                r"Info-P014:\s*property\s+(false|true):\s+(checker_inst\.[\w.]+)",
                re.IGNORECASE,
            )
            for m in p014_re.finditer(content):
                prop = m.group(2).split(".")[-1]
                status = "FALSE" if m.group(1).lower() == "false" else "TRUE"
                _record(prop, status)

        return result

    def validate_log_has_results(self, log_content: str) -> bool:
        return bool(re.search(
            r"Info-P016:\s*property .* is (?:TRIVIALLY_)?(?:TRUE|FALSE)", 
            log_content,
            re.IGNORECASE
        ))

    def extract_blackbox_count(self, log_content: str) -> int:
        blackbox_stats = re.search(r"blackboxes\s*:\s*(\d+)", log_content, re.IGNORECASE)
        if blackbox_stats:
            return int(blackbox_stats.group(1))
        return 0

    def required_script_commands(self) -> List[str]:
        return ["read_design", "prove", "def_clk", "def_rst"]

    def parse_coverage(self, tests_dir: str) -> dict:
        empty = {"covered": 0, "total": 0, "pct": 0.0}
        result = {
            "inputs": dict(empty), "outputs": dict(empty),
            "dffs": dict(empty), "nets": dict(empty),
            "uncovered": [],
            "overall_pct": 0.0
        }
        fanin_path = self.coverage_report_path(tests_dir)
        if not fanin_path or not os.path.exists(fanin_path):
            return result

        with open(fanin_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        _METRIC_RE = re.compile(
            r'(Inputs?|Outputs?|Dffs?|Nets?)\s*:\s*(\d+)\s*/\s*(\d+)\s+(\d+(?:\.\d+)?)%',
            re.IGNORECASE
        )
        _NAME_MAP = {
            'input': 'inputs', 'inputs': 'inputs',
            'output': 'outputs', 'outputs': 'outputs',
            'dff': 'dffs', 'dffs': 'dffs',
            'net': 'nets', 'nets': 'nets',
        }

        for m in _METRIC_RE.finditer(content):
            key = _NAME_MAP.get(m.group(1).lower())
            if key:
                pct = float(m.group(4))
                result[key] = {
                    "covered": int(m.group(2)),
                    "total":   int(m.group(3)),
                    "pct":     pct
                }
                # Assign overall_pct from nets generally or take the minimum
                if key == "nets":
                    result["overall_pct"] = pct

        result["uncovered"] = re.findall(r'^\s*-\s+(\S+)', content, re.MULTILINE)
        return result
