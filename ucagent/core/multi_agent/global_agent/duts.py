"""Discover DUT inputs within explicit project boundaries without reading runtime trees."""
from pathlib import Path
import os
import re


class DUTCatalog:
    """Resolve concrete DUT/source pairs, requiring clarification for ambiguous names."""

    def __init__(self, project, roots=(), runtime_root=None):
        """Retain the project and additional explicitly allowed source roots."""
        self.project = Path(project).resolve()
        self.roots = list(dict.fromkeys([self.project, *[(self.project / p).resolve() for p in roots]]))
        self.runtime_root = Path(runtime_root).resolve() if runtime_root else None

    def source(self, value):
        """Resolve source paths relative to the project and enforce configured boundaries."""
        path = (self.project / value).resolve()
        if not path.is_dir() or not any(path.is_relative_to(root) for root in self.roots):
            raise ValueError("source_workspace must be an existing directory inside the configured workspace roots")
        if ".ucagent" in path.relative_to(next(root for root in self.roots if path.is_relative_to(root))).parts or (self.runtime_root and path.is_relative_to(self.runtime_root)):
            raise ValueError("Cannot use session runtime state as a source workspace")
        return path

    def list(self, query=None):
        """List bounded RTL and prepared-workspace candidates with explicit source paths."""
        rows, seen, visited = [], set(), 0
        for root in self.roots:
            for directory, dirs, files in os.walk(root, followlinks=False):
                path = Path(directory)
                dirs[:] = sorted(name for name in dirs if not name.startswith('.') and name not in {
                    "node_modules", "__pycache__", "Guide_Doc", "docs", "tests", "ucagent", "build"}
                    and not (path / name).is_symlink()
                    and not (self.runtime_root and (path / name).resolve().is_relative_to(self.runtime_root)))
                visited += 1
                if visited > 2000:
                    return {"duts": rows, "truncated": True, "searched_roots": [str(p) for p in self.roots]}
                prepared = [name[:-4] for name in dirs if name.endswith("_RTL") and
                            any((path / name / (name[:-4] + ext)).is_file() for ext in (".v", ".sv"))]
                candidates = [(name, "prepared") for name in prepared]
                if not prepared:
                    candidates = [(Path(name).stem, "source") for name in sorted(files)
                                  if Path(name).suffix in {".v", ".sv"} and not (path / name).is_symlink()]
                else:
                    dirs[:] = [name for name in dirs if name not in {*prepared, *(n + "_RTL" for n in prepared)}]
                for name, kind in candidates:
                    key = (name, str(path))
                    if key in seen or (query and query.casefold() not in name.casefold()):
                        continue
                    seen.add(key)
                    rows.append({"dut_name": name, "source_workspace": str(path), "kind": kind})
                    if len(rows) >= 200:
                        return {"duts": rows, "truncated": True, "searched_roots": [str(p) for p in self.roots]}
                if len(path.relative_to(root).parts) >= 3:
                    dirs[:] = []
        return {"duts": rows, "truncated": False, "searched_roots": [str(p) for p in self.roots]}

    def resolve(self, dut_name, source_workspace):
        """Never guess a DUT from Global's placeholder name or an ambiguous candidate set."""
        if dut_name is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$-]*", dut_name):
            raise ValueError("dut_name must be a module name, not a path")
        source = self.source(source_workspace) if source_workspace else None
        if source is not None and dut_name:
            return dut_name, source
        listing = self.list(dut_name) if source is None else DUTCatalog(source).list(dut_name)
        if listing["truncated"]:
            raise ValueError("DUT search is incomplete; provide an exact source_workspace and dut_name from ListDUTs or the user.")
        candidates = listing["duts"]
        if dut_name:
            candidates = [row for row in candidates if row["dut_name"] == dut_name]
        if len(candidates) != 1:
            raise ValueError(f"DUT source is missing or ambiguous ({len(candidates)} candidates). Call ListDUTs, then specify dut_name and source_workspace; ask the user when multiple sources match.")
        row = candidates[0]
        return row["dut_name"], self.source(row["source_workspace"])
