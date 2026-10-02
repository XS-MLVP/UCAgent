"""Build an importable Picker DUT package for the active Python interpreter."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile


def _picker_xspcomm(picker: Path) -> Path:
    """Locate Picker's bundled xspcomm parent directory."""
    result = subprocess.run([str(picker), "--show_xcom_lib_location_python"],
                            capture_output=True, text=True, check=True)
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Picker did not report its xspcomm Python directory")
    package = Path(lines[-1]).resolve()
    if not (package / "xspcomm/__init__.py").is_file():
        raise ValueError(f"Picker xspcomm package missing: {package}")
    return package


def _probe_xspcomm(package: Path) -> str:
    """Import Picker's xspcomm with the current interpreter; return its version."""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(package), env.get("PYTHONPATH", "")))
    probe = subprocess.run([sys.executable, "-c", "import xspcomm; print(xspcomm.version())"],
                           capture_output=True, text=True, cwd=package, env=env, check=False)
    if probe.returncode:
        raise RuntimeError(f"Picker xspcomm cannot load in {sys.executable}:\n{probe.stderr[-1600:]}")
    return probe.stdout.strip()


def _run(command: list[str], cwd: Path, what: str, env: dict[str, str] | None = None) -> str:
    """Run one packaging step, failing with its last output lines."""
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                            check=False, env=env)
    if result.returncode:
        tail = "\n".join((result.stdout + result.stderr).splitlines()[-25:])
        raise RuntimeError(f"{what} failed (exit {result.returncode}):\n{tail}")
    return result.stdout


def _build_env() -> dict[str, str]:
    """Environment with common Homebrew headers/libs visible to the Apple toolchain."""
    env = os.environ.copy()
    for var, prefix in (("CPATH", "/opt/homebrew/include"), ("LIBRARY_PATH", "/opt/homebrew/lib")):
        if Path(prefix).is_dir() and prefix not in env.get(var, ""):
            env[var] = os.pathsep.join((env[var], prefix)) if env.get(var) else prefix
    return env


def _lz4_cmake_flags() -> list[str]:
    """Cache shared-linker flags for Homebrew lz4; Verilator FST trace needs it."""
    prefix = Path("/opt/homebrew")
    if (prefix / "include/lz4.h").is_file() and (prefix / "lib/liblz4.dylib").is_file():
        return [f"-DCMAKE_SHARED_LINKER_FLAGS=-L{prefix}/lib -llz4"]
    return []


def _toolchain_cmake_flags() -> list[str]:
    """Skip the generated macOS toolchain block when its pkg-config deps lack metadata.

    The generated macos-homebrew-llvm.cmake requires `pkg-config systemc`, but the
    Homebrew systemc formula ships no .pc file; a failed first configure still caches
    HOMEBREW_LLVM_TOOLCHAIN_INITIALIZED, which is how every working build on this
    machine actually ran. Seed that flag only when the headers exist without it.
    """
    if sys.platform != "darwin":
        return []
    probe = subprocess.run(["pkg-config", "--exists", "systemc"],
                           capture_output=True, check=False)
    if probe.returncode == 0:
        return []
    if not Path("/opt/homebrew/include/systemc.h").is_file():
        return []
    return ["-DHOMEBREW_LLVM_TOOLCHAIN_INITIALIZED:INTERNAL=TRUE"]


def _makefile_exports(makefile: Path) -> dict[str, str]:
    """Read `export VAR := VALUE` settings from a generated Picker Makefile."""
    exports: dict[str, str] = {}
    for line in makefile.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^export\s+([A-Za-z_][A-Za-z0-9_]*)\s*:?=\s*(.*?)\s*$", line)
        if match and "$(" not in match.group(2):
            exports[match.group(1)] = match.group(2)
    return exports


def _rewrite_o_level(paths: list[Path], opt: str) -> int:
    """Swap generated -O3 for `opt` and drop -march=native in build files.

    Verilator's giant per-step sources (one function spanning tens of thousands
    of lines) can push clang -O3 into hours-long pathological compiles; -O1
    finishes in minutes. The generated CMakeLists/verilator.cmake hardcode the
    flags and flags.make is derived from them, so patch both layers.
    """
    pattern = re.compile(r"(?<!\w)O3(?!\w)")
    patched = 0
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        new = pattern.sub(opt, text).replace("-march=native", "")
        if new != text:
            path.write_text(new, encoding="utf-8")
            patched += 1
    return patched


