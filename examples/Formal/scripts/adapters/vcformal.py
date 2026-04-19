# -*- coding: utf-8 -*-
import os
import re
from typing import Dict, List, Optional
from ..formal_adapter import FormalToolAdapter

class VCFormalAdapter(FormalToolAdapter):
    def tool_name(self) -> str:
        return "vcformal"

    def tool_display_name(self) -> str:
        return "Synopsys VC Formal"

    def log_filename(self) -> str:
        return "vcf.log"

    def coverage_report_path(self, tests_dir: str) -> Optional[str]:
        return None  # COI coverage is inline in vcf.log

    def build_command(self, tcl_path: str, exec_dir: str) -> List[str]:
        return ["vcf", "-f", tcl_path]

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

        # [Info] PROP_I_RESULT: FPV  Adder_wrapper.checker_inst.A_CK_CORE_ADD_RESULT  t1  proven  property  00:00:00
        # format: PROP_I_RESULT: FPV <full_name> <engine> <status> property
        vcf_prop_re = re.compile(
            r'\[Info\]\s+PROP_I_RESULT:\s+FPV\s+'
            r'(?:\S+\.checker_inst\.)?(\S+)\s+'
            r'(\S+)\s+'
            r'(proven|falsified(?::\d+)?|covered(?::\d+)?|uncoverable)\s+'
            r'property',
            re.IGNORECASE
        )

        for m in vcf_prop_re.finditer(content):
            prop = m.group(1)
            engine = m.group(2)
            status = m.group(3).lower()

            is_cov = prop.startswith("C_") or "COVER" in prop.upper()

            if status == "proven":
                if is_cov:
                    result["cover_pass"].append(prop)
                elif engine == "t1":
                    result["trivially_true"].append(prop)
                else:
                    result["pass"].append(prop)
            elif status.startswith("falsified"):
                if is_cov:
                    result["cover_fail"].append(prop)
                else:
                    result["false"].append(prop)
            elif status.startswith("covered"):
                result["cover_pass"].append(prop)
            elif status == "uncoverable":
                result["cover_fail"].append(prop)

        # Remove duplicates
        for key in result:
            result[key] = list(set(result[key]))

        return result

    def validate_log_has_results(self, log_content: str) -> bool:
        return bool(re.search(
            r'\[Info\]\s+PROP_I_RESULT:\s*FPV.*(?:proven|falsified|covered|uncoverable)\s+property',
            log_content,
            re.IGNORECASE
        ))

    def extract_blackbox_count(self, log_content: str) -> int:
        match = re.search(r'Number of Black-Box Instances\s*=\s*(\d+)', log_content)
        if match:
            return int(match.group(1))
        return 0

    def required_script_commands(self) -> List[str]:
        return ["read_file", "check_fv", "create_clock", "create_reset"]

    def parse_coverage(self, tests_dir: str) -> dict:
        result = {
            "overall_pct": 0.0,
            "uncovered": []
        }
        
        log_path = os.path.join(tests_dir, self.log_filename())
        if not os.path.exists(log_path):
            return result

        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Extract overall percentage
        pct_match = re.search(r'Overall coverage score:\s+(\d+(?:\.\d+)?)/100', content)
        if pct_match:
            result["overall_pct"] = float(pct_match.group(1))

        # Extract uncovered signals
        # Look for the section after `report_fv_coverage -list_uncovered`
        uncover_section_match = re.search(r'report_fv_coverage\s+-list_uncovered(.*?)(?:# =+|$)', content, re.DOTALL)
        if uncover_section_match:
            uncover_section = uncover_section_match.group(1)
            # Find words that might be signals, excluding comments or generic output
            # For VC Formal, they usually appear one per line.
            for line in uncover_section.split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("==="):
                    # Attempt to extract signal names, typical format either just signal name
                    parts = line.split()
                    if parts:
                        result["uncovered"].append(parts[0])

        return result
