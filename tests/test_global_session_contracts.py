"""Direct Super requests and operator policy boundaries."""
import pytest
from pydantic import ValidationError
from ucagent.core.multi_agent.global_agent.session_contracts import (
    SuperRequest, SuperProfile, GlobalSettings, load_global_settings,
)
from ucagent.util.config import Config

def policy(**values):
    return GlobalSettings(allowed_workflows=["try:prepare"],
                          launch_profiles={"standard": SuperProfile()}, **values)

def test_direct_request_needs_no_plan():
    request = SuperRequest(workflow_ref="try:prepare", instruction="Generate the inputs")
    assert request.inputs == {} and request.launch_profile == "standard"

@pytest.mark.parametrize("extra", [{"depends_on": []}, {"argv": ["sh"]}, {"template": "dag"}])
def test_reject_executable_or_graph_fields(extra):
    with pytest.raises(ValidationError):
        SuperRequest(workflow_ref="try:prepare", instruction="Do it", **extra)

@pytest.mark.parametrize("target", ["../out", "/tmp/out", "output/a", "inputs/../a"])
def test_input_targets_are_scoped(target):
    with pytest.raises((ValidationError, ValueError)):
        SuperRequest(workflow_ref="try:prepare", instruction="Do it",
                     inputs={target: {"agent_id": "a", "attempt": 1, "path": "output/a"}})

def test_reject_legacy_policy():
    with pytest.raises(ValidationError):
        policy(dag_templates={})

@pytest.mark.parametrize("value", [True, 0, -1])
def test_resource_capacity_is_strict(value):
    with pytest.raises(ValidationError):
        policy(resources={"sim": value})

def test_profile_secrets_are_not_in_catalog():
    profile = SuperProfile(overrides={"openai.api_key": "test-secret"})
    assert "test-secret" not in str(profile.describe())

@pytest.mark.parametrize("key", ["agent_run.id", "workflow", "runtime_options.agent_mode"])
def test_protected_profile_values(key):
    with pytest.raises(ValidationError):
        SuperProfile(overrides={key: "value"})

def test_enabled_and_disabled_settings():
    assert load_global_settings(Config({"runtime_options": {"agent_mode": "single"}})) is None
    cfg = Config({"runtime_options": {"agent_mode": "multi"}, "global_agent": policy().model_dump()})
    assert load_global_settings(cfg).max_parallel_supers == 2
    with pytest.raises(ValueError):
        load_global_settings(Config({"runtime_options": {"agent_mode": "invalid"}}))
