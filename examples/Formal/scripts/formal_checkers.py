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
    """
    Bug 报告一致性检查器，用于 formal_execution 阶段。
    
    从 checker.sv 中提取所有标记 // [RTL_BUG] 的属性，
    验证 bug_report.md 中是否为每个 RTL 缺陷都创建了对应章节。
    """
    def __init__(self, dut_name, property_file, bug_report_file, log_file=None, **kwargs):
        self.dut_name = dut_name
        self.property_file = property_file
        self.bug_report_file = bug_report_file
        self.log_file = log_file if log_file else f"avis/{self.dut_name}.log"

    def _extract_rtl_defects_from_checker(self, checker_path: str) -> list:
        """
        从 checker.sv 中提取所有标记 [RTL_BUG] 的属性。
        
        格式：
        // [RTL_BUG] 描述...
        A_CK_XXX: assert property(...);
        
        返回：属性名列表
        """
        if not os.path.exists(checker_path):
            return []
        
        with open(checker_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        rtl_defects = []
        for i, line in enumerate(lines):
            # 查找 [RTL_BUG] 标记
            if '[RTL_BUG]' in line:
                # 在后续几行（最多5行）内查找属性定义
                for j in range(i, min(i + 6, len(lines))):
                    # 匹配 property_name: assert property(...) 或 assert property @(...) property_name
                    match = re.search(r'([A-Z_][A-Z0-9_]*)\s*:\s*assert\s+property', lines[j])
                    if match:
                        rtl_defects.append(match.group(1))
                        break
        
        return rtl_defects

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """
        验证 bug report 与 RTL 缺陷的一致性。
        从 checker.sv 中提取标记 [RTL_BUG] 的属性，
        验证 bug_report.md 是否为每个缺陷都创建了章节。
        """
        checker_path = self.get_path(self.property_file)
        
        # Step 1: 从 checker.sv 提取 RTL 缺陷
        rtl_defects = self._extract_rtl_defects_from_checker(checker_path)
        info(f"从 checker.sv 中提取到 {len(rtl_defects)} 个标记 [RTL_BUG] 的属性")
        
        if not rtl_defects:
            return True, {
                "message": "✅ 无 RTL 缺陷需要报告",
                "note": "checker.sv 中未找到任何标记 [RTL_BUG] 的属性"
            }

        # Step 2: 检查 bug report 是否存在
        bug_report_path = self.get_path(self.bug_report_file)
        if not os.path.exists(bug_report_path):
            return False, {
                "error": "❌ Bug 报告文件不存在",
                "details": f"请创建 '{self.bug_report_file}' 并为以下 {len(rtl_defects)} 个 RTL 缺陷编写报告：",
                "rtl_defects": rtl_defects
            }

        with open(bug_report_path, 'r', encoding='utf-8') as f:
            bug_report_content = f.read()
        
        # Step 3: 解析 bug report，提取已记录的属性
        # 支持多种格式：## Failed Property: `A_CK_XXX` 或 ## ❌ Failed Property: A_CK_XXX
        report_sections = re.split(r'##\s*❌?\s*Failed Property:\s*`?([\w.]+)`?', bug_report_content)
        
        if len(report_sections) <= 1:
            return False, {
                "error": "❌ Bug 报告格式不正确",
                "details": "未找到任何 '## Failed Property: `prop_name`' 格式的章节",
                "expected_format": "## Failed Property: `A_CK_XXX`"
            }

        reported_props = set()
        for i in range(1, len(report_sections), 2):
            prop_name = report_sections[i].strip()
            # 去除可能的模块前缀（checker_inst.A_CK_XXX -> A_CK_XXX）
            short_name = prop_name.split('.')[-1] if '.' in prop_name else prop_name
            reported_props.add(short_name)

        # Step 4: 对比 RTL 缺陷与 bug report
        missing_in_report = []
        for defect in rtl_defects:
            if defect not in reported_props:
                missing_in_report.append(defect)
        
        extra_in_report = []
        for reported in reported_props:
            if reported not in rtl_defects:
                extra_in_report.append(reported)

        # Step 5: 生成检查结果
        if missing_in_report or extra_in_report:
            issues = []
            if missing_in_report:
                issues.append(f"缺少报告的 RTL 缺陷 ({len(missing_in_report)} 个): {', '.join(missing_in_report)}")
            if extra_in_report:
                issues.append(f"报告中多余的属性 ({len(extra_in_report)} 个): {', '.join(extra_in_report)}")
            
            return False, {
                "error": "❌ Bug 报告与 RTL 缺陷不一致",
                "details": issues,
                "missing_in_report": missing_in_report,
                "extra_in_report": extra_in_report,
                "rtl_defects_total": len(rtl_defects)
            }

        return True, {
            "message": f"✅ Bug 报告一致性检查通过：{len(rtl_defects)} 个 RTL 缺陷均已记录",
            "rtl_defects": rtl_defects
        }


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


class CoverageAnalysisChecker(Checker):
    """
    覆盖率分析检查器，用于 coverage_analysis_and_optimization 阶段。

    仅解析 fanin.rep，提取四项 COI（Cone of Influence）覆盖率指标：
      Inputs / Outputs / Dffs / Nets
    其中 Dff COI（寄存器覆盖）和 Net COI（组合逻辑覆盖）是形式化验证中
    等价于仿真"行覆盖率"的指标，二者均需达到阈值。

    自动重跑逻辑：
      若 checker.sv 比 fanin.rep 更新（或 fanin.rep 不存在），
      自动重新执行 TCL 脚本以刷新覆盖率数据。

    fanin.rep 格式示例：
         Inputs :     3 / 3      100%
        Outputs :     4 / 4      100%
           Dffs :    10 / 10     100%
           Nets :    30 / 30     100%
    """
    def __init__(self, dut_name, fanin_rep, tcl_script, checker_file, coi_threshold=100.0, **kwargs):
        self.dut_name = dut_name
        self.fanin_rep = fanin_rep
        self.tcl_script = tcl_script
        self.checker_file = checker_file
        self.coi_threshold = float(coi_threshold)

    def _need_rerun(self, fanin_path: str, checker_path: str) -> tuple[bool, str]:
        """若 fanin.rep 不存在或 checker.sv 比它更新，则需要重新执行 TCL。"""
        if not os.path.exists(fanin_path):
            return True, "fanin.rep 不存在，需要执行 TCL 生成覆盖率报告"
        if os.path.exists(checker_path) and os.path.getmtime(checker_path) > os.path.getmtime(fanin_path):
            return True, "checker.sv 已更新（比 fanin.rep 新），需要重新执行验证"
        return False, "覆盖率报告已是最新，直接读取 fanin.rep"

    def _parse_fanin_report(self, fanin_path: str) -> dict:
        """
        解析 fanin.rep，提取全部 COI 覆盖率指标及未覆盖信号列表。

        返回:
          {
            "inputs":  {"covered": N, "total": N, "pct": N},
            "outputs": {...},
            "dffs":    {...},
            "nets":    {...},
            "uncovered": [signal, ...]   # fanin -list 中以 "- " 开头的行
          }
        """
        empty = {"covered": 0, "total": 0, "pct": 0.0}
        result = {
            "inputs": dict(empty), "outputs": dict(empty),
            "dffs": dict(empty), "nets": dict(empty),
            "uncovered": []
        }
        if not os.path.exists(fanin_path):
            return result

        with open(fanin_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        metric_re = re.compile(
            r'(Inputs?|Outputs?|Dffs?|Nets?)\s*:\s*(\d+)\s*/\s*(\d+)\s+(\d+(?:\.\d+)?)%',
            re.IGNORECASE
        )
        name_map = {
            'input': 'inputs', 'inputs': 'inputs',
            'output': 'outputs', 'outputs': 'outputs',
            'dff': 'dffs', 'dffs': 'dffs',
            'net': 'nets', 'nets': 'nets',
        }
        for m in metric_re.finditer(content):
            key = name_map.get(m.group(1).lower())
            if key:
                result[key] = {
                    "covered": int(m.group(2)),
                    "total":   int(m.group(3)),
                    "pct":     float(m.group(4))
                }

        # fanin -list 输出：未覆盖信号以 "- signal_name" 格式列出
        result["uncovered"] = re.findall(r'^\s*-\s+(\S+)', content, re.MULTILINE)
        return result

    def do_check(self, timeout=300, **kwargs) -> tuple[bool, object]:
        """执行 COI 覆盖率检查"""

        fanin_path   = self.get_path(self.fanin_rep)
        checker_path = self.get_path(self.checker_file)

        # Step 1: 判断是否需要重新执行 TCL
        need_rerun, rerun_reason = self._need_rerun(fanin_path, checker_path)
        if need_rerun:
            info(f"🚀 {rerun_reason}，执行 TCL 脚本...")
            exec_checker = TclExecutionChecker(self.tcl_script, self.dut_name)
            exec_checker.get_path = self.get_path
            exec_success, exec_result = exec_checker.do_check(timeout)
            if not exec_success:
                return False, {
                    "error": "❌ TCL 脚本执行失败，无法生成覆盖率报告",
                    "details": exec_result,
                    "suggestion": "请检查 checker.sv 和 wrapper.sv 是否有语法错误"
                }
            info("✅ TCL 执行成功，fanin.rep 已更新")
        else:
            info(f"📋 {rerun_reason}")

        # Step 2: 解析 fanin.rep
        info(f"🔍 解析 COI 覆盖率报告：{fanin_path}")
        coi = self._parse_fanin_report(fanin_path)

        def fmt(d):
            if d["total"] == 0:
                return "N/A（无此类信号）"
            return f"{d['covered']}/{d['total']}  ({d['pct']:.1f}%)"

        net_pct = coi["nets"]["pct"]
        dff_pct = coi["dffs"]["pct"]
        net_ok = coi["nets"]["total"] == 0 or net_pct >= self.coi_threshold
        dff_ok = coi["dffs"]["total"] == 0 or dff_pct >= self.coi_threshold
        all_ok = net_ok and dff_ok

        report = {
            "fanin_rep": fanin_path,
            "阈值": f">= {self.coi_threshold:.0f}%",
            "Inputs  COI": fmt(coi["inputs"]),
            "Outputs COI": fmt(coi["outputs"]),
            "Dffs    COI（寄存器状态覆盖）": fmt(coi["dffs"]),
            "Nets    COI（组合逻辑覆盖）":   fmt(coi["nets"]),
            "未覆盖信号数": len(coi["uncovered"]),
            "未覆盖信号（前30个）": coi["uncovered"][:30],
        }

        if all_ok:
            return True, {
                "message": (
                    f"✅ COI 覆盖率达标\n"
                    f"  Dff COI（寄存器）: {fmt(coi['dffs'])}\n"
                    f"  Net COI（逻辑）  : {fmt(coi['nets'])}"
                ),
                "report": report
            }
        else:
            issues = []
            if not dff_ok:
                issues.append(
                    f"Dff COI 不足：{dff_pct:.1f}% < {self.coi_threshold:.0f}%\n"
                    f"  → 部分寄存器状态未被任何断言触达，需补充 (Style: Seq) 断言"
                )
            if not net_ok:
                issues.append(
                    f"Net COI 不足：{net_pct:.1f}% < {self.coi_threshold:.0f}%\n"
                    f"  → 部分组合逻辑路径未被覆盖，需补充 (Style: Comb) 断言"
                )
            return False, {
                "error": "\n".join(issues),
                "report": report,
                "suggestion": f"查看完整未覆盖信号列表：{fanin_path}"
            }


class EnvironmentDebuggingChecker(Checker):
    """
    环境调试检查器，用于 environment_debugging_iteration 阶段。

    工作流程：
    1. 检查日志是否存在；若不存在则先执行 TCL 脚本生成日志
    2. 若 checker.sv 或 wrapper.sv 比日志文件更新，则重新执行 TCL 脚本
    3. 解析日志，提取 TRIVIALLY_TRUE 和 FALSE 属性
    4. 对 FALSE 属性进行分类：
       - 在 checker.sv 中标记 // [RTL_BUG] 的属性 → 已确认 RTL 缺陷，本阶段忽略
       - 未标记的 FALSE 属性 → 可能是环境问题（欠约束），需要 LLM 分析并决策
    5. 通过条件：无 TRIVIALLY_TRUE 且无未分类的 FALSE 属性

    FALSE 属性分类约定（LLM 在 checker.sv 中添加标记）：
    - 确认为 RTL 缺陷：在属性定义前或同行添加 // [RTL_BUG] 注释
      例：// [RTL_BUG] counter不正确递增，见counter.v:42
           A_CK_COUNT_MAX_REACHED: assert property(...);
    - 确认为环境问题：修复 assume 约束后，该属性应变为 PASS
    """
    def __init__(self, dut_name, property_file, spec_file, log_file, checker_file, tcl_script, **kwargs):
        self.dut_name = dut_name
        self.property_file = property_file
        self.spec_file = spec_file
        self.log_file = log_file
        self.checker_file = checker_file
        self.tcl_script = tcl_script

    def _parse_log(self, log_path: str) -> dict:
        """
        解析 avis.log，提取所有属性结果。

        日志格式优先级：
        1. 汇总表格：  12  checker_inst.A_CK_XXX  :  Fail/Pass/TrivT
        2. 详细日志：Info-P016: property checker_inst.XXX is FALSE/TRUE/TRIVIALLY_TRUE

        返回:
            {
                "trivially_true": [prop_name, ...],  # assert 属性 TRIVIALLY_TRUE
                "false_props": [prop_name, ...],     # assert 属性 Fail/FALSE（RTL缺陷）
                "pass_props": [prop_name, ...],      # 通过的属性
                "cover_pass": [prop_name, ...],      # cover 通过
                "cover_fail": [prop_name, ...],      # cover 失败
                "summary": {...}                     # 汇总统计
            }
        """
        result = {
            "trivially_true": [],
            "false_props": [],
            "pass_props": [],
            "cover_pass": [],
            "cover_fail": [],
        }

        if not os.path.exists(log_path):
            return result

        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # 从 show_prop -summary 汇总表格中解析，格式：
        #   12  checker_inst.A_CK_COUNT_NO_X             :  TrivT
        #   8   checker_inst.A_CK_RST_RELEASE            :  Fail  (3)
        #   5   checker_inst.A_CK_RST_COUT_RESET         :  Pass
        #   18  checker_inst.C_CK_COVER_STATE_0          :  Pass  (2)
        table_pattern = re.compile(
            r'^\s*\d+\s+(checker_inst\.[\w.]+)\s*:\s*(TrivT|Fail|Pass|Undec)',
            re.MULTILINE
        )

        for m in table_pattern.finditer(content):
            prop_full = m.group(1)
            # 去掉 checker_inst. 前缀，取实际属性名
            prop = prop_full.split('.')[-1] if '.' in prop_full else prop_full
            status = m.group(2)

            is_cover = prop.startswith('C_') or 'COVER' in prop.upper()

            if status == 'TrivT':
                if not is_cover:
                    result["trivially_true"].append(prop)
            elif status == 'Fail':
                if is_cover:
                    result["cover_fail"].append(prop)
                else:
                    result["false_props"].append(prop)
            elif status == 'Pass':
                if is_cover:
                    result["cover_pass"].append(prop)
                else:
                    result["pass_props"].append(prop)

        # 若汇总表格没有解析到，回退到逐行 Info-P016/Info-P014 解析
        # 注意：log 中既有 "is FALSE" 也有 "false:" 格式
        if not any([result["trivially_true"], result["false_props"], result["pass_props"]]):
            # 解析 Info-P016 格式（最终结果）
            p016_pattern = re.compile(
                r'Info-P016:\s*property\s+(checker_inst\.[\w.]+)\s+is\s+(TRIVIALLY_TRUE|TRUE|FALSE)',
                re.IGNORECASE
            )
            for m in p016_pattern.finditer(content):
                prop_full = m.group(1)
                prop = prop_full.split('.')[-1] if '.' in prop_full else prop_full
                status = m.group(2).upper()
                is_cover = prop.startswith('C_') or 'COVER' in prop.upper()

                if status == 'TRIVIALLY_TRUE':
                    if not is_cover:
                        result["trivially_true"].append(prop)
                elif status == 'FALSE':
                    if is_cover:
                        result["cover_fail"].append(prop)
                    else:
                        result["false_props"].append(prop)
                elif status == 'TRUE':
                    if is_cover:
                        result["cover_pass"].append(prop)
                    else:
                        result["pass_props"].append(prop)
            
            # 补充解析 Info-P014 格式（中间结果，格式：property false: xxx）
            if not result["false_props"]:
                p014_pattern = re.compile(
                    r'Info-P014:\s*property\s+(false|true):\s+(checker_inst\.[\w.]+)',
                    re.IGNORECASE
                )
                for m in p014_pattern.finditer(content):
                    status_str = m.group(1).lower()
                    prop_full = m.group(2)
                    prop = prop_full.split('.')[-1] if '.' in prop_full else prop_full
                    is_cover = prop.startswith('C_') or 'COVER' in prop.upper()
                    
                    if status_str == 'false':
                        if is_cover:
                            result["cover_fail"].append(prop)
                        else:
                            result["false_props"].append(prop)
                    elif status_str == 'true':
                        if is_cover:
                            result["cover_pass"].append(prop)
                        else:
                            result["pass_props"].append(prop)

        result["summary"] = {
            "assert_pass": len(result["pass_props"]),
            "assert_trivially_true": len(result["trivially_true"]),
            "assert_false": len(result["false_props"]),
            "cover_pass": len(result["cover_pass"]),
            "cover_fail": len(result["cover_fail"]),
        }
        return result

    def _extract_prop_code(self, prop_name: str, checker_content: str) -> str:
        """
        从 checker.sv 中提取属性的 SVA 代码片段（前后各5行）。
        """
        lines = checker_content.split('\n')
        for i, line in enumerate(lines):
            if prop_name in line and ('assert' in line or 'property' in line or ':' in line):
                start = max(0, i - 3)
                end = min(len(lines), i + 6)
                return '\n'.join(lines[start:end])
        # 回退：只找属性名出现的行
        for i, line in enumerate(lines):
            if prop_name in line:
                start = max(0, i - 2)
                end = min(len(lines), i + 4)
                return '\n'.join(lines[start:end])
        return "(未找到属性定义)"

    def _classify_false_props(self, false_props: list, checker_content: str) -> tuple[list, list]:
        """
        将 FALSE 属性分为已确认 RTL 缺陷和未分类两类。

        判断依据：在属性对应的 property...endproperty 块及其前面注释区域内是否有 [RTL_BUG] 标记。
        搜索范围：从 `property CK_XXX;` 定义行往前 3 行，到 assert 语句行往后 2 行。
        这样无论 LLM 将 [RTL_BUG] 放在 property 块前还是 assert 行前，都能被正确检测到。

        返回: (rtl_defects, unclassified)
        """
        lines = checker_content.split('\n')
        rtl_defects = []
        unclassified = []

        for prop in false_props:
            found_marker = False

            # 从 A_CK_XXX 推导 property 块名 CK_XXX（去掉 A_ 前缀）
            ck_name = prop[2:] if prop.startswith('A_') else prop

            # 1. 找 assert 行：A_CK_XXX: assert property(...)
            assert_idx = None
            for i, line in enumerate(lines):
                if prop in line and 'assert' in line:
                    assert_idx = i
                    break

            # 2. 找 property 定义行：property CK_XXX; 或 property CK_XXX (
            prop_def_idx = None
            for i, line in enumerate(lines):
                if re.search(rf'\bproperty\s+{re.escape(ck_name)}\b', line):
                    prop_def_idx = i
                    break

            # 3. 确定搜索范围
            if prop_def_idx is not None:
                # 从 property 定义往前 3 行（覆盖 [RTL_BUG] 注释区域）
                search_start = max(0, prop_def_idx - 3)
            elif assert_idx is not None:
                # 找不到 property 定义时，从 assert 行往前 10 行兜底
                search_start = max(0, assert_idx - 10)
            else:
                # 完全找不到，标记为未分类
                unclassified.append(prop)
                continue

            search_end = min(len(lines), (assert_idx if assert_idx is not None else prop_def_idx + 10) + 3)

            window = '\n'.join(lines[search_start:search_end])
            if '[RTL_BUG]' in window:
                found_marker = True

            if found_marker:
                rtl_defects.append(prop)
            else:
                unclassified.append(prop)

        return rtl_defects, unclassified

    def _need_rerun(self, log_path: str, checker_path: str, wrapper_path: str) -> tuple[bool, str]:
        """
        判断是否需要重新执行 TCL 脚本。
        若 checker.sv 或 wrapper.sv 比 avis.log 更新，则需要重跑。
        """
        if not os.path.exists(log_path):
            return True, "日志文件不存在，需要执行 TCL"

        log_mtime = os.path.getmtime(log_path)

        for fpath, label in [(checker_path, "checker.sv"), (wrapper_path, "wrapper.sv")]:
            if os.path.exists(fpath) and os.path.getmtime(fpath) > log_mtime:
                return True, f"{label} 已更新（比日志新），需要重新执行验证"

        return False, "代码未更新，直接读取已有日志"

    def do_check(self, timeout=300, **kwargs) -> tuple[bool, object]:
        """执行环境调试检查"""
        log_path = self.get_path(self.log_file)
        checker_path = self.get_path(self.checker_file)

        # 推断 wrapper 路径（与 checker 同目录，名称为 {dut}_wrapper.sv）
        tests_dir = os.path.dirname(log_path)
        wrapper_path = os.path.join(tests_dir, f"{self.dut_name}_wrapper.sv")

        # Step 1: 判断是否需要重新执行 TCL
        need_rerun, rerun_reason = self._need_rerun(log_path, checker_path, wrapper_path)

        if need_rerun:
            info(f"🚀 {rerun_reason}，执行 TCL 脚本...")
            exec_checker = TclExecutionChecker(self.tcl_script, self.dut_name)
            exec_checker.get_path = self.get_path
            exec_success, exec_result = exec_checker.do_check(timeout)

            if not exec_success:
                return False, {
                    "error": "❌ TCL 脚本执行失败",
                    "details": exec_result,
                    "suggestion": "请检查 TCL 脚本、checker.sv 和 wrapper.sv 是否有语法错误"
                }
            info("✅ TCL 执行成功，日志已更新")
        else:
            info(f"📋 {rerun_reason}")

        # Step 2: 解析日志
        info("🔍 解析验证日志...")
        parsed = self._parse_log(log_path)
        trivially_true = parsed["trivially_true"]
        false_props = parsed["false_props"]
        summary = parsed["summary"]

        # Step 3: 读取 checker.sv 用于 FALSE 属性分析
        checker_content = ""
        if os.path.exists(checker_path):
            with open(checker_path, 'r', encoding='utf-8', errors='ignore') as f:
                checker_content = f.read()

        # Step 4: 对所有 Fail 属性分类（assert fail + cover fail 统一处理）
        # 分类依据：checker.sv 中是否有 [RTL_BUG] 注释
        #   - 有 [RTL_BUG] 标记 → 已确认 RTL 缺陷，本阶段放行，后续 formal_execution 深入分析
        #   - 无任何标记      → 未分类，必须处理（修复环境或标记 RTL_BUG）
        rtl_defects_assert, unclassified_false = self._classify_false_props(false_props, checker_content)
        rtl_defects_cover, unclassified_cover_fail = self._classify_false_props(parsed["cover_fail"], checker_content)

        all_rtl_defects = rtl_defects_assert + rtl_defects_cover
        all_unclassified = unclassified_false + unclassified_cover_fail

        # Step 5: 判断是否通过
        # TRIVIALLY_TRUE 为警告（不阻塞通过），任何未分类 Fail 均阻塞（必须修复环境或标记 RTL_BUG）
        has_tt = len(trivially_true) > 0
        has_unclassified = len(all_unclassified) > 0

        # 构建公共报告体
        report = {"summary": summary, "log_path": log_path}

        if has_tt:
            tt_list = "\n".join(f"  - {p}" for p in trivially_true)
            report["warning_trivially_true"] = {
                "count": len(trivially_true),
                "props": trivially_true,
                "analysis": (
                    f"⚠️  以下 {len(trivially_true)} 个属性为 TRIVIALLY_TRUE（环境过约束，建议修复）：\n{tt_list}\n"
                    "修复方向：\n"
                    "  1. 检查对应 assume 约束是否过强（排除了合法输入）\n"
                    "  2. 检查 $isunknown / !$isunknown 断言是否正确——若信号不可能为X则会被常量折叠\n"
                    "  3. 检查 wrapper.sv 信号映射是否有误导致常数传播\n"
                    "注意：TRIVIALLY_TRUE 不阻塞阶段通过，但建议尽量修复以提升验证有效性。"
                )
            }

        def _build_unclassified_detail(props, prop_kind):
            details = []
            for prop in props:
                code = self._extract_prop_code(prop, checker_content)
                details.append({"property": prop, "sva_code": code})
            prop_list = "\n".join(f"  - {p}" for p in props)
            if prop_kind == "assert":
                hint = (
                    f"以下 {len(props)} 个 assert Fail 属性尚未分类，需逐一分析：\n{prop_list}\n\n"
                    "分析步骤（对每个属性）：\n"
                    "  1. 阅读上面显示的SVA代码，理解该属性要验证什么\n"
                    "  2. 使用ReadTextFile工具查看RTL代码，分析该属性失败的原因\n"
                    "  3. 判断：该属性是 RTL 本身的 Bug？还是环境约束不足导致工具找到了不真实的反例？\n"
                    "     环境问题特征：反例中输入信号有不合理的组合；或约束 assume 明显缺失\n"
                    "     RTL缺陷特征：反例展示了真实的 RTL 功能错误（如位宽错误、算术错误、逻辑错误）\n"
                    "  4. 若确认为 RTL 缺陷：在 checker.sv 中该属性定义的前一行加上:\n"
                    "       // [RTL_BUG] <简短描述>\n"
                    "  5. 若确认为环境问题：修复对应 assume 约束，该属性修复后应变为 PASS\n"
                    "  6. 完成所有标记/修复后，再次调用 Check"
                )
            else:
                hint = (
                    f"以下 {len(props)} 个 cover Fail 属性尚未分类，需逐一分析：\n{prop_list}\n\n"
                    "cover Fail 表示该场景从未被到达，分析步骤：\n"
                    "  1. 阅读上面显示的SVA代码，理解该cover要到达什么状态\n"
                    "  2. 使用ReadTextFile工具查看RTL代码和assume约束\n"
                    "  3. 判断：该场景是 RTL Bug 导致不可达？还是 assume 过强排除了该场景？\n"
                    "     环境过约束特征：放宽 assume 后场景可到达\n"
                    "     RTL缺陷特征：逻辑上应可达但 RTL 实现有误\n"
                    "  4. 若确认为 RTL 缺陷：在 checker.sv 中该属性定义的前一行加上:\n"
                    "       // [RTL_BUG] <简短描述>\n"
                    "  5. 若确认为环境过约束：修复对应 assume，该 cover 修复后应变为 PASS\n"
                    "  6. 完成所有标记/修复后，再次调用 Check"
                )
            return {"count": len(props), "props": props, "details": details, "analysis_required": hint}

        if unclassified_false:
            report["unclassified_assert_fail"] = _build_unclassified_detail(unclassified_false, "assert")

        if unclassified_cover_fail:
            report["unclassified_cover_fail"] = _build_unclassified_detail(unclassified_cover_fail, "cover")

        if all_rtl_defects:
            report["rtl_defects_already_marked"] = all_rtl_defects

        if has_unclassified:
            parts = []
            if unclassified_false:
                parts.append(f"{len(unclassified_false)} 个 assert Fail 未分类")
            if unclassified_cover_fail:
                parts.append(f"{len(unclassified_cover_fail)} 个 cover Fail 未分类")
            report["error"] = (
                "❌ 环境调试未完成：" + "，".join(parts) +
                "。\n请逐一分析每个 Fail 属性：确认为 RTL 缺陷则加 // [RTL_BUG] 注释；确认为环境问题则修复 assume 约束。"
            )
            if has_tt:
                report["error"] += f"\n（另有 {len(trivially_true)} 个 TRIVIALLY_TRUE 警告，建议修复但不阻塞）"
            return False, report

        # 通过：所有 Fail 均已分类（TRIVIALLY_TRUE 仅作警告）
        rtl_list = "\n".join(f"  - {p}" for p in all_rtl_defects)
        result = {
            "summary": summary,
            "rtl_defects_confirmed": all_rtl_defects,
            "note": (
                f"已确认 {len(all_rtl_defects)} 个 RTL 缺陷（标记 [RTL_BUG]），"
                "将在后续 formal_execution 阶段深度分析：\n" + rtl_list
                if all_rtl_defects else "无未分类 Fail 属性，验证环境质量良好"
            ),
            "log_path": log_path
        }
        if has_tt:
            result["message"] = f"✅ 环境调试阶段通过（含 {len(trivially_true)} 个 TRIVIALLY_TRUE 警告，建议修复）"
            result["warning_trivially_true"] = report["warning_trivially_true"]
        else:
            result["message"] = "✅ 环境调试阶段通过"
        return True, result
