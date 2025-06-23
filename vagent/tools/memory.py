#coding=utf-8


from mem0 import Memory
from .uctool import UCTool
from langchain_core.tools.base import ArgsSchema

from typing import Optional, List
from pydantic import BaseModel, Field

import os
from vagent.util.log import info


class ArgsMemSearch(BaseModel):
    """Arguments for memory search"""
    query: str = Field(..., description="The query string to search")
    limit: int = Field(3, description="The maximum number of results to return", ge=1, le=100)


class ReferenceDoc(UCTool):
    """Search task referce documents and examples"""
    name: str = "ReferenceDoc"
    description: str = (
        "List all files and directories in a workspace directory, including subdirectories. "
        "Returns a list with index, name, type, and size."
    )
    args_schema: Optional[ArgsSchema] = ArgsMemSearch

    def __init__(self, url, key, workspace, doc_path, file_extension: List[str] = [".md", ".py", ".v"]):
        super().__init__()
        self.memory = Memory()
        self.workspace = os.path.abspath(workspace)
        self.doc_path = os.path.abspath(os.path.join(workspace, doc_path))
        assert os.path.exists(self.doc_path), f"Doc path {self.doc_path} does not exist."
        for root, _, files in os.walk(self.doc_path):
            for file in files:
                if any(file.endswith(ext) for ext in file_extension):
                    file_path = os.path.abspath(os.path.join(root, file)).removeprefix(self.workspace + os.sep)
                    data = {
                        "file": file_path,
                        "content": open(os.path.join(root, file), 'r', encoding='utf-8').read()
                        }
                    self.memory.add(data)
                    info(f"Added file {file_path} to memory.")

    def _run(self, query: str, limit: int = 3, run_manager = None) -> str:
        return self.memory.search(query, limit=limit)

