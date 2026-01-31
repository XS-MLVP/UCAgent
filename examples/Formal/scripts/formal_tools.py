# -*- coding: utf-8 -*-
"""Formal verification tools for the Formal workflow example."""

import os
import re
import glob
from typing import Optional, List, Tuple
import pyslang
from ucagent.tools.uctool import UCTool
from ucagent.tools.fileops import BaseReadWrite
from ucagent.util.log import info, str_info, str_error, str_data
from pydantic import BaseModel, Field
from langchain_core.tools.base import ArgsSchema

__all__ = ["GenerateChecker", "GenerateFormalScript"]

class ArgGenerateChecker(BaseModel):
    """Arguments for GenerateChecker tool."""
    dut_name: str = Field(description="DUT模块名称")
    output_file: str = Field(description="输出的checker.sv文件路径")
    rtl_dir: str = Field(default="{DUT}_RTL", description="RTL源码所在的文件夹路径")

class GenerateChecker(UCTool, BaseReadWrite):
    name: str = "GenerateChecker"
    description: str = "1. checker创建：自动读取RTL文件，创建 `checker.sv` 和 `wrapper.sv`。"
    args_schema: Optional[ArgsSchema] = ArgGenerateChecker

    def _find_rtl_file(self, rtl_dir: str, dut_name: str) -> str:
        # Search for .v or .sv files
        patterns = [
            os.path.join(rtl_dir, f"{dut_name}.v"),
            os.path.join(rtl_dir, f"{dut_name}.sv")
        ]
        for p in patterns:
            if os.path.exists(p):
                return p
            abs_p = os.path.abspath(p)
            if os.path.exists(abs_p):
                return abs_p
        
        # Fallback: search anywhere in rtl_dir
        search_pattern = os.path.join(rtl_dir, f"{dut_name}.*")
        files = glob.glob(search_pattern)
        for f in files:
            if f.endswith('.v') or f.endswith('.sv'):
                return f
        
        raise FileNotFoundError(f"Could not find RTL source for {dut_name} in {rtl_dir}")

    def _extract_ports(self, file_path: str) -> Tuple[str, List[Tuple[str, str]], List[Tuple[str, str]]]:
        """
        Extract ports and parameters from RTL file using pyslang.

        Returns:
            1. Full port declaration string (for checker definition).
            2. List of (port_name, port_definition) tuples (for wrapper instantiation).
            3. List of (param_name, param_definition) tuples (for checker parameters).
        """
        try:
            tree = pyslang.SyntaxTree.fromFile(file_path)
        except Exception as e:
            str_error(f"Failed to parse RTL file with pyslang: {e}")
            return f"// Error parsing file: {e}", [], []

        port_info_list = []
        param_info_list = []

        # Find the first module declaration
        for member in tree.root.members:
            if member.kind == pyslang.SyntaxKind.ModuleDeclaration:
                header = member.header

                # Extract parameters from header.parameters.declarations
                if hasattr(header, 'parameters') and header.parameters:
                    if hasattr(header.parameters, 'declarations'):
                        for decl in header.parameters.declarations:
                            if decl.kind == pyslang.SyntaxKind.ParameterDeclaration:
                                # Iterate over declarators (can be multiple per declaration)
                                if hasattr(decl, 'declarators'):
                                    for declarator in decl.declarators:
                                        if hasattr(declarator, 'name'):
                                            param_name = declarator.name.value
                                            # Try to get default value if present
                                            default_value = None
                                            if hasattr(declarator, 'initializer') and declarator.initializer:
                                                default_value = str(declarator.initializer.expr).strip()

                                            # Build parameter declaration string
                                            if default_value:
                                                full_param_def = f"parameter {param_name} = {default_value}"
                                            else:
                                                full_param_def = f"parameter {param_name}"

                                            param_info_list.append((param_name, full_param_def))
                                            str_info(f"Extracted parameter: {param_name} = {default_value}")

                # Extract ports
                if hasattr(header, 'ports') and header.ports.kind == pyslang.SyntaxKind.AnsiPortList:
                    for port in header.ports.ports:
                        # Get port name and full declaration from string representation
                        if port.kind == pyslang.SyntaxKind.ImplicitAnsiPort:
                            port_name = port.declarator.name.value
                            # Get full port declaration from string representation
                            full_def = str(port).strip()
                            port_info_list.append((port_name, full_def))
                            str_info(f"Extracted port: {port_name}")
                break

        if not port_info_list:
            str_error("No ports found in module")
            return "// Error: No ports found", [], []

        # Create port declaration string
        port_decl_str = ",\n  ".join([info[1] for info in port_info_list])

        str_info(f"Extracted {len(param_info_list)} parameters and {len(port_info_list)} ports")

        return port_decl_str, port_info_list, param_info_list

    def _load_template(self, template_name: str) -> str:
        """Load template file from templates directory."""
        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        template_path = os.path.join(template_dir, template_name)
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            str_error(f"Failed to load template {template_name}: {e}")
            raise

    def _run(self, dut_name: str, output_file: str, rtl_dir: str) -> str:
        # Simplify: assume workspace is always cwd/output
        workspace = os.path.join(os.getcwd(), "output")
        real_path = os.path.abspath(os.path.join(workspace, output_file))
        wrapper_path = os.path.join(os.path.dirname(real_path), f"{dut_name}_wrapper.sv")

        os.makedirs(os.path.dirname(real_path), exist_ok=True)

        try:
            if "{DUT}" in rtl_dir:
                rtl_dir = rtl_dir.replace("{DUT}", dut_name)

            rtl_file_path = self._find_rtl_file(rtl_dir, dut_name)
            str_info(f"Found RTL file: {rtl_file_path}")
            
            port_decl_str, port_info, param_info = self._extract_ports(rtl_file_path)

            # Build parameter declaration for checker
            if param_info:
                param_decl_str = " #(\n  " + ",\n  ".join([info[1] for info in param_info]) + "\n)"
                param_inst_str = " #(\n    " + ",\n    ".join([f".{name}({name})" for name, _ in param_info]) + "\n  )"
                str_info(f"Generated parameter declaration for checker: {param_decl_str}")
                str_info(f"Generated parameter instantiation: {param_inst_str}")
            else:
                param_decl_str = ""
                param_inst_str = ""
                str_info("No parameters found in DUT")

            # 1. Generate Checker
            # Convert all ports to input for checker
            checker_ports = []
            for port_name, port_def in port_info:
                # Replace direction with 'input' while preserving the rest
                # This handles cases like "input [WIDTH-1:0] a", "output [WIDTH-2:0] sum", etc.
                # Use regex to replace the direction at the start
                import re
                # Match the direction at the beginning (input/output/inout)
                checker_port = re.sub(r'^(input|output|inout)\s+', 'input ', port_def, count=1)
                checker_ports.append(checker_port)
            checker_port_decl_str = ",\n  ".join(checker_ports)

            checker_template = self._load_template("checker_template.sv")
            checker_code = checker_template.format(
                dut_name=dut_name,
                rtl_file_path=rtl_file_path,
                param_decl=param_decl_str,
                port_decl=checker_port_decl_str
            )
            with open(real_path, 'w', encoding='utf-8') as f:
                f.write(checker_code)
            str_info(f"Checker generated at: {real_path}")

            # 2. Generate Wrapper
            # Identify potential symbolic indexing candidates (ports with _0, _1...)
            symbolic_groups = {}
            for port_name, _ in port_info:
                match = re.match(r'^(.*)_(\d+)$', port_name)
                if match:
                    base_name, index = match.groups()
                    if base_name not in symbolic_groups:
                        symbolic_groups[base_name] = []
                    symbolic_groups[base_name].append(index)

            # Calculate fv_idx width based on max index
            fv_idx_width = 4  # Default width
            if symbolic_groups:
                max_index = 0
                for indices in symbolic_groups.values():
                    for idx_str in indices:
                        idx = int(idx_str)
                        if idx > max_index:
                            max_index = idx
                # Calculate minimum bits needed to represent max_index
                import math
                fv_idx_width = max(1, int(math.ceil(math.log2(max_index + 1))))

            symbolic_logic = ""
            if symbolic_groups:
                symbolic_logic += "  // =============================================================================\n"
                symbolic_logic += "  // 符号化索引配置 (Symbolic Indexing Configuration)\n"
                symbolic_logic += "  // =============================================================================\n"
                symbolic_logic += f"  // 检测到 {len(symbolic_groups)} 个数组结构，需要符号化验证\n"
                symbolic_logic += f"  // 索引位宽: {fv_idx_width} bits (支持索引 0-{(2**fv_idx_width)-1})\n"
                symbolic_logic += "  //\n"
                symbolic_logic += "  // 【重要】请在 checker 中添加以下约束以防止假阳性：\n"
                symbolic_logic += "  // 1. M_CK_FV_IDX_STABLE: assume property(@(posedge clk) disable iff(!rst_n) $stable(fv_idx));\n"
                symbolic_logic += "  // 2. M_CK_FV_IDX_VALID:  assume property(@(posedge clk) fv_idx < NUM_PORTS);\n"
                symbolic_logic += "  // 3. M_CK_FV_IDX_KNOWN:  assume property(@(posedge clk) !$isunknown(fv_idx));\n"
                symbolic_logic += "  //\n"

                for base, indices in symbolic_groups.items():
                    if len(indices) > 1:
                        sorted_indices = sorted([int(idx) for idx in indices])
                        max_idx = sorted_indices[-1]
                        # Extract data width from port_info
                        width_match = ""
                        for p_name, p_def in port_info:
                            if p_name == f"{base}_{sorted_indices[0]}":
                                width_m = re.search(r'\[(\d+:\d+)\]', p_def)
                                if width_m:
                                    width_match = f"[{width_m.group(1)}] "
                                break

                        symbolic_logic += f"  // 数组 '{base}' 包含 {len(indices)} 个元素 (索引 {sorted_indices[0]} 到 {max_idx})\n"
                        symbolic_logic += f"  // wire {width_match}fv_mon_{base};\n"
                        symbolic_logic += f"  // always_comb begin\n"
                        symbolic_logic += f"  //   fv_mon_{base} = "
                        for i, idx in enumerate(sorted_indices):
                            symbolic_logic += f"(fv_idx == {idx}) ? {base}_{idx}"
                            if i < len(sorted_indices) - 1:
                                symbolic_logic += " : "
                            else:
                                symbolic_logic += " : 'x;\n"
                        symbolic_logic += f"  // end\n"
                        symbolic_logic += f"  //\n"

            # Wrapper ports: all DUT ports
            wrapper_ports = [info[1] for info in port_info]
            # Add fv_idx to wrapper if symbols detected
            if symbolic_groups:
                wrapper_ports.append(f"input [{fv_idx_width-1}:0] fv_idx")
            wrapper_ports_str = ",\n  ".join(wrapper_ports)

            # DUT Instance connections
            dut_conns = [f".{name}({name})" for name, _ in port_info]
            dut_conns_str = ",\n    ".join(dut_conns)

            # Checker Instance connections
            checker_conns = [f".{name}({name})" for name, _ in port_info]
            if symbolic_groups:
                checker_conns.append(f".fv_idx(fv_idx)")
                # Placeholder for monitored signals
                for base, indices in symbolic_groups.items():
                    if len(indices) > 1:
                        checker_conns.append(f".fv_mon_{base}(fv_mon_{base})")
            checker_conns_str = ",\n    ".join(checker_conns)

            # Wrapper parameter declaration (same as DUT)
            if param_info:
                wrapper_params_str = " #(\n  " + ",\n  ".join([info[1] for info in param_info]) + "\n)"
                str_info(f"Generated parameter declaration for wrapper: {wrapper_params_str}")
            else:
                wrapper_params_str = ""

            # Generate wrapper code
            wrapper_template = self._load_template("wrapper_template.sv")
            wrapper_code = wrapper_template.format(
                dut_name=dut_name,
                param_decl=wrapper_params_str,
                port_decl=wrapper_ports_str,
                param_inst=param_inst_str,
                dut_conns=dut_conns_str,
                checker_conns=checker_conns_str,
                dut_name_wrapper=f"{dut_name}_wrapper"
            )
            # Inject symbolic logic into template placeholder
            wrapper_code = wrapper_code.replace("// [LLM-TODO]: If the design has array-like storage, define fv_idx and mux.", symbolic_logic)
            
            with open(wrapper_path, 'w', encoding='utf-8') as f:
                f.write(wrapper_code)
            str_info(f"Wrapper generated at: {wrapper_path}")

            return str_info(f"Checker skeleton created at: {real_path}\nWrapper created at: {wrapper_path}\n(Ports extracted from {rtl_file_path})")

        except Exception as e:
            str_error(f"Error generating checker/wrapper: {e}")
            import traceback
            traceback.print_exc()
            return str_error(f"Error generating checker/wrapper: {e}")



