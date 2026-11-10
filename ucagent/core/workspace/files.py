"""Workspace-confined file operations without HTTP objects or LLM usage evidence."""

from contextlib import contextmanager
import mimetypes
import os
from pathlib import Path
import shutil

from ucagent.util.file_policy import resolve_workspace_path


class WorkspaceAccessError(ValueError):
    """Describe an invalid workspace operation independently of its transport."""

    def __init__(self, code, message):
        """Keep a stable error code alongside the user-facing explanation."""
        super().__init__(message)
        self.code = code


_TEXT_EXTS = {
    ".txt", ".md", ".rst", ".py", ".js", ".ts", ".css", ".html", ".htm",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".sh",
    ".bash", ".zsh", ".fish", ".v", ".sv", ".svh", ".vhd", ".vhdl",
    ".c", ".h", ".cpp", ".hpp", ".java", ".rs", ".go", ".rb", ".php",
    ".xml", ".csv", ".log", ".env", ".gitignore", ".makefile", ".mk",
    ".scala", ".lua", ".r", ".m", ".tex", ".bib", ".diff", ".patch",
}


def is_text_file(path):
    """Identify file-manager text candidates by filename and MIME type."""
    candidate = Path(path)
    if candidate.suffix.lower() in _TEXT_EXTS or candidate.name.lower() in _TEXT_EXTS or "." + candidate.name.lower() in _TEXT_EXTS:
        return True
    mime, _ = mimetypes.guess_type(path)
    return bool(mime and mime.startswith("text/"))


class WorkspaceFiles:
    """Use operator filesystem permissions within one explicitly selected root.

    Task write-directory restrictions belong to LLM tools; these operations never
    change chmod or manufacture tool-read/use evidence.
    """

    def __init__(self, root):
        """Bind a root without reading or changing workspace state."""
        self.root = os.path.abspath(root)

    def path(self, relative, *, allow_root=True):
        """Validate both lexical and final symlink targets for every operation."""
        try:
            return resolve_workspace_path(self.root, relative, allow_workspace=allow_root)
        except ValueError as error:
            raise WorkspaceAccessError("invalid_path", str(error)) from error

    def read_bytes(self, relative):
        """Read one existing regular file after workspace containment validation."""
        target = self.path(relative)
        if not os.path.isfile(target):
            raise WorkspaceAccessError("not_found", f"File '{relative}' not found or is a directory")
        return Path(target).read_bytes()

    def read_text(self, relative):
        """Read file-manager text using the existing UTF-8/Latin-1 decoding contract."""
        target = self.path(relative)
        if not os.path.isfile(target):
            raise WorkspaceAccessError("not_found", f"File '{relative}' not found")
        if not is_text_file(target):
            raise WorkspaceAccessError("invalid_argument", f"'{relative}' does not appear to be a text file")
        size = os.stat(target).st_size
        for encoding in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                with open(target, encoding=encoding) as stream:
                    content = stream.read()
                break
            except UnicodeDecodeError:
                continue
        return {"path": relative, "size": size, "content": content, "exists": True}

    def list_directory(self, relative=""):
        """List metadata for entries whose final targets remain in this workspace."""
        target = self.path(relative)
        if not os.path.isdir(target):
            raise WorkspaceAccessError("invalid_argument", f"'{relative}' is not a directory")
        entries = []
        for name in os.listdir(target):
            rel = os.path.relpath(os.path.join(target, name), self.root)
            try:
                full = self.path(rel)
                stat = os.stat(full)
            except (OSError, WorkspaceAccessError):
                continue
            is_dir = os.path.isdir(full)
            entries.append({"name": name, "path": rel, "is_dir": is_dir,
                            "size": 0 if is_dir else stat.st_size, "mtime": stat.st_mtime,
                            "type": "" if is_dir else Path(name).suffix.lstrip(".").lower(),
                            "is_text": not is_dir and is_text_file(full)})
        return sorted(entries, key=lambda row: (not row["is_dir"], row["name"].lower()))

    def write_text(self, relative, content, *, create=False):
        """Create exclusively or overwrite a text file without changing its permissions."""
        target = self.path(relative, allow_root=False)
        if create and os.path.lexists(target):
            raise WorkspaceAccessError("conflict", f"'{relative}' already exists")
        if not os.path.isdir(os.path.dirname(target)):
            raise WorkspaceAccessError("invalid_argument", "Parent directory does not exist")
        with open(target, "x" if create else "w", encoding="utf-8") as stream:
            stream.write(content)
        return {"path": relative, "size": len(content.encode("utf-8"))}

    def rename(self, relative, new_name):
        """Rename an entry to one plain filename in its current directory."""
        source = self.path(relative, allow_root=False)
        name = new_name.strip()
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise WorkspaceAccessError("invalid_argument", "new_name must be a plain filename")
        if not os.path.lexists(source):
            raise WorkspaceAccessError("not_found", f"'{relative}' not found")
        new_relative = os.path.join(os.path.dirname(os.path.relpath(source, self.root)), name)
        destination = self.path(new_relative, allow_root=False)
        if os.path.lexists(destination):
            raise WorkspaceAccessError("conflict", f"'{name}' already exists in the same directory")
        os.rename(source, destination)
        return new_relative

    def delete(self, relative):
        """Delete one selected entry recursively, protecting the selected workspace root."""
        target = self.path(relative, allow_root=False)
        if not os.path.lexists(target):
            raise WorkspaceAccessError("not_found", f"'{relative}' not found")
        if os.path.isdir(target) and not os.path.islink(target):
            shutil.rmtree(target)
        else:
            os.unlink(target)

    @contextmanager
    def upload(self, directory, filename):
        """Open a validated final upload target and close it on success or failure."""
        parent = self.path(directory)
        if not os.path.isdir(parent):
            raise WorkspaceAccessError("invalid_argument", f"Target path '{directory}' is not a directory")
        name = Path(filename or "upload").name
        relative = os.path.join(os.path.relpath(parent, self.root), name)
        target = self.path(relative, allow_root=False)
        with open(target, "wb") as stream:
            yield stream, os.path.relpath(target, self.root)
