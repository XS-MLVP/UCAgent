# -*- coding: utf-8 -*-
"""AI Skills for the Formal workflow example."""

import glob
import os
import re
import shutil
from typing import Dict, List, Optional, Tuple

from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field

from ucagent.tools.fileops import BaseReadWrite
from ucagent.tools.uctool import UCTool
from ucagent.util.log import str_error, str_info

from examples.Formal.scripts.formal_tools import (
    parse_avis_log,
    extract_rtl_bug_from_analysis_doc,
    extract_property_code,
    strip_prop_prefix,
    resolve_paths,
    extract_ports,
    detect_clock_reset,
    build_symbolic_logic,
    build_clk_rst_remap,
    parse_wrapper_clock_reset,
    parse_spec_ck_items,
    run_formal_verification,
    summarize_execution,
)

# =============================================================================
# Helper for Bug Output Backup
# =============================================================================

def _backup_if_exists(filepath: str) -> None:
    """If file exists, copy to .bak and print message."""
    if os.path.exists(filepath):
        bak = filepath + '.bak'
        shutil.copy2(filepath, bak)
        str_info(f'Backed up: {filepath} -> {bak}')

# =============================================================================
# Module-Level Template Rendering Functions
# =============================================================================

def _render_tt_entry(idx: int, prop_name: str, checker_content: str) -> str:
    sva_code = extract_property_code(checker_content, prop_name)
    return f"""### <TT-{idx:03d}> {prop_name}
- **属性名**: {prop_name}
- **SVA 代码**:
  ```systemverilog
{sva_code}
  ```
- **根因分类**: [LLM-TODO: ASSUME_TOO_STRONG | SIGNAL_CONSTANT | WRAPPER_ERROR | DESIGN_EXPECTED]
- **关联 Assume**: [LLM-TODO: M_CK_YYY 或 N/A]
- **分析**: [LLM-TODO: 具体描述为何此属性 trivially true]
- **修复动作**: [LLM-TODO: FIXED | ACCEPTED]
- **修复说明**: [LLM-TODO: 描述修改内容或接受理由]
"""

def _render_fa_entry(idx: int, prop_name: str, prop_type: str, checker_content: str) -> str:
    sva_code = extract_property_code(checker_content, prop_name)
    return f"""### <FA-{idx:03d}> {prop_name}
- **属性名**: {prop_name}
- **属性类型**: {prop_type}
- **SVA 代码**:
  ```systemverilog
{sva_code}
  ```
- **解决状态**: [LLM-TODO: RTL_BUG | ENV_FIXED | ENV_PENDING | COVER_EXPECTED_FAIL]
- **反例/分析**: [LLM-TODO: 描述反例中的信号值和时序关系]
- **修复说明**: [LLM-TODO: 具体描述修复内容或缺陷现象]
"""

def _render_bug_entry(idx: int, fa_id: str, prop_name: str) -> str:
    ck_part = strip_prop_prefix(prop_name)
    bg_name = f'BG-FORMAL-{idx:03d}-{ck_part.replace("_", "-")}'

    return f"""## Failed Property: `{prop_name}`

### [LLM-TODO: <FG-???> 关联的功能组]

### [LLM-TODO: <FC-???> 关联的功能点]

### <{bg_name}> [LLM-TODO: 缺陷标题]

<CK-{ck_part.replace("_", "-")}>

<TC-FORMAL-{idx:03d}> 形式化验证反例证实（对应 {fa_id}）

**FILE-RTL文件路径**: [LLM-TODO: RTL文件路径:行号]

**问题描述**: [LLM-TODO: 详细描述由于什么原因导致了预期之外的行为]
**根本原因**: [LLM-TODO: 是什么代码逻辑或参数导致了这个问题]
**触发条件**: [LLM-TODO: 什么输入组合或时序状态能够复现该 Bug]
**预期行为**: [LLM-TODO: 预期的正确输出是什么]
**实际行为**: [LLM-TODO: 当前错误的输出是什么]
**修复建议**: [LLM-TODO: 具体的代码修改建议]

**反例波形解读**:
- 触发条件: [LLM-TODO]
- 反例值: [LLM-TODO: e.g. a = 0x..., b = 0x...]
- 预期结果: [LLM-TODO]
- 实际结果: [LLM-TODO]

**影响范围**: [LLM-TODO: 严重 | 中等 | 低]
**置信度**: [LLM-TODO: 高 | 中 | 低]
**优先级**: [LLM-TODO: 最高 | 高 | 中 | 低]

---
"""

