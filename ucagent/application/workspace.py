"""Resolve local, archived and temporary workspaces before configuration loading."""

import base64
import os
import ntpath
import posixpath
import shutil
import stat
import tarfile
import tempfile
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from ucagent.version import __version__

class WorkspaceArchiveError(ValueError):
    """Raised when a workspace archive cannot be downloaded, extracted, or validated."""


def _normalize_archive_member_path(name: str) -> str:
    """Reject archive entries outside the workspace root."""
    raw = name or ""
    raw_parts = raw.split("/")
    normalized = posixpath.normpath(raw)
    if (
        "\\" in raw
        or normalized in ("", ".")
        or ".." in raw_parts
        or normalized.startswith("../")
        or normalized == ".."
        or posixpath.isabs(normalized)
        or ntpath.isabs(raw)
    ):
        raise WorkspaceArchiveError(f"Unsafe archive entry path: {name}")
    parts = normalized.split("/")
    if not parts or parts[0] != "workspace":
        raise WorkspaceArchiveError(
            "Invalid workspace archive layout: archive root must contain a direct 'workspace' directory"
        )
    return normalized


def _validate_archive_symlink(member: tarfile.TarInfo, normalized_name: str) -> None:
    """Reject links whose resolved target escapes the extracted workspace."""
    linkname = member.linkname or ""
    if (
        not linkname
        or "\\" in linkname
        or posixpath.isabs(linkname)
        or ntpath.isabs(linkname)
    ):
        raise WorkspaceArchiveError(f"Unsafe archive symlink target: {member.name} -> {linkname}")

    target = posixpath.normpath(posixpath.join(posixpath.dirname(normalized_name), linkname))
    if (
        target in ("", ".", "..")
        or target.startswith("../")
        or posixpath.isabs(target)
        or not (target == "workspace" or target.startswith("workspace/"))
    ):
        raise WorkspaceArchiveError(f"Unsafe archive symlink target: {member.name} -> {linkname}")


def _extractall_workspace_archive(tf: tarfile.TarFile, extract_dir: str) -> None:
    """Extract validated members using the available tar safety filter."""
    data_filter = getattr(tarfile, "data_filter", None)
    extractall_kwargs = getattr(tarfile.TarFile.extractall, "__kwdefaults__", {}) or {}
    if data_filter is not None and "filter" in extractall_kwargs:
        tf.extractall(extract_dir, filter=data_filter)
    else:
        tf.extractall(extract_dir)


def _is_workspace_archive_source(workspace: str) -> bool:
    """Recognize local and HTTP tarball inputs."""
    raw = str(workspace or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    if parsed.scheme in ("http", "https"):
        return parsed.path.lower().endswith(".tar.gz")
    return raw.lower().endswith(".tar.gz")


def _archive_name_from_source(source: str) -> str:
    """Derive a bounded extraction directory name from the archive basename."""
    parsed = urlparse(source)
    if parsed.scheme in ("http", "https"):
        name = posixpath.basename(parsed.path)
    else:
        name = os.path.basename(source)
    if not name.lower().endswith(".tar.gz"):
        raise WorkspaceArchiveError(
            f"Workspace archive must be a .tar.gz file or http(s) .tar.gz URL: {source}"
        )
    stem = name[:-7]
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in stem).strip("._-")
    if not cleaned:
        raise WorkspaceArchiveError(f"Cannot infer extraction directory name from workspace archive: {source}")
    return cleaned


