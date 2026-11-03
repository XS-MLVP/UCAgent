"""Picker command construction and synchronous, streaming, and background compilation."""

from __future__ import annotations

import json
import os
import pathlib
import queue
import shutil
import shlex
import subprocess
import threading
from typing import Any, Dict, List, Optional, Tuple

from .common import (
    _FILELIST_EXTS,
    _is_picker_f_file,
    _is_rtl_workspace_file,
    _normalize_arg_list,
    _now,
    _plain_config_value,
    _safe_name,
)


# Keep the waveform defaults aligned with the Makefile SIM contract.
PICKER_SIMULATORS = {
    "verilator": {"label": "Verilator", "waveform_suffix": "fst"},
    "vcs": {"label": "VCS", "waveform_suffix": "fsdb"},
    "gsim": {"label": "GSim", "waveform_suffix": "fst"},
    "uvs": {"label": "UVS", "waveform_suffix": "usdb"},
}


class CompilationMixin:
    """Picker command construction and synchronous, streaming, and background compilation."""

    def _simulator_priority(self) -> List[str]:
        """Return the configured simulator candidates in strict priority order."""
        defaults = _plain_config_value(self.cfg.get_value("launch.default_args", {}) or {})
        if not isinstance(defaults, dict):
            raise ValueError("'launch.default_args' must be a mapping")
        priority = defaults.get("simulator", list(PICKER_SIMULATORS))
        if (
            not isinstance(priority, list)
            or not priority
            or any(not isinstance(item, str) or item not in PICKER_SIMULATORS for item in priority)
            or len(set(priority)) != len(priority)
        ):
            raise ValueError(
                "'launch.default_args.simulator' must be a nonempty ordered list of unique names from: "
                + ", ".join(PICKER_SIMULATORS)
            )
        return list(priority)

    def _effective_simulator(self, simulator: Any = None) -> str:
        """Validate an explicit selection or choose the first available configured simulator."""
        if simulator is None:
            simulator = next((item["value"] for item in self._picker_simulator_options() if item["enabled"]), "")
            if not simulator:
                raise ValueError(
                    "No configured Picker simulator is available in the Master environment. "
                    "Make picker and a configured simulator available, then refresh availability."
                )
        if not isinstance(simulator, str) or simulator not in PICKER_SIMULATORS:
            raise ValueError("'simulator' must be one of: " + ", ".join(PICKER_SIMULATORS))
        return simulator

    def _picker_simulator_options(self) -> List[Dict[str, Any]]:
        """Report executables visible to the Master process without claiming license readiness."""
        picker_path = shutil.which("picker")
        options = []
        for value in self._simulator_priority():
            metadata = PICKER_SIMULATORS[value]
            executable = shutil.which(value)
            missing = [name for name, path in (("picker", picker_path), (value, executable)) if not path]
            options.append({
                "value": value,
                **metadata,
                "enabled": not missing,
                "reason": "Not found in Master PATH: " + ", ".join(missing) if missing else "",
            })
        return options

    def _validate_compile_options(self, simulator: Any, picker_extra_args: Any) -> Tuple[str, List[str]]:
        """Reject unavailable simulators and conflicting arguments before changing a workspace."""
        simulator = self._effective_simulator(simulator)
        picker_args = self._effective_picker_args(picker_extra_args)
        option = next((item for item in self._picker_simulator_options() if item["value"] == simulator), None)
        if option is None:
            raise ValueError(
                f"Simulator '{simulator}' is not in launch.default_args.simulator. "
                "Select a configured simulator."
            )
        if not option["enabled"]:
            raise ValueError(f"Simulator '{simulator}' is unavailable. {option['reason']}. Select an available simulator.")
        return simulator, picker_args

    def _reset_compiled_workspace_dirs(self, picker_workspace: str, dut: str) -> Tuple[str, str, str]:
        rtl_dir = os.path.join(picker_workspace, f"{dut}_RTL")
        doc_dir = os.path.join(picker_workspace, f"{dut}_Doc")
        dut_dir = os.path.join(picker_workspace, dut)
        for path in (rtl_dir, doc_dir, dut_dir):
            if os.path.exists(path):
                shutil.rmtree(path)
        os.makedirs(rtl_dir, exist_ok=True)
        os.makedirs(doc_dir, exist_ok=True)
        return rtl_dir, doc_dir, dut_dir

    def _prepare_workspace_layout(
        self,
        workspace_id: str,
        *,
        effective_dut: str,
        main_verilog_path: str = "",
        selected_module: str = "",
        picker_extra_args: Optional[List[str]] = None,
        simulator: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate compilation inputs and prepare a fresh simulator-specific DUT layout."""
        simulator, picker_extra_args = self._validate_compile_options(simulator, picker_extra_args)
        ws = self._ensure_workspace_materialized(workspace_id, status="active")
        root = ws["workspace_dir"]
        picker_workspace = ws.get("picker_workspace") or os.path.join(root, "workspace")
        dut = _safe_name(effective_dut, "DUT")
        main_item = self._select_main_item(ws, main_verilog_path)
        f_items = [
            item for item in ws.get("files", [])
            if _is_picker_f_file(item.get("stored_path") or item.get("original_name") or "")
        ]
        if main_item is None and not f_items:
            raise ValueError("No main Verilog file or .f file found in workspace")
        if not str(selected_module or "").strip():
            raise ValueError("'selected_module' is required")
        # Resetting the layout destroys the package authorized by the old record.
        # Invalidate it first so preparation failures cannot permit a stale launch.
        with self._workspaces_lock:
            self._clear_workspace_compile_locked(ws)
        self._mark_dirty()
        rtl_dir, doc_dir, dut_dir = self._reset_compiled_workspace_dirs(picker_workspace, dut)
        copied: List[str] = []
        main_target = ""
        filelist_path = ""
        source_f_filelist_paths: List[str] = []
        f_filelist_paths: List[str] = []
        rtl_sources: List[str] = []
        config_path = ""
        for item in ws.get("files", []):
            src = item["stored_path"]
            cat = item.get("category", "misc")
            filename = os.path.basename(src)
            is_f_file = _is_picker_f_file(filename)
            if is_f_file:
                source_f_abs = os.path.abspath(src)
                if os.path.isfile(source_f_abs) and source_f_abs not in source_f_filelist_paths:
                    source_f_filelist_paths.append(source_f_abs)
            if is_f_file and item.get("source") == "server":
                f_abs = os.path.abspath(src)
                if os.path.isfile(f_abs) and f_abs not in f_filelist_paths:
                    f_filelist_paths.append(f_abs)
                continue
            if _is_rtl_workspace_file(filename, cat):
                target_dir = rtl_dir
            else:
                target_dir = doc_dir
            os.makedirs(target_dir, exist_ok=True)
            target = os.path.join(target_dir, filename)
            if os.path.abspath(src) != os.path.abspath(target):
                shutil.copy2(src, target)
            copied.append(target)
            if target_dir == rtl_dir and pathlib.Path(target).suffix.lower() in _FILELIST_EXTS:
                rtl_sources.append(target)
            if is_f_file:
                f_abs = os.path.abspath(target)
                if f_abs not in f_filelist_paths:
                    f_filelist_paths.append(f_abs)
            if main_item is not None and os.path.abspath(src) == os.path.abspath(main_item["stored_path"]):
                main_target = target
            if filename.lower() == "filelist.txt":
                filelist_path = target
            if cat == "config" and not config_path:
                config_path = os.path.relpath(target, root)

        if main_item is not None and not main_target:
            raise ValueError("Failed to locate copied main Verilog file")
        generated_filelist = False
        if main_target and not filelist_path:
            deps = [path for path in rtl_sources if os.path.abspath(path) != os.path.abspath(main_target)]
            if deps:
                filelist_path = os.path.join(rtl_dir, "filelist.txt")
                with open(filelist_path, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(sorted(os.path.abspath(path) for path in deps)) + "\n")
                copied.append(filelist_path)
                generated_filelist = True
        picker_command = self._build_picker_command(
            workspace_dir=root,
            picker_workspace=picker_workspace,
            dut_name=dut,
            selected_module=selected_module,
            main_verilog_path=main_target,
            filelist_path=filelist_path,
            f_filelist_paths=f_filelist_paths,
            picker_extra_args=picker_extra_args or [],
            simulator=simulator,
        )
        return {
            "workspace_dir": root,
            "picker_workspace": picker_workspace,
            "dut_name": dut,
            "rtl_dir": rtl_dir,
            "dut_dir": dut_dir,
            "doc_dir": doc_dir,
            "source_main_verilog_path": main_item["stored_path"] if main_item is not None else "",
            "main_verilog_path": main_target,
            "filelist_path": filelist_path,
            "source_f_filelist_paths": source_f_filelist_paths,
            "f_filelist_paths": f_filelist_paths,
            "generated_filelist": generated_filelist,
            "copied_files": copied,
            "config_path": config_path,
            "picker_extra_args": list(picker_extra_args or []),
            "picker_command": picker_command,
            "simulator": simulator,
            "waveform_suffix": PICKER_SIMULATORS[simulator]["waveform_suffix"],
        }

    def _copy_requirement_readme(self, ws: Dict[str, Any], dut_dir: str) -> str:
        requirement = self._select_workspace_item_by_category(ws, "requirement")
        if requirement is None:
            return ""
        src = requirement.get("stored_path", "")
        if not src or not os.path.isfile(src):
            return ""
        os.makedirs(dut_dir, exist_ok=True)
        readme_path = os.path.join(dut_dir, "README.md")
        shutil.copy2(src, readme_path)
        return readme_path

    def _default_picker_args(self) -> List[str]:
        default_args = _plain_config_value(self.cfg.get_value("launch.default_args", {}) or {})
        if not isinstance(default_args, dict):
            return []
        picker_args = _normalize_arg_list(default_args.get("picker_args"))
        if picker_args:
            return picker_args
        return _normalize_arg_list(default_args.get("picker_extra_args"))

    def _effective_picker_args(self, picker_extra_args: Any = None) -> List[str]:
        """Resolve extra arguments while reserving simulator, access mode, and waveform options."""
        args = self._default_picker_args() if picker_extra_args is None else _normalize_arg_list(picker_extra_args)
        reserved = {"--sim", "-w", "--wave_file_name", "--rw", "--access-mode"}
        for arg in args:
            if arg.split("=", 1)[0] in reserved or (arg.startswith("-w") and not arg.startswith("--")):
                raise ValueError(
                    "picker_args must not set --sim, -w/--wave_file_name, or --rw/--access-mode. "
                    "Select 'simulator'; access mode and waveform path are set automatically."
                )
        return args

    def _compile_workspace_dut(
        self,
        workspace_id: str,
        *,
        effective_dut: str,
        selected_module: str,
        main_verilog_path: str = "",
        picker_extra_args: Optional[List[str]] = None,
        simulator: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Compile and persist one DUT package with its simulator identity."""
        ws = self._get_workspace(workspace_id)
        picker_args = self._effective_picker_args(picker_extra_args)
        prepared = self._prepare_workspace_layout(
            workspace_id,
            effective_dut=effective_dut,
            selected_module=selected_module,
            main_verilog_path=main_verilog_path,
            picker_extra_args=picker_args,
            simulator=simulator,
        )
        picker = self._run_picker(
            workspace_dir=prepared["workspace_dir"],
            picker_workspace=prepared["picker_workspace"],
            dut_name=prepared["dut_name"],
            selected_module=selected_module,
            main_verilog_path=prepared["main_verilog_path"],
            filelist_path=prepared["filelist_path"],
            f_filelist_paths=prepared["f_filelist_paths"],
            picker_extra_args=prepared["picker_extra_args"],
            simulator=prepared["simulator"],
        )
        readme_path = ""
        if picker["success"]:
            readme_path = self._copy_requirement_readme(ws, prepared["dut_dir"])
        compile_info = {
            "status": "success" if picker["success"] else "failed",
            "dut_name": prepared["dut_name"],
            "selected_module": selected_module,
            "main_verilog_path": prepared["source_main_verilog_path"],
            "compiled_main_verilog_path": prepared["main_verilog_path"],
            "picker_workspace": prepared["picker_workspace"],
            "rtl_dir": prepared["rtl_dir"],
            "doc_dir": prepared["doc_dir"],
            "dut_dir": prepared["dut_dir"],
            "filelist_path": prepared["filelist_path"],
            "source_f_filelist_paths": prepared["source_f_filelist_paths"],
            "f_filelist_paths": prepared["f_filelist_paths"],
            "generated_filelist": prepared["generated_filelist"],
            "config_path": prepared.get("config_path", ""),
            "readme_path": readme_path,
            "compiled_at": _now(),
            "copied_files": prepared["copied_files"],
            "simulator": prepared["simulator"],
            "waveform_suffix": prepared["waveform_suffix"],
            "picker_command": picker["command"],
            "picker_extra_args": prepared["picker_extra_args"],
            "picker_exit_code": picker["exit_code"],
            "picker_stdout": picker["stdout"],
            "picker_stderr": picker["stderr"],
        }
        with self._workspaces_lock:
            ws = self._workspaces.get(workspace_id)
            if ws is None:
                raise KeyError(f"Workspace '{workspace_id}' not found")
            ws["compile"] = compile_info
        self._mark_dirty()
        return {"prepared": prepared, "picker": picker, "compile": compile_info}

    def _run_picker(
        self,
        *,
        workspace_dir: str,
        picker_workspace: str,
        dut_name: str,
        selected_module: str,
        main_verilog_path: str,
        filelist_path: str = "",
        f_filelist_paths: Optional[List[str]] = None,
        picker_extra_args: Optional[List[str]] = None,
        simulator: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run a Picker export and retry once after an existing-package conflict."""
        cmd = self._build_picker_command(
            workspace_dir=workspace_dir,
            picker_workspace=picker_workspace,
            dut_name=dut_name,
            selected_module=selected_module,
            main_verilog_path=main_verilog_path,
            filelist_path=filelist_path,
            f_filelist_paths=f_filelist_paths or [],
            picker_extra_args=picker_extra_args or [],
            simulator=simulator,
        )
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=workspace_dir)
        already_exists = self._picker_create_conflict(picker_workspace, dut_name, result.stdout + result.stderr)
        if already_exists:
            shutil.rmtree(os.path.join(picker_workspace, dut_name), ignore_errors=True)
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=workspace_dir)
        return {
            "command": cmd,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "success": result.returncode == 0,
        }

    def _build_picker_command(
        self,
        *,
        workspace_dir: str,
        picker_workspace: str,
        dut_name: str,
        selected_module: str,
        main_verilog_path: str,
        filelist_path: str = "",
        f_filelist_paths: Optional[List[str]] = None,
        picker_extra_args: Optional[List[str]] = None,
        simulator: Optional[str] = None,
    ) -> List[str]:
        """Build a Picker export command with consistent simulator, access, and waveform settings."""
        simulator = self._effective_simulator(simulator)
        picker_extra_args = self._effective_picker_args(picker_extra_args)
        suffix = PICKER_SIMULATORS[simulator]["waveform_suffix"]
        waveform_path = os.path.join(picker_workspace, dut_name, f"{dut_name}.{suffix}")
        cmd = ["picker", "export"]
        if main_verilog_path:
            cmd.append(main_verilog_path)
        cmd.extend([
            "--sim",
            simulator,
            "--rw",
            "1" if simulator == "verilator" else "0",
            "--sname",
            selected_module,
            "--tdir",
            os.path.join(picker_workspace, ""),
            "-c",
            "-w",
            waveform_path,
        ])
        if filelist_path and os.path.isfile(filelist_path):
            cmd.extend(["--fs", filelist_path])
        for f_path in f_filelist_paths or []:
            if f_path and os.path.isfile(f_path):
                cmd.extend(["--filelist", os.path.abspath(f_path)])
        cmd.extend([arg for arg in (picker_extra_args or []) if str(arg).strip()])
        return cmd

    def _picker_create_conflict(self, picker_workspace: str, dut_name: str, output: str) -> bool:
        return f"Create: {os.path.join(picker_workspace, dut_name)} fail" in (output or "")

    def _append_compile_log(self, workspace_id: str, text: str, stream: str = "") -> None:
        with self._compile_runtime_lock:
            runtime = self._compile_runtime.get(workspace_id)
            if runtime is None:
                return
            runtime["log"] = runtime.get("log", "") + str(text or "")
            runtime["cursor"] = len(runtime["log"])
            runtime["last_stream"] = stream

    def _compile_runtime_public(self, workspace_id: str, cursor: int = 0) -> Dict[str, Any]:
        with self._compile_runtime_lock:
            runtime = dict(self._compile_runtime.get(workspace_id) or {})
        log = str(runtime.get("log") or "")
        safe_cursor = max(0, min(int(cursor or 0), len(log)))
        return {
            "status": runtime.get("status", ""),
            "cursor": len(log),
            "chunk": log[safe_cursor:],
            "started_at": runtime.get("started_at", 0),
            "finished_at": runtime.get("finished_at", 0),
            "error": runtime.get("error", ""),
            "workspace": runtime.get("workspace"),
            "compile": runtime.get("compile"),
            "result": runtime.get("result"),
        }

    def _run_compile_job(
        self,
        workspace_id: str,
        effective_dut: str,
        selected_module: str,
        main_verilog_path: str,
        picker_extra_args: Optional[List[str]] = None,
        simulator: Optional[str] = None,
    ) -> None:
        """Stream a background compile into the workspace runtime log and persist its result."""
        prepared: Dict[str, Any] = {}
        picker: Dict[str, Any] = {"command": [], "exit_code": None, "stdout": "", "stderr": "", "success": False}
        try:
            picker_args = self._effective_picker_args(picker_extra_args)
            prepared = self._prepare_workspace_layout(
                workspace_id,
                effective_dut=effective_dut,
                selected_module=selected_module,
                main_verilog_path=main_verilog_path,
                picker_extra_args=picker_args,
                simulator=simulator,
            )
            self._append_compile_log(
                workspace_id,
                (
                    f"Prepared workspace layout:\n"
                    f"  RTL: {prepared['rtl_dir']}\n"
                    f"  DOC: {prepared['doc_dir']}\n"
                    f"  DUT: {prepared['dut_dir']}\n"
                    f"  Picker: {shlex.join(prepared['picker_command'])}\n"
                ),
                "info",
            )

            def _run_once() -> Dict[str, Any]:
                cmd = list(prepared["picker_command"])
                proc = subprocess.Popen(
                    cmd,
                    cwd=prepared["workspace_dir"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
                out_parts: List[str] = []
                err_parts: List[str] = []
                events: "queue.Queue[Tuple[str, Optional[str]]]" = queue.Queue()

                def _pump(pipe, stream_name: str):
                    try:
                        for line in iter(pipe.readline, ""):
                            events.put((stream_name, line))
                    finally:
                        try:
                            pipe.close()
                        except Exception:
                            pass
                        events.put((stream_name, None))

                threads = [
                    threading.Thread(target=_pump, args=(proc.stdout, "stdout"), daemon=True),
                    threading.Thread(target=_pump, args=(proc.stderr, "stderr"), daemon=True),
                ]
                for thread in threads:
                    thread.start()

                closed = 0
                while closed < 2 or proc.poll() is None:
                    try:
                        stream_name, chunk = events.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if chunk is None:
                        closed += 1
                        continue
                    if stream_name == "stdout":
                        out_parts.append(chunk)
                    else:
                        err_parts.append(chunk)
                    self._append_compile_log(workspace_id, chunk, stream_name)
                proc.wait()
                return {
                    "command": cmd,
                    "exit_code": proc.returncode,
                    "stdout": "".join(out_parts),
                    "stderr": "".join(err_parts),
                    "success": proc.returncode == 0,
                }

            picker = _run_once()
            if self._picker_create_conflict(prepared["picker_workspace"], prepared["dut_name"], picker["stdout"] + picker["stderr"]):
                self._append_compile_log(
                    workspace_id,
                    f"Detected existing package directory, cleaning {os.path.join(prepared['picker_workspace'], prepared['dut_name'])} and retrying...\n",
                    "info",
                )
                shutil.rmtree(os.path.join(prepared["picker_workspace"], prepared["dut_name"]), ignore_errors=True)
                picker = _run_once()

            readme_path = ""
            if picker["success"]:
                readme_path = self._copy_requirement_readme(self._get_workspace(workspace_id), prepared["dut_dir"])
            compile_info = {
                "status": "success" if picker["success"] else "failed",
                "dut_name": prepared["dut_name"],
                "selected_module": selected_module,
                "main_verilog_path": prepared["source_main_verilog_path"],
                "compiled_main_verilog_path": prepared["main_verilog_path"],
                "picker_workspace": prepared["picker_workspace"],
                "rtl_dir": prepared["rtl_dir"],
                "doc_dir": prepared["doc_dir"],
                "dut_dir": prepared["dut_dir"],
                "filelist_path": prepared["filelist_path"],
                "source_f_filelist_paths": prepared["source_f_filelist_paths"],
                "f_filelist_paths": prepared["f_filelist_paths"],
                "generated_filelist": prepared["generated_filelist"],
                "config_path": prepared.get("config_path", ""),
                "readme_path": readme_path,
                "compiled_at": _now(),
                "copied_files": prepared["copied_files"],
                "simulator": prepared["simulator"],
                "waveform_suffix": prepared["waveform_suffix"],
                "picker_command": picker["command"],
                "picker_extra_args": prepared["picker_extra_args"],
                "picker_exit_code": picker["exit_code"],
                "picker_stdout": picker["stdout"],
                "picker_stderr": picker["stderr"],
            }
            with self._workspaces_lock:
                ws = self._workspaces.get(workspace_id)
                if ws is None:
                    raise KeyError(f"Workspace '{workspace_id}' not found")
                ws["compile"] = compile_info
            self._mark_dirty()
            ws_public = self._workspace_public(self._get_workspace(workspace_id))
            with self._compile_runtime_lock:
                runtime = self._compile_runtime.get(workspace_id)
                if runtime is not None:
                    runtime["status"] = "success" if picker["success"] else "failed"
                    runtime["finished_at"] = _now()
                    runtime["workspace"] = ws_public
                    runtime["compile"] = self._workspace_compile_public(self._get_workspace(workspace_id))
                    runtime["result"] = picker
        except Exception as exc:
            self._append_compile_log(workspace_id, f"{exc}\n", "stderr")
            with self._compile_runtime_lock:
                runtime = self._compile_runtime.get(workspace_id)
                if runtime is not None:
                    runtime["status"] = "failed"
                    runtime["finished_at"] = _now()
                    runtime["error"] = str(exc)

    def _start_compile_job(
        self,
        workspace_id: str,
        effective_dut: str,
        selected_module: str,
        main_verilog_path: str,
        picker_extra_args: Optional[List[str]] = None,
        simulator: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start one background compile per workspace, reusing only an identical running request."""
        simulator, picker_extra_args = self._validate_compile_options(simulator, picker_extra_args)
        request = {
            "dut_name": _safe_name(effective_dut, "DUT"),
            "selected_module": selected_module,
            "main_verilog_path": main_verilog_path,
            "picker_args": picker_extra_args,
            "simulator": simulator,
        }
        with self._compile_runtime_lock:
            existing = self._compile_runtime.get(workspace_id)
            if existing and existing.get("status") == "running":
                if existing["request"] != request:
                    raise ValueError(
                        "A compilation with different settings is already running for this workspace. "
                        "Wait for it to finish before recompiling."
                    )
                return dict(existing)
            runtime = {
                "status": "running",
                "request": request,
                "started_at": _now(),
                "finished_at": 0,
                "log": "",
                "cursor": 0,
                "error": "",
                "workspace": None,
                "compile": None,
                "result": None,
            }
            self._compile_runtime[workspace_id] = runtime
        thread = threading.Thread(
            target=self._run_compile_job,
            args=(workspace_id, effective_dut, selected_module, main_verilog_path, picker_extra_args, simulator),
            daemon=True,
            name=f"compile-{workspace_id}",
        )
        thread.start()
        return dict(runtime)

    def _stream_picker_run(
        self,
        *,
        workspace_dir: str,
        picker_workspace: str,
        dut_name: str,
        selected_module: str,
        main_verilog_path: str,
        filelist_path: str = "",
        f_filelist_paths: Optional[List[str]] = None,
        picker_extra_args: Optional[List[str]] = None,
        simulator: Optional[str] = None,
        command: Optional[List[str]] = None,
    ):
        """Yield NDJSON log events and return the completed Picker process result."""
        cmd = list(command or self._build_picker_command(
            workspace_dir=workspace_dir,
            picker_workspace=picker_workspace,
            dut_name=dut_name,
            selected_module=selected_module,
            main_verilog_path=main_verilog_path,
            filelist_path=filelist_path,
            f_filelist_paths=f_filelist_paths or [],
            picker_extra_args=picker_extra_args or [],
            simulator=simulator,
        ))
        proc = subprocess.Popen(
            cmd,
            cwd=workspace_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        out_parts: List[str] = []
        err_parts: List[str] = []
        events: "queue.Queue[Tuple[str, Optional[str]]]" = queue.Queue()

        def _pump(pipe, stream_name: str):
            try:
                for line in iter(pipe.readline, ""):
                    events.put((stream_name, line))
            finally:
                try:
                    pipe.close()
                except Exception:
                    pass
                events.put((stream_name, None))

        threads = [
            threading.Thread(target=_pump, args=(proc.stdout, "stdout"), daemon=True),
            threading.Thread(target=_pump, args=(proc.stderr, "stderr"), daemon=True),
        ]
        for thread in threads:
            thread.start()

        closed = 0
        while closed < 2 or proc.poll() is None:
            try:
                stream_name, chunk = events.get(timeout=0.1)
            except queue.Empty:
                continue
            if chunk is None:
                closed += 1
                continue
            if stream_name == "stdout":
                out_parts.append(chunk)
            else:
                err_parts.append(chunk)
            yield (json.dumps({"type": "log", "stream": stream_name, "text": chunk}, ensure_ascii=False) + "\n").encode("utf-8")
        proc.wait()
        return {
            "command": cmd,
            "exit_code": proc.returncode,
            "stdout": "".join(out_parts),
            "stderr": "".join(err_parts),
            "success": proc.returncode == 0,
        }
