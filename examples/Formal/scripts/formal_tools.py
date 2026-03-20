# -*- coding: utf-8 -*-
"""Formal verification tools for the Formal workflow example."""

import glob
import math
import os
import re
import subprocess
from typing import Dict, List, Optional, Tuple

import psutil
import pyslang
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field

from ucagent.tools.fileops import BaseReadWrite
from ucagent.tools.uctool import UCTool
from ucagent.util.log import str_error, str_info

__all__ = ["GenerateChecker", "GenerateFormalScript", "RunFormalVerification"]


# =============================================================================
# Shared Utilities
# =============================================================================


def parse_avis_log(log_path: str) -> Dict[str, list]:
    """Parse avis.log and return property result statistics.

    This is the single source of truth for log parsing, shared by
    ``RunFormalVerification`` and all Checker classes that need to
    inspect verification results.

    Returns a dict with the following keys:
        pass            – list of assert properties that passed
        trivially_true  – list of assert TRIVIALLY_TRUE properties
        false           – list of assert properties that failed
        cover_pass      – list of cover properties that passed
        cover_fail      – list of cover properties that failed
    """
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
    # Format: "  12  checker_inst.A_CK_XXX  :  TrivT"
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


def _terminate_process_tree(proc: subprocess.Popen, timeout: int = 5) -> None:
    """Gracefully terminate a process and all its children."""
    try:
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
        # Terminate children first, then parent
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        try:
            parent.terminate()
        except psutil.NoSuchProcess:
            pass
        # Wait for all to exit
        gone, alive = psutil.wait_procs(children + [parent], timeout=timeout)
        # Force-kill any survivors
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass
    except Exception:
        # Last resort
        try:
            proc.kill()
        except Exception:
            pass


# =============================================================================
# Tool: GenerateChecker
# =============================================================================


class ArgGenerateChecker(BaseModel):
    """Arguments for GenerateChecker tool.

    Usage Instructions:
    1. dut_name: Top-level module name defined in the RTL file (extracted via 'module xxx').
    2. output_file: Output path prefix (e.g., '{OUT}/tests/{DUT}'); generates {OUT}/tests/{DUT}_checker.sv and {OUT}/tests/{DUT}_wrapper.sv.
    3. rtl_dir: Directory containing RTL files, defaults to FILE_PATH.
    """

    dut_name: str = Field(
        description="Top-level module name of the DUT (extracted from RTL file, e.g., 'main', 'traffic')."
    )
    output_file: str = Field(
        description="Output path prefix (e.g., '{OUT}/tests/{DUT}'); generates {DUT}_checker.sv and {DUT}_wrapper.sv."
    )
    rtl_dir: str = Field(
        default="{FILE_PATH}", description="RTL source directory path (defaults to FILE_PATH)."
    )


class GenerateChecker(UCTool, BaseReadWrite):
    name: str = "GenerateChecker"
    description: str = """Generates checker.sv and wrapper.sv files for the formal verification environment.

Usage:
1. Provide dut_name: Top-level module name defined in the RTL file.
2. Provide output_file: Output path prefix (e.g., '{OUT}/tests/{DUT}'); generates {DUT}_checker.sv and {DUT}_wrapper.sv.
3. rtl_dir: Optional, defaults to FILE_PATH.

The tool will:
- Search for .v/.sv files containing the dut_name module in the rtl_dir directory.
- Parse RTL to extract all ports and parameters.
- Generate {output_file}_checker.sv and {output_file}_wrapper.sv.

Example Usage:
- GenerateChecker(dut_name="main", output_file="{OUT}/tests/main")
- GenerateChecker(dut_name="traffic", output_file="{OUT}/tests/traffic", rtl_dir="traffic")
"""
    args_schema: Optional[ArgsSchema] = ArgGenerateChecker

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
        """Load template file from templates directory."""
        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        template_path = os.path.join(template_dir, template_name)
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError as e:
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

        checker_template = self._load_template("checker_template.sv")
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
        wrapper_template = self._load_template("wrapper_template.sv")
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

    def _run(self, dut_name: str, output_file: str, rtl_dir: str) -> str:
        """Executes checker and wrapper generation."""
        # Resolve paths
        workspace = getattr(self, "workspace", os.getcwd())
        if not os.path.isabs(rtl_dir):
            rtl_dir = os.path.abspath(os.path.join(workspace, rtl_dir))
        if not os.path.isabs(output_file):
            output_file = os.path.abspath(os.path.join(workspace, output_file))

        str_info(f"RTL directory: {rtl_dir}")
        checker_path = f"{output_file}_checker.sv"
        wrapper_path = f"{output_file}_wrapper.sv"
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

            return str_info(
                f"Checker skeleton created at: {checker_path}\n"
                f"Wrapper created at: {wrapper_path}\n"
                f"(Ports extracted from {rtl_file_path})"
            )

        except FileNotFoundError as e:
            return str_error(f"RTL file not found: {e}")
        except Exception as e:
            str_error(f"Error generating checker/wrapper: {e}")
            import traceback

            traceback.print_exc()
            return str_error(f"Error generating checker/wrapper: {e}")


# =============================================================================
# Tool: GenerateFormalScript
# =============================================================================


class ArgGenerateFormalScript(BaseModel):
    """Arguments for GenerateFormalScript tool."""

    dut_name: str = Field(description="DUT module name")
    checker_file: str = Field(description="Path to checker.sv file")
    rtl_dir: str = Field(description="Directory containing RTL source")


