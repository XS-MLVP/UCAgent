"""Portable waveform metadata and workspace-contained viewer links."""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import posixpath
import secrets
import stat
import tempfile
import threading
from typing import Any, Mapping
from urllib.parse import quote, unquote

WAVEFORM_METADATA_LOCK = threading.RLock()
WAVEFORM_VIEWER_ROUTE = "/wave/"
WAVEFORM_VIEWER_MARKER = "<WAVEFORM-VIEWER>"
WAVEFORM_VIEWER_MAX_SIGNALS = 64
_DECIMAL_RE = re.compile(r"0|[1-9][0-9]*")
_LINK_RE = re.compile(r"<WAVEFORM-VIEWER>[ \t]+\[[^\]\r\n]+\]\(/wave/\?meta=([^&#)\s]+)\)")
_METADATA_KEYS = frozenset({"schema_version", "waveform_file", "signals", "source_files",
                            "dut_python_path", "test_file", "test_case", "start", "end", "cursor"})
_METADATA_KEY_DIRECTORY = Path.home() / ".ucagent" / "waveform_keys"


class WaveformViewerProtocolError(ValueError):
    """A metadata file or viewer link violates the current viewing contract."""


class WaveformMetadataIntegrityError(WaveformViewerProtocolError):
    """Stored viewing metadata is unsigned, modified or unverifiable."""


def _metadata_key(workspace: str | Path, *, create: bool) -> bytes:
    """Keep workspace-scoped secrets outside served files and never recreate on reads."""
    root = Path(workspace).resolve()
    directory = _METADATA_KEY_DIRECTORY
    if directory.resolve().is_relative_to(root) or directory.is_symlink():
        raise WaveformMetadataIntegrityError("metadata signing keys must remain outside the workspace")
    if create:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        info = directory.lstat()
    except FileNotFoundError:
        raise WaveformMetadataIntegrityError("metadata signing key is missing; regenerate the viewing metadata") from None
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise WaveformMetadataIntegrityError("metadata signing directory must be owned by the running user")
    if create:
        os.chmod(directory, 0o700)
    elif info.st_mode & 0o077:
        raise WaveformMetadataIntegrityError("metadata signing directory must be private (mode 0700)")
    name = hashlib.sha256(os.fsencode(root)).hexdigest() + ".key"
    path = directory / name
    # Publish only a complete key so simultaneous processes never read partial bytes.
    if create:
        if not path.exists() and not path.is_symlink():
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=directory, delete=False) as handle:
                    temporary = handle.name
                    handle.write(secrets.token_bytes(32))
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    pass
            finally:
                if temporary is not None:
                    os.unlink(temporary)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        raise WaveformMetadataIntegrityError("metadata signing key is missing; regenerate the viewing metadata") from None
    except OSError:
        raise WaveformMetadataIntegrityError("metadata signing key cannot be opened as a private regular file") from None
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise WaveformMetadataIntegrityError("metadata signing key must be a private regular file (mode 0600)")
        key = handle.read(33)
    if len(key) != 32:
        raise WaveformMetadataIntegrityError("metadata signing key is invalid; restore the private key before retrying")
    return key


