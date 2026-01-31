#coding=utf-8
import os
import re
import glob
import subprocess
import pyslang
from ucagent.checkers.base import Checker
from ucagent.util.log import info, warning
import psutil

class FormalAnalysisChecker(Checker):
    def __init__(self, analysis_file, **kwargs):
        self.analysis_file = analysis_file

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Checks the formal analysis file for required keywords."""
        path = self.get_path(self.analysis_file)
        if not os.path.exists(path):
            return False, {"error": f"Formal analysis file {self.analysis_file} not found."}
        
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        required_keywords = ["验证目标", "验证范围", "属性", "FormalMC"]
        missing = [k for k in required_keywords if k not in content]
        
        if missing:
            return False, {"error": f"Formal analysis file missing keywords: {missing}"}
            
        return True, "Formal analysis file check passed."

class PropertyStructureChecker(Checker):
    def __init__(self, property_file, spec_file=None, **kwargs):
        self.property_file = property_file
        self.spec_file = spec_file

    def _extract_property_details(self, file_path: str) -> dict:
        """
        Extract property details including names, content, and instantiation type.
        Returns: { 'CK_NAME': {'body': '...', 'type': 'assert|assume|cover'} }
        """
        details = {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 1. Extract property blocks: property NAME; ... endproperty
            prop_blocks = re.findall(r'property\s+(CK_[A-Za-z0-9_]+)\s*;(.*?)\bendproperty', content, re.DOTALL)
            for name, body in prop_blocks:
                details[name] = {'body': body, 'type': None}

            # 2. Extract instantiation statements: label: (assert|assume|cover) property (NAME);
            stmt_matches = re.findall(r'(\w+)\s*:\s*(assert|assume|cover)\s+property\s*\((CK_[A-Za-z0-9_]+)\)', content)
            for inst_label, p_type, prop_name in stmt_matches:
                if prop_name in details:
                    details[prop_name]['type'] = p_type
                else:
                    # Direct definition in assert/assume/cover without separate property block
                    details[prop_name] = {'body': '', 'type': p_type}
            
            return details
        except Exception:
            return {}

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Performs structured validation of SVA properties against spec requirements."""
        prop_path = self.get_path(self.property_file)
        if not os.path.exists(prop_path):
            return False, {"error": f"Property file {self.property_file} not found."}

        # Parse Property Implementation
        implemented_map = self._extract_property_details(prop_path)
        if not implemented_map:
            return False, {"error": "No SVA properties (CK_...) found in implementation file."}

        if not self.spec_file:
            return True, f"Found {len(implemented_map)} properties. No spec file provided for consistency check."

        spec_path = self.get_path(self.spec_file)
        if not os.path.exists(spec_path):
            return False, {"error": f"Spec file {self.spec_file} not found."}

        # Parse Spec Requirements
        with open(spec_path, 'r', encoding='utf-8') as f:
            spec_content = f.read()
        
        # Regex to find: <CK_NAME> (Style: STYLE_STR), allowing optional markdown bold/italic markers
        spec_items = re.findall(r'<(CK_[A-Za-z0-9_]+)>\s*[\*_]*\((Style:\s*[^)]+)\)[\*_]*', spec_content)
        if not spec_items:
            return False, {"error": f"No valid CK tags with (Style: ...) found in spec file {self.spec_file}."}

        errors = []
        warnings = []
        
        for ck_name, style_str in spec_items:
            style = style_str.lower()
            
            # Check for Existence
            if ck_name not in implemented_map:
                errors.append(f"Missing implementation for '{ck_name}' ({style_str})")
                continue
            
            impl = implemented_map[ck_name]
            
            # 1. Check Keyword Consistency (Type Check)
            if 'assume' in style and impl['type'] != 'assume':
                errors.append(f"'{ck_name}' is marked as 'Assume' in spec, but implemented as '{impl['type'] or 'unknown'}'")
            elif 'cover' in style and impl['type'] != 'cover':
                errors.append(f"'{ck_name}' is marked as 'Cover' in spec, but implemented as '{impl['type'] or 'unknown'}'")
            elif ('comb' in style or 'seq' in style) and impl['type'] not in ['assert', None]:
                # If it's Comb/Seq but uses assume/cover, it's an error
                if impl['type'] in ['assume', 'cover']:
                    errors.append(f"'{ck_name}' is marked as assertion style ({style_str}), but implemented as '{impl['type']}'")

            # 2. Check Symbolic Indexing Usage (Advanced Feature Check)
            if 'symbolic' in style:
                # Must use fv_idx or fv_mon_
                if not re.search(r'fv_(idx|mon_)', impl['body']):
                    errors.append(f"'{ck_name}' is marked as 'Symbolic', but its implementation does not use 'fv_idx' or 'fv_mon_' signals.")

            # 3. Placeholder Detection (Quality Check)
            if re.search(r'\|->\s*(1\'b1|1|true)\s*;', impl['body']):
                warnings.append(f"'{ck_name}' implementation appears to be a vacuous placeholder (... |-> 1'b1).")

        if errors:
            error_msg = f"Property Structure Consistency Check Failed for '{self.property_file}':\n"
            error_msg += "\n".join([f"  [ERROR] {e}" for e in errors])
            if warnings:
                error_msg += "\n" + "\n".join([f"  [WARN]  {w}" for w in warnings])
            return False, {"error": error_msg}

        success_msg = f"All {len(spec_items)} CKs from spec are correctly implemented."
        if warnings:
            success_msg += "\nWarnings:\n" + "\n".join([f"  - {w}" for w in warnings])
        
        return True, success_msg

