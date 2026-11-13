"""H1 contracts for trusted workflow metadata, configuration and input selection."""

from pathlib import Path
from types import SimpleNamespace
import pytest

from ucagent.core.plugins import Plugin, PluginWorkflow, LoadedPlugin
from ucagent.core.workflow.contracts import (
    HandoffSettings, NextWorkflow, WorkflowCatalog, execution_overrides,
    load_handoff_settings, source_file,
)
from ucagent.util.config import Config


def catalog(tmp_path):
    """Construct declarations only, with a factory that must never be activated."""
    config = tmp_path / "workflow.yaml"
    config.write_text("stage: []\n")

    def forbidden(context):
        """Fail if discovery activates a candidate's business tools."""
        pytest.fail("Catalog activated a plugin tool")

    plugin = Plugin(name="fixture", version="1.0", description="Fixture", root=tmp_path,
                    tool_factories=(forbidden,), workflows=(
        PluginWorkflow("a", config, purpose="Produce payload", outputs={"out/a.json": "payload", "out/result.md": "evidence"}),
        PluginWorkflow("b", config, purpose="Consume payload", inputs={"inputs/a.json": "payload"})))
    settings = HandoffSettings(allowed_workflows=["fixture:a", "fixture:b"],
                               allowed_next={"fixture:a": ["fixture:b"], "fixture:b": []})
    return WorkflowCatalog(settings, [LoadedPlugin(plugin, "fixture", "test")])


def request(**changes):
    """Create one current-contract request without process or configuration authority."""
    return NextWorkflow.model_validate(dict(workflow_ref="fixture:b", reason="Continue", summary="A accepted",
        inputs={"inputs/a.json": "out/a.json"}, transition_token="current", **changes))


def test_catalog_is_inert_and_validates_target(tmp_path):
    """Listing candidates cannot construct tools and selection obeys declared input contracts."""
    value = catalog(tmp_path)
    assert value.entries["fixture:b"].describe()["purpose"] == "Consume payload"
    assert value.select("fixture:a", request(), ["fixture:a"]).ref == "fixture:b"
    with pytest.raises(ValueError, match="successor"):
        value.select("fixture:b", request(), ["fixture:a"])
    with pytest.raises(ValueError, match="revisits"):
        value.select("fixture:a", request(), ["fixture:a", "fixture:b"])
    item = request().model_copy(update={"inputs": {}})
    with pytest.raises(ValueError, match="exactly"):
        value.select("fixture:a", item, [])


@pytest.mark.parametrize("path", ["../outside", "/absolute", "out//file", ".ucagent/state", "Guide_Doc/a", "out/../a"])
def test_reject_unsafe_input_paths(path):
    """Model inputs cannot copy hidden state, guides or arbitrary filesystem files."""
    with pytest.raises(ValueError):
        NextWorkflow(workflow_ref="fixture:b", reason="Continue", summary="A", transition_token="t",
                     inputs={"inputs/a.json": path})


def test_source_input_requires_real_regular_file(tmp_path):
    """Symlinks and missing inputs fail before any candidate workspace exists."""
    (tmp_path / "a").write_text("payload")
    (tmp_path / "link").symlink_to(tmp_path / "a")
    assert source_file(tmp_path, "a").read_text() == "payload"
    for name in ("link", "missing"):
        with pytest.raises(ValueError):
            source_file(tmp_path, name)


@pytest.mark.parametrize("value", ["true", 1, None])
def test_flag_is_strict(value):
    """An ambiguous runtime boolean never silently enables or disables handoff."""
    with pytest.raises(ValueError):
        load_handoff_settings(Config({"runtime_options": {"workflow_handoff_enabled": value}}))


def test_disabled_is_inert_and_single_blank_are_rejected():
    """Disabled mode ignores unused policy; enabled mode fails without a managed Super."""
    assert load_handoff_settings(Config({"runtime_options": {}, "workflow_handoff": {"bad": True}})) is None
    for cfg in ({"runtime_options": {}}, {"runtime_options": {"multi_agent_enabled": True}, "backend": {"key_name": "blank"}}):
        value = Config(cfg)
        value.set_value("runtime_options.workflow_handoff_enabled", True)
        with pytest.raises(ValueError, match="managed multi"):
            load_handoff_settings(value)


@pytest.mark.parametrize("changes", [{"max_runs": True}, {"max_start_attempts": 0},
    {"ready_timeout_seconds": float("inf")}, {"allow_revisit": "false"},
    {"allowed_next": {"fixture:a": ["missing"]}}, {"decision_limits": {"backend_turns": 0}}])
def test_policy_is_finite_and_strict(tmp_path, changes):
    """Policy budgets and references cannot be weakened through coercion or unknown fields."""
    raw = catalog(tmp_path).settings.model_dump()
    raw.update(changes)
    with pytest.raises(ValueError):
        HandoffSettings.model_validate(raw)


def test_successor_inherits_connections_but_no_workflow_config():
    """Source stages, roles and file permissions never become successor overrides."""
    cfg = Config({"backend": {"key_name": "langchain"}, "openai": {"model_name": "fixture"},
                  "stage": [{"name": "a"}], "write_dirs": ["result_a"], "output": "result_a",
                  "multi_agent": {"roles": {"source": {"system": "source"}}}})
    overrides = execution_overrides(cfg)
    assert set(overrides) == {"backend", "openai"}
    overrides["backend"]["key_name"] = "changed"
    assert cfg.backend.key_name == "langchain"