def _metadata_signature(workspace: str | Path, target: Path, payload: Mapping[str, Any],
                        *, create: bool) -> str:
    """Authenticate all exact JSON fields and their workspace-relative destination."""
    root = Path(workspace).resolve()
    message = json.dumps(["ucagent.waveform-metadata.v1", target.relative_to(root).as_posix(), payload],
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    return hmac.new(_metadata_key(root, create=create), message, hashlib.sha256).hexdigest()


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict:
    """Reject duplicate object keys instead of authenticating an ambiguous document."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise WaveformViewerProtocolError("waveform metadata must not contain duplicate JSON fields")
        result[key] = value
    return result


def normalize_relative_path(value: Any, *, parents: bool = False) -> str:
    """Validate a POSIX relative file path, optionally allowing parent segments."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise WaveformViewerProtocolError("file path must be a nonempty relative string")
    if (chr(92) in value or any(ord(char) < 32 for char in value)
            or PurePosixPath(value).is_absolute() or PureWindowsPath(value).drive
            or any(part in {"", "."} for part in value.split("/"))
            or (not parents and ".." in value.split("/"))):
        raise WaveformViewerProtocolError("file path must use relative '/' segments without escaping its root")
    return value


def resolve_workspace_path(workspace: str | Path, value: str, *, base: Path | None = None,
                           must_exist: bool = True) -> Path:
    """Resolve a relative path and reject workspace escapes, including symlinks."""
    root = Path(workspace).resolve()
    normalize_relative_path(value, parents=base is not None)
    try:
        target = ((base or root) / value).resolve()
    except (OSError, RuntimeError) as error:
        raise WaveformViewerProtocolError(f"file path cannot be resolved: {value}") from error
    if not target.is_relative_to(root):
        raise WaveformViewerProtocolError(f"file path escapes the workspace: {value}")
    if must_exist and not target.is_file():
        raise FileNotFoundError(f"File '{value}' is missing; regenerate the waveform/metadata or correct its source path.")
    return target


def normalize_waveform_viewer_payload(payload: Mapping[str, Any]) -> OrderedDict:
    """Validate the single canonical JSON schema without accessing live files."""
    if not isinstance(payload, Mapping) or type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise WaveformViewerProtocolError("metadata must be an object with schema_version=1")
    if set(payload) - _METADATA_KEYS:
        raise WaveformViewerProtocolError("metadata contains unknown fields")
    required = {"waveform_file", "signals", "source_files", "dut_python_path"}
    if not required.issubset(payload):
        raise WaveformViewerProtocolError("metadata requires waveform_file, signals, source_files and dut_python_path")
    wave = normalize_relative_path(payload["waveform_file"])
    if "/" in wave or not PurePosixPath(wave).suffix:
        raise WaveformViewerProtocolError("waveform_file must name the waveform beside its JSON")
    result = OrderedDict(schema_version=1, waveform_file=wave)
    for key in ("signals", "source_files"):
        items = payload[key]
        if not isinstance(items, list) or any(not isinstance(item, str) or not item.strip()
                                             or any(ord(char) < 32 for char in item) for item in items):
            raise WaveformViewerProtocolError(f"{key} must be an array of nonempty strings")
        items = list(dict.fromkeys(items))
        if key == "signals" and len(items) > WAVEFORM_VIEWER_MAX_SIGNALS:
            raise WaveformViewerProtocolError("signals must contain at most 64 entries")
        if key == "source_files":
            items = [normalize_relative_path(item, parents=True) for item in items]
        result[key] = items
    for key in ("dut_python_path", "test_file"):
        if key in payload:
            result[key] = None if payload[key] is None else normalize_relative_path(payload[key], parents=True)
    if "test_case" in payload:
        if (not isinstance(payload["test_case"], str) or not payload["test_case"].strip()
                or any(ord(char) < 32 for char in payload["test_case"])):
            raise WaveformViewerProtocolError("test_case must be a nonempty exact node ID")
        result["test_case"] = payload["test_case"]
    present = [key for key in ("start", "end", "cursor") if key in payload]
    if present:
        if len(present) != 3 or not result["signals"]:
            raise WaveformViewerProtocolError("an analysis window requires start, end, cursor and signals")
        for key in present:
            if not isinstance(payload[key], str) or _DECIMAL_RE.fullmatch(payload[key]) is None:
                raise WaveformViewerProtocolError(f"{key} must be a nonnegative decimal string")
            result[key] = payload[key]
        if not int(result["start"]) <= int(result["cursor"]) <= int(result["end"]):
            raise WaveformViewerProtocolError("time range must satisfy start <= cursor <= end")
    return result


def validate_waveform_metadata(workspace: str | Path, meta: str, payload: Mapping[str, Any],
                               *, must_exist: bool = True) -> tuple[Path, OrderedDict]:
    """Validate a metadata snapshot and every file against its workspace boundary."""
    target = resolve_workspace_path(workspace, meta, must_exist=False)
    normalized = normalize_waveform_viewer_payload(payload)
    if target.name != normalized["waveform_file"] + ".json":
        raise WaveformViewerProtocolError("metadata filename must be the waveform filename followed by .json")
    for value in [normalized["waveform_file"], *normalized["source_files"],
                  normalized["dut_python_path"], normalized.get("test_file")]:
        if value is not None:
            resolve_workspace_path(workspace, value, base=target.parent, must_exist=must_exist)
    return target, normalized


def load_waveform_metadata(workspace: str | Path, meta: str) -> tuple[Path, OrderedDict]:
    """Authenticate bounded stored JSON before resolving any associated live file."""
    target = resolve_workspace_path(workspace, meta)
    if target.relative_to(Path(workspace).resolve()).as_posix() != meta:
        raise WaveformMetadataIntegrityError("metadata link must use its resolved workspace-relative JSON path")
    try:
        with target.open("rb") as handle:
            content = handle.read(1024 * 1024 + 1)
        if len(content) > 1024 * 1024:
            raise WaveformViewerProtocolError("waveform metadata exceeds 1 MiB")
        payload = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_json_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise WaveformViewerProtocolError("waveform metadata must contain valid UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise WaveformViewerProtocolError("waveform metadata must be a JSON object")
    signature = payload.pop("integrity_hmac", None)
    if not isinstance(signature, str) or re.fullmatch(r"[0-9a-f]{64}", signature) is None:
        raise WaveformMetadataIntegrityError("metadata requires a tool-generated integrity_hmac; regenerate its viewing metadata")
    if not hmac.compare_digest(signature, _metadata_signature(workspace, target, payload, create=False)):
        raise WaveformMetadataIntegrityError("metadata signature does not match its content and path; regenerate its viewing metadata")
    return validate_waveform_metadata(workspace, meta, payload)


def write_waveform_metadata(workspace: str | Path, meta: str, payload: Mapping[str, Any],
                            *, write_dirs: list[str] | None = None,
                            un_write_dirs: list[str] | None = None) -> None:
    """Atomically publish signed metadata without bypassing write restrictions."""
    with WAVEFORM_METADATA_LOCK:
        from ucagent.tools.fileops import is_file_writeable
        target, normalized = validate_waveform_metadata(workspace, meta, payload)
        # A workspace-contained symlink must not bypass a protected target directory.
        for policy_path in {meta, target.relative_to(Path(workspace).resolve()).as_posix()}:
            allowed, reason = is_file_writeable(policy_path, un_write_dirs, write_dirs)
            if not allowed:
                raise PermissionError(reason)
        # The browser resolves waveform_file beside the link, so aliases would change its target.
        if target.relative_to(Path(workspace).resolve()).as_posix() != meta:
            raise WaveformViewerProtocolError("metadata link must use its resolved workspace-relative JSON path")
        stored = dict(normalized, integrity_hmac=_metadata_signature(workspace, target, normalized, create=True))
        serialized = json.dumps(stored, ensure_ascii=False, indent=2) + chr(10)
        if len(serialized.encode("utf-8")) > 1024 * 1024:
            raise WaveformViewerProtocolError("waveform metadata exceeds 1 MiB")
        if target.is_file() and target.read_bytes() == serialized.encode("utf-8"):
            return
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                             prefix=f".{target.name}.", delete=False) as handle:
                temporary = handle.name
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            if target.is_file():
                os.chmod(temporary, stat.S_IMODE(target.stat().st_mode))
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                os.unlink(temporary)


def build_waveform_viewer_url(meta: str) -> str:
    """Build a canonical same-origin link to a specific metadata file."""
    normalize_relative_path(meta)
    if not meta.endswith(".json"):
        raise WaveformViewerProtocolError("meta must name a .json file")
    return f"{WAVEFORM_VIEWER_ROUTE}?meta={quote(meta, safe='/')}"


def build_waveform_viewer_markdown_link(meta: str, *, label: str | None = None) -> str:
    """Render a tagged metadata link with a single-line visible label."""
    label = (label or PurePosixPath(meta).name[:-5]).replace("[", "(").replace("]", ")").strip()
    if not label or chr(10) in label or chr(13) in label:
        raise WaveformViewerProtocolError("viewer link label must be nonempty and single-line")
    return f"{WAVEFORM_VIEWER_MARKER} [{label}]({build_waveform_viewer_url(meta)})"


def parse_waveform_viewer_markdown_link(line: str) -> str:
    """Parse a canonical link without requiring historical artifacts to exist."""
    match = _LINK_RE.fullmatch(line) if isinstance(line, str) else None
    if match is None:
        raise WaveformViewerProtocolError("viewer link must use <WAVEFORM-VIEWER> and /wave/?meta=<relative JSON path>")
    try:
        meta = unquote(match[1], errors="strict")
    except UnicodeError as error:
        raise WaveformViewerProtocolError("viewer metadata path must use valid UTF-8 encoding") from error
    if build_waveform_viewer_url(meta) != WAVEFORM_VIEWER_ROUTE + "?meta=" + match[1]:
        raise WaveformViewerProtocolError("viewer metadata path is not canonically encoded")
    return meta


def build_waveform_metadata(workspace: str | Path, waveform_file: str, *, dut_name: str = "",
                            test_case: str = "", test_dir: str | Path | None = None,
                            source_files: list[str] = (),
                            dut_python_path: str | None = None) -> tuple[str, OrderedDict, list[str]]:
    """Fill deterministic file associations and serialize paths relative to the JSON."""
    root = Path(workspace).resolve()
    wave = resolve_workspace_path(root, waveform_file)
    meta = wave.relative_to(root).as_posix() + ".json"
    sources = [resolve_workspace_path(root, value) for value in source_files]
    if dut_name:
        for suffix in (".v", ".sv", ".vhd", ".vhdl"):
            primary = root / dut_name / (dut_name + suffix)
            if primary.is_file():
                sources.insert(0, resolve_workspace_path(root, primary.relative_to(root).as_posix()))
                break
    dut = resolve_workspace_path(root, dut_python_path) if dut_python_path else None
    if dut is None and dut_name:
        for value in (f"{dut_name}/__init__.py", f"{dut_name}.py"):
            if (root / value).is_file():
                dut = resolve_workspace_path(root, value)
                break
    warnings = [] if dut else ["DUT Python entry is unresolved; provide dut_python_path when known."]
    payload = OrderedDict(schema_version=1, waveform_file=wave.name, signals=[],
                          source_files=list(dict.fromkeys(os.path.relpath(path, wave.parent).replace(os.sep, "/") for path in sources)),
                          dut_python_path=os.path.relpath(dut, wave.parent).replace(os.sep, "/") if dut else None)
    if test_case:
        file_part = test_case.split("::", 1)[0]
        test = None
        if file_part.endswith(".py"):
            normalize_relative_path(file_part)
            candidates = [root / file_part]
            if test_dir is not None:
                tests = Path(test_dir)
                if not tests.is_absolute():
                    tests = root / tests
                candidates.append(tests.parent / file_part)
            for candidate in candidates:
                if candidate.is_file():
                    test = resolve_workspace_path(root, candidate.relative_to(root).as_posix())
                    break
        if test is None:
            warnings.append("Test source is unresolved; verify the exact workspace-relative test node ID.")
        payload["test_file"] = os.path.relpath(test, wave.parent).replace(os.sep, "/") if test else None
        payload["test_case"] = test_case
    if not sources:
        warnings.append("No related design source was determined; provide source_files after inspecting relevant sources.")
    return meta, normalize_waveform_viewer_payload(payload), warnings


def waveform_viewer_semantics(viewer: object) -> dict | None:
    """Compare analysis and workspace-relative associations across session rotations."""
    if not isinstance(viewer, dict) or not isinstance(viewer.get("payload"), dict):
        return None
    payload = viewer["payload"]
    result = {key: payload.get(key) for key in ("schema_version", "test_case", "start", "end", "cursor", "signals")}
    base = posixpath.dirname(viewer["meta"])
    result["source_files"] = [posixpath.normpath(posixpath.join(base, value)) for value in payload["source_files"]]
    for key in ("dut_python_path", "test_file"):
        value = payload.get(key)
        result[key] = posixpath.normpath(posixpath.join(base, value)) if value else None
    return result