class EnvSyntaxChecker(Checker):
    def __init__(self, env_file, **kwargs):
        self.env_file = env_file

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Checks the environment file for valid SystemVerilog module syntax."""
        path = self.get_path(self.env_file)
        if not os.path.exists(path):
            return False, {"error": f"Environment file {self.env_file} not found."}

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        if "module" not in content or "endmodule" not in content:
            return False, {"error": "Environment file does not look like a valid SystemVerilog module."}

        if "bind" not in content and "bind" not in self.env_file:
             pass

        return True, "Environment syntax check passed."

class WrapperTimingChecker(Checker):
    def __init__(self, wrapper_file, rtl_path, **kwargs):
        self.wrapper_file = wrapper_file
        self.rtl_path = rtl_path

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Checks if wrapper includes clk and rst_n for formal verification."""
        wrapper_path = self.get_path(self.wrapper_file)
        if not os.path.exists(wrapper_path):
            return False, {"error": f"Wrapper file {self.wrapper_file} not found."}

        # Read wrapper content
        with open(wrapper_path, 'r', encoding='utf-8') as f:
            wrapper_content = f.read()

        errors = []

        # Check if wrapper has clk and rst_n
        if not re.search(r'input\s+clk', wrapper_content):
            errors.append("Wrapper must include 'input clk' for formal verification.")

        if not re.search(r'input\s+rst_n', wrapper_content):
            errors.append("Wrapper must include 'input rst_n' for formal verification.")

        if errors:
            error_msg = "Wrapper timing check failed:\n" + "\n".join(f"  - {e}" for e in errors)
            return False, {"error": error_msg}

        return True, "Wrapper timing check passed. Wrapper includes clk and rst_n for formal verification."