def _render_test_function(prop_name: str, fa_id: str, clock_name: Optional[str], reset_name: Optional[str], dut_class: str) -> str:
    name = strip_prop_prefix(prop_name).lower()
    func_name = f'test_cex_{name}'
    
    clock_init = f"    dut.InitClock('{clock_name}')\n    # 复位序列\n" if clock_name else ""
    if clock_name:
        if reset_name:
            clock_init += f"    dut.{reset_name}.value = 0\n    dut.Step(5)\n    dut.{reset_name}.value = 1\n"
        else:
            clock_init += f"    # [LLM-TODO]: 复位序列\n    dut.Step(5)\n"
        clock_init += "    dut.Step(1)\n"

    tq = '"""'  # triple-quote for generated docstring
    return (
        f"def {func_name}():\n"
        f"    {tq}反例测试: {prop_name} (来源: {fa_id})\n"
        f"    [LLM-TODO]: 补充 Bug 描述、反例条件、预期/实际行为\n"
        f"    {tq}\n"
        f"    dut = DUT{dut_class}()\n"
        f"{clock_init}"
        f"    # [LLM-TODO]: 按反例时序驱动引脚\n"
        f"    dut.Step(1)\n"
        f"\n"
        f"    # [LLM-TODO]: 断言检查\n"
        f"    # assert dut.yyy.value == expected\n"
        f"\n"
        f"    dut.Finish()\n"
    )

# =============================================================================
# Tool: GenerateFormalEnv
# =============================================================================

class ArgGenerateFormalEnv(BaseModel):
    """Arguments for GenerateFormalEnv tool."""

    dut_name: str = Field(description="Top-level module name of the DUT (extracted from RTL file, e.g., 'main', 'traffic').")
    output_dir: str = Field(default="formal_test", description="Output directory name for formal tests. Defaults to 'formal_test'.")
    rtl_dir: Optional[str] = Field(default=None, description="RTL source directory path. Defaults to '{workspace}/{dut_name}'.")
    spec_file: Optional[str] = Field(default=None, description="Path to functions_and_checks.md for parsing SVA scaffold. Defaults to '{output_dir}/03_{dut_name}_functions_and_checks.md'.")


