# -*- coding: utf-8 -*-
"""Formal verification tools for the Formal workflow example."""

import os
import re
import glob
import subprocess
from typing import Optional, List, Tuple
import pyslang
import psutil
from ucagent.tools.uctool import UCTool
from ucagent.tools.fileops import BaseReadWrite
from ucagent.util.log import info, str_info, str_error, str_data
from pydantic import BaseModel, Field
from langchain_core.tools.base import ArgsSchema

__all__ = ["GenerateChecker", "GenerateFormalScript", "RunFormalVerification"]

class ArgGenerateChecker(BaseModel):
    """Arguments for GenerateChecker tool.
    
    使用说明：
    1. dut_name: RTL文件中定义的顶层模块名称（通过 'module xxx' 提取）
    2. output_file: 输出路径前缀（例如 '{OUT}/tests/{DUT}'），会生成 {OUT}/tests/{DUT}_checker.sv 和 {OUT}/tests/{DUT}_wrapper.sv
    3. rtl_dir: RTL文件所在目录，默认为 FILE_PATH
    """
    dut_name: str = Field(
        description="DUT的顶层模块名称（从RTL文件中提取，例如 'main'、'traffic'）"
    )
    output_file: str = Field(
        description="输出路径前缀（例如 '{OUT}/tests/{DUT}'），会生成 {DUT}_checker.sv 和 {DUT}_wrapper.sv"
    )
    rtl_dir: str = Field(
        default="{FILE_PATH}",
        description="RTL源码目录路径（默认使用FILE_PATH）"
    )

