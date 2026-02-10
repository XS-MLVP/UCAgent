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

class EnvironmentIterationChecker(Checker):
    """
    整合的环境迭代检查器，用于 environment_debugging_iteration 阶段。
    功能包括：
    1. 失败分类 (FailureClassification)
    2. 环境质量检查 (EnvironmentQuality)
    3. 综合诊断和修复建议
    """
    def __init__(self, log_file, checker_file, **kwargs):
        self.log_file = log_file
        self.checker_file = checker_file
    
    def _parse_log_failures(self, log_content: str) -> dict:
        """Parse avis.log to extract failure information."""
        failures = {
            'trivially_true': [],
            'false_properties': [],
            'cover_failures': [],
            'environment_issues': [],
            'rtl_defects': []
        }
        
        # Extract TRIVIALLY_TRUE properties
        trivial_matches = re.findall(r'property\s+([\w_.]+)\s+is\s+TRIVIALLY_TRUE', log_content)
        failures['trivially_true'] = trivial_matches
        
        # Extract FALSE properties
        false_matches = re.findall(r'property\s+([\w_.]+)\s+is\s+FALSE', log_content)
        failures['false_properties'] = false_matches
        
        # Extract summary table
        summary_section = re.search(r'Active assertions:.*?Verification status:', log_content, re.DOTALL)
        if summary_section:
            summary = summary_section.group()
            # Parse each line: property_name : status
            for line in summary.split('\n'):
                match = re.search(r'(\S+)\s+:\s+(Pass|Fail|TrivT)', line)
                if match:
                    prop_name, status = match.groups()
                    if status == 'TrivT':
                        if prop_name not in failures['trivially_true']:
                            failures['trivially_true'].append(prop_name)
                    elif status == 'Fail':
                        if prop_name not in failures['false_properties']:
                            failures['false_properties'].append(prop_name)
        
        # Extract cover results
        cover_summary = re.findall(r'([\w_.]+COVER)\s+:\s+(Pass|Fail)', log_content)
        for name, status in cover_summary:
            if status == 'Fail':
                failures['cover_failures'].append(name)
        
        return failures
    
    def _classify_failure(self, prop_name: str, checker_content: str, log_content: str) -> str:
        """
        Classify a failure as 'environment' or 'rtl_defect'.
        
        环境问题的明确标准：
        1. TRIVIALLY_TRUE：过约束，属性无法被触发
        2. assume property失败：约束本身不满足
        
        RTL缺陷的明确标准：
        1. assert property失败且有合理反例
        2. Cover失败：可能是环境问题，但更可能是RTL设计缺陷导致状态不可达
        """
        # Check if it's already marked as TRIVIALLY_TRUE
        if re.search(rf'{prop_name}\s+is\s+TRIVIALLY_TRUE', log_content):
            return 'environment'
        
        # Check if this is an assume property
        if re.search(rf'{prop_name}\s*:\s*assume\s+property', checker_content):
            return 'environment'
        
        # Cover失败：不再默认当作环境问题
        # 因为Cover失败往往是因为RTL设计缺陷导致某些状态无法达到
        # 只有在明确检测到约束问题时才归类为环境问题
        
        # Default: assume it's an RTL defect if it has a reasonable failure
        return 'rtl_defect'
    
    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """
        执行综合的环境迭代检查。
        返回：成功时通过，失败时提供详细的诊断和修复建议。
        """
        log_path = self.get_path(self.log_file)
        checker_path = self.get_path(self.checker_file)
        
        if not os.path.exists(log_path):
            return False, {"error": f"Log file '{self.log_file}' not found."}
        
        if not os.path.exists(checker_path):
            return False, {"error": f"Checker file '{self.checker_file}' not found."}
        
        with open(log_path, 'r', encoding='utf-8') as f:
            log_content = f.read()
        
        with open(checker_path, 'r', encoding='utf-8') as f:
            checker_content = f.read()
        
        # Step 1: Parse and classify failures
        failures = self._parse_log_failures(log_content)
        
        # Classify each false property
        for prop in failures['false_properties']:
            classification = self._classify_failure(prop, checker_content, log_content)
            if classification == 'environment':
                failures['environment_issues'].append(prop)
            else:
                failures['rtl_defects'].append(prop)
        
        # All TRIVIALLY_TRUE are environment issues
        failures['environment_issues'].extend(failures['trivially_true'])
        failures['environment_issues'] = list(set(failures['environment_issues']))
        
        # Step 2: Environment quality checks
        issues = []
        suggestions = []
        
        # Check 1: TRIVIALLY_TRUE (过约束) - 但需要验证属性是否真的存在于代码中
        active_trivial_props = []
        for prop in failures['trivially_true']:
            # 提取属性名（去掉checker_inst.前缀）
            prop_short = prop.replace('checker_inst.', '')
            # 检查属性是否在checker代码中存在且未被注释
            # 匹配: prop_name: assert/assume property
            pattern = rf'{prop_short}\s*:\s*(assert|assume)\s+property'
            if re.search(pattern, checker_content):
                active_trivial_props.append(prop)
        
        if active_trivial_props:
            issues.append(
                f"❌ 发现 {len(active_trivial_props)} 个 TRIVIALLY_TRUE 属性（过约束）"
            )
            suggestions.append(
                "- 检查并放松过强的 assume 约束\n"
                "- 确认约束之间没有冲突\n"
                f"- 问题属性: {', '.join([p.replace('checker_inst.', '') for p in active_trivial_props[:3]])}"
                + ("..." if len(active_trivial_props) > 3 else "")
            )
        
        # Check 2: fv_idx约束 - 只在真正使用fv_idx时才检查
        # 检查wrapper中是否定义了fv_idx信号（未被注释）
        has_fv_idx_signal = False
        try:
            wrapper_file = self.checker_file.replace('_checker.sv', '_wrapper.sv')
            wrapper_path = self.get_path(wrapper_file)
            if os.path.exists(wrapper_path):
                with open(wrapper_path, 'r', encoding='utf-8') as f:
                    wrapper_content = f.read()
                # 检查是否有活跃的fv_idx定义（未被注释）
                if re.search(r'^\s*input\s+.*fv_idx', wrapper_content, re.MULTILINE):
                    has_fv_idx_signal = True
        except:
            pass
        
        if has_fv_idx_signal:
            # 只在真正使用fv_idx时才检查约束
            has_stable = bool(re.search(r'M_CK_FV_IDX_STABLE.*assume.*\$stable\(fv_idx\)', checker_content, re.DOTALL))
            has_valid = bool(re.search(r'M_CK_FV_IDX_VALID.*assume.*fv_idx\s*<', checker_content, re.DOTALL))
            has_known = bool(re.search(r'M_CK_FV_IDX_KNOWN.*assume.*\$isunknown\(fv_idx\)', checker_content, re.DOTALL))
            
            if not (has_stable and has_valid and has_known):
                issues.append("⚠️  检测到 fv_idx 符号化索引，但缺少必要约束")
                missing = []
                if not has_stable: missing.append("M_CK_FV_IDX_STABLE")
                if not has_valid: missing.append("M_CK_FV_IDX_VALID")
                if not has_known: missing.append("M_CK_FV_IDX_KNOWN")
                suggestions.append(
                    f"- 添加缺失的 fv_idx 约束: {', '.join(missing)}\n"
                    "- 参考模板添加三个强制约束防止假阳性"
                )
        
        # Step 3: Generate result
        total_failures = len(failures['false_properties']) + len(failures['trivially_true'])
        
        if issues:
            error_msg = f"🔍 环境迭代检查发现 {len(issues)} 类问题需要修复\n\n"
            error_msg += "**问题列表:**\n" + "\n".join([f"{i+1}. {issue}" for i, issue in enumerate(issues)])
            error_msg += "\n\n**修复建议:**\n" + "\n".join(suggestions)
            error_msg += f"\n\n**统计信息:**\n"
            error_msg += f"- 真实环境问题: {len(active_trivial_props)} 个\n"
            error_msg += f"- 疑似RTL缺陷: {len(failures['rtl_defects'])} 个\n"
            error_msg += f"- Cover失败: {len(failures['cover_failures'])} 个 (可能由RTL缺陷导致)\n"
            error_msg += f"- 总失败数: {total_failures} 个\n"
            error_msg += f"\n**注意:** Cover属性失败不一定是环境问题，可能是RTL缺陷导致状态不可达。"
            
            return False, {
                "error": error_msg,
                "environment_issues": active_trivial_props,
                "rtl_defects": failures['rtl_defects'],
                "trivially_true": active_trivial_props,
                "cover_failures": failures['cover_failures']
            }
        
        # All checks passed
        success_msg = "✅ 验证环境质量检查通过\n\n"
        success_msg += f"- 无活跃的 TRIVIALLY_TRUE 属性\n"
        success_msg += f"- 环境约束合理\n"
        if has_fv_idx_signal:
            success_msg += f"- 符号化索引约束完整\n"
        success_msg += f"- 检测到RTL缺陷: {len(failures['rtl_defects'])} 个（将在下阶段分析）\n"
        success_msg += f"- Cover失败: {len(failures['cover_failures'])} 个（可能由RTL缺陷导致）"
        
        return True, {
            "message": success_msg,
            "rtl_defects": failures['rtl_defects'],
            "cover_failures": failures['cover_failures'],
            "environment_quality": "excellent"
        }


