"""Memory tool regressions without network embeddings or LangMem dependencies."""

from datetime import datetime
import json

from langchain_core.embeddings import DeterministicFakeEmbedding
from langgraph.graph import END, START, StateGraph
from langgraph.store.memory import InMemoryStore
import pytest

from ucagent.tools import memory
from ucagent.tools.memory import MemoryGet, MemoryPut, SemanticSearchInGuidDoc


def test_memory_round_trip_preserves_scopes_json_and_timestamps():
    """Writes and searches must share scopes and serialize complete store records."""
    store = InMemoryStore()
    put = MemoryPut().set_store(store=store)
    get = MemoryGet().set_store(store=store)
    data = {"title": "verification \u2713", "items": [1, True, None, {"ratio": 1.5}]}
    put._run("general", data)
    put._run("private", "hidden")

    results = json.loads(get.invoke({"scope": "general", "query": "verification"}))
    assert len(results) == 1
    item = results[0]
    assert item["namespace"] == ["general"]
    assert item["value"] == {"content": data}
    assert item["key"].isdigit()
    for key in ("created_at", "updated_at"):
        assert datetime.fromisoformat(item[key]).tzinfo is not None
    assert json.loads(get._run("missing", "query")) == []
    put.invoke({"scope": "general", "data": "second entry"})
    assert len(json.loads(get._run("general", "query", limit=1))) == 1
    assert len(store.search(("general",))) == 2


def test_memory_configurable_scope_resolves_in_current_graph_context():
    """Dynamic scopes must isolate users using the current runnable configuration."""
    store = InMemoryStore()
    put = MemoryPut().set_store(store=store)
    get = MemoryGet().set_store(store=store)

    def remember(state):
        """Use the same dynamic scope for both memory operations in a graph node."""
        put.invoke({"scope": "{user_id}", "data": state["data"]})
        return {"results": json.loads(get.invoke({"scope": "{user_id}", "query": "data"}))}

    graph = StateGraph(dict)
    graph.add_node("remember", remember)
    graph.add_edge(START, "remember")
    graph.add_edge("remember", END)
    runnable = graph.compile()
    for user in ("alice", "bob"):
        result = runnable.invoke({"data": user}, {"configurable": {"user_id": user}})
        assert [item["value"] for item in result["results"]] == [{"content": user}]
        assert result["results"][0]["namespace"] == [user]


@pytest.mark.parametrize("tool,args", [
    (MemoryPut, {"data": "content"}),
    (MemoryGet, {"query": "content"}),
])
def test_memory_missing_scope_configuration_is_actionable(tool, args):
    """A missing dynamic scope must fail without writing to a shared fallback."""
    store = InMemoryStore()
    with pytest.raises(ValueError, match="Missing memory scope key 'user_id'.*Set this key"):
        tool().set_store(store=store).invoke({"scope": "{user_id}", **args})
    assert store.list_namespaces() == []


def test_document_search_indexes_supported_files_and_serializes_results(tmp_path, monkeypatch):
    """Documentation search must retain file keys, Unicode content and limits."""
    docs = tmp_path / "Guide_Doc"
    docs.mkdir()
    (docs / "guide.md").write_text("verification \u2713", encoding="utf-8")
    (docs / "example.py").write_text("assert 1 + 1 == 2", encoding="utf-8")
    (docs / "ignored.txt").write_text("not indexed", encoding="utf-8")
    monkeypatch.setattr(memory, "new_embed", lambda config: {
        "embed": DeterministicFakeEmbedding(size=8), "dims": 8,
    })
    tool = SemanticSearchInGuidDoc({}, str(tmp_path), "Guide_Doc")
    items = json.loads(tool.invoke({"query": "verification", "limit": 2}))
    assert {item["key"] for item in items} == {"Guide_Doc/guide.md", "Guide_Doc/example.py"}
    assert all(item["namespace"] == ["doc_reference"] for item in items)
    assert {item["value"]["content"] for item in items} == {
        "verification \u2713", "assert 1 + 1 == 2",
    }
    assert len(json.loads(tool.invoke({"query": "verification", "limit": 1}))) == 1