class GenerateChecker(UCTool, BaseReadWrite):
    name: str = "GenerateChecker"
    description: str = """生成形式化验证环境的 checker.sv 和 wrapper.sv 文件。

使用方法：
1. 提供 dut_name: RTL文件中定义的顶层模块名
2. 提供 output_file: 输出路径前缀（例如 '{OUT}/tests/{DUT}'），会生成 {DUT}_checker.sv 和 {DUT}_wrapper.sv
3. rtl_dir: 可选，默认为 FILE_PATH

工具会：
- 在 rtl_dir 目录下查找包含 dut_name 模块的 .v/.sv 文件
- 解析RTL提取所有端口和参数
- 生成 {output_file}_checker.sv 和 {output_file}_wrapper.sv

使用示例：
- GenerateChecker(dut_name="main", output_file="{OUT}/tests/main")
- GenerateChecker(dut_name="traffic", output_file="{OUT}/tests/traffic", rtl_dir="traffic")
"""
    args_schema: Optional[ArgsSchema] = ArgGenerateChecker

    def _find_rtl_file(self, rtl_dir: str, dut_name: str) -> str:
        """在指定目录查找包含dut_name模块的RTL文件"""
        str_info(f"Searching for RTL file for module '{dut_name}' in: {rtl_dir}")
        
        if not os.path.isdir(rtl_dir):
            raise FileNotFoundError(f"RTL directory does not exist: {rtl_dir}")
        
        # 查找所有 .v/.sv 文件
        all_files = []
        for ext in ['*.v', '*.sv']:
            all_files.extend(glob.glob(os.path.join(rtl_dir, ext)))
        
        str_info(f"Found {len(all_files)} RTL files")
        
        # 解析每个文件，查找模块名匹配
        for file_path in all_files:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    module_pattern = rf'\bmodule\s+{re.escape(dut_name)}\b'
                    if re.search(module_pattern, content):
                        str_info(f"Found RTL: {file_path}")
                        return file_path
            except Exception as e:
                str_error(f"Error parsing {file_path}: {e}")
                continue
        
        # 如果只有一个文件，直接使用
        if len(all_files) == 1:
            str_info(f"Using only RTL file: {all_files[0]}")
            return all_files[0]
        
        raise FileNotFoundError(
            f"Could not find RTL source for module '{dut_name}' in '{rtl_dir}'. "
            f"Found files: {all_files if all_files else 'none'}"
        )

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

    def _detect_clock_reset(
        self, port_info: List[Tuple[str, str]]
    ) -> Tuple[Optional[str], Optional[str], bool]:
        """Detect clock and reset ports from port_info.

        Returns:
            clk_port:       name of the detected clock port (None if not found)
            rst_port:       name of the detected reset port (None if not found)
            rst_active_low: True if the reset is active-low, False if active-high
        """
        # Known clock port names (case-insensitive exact match)
        clk_exact = frozenset({
            "clk", "clock", "sys_clk", "i_clk", "i_clock",
            "pclk", "aclk", "hclk", "fclk", "clk_i", "clk_in",
        })
        # Known reset port names (case-insensitive exact match)
        rst_exact = frozenset({
            "rst_n", "rstn", "rst", "reset", "reset_n", "resetn",
            "sys_rst", "arst_n", "arst", "nreset", "n_reset",
            "rst_b", "reset_b", "i_rst", "i_reset", "i_rstn", "i_rst_n",
            "rst_ni", "rst_i",
        })

        clk_port: Optional[str] = None
        rst_port: Optional[str] = None

        # First pass: exact name match (case-insensitive)
        for port_name, _ in port_info:
            lower = port_name.lower()
            if clk_port is None and lower in clk_exact:
                clk_port = port_name
            if rst_port is None and lower in rst_exact:
                rst_port = port_name

        # Second pass: substring fallback (only if not yet found)
        if clk_port is None or rst_port is None:
            for port_name, _ in port_info:
                lower = port_name.lower()
                if clk_port is None and ("clk" in lower or "clock" in lower):
                    clk_port = port_name
                if rst_port is None and ("rst" in lower or "reset" in lower):
                    rst_port = port_name

        # Determine reset polarity (active-low is most common in modern RTL)
        rst_active_low = True
        if rst_port:
            lower_rst = rst_port.lower()
            # Plain names without a negation suffix/prefix are active-high
            if lower_rst in ("rst", "reset", "arst", "sys_rst", "i_rst", "i_reset"):
                rst_active_low = False

        str_info(
            f"Detected clock: '{clk_port}', reset: '{rst_port}' "
            f"(active-{'low' if rst_active_low else 'high'})"
        )
        return clk_port, rst_port, rst_active_low

    def _run(self, dut_name: str, output_file: str, rtl_dir: str) -> str:
        """执行 checker 和 wrapper 生成"""
        # Resolve relative paths against workspace so the tool works regardless
        # of the current working directory.
        workspace = getattr(self, "workspace", os.getcwd())
        if not os.path.isabs(rtl_dir):
            rtl_dir = os.path.abspath(os.path.join(workspace, rtl_dir))
        if not os.path.isabs(output_file):
            output_file = os.path.abspath(os.path.join(workspace, output_file))

        str_info(f"RTL directory: {rtl_dir}")
        
        # output_file 是路径前缀，生成 {output_file}_checker.sv 和 {output_file}_wrapper.sv
        checker_path = f"{output_file}_checker.sv"
        wrapper_path = f"{output_file}_wrapper.sv"
        str_info(f"Output checker: {checker_path}")
        str_info(f"Output wrapper: {wrapper_path}")

        os.makedirs(os.path.dirname(checker_path), exist_ok=True)

        try:
            # 查找 RTL 文件
            rtl_file_path = self._find_rtl_file(rtl_dir, dut_name)
            str_info(f"Found RTL: {rtl_file_path}")
            
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

            # Detect clock and reset ports for normalization
            clk_port, rst_port, rst_active_low = self._detect_clock_reset(port_info)

            # 1. Generate Checker
            # Convert all ports to input, normalizing clock/reset names to 'clk'/'rst_n'
            checker_ports = []
            # Prepend standard ports if RTL has no clock/reset (pure combinational design)
            if clk_port is None:
                checker_ports.append("input clk")
            if rst_port is None:
                checker_ports.append("input rst_n")
            for port_name, port_def in port_info:
                checker_port = re.sub(r'^(input|output|inout)\s+', 'input ', port_def, count=1)
                # Normalize clock port name to standard 'clk'
                if port_name == clk_port and port_name != "clk":
                    checker_port = re.sub(rf'\b{re.escape(port_name)}\s*$', 'clk', checker_port)
                # Normalize reset port name to standard 'rst_n'
                elif port_name == rst_port and port_name != "rst_n":
                    checker_port = re.sub(rf'\b{re.escape(port_name)}\s*$', 'rst_n', checker_port)
                checker_ports.append(checker_port)
            checker_port_decl_str = ",\n  ".join(checker_ports)

            checker_template = self._load_template("checker_template.sv")
            checker_code = checker_template.format(
                dut_name=dut_name,
                rtl_file_path=rtl_file_path,
                param_decl=param_decl_str,
                port_decl=checker_port_decl_str
            )
            with open(checker_path, 'w', encoding='utf-8') as f:
                f.write(checker_code)
            str_info(f"Checker generated at: {checker_path}")

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

            # Build clock/reset remapping wires for wrapper
            # The wrapper interface always uses standard 'clk'/'rst_n'; internal wires
            # map them to the RTL-specific names so DUT connections remain unchanged.
            clk_rst_remap_lines = []
            if clk_port is None or rst_port is None:
                missing = []
                if clk_port is None:
                    missing.append("clk")
                if rst_port is None:
                    missing.append("rst_n")
                clk_rst_remap_lines.append(
                    f"  // No {'/' .join(missing)} detected in RTL "
                    f"(combinational design); added for SVA sampling only"
                )
            if clk_port and clk_port != "clk":
                clk_rst_remap_lines.append(
                    f"  // Clock remapping: RTL uses '{clk_port}', wrapper standardizes to 'clk'"
                )
                clk_rst_remap_lines.append(f"  wire {clk_port} = clk;")
            if rst_port and rst_port != "rst_n":
                if rst_active_low:
                    clk_rst_remap_lines.append(
                        f"  // Reset remapping: RTL uses '{rst_port}' (active-low), mapped from 'rst_n'"
                    )
                    clk_rst_remap_lines.append(f"  wire {rst_port} = rst_n;")
                else:
                    clk_rst_remap_lines.append(
                        f"  // Reset remapping: RTL uses '{rst_port}' (active-high), inverted from 'rst_n'"
                    )
                    clk_rst_remap_lines.append(f"  wire {rst_port} = ~rst_n;")
            clk_rst_remap = "\n".join(clk_rst_remap_lines)

            # Wrapper ports: all DUT ports with clock/reset normalized to 'clk'/'rst_n'
            wrapper_ports = []
            # If RTL has no clock/reset, prepend standard ports for SVA sampling
            if clk_port is None:
                wrapper_ports.append("input clk")
            if rst_port is None:
                wrapper_ports.append("input rst_n")
            for port_name, port_def in port_info:
                if port_name == clk_port and port_name != "clk":
                    normalized = re.sub(rf'\b{re.escape(port_name)}\s*$', 'clk', port_def)
                    wrapper_ports.append(normalized)
                elif port_name == rst_port and port_name != "rst_n":
                    normalized = re.sub(rf'\b{re.escape(port_name)}\s*$', 'rst_n', port_def)
                    wrapper_ports.append(normalized)
                else:
                    wrapper_ports.append(port_def)
            # Add fv_idx to wrapper if symbols detected
            if symbolic_groups:
                wrapper_ports.append(f"input [{fv_idx_width-1}:0] fv_idx")
            wrapper_ports_str = ",\n  ".join(wrapper_ports)

            # DUT Instance connections: use RTL original names (resolved via remapping wires)
            dut_conns = [f".{name}({name})" for name, _ in port_info]
            dut_conns_str = ",\n    ".join(dut_conns)

            # Checker Instance connections: always use normalized 'clk'/'rst_n'
            checker_conns = []
            # If RTL has no clock/reset, connect the wrapper-added ports first
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
                clk_rst_remap=clk_rst_remap,
                dut_name_wrapper=f"{dut_name}_wrapper"
            )
            # Inject symbolic logic into template placeholder
            wrapper_code = wrapper_code.replace("// [LLM-TODO]: If the design has array-like storage, define fv_idx and mux.", symbolic_logic)
            
            with open(wrapper_path, 'w', encoding='utf-8') as f:
                f.write(wrapper_code)
            str_info(f"Wrapper generated at: {wrapper_path}")

            return str_info(f"Checker skeleton created at: {checker_path}\nWrapper created at: {wrapper_path}\n(Ports extracted from {rtl_file_path})")

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
    rtl_dir: str = Field(description="RTL源码所在目录路径")

