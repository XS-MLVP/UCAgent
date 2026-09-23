"""Public RTL-language adaptation contracts for the DesignWithPPA workflow."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Mapping

from .contracts import resolved_output, sha256_file


_LANGUAGE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_MODULE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

CHISEL_VERSION = "7.15.0"
CHISEL_SCALA_VERSION = "2.13.18"
CHISEL_MILL_VERSION = "0.4.2"
CHISEL_MINIMUM_JAVA_VERSION = 17

# Arguments forwarded through picker's ``--vflag`` to verilator for every
# Python-DUT build.  ``--output-split`` is verilator's generated-C++ file
# splitter (statement-count based; there is no line-count variant), so the
# default 2000 keeps every translation unit small enough to compile in
# parallel instead of one oversized module dominating the managed build.
PICKER_VERILATOR_ARGS_DEFAULT: tuple[str, ...] = ("--output-split", "2000")

# One verilator argument token: flags, values, and paths only.  Whitespace,
# quotes, and shell/Makefile metacharacters are rejected because the
# passthrough value is re-split and re-expanded by picker's launcher and
# generated build files.
_VERILATOR_ARG_TOKEN_RE = re.compile(r"[A-Za-z0-9_+.=,:/-]+")


class RTLLanguageError(ValueError):
    """Report an invalid or unavailable RTL-language integration contract."""


@dataclass(frozen=True)
class RTLPreparationRequest:
    """Describe one trusted language adapter invocation."""

    workspace: Path
    language: str
    top_module: str
    source_files: tuple[Path, ...]
    library_files: tuple[Path, ...]
    build_dir: Path
    language_options: Mapping[str, Any]
    python_dut_options: Mapping[str, Any]
    timeout: int


@dataclass(frozen=True)
class RTLSourceTemplate:
    """Describe one authored-language source scaffold and its coding guide."""

    filename: str
    content: str
    coding_guide: str


@dataclass(frozen=True)
class RTLSourceValidation:
    """Describe the public validation gate for one authored RTL language."""

    checker: str
    description: str
    task: str
    guide: str
    report_filename: str


@dataclass(frozen=True)
class PreparedRTL:
    """Bind authored sources to Verilog analysis and Python-DUT build inputs."""

    language: str
    source_files: tuple[Path, ...]
    library_files: tuple[Path, ...]
    analysis_verilog_files: tuple[Path, ...]
    python_dut_files: tuple[Path, ...]
    metadata: Mapping[str, Any]

    def content_identity(self) -> dict[str, Any]:
        """Return path-free content identities for private build receipts."""

        identities = {}
        for name, files in (
            ("analysis", self.analysis_verilog_files),
            ("python_dut", self.python_dut_files),
        ):
            digests = []
            for path in files:
                digest = hashlib.sha256()
                with path.open("rb") as file_obj:
                    for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                        digest.update(chunk)
                digests.append(digest.hexdigest())
            aggregate = hashlib.sha256(
                json.dumps(digests, separators=(",", ":")).encode("ascii")
            ).hexdigest()
            identities[name] = {
                "file_count": len(files),
                "content_sha256": aggregate,
            }
        return identities


@dataclass(frozen=True)
class ResolvedRTLConfig:
    """Hold the validated workflow configuration for one RTL language."""

    language: str
    source_glob: str
    source_template: str
    library_paths: tuple[str, ...]
    language_options: Mapping[str, Any]
    python_dut_interface: str
    python_dut_options: Mapping[str, Any]

    def identity(self) -> dict[str, Any]:
        """Return the finite JSON identity persisted in build evidence."""

        return {
            "language": self.language,
            "source_glob": self.source_glob,
            "source_template": self.source_template,
            "library_paths": list(self.library_paths),
            "language_options": dict(self.language_options),
            "python_dut": {
                "interface": self.python_dut_interface,
                "options": dict(self.python_dut_options),
            },
        }


class RTLLanguageBackend(ABC):
    """Convert one authored RTL language into analysis and Python-DUT inputs."""

    name: str
    display_name: str
    source_extensions: tuple[str, ...]
    source_template: str
    # Set by backends whose prepare() output uses SystemVerilog constructs
    # (firtool emits always_comb even for simple modules); every downstream
    # Yosys reader must enable SystemVerilog mode for those files.
    analysis_systemverilog: bool = False

    @abstractmethod
    def default_source_glob(self, output_dir: str) -> str:
        """Return the default workspace-relative source glob for this language."""

    @abstractmethod
    def source_template_bundle(self, module_name: str) -> RTLSourceTemplate:
        """Return the selected language's initial source and runtime guide."""

    @abstractmethod
    def source_validation_bundle(
        self, module_name: str
    ) -> RTLSourceValidation:
        """Return the authored-language source validation stage contract."""

    def normalize_options(self, options: Mapping[str, Any]) -> Mapping[str, Any]:
        """Validate language-specific configuration before workspace access."""

        if options:
            raise RTLLanguageError(
                f"RTL language {self.name!r} does not accept language_options"
            )
        return {}

    def normalize_python_dut_options(
        self, options: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Validate public Python-DUT conversion options for this language.

        ``verilator_args`` is the complete list of verilator argument tokens
        the managed picker export forwards through ``--vflag``.  An absent
        key selects the canonical output-split default; every configured
        entry must be one metacharacter-free token because the value is
        re-split by a shell-based launcher and expanded inside the
        generated build files.
        """

        unknown = sorted(set(options) - {"verilator_args"})
        if unknown:
            raise RTLLanguageError(
                f"RTL language {self.name!r} does not accept python_dut.options: {unknown}"
            )
        raw_args = options.get("verilator_args")
        if raw_args is None:
            return {"verilator_args": list(PICKER_VERILATOR_ARGS_DEFAULT)}
        if not isinstance(raw_args, list) or any(
            not isinstance(arg, str) or not _VERILATOR_ARG_TOKEN_RE.fullmatch(arg)
            for arg in raw_args
        ):
            raise RTLLanguageError(
                "design_with_ppa.rtl.python_dut.options.verilator_args must be "
                "a list of non-empty verilator argument tokens without "
                "whitespace, quotes, or shell/Makefile metacharacters"
            )
        return {"verilator_args": list(raw_args)}

    @abstractmethod
    def prepare(self, request: RTLPreparationRequest) -> PreparedRTL:
        """Prepare deterministic Verilog analysis and Python-DUT input files."""


class VerilogLanguageBackend(RTLLanguageBackend):
    """Use synthesizable IEEE 1364-2005 Verilog sources without translation."""

    name = "verilog"
    display_name = "Verilog"
    source_extensions = (".v",)
    source_template = "verilog-2005"

    def default_source_glob(self, output_dir: str) -> str:
        """Select every top-level Verilog module emitted by the workflow."""

        return f"{output_dir}/rtl/*.v"

    def source_template_bundle(self, module_name: str) -> RTLSourceTemplate:
        """Return the canonical IEEE 1364-2005 starting point."""

        return RTLSourceTemplate(
            filename=f"{module_name}.v",
            coding_guide="Guide_Doc/coding_standard_verilog.md",
            content=(
                "`default_nettype none\n\n"
                "// Module: " + module_name + "\n"
                "// Purpose: Describe the exact function implemented by this RTL module.\n"
                "// Interface: Document every port's direction, width, signedness, and\n"
                "//           transaction or handshake meaning below.\n"
                "// Parameters: Document each parameter's legal range and hardware impact.\n"
                "// Timing/reset: Document whether this design is combinational or sequential,\n"
                "//              plus clock edge, reset polarity, reset synchrony, and latency.\n"
                "// Numeric behavior: Document non-obvious encoding, extension, truncation,\n"
                "//                  rounding, saturation, overflow, and invalid-input rules.\n"
                f"module {module_name} (\n"
                "    // input_i  - replace with an architecture-defined input port.\n"
                "    input  wire input_i,\n"
                "    // output_o - replace with an architecture-defined output port.\n"
                "    output wire output_o\n"
                ");\n\n"
                "// Core datapath: replace this identity operation with the architecture\n"
                "// contract after the Python executable specification passes. Explain any\n"
                "// non-obvious width or control decision immediately before the logic.\n"
                "assign output_o = input_i;\n\n"
                "endmodule\n\n"
                "`default_nettype wire\n"
            ),
        )

    def source_validation_bundle(
        self, module_name: str
    ) -> RTLSourceValidation:
        """Require line coverage for directly authored Verilog statements."""

        return RTLSourceValidation(
            checker="RTLLineCoverageChecker",
            description="Authored Verilog line coverage [{COVERAGE_COMPLETE}]",
            task=(
                "Call Check to measure authored Verilog line coverage. Add tests "
                "for every reachable specified behavior before excluding lines. "
                f"For a proven exact exclusion, write only its raw pattern in "
                f"tests/{module_name}.ignore and write the matching traced proof "
                f"in {module_name}_line_coverage_analysis.md."
            ),
            guide="Guide_Doc/rtl_line_coverage.md",
            report_filename=f"{module_name}_line_coverage_analysis.md",
        )

    def normalize_options(self, options: Mapping[str, Any]) -> Mapping[str, Any]:
        """Accept only the canonical Verilog language standard option."""

        unknown = sorted(set(options) - {"standard"})
        if unknown:
            raise RTLLanguageError(
                f"unsupported Verilog language_options: {unknown}"
            )
        standard = options.get("standard", "verilog-2005")
        if standard != "verilog-2005":
            raise RTLLanguageError(
                "design_with_ppa.rtl.language_options.standard must be "
                "'verilog-2005'"
            )
        return {"standard": standard}

    def prepare(self, request: RTLPreparationRequest) -> PreparedRTL:
        """Return the authored Verilog files as both downstream input sets."""

        return PreparedRTL(
            language=self.name,
            source_files=request.source_files,
            library_files=request.library_files,
            analysis_verilog_files=tuple(
                sorted(
                    {*request.library_files, *request.source_files},
                    key=lambda path: path.as_posix(),
                )
            ),
            python_dut_files=tuple(
                sorted(
                    {*request.library_files, *request.source_files},
                    key=lambda path: path.as_posix(),
                )
            ),
            metadata={
                "translation": "identity",
                "standard": request.language_options["standard"],
            },
        )


class ChiselLanguageBackend(RTLLanguageBackend):
    """Elaborate a pinned, portable Chisel 7 source set in private storage."""

    name = "chisel"
    display_name = "Chisel"
    source_extensions = (".scala",)
    source_template = "chisel-7"
    analysis_systemverilog = True

    def default_source_glob(self, output_dir: str) -> str:
        """Select every authored Chisel source in the RTL delivery directory."""

        return f"{output_dir}/rtl/*.scala"

    def source_template_bundle(self, module_name: str) -> RTLSourceTemplate:
        """Return a small Chisel 7 module that the architecture will replace."""

        return RTLSourceTemplate(
            filename=f"{module_name}.scala",
            coding_guide="Guide_Doc/coding_standard_chisel.md",
            content=(
                "/**\n"
                "  * Module: " + module_name + "\n"
                "  * Purpose: replace this scaffold with the architecture-defined function.\n"
                "  * Interface: document each IO direction, width, signedness, and\n"
                "  *            transaction or handshake meaning next to its declaration.\n"
                "  * Parameters: document each constructor parameter's legal range and\n"
                "  *             effect on generated hardware and latency.\n"
                "  * Timing/reset: document combinational or sequential behavior, clock edge,\n"
                "  *              reset polarity/synchrony, and the observable latency.\n"
                "  * Numeric behavior: document encodings, width changes, rounding, saturation,\n"
                "  *                  overflow, and invalid-input handling.\n"
                "  */\n"
                "import chisel3._\n\n"
                f"class {module_name} extends RawModule {{\n"
                "  // input_i  - replace with the exact architecture input declaration.\n"
                "  val input_i = IO(Input(Bool()))\n"
                "  // output_o - replace with the exact architecture output declaration.\n"
                "  val output_o = IO(Output(Bool()))\n\n"
                "  // Replace this scaffold with the architecture contract after Python UT passes.\n"
                "  // Core datapath: keep a short explanation beside each non-obvious\n"
                "  // decode, pipeline, width conversion, or state transition.\n"
                "  output_o := input_i\n"
                "}\n"
            ),
        )

    def source_validation_bundle(
        self, module_name: str
    ) -> RTLSourceValidation:
        """Use authored-source and regression receipts instead of generated lines."""

        return RTLSourceValidation(
            checker="RTLSourceEvidenceChecker",
            description="Chisel authored-source and functional-evidence gate",
            task=(
                "Call Check to bind the current Chisel source hashes to automatic "
                "elaboration, synthesis, and the complete shared RTL regression. "
                "Generated implementation line coverage is not an authored Chisel "
                "source metric."
            ),
            guide="Guide_Doc/source_validation_chisel.md",
            report_filename=f"{module_name}_chisel_source_validation.md",
        )

    def normalize_options(self, options: Mapping[str, Any]) -> Mapping[str, Any]:
        """Pin Chisel, Scala, and Mill to the tested cross-version contract."""

        supported = {"chisel_version", "scala_version", "mill_version"}
        unknown = sorted(set(options) - supported)
        if unknown:
            raise RTLLanguageError(
                f"unsupported Chisel language_options: {unknown}"
            )
        expected = {
            "chisel_version": CHISEL_VERSION,
            "scala_version": CHISEL_SCALA_VERSION,
            "mill_version": CHISEL_MILL_VERSION,
        }
        normalized: dict[str, str] = {}
        for field, version in expected.items():
            value = options.get(field, version)
            if value != version:
                raise RTLLanguageError(
                    f"design_with_ppa.rtl.language_options.{field} must be "
                    f"{version!r}"
                )
            normalized[field] = version
        return normalized

    def prepare(self, request: RTLPreparationRequest) -> PreparedRTL:
        """Compile and elaborate authored Chisel into one private Verilog file."""

        options = self.normalize_options(request.language_options)
        mill = shutil.which("mill")
        if mill is None:
            raise RTLLanguageError(
                "The Chisel compilation environment is unavailable because the "
                "supported build executable was not found in PATH. Install Mill "
                f"{CHISEL_MILL_VERSION} and call Check again."
            )
        shell = shutil.which("sh")
        if shell is None:
            raise RTLLanguageError(
                "The Chisel compilation environment requires a POSIX shell to "
                f"launch Mill {CHISEL_MILL_VERSION}."
            )
        java_home, java_version = self._resolve_java_home(request.timeout)
        environment = os.environ.copy()
        environment["JAVA_HOME"] = str(java_home)
        environment["PATH"] = os.pathsep.join(
            (str(java_home / "bin"), environment.get("PATH", ""))
        )
        version_result = subprocess.run(
            [shell, mill, "-i", "version"],
            cwd=request.build_dir,
            env=environment,
            text=True,
            capture_output=True,
            timeout=min(request.timeout, 60),
            check=False,
        )
        mill_output = f"{version_result.stdout}\n{version_result.stderr}"
        if version_result.returncode != 0 or not re.search(
            rf"(?m)^\s*{re.escape(CHISEL_MILL_VERSION)}\s*$", mill_output
        ):
            raise RTLLanguageError(
                "The Chisel compilation environment has an unsupported build "
                f"version; install Mill {CHISEL_MILL_VERSION} and call Check again."
            )

        source_dir = request.build_dir / "design" / "src"
        source_dir.mkdir(parents=True, exist_ok=False)
        public_paths: dict[str, str] = {}
        selected_sources = (
            *(("authored", source) for source in request.source_files),
            *(("library", source) for source in request.library_files),
        )
        for index, (category, source) in enumerate(selected_sources):
            target = source_dir / category / f"{index:05d}-{source.name}"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            try:
                public_path = source.relative_to(request.workspace).as_posix()
            except ValueError:
                public_path = f"configured-library/{source.name}"
            public_paths[str(target)] = public_path

        (request.build_dir / "build.sc").write_text(
            self._mill_build(options), encoding="utf-8"
        )
        (source_dir / "UCAgentElaborate.scala").write_text(
            self._elaboration_runner(), encoding="utf-8"
        )
        generated = request.build_dir / f"{request.top_module}.v"
        completed = subprocess.run(
            [
                shell,
                mill,
                "-i",
                "design.runMain",
                "ucagent.internal.UCAgentElaborate",
                request.top_module,
                str(generated),
            ],
            cwd=request.build_dir,
            env=environment,
            text=True,
            capture_output=True,
            timeout=request.timeout,
            check=False,
        )
        if completed.returncode != 0:
            details = self._source_diagnostics(
                f"{completed.stdout}\n{completed.stderr}", public_paths
            )
            message = (
                "Chisel source compilation or top-module elaboration failed. "
                "Fix the selected Chisel sources and top-module contract, then "
                "call Check again."
            )
            if details:
                message = f"{message}\n{details}"
            raise RTLLanguageError(message)
        if not generated.is_file() or generated.is_symlink():
            raise RTLLanguageError(
                "Chisel elaboration completed without a usable hardware result; "
                "check the selected top-module class and call Check again."
            )
        if not re.search(
            rf"(?m)^\s*module\s+{re.escape(request.top_module)}\s*\(",
            generated.read_text(encoding="utf-8"),
        ):
            raise RTLLanguageError(
                "Chisel elaboration did not emit the architecture top module; "
                "make the top a package-free, zero-argument RawModule or Module "
                "class whose name exactly matches architecture.top_module."
            )
        files = (generated.resolve(),)
        return PreparedRTL(
            language=self.name,
            source_files=request.source_files,
            library_files=request.library_files,
            analysis_verilog_files=files,
            python_dut_files=files,
            metadata={
                "translation": "chisel-elaboration",
                **options,
                "java_major_version": java_version,
                "library_source_count": len(request.library_files),
            },
        )

    @staticmethod
    def _resolve_java_home(timeout: int) -> tuple[Path, int]:
        """Find and validate a JDK suitable for the pinned Chisel toolchain."""

        candidates: list[Path] = []
        configured = os.environ.get("JAVA_HOME")
        if configured:
            candidates.append(Path(configured))
        java_home_helper = Path("/usr/libexec/java_home")
        if java_home_helper.is_file():
            completed = subprocess.run(
                [str(java_home_helper), "-v", str(CHISEL_MINIMUM_JAVA_VERSION)],
                text=True,
                capture_output=True,
                timeout=min(timeout, 30),
                check=False,
            )
            if completed.returncode == 0 and completed.stdout.strip():
                candidates.append(Path(completed.stdout.strip()))
        candidates.append(
            Path.home() / ".local" / "share" / "ucagent-toolchains" / "jdk-17"
        )
        java = shutil.which("java")
        if java:
            candidates.append(Path(java).resolve().parent.parent)

        visited: set[Path] = set()
        for candidate in candidates:
            home = candidate.expanduser().resolve()
            if home in visited:
                continue
            visited.add(home)
            executable = home / "bin" / "java"
            if not executable.is_file():
                continue
            completed = subprocess.run(
                [str(executable), "-version"],
                text=True,
                capture_output=True,
                timeout=min(timeout, 30),
                check=False,
            )
            output = f"{completed.stdout}\n{completed.stderr}"
            match = re.search(r'version\s+"(?:1\.)?(\d+)', output)
            if completed.returncode == 0 and match:
                major = int(match.group(1))
                if major >= CHISEL_MINIMUM_JAVA_VERSION:
                    return home, major
        raise RTLLanguageError(
            "The Chisel compilation environment requires JDK 17 or newer. "
            "Install a JDK, set JAVA_HOME when needed, and call Check again."
        )

    @staticmethod
    def _mill_build(options: Mapping[str, Any]) -> str:
        """Render the private Mill 0.4 project for the pinned dependency graph."""

        return (
            "import mill._, scalalib._\n\n"
            "object design extends ScalaModule {\n"
            f'  def scalaVersion = "{options["scala_version"]}"\n'
            "  def ivyDeps = Agg(ivy\"org.chipsalliance::chisel:"
            f'{options["chisel_version"]}\")\n'
            "  def scalacPluginIvyDeps = Agg(ivy\"org.chipsalliance:::chisel-plugin:"
            f'{options["chisel_version"]}\")\n'
            "  def scalacOptions = Seq(\n"
            '    "-deprecation",\n'
            '    "-feature",\n'
            '    "-unchecked",\n'
            '    "-language:reflectiveCalls",\n'
            '    "-Xcheckinit",\n'
            '    "-Ymacro-annotations"\n'
            "  )\n"
            "}\n"
        )

    @staticmethod
    def _elaboration_runner() -> str:
        """Return the private, package-neutral top-module elaboration entry point."""

        return (
            "package ucagent.internal\n\n"
            "import chisel3.RawModule\n"
            "import _root_.circt.stage.ChiselStage\n"
            "import java.nio.charset.StandardCharsets\n"
            "import java.nio.file.{Files, Paths}\n\n"
            "object UCAgentElaborate extends App {\n"
            '  require(args.length == 2, "expected top module and output file")\n'
            "  val moduleClass = Class.forName(args(0))\n"
            "  val constructor = moduleClass.getDeclaredConstructor()\n"
            "  val verilog = ChiselStage.emitSystemVerilog(\n"
            "    gen = constructor.newInstance().asInstanceOf[RawModule],\n"
            "    firtoolOpts = Array(\n"
            '      "-disable-all-randomization",\n'
            # Lower locals and packed arrays to plain mux/case logic so the
            # emitted Verilog has no SystemVerilog automatic-array
            # initializers that the synthesis toolchain cannot read.
            '      "-lowering-options=disallowLocalVariables,disallowPackedArrays",\n'
            '      "-strip-debug-info",\n'
            '      "-default-layer-specialization=enable"\n'
            "    )\n"
            "  )\n"
            "  Files.write(Paths.get(args(1)), verilog.getBytes(StandardCharsets.UTF_8))\n"
            "}\n"
        )

    @staticmethod
    def _source_diagnostics(output: str, paths: Mapping[str, str]) -> str:
        """Project private compiler output into bounded authored-source diagnostics."""

        cleaned = _ANSI_ESCAPE_RE.sub("", output).replace("\r", "")
        for private_path, public_path in paths.items():
            cleaned = cleaned.replace(private_path, public_path)
        selected: list[str] = []
        keep_context = 0
        for raw_line in cleaned.splitlines():
            line = raw_line.strip("\n")
            lower = line.lower()
            source_line = ".scala:" in lower
            significant = source_line or any(
                marker in lower
                for marker in (
                    "error:",
                    "exception",
                    "classnotfoundexception",
                    "nosuchmethodexception",
                )
            )
            if significant:
                keep_context = 3
            elif keep_context:
                keep_context -= 1
            else:
                continue
            if any(
                private_term in lower
                for private_term in (
                    "build.sc",
                    "/out/",
                    "ucagentelaborate",
                    "mill.",
                    "generated.v",
                )
            ):
                continue
            if line.strip():
                selected.append(line[-800:])
            if len(selected) >= 24:
                break
        return "\n".join(selected)[-6000:]


class RTLLanguageRegistry:
    """Register trusted RTL-language adapters by stable configuration name."""

    def __init__(self) -> None:
        """Create an empty registry."""

        self._backends: dict[str, RTLLanguageBackend] = {}

    def register(self, backend: RTLLanguageBackend) -> None:
        """Register one backend while rejecting malformed or duplicate names."""

        if not isinstance(backend, RTLLanguageBackend):
            raise TypeError("RTL language backend must inherit RTLLanguageBackend")
        name = backend.name
        if not isinstance(name, str) or not _LANGUAGE_NAME_RE.fullmatch(name):
            raise RTLLanguageError(f"invalid RTL language name: {name!r}")
        if name in self._backends:
            raise RTLLanguageError(f"RTL language is already registered: {name}")
        if (
            not isinstance(backend.display_name, str)
            or not backend.display_name.strip()
        ):
            raise RTLLanguageError(f"RTL language {name!r} has no display_name")
        if (
            not isinstance(backend.source_template, str)
            or not backend.source_template.strip()
        ):
            raise RTLLanguageError(f"RTL language {name!r} has no source_template")
        extensions = backend.source_extensions
        if (
            not isinstance(extensions, tuple)
            or not extensions
            or any(
                not isinstance(value, str)
                or not re.fullmatch(r"\.[A-Za-z0-9]+", value)
                or value != value.lower()
                for value in extensions
            )
            or len(set(extensions)) != len(extensions)
        ):
            raise RTLLanguageError(
                f"RTL language {name!r} source_extensions are invalid"
            )
        self._backends[name] = backend

    def unregister(self, name: str) -> None:
        """Remove one optional backend, primarily for plugin unload and tests."""

        if name in {"verilog", "chisel"}:
            raise RTLLanguageError(
                f"the built-in {name} backend cannot be unregistered"
            )
        self._backends.pop(name, None)

    def get(self, name: str) -> RTLLanguageBackend:
        """Return one registered backend with actionable availability details."""

        try:
            return self._backends[name]
        except KeyError as exc:
            available = ", ".join(self.names()) or "none"
            raise RTLLanguageError(
                f"RTL language {name!r} is not registered; available: {available}"
            ) from exc

    def names(self) -> tuple[str, ...]:
        """Return stable registered language names."""

        return tuple(sorted(self._backends))


RTL_LANGUAGE_REGISTRY = RTLLanguageRegistry()
RTL_LANGUAGE_REGISTRY.register(VerilogLanguageBackend())
RTL_LANGUAGE_REGISTRY.register(ChiselLanguageBackend())


def register_rtl_language(backend: RTLLanguageBackend) -> None:
    """Expose one trusted language adapter to DesignWithPPA Checkers."""

    RTL_LANGUAGE_REGISTRY.register(backend)


def unregister_rtl_language(name: str) -> None:
    """Remove one non-default language adapter from the shared registry."""

    RTL_LANGUAGE_REGISTRY.unregister(name)


def available_rtl_languages() -> tuple[str, ...]:
    """List language identifiers accepted by the current process."""

    return RTL_LANGUAGE_REGISTRY.names()


def _workspace_python_dut_root(workspace: Path) -> Path:
    """Return the portable generated Python-DUT root inside one workspace."""

    return workspace.resolve() / "run" / "design_with_ppa" / "python-dut"


def _generated_python_dut_identity(root: Path) -> dict[str, Any]:
    """Hash one regular generated Python-DUT package tree."""

    if root.is_symlink() or not root.is_dir():
        raise ValueError("generated Python-DUT runtime is unavailable")
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("generated Python-DUT runtime must not contain symbolic links")
    files = sorted(
        path.resolve()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts
    )
    if not files or not any(path.suffix == ".py" for path in files):
        raise ValueError("generated Python-DUT runtime has no Python sources")
    rows = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in files
    ]
    return {
        "file_count": len(rows),
        "content_sha256": hashlib.sha256(
            json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def _config_value(cfg: Any, key: str, default: Any) -> Any:
    """Read an optional nested configuration value without masking type errors."""

    try:
        return cfg.get_value(key, default)
    except AttributeError:
        return default


def _mapping(value: Any, field: str) -> dict[str, Any]:
    """Convert one Config or mapping value into a plain dictionary."""

    if hasattr(value, "as_dict") and callable(value.as_dict):
        value = value.as_dict()
    if not isinstance(value, dict):
        raise RTLLanguageError(f"{field} must be a mapping")
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RTLLanguageError(f"{field} must contain finite JSON values") from exc
    return dict(value)


def resolve_rtl_config(
    cfg: Any,
    *,
    output_dir: str | None = None,
) -> tuple[ResolvedRTLConfig, RTLLanguageBackend]:
    """Resolve the RTL contract using an optional initialization-time output."""

    language = _config_value(cfg, "design_with_ppa.rtl.language", "verilog")
    if not isinstance(language, str) or not _LANGUAGE_NAME_RE.fullmatch(language):
        raise RTLLanguageError(
            "design_with_ppa.rtl.language must be a lowercase language identifier"
        )
    backend = RTL_LANGUAGE_REGISTRY.get(language)
    resolved_output_dir = output_dir if output_dir is not None else resolved_output(cfg)
    if not isinstance(resolved_output_dir, str) or not resolved_output_dir.strip():
        raise RTLLanguageError("resolved RTL output directory must be a non-empty string")
    source_glob = _config_value(
        cfg,
        "design_with_ppa.rtl.source_glob",
        backend.default_source_glob(resolved_output_dir),
    )
    if not isinstance(source_glob, str) or not source_glob.strip():
        raise RTLLanguageError(
            "design_with_ppa.rtl.source_glob must be a non-empty string"
        )
    source_path = Path(source_glob)
    if source_path.is_absolute() or ".." in source_path.parts:
        raise RTLLanguageError(
            "design_with_ppa.rtl.source_glob must remain workspace-relative"
        )
    output_path = Path(resolved_output_dir)
    if source_path.parts[: len(output_path.parts)] != output_path.parts:
        raise RTLLanguageError(
            "design_with_ppa.rtl.source_glob must remain below the resolved OUT directory"
        )
    source_template = _config_value(
        cfg, "design_with_ppa.rtl.source_template", backend.source_template
    )
    if source_template != backend.source_template:
        raise RTLLanguageError(
            f"RTL language {language!r} requires source_template "
            f"{backend.source_template!r}"
        )
    configured_library_paths = _config_value(
        cfg, "design_with_ppa.rtl.library_paths", []
    )
    if not isinstance(configured_library_paths, list) or any(
        not isinstance(value, str) or not value.strip()
        for value in configured_library_paths
    ):
        raise RTLLanguageError(
            "design_with_ppa.rtl.library_paths must be a list of non-empty directory paths"
        )
    library_path_append = _config_value(
        cfg, "design_with_ppa.rtl.library_path_append", ""
    )
    if not isinstance(library_path_append, str):
        raise RTLLanguageError(
            "design_with_ppa.rtl.library_path_append must be a path-separated string"
        )
    library_paths = []
    for raw_path in (
        *configured_library_paths,
        *(value for value in library_path_append.split(os.pathsep) if value),
    ):
        normalized_path = Path(raw_path.strip()).expanduser()
        normalized_value = (
            str(normalized_path)
            if normalized_path.is_absolute()
            else normalized_path.as_posix()
        )
        if normalized_value in {"", "."}:
            raise RTLLanguageError(
                "RTL library paths must identify explicit library directories"
            )
        if normalized_value not in library_paths:
            library_paths.append(normalized_value)
    raw_options = _config_value(cfg, "design_with_ppa.rtl.language_options", {})
    options = backend.normalize_options(
        _mapping(raw_options, "design_with_ppa.rtl.language_options")
    )
    interface = _config_value(
        cfg, "design_with_ppa.rtl.python_dut.interface", "automatic"
    )
    if interface != "automatic":
        raise RTLLanguageError(
            "design_with_ppa.rtl.python_dut.interface must be 'automatic'"
        )
    python_dut_options = backend.normalize_python_dut_options(
        _mapping(
            _config_value(cfg, "design_with_ppa.rtl.python_dut.options", {}),
            "design_with_ppa.rtl.python_dut.options",
        )
    )
    resolved = ResolvedRTLConfig(
        language=language,
        source_glob=source_glob,
        source_template=source_template,
        library_paths=tuple(library_paths),
        language_options=dict(options),
        python_dut_interface=interface,
        python_dut_options=dict(python_dut_options),
    )
    try:
        json.dumps(resolved.identity(), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RTLLanguageError("resolved RTL configuration is not finite JSON") from exc
    return resolved, backend


def build_rtl_template_context(
    cfg: Any,
    base_context: Mapping[str, Any],
) -> dict[str, str]:
    """Derive LLM-visible source-language template values from final config."""

    module_name = base_context.get("DUT")
    if not isinstance(module_name, str) or not _MODULE_NAME_RE.fullmatch(module_name):
        raise RTLLanguageError("DUT must be a portable RTL identifier")
    resolved, backend = resolve_rtl_config(cfg, output_dir=base_context.get("OUT"))
    bundle = backend.source_template_bundle(module_name)
    if not isinstance(bundle, RTLSourceTemplate):
        raise RTLLanguageError(
            f"RTL language {resolved.language!r} returned an invalid source template"
        )
    filename = Path(bundle.filename)
    if (
        filename.is_absolute()
        or len(filename.parts) != 1
        or filename.name in {"", ".", ".."}
        or filename.suffix.lower() not in backend.source_extensions
    ):
        raise RTLLanguageError(
            f"RTL language {resolved.language!r} returned an invalid template filename"
        )
    if not isinstance(bundle.content, str) or not bundle.content.strip():
        raise RTLLanguageError(
            f"RTL language {resolved.language!r} returned an empty source template"
        )
    if not isinstance(bundle.coding_guide, str) or not bundle.coding_guide:
        raise RTLLanguageError(
            f"RTL language {resolved.language!r} returned an invalid coding guide"
        )
    guide = Path(bundle.coding_guide)
    if (
        guide.is_absolute()
        or ".." in guide.parts
        or not guide.parts
        or guide.parts[0] != "Guide_Doc"
        or guide.suffix.lower() != ".md"
    ):
        raise RTLLanguageError(
            f"RTL language {resolved.language!r} returned an invalid coding guide"
        )
    source_validation = backend.source_validation_bundle(module_name)
    if not isinstance(source_validation, RTLSourceValidation):
        raise RTLLanguageError(
            f"RTL language {resolved.language!r} returned invalid source validation"
        )
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", source_validation.checker):
        raise RTLLanguageError(
            f"RTL language {resolved.language!r} returned an invalid validation checker"
        )
    if (
        not source_validation.description.strip()
        or not source_validation.task.strip()
        or not source_validation.guide.strip()
    ):
        raise RTLLanguageError(
            f"RTL language {resolved.language!r} returned incomplete source validation"
        )
    validation_guide = Path(source_validation.guide)
    if (
        validation_guide.is_absolute()
        or ".." in validation_guide.parts
        or not validation_guide.parts
        or validation_guide.parts[0] != "Guide_Doc"
        or validation_guide.suffix.lower() != ".md"
    ):
        raise RTLLanguageError(
            f"RTL language {resolved.language!r} returned an invalid validation guide"
        )
    report_name = Path(source_validation.report_filename)
    if (
        report_name.is_absolute()
        or len(report_name.parts) != 1
        or report_name.name in {"", ".", ".."}
        or report_name.suffix.lower() != ".md"
    ):
        raise RTLLanguageError(
            f"RTL language {resolved.language!r} returned an invalid validation report"
        )
    return {
        "RTL_LANGUAGE": backend.display_name,
        "RTL_LANGUAGE_ID": resolved.language,
        "RTL_SOURCE_FILE": bundle.filename,
        "RTL_SOURCE_GLOB": resolved.source_glob,
        "RTL_SOURCE_TEMPLATE": resolved.source_template,
        "RTL_SOURCE_TEMPLATE_BODY": bundle.content,
        "RTL_CODING_GUIDE": bundle.coding_guide,
        "RTL_CODING_GUIDE_FILE": guide.relative_to("Guide_Doc").as_posix(),
        "RTL_LIBRARY_PATHS": json.dumps(
            list(resolved.library_paths), ensure_ascii=True
        ),
        "RTL_LIBRARY_GLOB": (
            f"{module_name}/lib/**/*{backend.source_extensions[0]}"
        ),
        "RTL_SOURCE_VALIDATION_CHECKER": source_validation.checker,
        "RTL_SOURCE_VALIDATION_DESC": source_validation.description,
        "RTL_SOURCE_VALIDATION_TASK": source_validation.task,
        "RTL_SOURCE_VALIDATION_GUIDE": source_validation.guide,
        "RTL_SOURCE_VALIDATION_GUIDE_FILE": validation_guide.relative_to(
            "Guide_Doc"
        ).as_posix(),
        "RTL_SOURCE_VALIDATION_REPORT": (
            f"{base_context['OUT']}/{source_validation.report_filename}"
        ),
    }


def discover_rtl_sources(
    workspace: Path,
    config: ResolvedRTLConfig,
    backend: RTLLanguageBackend,
) -> tuple[Path, ...]:
    """Discover a stable, extension-checked authored source set."""

    root = workspace.resolve()
    sources: list[Path] = []
    for candidate in root.glob(config.source_glob):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        lexical = candidate.absolute()
        if any(
            parent.is_symlink()
            for parent in lexical.parents
            if parent == root or root in parent.parents
        ):
            raise RTLLanguageError(
                f"RTL source path must not traverse a symbolic link: {candidate}"
            )
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise RTLLanguageError(
                f"RTL source escapes the workspace: {candidate}"
            ) from exc
        if resolved.suffix.lower() not in backend.source_extensions:
            continue
        sources.append(resolved)
    result = tuple(sorted(set(sources), key=lambda path: path.as_posix()))
    if not result:
        extensions = ", ".join(backend.source_extensions)
        raise RTLLanguageError(
            f"no {backend.display_name} source files matched {config.source_glob}; "
            f"expected extensions: {extensions}"
        )
    return result


def discover_rtl_libraries(
    workspace: Path,
    config: ResolvedRTLConfig,
    backend: RTLLanguageBackend,
) -> tuple[tuple[Path, ...], tuple[dict[str, Any], ...]]:
    """Discover configured language-library sources and path-free provenance."""

    workspace = workspace.resolve()
    files: list[Path] = []
    provenance: list[dict[str, Any]] = []
    seen_files: set[Path] = set()
    for library_index, configured_path in enumerate(config.library_paths):
        candidate_root = Path(configured_path).expanduser()
        if not candidate_root.is_absolute():
            candidate_root = workspace / candidate_root
        library_root = candidate_root.resolve()
        if not library_root.is_dir():
            raise RTLLanguageError(
                f"RTL library path is not a readable directory: {configured_path}"
            )
        selected: list[tuple[str, Path]] = []
        for candidate in library_root.rglob("*"):
            if (
                not candidate.is_file()
                or candidate.is_symlink()
                or candidate.suffix.lower() not in backend.source_extensions
            ):
                continue
            resolved = candidate.resolve()
            try:
                relative = resolved.relative_to(library_root).as_posix()
            except ValueError as exc:
                raise RTLLanguageError(
                    f"RTL library source escapes its configured directory: {configured_path}"
                ) from exc
            selected.append((relative, resolved))
        selected.sort(key=lambda item: item[0])
        if not selected:
            extensions = ", ".join(backend.source_extensions)
            raise RTLLanguageError(
                f"RTL library path {configured_path!r} contains no {backend.display_name} "
                f"sources with extensions: {extensions}"
            )
        for relative, source in selected:
            if source in seen_files:
                raise RTLLanguageError(
                    "RTL library paths overlap at one selected-language source: "
                    f"library[{library_index}]/{relative}"
                )
            seen_files.add(source)
            digest = hashlib.sha256()
            with source.open("rb") as file_obj:
                for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                    digest.update(chunk)
            files.append(source)
            provenance.append(
                {
                    "library_index": library_index,
                    "path": relative,
                    "sha256": digest.hexdigest(),
                }
            )
    return tuple(files), tuple(provenance)


def validate_prepared_rtl(
    workspace: Path,
    request: RTLPreparationRequest,
    prepared: PreparedRTL,
) -> PreparedRTL:
    """Validate a language adapter result before invoking external tools."""

    if not isinstance(prepared, PreparedRTL):
        raise RTLLanguageError("RTL language adapter returned an invalid result")
    if prepared.language != request.language:
        raise RTLLanguageError("RTL language adapter result language is inconsistent")
    if prepared.source_files != request.source_files:
        raise RTLLanguageError("RTL language adapter changed the authored source set")
    if prepared.library_files != request.library_files:
        raise RTLLanguageError("RTL language adapter changed the configured library set")
    if not prepared.analysis_verilog_files:
        raise RTLLanguageError("RTL language adapter produced no analysis Verilog")
    if not prepared.python_dut_files:
        raise RTLLanguageError("RTL language adapter produced no Python-DUT inputs")
    root = workspace.resolve()
    private_root = request.build_dir.resolve()
    for label, files in (
        ("analysis Verilog", prepared.analysis_verilog_files),
        ("Python-DUT input", prepared.python_dut_files),
    ):
        if len(set(files)) != len(files):
            raise RTLLanguageError(f"RTL language adapter returned duplicate {label} files")
        if tuple(sorted(files, key=lambda path: path.as_posix())) != files:
            raise RTLLanguageError(
                f"RTL language adapter must return path-sorted {label} files"
            )
        for path in files:
            resolved = path.resolve()
            if resolved not in {*request.source_files, *request.library_files}:
                try:
                    resolved.relative_to(private_root)
                except ValueError as exc:
                    raise RTLLanguageError(
                        f"RTL language adapter {label} must be an authored source "
                        f"or remain inside its private build directory: {path}"
                    ) from exc
            elif resolved in request.source_files:
                try:
                    resolved.relative_to(root)
                except ValueError as exc:
                    raise RTLLanguageError(
                        f"RTL language adapter authored source escapes the workspace: {path}"
                    ) from exc
            if path.is_symlink() or not path.is_file():
                raise RTLLanguageError(
                    f"RTL language adapter {label} is not a regular file: {path}"
                )
            if label == "analysis Verilog" and path.suffix.lower() != ".v":
                raise RTLLanguageError(
                    f"RTL language adapter analysis output must use .v: {path}"
                )
    try:
        json.dumps(dict(prepared.metadata), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RTLLanguageError(
            "RTL language adapter metadata must contain finite JSON values"
        ) from exc
    return prepared