def _download_workspace_archive(source_url: str, archive_path: str) -> None:
    """Download an authenticated archive without exposing credentials in errors."""
    parsed = urlparse(source_url)
    headers = {"User-Agent": f"UCAgent/{__version__}"}
    query = parse_qs(parsed.query, keep_blank_values=True)
    access_keys = query.pop("key", [])
    if access_keys and access_keys[0]:
        headers["X-Access-Key"] = access_keys[0]
    elif os.environ.get("UCAGENT_WORKSPACE_ARCHIVE_KEY"):
        headers["X-Access-Key"] = os.environ["UCAGENT_WORKSPACE_ARCHIVE_KEY"]
    if os.environ.get("UCAGENT_WORKSPACE_ARCHIVE_PASSWORD"):
        token = base64.b64encode(f":{os.environ['UCAGENT_WORKSPACE_ARCHIVE_PASSWORD']}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    clean_query = urlencode([(key, value) for key, values in query.items() for value in values])
    request_url = urlunparse(parsed._replace(query=clean_query))
    display_url = urlunparse(parsed._replace(query=clean_query))
    request = Request(request_url, headers=headers)
    try:
        with urlopen(request, timeout=60) as response:
            status = getattr(response, "status", 200)
            if status and int(status) >= 400:
                raise WorkspaceArchiveError(f"Failed to download workspace archive: HTTP {status} {display_url}")
            with open(archive_path, "wb") as fh:
                shutil.copyfileobj(response, fh)
    except HTTPError as exc:
        raise WorkspaceArchiveError(
            f"Failed to download workspace archive from {display_url}: HTTP {exc.code} {exc.reason}"
        ) from exc
    except URLError as exc:
        raise WorkspaceArchiveError(
            f"Failed to download workspace archive from {display_url}: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise WorkspaceArchiveError(f"Timed out downloading workspace archive from {display_url}") from exc
    except OSError as exc:
        raise WorkspaceArchiveError(
            f"Failed to save downloaded workspace archive to {archive_path}: {exc}"
        ) from exc
    if not os.path.isfile(archive_path) or os.path.getsize(archive_path) == 0:
        raise WorkspaceArchiveError(f"Downloaded workspace archive is empty: {display_url}")


def _make_path_removable(path: str) -> None:
    """Restore owner permissions on one non-symlink path before archive cleanup."""
    try:
        st = os.lstat(path)
    except OSError:
        return
    if stat.S_ISLNK(st.st_mode):
        return
    chflags = getattr(os, "chflags", None)
    if chflags is not None:
        try:
            chflags(path, 0)
        except OSError:
            pass
    mode = stat.S_IMODE(st.st_mode) | stat.S_IRUSR | stat.S_IWUSR
    if stat.S_ISDIR(st.st_mode):
        mode |= stat.S_IXUSR
    try:
        os.chmod(path, mode)
    except OSError:
        return


def _make_tree_removable(path: str) -> None:
    """Restore cleanup permissions without following directory symlinks."""
    _make_path_removable(path)
    for root, dirs, files in os.walk(path, topdown=True, followlinks=False):
        _make_path_removable(root)
        for name in dirs:
            _make_path_removable(os.path.join(root, name))
        for name in files:
            _make_path_removable(os.path.join(root, name))


def _remove_workspace_archive_extract(extract_dir: str) -> None:
    """Remove one resolved archive extraction tree."""
    def _on_remove_error(func, failed_path, exc_info):
        """Retry a failed removal after restoring owner permissions."""
        _make_path_removable(os.path.dirname(failed_path))
        _make_path_removable(failed_path)
        func(failed_path)

    if os.path.islink(extract_dir) or os.path.isfile(extract_dir):
        _make_path_removable(os.path.dirname(extract_dir))
        _make_path_removable(extract_dir)
        os.unlink(extract_dir)
        return
    _make_tree_removable(extract_dir)
    shutil.rmtree(extract_dir, onerror=_on_remove_error)


def _write_workspace_archive_marker(marker_path: str, workspace: str, effective_workspace: str = "") -> None:
    """Record the archive source and resolved workspace for inspection."""
    try:
        with open(marker_path, "w", encoding="utf-8") as fh:
            fh.write(f"source={workspace}\n")
            if effective_workspace:
                fh.write(f"workspace={effective_workspace}\n")
    except OSError:
        pass


def _safe_extract_workspace_archive(archive_path: str, extract_dir: str, dut_name: str) -> str:
    """Validate archive paths and links before extracting a DUT workspace."""
    workspace_dir = os.path.join(extract_dir, "workspace")
    try:
        with tarfile.open(archive_path, "r:gz") as tf:
            members = tf.getmembers()
            if not members:
                raise WorkspaceArchiveError("Workspace archive is empty")
            has_workspace_root = False
            for member in members:
                name = member.name or ""
                normalized = _normalize_archive_member_path(name)
                if member.islnk():
                    raise WorkspaceArchiveError(f"Unsupported archive hard link entry: {name}")
                if member.issym():
                    _validate_archive_symlink(member, normalized)
                elif not (member.isdir() or member.isfile()):
                    raise WorkspaceArchiveError(f"Unsupported archive entry type: {name}")
                if member.isdir() and normalized == "workspace":
                    has_workspace_root = True
                if normalized == "workspace" or normalized.startswith("workspace/"):
                    has_workspace_root = True
            if not has_workspace_root:
                raise WorkspaceArchiveError(
                    "Invalid workspace archive layout: missing root 'workspace' directory"
                )
            _extractall_workspace_archive(tf, extract_dir)
    except WorkspaceArchiveError:
        raise
    except tarfile.TarError as exc:
        raise WorkspaceArchiveError(f"Invalid or unreadable .tar.gz workspace archive: {archive_path}: {exc}") from exc
    except OSError as exc:
        raise WorkspaceArchiveError(f"Failed to extract workspace archive to {extract_dir}: {exc}") from exc

    if not os.path.isdir(workspace_dir):
        raise WorkspaceArchiveError(
            f"Invalid workspace archive layout: extracted directory is missing '{workspace_dir}'"
        )
    dut_path = os.path.join(workspace_dir, dut_name)
    if not os.path.isdir(dut_path):
        raise WorkspaceArchiveError(
            f"Invalid workspace archive layout: expected DUT directory '{dut_name}' under '{workspace_dir}'"
        )
    return workspace_dir


def _prepare_workspace_archive_source(workspace: str, dut_name: str, workspace_base: str) -> str:
    """Resolve an ordinary workspace or safely materialize an archive."""
    parsed = urlparse(str(workspace or ""))
    if parsed.scheme in ("http", "https") and not _is_workspace_archive_source(workspace):
        raise WorkspaceArchiveError(f"Remote workspace URL must point to a .tar.gz archive: {workspace}")
    if not _is_workspace_archive_source(workspace):
        return workspace
    if not dut_name:
        raise WorkspaceArchiveError("DUT name is required when workspace is a .tar.gz archive")

    archive_name = _archive_name_from_source(workspace)
    base_dir = os.path.abspath(os.path.expanduser(workspace_base or "/tmp/ucagent_workspace_base"))
    extract_dir = os.path.join(base_dir, archive_name)
    marker_path = os.path.join(extract_dir, ".ucagent_archive_extract")
    try:
        os.makedirs(base_dir, exist_ok=True)
    except OSError as exc:
        raise WorkspaceArchiveError(f"Failed to create --workspace-base directory '{base_dir}': {exc}") from exc

    if os.path.lexists(extract_dir):
        try:
            _remove_workspace_archive_extract(extract_dir)
        except OSError as exc:
            raise WorkspaceArchiveError(f"Failed to clean previous extracted workspace '{extract_dir}': {exc}") from exc
    try:
        os.makedirs(extract_dir, exist_ok=False)
        _write_workspace_archive_marker(marker_path, workspace)
        with tempfile.TemporaryDirectory(prefix="ucagent_workspace_archive_") as tmp_dir:
            archive_path = workspace
            if parsed.scheme in ("http", "https"):
                archive_path = os.path.join(tmp_dir, f"{archive_name}.tar.gz")
                _download_workspace_archive(workspace, archive_path)
            else:
                archive_path = os.path.abspath(os.path.expanduser(workspace))
                if not os.path.isfile(archive_path):
                    raise WorkspaceArchiveError(f"Workspace archive file not found: {archive_path}")
            effective_workspace = _safe_extract_workspace_archive(archive_path, extract_dir, dut_name)
    except Exception:
        try:
            _remove_workspace_archive_extract(extract_dir)
        except OSError:
            pass
        raise

    _write_workspace_archive_marker(marker_path, workspace, effective_workspace)
    print(f"Workspace archive extracted to: {extract_dir}")
    print(f"Effective workspace: {effective_workspace}")
    return effective_workspace


def prepare_workspace(workspace, dut_name, workspace_base="/tmp/ucagent_workspace_base", *,
        temporary_prefix=None, create_workspace=False, create_dut=False, cleanup=None):
    """Resolve workspace sources and register temporary lifetime with the caller's cleanup owner."""
    if temporary_prefix is not None:
        if cleanup is None:
            raise ValueError("A temporary workspace requires a cleanup owner")
        temporary = tempfile.TemporaryDirectory(prefix=temporary_prefix)
        cleanup.callback(temporary.cleanup)
        workspace = temporary.name
    if workspace is None or dut_name is None:
        raise ValueError("workspace and dut_name are required")
    if create_workspace:
        os.makedirs(workspace, exist_ok=True)
    if create_dut:
        dut_path = os.path.join(workspace, dut_name)
        os.makedirs(dut_path, exist_ok=True)
        with open(os.path.join(dut_path, "__init__.py"), "w", encoding="utf-8"):
            pass
    return _prepare_workspace_archive_source(workspace, dut_name, workspace_base)