class FormalScriptChecker(Checker):
    def __init__(self, script_file, **kwargs):
        self.script_file = script_file

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Checks the formal script for required commands."""
        path = self.get_path(self.script_file)
        if not os.path.exists(path):
            return False, {"error": f"Formal script file {self.script_file} not found."}
            
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        required_cmds = ["read_design", "prove", "def_clk", "def_rst"]
        missing = [k for k in required_cmds if k not in content]
        
        if missing:
            return False, {"error": f"Formal script missing commands: {missing}"}

        return True, "Formal script check passed."

class TclExecutionChecker(Checker):
    def __init__(self, tcl_script, dut_name, **kwargs):
        self.tcl_script = tcl_script
        self.dut_name = dut_name

    def do_check(self, timeout=300, **kwargs) -> tuple[bool, object]:
        """
        Runs the TCL script using FormalMC and checks the output log for failures.
        The command is executed in the same directory as the tcl script.
        """
        tcl_path = self.get_path(self.tcl_script)
        if not os.path.exists(tcl_path):
            return False, {"error": f"TCL script not found at '{self.tcl_script}'. Cannot run verification."}

        # Use the TCL script's directory as the execution and work directory
        exec_dir = os.path.dirname(tcl_path)
        
        # The log file is now relative to the execution directory
        log_file_name = "avis.log"
        log_path = os.path.join(exec_dir, log_file_name)
        
        # The -work_dir argument tells FormalMC where to place its output files.
        cmd = ["FormalMC", "-f", tcl_path, "-override", "-work_dir", exec_dir]
        info(f"Running command: {' '.join(cmd)} in directory {exec_dir}")

        stdout_log = ""
        stderr_log = ""
        try:
            worker = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=exec_dir # Execute from the script's directory
            )
            self.set_check_process(worker, timeout)
            stdout_log, stderr_log = worker.communicate(timeout=timeout)

            if worker.returncode != 0:
                return False, {
                    "error": f"FormalMC execution failed with return code {worker.returncode}.",
                    "details": "This might indicate an issue with the tool, script, or environment.",
                    "stdout": stdout_log,
                    "stderr": stderr_log
                }

        except FileNotFoundError:
            return False, {"error": "The 'FormalMC' command was not found. Please ensure it is installed and in your PATH."}
        except subprocess.TimeoutExpired:
            try:
                worker.terminate()
                _, alive = psutil.wait_procs([worker], timeout=3)
                if alive: worker.kill()
            except Exception as ex:
                warning(f"Error terminating process after timeout: {ex}")
            stdout_log, stderr_log = worker.communicate()
            return False, {
                "error": f"Formal verification timed out after {timeout} seconds.",
                "stdout": stdout_log,
                "stderr": stderr_log
            }
        
        # --- Analyze the log to see if verification ran and produced results ---
        if not os.path.exists(log_path):
            return False, {"error": f"Log file '{log_file_name}' was not generated in '{os.path.dirname(self.tcl_script)}' by the verification run."}
        
        with open(log_path, 'r', encoding='utf-8') as f:
            log_content = f.read()

        # Check for non-zero blackboxes in log statistics
        # Pattern matches "blackboxes : N" where N > 0
        blackbox_stats = re.search(r"blackboxes\s*:\s*(\d+)", log_content, re.IGNORECASE)
        if blackbox_stats:
            count = int(blackbox_stats.group(1))
            if count > 0:
                return False, {
                    "error": f"Design contains {count} blackboxes which is not allowed for complete formal verification.",
                    "details": "The log file indicates that some modules were treated as blackboxes. Please modify your formal TCL script to ensure all RTL files are correctly included and correctly identified.",
                    "stdout": stdout_log,
                    "stderr": stderr_log
                }
        elif "blackbox" in log_content.lower():
             # If summary stats are missing but "blackbox" keyword appears, it might be an error.
             # But we must be careful not to match benign text. 
             # Given the tool produces a summary table, we largely rely on that. 
             # Only fail if we are sure it's not a false positive.
             pass

        # Per user request, check passes if ANY result is found, indicating a successful run.
        if re.search(r"Info-P016: property .* is (?:TRIVIALLY_)?(?:TRUE|FALSE)", log_content):
            failed_properties = re.findall(r"Info-P016: property ([\w_.]+) is (?:TRIVIALLY_)?FALSE", log_content)
            if failed_properties:
                return True, {
                    "message": f"Verification run completed, but {len(failed_properties)} properties failed. This check passes as the script executed correctly.",
                    "details": "The next stage will involve analyzing these failures.",
                    "failed_properties": failed_properties
                }
            else:
                 return True, "Verification run completed successfully. All properties passed."
        
        # If no TRUE or FALSE results, it's a failure of the run itself.
        return False, {
            "error": "TCL script execution failed to produce results.",
            "details": "The log file was generated, but it contains no conclusive '... is TRUE' or '... is FALSE' messages. This may indicate a syntax error in the SVA or TCL files that prevented the 'prove' command from completing.",
            "stdout": stdout_log,
            "stderr": stderr_log
        }

class BugReportConsistencyChecker(Checker):
    def __init__(self, dut_name, property_file, bug_report_file, log_file=None, **kwargs):
        self.dut_name = dut_name
        self.property_file = property_file
        self.bug_report_file = bug_report_file
        self.log_file = log_file if log_file else f"avis/{self.dut_name}.log"

    def _get_ck_for_property(self, prop_name, prop_content_lines):
        """Finds the CK label associated with a given property name."""
        try:
            line_num = -1
            for i, line in enumerate(prop_content_lines):
                if re.search(r'\b' + prop_name + r'\b\s*:\s*assert', line):
                    line_num = i
                    break
            
            if line_num != -1:
                for i in range(line_num - 1, -1, -1):
                    match = re.search(r'//\s*<(CK-[\w-]+)>', prop_content_lines[i])
                    if match:
                        return match.group(1)
        except Exception:
            return None
        return None

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """
        Verifies that the bug report is consistent with the failures in the log file.
        """
        log_path = self.get_path(self.log_file)
        if not os.path.exists(log_path):
            return False, {"error": f"Log file '{self.log_file}' not found. The previous stage should have generated it."}
        
        with open(log_path, 'r', encoding='utf-8') as f:
            log_content = f.read()
        
        failed_properties = re.findall(r'^Fail:\s*(\w+)', log_content, re.MULTILINE)
        
        if not failed_properties:
            return True, "No failures found in the log file. Nothing to report."

        bug_report_path = self.get_path(self.bug_report_file)
        if not os.path.exists(bug_report_path):
            return False, {
                "error": "Verification failed, but the bug report file was not found.",
                "details": f"Please create or update '{self.bug_report_file}' to document the {len(failed_properties)} failed properties: {', '.join(failed_properties)}"
            }

        with open(bug_report_path, 'r', encoding='utf-8') as f:
            bug_report_content = f.read()
        
        with open(self.get_path(self.property_file), 'r', encoding='utf-8') as f:
            prop_content_lines = f.readlines()

        inconsistencies = []
        true_ck_map = {prop: self._get_ck_for_property(prop, prop_content_lines) for prop in failed_properties}
        
        report_sections = re.split(r'##\s*❌?\s*Failed Property:\s*`(\w+)`', bug_report_content)
        
        if len(report_sections) <= 1:
             return False, {"error": "Bug report is not in the expected format. Could not find any sections like '## Failed Property: `prop_name`'."}

        reported_props_map = {}
        for i in range(1, len(report_sections), 2):
            prop_name_from_report = report_sections[i]
            section_content = report_sections[i+1]
            match = re.search(r'\*\*Checklist Item:\*\*\s*`(.+?)`', section_content)
            if match:
                reported_props_map[prop_name_from_report] = match.group(1)

        normalized_true_ck_map = {p.replace('assert_',''): ck for p, ck in true_ck_map.items()}

        for prop_from_report, reported_ck in reported_props_map.items():
            norm_prop_from_report = prop_from_report.replace('assert_','')
            if norm_prop_from_report not in normalized_true_ck_map:
                inconsistencies.append(f"Bug report documents property '{prop_from_report}', but it did not appear in the verification failure log.")
            elif normalized_true_ck_map.get(norm_prop_from_report) != reported_ck:
                 inconsistencies.append(f"Inconsistency for property '{prop_from_report}': Log implies CK is '{normalized_true_ck_map.get(norm_prop_from_report)}', but bug report states '{reported_ck}'.")

        for true_prop in true_ck_map:
            if true_prop not in reported_props_map and true_prop.replace('assert_','') not in reported_props_map:
                inconsistencies.append(f"Failure for property '{true_prop}' is present in the log but not documented in the bug report.")

        if inconsistencies:
            return False, {
                "error": "Bug report is inconsistent with the verification results.",
                "details": inconsistencies
            }

        return True, "Bug report is consistent with all failures found in the log."