class GenerateFormalScript(UCTool, BaseReadWrite):
    name: str = "GenerateFormalScript"
    description: str = "2. tcl脚本创建：创建 `formal.tcl`，使用Wrapper作为顶层。"
    args_schema: Optional[ArgsSchema] = ArgGenerateFormalScript

    def _run(self, dut_name: str, checker_file: str, output_file: str, rtl_dir: str) -> str:
        workspace = getattr(self, "workspace", os.getcwd())
        if not os.path.isabs(output_file):
            real_output_path = os.path.abspath(os.path.join(workspace, output_file))
        else:
            real_output_path = output_file
        if not os.path.isabs(rtl_dir):
            rtl_dir = os.path.abspath(os.path.join(workspace, rtl_dir))

        os.makedirs(os.path.dirname(real_output_path), exist_ok=True)

        # 计算相对路径：从TCL脚本所在目录到RTL目录
        script_dir_from_ws = os.path.dirname(real_output_path)
        rel_rtl_dir = os.path.relpath(rtl_dir, script_dir_from_ws)
        
        str_info(f"Script directory (from workspace): {script_dir_from_ws}")
        str_info(f"RTL directory: {rtl_dir}")
        str_info(f"Relative RTL path: {rel_rtl_dir}")
        
        checker_basename = os.path.basename(checker_file)
        wrapper_basename = f"{dut_name}_wrapper.sv"

        # Use wrapper as top
        top_module = f"{dut_name}_wrapper"

        # 使用默认的时钟和复位配置
        clock_config = "def_clk clk"
        reset_config = "def_rst rst_n -value 0"

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