class BugReportConsistencyChecker(Checker):
    def __init__(self, dut_name, property_file, bug_report_file, log_file=None, tracking_doc=None, **kwargs):
        self.dut_name = dut_name
        self.property_file = property_file
        self.bug_report_file = bug_report_file
        self.log_file = log_file if log_file else f"avis/{self.dut_name}.log"
        self.tracking_doc = tracking_doc

    def _parse_tracking_doc(self, doc_path):
        """解析跟踪文档，提取标记为 RTL缺陷 的属性列表"""
        if not os.path.exists(doc_path):
            return []
        
        with open(doc_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        rtl_defects = []
        # 匹配格式：## [ENV-XXX] 属性名：YYY
        issue_pattern = r'##\s*\[ENV-\d+\]\s*属性名[：:]\s*(\S+)(.*?)(?=##\s*\[ENV-|\Z)'
        issues = re.findall(issue_pattern, content, re.DOTALL)
        
        for prop_name, issue_content in issues:
            # 检查问题分类是否为 RTL缺陷
            classification_match = re.search(r'\*\*问题分类\*\*[：:]\s*(\S+)', issue_content)
            if classification_match and classification_match.group(1).strip() == 'RTL缺陷':
                rtl_defects.append(prop_name.strip())
        
        return rtl_defects
    
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
        验证 bug report 与 RTL 缺陷的一致性。
        优先从 environment_issues_tracking.md 获取 RTL 缺陷列表，
        如果跟踪文档不存在，则从日志文件提取失败属性。
        """
        # 尝试从跟踪文档获取 RTL 缺陷列表
        rtl_defects_from_tracking = []
        if self.tracking_doc:
            tracking_path = self.get_path(self.tracking_doc)
            rtl_defects_from_tracking = self._parse_tracking_doc(tracking_path)
        
        # 如果跟踪文档中有 RTL 缺陷记录，使用它作为验证依据
        if rtl_defects_from_tracking:
            failed_properties = rtl_defects_from_tracking
            info(f"从跟踪文档中提取到 {len(failed_properties)} 个 RTL 缺陷")
        else:
            # 回退到从日志文件提取（保持向后兼容）
            log_path = self.get_path(self.log_file)
            if not os.path.exists(log_path):
                return False, {"error": f"Log file '{self.log_file}' not found. The previous stage should have generated it."}
            
            with open(log_path, 'r', encoding='utf-8') as f:
                log_content = f.read()
            
            # Only look for actual FALSE properties, excluding TRIVIALLY_TRUE
            failed_properties = []
            summary_section = re.search(r'Active assertions:.*?Verification status:', log_content, re.DOTALL)
            if summary_section:
                summary = summary_section.group()
                for line in summary.split('\n'):
                    match = re.search(r'(\S+)\s+:\s+Fail', line)
                    if match:
                        prop_name = match.group(1)
                        failed_properties.append(prop_name)
            
            info(f"从日志文件中提取到 {len(failed_properties)} 个失败属性")
        
        if not failed_properties:
            return True, "No RTL defect failures found in the log file. Nothing to report."

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
        
        # 修改正则以支持带点号的属性名（如 checker_inst.A_CK_XXX）
        # 使用 [\w.]+ 而不是 \w+ 来匹配包含点号的属性名
        report_sections = re.split(r'##\s*❌?\s*Failed Property:\s*`?([\w.]+)`?', bug_report_content)
        
        if len(report_sections) <= 1:
             return False, {"error": "Bug report is not in the expected format. Could not find any sections like '## Failed Property: `prop_name`'."}

        reported_props_map = {}
        for i in range(1, len(report_sections), 2):
            prop_name_from_report = report_sections[i]
            section_content = report_sections[i+1]
            # 尝试多种格式提取 CK 标签
            # 格式1: **Checklist Item:** `CK_XXX`
            # 格式2: **属性名称**：A_CK_XXX (CK_XXX)
            ck_label = None
            match = re.search(r'\*\*Checklist Item:\*\*\s*`(.+?)`', section_content)
            if match:
                ck_label = match.group(1)
            else:
                # 尝试从属性名称字段提取
                match = re.search(r'\*\*属性名称\*\*[：:]\s*\S+\s*\(([^)]+)\)', section_content)
                if match:
                    ck_label = match.group(1)
            
            # 即使没有找到 CK 标签，也记录属性（用于检查是否有记录）
            reported_props_map[prop_name_from_report] = ck_label

        normalized_true_ck_map = {p.replace('assert_',''): ck for p, ck in true_ck_map.items()}

        for prop_from_report, reported_ck in reported_props_map.items():
            norm_prop_from_report = prop_from_report.replace('assert_','')
            if norm_prop_from_report not in normalized_true_ck_map:
                inconsistencies.append(f"Bug report documents property '{prop_from_report}', but it did not appear in the verification failure log.")
            elif reported_ck and normalized_true_ck_map.get(norm_prop_from_report) and normalized_true_ck_map.get(norm_prop_from_report) != reported_ck:
                 inconsistencies.append(f"Inconsistency for property '{prop_from_report}': Log implies CK is '{normalized_true_ck_map.get(norm_prop_from_report)}', but bug report states '{reported_ck}'.")

        for true_prop in true_ck_map:
            # 提取属性的短名称（去除模块实例前缀）
            # 例如：Adder_checker_inst.A_CK_ADD_OVERFLOW -> A_CK_ADD_OVERFLOW
            short_prop = true_prop.split('.')[-1] if '.' in true_prop else true_prop
            short_prop = short_prop.replace('assert_', '')
            
            # 检查是否在 bug report 中记录
            found = False
            for reported_prop in reported_props_map.keys():
                if reported_prop == short_prop or reported_prop.replace('assert_', '') == short_prop:
                    found = True
                    break
            
            if not found:
                inconsistencies.append(f"Failure for property '{true_prop}' is present in the log but not documented in the bug report.")

        if inconsistencies:
            return False, {
                "error": "Bug report is inconsistent with the verification results.",
                "details": inconsistencies
            }

        return True, "Bug report is consistent with all RTL defect failures found in the log."


class ScriptGenerationChecker(Checker):
    """
    整合的脚本生成检查器，用于 script_generation 阶段。
    按顺序执行：
    1. FormalScriptChecker - TCL脚本语法检查
    2. PropertyStructureChecker - 属性结构检查
    3. TclExecutionChecker - TCL脚本执行验证
    """
    def __init__(self, dut_name, property_file, spec_file, script_file, tcl_script, **kwargs):
        self.dut_name = dut_name
        self.property_file = property_file
        self.spec_file = spec_file
        self.script_file = script_file
        self.tcl_script = tcl_script
    
    def do_check(self, timeout=300, **kwargs) -> tuple[bool, object]:
        """执行三阶段综合检查"""
        
        # Stage 1: Formal Script Check
        info("📝 Stage 1/3: 检查TCL脚本语法...")
        script_checker = FormalScriptChecker(self.script_file)
        script_checker.get_path = self.get_path
        success, result = script_checker.do_check(timeout)
        
        if not success:
            return False, {
                "error": "❌ Stage 1/3 失败: TCL脚本检查未通过",
                "details": result
            }
        
        info(f"✅ Stage 1/3 通过: {result}")
        
        # Stage 2: Property Structure Check
        info("🔍 Stage 2/3: 检查属性结构一致性...")
        prop_checker = PropertyStructureChecker(self.property_file, self.spec_file)
        prop_checker.get_path = self.get_path
        success, result = prop_checker.do_check(timeout)
        
        if not success:
            return False, {
                "error": "❌ Stage 2/3 失败: 属性结构检查未通过",
                "details": result
            }
        
        info(f"✅ Stage 2/3 通过: {result}")
        
        # Stage 3: TCL Execution Check
        info("🚀 Stage 3/3: 执行TCL脚本并验证...")
        exec_checker = TclExecutionChecker(self.tcl_script, self.dut_name)
        exec_checker.get_path = self.get_path
        success, result = exec_checker.do_check(timeout)
        
        if not success:
            return False, {
                "error": "❌ Stage 3/3 失败: TCL执行验证未通过",
                "details": result
            }
        
        info(f"✅ Stage 3/3 通过")
        
        return True, {
            "message": "✅ 脚本生成阶段所有检查通过",
            "details": result
        }


class EnvironmentDebuggingChecker(Checker):
    """
    环境调试检查器，用于 environment_debugging_iteration 阶段。
    
    新工作流程（LLM驱动）：
    1. 检查跟踪文档 environment_issues_tracking.md 是否存在
    2. 执行TCL脚本生成新的验证日志
    3. 解析跟踪文档，检查是否存在未修复的环境问题
    4. 通过条件：文档中没有【问题分类=环境问题 且 状态=待修复】的记录
    
    跟踪文档格式示例：
    ## [ENV-001] 属性名：CK_EXAMPLE
    - **状态**：待修复 / 已修复 / 待分析 / 已分类
    - **失败类型**：TRIVIALLY_TRUE / FAIL / UNREACHABLE
    - **问题分类**：环境问题 / RTL缺陷 / 待定
    - **分析说明**：...
    - **修复措施**：...
    """
    def __init__(self, dut_name, property_file, spec_file, log_file, checker_file, tcl_script, **kwargs):
        self.dut_name = dut_name
        self.property_file = property_file
        self.spec_file = spec_file
        self.log_file = log_file
        self.checker_file = checker_file
        self.tcl_script = tcl_script
    
    def _parse_tracking_doc(self, doc_path: str) -> tuple[list, list]:
        """
        解析跟踪文档，提取环境问题
        
        返回:
            (unresolved_env_issues, all_issues)
            - unresolved_env_issues: 【问题分类=环境问题 且 状态=待修复】的记录列表
            - all_issues: 所有问题记录列表
        """
        import re
        
        if not os.path.exists(doc_path):
            return [], []
        
        with open(doc_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 使用正则提取每个问题记录
        # 匹配格式：## [ENV-XXX] 属性名：...
        issue_pattern = r'##\s*\[ENV-\d+\]\s*属性名[：:]\s*(\S+)(.*?)(?=##\s*\[ENV-|\Z)'
        issues = re.findall(issue_pattern, content, re.DOTALL)
        
        all_issues = []
        unresolved_env_issues = []
        
        for prop_name, issue_content in issues:
            # 提取状态字段
            status_match = re.search(r'\*\*状态\*\*[：:]\s*(\S+)', issue_content)
            status = status_match.group(1).strip() if status_match else "未知"
            
            # 提取问题分类字段
            classification_match = re.search(r'\*\*问题分类\*\*[：:]\s*(\S+)', issue_content)
            classification = classification_match.group(1).strip() if classification_match else "未知"
            
            issue_info = {
                "property": prop_name.strip(),
                "status": status,
                "classification": classification,
                "content": issue_content.strip()
            }
            
            all_issues.append(issue_info)
            
            # 判断是否为未解决的环境问题
            # 条件：状态=待修复 且 问题分类=环境问题
            if status == "待修复" and classification == "环境问题":
                unresolved_env_issues.append(issue_info)
        
        return unresolved_env_issues, all_issues
    
    def do_check(self, timeout=300, **kwargs) -> tuple[bool, object]:
        """执行环境调试检查"""
        
        # Step 1: 检查跟踪文档是否存在
        # 基于 log_file 路径构造跟踪文档路径
        log_dir = os.path.dirname(self.get_path(self.log_file))
        tracking_doc = os.path.join(log_dir, "environment_issues_tracking.md")
        
        if not os.path.exists(tracking_doc):
            return False, {
                "error": "❌ 跟踪文档不存在",
                "missing_file": tracking_doc,
                "suggestion": (
                    "请创建跟踪文档 environment_issues_tracking.md 并记录所有失败属性：\n"
                    "1. 读取 avis.log 提取所有失败属性\n"
                    "2. 为每个失败创建一条记录，格式：\n"
                    "   ## [ENV-001] 属性名：CK_XXX\n"
                    "   - **状态**：待分析\n"
                    "   - **失败类型**：TRIVIALLY_TRUE/FAIL/...\n"
                    "   - **问题分类**：待定\n"
                    "   - **分析说明**：（待LLM分析）\n"
                    "   - **修复措施**：（待确定）\n"
                )
            }
        
        info(f"✅ 跟踪文档存在: {tracking_doc}")
        
        # Step 2: 执行TCL脚本生成新的验证日志
        info("🚀 执行TCL脚本，生成最新验证日志...")
        exec_checker = TclExecutionChecker(self.tcl_script, self.dut_name)
        exec_checker.get_path = self.get_path
        exec_success, exec_result = exec_checker.do_check(timeout)
        
        if not exec_success:
            return False, {
                "error": "❌ TCL脚本执行失败",
                "details": exec_result,
                "suggestion": "请检查TCL脚本和checker/wrapper文件是否有语法错误"
            }
        
        info(f"✅ TCL执行成功，日志已生成")
        
        # Step 3: 解析跟踪文档
        info("🔍 解析跟踪文档，检查未修复的环境问题...")
        unresolved_issues, all_issues = self._parse_tracking_doc(tracking_doc)
        
        # Step 4: 判断是否通过
        if len(unresolved_issues) > 0:
            # 存在未修复的环境问题
            issue_list = "\n".join([
                f"  - [{issue['property']}] 状态={issue['status']}, 分类={issue['classification']}"
                for issue in unresolved_issues
            ])
            
            return False, {
                "error": f"❌ 存在 {len(unresolved_issues)} 个未修复的环境问题",
                "unresolved_issues": unresolved_issues,
                "details": f"以下环境问题需要修复：\n{issue_list}",
                "next_steps": (
                    "请继续环境调试流程：\n"
                    "1. 分析每个未修复的环境问题\n"
                    "2. 修改 checker.sv 或 wrapper.sv\n"
                    "3. 重新生成TCL脚本\n"
                    "4. 再次运行Check工具\n"
                    "5. 根据新日志更新跟踪文档中的状态"
                ),
                "tracking_doc_path": tracking_doc,
                "total_issues": len(all_issues),
                "unresolved_count": len(unresolved_issues)
            }
        
        # 所有环境问题已修复
        resolved_count = sum(1 for issue in all_issues 
                           if issue['status'] == '已修复' and issue['classification'] == '环境问题')
        rtl_issues_count = sum(1 for issue in all_issues 
                             if issue['classification'] == 'RTL缺陷')
        
        return True, {
            "message": "✅ 环境调试阶段检查通过",
            "summary": f"所有环境问题已修复，可以进入RTL缺陷分析阶段",
            "statistics": {
                "total_issues": len(all_issues),
                "resolved_env_issues": resolved_count,
                "rtl_defects": rtl_issues_count,
                "unresolved_env_issues": 0
            },
            "tracking_doc_path": tracking_doc,
            "details": f"共记录 {len(all_issues)} 个问题，其中环境问题已全部修复"
        }