class GenerateFormalEnv(UCTool, BaseReadWrite):
    name: str = "GenerateFormalEnv"
    description: str = """Generates checker.sv and wrapper.sv files for the formal verification environment.
If a spec document exists, it automatically appends the SVA property scaffold skeletons to the end of checker.sv.

Usage:
1. Provide dut_name: Top-level module name defined in the RTL file.
2. The tool inherently determines the 'rtl_dir', 'output_file', and 'spec_file' paths internally. You usually do NOT need to specify them.

Example Usage:
- GenerateFormalEnv(dut_name="Adder")
"""
    args_schema: Optional[ArgsSchema] = ArgGenerateFormalEnv

    def _find_rtl_file(self, rtl_dir: str, dut_name: str) -> str:
        """Finds the RTL file containing the dut_name module in the specified directory."""
        str_info(f"Searching for RTL file for module '{dut_name}' in: {rtl_dir}")

        if not os.path.isdir(rtl_dir):
            raise FileNotFoundError(f"RTL directory does not exist: {rtl_dir}")

        # Find all .v/.sv files
        all_files = []
        for ext in ["*.v", "*.sv"]:
            all_files.extend(glob.glob(os.path.join(rtl_dir, ext)))

        str_info(f"Found {len(all_files)} RTL files")

        # Parse each file to find a module name match
        for file_path in all_files:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    module_pattern = rf"\bmodule\s+{re.escape(dut_name)}\b"
                    if re.search(module_pattern, content):
                        str_info(f"Found RTL: {file_path}")
                        return file_path
            except OSError as e:
                str_error(f"Error reading {file_path}: {e}")
                continue

        # If there's only one file, use it directly
        if len(all_files) == 1:
            str_info(f"Using only RTL file: {all_files[0]}")
            return all_files[0]

        raise FileNotFoundError(
            f"Could not find RTL source for module '{dut_name}' in '{rtl_dir}'. "
            f"Found files: {all_files if all_files else 'none'}"
        )


    def _load_template(self, template_name: str) -> str:
        """Load template file from workspace directory.
        
        Templates are deployed to workspace/formal_test/tests/ by UCAgent's
        template engine on startup (from ucagent/lang/zh/template/formal_test/).
        """
        workspace = os.environ.get("UCAGENT_WORKSPACE", os.getcwd())
        template_path = os.path.join(workspace, "formal_test", "tests", template_name)
        
        if not os.path.exists(template_path):
            raise FileNotFoundError(
                f"Template '{template_name}' not found at: {template_path}\n"
                f"Ensure UCAgent was started with '--output formal_test' to deploy templates."
            )
        
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()


    def _generate_checker_file(
        self,
        dut_name: str,
        rtl_file_path: str,
        port_info: List[Tuple[str, str]],
        param_info: List[Tuple[str, str]],
        clk_port: Optional[str],
        rst_port: Optional[str],
        symbolic_groups: Dict[str, List[str]],
        fv_idx_width: int,
        checker_path: str,
    ) -> None:
        """Generate the checker.sv file."""
        # Build parameter declaration
        if param_info:
            param_decl_str = (
                " #(\n  " + ",\n  ".join([info[1] for info in param_info]) + "\n)"
            )
        else:
            param_decl_str = ""

        # Convert all ports to input, normalizing clock/reset
        checker_ports = []
        if clk_port is None:
            checker_ports.append("input clk")
        if rst_port is None:
            checker_ports.append("input rst_n")
        for port_name, port_def in port_info:
            checker_port = re.sub(
                r"^(input|output|inout)\s+", "input ", port_def, count=1
            )
            if port_name == clk_port and port_name != "clk":
                checker_port = re.sub(
                    rf"\b{re.escape(port_name)}\s*$", "clk", checker_port
                )
            elif port_name == rst_port and port_name != "rst_n":
                checker_port = re.sub(
                    rf"\b{re.escape(port_name)}\s*$", "rst_n", checker_port
                )
            checker_ports.append(checker_port)

        # Add fv_idx and monitored signals for symbolic groups
        if symbolic_groups:
            checker_ports.append(f"input [{fv_idx_width - 1}:0] fv_idx")
            for base, indices in symbolic_groups.items():
                if len(indices) > 1:
                    checker_ports.append(f"input fv_mon_{base}")

        checker_port_decl_str = ",\n  ".join(checker_ports)

        checker_template = self._load_template(f"{dut_name}_checker.sv")
        checker_code = checker_template.format(
            dut_name=dut_name,
            rtl_file_path=rtl_file_path,
            param_decl=param_decl_str,
            port_decl=checker_port_decl_str,
        )
        with open(checker_path, "w", encoding="utf-8") as f:
            f.write(checker_code)
        str_info(f"Checker generated at: {checker_path}")


    def _generate_wrapper_file(
        self,
        dut_name: str,
        port_info: List[Tuple[str, str]],
        param_info: List[Tuple[str, str]],
        clk_port: Optional[str],
        rst_port: Optional[str],
        symbolic_groups: Dict[str, List[str]],
        symbolic_logic: str,
        fv_idx_width: int,
        clk_rst_remap: str,
        wrapper_path: str,
    ) -> None:
        """Generate the wrapper.sv file."""
        # Parameter strings
        if param_info:
            param_inst_str = (
                " #(\n    "
                + ",\n    ".join([f".{name}({name})" for name, _ in param_info])
                + "\n  )"
            )
        else:
            param_inst_str = ""

        # Wrapper ports
        wrapper_ports = []
        if clk_port is None:
            wrapper_ports.append("input clk")
        if rst_port is None:
            wrapper_ports.append("input rst_n")
        for port_name, port_def in port_info:
            if port_name == clk_port and port_name != "clk":
                normalized = re.sub(rf"\b{re.escape(port_name)}\s*$", "clk", port_def)
                wrapper_ports.append(normalized)
            elif port_name == rst_port and port_name != "rst_n":
                normalized = re.sub(rf"\b{re.escape(port_name)}\s*$", "rst_n", port_def)
                wrapper_ports.append(normalized)
            else:
                wrapper_ports.append(port_def)
        if symbolic_groups:
            wrapper_ports.append(f"input [{fv_idx_width - 1}:0] fv_idx")
        wrapper_ports_str = ",\n  ".join(wrapper_ports)

        # DUT instance connections (original RTL names)
        dut_conns_str = ",\n    ".join(f".{name}({name})" for name, _ in port_info)

        # Checker instance connections (normalized)
        checker_conns = []
        if clk_port is None:
            checker_conns.append(".clk(clk)")
        if rst_port is None:
            checker_conns.append(".rst_n(rst_n)")
        for port_name, _ in port_info:
            if port_name == clk_port:
                checker_conns.append(".clk(clk)")
            elif port_name == rst_port:
                checker_conns.append(".rst_n(rst_n)")
            else:
                checker_conns.append(f".{port_name}({port_name})")
        if symbolic_groups:
            checker_conns.append(".fv_idx(fv_idx)")
            for base, indices in symbolic_groups.items():
                if len(indices) > 1:
                    checker_conns.append(f".fv_mon_{base}(fv_mon_{base})")
        checker_conns_str = ",\n    ".join(checker_conns)

        # Wrapper parameter declaration
        if param_info:
            wrapper_params_str = (
                " #(\n  " + ",\n  ".join([info[1] for info in param_info]) + "\n)"
            )
        else:
            wrapper_params_str = ""

        # Render template
        wrapper_template = self._load_template(f"{dut_name}_wrapper.sv")
        wrapper_code = wrapper_template.format(
            dut_name=dut_name,
            param_decl=wrapper_params_str,
            port_decl=wrapper_ports_str,
            param_inst=param_inst_str,
            dut_conns=dut_conns_str,
            checker_conns=checker_conns_str,
            clk_rst_remap=clk_rst_remap,
            dut_name_wrapper=f"{dut_name}_wrapper",
        )
        # Inject symbolic logic
        wrapper_code = wrapper_code.replace(
            "// [LLM-TODO]: If the design has array-like storage, define fv_idx and mux.",
            symbolic_logic,
        )

        with open(wrapper_path, "w", encoding="utf-8") as f:
            f.write(wrapper_code)
        str_info(f"Wrapper generated at: {wrapper_path}")


    def _append_sva_scaffold(self, spec_file: str, checker_path: str) -> str:
        if not os.path.exists(spec_file): return f"\nℹ️ Spec file not found at {spec_file}. Scaffold generation skipped."
        try:
            with open(spec_file, "r", encoding="utf-8") as f: content = f.read()
            items = parse_spec_ck_items(content)
            if not items: return "\nℹ️ No <CK-...> tags found in spec file. Scaffold generation skipped."
            scaffolds = []
            for ck_name, style, desc in items:
                style = style.capitalize()
                if style == "Assume":
                    inst_prefix, inst_kind, clock_in_prop = "M", "assume", True
                elif style == "Comb":
                    inst_prefix, inst_kind, clock_in_prop = "A", "assert", False
                elif style == "Cover":
                    inst_prefix, inst_kind, clock_in_prop = "C", "cover", True
                else:
                    inst_prefix, inst_kind, clock_in_prop = "A", "assert", True
                prop_name = f"CK_{ck_name.upper()}"
                inst_label = f"{inst_prefix}_{prop_name}"
                scaffold = f"// [LLM-TODO] Style: {style} - 检测点: <CK-{ck_name}>\n// {desc}\n"
                if clock_in_prop:
                    scaffold += f"property {prop_name};\n  @(posedge clk) disable iff (!rst_n)\n  1; // TODO\nendproperty\n{inst_label}: {inst_kind} property ({prop_name});\n"
                else:
                    scaffold += f"property {prop_name};\n  1; // TODO\nendproperty\n{inst_label}: {inst_kind} property (@(posedge clk) disable iff (!rst_n) {prop_name});\n"
                scaffolds.append(scaffold)

            append_text = "\n\n  // " + "="*70 + "\n  // Auto-generated SVA Scaffold\n  // " + "="*70 + "\n\n"
            append_text += "\n".join("  " + s.replace("\n", "\n  ") for s in scaffolds) + "\n"
            with open(checker_path, "r", encoding="utf-8") as f: checker_code = f.read()
            if "endmodule" in checker_code:
                checker_code = checker_code.replace("endmodule", append_text + "\nendmodule")
            else:
                checker_code += append_text
            with open(checker_path, "w", encoding="utf-8") as f: f.write(checker_code)
            return f"\n✅ Injected {len(scaffolds)} SVA scaffolds to {checker_path} based on spec."
        except OSError as e:
            return f"\n⚠️ Error reading spec or appending scaffold: {e}"

    def _run(self, dut_name: str, output_dir: str = "formal_test", rtl_dir: Optional[str] = None, spec_file: Optional[str] = None) -> str:
        paths = resolve_paths(dut_name, output_dir=output_dir, rtl_dir=rtl_dir, spec_file=spec_file)
        rtl_dir_res = paths["rtl_dir"]
        checker_path = paths["checker_file"]
        wrapper_path = paths["wrapper_file"]
        spec_path = paths["spec_file"]

        str_info(f"RTL directory: {rtl_dir_res}")
        str_info(f"Output checker: {checker_path}")
        str_info(f"Output wrapper: {wrapper_path}")
        os.makedirs(os.path.dirname(checker_path), exist_ok=True)

        try:
            rtl_file_path = self._find_rtl_file(rtl_dir_res, dut_name)
            str_info(f"Found RTL: {rtl_file_path}")
            port_decl_str, port_info, param_info = extract_ports(rtl_file_path)
            clk_port, rst_port, rst_active_low = detect_clock_reset(port_info)
            symbolic_groups, symbolic_logic, fv_idx_width = build_symbolic_logic(port_info)
            clk_rst_remap = build_clk_rst_remap(clk_port, rst_port, rst_active_low)

            self._generate_checker_file(dut_name, rtl_file_path, port_info, param_info, clk_port, rst_port, symbolic_groups, fv_idx_width, checker_path)
            self._generate_wrapper_file(dut_name, port_info, param_info, clk_port, rst_port, symbolic_groups, symbolic_logic, fv_idx_width, clk_rst_remap, wrapper_path)

            res_msg = f"Checker skeleton created at: {checker_path}\nWrapper created at: {wrapper_path}\n(Ports extracted from {rtl_file_path})"
            res_msg += self._append_sva_scaffold(spec_path, checker_path)
            return str_info(res_msg)

        except FileNotFoundError as e:
            return str_error(f"RTL file not found: {e}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            return str_error(f"Error generating checker/wrapper: {e}")

# =============================================================================
# Tool: RunFormalVerification
# =============================================================================

class ArgRunFormalVerification(BaseModel):
    dut_name: str = Field(description="DUT name (e.g., 'Adder'). The tool will automatically execute formal_test/tests/{dut_name}_formal.tcl")
    timeout: int = Field(default=300, description="Timeout (seconds), default 300s")

class RunFormalVerification(UCTool, BaseReadWrite):
    name: str = "RunFormalVerification"
    description: str = """Immediately executes formal verification and returns a results summary.
Applicable Scenarios:
- Wanting to immediately re-run verification to see results after modifying checker.sv or wrapper.sv.
- Not wanting to wait for the Check/Complete tools to trigger an automatic re-run.
- Refreshing fanin.rep after adding assertions during the coverage analysis phase.
    
Example Usage:
  RunFormalVerification(dut_name="Adder")
"""
    args_schema: Optional[ArgsSchema] = ArgRunFormalVerification

    def _run(self, dut_name: str, timeout: int = 300) -> str:
        paths = resolve_paths(dut_name)
        tcl_path = paths["tcl_script"]
        if not os.path.exists(tcl_path):
            tcl_path = tcl_path.replace("formal_test/tests", "unity_tests/tests")
        if not os.path.exists(tcl_path):
            return str_error(f"TCL script does not exist: {tcl_path}\nPlease run GenerateFormalScript first to generate {dut_name}_formal.tcl")

        res = run_formal_verification(tcl_path, timeout)
        if not res["success"]:
            if res["error"] and "not found" in res["error"]: return str_error(f"❌ '{res['error']}', please ensure the tool is installed and in your PATH")
            if res["error"] and "Timeout" in res["error"]: return str_error(f"❌ Verification timed out (>{timeout}s), please check if constraints are too weak or design state space is too large")
            return str_error(f"❌ Formal verification execution failed: {res['error']}\n{summarize_execution(res.get('stdout', ''), res.get('stderr', ''))}")

        parsed = res["parsed_log"]
        if not parsed: return str_error("❌ Verification completed but no property results found in log")
        
        lines = [f"✅ Execution completed, log: {res['log_path']}", "", "📊 Verification Results Summary:",
                 f"  Assert Pass        : {len(parsed['pass'])}",
                 f"  Assert TRIVIALLY_TRUE : {len(parsed['trivially_true'])}",
                 f"  Assert Fail        : {len(parsed['false'])}",
                 f"  Cover  Pass        : {len(parsed['cover_pass'])}",
                 f"  Cover  Fail        : {len(parsed['cover_fail'])}"]

        if parsed["false"]: lines.extend([f"\n❌ Failed Assert Properties ({len(parsed['false'])}):"] + [f"  - {p}" for p in parsed["false"]])
        if parsed["trivially_true"]: lines.extend([f"\n⚠️  TRIVIALLY_TRUE Properties ({len(parsed['trivially_true'])} - environment over-constrained):"] + [f"  - {p}" for p in parsed["trivially_true"]])
        if parsed["cover_fail"]: lines.extend([f"\n⚠️  Failed Cover Properties ({len(parsed['cover_fail'])}):"] + [f"  - {p}" for p in parsed["cover_fail"]])
        return str_info("\n".join(lines))

# =============================================================================
# Tool: InitEnvAnalysis
# =============================================================================

class ArgInitEnvAnalysis(BaseModel):
    dut_name: str = Field(description="DUT module name")
    log_path: Optional[str] = Field(default=None, description="Path to avis.log. If not provided, defaults to output_dir/tests/avis.log.")
    output_path: Optional[str] = Field(default=None, description="Path to save the generated analysis document. If not provided, defaults to output_dir/07_{dut_name}_env_analysis.md.")
    output_dir: str = Field(default="formal_test", description="The output directory name within the workspace. Typically 'formal_test'.")

class InitEnvAnalysis(UCTool, BaseReadWrite):
    name: str = "InitEnvAnalysis"
    description: str = """Generates the environment analysis document framework (07_{DUT}_env_analysis.md) by parsing avis.log."""
    args_schema: Optional[ArgsSchema] = ArgInitEnvAnalysis

    def _run(self, dut_name: str, log_path: Optional[str] = None, output_path: Optional[str] = None, output_dir: str = "formal_test") -> str:
        paths = resolve_paths(dut_name, output_dir=output_dir, log_file=log_path, analysis_doc=output_path)
        res_log_path = paths["log_file"]
        res_output_path = paths["analysis_doc"]
        checker_path = paths["checker_file"]
            
        if not os.path.exists(res_log_path): return str_error(f"Error: log file not found at {res_log_path}")
        log_result = parse_avis_log(res_log_path)
        _backup_if_exists(res_output_path)
        os.makedirs(os.path.dirname(res_output_path), exist_ok=True)
        
        checker_content = ""
        if os.path.exists(checker_path):
            with open(checker_path, "r", encoding="utf-8", errors="ignore") as f: checker_content = f.read()
        
        n_pass = len(log_result["pass"])
        n_tt = len(log_result["trivially_true"])
        n_false = len(log_result["false"])
        n_cover_pass = len(log_result["cover_pass"])
        n_cover_fail = len(log_result["cover_fail"])
        n_total = n_pass + n_tt + n_false + n_cover_pass + n_cover_fail

        lines = [f"# {dut_name} 形式化验证环境分析报告\n", "> **由 InitEnvAnalysis 自动生成** — [LLM-TODO] 标记处需要人工填写\n", "---"]
        lines.extend(["## 1. 验证结果概览\n", "| 类型 | 数量 |", "|------|------|",
                      f"| Assert Pass | {n_pass} |", f"| Assert TRIVIALLY_TRUE | {n_tt} |",
                      f"| Assert Fail | {n_false} |", f"| Cover Pass | {n_cover_pass} |",
                      f"| Cover Fail | {n_cover_fail} |", f"| **Total** | **{n_total}** |", "", "---"])

        lines.append("## 2. TRIVIALLY_TRUE 属性分析\n")
        if n_tt == 0:
            lines.append("> 无 TRIVIALLY_TRUE 属性，验证环境约束健康。\n")
        else:
            lines.append(f"> 共 {n_tt} 个 TRIVIALLY_TRUE 属性需要分析。\n")
            lines.extend(_render_tt_entry(i, prop, checker_content) for i, prop in enumerate(log_result["trivially_true"], start=1))
        lines.append("---")

        lines.append("## 3. FALSE 属性分析\n")
        false_props = [(p, "assert") for p in log_result["false"]] + [(p, "cover") for p in log_result["cover_fail"]]
        n_fa = len(false_props)
        if n_fa == 0:
            lines.append("> 无 FALSE 属性，所有断言和覆盖属性均已通过。\n")
        else:
            lines.append(f"> 共 {n_fa} 个 FALSE 属性需要分析。\n")
            lines.extend(_render_fa_entry(i, prop, ptype, checker_content) for i, (prop, ptype) in enumerate(false_props, start=1))
        
        with open(res_output_path, "w", encoding="utf-8") as f: f.write("\n".join(lines))
        return str_info(f"✅ Document generated at: {res_output_path}\n   - TRIVIALLY_TRUE entries: {n_tt}\n   - FALSE entries: {n_fa}\n   - Total [LLM-TODO] remaining: {n_tt + n_fa}")

# =============================================================================
# Tool: UpdateEnvAnalysis
# =============================================================================

class ArgUpdateEnvAnalysis(BaseModel):
    dut_name: str = Field(description="DUT module name")
    output_dir: str = Field(default="formal_test", description="The output directory name within the workspace. Typically 'formal_test'.")

class UpdateEnvAnalysis(UCTool, BaseReadWrite):
    name: str = "UpdateEnvAnalysis"
    description: str = """Incrementally updates the environment analysis document (07_{DUT}_env_analysis.md) with newly failed properties."""
    args_schema: Optional[ArgsSchema] = ArgUpdateEnvAnalysis

    def _run(self, dut_name: str, output_dir: str = "formal_test") -> str:
        paths = resolve_paths(dut_name, output_dir=output_dir)
        log_path, doc_path, checker_path = paths["log_file"], paths["analysis_doc"], paths["checker_file"]
        
        if not os.path.exists(log_path): return str_error(f"Error: log file not found at {log_path}")
        if not os.path.exists(doc_path): return str_error(f"Error: document not found at {doc_path}. Use InitEnvAnalysis first.")
            
        log_result = parse_avis_log(log_path)
        current_tt = set(log_result["trivially_true"])
        current_fa = set(log_result["false"]).union(set(log_result["cover_fail"]))
        
        with open(doc_path, "r", encoding="utf-8", errors="ignore") as f: doc_content = f.read()
            
        existing_tt = set(re.findall(r"###\s*<TT-\d+>\s+(\S+)", doc_content))
        existing_fa = set(re.findall(r"###\s*<FA-\d+>\s+(\S+)", doc_content))
        
        new_tt, new_fa = current_tt - existing_tt, current_fa - existing_fa
        
        if not new_tt and not new_fa:
            return str_info(f"ℹ️ No new abnormal properties found in log. Doc is up-to-date.\n   - Log TT count: {len(current_tt)}, FA count: {len(current_fa)}\n   - Doc TT count: {len(existing_tt)}, FA count: {len(existing_fa)}")
                             
        checker_content = ""
        if os.path.exists(checker_path):
            with open(checker_path, "r", encoding="utf-8", errors="ignore") as f: checker_content = f.read()
                
        def get_max_id(prefix):
            ids = [int(x) for x in re.findall(rf"###\s*<{prefix}-(\d+)>", doc_content)]
            return max(ids) if ids else 0
            
        next_tt_id, next_fa_id = get_max_id("TT") + 1, get_max_id("FA") + 1
        
        tt_additions = []
        for prop in sorted(new_tt):
            tt_additions.append(_render_tt_entry(next_tt_id, prop, checker_content))
            next_tt_id += 1
            
        fa_additions = []
        for prop in sorted(new_fa):
            ptype = "cover" if prop in log_result["cover_fail"] else "assert"
            fa_additions.append(_render_fa_entry(next_fa_id, prop, ptype, checker_content))
            next_fa_id += 1
            
        _backup_if_exists(doc_path)
        with open(doc_path, "a", encoding="utf-8") as f:
            f.write("\n\n")
            if tt_additions:
                f.write(f"<!-- {len(tt_additions)} NEW TT ENTRIES ADDED BY UpdateEnvAnalysis -->\n")
                f.write("\n".join(tt_additions))
            if fa_additions:
                f.write(f"<!-- {len(fa_additions)} NEW FA ENTRIES ADDED BY UpdateEnvAnalysis -->\n")
                f.write("\n".join(fa_additions))
                
        return str_info(f"✅ Document incrementally updated at: {doc_path}\n   - New TT entries appended: {len(new_tt)}\n   - New FA entries appended: {len(new_fa)}")

# =============================================================================
# Tool: InitTestFile
# =============================================================================

class ArgInitTestFile(BaseModel):
    dut_name: str = Field(description="DUT module name")
    analysis_doc: Optional[str] = Field(default=None, description="Path to analysis document. Defaults to output_dir/07_{dut}_env_analysis.md.")
    wrapper_path: Optional[str] = Field(default=None, description="Path to wrapper.sv. Defaults to output_dir/tests/{dut}_wrapper.sv.")
    output_path: Optional[str] = Field(default=None, description="Path to save the generated test file. Defaults to output_dir/tests/test_{dut}_counterexample.py.")
    output_dir: str = Field(default="formal_test", description="The output directory name within the workspace. Typically 'formal_test'.")

class InitTestFile(UCTool, BaseReadWrite):
    name: str = "InitTestFile"
    description: str = """Generates a counterexample test file framework (test_{DUT}_counterexample.py)."""
    args_schema: Optional[ArgsSchema] = ArgInitTestFile

    def _run(self, dut_name: str, analysis_doc: Optional[str] = None, wrapper_path: Optional[str] = None, output_path: Optional[str] = None, output_dir: str = "formal_test") -> str:
        paths = resolve_paths(dut_name, output_dir=output_dir, analysis_doc=analysis_doc, wrapper_file=wrapper_path, test_file=output_path)
        res_analysis_path, res_wrapper_path, res_output_path = paths["analysis_doc"], paths["wrapper_file"], paths["test_file"]
            
        if not os.path.exists(res_analysis_path): return str_error(f"Error: Analysis doc not found at {res_analysis_path}")
            
        rtl_bugs = extract_rtl_bug_from_analysis_doc(res_analysis_path)
        clock_name, reset_name = parse_wrapper_clock_reset(res_wrapper_path)
        
        _backup_if_exists(res_output_path)
        os.makedirs(os.path.dirname(res_output_path), exist_ok=True)
        
        dut_class = dut_name[0].upper() + dut_name[1:] if dut_name else dut_name
        lines = ['"""形式化反例测试用例 — 由 InitTestFile 自动生成"""', ""]

        if not rtl_bugs:
            lines.extend(["# 形式化验证未发现 RTL 缺陷，无需生成反例测试用例", ""])
        else:
            lines.extend([f"from {dut_name} import DUT{dut_class}", "", ""])
            for fa_id, prop_name in rtl_bugs:
                lines.extend([_render_test_function(prop_name, fa_id, clock_name, reset_name, dut_class), ""])

        with open(res_output_path, "w", encoding="utf-8") as f: f.write("\n".join(lines))
            
        msg = [f"✅ Test framework generated: {res_output_path}"]
        if rtl_bugs:
            msg.extend([f"   - RTL_BUGs found: {len(rtl_bugs)}", f"   - Clock: {clock_name or '[Unknown]'}, Reset: {reset_name or '[Unknown]'}"])
            msg.extend(f"     • test_cex_{strip_prop_prefix(prop_name).lower()}() ← {fa_id}" for fa_id, prop_name in rtl_bugs)
        else:
            msg.append("   - No RTL_BUG found, generated empty test file.")
        return str_info("\n".join(msg))

# =============================================================================
# Tool: InitBugReport
# =============================================================================

class ArgInitBugReport(BaseModel):
    dut_name: str = Field(description="DUT module name")
    analysis_doc: Optional[str] = Field(default=None, description="Path to analysis document. Defaults to output_dir/07_{dut}_env_analysis.md.")
    output_path: Optional[str] = Field(default=None, description="Path to save the generated bug report. Defaults to output_dir/04_{dut}_bug_report.md.")
    output_dir: str = Field(default="formal_test", description="The output directory name within the workspace. Typically 'formal_test'.")

class InitBugReport(UCTool, BaseReadWrite):
    name: str = "InitBugReport"
    description: str = """Generates a bug report document framework (04_{DUT}_bug_report.md)."""
    args_schema: Optional[ArgsSchema] = ArgInitBugReport

    def _run(self, dut_name: str, analysis_doc: Optional[str] = None, output_path: Optional[str] = None, output_dir: str = "formal_test") -> str:
        paths = resolve_paths(dut_name, output_dir=output_dir, analysis_doc=analysis_doc, bug_report_doc=output_path)
        res_analysis_path, res_output_path = paths["analysis_doc"], paths["bug_report_doc"]
            
        if not os.path.exists(res_analysis_path): return str_error(f"Error: Analysis doc not found at {res_analysis_path}")
            
        rtl_bugs = extract_rtl_bug_from_analysis_doc(res_analysis_path)
        _backup_if_exists(res_output_path)
        os.makedirs(os.path.dirname(res_output_path), exist_ok=True)
        
        lines = [f"# {dut_name} 形式化验证缺陷报告\n"]
        if not rtl_bugs:
            lines.append("形式化验证未发现 RTL 设计缺陷，所有属性已通过证明。\n")
        else:
            lines.extend(["> **由 InitBugReport 自动生成** — [LLM-TODO] 标记处需要人工填写\n", f"本报告记录了 {len(rtl_bugs)} 个 RTL 缺陷。\n", "---"])
            lines.extend(_render_bug_entry(i, fa_id, prop_name) for i, (fa_id, prop_name) in enumerate(rtl_bugs, start=1))
            lines.extend(["## 缺陷统计汇总\n", "| 序号 | BG 标签 | 对应属性 | 来源 | 影响范围 | 优先级 |", "|------|---------|----------|------|----------|--------|"])
            for i, (fa_id, prop_name) in enumerate(rtl_bugs, start=1):
                bg_name = f"BG-FORMAL-{i:03d}-{strip_prop_prefix(prop_name).replace('_', '-')}"
                lines.append(f"| {i} | {bg_name} | {prop_name} | {fa_id} | [LLM-TODO] | [LLM-TODO] |")
            lines.extend(["", "## 根因分析总结\n", "> [LLM-TODO: 如果多个缺陷源于同一个代码错误，请在此总结提炼出根本原因。如果缺陷互不相关，可分别简述。]\n",
                          "| 缺陷 | 行号 | 当前代码缺陷 | 修复建议 |", "|------|------|----------|----------|",
                          "| [LLM-TODO: FA_ID] | [LLM-TODO] | [LLM-TODO] | [LLM-TODO] |", "\n**修复方案总结**: [LLM-TODO: 归纳该如何修改代码以修复上述问题]\n"])
            
        with open(res_output_path, "w", encoding="utf-8") as f: f.write("\n".join(lines))
        msg = [f"✅ Bug report framework generated: {res_output_path}"]
        if rtl_bugs:
            msg.append(f"   - RTL_BUGs found: {len(rtl_bugs)}")
            msg.extend(f"     • {fa_id}: {prop_name}" for fa_id, prop_name in rtl_bugs)
        else:
            msg.append("   - No RTL_BUG found, generated empty defect declaration.")
        return str_info("\n".join(msg))