class ArgGenerateFormalScript(BaseModel):
    """Arguments for GenerateFormalScript tool."""
    dut_name: str = Field(description="DUT模块名称")
    checker_file: str = Field(description="checker.sv文件路径")
    output_file: str = Field(description="输出的.tcl文件路径")
    rtl_path: str = Field(default="{DUT}_RTL", description="RTL源码路径")
    clock_config: str = Field(default="def_clk clk", description="时钟配置")
    reset_config: str = Field(default="def_rst rst_n -value 0", description="复位配置")

class GenerateFormalScript(UCTool, BaseReadWrite):
    name: str = "GenerateFormalScript"
    description: str = "2. tcl脚本创建：创建 `formal.tcl`，使用Wrapper作为顶层。"
    args_schema: Optional[ArgsSchema] = ArgGenerateFormalScript

    def _run(self, dut_name: str, checker_file: str, output_file: str, rtl_path: str, clock_config: str, reset_config: str) -> str:
        workspace = os.path.join(os.getcwd(), "output")
        real_output_path = os.path.abspath(os.path.join(workspace, output_file))

        os.makedirs(os.path.dirname(real_output_path), exist_ok=True)

        script_dir_from_ws = os.path.dirname(output_file)
        rtl_path_from_ws = rtl_path.format(DUT=dut_name)
        rel_rtl_dir = os.path.relpath(rtl_path_from_ws, script_dir_from_ws)
        
        checker_basename = os.path.basename(checker_file)
        wrapper_basename = f"{dut_name}_wrapper.sv"

        # Use wrapper as top
        top_module = f"{dut_name}_wrapper"

        # Load template and generate script
        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        template_path = os.path.join(template_dir, "formal_script_template.tcl")
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                tcl_template = f.read()
        except Exception as e:
            return str_error(f"Failed to load template: {e}")

        tcl_script = tcl_template.format(
            dut_name=dut_name,
            rel_rtl_dir=rel_rtl_dir,
            checker_basename=checker_basename,
            wrapper_basename=wrapper_basename,
            top_module=top_module,
            clock_config=clock_config,
            reset_config=reset_config
        )
        
        try:
            with open(real_output_path, 'w', encoding='utf-8') as f:
                f.write(tcl_script)
            return str_info(f"TCL script created at: {real_output_path}")
        except Exception as e:
            return str_error(f"Error writing to {output_file}: {e}")