def _build_mem_direct(picker: Path, project: Path, dut: str, jobs: str,
                      env: dict[str, str]) -> None:
    """Build the mem_direct offset generator and emit <dut>_offset.yaml."""
    offset = project / "mem_direct" / f"{dut}_offset.yaml"
    if offset.is_file():
        return
    header = project / "build" / f"DPI{dut}" / f"V{dut}___024root.h"
    if not header.is_file():
        raise RuntimeError(f"verilator root header missing for mem_direct: {header}")
    template = picker.parent.parent / "share" / "picker" / "template" / "mem_direct"
    if not template.is_dir():
        raise FileNotFoundError(f"Picker mem_direct template missing: {template}")
    _run([str(picker), "export", str(header), "--source_dir", str(template),
          "--target_dir", "./mem_direct", "--source_module_name", dut, "--sim", "verilator"],
         project, "mem_direct export", env)
    cxx = env.get("CXX") or shutil.which("clang++") or shutil.which("g++") or "c++"
    # The generated mem_direct Makefile has no -std flag; std::filesystem needs C++17.
    _run(["make", f"CXX={cxx} -std=c++17", f"-j{jobs}", f"TOP_NAME={dut}"],
         project / "mem_direct", "mem_direct build", env)
    result = subprocess.run(["./export.bin"], cwd=project / "mem_direct", env=env,
                            capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"mem_direct offset generation failed:\n{result.stderr[-1600:]}")
    offset.write_text(result.stdout, encoding="utf-8")


def _freeze_cold_paths(build: Path) -> int:
    """Compile generated *__Slow.cpp objects at -O0 via make pattern variables.

    Coverage/ctor `__Slow` sources are VL_ATTR_COLD one-shot init code, but
    verilator can emit single functions spanning tens of thousands of lines
    that clang compiles pathologically at ANY -O level (sbuffer: one
    _configure_coverage_0 of ~37k lines burned hours at -O3 and at -O1). The
    pattern-specific variable lands after CXX_FLAGS, so the trailing -O0 wins
    while hot-path eval files keep the downgraded level. Returns how many
    flags.make files were annotated.
    """
    patched = 0
    for flags in sorted(build.rglob("flags.make")):
        prefix = flags.parent.name
        if prefix.endswith(".dir"):
            prefix = prefix[:-len(".dir")]
        rule = f"CMakeFiles/{prefix}.dir/%__Slow.cpp.o: CXX_FLAGS += -O0"
        text = flags.read_text(encoding="utf-8", errors="replace")
        if "__Slow.cpp.o: CXX_FLAGS" in text:
            continue
        flags.write_text(text + f"\n# cold-path init sources: compile at -O0\n{rule}\n",
                         encoding="utf-8")
        patched += 1
    return patched