class ArgRunFormalVerification(BaseModel):
    """Arguments for RunFormalVerification tool."""
    tcl_script: str = Field(
        description="TCL脚本路径（相对workspace），例如 'output/unity_tests/tests/Adder_formal.tcl'"
    )
    timeout: int = Field(
        default=300,
        description="超时时间（秒），默认300秒"
    )


class RunFormalVerification(UCTool, BaseReadWrite):
    name: str = "RunFormalVerification"
    description: str = """立即执行形式化验证并返回结果摘要。

适用场景：
- 修改 checker.sv 或 wrapper.sv 后，想立即重新运行验证查看结果
- 不想等待 Check/Complete 工具触发自动重跑
- 在覆盖率分析阶段补充断言后刷新 fanin.rep

工具会：
1. 执行指定的 FormalMC TCL 脚本
2. 解析 avis.log，返回 pass/fail/trivially_true 属性统计
3. 列出所有失败属性名称，便于快速定位问题

使用示例：
  RunFormalVerification(tcl_script="output/unity_tests/tests/Adder_formal.tcl")
"""
    args_schema: Optional[ArgsSchema] = ArgRunFormalVerification

    def _parse_log_summary(self, log_path: str) -> dict:
        """解析 avis.log，返回属性结果统计。"""
        result = {
            "pass": [], "trivially_true": [], "false": [],
            "cover_pass": [], "cover_fail": []
        }
        if not os.path.exists(log_path):
            return result

        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # 优先从汇总表格解析
        table_pattern = re.compile(
            r'^\s*\d+\s+(checker_inst\.[\w.]+)\s*:\s*(TrivT|Fail|Pass|Undec)',
            re.MULTILINE
        )
        for m in table_pattern.finditer(content):
            prop = m.group(1).split('.')[-1]
            status = m.group(2)
            is_cover = prop.startswith('C_') or 'COVER' in prop.upper()
            if status == 'TrivT':
                if not is_cover:
                    result["trivially_true"].append(prop)
            elif status == 'Fail':
                (result["cover_fail"] if is_cover else result["false"]).append(prop)
            elif status == 'Pass':
                (result["cover_pass"] if is_cover else result["pass"]).append(prop)

        # 回退：从 Info-P016 逐行解析
        if not any([result["pass"], result["trivially_true"], result["false"]]):
            p016 = re.compile(
                r'Info-P016:\s*property\s+(checker_inst\.[\w.]+)\s+is\s+(TRIVIALLY_TRUE|TRUE|FALSE)',
                re.IGNORECASE
            )
            for m in p016.finditer(content):
                prop = m.group(1).split('.')[-1]
                status = m.group(2).upper()
                is_cover = prop.startswith('C_') or 'COVER' in prop.upper()
                if status == 'TRIVIALLY_TRUE':
                    if not is_cover:
                        result["trivially_true"].append(prop)
                elif status == 'FALSE':
                    (result["cover_fail"] if is_cover else result["false"]).append(prop)
                elif status == 'TRUE':
                    (result["cover_pass"] if is_cover else result["pass"]).append(prop)

        return result

    def _run(self, tcl_script: str, timeout: int = 300) -> str:
        workspace = getattr(self, "workspace", os.getcwd())
        if not os.path.isabs(tcl_script):
            tcl_path = os.path.abspath(os.path.join(workspace, tcl_script))
        else:
            tcl_path = tcl_script

        if not os.path.exists(tcl_path):
            return str_error(f"TCL脚本不存在：{tcl_path}")

        exec_dir = os.path.dirname(tcl_path)
        log_path = os.path.join(exec_dir, "avis.log")

        cmd = ["FormalMC", "-f", tcl_path, "-override", "-work_dir", exec_dir]
        str_info(f"执行命令：{' '.join(cmd)}")

        try:
            worker = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=exec_dir
            )
            try:
                stdout, stderr = worker.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    worker.terminate()
                    psutil.wait_procs([psutil.Process(worker.pid)], timeout=3)
                except Exception:
                    pass
                worker.kill()
                worker.communicate()
                return str_error(f"❌ 验证超时（>{timeout}s），请检查约束是否过弱或设计状态空间过大")

            if worker.returncode != 0:
                return str_error(
                    f"❌ FormalMC 返回非零退出码 {worker.returncode}\n"
                    f"stderr: {stderr[:500] if stderr else '(empty)'}"
                )
        except FileNotFoundError:
            return str_error("❌ 未找到 FormalMC 命令，请确认工具已安装并在 PATH 中")

        # 解析日志
        parsed = self._parse_log_summary(log_path)

        total = (len(parsed["pass"]) + len(parsed["trivially_true"]) +
                 len(parsed["false"]) + len(parsed["cover_pass"]) + len(parsed["cover_fail"]))
        if total == 0:
            return str_error(f"❌ 验证执行完毕但日志中未找到属性结果，请检查 {log_path}")

        lines = [
            f"✅ FormalMC 执行完毕，日志：{log_path}",
            f"",
            f"📊 验证结果摘要：",
            f"  Assert Pass        : {len(parsed['pass'])}",
            f"  Assert TRIVIALLY_TRUE : {len(parsed['trivially_true'])}",
            f"  Assert Fail        : {len(parsed['false'])}",
            f"  Cover  Pass        : {len(parsed['cover_pass'])}",
            f"  Cover  Fail        : {len(parsed['cover_fail'])}",
        ]

        if parsed["false"]:
            lines.append(f"\n❌ 失败的 Assert 属性（{len(parsed['false'])} 个）：")
            for p in parsed["false"]:
                lines.append(f"  - {p}")

        if parsed["trivially_true"]:
            lines.append(f"\n⚠️  TRIVIALLY_TRUE 属性（{len(parsed['trivially_true'])} 个，环境过约束）：")
            for p in parsed["trivially_true"]:
                lines.append(f"  - {p}")

        if parsed["cover_fail"]:
            lines.append(f"\n⚠️  失败的 Cover 属性（{len(parsed['cover_fail'])} 个）：")
            for p in parsed["cover_fail"]:
                lines.append(f"  - {p}")

        return str_info("\n".join(lines))