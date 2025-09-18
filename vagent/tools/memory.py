# -*- coding: utf-8 -*-
"""Memory management tools for UCAgent."""

from mem0 import Memory
import time
from .uctool import UCTool
from langchain_core.tools.base import ArgsSchema

from typing import Optional, List, Union
from pydantic import BaseModel, Field

import os
from vagent.util.log import info


from langgraph.store.memory import InMemoryStore
from langchain_openai import OpenAIEmbeddings
from langmem import utils


class ArgsMemSearch(BaseModel):
    """Arguments for memory search"""
    query: str = Field(..., description="The query string to search")
    limit: int = Field(3, description="The maximum number of results to return, default 3", ge=1, le=100)


def new_embed(config) -> dict:
    info(f"Creating new embedding with model: {config['model_name']}, base_url: {config['openai_api_base']}")
    return {"embed":OpenAIEmbeddings(model   = config["model_name"],
                            base_url= config["openai_api_base"],
                            api_key = config["openai_api_key"]),
            "dims":config["dims"]
            }

class SemanticSearchInGuidDoc(UCTool):
    """Semantic search in the guild documentation for verification definitions and examples."""
    name: str = "SemanticSearchInGuidDoc"
    description: str = (
        "Semantic search in the guild documentation for verification definitions and examples. "
    )
    args_schema: Optional[ArgsSchema] = ArgsMemSearch

    # custom variables
    workspace: str = Field(str, description="The workspace directory to search in")
    doc_path: str = Field(str, description="The path to the documentation directory relative to the workspace")
    store: InMemoryStore = Field(InMemoryStore, description="In-memory store for document references")
    namespace: utils.NamespaceTemplate = Field(utils.NamespaceTemplate,
        description="Namespace template for document references"
    )

    def __init__(self, config, workspace, doc_path, file_extension: List[str] = [".md", ".py", ".v"]):
        super().__init__()
        self.namespace = utils.NamespaceTemplate("doc_reference")
        self.store = InMemoryStore(
            index=new_embed(config)
        )
        self.workspace = os.path.abspath(workspace)
        self.doc_path = os.path.abspath(os.path.join(workspace, doc_path))
        assert os.path.exists(self.doc_path), f"Doc path {self.doc_path} does not exist."
        info(f"Initializing SearchInGuidDoc with workspace: {self.workspace}, doc_path: {self.doc_path}")
        for root, _, files in os.walk(self.doc_path):
            for file in files:
                if any(file.endswith(ext) for ext in file_extension):
                    file_path = os.path.abspath(os.path.join(root, file)).removeprefix(self.workspace + os.sep)
                    self.store.put(self.namespace(),
                                   key=str(file_path),
                                   value={"content": open(os.path.join(root, file), 'r', encoding='utf-8').read()}),
                    info(f"Added file {file_path} to memory.")

    def _run(self, query: str, limit: int = 3, run_manager = None) -> str:
        memories = self.store.search(
            self.namespace(),
            query=query,
            filter=None,
            limit=limit,
            offset=0,
        )
        return utils.dumps([m.dict() for m in memories])


class ArgsMemoryPut(BaseModel):
    """Arguments for MemoryPut"""
    scope: str = Field(..., description="The scope of the memory, e.g., 'general', 'task-specific'")
    data: str = Field(..., description="The content to save in memory, can be a string or a JSON object")


class ArgsMemoryGet(BaseModel):
    """Arguments for MemoryGet"""
    scope: str = Field(..., description="The scope of the memory, e.g., 'general', 'task-specific'")
    query: str = Field(..., description="The query string to search")
    limit: int = Field(3, description="The maximum number of results to return, default 3", ge=1, le=100)


class MemoryTool(UCTool):
    store: InMemoryStore = Field(None, description="In-memory store for document references")
    def set_store(self, config=None, store: Optional[InMemoryStore] = None):
        super().__init__()
        if store is not None:
            self.store = store
        else:
            self.store = InMemoryStore(
                index=new_embed(config)
            )
        return self

    def get_store(self):
        """Get the in-memory store."""
        return self.store


class MemoryPut(MemoryTool):
    """Save important information to long-term memory."""
    name: str = "MemoryPut"
    description: str = (
        "Save important information to long-term memory. "
        "This tool allows you to store content in the memory store for future reference. "
        "The content can be a string or a JSON object. "
        "You can specify the scope of the memory, such as 'general' or 'task-specific'. "
        "The content will be saved in the memory store and can be retrieved later using the MemoryGet tool."
    )
    args_schema: Optional[ArgsSchema] = ArgsMemoryPut

    def _run(self, scope: str, data, run_manager = None) -> str:
        """Save the content to the memory store."""
        key = str(time.time_ns())
        self.store.put(
            utils.NamespaceTemplate(scope)(),
            key=key,  # Use a unique key based on the current time
            value={"content": data}
        )
        return f"Content saved to memory under scope '{scope}' with key '{key}' complete. "


class MemoryGet(MemoryTool):
    """Retrieve information from long-term memory."""
    name: str = "MemoryGet"
    description: str = (
        "Retrieve information from long-term memory. "
        "This tool allows you to search for content in the memory store based on a query. "
        "You can specify the scope of the memory, such as 'general' or 'task-specific'. "
        "The tool will return the most relevant content based on the query."
    )
    args_schema: Optional[ArgsSchema] = ArgsMemoryGet

    def _run(self, scope: str, query: str, limit: int = 3, run_manager = None) -> str:
        """Search for content in the memory store."""
        memories = self.store.search(
            utils.NamespaceTemplate(scope)(),
            query=query,
            filter=None,
            limit=limit,
            offset=0,
        )
        return utils.dumps([m.dict() for m in memories])