def build_picker_package(workspace: Path, destination: Path, picker: Path,
                         jobs: int | None = None, cxx_opt: str | None = None,
                         module: str | None = None,
                         source_files: list[Path] | None = None) -> dict[str, str]:
    """Rebuild the DUT runtime package with the current interpreter via Picker."""
    picker = Path(picker).expanduser().resolve()
    if not picker.is_file():
        raise FileNotFoundError(picker)
    workspace = Path(workspace).expanduser().resolve()
    if not workspace.is_dir() or not workspace.name.startswith("workspace_"):
        raise ValueError(f"workspace must be an existing workspace_<dut> directory: {workspace}")
    dut = workspace.name[len("workspace_"):]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", dut):
        raise ValueError(f"invalid dut name from workspace: {dut}")
    module = module or dut
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", module):
        raise ValueError(f"invalid source module name: {module}")
    filelist = workspace / "filelist.txt"
    if not filelist.is_file():
        raise FileNotFoundError(filelist)
    xspcomm_dir = _picker_xspcomm(picker)
    version = _probe_xspcomm(xspcomm_dir)

    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    build = Path(tempfile.mkdtemp(prefix=f".build_{dut}_", dir=destination.parent))
    try:
        project = build / "project"
        project.mkdir()
        build_filelist = []
        selected = (source_files if source_files is not None
                    else [workspace / line.strip()
                          for line in filelist.read_text(encoding="utf-8").splitlines()
                          if line.strip() and not line.lstrip().startswith("#")])
        for source_file in selected:
            source_file = Path(source_file).resolve()
            if not source_file.is_file():
                raise FileNotFoundError(source_file)
            build_filelist.append(str(source_file))
        if not build_filelist:
            raise ValueError(f"filelist has no RTL sources: {filelist}")
        (project / "filelist.txt").write_text("\n".join(build_filelist) + "\n", encoding="utf-8")
        # Picker exits nonzero when its internal build attempt fails; the generated
        # files are complete at that point, so keep going and gate on them below.
        export = subprocess.run([str(picker), "export", "--rw", "1",
                                 "--sname", module, "--tname", dut,
                                 "--tdir", f"{project}/", "-c", "-w", f"{project}/{dut}/{dut}.fst",
                                 "--fs", "filelist.txt"],
                                cwd=project, env=_build_env(), capture_output=True,
                                text=True, check=False)
        if export.returncode:
            tail = "\n".join((export.stdout + export.stderr).splitlines()[-4:])
            print(f"note: picker export internal build failed; generation kept:\n{tail}",
                  file=sys.stderr)
        for needed in (project / dut / "Makefile", project / dut / "python" / "dut.py"):
            if not needed.is_file():
                raise RuntimeError(f"picker export did not generate {needed}")
        # The generated root CMakeLists reads COVERAGE/CHECKPOINTS/VPI from the
        # environment, so export them like make does, then drive cmake directly.
        exports = _makefile_exports(project / dut / "Makefile")
        env = _build_env()
        env.update(exports)
        jobs = str(jobs or os.cpu_count() or 2)
        source_count = 0
        if cxx_opt:
            dut_dir = project / dut
            sources = [dut_dir / "CMakeLists.txt", *sorted((dut_dir / "cmake").glob("*.cmake"))]
            source_count = _rewrite_o_level([p for p in sources if p.is_file()], cxx_opt)
        _run(["cmake", ".", "-Bbuild", "-DSIMULATOR=" + exports.get("SIMULATOR", "verilator"),
              "-DTRACE=" + exports.get("TRACE", "fst"), "-DPROJECT=" + dut,
              "-DRW_TYPE=" + exports.get("RW_TYPE", "MEM_DIRECT"),
              "-DCMAKE_BUILD_PARALLEL=" + jobs,
              *_lz4_cmake_flags(), *_toolchain_cmake_flags()],
             project / dut, "DUT library configure (cmake)", env)
        if cxx_opt:
            flag_count = _rewrite_o_level(sorted((project / dut / "build").rglob("flags.make")),
                                          cxx_opt)
            cold_count = _freeze_cold_paths(project / dut / "build")
            if not source_count and not flag_count:
                raise RuntimeError(f"no generated build file contained O3; -{cxx_opt} did not apply")
            print(f"note: rewrote O3 to -{cxx_opt} in {source_count} source files "
                  f"and {flag_count} flags.make; froze {cold_count} flags.make cold paths to -O0",
                  file=sys.stderr)
        _run(["cmake", "--build", "build", "--parallel", jobs],
             project / dut, "DUT library build (verilator + DPI)", env)
        _build_mem_direct(picker, project / dut, dut, jobs, env)

        target = f"UT_{dut}"
        built = project / dut / "build" / target
        if not built.is_dir():
            raise RuntimeError(f"expected build output directory is missing: {built}")
        package = build / dut
        shutil.copytree(built, package)
        inner = project / dut / "python"
        shutil.copy2(inner / "dut.py", package / "__init__.py")
        for item in ("example.py", "dut.i", "CMakeLists.txt", "Makefile"):
            shutil.copy2(inner / item, package / item)
        shutil.copy2(inner / "cmake" / "verilator.cmake", package / "dut.cmake")
        for item in ("signals.json", "pli.tab", "dut_type.hpp", "dut_base.hpp"):
            if (project / dut / item).is_file():
                shutil.copy2(project / dut / item, package / item)
        for item in (project / dut).glob(f"{dut}*"):
            if item.suffix in {".v", ".sv", ".yaml"}:
                shutil.copy2(item, package / item.name)
        offset = project / dut / "mem_direct" / f"{dut}_offset.yaml"
        if offset.is_file():
            shutil.copy2(offset, package / offset.name)
        shutil.rmtree(package / "build", ignore_errors=True)
        shutil.copytree(xspcomm_dir / "xspcomm", package / "xspcomm",
                        ignore=shutil.ignore_patterns("__pycache__"))
        _run(["cmake", ".", "-Bbuild", f"-DPython3_EXECUTABLE={sys.executable}",
              f"-DPython3_INCLUDE_DIR={sysconfig.get_path('include')}"],
             package, "wrapper configure (cmake)", env)
        _run(["cmake", "--build", "build", "--parallel", jobs],
             package, "wrapper build (swig)", env)
        # SWIG emits the loader shim and extension into build/; move them up
        # next to __init__.py before dropping the build tree.
        for pattern in ("*.py", "*.so"):
            for item in (package / "build").glob(pattern):
                shutil.copy2(item, package / item.name)
        if not (package / f"libUT_{dut}.py").is_file():
            raise RuntimeError("SWIG wrapper did not produce the loader shim")
        shutil.rmtree(package / "build", ignore_errors=True)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(build)
        probe = subprocess.run(
            [sys.executable, "-c",
             f"import {dut} as dut; d = dut.DUT{dut}(); d.Step(1); d.Finish(); print('smoke OK')"],
            capture_output=True, text=True, env=env, cwd=build, check=False)
        if probe.returncode:
            raise RuntimeError(f"rebuilt package failed import smoke test:\n{probe.stderr[-1600:]}")

        package.rename(destination)
    except Exception:
        # Preserve generated files for diagnosis when compilation fails.
        raise
    shutil.rmtree(build, ignore_errors=True)
    return {"dut": dut, "python": sys.executable, "xspcomm": version,
            "package": str(destination)}