class GenerateFormalScript(UCTool, BaseReadWrite):
    name: str = "GenerateFormalScript"
    description: str = """Generates a TCL script file for formal verification.

Usage:
1. Provide dut_name: DUT module name.
2. Provide checker_file: Path to checker.sv file.
3. Provide rtl_dir: Directory containing RTL source.

The tool will:
- Generate a TCL verification script in FormalMC format.
- Use the Wrapper as the top-level module ({dut_name}_wrapper).
- Automatically configure RTL file paths, clock, and reset.
- Write script to output/unity_tests/tests/{dut_name}_formal.tcl under workspace.
- Include prove, show_prop -summary, and fanin coverage analysis commands.

Example Usage:
  GenerateFormalScript(
      dut_name="main",
      checker_file="{OUT}/tests/main_checker.sv",
      rtl_dir="{FILE_PATH}"
  )
"""
    args_schema: Optional[ArgsSchema] = ArgGenerateFormalScript

    def _run(self, dut_name: str, checker_file: str, rtl_dir: str) -> str:
        workspace = getattr(self, "workspace", os.getcwd())
        real_output_path = os.path.abspath(
            os.path.join(
                workspace,
                "output",
                "unity_tests",
                "tests",
                f"{dut_name}_formal.tcl",
            )
        )
        if not os.path.isabs(rtl_dir):
            rtl_dir = os.path.abspath(os.path.join(workspace, rtl_dir))

        os.makedirs(os.path.dirname(real_output_path), exist_ok=True)

        # Calculate relative path: from TCL script directory to RTL directory
        script_dir_from_ws = os.path.dirname(real_output_path)
        rel_rtl_dir = os.path.relpath(rtl_dir, script_dir_from_ws)

        str_info(f"Script directory (from workspace): {script_dir_from_ws}")
        str_info(f"RTL directory: {rtl_dir}")
        str_info(f"Relative RTL path: {rel_rtl_dir}")

        checker_basename = os.path.basename(checker_file)
        wrapper_basename = f"{dut_name}_wrapper.sv"

        # Use wrapper as top
        top_module = f"{dut_name}_wrapper"

        # Use default clock and reset configuration
        clock_config = "def_clk clk"
        reset_config = "def_rst rst_n -value 0"

        # Load template and generate script
        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        template_path = os.path.join(template_dir, "formal_script_template.tcl")
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                tcl_template = f.read()
        except OSError as e:
            return str_error(f"Failed to load template: {e}")

        tcl_script = tcl_template.format(
            dut_name=dut_name,
            rel_rtl_dir=rel_rtl_dir,
            checker_basename=checker_basename,
            wrapper_basename=wrapper_basename,
            top_module=top_module,
            clock_config=clock_config,
            reset_config=reset_config,
            basedir_pattern="basedir pattern",
        )

        # Fix the basedir pattern definition (add braces around it)
        tcl_script = tcl_script.replace("basedir pattern", "{basedir pattern}")

        try:
            with open(real_output_path, "w", encoding="utf-8") as f:
                f.write(tcl_script)
            return str_info(f"TCL script created at: {real_output_path}")
        except OSError as e:
            return str_error(f"Error writing to {real_output_path}: {e}")


# =============================================================================
# Tool: RunFormalVerification
# =============================================================================


class ArgRunFormalVerification(BaseModel):
    """Arguments for RunFormalVerification tool."""

    dut_name: str = Field(
        description="DUT name (e.g., 'Adder'). The tool will automatically execute output/unity_tests/tests/{dut_name}_formal.tcl"
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
            os.path.abspath(
                os.path.join(workspace, "output", "unity_tests", "tests", script_name)
            ),
            # os.path.abspath(os.path.join(workspace, "unity_tests", "tests", script_name)),
            # os.path.abspath(os.path.join(workspace, "..", "output", "unity_tests", "tests", script_name)),
        ]

        for p in candidates:
            if os.path.exists(p):
                return p
        return candidates[0]

    def _run(self, dut_name: str, timeout: int = 300) -> str:
        workspace = getattr(self, "workspace", os.getcwd())
        tcl_path = self._resolve_tcl_path(workspace, dut_name=dut_name)

        if not os.path.exists(tcl_path):
            return str_error(
                f"TCL script does not exist: {tcl_path}\n"
                f"Please run GenerateFormalScript first to generate {dut_name}_formal.tcl"
            )

        exec_dir = os.path.dirname(tcl_path)
        log_path = os.path.join(exec_dir, "avis.log")

        cmd = ["FormalMC", "-f", tcl_path, "-override", "-work_dir", exec_dir]
        str_info(f"Executing command: {' '.join(cmd)}")

        try:
            worker = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=exec_dir,
            )
            try:
                stdout, stderr = worker.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                _terminate_process_tree(worker)
                worker.communicate()
                return str_error(
                    f"❌ Verification timed out (>{timeout}s), please check if constraints are too weak or design state space is too large"
                )

            if worker.returncode != 0:
                return str_error(
                    f"❌ FormalMC returned non-zero exit code {worker.returncode}\n"
                    f"stderr: {stderr[:500] if stderr else '(empty)'}"
                )
        except FileNotFoundError:
            return str_error("❌ FormalMC command not found, please ensure the tool is installed and in your PATH")

        # Use the shared log parsing function
        parsed = parse_avis_log(log_path)

        total = sum(len(parsed[k]) for k in parsed)
        if total == 0:
            return str_error(
                f"❌ Verification completed but no property results found in log, please check {log_path}"
            )

        lines = [
            f"✅ FormalMC execution completed, log: {log_path}",
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
