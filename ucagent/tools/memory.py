# -*- coding: utf-8 -*-
"""Memory management tools for UCAgent."""

import json
import time
from .uctool import UCTool
from langchain_core.tools.base import ArgsSchema

from typing import Optional, List
from pydantic import BaseModel, Field

import os
from ucagent.util.log import info


from langgraph.store.memory import InMemoryStore
from langgraph.config import get_config
from langchain_openai import OpenAIEmbeddings


def _memory_namespace(scope: str) -> tuple[str, ...]:
    """Resolve a fixed scope or a configurable scope such as ``{user_id}``."""
    if not scope.startswith("{"):
        return (scope,)
    key = scope.strip("{}")
    try:
        configurable = get_config().get("configurable", {})
    except RuntimeError:
        configurable = {}
    if key not in configurable:
        raise ValueError(
            f"Missing memory scope key '{key}' in 'configurable'. "
            f"Available keys: {list(configurable)}. "
            "Set this key in the runnable configuration or use a fixed scope."
        )
    return (configurable[key],)


class ArgsMemSearch(BaseModel):
    """Arguments for memory search"""
    query: str = Field(..., description="The query string to search")
    limit: int = Field(3, description="The maximum number of results to return, default 3", ge=1, le=100)


def new_embed(config) -> dict:
    """Create the embedding index configuration used by memory stores."""
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
    namespace: tuple[str, ...] = Field(("doc_reference",),
        description="Namespace for document references"
    )

    def __init__(self, config, workspace, doc_path, file_extension: List[str] = [".md", ".py", ".v"]):
        """Index matching documentation files within the configured workspace."""
        super().__init__()
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
                    with open(os.path.join(root, file), 'r', encoding='utf-8') as source:
                        content = source.read()
                    self.store.put(self.namespace,
                                   key=str(file_path),
                                   value={"content": content})
                    info(f"Added file {file_path} to memory.")

    def _run(self, query: str, limit: int = 3, run_manager = None) -> str:
        """Return matching documentation records as JSON, including timestamps."""
        memories = self.store.search(
            self.namespace,
            query=query,
            filter=None,
            limit=limit,
            offset=0,
        )
        return json.dumps([m.dict() for m in memories], ensure_ascii=False)


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
    """Base tool for sharing a configured in-memory store."""
    store: InMemoryStore = Field(None, description="In-memory store for document references")
    def set_store(self, config=None, store: Optional[InMemoryStore] = None):
        """Use an existing store or create one from the embedding configuration."""
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
            _memory_namespace(scope),
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
            _memory_namespace(scope),
            query=query,
            filter=None,
            limit=limit,
            offset=0,
        )
        return json.dumps([m.dict() for m in memories], ensure_ascii=False)
