# -*- coding: utf-8 -*-
"""AI Skills for the Formal workflow example."""

import glob
import math
import os
import re
import shutil
import subprocess
import json
from typing import Dict, List, Optional, Tuple

from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field

from ucagent.tools.fileops import BaseReadWrite
from ucagent.tools.uctool import UCTool
from ucagent.util.log import str_error, str_info

from examples.Formal.scripts.formal_tools import (
    parse_avis_log,
    extract_rtl_bug_from_analysis_doc,
    _terminate_process_tree,
)

# =============================================================================
# Tool: GenerateFormalEnv
# =============================================================================


class ArgGenerateFormalEnv(BaseModel):
    """Arguments for GenerateFormalEnv tool."""

    dut_name: str = Field(
        description="Top-level module name of the DUT (extracted from RTL file, e.g., 'main', 'traffic')."
    )
    output_dir: str = Field(
        default="formal_test",
        description="Output directory name for formal tests. Defaults to 'formal_test'."
    )
    rtl_dir: Optional[str] = Field(
        default=None,
        description="RTL source directory path. Defaults to '{workspace}/{dut_name}'."
    )
    spec_file: Optional[str] = Field(
        default=None,
        description="Path to functions_and_checks.md for parsing SVA scaffold. Defaults to '{output_dir}/03_{dut_name}_functions_and_checks.md'."
    )


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

    def _extract_ports(
        self, file_path: str
    ) -> Tuple[str, List[Tuple[str, str]], List[Tuple[str, str]]]:
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
                if hasattr(header, "parameters") and header.parameters:
                    if hasattr(header.parameters, "declarations"):
                        for decl in header.parameters.declarations:
                            if decl.kind == pyslang.SyntaxKind.ParameterDeclaration:
                                # Iterate over declarators (can be multiple per declaration)
                                if hasattr(decl, "declarators"):
                                    for declarator in decl.declarators:
                                        if hasattr(declarator, "name"):
                                            param_name = declarator.name.value
                                            # Try to get default value if present
                                            default_value = None
                                            if (
                                                hasattr(declarator, "initializer")
                                                and declarator.initializer
                                            ):
                                                default_value = str(
                                                    declarator.initializer.expr
                                                ).strip()

                                            # Build parameter declaration string
                                            if default_value:
                                                full_param_def = f"parameter {param_name} = {default_value}"
                                            else:
                                                full_param_def = (
                                                    f"parameter {param_name}"
                                                )

                                            param_info_list.append(
                                                (param_name, full_param_def)
                                            )
                                            str_info(
                                                f"Extracted parameter: {param_name} = {default_value}"
                                            )

                # Extract ports
                if (
                    hasattr(header, "ports")
                    and header.ports.kind == pyslang.SyntaxKind.AnsiPortList
                ):
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

        str_info(
            f"Extracted {len(param_info_list)} parameters and {len(port_info_list)} ports"
        )

        return port_decl_str, port_info_list, param_info_list

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
        clk_exact = frozenset(
            {
                "clk",
                "clock",
                "sys_clk",
                "i_clk",
                "i_clock",
                "pclk",
                "aclk",
                "hclk",
                "fclk",
                "clk_i",
                "clk_in",
            }
        )
        # Known reset port names (case-insensitive exact match)
        rst_exact = frozenset(
            {
                "rst_n",
                "rstn",
                "rst",
                "reset",
                "reset_n",
                "resetn",
                "sys_rst",
                "arst_n",
                "arst",
                "nreset",
                "n_reset",
                "rst_b",
                "reset_b",
                "i_rst",
                "i_reset",
                "i_rstn",
                "i_rst_n",
                "rst_ni",
                "rst_i",
            }
        )

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

    # ----- Refactored sub-methods for _run() -----

    def _build_symbolic_logic(
        self, port_info: List[Tuple[str, str]]
    ) -> Tuple[Dict[str, List[str]], str, int]:
        """Identify symbolic indexing candidates and generate helper logic.

        Returns:
            symbolic_groups: mapping of base_name -> list of index strings
            symbolic_logic:  SV comment/code block for the wrapper
            fv_idx_width:    bit-width for fv_idx signal
        """
        symbolic_groups: Dict[str, List[str]] = {}
        for port_name, _ in port_info:
            match = re.match(r"^(.*)_(\d+)$", port_name)
            if match:
                base_name, index = match.groups()
                symbolic_groups.setdefault(base_name, []).append(index)

        if not symbolic_groups:
            return {}, "", 4

        # Calculate fv_idx width
        max_index = max(
            int(idx) for indices in symbolic_groups.values() for idx in indices
        )
        fv_idx_width = max(1, int(math.ceil(math.log2(max_index + 1))))

        lines = [
            "  // =============================================================================",
            "  // Symbolic Indexing Configuration",
            "  // =============================================================================",
            f"  // Detected {len(symbolic_groups)} array structures, symbolic verification required",
            f"  // Index width: {fv_idx_width} bits (supports indices 0 to {(2**fv_idx_width) - 1})",
            "  //",
            "  // [IMPORTANT] Please add the following constraints to the checker to prevent false positives:",
            "  // 1. M_CK_FV_IDX_STABLE: assume property(@(posedge clk) disable iff(!rst_n) $stable(fv_idx));",
            "  // 2. M_CK_FV_IDX_VALID:  assume property(@(posedge clk) fv_idx < NUM_PORTS);",
            "  // 3. M_CK_FV_IDX_KNOWN:  assume property(@(posedge clk) !$isunknown(fv_idx));",
            "  //",
        ]

        for base, indices in symbolic_groups.items():
            if len(indices) <= 1:
                continue
            sorted_indices = sorted(int(idx) for idx in indices)
            # Detect data width from port definition
            width_str = ""
            for p_name, p_def in port_info:
                if p_name == f"{base}_{sorted_indices[0]}":
                    width_m = re.search(r"\[(\d+:\d+)\]", p_def)
                    if width_m:
                        width_str = f"[{width_m.group(1)}] "
                    break

            lines.append(
                f"  // Array '{base}' contains {len(indices)} elements (indices {sorted_indices[0]} to {sorted_indices[-1]})"
            )
            lines.append(f"  // wire {width_str}fv_mon_{base};")
            lines.append("  // always_comb begin")

            mux_parts = []
            for idx in sorted_indices:
                mux_parts.append(f"(fv_idx == {idx}) ? {base}_{idx}")
            mux_expr = " : ".join(mux_parts) + " : 'x;"
            lines.append(f"  //   fv_mon_{base} = {mux_expr}")
            lines.append("  // end")
            lines.append("  //")

        return symbolic_groups, "\n".join(lines), fv_idx_width

    def _build_clk_rst_remap(
        self,
        clk_port: Optional[str],
        rst_port: Optional[str],
        rst_active_low: bool,
    ) -> str:
        """Generate clock/reset remapping wire declarations for the wrapper."""
        remap_lines = []

        if clk_port is None or rst_port is None:
            missing = []
            if clk_port is None:
                missing.append("clk")
            if rst_port is None:
                missing.append("rst_n")
            remap_lines.append(
                f"  // No {'/'.join(missing)} detected in RTL "
                f"(combinational design); added for SVA sampling only"
            )

        if clk_port and clk_port != "clk":
            remap_lines.append(
                f"  // Clock remapping: RTL uses '{clk_port}', wrapper standardizes to 'clk'"
            )
            remap_lines.append(f"  wire {clk_port} = clk;")

        if rst_port and rst_port != "rst_n":
            if rst_active_low:
                remap_lines.append(
                    f"  // Reset remapping: RTL uses '{rst_port}' (active-low), mapped from 'rst_n'"
                )
                remap_lines.append(f"  wire {rst_port} = rst_n;")
            else:
                remap_lines.append(
                    f"  // Reset remapping: RTL uses '{rst_port}' (active-high), inverted from 'rst_n'"
                )
                remap_lines.append(f"  wire {rst_port} = ~rst_n;")

        return "\n".join(remap_lines)

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

    def _run(self, dut_name: str, output_dir: str = "formal_test", rtl_dir: Optional[str] = None, spec_file: Optional[str] = None) -> str:
        """Executes checker and wrapper generation, and appends SVA scaffold if spec is found."""
        # Resolve paths
        workspace = os.environ.get("UCAGENT_WORKSPACE", os.getcwd())
        if not rtl_dir:
            rtl_dir = os.path.abspath(os.path.join(workspace, dut_name))
        else:
            if not os.path.isabs(rtl_dir):
                rtl_dir = os.path.abspath(os.path.join(workspace, rtl_dir))
        
        output_file_prefix = os.path.abspath(os.path.join(workspace, output_dir, "tests", dut_name))
        
        if not spec_file:
            abs_spec = os.path.abspath(os.path.join(workspace, output_dir, f"03_{dut_name}_functions_and_checks.md"))
        else:
            if not os.path.isabs(spec_file):
                abs_spec = os.path.abspath(os.path.join(workspace, spec_file))
            else:
                abs_spec = spec_file

        str_info(f"RTL directory: {rtl_dir}")
        checker_path = f"{output_file_prefix}_checker.sv"
        wrapper_path = f"{output_file_prefix}_wrapper.sv"
        str_info(f"Output checker: {checker_path}")
        str_info(f"Output wrapper: {wrapper_path}")

        os.makedirs(os.path.dirname(checker_path), exist_ok=True)

        try:
            # Step 1: Find and parse RTL
            rtl_file_path = self._find_rtl_file(rtl_dir, dut_name)
            str_info(f"Found RTL: {rtl_file_path}")
            port_decl_str, port_info, param_info = self._extract_ports(rtl_file_path)

            # Step 2: Detect clock/reset
            clk_port, rst_port, rst_active_low = self._detect_clock_reset(port_info)

            # Step 3: Build symbolic indexing logic
            symbolic_groups, symbolic_logic, fv_idx_width = self._build_symbolic_logic(
                port_info
            )

            # Step 4: Build clock/reset remapping
            clk_rst_remap = self._build_clk_rst_remap(
                clk_port, rst_port, rst_active_low
            )

            # Step 5: Generate checker
            self._generate_checker_file(
                dut_name,
                rtl_file_path,
                port_info,
                param_info,
                clk_port,
                rst_port,
                symbolic_groups,
                fv_idx_width,
                checker_path,
            )

            # Step 6: Generate wrapper
            self._generate_wrapper_file(
                dut_name,
                port_info,
                param_info,
                clk_port,
                rst_port,
                symbolic_groups,
                symbolic_logic,
                fv_idx_width,
                clk_rst_remap,
                wrapper_path,
            )

            res_msg = (
                f"Checker skeleton created at: {checker_path}\n"
                f"Wrapper created at: {wrapper_path}\n"
                f"(Ports extracted from {rtl_file_path})"
            )
            
            # Step 7: Append SVA Scaffold if spec exists
            if os.path.exists(abs_spec):
                try:
                    with open(abs_spec, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                        
                    ck_pattern = re.compile(r"<\s*CK-([^>]+)\s*>")
                    style_pattern = re.compile(r"\(\s*Style:\s*([A-Za-z]+)\s*\)")

                    scaffolds = []
                    for line in lines:
                        ck_match = ck_pattern.search(line)
                        if ck_match:
                            ck_name = ck_match.group(1).replace("-", "_").upper()
                            desc = line.strip()
                            style_match = style_pattern.search(line)
                            style = style_match.group(1).capitalize() if style_match else "Seq"
                            
                            if style == "Assume":
                                inst_prefix = "M"
                                inst_kind = "assume"
                                clock_in_prop = True
                            elif style == "Comb":
                                inst_prefix = "A"
                                inst_kind = "assert"
                                clock_in_prop = False
                            elif style == "Cover":
                                inst_prefix = "C"
                                inst_kind = "cover"
                                clock_in_prop = True
                            else:  # Seq
                                inst_prefix = "A"
                                inst_kind = "assert"
                                clock_in_prop = True

                            prop_name = f"CK_{ck_name}"
                            inst_label = f"{inst_prefix}_{prop_name}"

                            scaffold = f"// [LLM-TODO] Style: {style} - 检测点: <CK-{ck_match.group(1)}>\n"
                            scaffold += f"// {desc}\n"
                            if clock_in_prop:
                                scaffold += f"property {prop_name};\n"
                                scaffold += f"  @(posedge clk) disable iff (!rst_n)\n"
                                scaffold += f"  1; // TODO\n"
                                scaffold += f"endproperty\n"
                                scaffold += f"{inst_label}: {inst_kind} property ({prop_name});\n"
                            else:
                                scaffold += f"property {prop_name};\n"
                                scaffold += f"  1; // TODO\n"
                                scaffold += f"endproperty\n"
                                scaffold += f"{inst_label}: {inst_kind} property (@(posedge clk) disable iff (!rst_n) {prop_name});\n"
                            scaffolds.append(scaffold)

                    if scaffolds:
                        append_text = "\n\n  // " + "="*70 + "\n"
                        append_text += "  // Auto-generated SVA Scaffold\n"
                        append_text += "  // " + "="*70 + "\n\n"
                        # Indent scaffolds properly
                        append_text += "\n".join("  " + s.replace("\n", "\n  ") for s in scaffolds)
                        append_text += "\n"
                        
                        # Read existing checker logic to inject before endmodule
                        with open(checker_path, "r", encoding="utf-8") as f:
                            checker_code = f.read()
                            
                        if "endmodule" in checker_code:
                            checker_code = checker_code.replace("endmodule", append_text + "\nendmodule")
                        else:
                            checker_code += append_text
                            
                        with open(checker_path, "w", encoding="utf-8") as f:
                            f.write(checker_code)
                            
                        res_msg += f"\n✅ Injected {len(scaffolds)} SVA scaffolds to {checker_path} based on spec."
                    else:
                        res_msg += "\nℹ️ No <CK-...> tags found in spec file. Scaffold generation skipped."
                except OSError as e:
                    res_msg += f"\n⚠️ Error reading spec or appending scaffold: {e}"
            else:
                res_msg += f"\nℹ️ Spec file not found at {abs_spec}. Scaffold generation skipped."

            return str_info(res_msg)

        except FileNotFoundError as e:
            return str_error(f"RTL file not found: {e}")
        except Exception as e:
            str_error(f"Error generating checker/wrapper: {e}")
            import traceback

            traceback.print_exc()
            return str_error(f"Error generating checker/wrapper: {e}")

# =============================================================================
# Tool: RunFormalVerification
# =============================================================================


class ArgRunFormalVerification(BaseModel):
    """Arguments for RunFormalVerification tool."""

    dut_name: str = Field(
        description="DUT name (e.g., 'Adder'). The tool will automatically execute formal_test/tests/{dut_name}_formal.tcl"
    )
    timeout: int = Field(default=300, description="Timeout (seconds), default 300s")


class RunFormalVerification(UCTool, BaseReadWrite):
    name: str = "RunFormalVerification"
    description: str = """Immediately executes formal verification and returns a results summary.

Applicable Scenarios:
- Wanting to immediately re-run verification to see results after modifying checker.sv or wrapper.sv.
- Not wanting to wait for the Check/Complete tools to trigger an automatic re-run.
- Refreshing fanin.rep after adding assertions during the coverage analysis phase.

The tool will:
1. Locate and execute the FormalMC TCL script based on dut_name.
2. Parse avis.log and return statistics for pass/fail/trivially_true properties.
3. List all failed property names for quick troubleshooting.

Example Usage:
  RunFormalVerification(dut_name="Adder")
"""
    args_schema: Optional[ArgsSchema] = ArgRunFormalVerification

    def _resolve_tcl_path(self, workspace: str, dut_name: str) -> str:
        """Resolve TCL path from fixed Formal Makefile output layout."""
        script_name = f"{dut_name}_formal.tcl"
        candidates = [
            os.path.abspath(os.path.join(workspace, "formal_test", "tests", script_name)),
            os.path.abspath(os.path.join(workspace, "unity_tests", "tests", script_name)),
        ]

        for p in candidates:
            if os.path.exists(p):
                return p
        return candidates[0]

    def _run(self, dut_name: str, timeout: int = 300) -> str:
        workspace = os.environ.get("UCAGENT_WORKSPACE", os.getcwd())
        tcl_path = self._resolve_tcl_path(workspace, dut_name=dut_name)

        if not os.path.exists(tcl_path):
            return str_error(
                f"TCL script does not exist: {tcl_path}\n"
                f"Please run GenerateFormalScript first to generate {dut_name}_formal.tcl"
            )

        exec_dir = os.path.dirname(tcl_path)
        adapter = get_adapter()
        log_path = os.path.join(exec_dir, adapter.log_filename())

        cmd = adapter.build_command(tcl_path, exec_dir)
        str_info(f"Executing command: {' '.join(cmd)}")
        from examples.Formal.scripts.formal_tools import run_formal_command_sync
        
        success, stdout_log, stderr_log, err_msg = run_formal_command_sync(cmd, exec_dir, timeout)
        
        if not success:
            if "not found" in err_msg:
                return str_error(f"❌ '{cmd[0]}' command not found, please ensure the tool is installed and in your PATH")
            elif "Timeout" in err_msg:
                return str_error(f"❌ Verification timed out (>{timeout}s), please check if constraints are too weak or design state space is too large")
            else:
                return str_error(
                    f"❌ Formal verification returned non-zero exit code: {err_msg}\n"
                    f"stderr: {stderr_log[:500] if stderr_log else '(empty)'}"
                )

        # Use the shared log parsing function
        parsed = parse_avis_log(log_path)

        total = sum(len(parsed[k]) for k in parsed)
        if total == 0:
            return str_error(
                f"❌ Verification completed but no property results found in log, please check {log_path}"
            )

        lines = [
            f"✅ {adapter.tool_display_name()} execution completed, log: {log_path}",
            "",
            "📊 Verification Results Summary:",
            f"  Assert Pass        : {len(parsed['pass'])}",
            f"  Assert TRIVIALLY_TRUE : {len(parsed['trivially_true'])}",
            f"  Assert Fail        : {len(parsed['false'])}",
            f"  Cover  Pass        : {len(parsed['cover_pass'])}",
            f"  Cover  Fail        : {len(parsed['cover_fail'])}",
        ]

        if parsed["false"]:
            lines.append(f"\n❌ Failed Assert Properties ({len(parsed['false'])}):")
            for p in parsed["false"]:
                lines.append(f"  - {p}")

        if parsed["trivially_true"]:
            lines.append(
                f"\n⚠️  TRIVIALLY_TRUE Properties ({len(parsed['trivially_true'])} - environment over-constrained):"
            )
            for p in parsed["trivially_true"]:
                lines.append(f"  - {p}")

        if parsed["cover_fail"]:
            lines.append(f"\n⚠️  Failed Cover Properties ({len(parsed['cover_fail'])}):")
            for p in parsed["cover_fail"]:
                lines.append(f"  - {p}")

        return str_info("\n".join(lines))


# =============================================================================
# Helper for Bug Output Backup
# =============================================================================

def _backup_if_exists(filepath: str) -> None:
    """If file exists, copy to .bak and print message."""
    if os.path.exists(filepath):
        bak = filepath + ".bak"
        shutil.copy2(filepath, bak)
        str_info(f"Backed up: {filepath} -> {bak}")


# =============================================================================
# Tool: InitEnvAnalysis
# =============================================================================

class ArgInitEnvAnalysis(BaseModel):
    """Arguments for InitEnvAnalysis tool."""

    dut_name: str = Field(description="DUT module name")
    log_path: Optional[str] = Field(default=None, description="Path to avis.log. If not provided, defaults to output_dir/tests/avis.log.")
    output_path: Optional[str] = Field(default=None, description="Path to save the generated analysis document. If not provided, defaults to output_dir/07_{dut_name}_env_analysis.md.")
    output_dir: str = Field(default="formal_test", description="The output directory name within the workspace. Typically 'formal_test'.")


class InitEnvAnalysis(UCTool, BaseReadWrite):
    name: str = "InitEnvAnalysis"
    description: str = """Generates the environment analysis document framework (07_{DUT}_env_analysis.md) by parsing avis.log.
    
Usage:
1. Provide dut_name: DUT module name.
2. (Optional) Provide output_dir: The output directory name, defaulting to "formal_test".
3. (Optional) Provide log_path and output_path to override default locations.

The tool will parse avis.log and generate a Markdown file with stubs for each TRIVIALLY_TRUE and FALSE property.
Existing output files will be backed up as .bak.
"""
    args_schema: Optional[ArgsSchema] = ArgInitEnvAnalysis

    def _extract_prop_code(self, prop_name: str, checker_content: str) -> str:
        """Extract the SVA property definition from checker code."""
        if not checker_content:
            return f"  // [LLM-TODO]: 无法读取 checker.sv，请手动提取 {prop_name} 的代码"
        
        # Try to find property definition block
        pattern = re.compile(rf"(property\s+(?:(?:A|M|C)_)?{re.escape(prop_name)}[\s;].*?endproperty)", re.DOTALL)
        match = pattern.search(checker_content)
        if match:
            # Indent the matching code logic nicely
            return "\n".join("  " + line for line in match.group(1).split("\n"))
            
        # Try finding inline assert/assume/cover if not a property block
        pattern_inline = re.compile(rf"(?:assert|assume|cover)\s+property\s*\([^;]*{re.escape(prop_name)}[^;]*\)\s*;")
        match = pattern_inline.search(checker_content)
        if match:
            return f"  {match.group(0)}"

        # If we can't find it directly, try looking for just the property name definition
        short_name = prop_name
        for prefix in ["A_CK_", "M_CK_", "C_CK_", "CK_"]:
            if short_name.startswith(prefix):
                short_name = short_name[len(prefix):]
                break
        
        pattern_short = re.compile(rf"(property\s+.*?{re.escape(short_name)}.*?;.*?endproperty)", re.DOTALL)
        match = pattern_short.search(checker_content)
        if match:
            return "\n".join("  " + line for line in match.group(1).split("\n"))

        return f"  // [LLM-TODO]: 无法自动提取 {prop_name} 的代码，请从 checker.sv 手动提取"

    def _generate_tt_entry(self, idx: int, prop_name: str, checker_content: str) -> str:
        sva_code = self._extract_prop_code(prop_name, checker_content)
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

    def _generate_fa_entry(self, idx: int, prop_name: str, prop_type: str, checker_content: str) -> str:
        sva_code = self._extract_prop_code(prop_name, checker_content)
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

    def _run(self, dut_name: str, log_path: Optional[str] = None, output_path: Optional[str] = None, output_dir: str = "formal_test") -> str:
        workspace = os.environ.get("UCAGENT_WORKSPACE", os.getcwd())
        
        # Default paths
        res_log_path = log_path or os.path.join(workspace, output_dir, "tests", "avis.log")
        res_output_path = output_path or os.path.join(workspace, output_dir, f"07_{dut_name}_env_analysis.md")
        checker_path = os.path.join(workspace, output_dir, "tests", f"{dut_name}_checker.sv")
        
        if not os.path.isabs(res_log_path):
            res_log_path = os.path.abspath(os.path.join(workspace, res_log_path))
        if not os.path.isabs(res_output_path):
            res_output_path = os.path.abspath(os.path.join(workspace, res_output_path))
            
        if not os.path.exists(res_log_path):
            return str_error(f"Error: log file not found at {res_log_path}")
            
        log_result = parse_avis_log(res_log_path)
        _backup_if_exists(res_output_path)
        os.makedirs(os.path.dirname(res_output_path), exist_ok=True)
        
        # Read checker.sv for code extraction
        checker_content = ""
        if os.path.exists(checker_path):
            with open(checker_path, "r", encoding="utf-8", errors="ignore") as f:
                checker_content = f.read()
        
        n_pass = len(log_result["pass"])
        n_tt = len(log_result["trivially_true"])
        n_false = len(log_result["false"])
        n_cover_pass = len(log_result["cover_pass"])
        n_cover_fail = len(log_result["cover_fail"])
        n_total = n_pass + n_tt + n_false + n_cover_pass + n_cover_fail

        lines: List[str] = []
        lines.append(f"# {dut_name} 形式化验证环境分析报告\n")
        lines.append("> **由 InitEnvAnalysis 自动生成** — [LLM-TODO] 标记处需要人工填写\n")
        lines.append("---\n")

        lines.append("## 1. 验证结果概览\n")
        lines.append("| 类型 | 数量 |")
        lines.append("|------|------|")
        lines.append(f"| Assert Pass | {n_pass} |")
        lines.append(f"| Assert TRIVIALLY_TRUE | {n_tt} |")
        lines.append(f"| Assert Fail | {n_false} |")
        lines.append(f"| Cover Pass | {n_cover_pass} |")
        lines.append(f"| Cover Fail | {n_cover_fail} |")
        lines.append(f"| **Total** | **{n_total}** |")
        lines.append("")
        lines.append("---\n")

        lines.append("## 2. TRIVIALLY_TRUE 属性分析\n")
        if n_tt == 0:
            lines.append("> 无 TRIVIALLY_TRUE 属性，验证环境约束健康。\n")
        else:
            lines.append(f"> 共 {n_tt} 个 TRIVIALLY_TRUE 属性需要分析。\n")
            for i, prop in enumerate(log_result["trivially_true"], start=1):
                lines.append(self._generate_tt_entry(i, prop, checker_content))
        lines.append("---\n")

        lines.append("## 3. FALSE 属性分析\n")
        false_props = [(p, "assert") for p in log_result["false"]]
        false_props += [(p, "cover") for p in log_result["cover_fail"]]
        n_fa = len(false_props)
        if n_fa == 0:
            lines.append("> 无 FALSE 属性，所有断言和覆盖属性均已通过。\n")
        else:
            lines.append(f"> 共 {n_fa} 个 FALSE 属性需要分析。\n")
            for i, (prop, ptype) in enumerate(false_props, start=1):
                lines.append(self._generate_fa_entry(i, prop, ptype, checker_content))
        
        with open(res_output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
            
        return str_info(
            f"✅ Document generated at: {res_output_path}\n"
            f"   - TRIVIALLY_TRUE entries: {n_tt}\n"
            f"   - FALSE entries: {n_fa}\n"
            f"   - Total [LLM-TODO] remaining: {n_tt + n_fa}"
        )


# =============================================================================
# Tool: UpdateEnvAnalysis
# =============================================================================

class ArgUpdateEnvAnalysis(BaseModel):
    """Arguments for UpdateEnvAnalysis tool."""

    dut_name: str = Field(description="DUT module name")
    output_dir: str = Field(default="formal_test", description="The output directory name within the workspace. Typically 'formal_test'.")


class UpdateEnvAnalysis(UCTool, BaseReadWrite):
    name: str = "UpdateEnvAnalysis"
    description: str = """Incrementally updates the environment analysis document (07_{DUT}_env_analysis.md) with newly failed properties.
    
Usage:
1. Provide dut_name: DUT module name.
2. (Optional) Provide output_dir: The output directory name, defaulting to "formal_test".

Use this tool during the environment debugging iteration (Stage 7). After fixing some assumes and re-running formal,
there might be new properties failing. This tool will parse the NEW avis.log, find properties that are NOT in the existing doc,
and append them to the existing analysis document. It preserves all your previous analysis and judgments.
"""
    args_schema: Optional[ArgsSchema] = ArgUpdateEnvAnalysis

    def _run(self, dut_name: str, output_dir: str = "formal_test") -> str:
        workspace = os.environ.get("UCAGENT_WORKSPACE", os.getcwd())
        
        log_path = os.path.abspath(os.path.join(workspace, output_dir, "tests", "avis.log"))
        doc_path = os.path.abspath(os.path.join(workspace, output_dir, f"07_{dut_name}_env_analysis.md"))
        checker_path = os.path.abspath(os.path.join(workspace, output_dir, "tests", f"{dut_name}_checker.sv"))
        
        if not os.path.exists(log_path):
            return str_error(f"Error: log file not found at {log_path}")
        if not os.path.exists(doc_path):
            return str_error(f"Error: document not found at {doc_path}. Use InitEnvAnalysis first.")
            
        # Parse current log
        log_result = parse_avis_log(log_path)
        current_tt = set(log_result["trivially_true"])
        current_fa = set(log_result["false"]).union(set(log_result["cover_fail"]))
        
        # Read existing doc
        with open(doc_path, "r", encoding="utf-8", errors="ignore") as f:
            doc_content = f.read()
            
        # Find existing entries using regex
        existing_tt = set(re.findall(r"###\s*<TT-\d+>\s+(\S+)", doc_content))
        existing_fa = set(re.findall(r"###\s*<FA-\d+>\s+(\S+)", doc_content))
        
        # Determine new properties
        new_tt = current_tt - existing_tt
        new_fa = current_fa - existing_fa
        
        if not new_tt and not new_fa:
            return str_info(f"ℹ️ No new abnormal properties found in log. Doc is up-to-date.\n"
                            f"   - Log TT count: {len(current_tt)}, FA count: {len(current_fa)}\n"
                            f"   - Doc TT count: {len(existing_tt)}, FA count: {len(existing_fa)}")
                            
        # Read checker content for code extraction
        checker_content = ""
        if os.path.exists(checker_path):
            with open(checker_path, "r", encoding="utf-8", errors="ignore") as f:
                checker_content = f.read()
                
        # To reuse the generation methods, we'll instantiate InitEnvAnalysis
        init_tool = InitEnvAnalysis()
        
        # Calculate next max IDs
        def get_max_id(prefix):
            ids = [int(x) for x in re.findall(rf"###\s*<{prefix}-(\d+)>", doc_content)]
            return max(ids) if ids else 0
            
        next_tt_id = get_max_id("TT") + 1
        next_fa_id = get_max_id("FA") + 1
        
        # Prepare additions
        tt_additions = []
        for prop in sorted(new_tt):
            tt_additions.append(init_tool._generate_tt_entry(next_tt_id, prop, checker_content))
            next_tt_id += 1
            
        fa_additions = []
        for prop in sorted(new_fa):
            ptype = "cover" if prop in log_result["cover_fail"] else "assert"
            fa_additions.append(init_tool._generate_fa_entry(next_fa_id, prop, ptype, checker_content))
            next_fa_id += 1
            
        # Append to document (naively to the end)
        _backup_if_exists(doc_path)
        with open(doc_path, "a", encoding="utf-8") as f:
            f.write("\n\n")
            if tt_additions:
                f.write(f"<!-- {len(tt_additions)} NEW TT ENTRIES ADDED BY UpdateEnvAnalysis -->\n")
                f.write("\n".join(tt_additions))
            if fa_additions:
                f.write(f"<!-- {len(fa_additions)} NEW FA ENTRIES ADDED BY UpdateEnvAnalysis -->\n")
                f.write("\n".join(fa_additions))
                
        return str_info(f"✅ Document incrementally updated at: {doc_path}\n"
                        f"   - New TT entries appended: {len(new_tt)}\n"
                        f"   - New FA entries appended: {len(new_fa)}")


# =============================================================================
# Tool: InitTestFile
# =============================================================================

class ArgInitTestFile(BaseModel):
    """Arguments for InitTestFile tool."""

    dut_name: str = Field(description="DUT module name")
    analysis_doc: Optional[str] = Field(default=None, description="Path to analysis document. Defaults to output_dir/07_{dut}_env_analysis.md.")
    wrapper_path: Optional[str] = Field(default=None, description="Path to wrapper.sv. Defaults to output_dir/tests/{dut}_wrapper.sv.")
    output_path: Optional[str] = Field(default=None, description="Path to save the generated test file. Defaults to output_dir/tests/test_{dut}_counterexample.py.")
    output_dir: str = Field(default="formal_test", description="The output directory name within the workspace. Typically 'formal_test'.")


class InitTestFile(UCTool, BaseReadWrite):
    name: str = "InitTestFile"
    description: str = """Generates a counterexample test file framework (test_{DUT}_counterexample.py).
    
Usage:
1. Provide dut_name: DUT module name.
2. (Optional) Provide output_dir. Defaults to "formal_test".
3. (Optional) Override path parameters if needed.

The tool parses the environment analysis document to find properties tagged as RTL_BUG, extracting clock and reset info from wrapper.sv, and generates Python test function stubs for UCAgent.
"""
    args_schema: Optional[ArgsSchema] = ArgInitTestFile

    def _parse_wrapper_clock_reset(self, wrapper_path: str) -> Tuple[Optional[str], Optional[str]]:
        clock_name = None
        reset_name = None

        if not os.path.exists(wrapper_path):
            return clock_name, reset_name

        with open(wrapper_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        clk_match = re.search(r"wire\s+clk\s*=\s*(\w+)\s*;", content)
        if clk_match:
            clock_name = clk_match.group(1)

        rst_match = re.search(r"wire\s+rst_n\s*=\s*(\w+)\s*;", content)
        if rst_match:
            reset_name = rst_match.group(1)

        if clock_name is None:
            for pat in [r"input\s+(?:wire\s+)?(\w*cl(?:oc)?k\w*)", r"input\s+(?:wire\s+)?(clk\w*)"]:
                m = re.search(pat, content, re.IGNORECASE)
                if m:
                    clock_name = m.group(1)
                    break

        if reset_name is None:
            for pat in [r"input\s+(?:wire\s+)?(\w*res(?:et)?\w*)", r"input\s+(?:wire\s+)?(rst\w*)"]:
                m = re.search(pat, content, re.IGNORECASE)
                if m:
                    reset_name = m.group(1)
                    break

        return clock_name, reset_name

    def _prop_to_func_name(self, prop_name: str) -> str:
        name = prop_name.lower()
        for prefix in ("a_", "m_", "c_"):
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        return f"test_cex_{name}"

    def _generate_test_function(self, prop_name: str, fa_id: str, clock_name: Optional[str], reset_name: Optional[str], dut_class: str) -> str:
        func_name = self._prop_to_func_name(prop_name)
        lines = []
        lines.append(f"def {func_name}():")
        lines.append(f'    \"\"\"反例测试: {prop_name} (来源: {fa_id})')
        lines.append(f"    [LLM-TODO]: 补充 Bug 描述、反例条件、预期/实际行为")
        lines.append(f'    \"\"\"')
        lines.append(f"    dut = DUT{dut_class}()")

        if clock_name:
            lines.append(f"    dut.InitClock('{clock_name}')")
            lines.append(f"    # 复位序列")
            if reset_name:
                lines.append(f"    dut.{reset_name}.value = 0")
                lines.append(f"    dut.Step(5)")
                lines.append(f"    dut.{reset_name}.value = 1")
            else:
                lines.append(f"    # [LLM-TODO]: 复位序列")
                lines.append(f"    dut.Step(5)")
            lines.append(f"    dut.Step(1)")

        lines.append(f"")
        lines.append(f"    # [LLM-TODO]: 按反例时序驱动引脚")
        lines.append(f"    dut.Step(1)")
        lines.append(f"")
        lines.append(f"    # [LLM-TODO]: 断言检查")
        lines.append(f"    # assert dut.yyy.value == expected")
        lines.append(f"")
        lines.append(f"    dut.Finish()")
        lines.append(f"")
        return "\n".join(lines)

    def _run(self, dut_name: str, analysis_doc: Optional[str] = None, wrapper_path: Optional[str] = None, output_path: Optional[str] = None, output_dir: str = "formal_test") -> str:
        workspace = os.environ.get("UCAGENT_WORKSPACE", os.getcwd())
        
        # Default paths
        res_analysis_path = analysis_doc or os.path.join(workspace, output_dir, f"07_{dut_name}_env_analysis.md")
        res_wrapper_path = wrapper_path or os.path.join(workspace, output_dir, "tests", f"{dut_name}_wrapper.sv")
        res_output_path = output_path or os.path.join(workspace, output_dir, "tests", f"test_{dut_name}_counterexample.py")
        
        if not os.path.isabs(res_analysis_path):
            res_analysis_path = os.path.abspath(os.path.join(workspace, res_analysis_path))
        if not os.path.isabs(res_wrapper_path):
            res_wrapper_path = os.path.abspath(os.path.join(workspace, res_wrapper_path))
        if not os.path.isabs(res_output_path):
            res_output_path = os.path.abspath(os.path.join(workspace, res_output_path))
            
        if not os.path.exists(res_analysis_path):
            return str_error(f"Error: Analysis doc not found at {res_analysis_path}")
            
        rtl_bugs = extract_rtl_bug_from_analysis_doc(res_analysis_path)
        clock_name, reset_name = self._parse_wrapper_clock_reset(res_wrapper_path)
        
        _backup_if_exists(res_output_path)
        os.makedirs(os.path.dirname(res_output_path), exist_ok=True)
        
        dut_class = dut_name[0].upper() + dut_name[1:] if dut_name else dut_name

        lines = []
        lines.append(f'\"\"\"形式化反例测试用例 — 由 InitTestFile 自动生成\"\"\"')
        lines.append(f"")

        if not rtl_bugs:
            lines.append(f"# 形式化验证未发现 RTL 缺陷，无需生成反例测试用例")
            lines.append(f"")
        else:
            lines.append(f"from {dut_name} import DUT{dut_class}")
            lines.append(f"")
            lines.append(f"")

            for fa_id, prop_name in rtl_bugs:
                lines.append(self._generate_test_function(prop_name, fa_id, clock_name, reset_name, dut_class))
                lines.append(f"")

        with open(res_output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
            
        msg = [f"✅ Test framework generated: {res_output_path}"]
        if rtl_bugs:
            msg.append(f"   - RTL_BUGs found: {len(rtl_bugs)}")
            msg.append(f"   - Clock: {clock_name or '[Unknown]'}, Reset: {reset_name or '[Unknown]'}")
            for fa_id, prop_name in rtl_bugs:
                msg.append(f"     • {self._prop_to_func_name(prop_name)}() ← {fa_id}")
        else:
            msg.append("   - No RTL_BUG found, generated empty test file.")
            
        return str_info("\n".join(msg))


# =============================================================================
# Tool: InitBugReport
# =============================================================================

class ArgInitBugReport(BaseModel):
    """Arguments for InitBugReport tool."""

    dut_name: str = Field(description="DUT module name")
    analysis_doc: Optional[str] = Field(default=None, description="Path to analysis document. Defaults to output_dir/07_{dut}_env_analysis.md.")
    output_path: Optional[str] = Field(default=None, description="Path to save the generated bug report. Defaults to output_dir/04_{dut}_bug_report.md.")
    output_dir: str = Field(default="formal_test", description="The output directory name within the workspace. Typically 'formal_test'.")


class InitBugReport(UCTool, BaseReadWrite):
    name: str = "InitBugReport"
    description: str = """Generates a bug report document framework (04_{DUT}_bug_report.md).
    
Usage:
1. Provide dut_name: DUT module name.
2. (Optional) Provide output_dir. Defaults to "formal_test".
3. (Optional) Override path parameters if needed.

The tool parses the environment analysis document to extract RTL_BUGs and creates a markdown bug report ready to be filled out.
"""
    args_schema: Optional[ArgsSchema] = ArgInitBugReport

    def _generate_bug_entry(self, idx: int, fa_id: str, prop_name: str) -> str:
        ck_part = prop_name
        for prefix in ("A_CK_", "M_CK_", "C_CK_", "A_", "M_", "C_"):
            if ck_part.startswith(prefix):
                ck_part = ck_part[len(prefix):]
                break
        bg_name = f"BG-FORMAL-{idx:03d}-{ck_part.replace('_', '-')}"

        return f"""## Failed Property: `{prop_name}`

### [LLM-TODO: <FG-???> 关联的功能组]

### [LLM-TODO: <FC-???> 关联的功能点]

### <{bg_name}> [LLM-TODO: 缺陷标题]

<CK-{ck_part.replace('_', '-')}>

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

    def _run(self, dut_name: str, analysis_doc: Optional[str] = None, output_path: Optional[str] = None, output_dir: str = "formal_test") -> str:
        workspace = os.environ.get("UCAGENT_WORKSPACE", os.getcwd())
        
        # Default paths
        res_analysis_path = analysis_doc or os.path.join(workspace, output_dir, f"07_{dut_name}_env_analysis.md")
        res_output_path = output_path or os.path.join(workspace, output_dir, f"04_{dut_name}_bug_report.md")
        
        if not os.path.isabs(res_analysis_path):
            res_analysis_path = os.path.abspath(os.path.join(workspace, res_analysis_path))
        if not os.path.isabs(res_output_path):
            res_output_path = os.path.abspath(os.path.join(workspace, res_output_path))
            
        if not os.path.exists(res_analysis_path):
            return str_error(f"Error: Analysis doc not found at {res_analysis_path}")
            
        rtl_bugs = extract_rtl_bug_from_analysis_doc(res_analysis_path)
        _backup_if_exists(res_output_path)
        os.makedirs(os.path.dirname(res_output_path), exist_ok=True)
        
        lines: List[str] = []
        lines.append(f"# {dut_name} 形式化验证缺陷报告\n")

        if not rtl_bugs:
            lines.append("形式化验证未发现 RTL 设计缺陷，所有属性已通过证明。\n")
        else:
            lines.append("> **由 InitBugReport 自动生成** — [LLM-TODO] 标记处需要人工填写\n")
            lines.append(f"本报告记录了 {len(rtl_bugs)} 个 RTL 缺陷。\n")
            lines.append("---\n")

            for i, (fa_id, prop_name) in enumerate(rtl_bugs, start=1):
                lines.append(self._generate_bug_entry(i, fa_id, prop_name))

            lines.append("## 缺陷统计汇总\n")
            lines.append("| 序号 | BG 标签 | 对应属性 | 来源 | 影响范围 | 优先级 |")
            lines.append("|------|---------|----------|------|----------|--------|")
            for i, (fa_id, prop_name) in enumerate(rtl_bugs, start=1):
                ck_part = prop_name
                for prefix in ("A_CK_", "M_CK_", "C_CK_", "A_", "M_", "C_"):
                    if ck_part.startswith(prefix):
                        ck_part = ck_part[len(prefix):]
                        break
                bg_name = f"BG-FORMAL-{i:03d}-{ck_part.replace('_', '-')}"
                lines.append(f"| {i} | {bg_name} | {prop_name} | {fa_id} | [LLM-TODO] | [LLM-TODO] |")
            lines.append("")
            
            lines.append("## 根因分析总结\n")
            lines.append("> [LLM-TODO: 如果多个缺陷源于同一个代码错误，请在此总结提炼出根本原因。如果缺陷互不相关，可分别简述。]\n")
            lines.append("| 缺陷 | 行号 | 当前代码缺陷 | 修复建议 |")
            lines.append("|------|------|----------|----------|")
            lines.append("| [LLM-TODO: FA_ID] | [LLM-TODO] | [LLM-TODO] | [LLM-TODO] |")
            lines.append("\n**修复方案总结**: [LLM-TODO: 归纳该如何修改代码以修复上述问题]\n")
            
        with open(res_output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
            
        msg = [f"✅ Bug report framework generated: {res_output_path}"]
        if rtl_bugs:
            msg.append(f"   - RTL_BUGs found: {len(rtl_bugs)}")
            for fa_id, prop_name in rtl_bugs:
                msg.append(f"     • {fa_id}: {prop_name}")
        else:
            msg.append("   - No RTL_BUG found, generated empty defect declaration.")
            
        return str_info("\n".join(msg))
