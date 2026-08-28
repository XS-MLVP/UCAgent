"""OpenAI Responses and Chat Completions negotiation regression tests."""

from pathlib import Path

import pytest
from langchain_openai import ChatOpenAI

from ucagent.abackend.langchain.agent import UCAgentLangChainBackend
from ucagent.util.config import Config, load_yaml_with_env_vars
from ucagent.util.models import get_chat_model_openai, negotiate_openai_api_mode


class _ProbeError(Exception):
    def __init__(self, message, status_code=None, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _config(api_mode="auto", probe_timeout=10):
    return Config(
        {
            "seed": 42,
            "openai": {
                "model_name": "test-model",
                "openai_api_key": "test-key",
                "openai_api_base": "https://example.test/v1",
                "api_mode": api_mode,
                "responses_probe_timeout": probe_timeout,
                "reasoning_effort": "xhigh",
                "top_p": 0.9,
                "model_kwargs": {"stop": ["END"]},
            },
        }
    )


def test_auto_mode_prefers_responses_and_uses_a_bounded_probe(monkeypatch):
    calls = []
    cfg = _config(probe_timeout=3.5)
    cfg.openai.request_timeout = 99

    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            calls.append({"constructor": kwargs})

        def invoke(self, prompt, **kwargs):
            calls.append({"invoke": (prompt, kwargs)})
            return object()

    monkeypatch.setattr("langchain_openai.ChatOpenAI", _FakeChatOpenAI)

    assert negotiate_openai_api_mode(cfg) == "responses"
    constructor = calls[0]["constructor"]
    assert constructor["use_responses_api"] is True
    assert constructor["output_version"] == "responses/v1"
    assert constructor["max_retries"] == 0
    assert constructor["timeout"] == 3.5
    assert "request_timeout" not in constructor
    assert constructor["streaming"] is False
    assert "seed" not in constructor
    assert "stop" not in constructor
    assert constructor["reasoning"] == {"effort": "xhigh"}
    assert "reasoning_effort" not in constructor
    assert calls[1] == {"invoke": ("Reply with OK.", {"max_tokens": 8})}


@pytest.mark.parametrize(
    ("status_code", "message"),
    [
        (404, "Not found"),
        (405, "Method not allowed"),
        (400, "Responses API is not supported by this endpoint"),
        (400, "This model is not supported for the Responses API"),
        (400, "Unknown parameter: 'input'"),
        (200, "Response body does not match the Responses schema"),
    ],
)
def test_auto_mode_falls_back_only_for_explicit_protocol_failures(
    monkeypatch, status_code, message
):
    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            self.responses = kwargs["use_responses_api"]

        def invoke(self, prompt, **kwargs):
            if self.responses:
                raise _ProbeError(message, status_code=status_code)
            return object()

    monkeypatch.setattr("langchain_openai.ChatOpenAI", _FakeChatOpenAI)

    assert negotiate_openai_api_mode(_config()) == "chat_completions"


def test_model_not_found_does_not_trigger_chat_fallback(monkeypatch):
    constructions = []

    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            constructions.append(kwargs)

        def invoke(self, prompt, **kwargs):
            raise _ProbeError(
                "The model 'missing-model' does not exist or you do not have access",
                status_code=404,
                body={"error": {"code": "model_not_found"}},
            )

    monkeypatch.setattr("langchain_openai.ChatOpenAI", _FakeChatOpenAI)

    with pytest.raises(RuntimeError, match="fallback was not attempted"):
        negotiate_openai_api_mode(_config())
    assert len(constructions) == 1


def test_failed_chat_fallback_probe_is_reported(monkeypatch):
    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            self.responses = kwargs["use_responses_api"]

        def invoke(self, prompt, **kwargs):
            if self.responses:
                raise _ProbeError("Route not found", status_code=404)
            raise _ProbeError("Chat endpoint failed", status_code=503)

    monkeypatch.setattr("langchain_openai.ChatOpenAI", _FakeChatOpenAI)

    with pytest.raises(RuntimeError, match="fallback probe also failed"):
        negotiate_openai_api_mode(_config())


@pytest.mark.parametrize(
    ("status_code", "message"),
    [
        (401, "Invalid API key"),
        (429, "Rate limit exceeded"),
        (None, "Connection timed out"),
        (500, "Internal server error"),
    ],
)
def test_auto_mode_does_not_mask_operational_failures(
    monkeypatch, status_code, message
):
    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            pass

        def invoke(self, prompt, **kwargs):
            raise _ProbeError(message, status_code=status_code)

    monkeypatch.setattr("langchain_openai.ChatOpenAI", _FakeChatOpenAI)

    with pytest.raises(RuntimeError, match="fallback was not attempted"):
        negotiate_openai_api_mode(_config())


def test_forced_responses_mode_does_not_fallback(monkeypatch):
    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            pass

        def invoke(self, prompt, **kwargs):
            raise _ProbeError("Not found", status_code=404)

    monkeypatch.setattr("langchain_openai.ChatOpenAI", _FakeChatOpenAI)

    with pytest.raises(RuntimeError, match="required by openai.api_mode"):
        negotiate_openai_api_mode(_config(api_mode="responses"))


def test_configured_chat_completions_skips_the_probe(monkeypatch):
    def fail_if_constructed(**kwargs):
        raise AssertionError("ChatOpenAI must not be constructed for negotiation")

    monkeypatch.setattr("langchain_openai.ChatOpenAI", fail_if_constructed)

    assert (
        negotiate_openai_api_mode(_config(api_mode="chat_completions"))
        == "chat_completions"
    )


@pytest.mark.parametrize("api_mode", ["invalid", "", None, True])
def test_invalid_api_mode_fails_before_model_construction(api_mode):
    with pytest.raises(ValueError, match="openai.api_mode"):
        negotiate_openai_api_mode(_config(api_mode=api_mode))


@pytest.mark.parametrize("probe_timeout", [0, -1, "ten", True, None])
def test_invalid_probe_timeout_fails_before_model_construction(probe_timeout):
    with pytest.raises(ValueError, match="responses_probe_timeout"):
        negotiate_openai_api_mode(_config(probe_timeout=probe_timeout))


def test_responses_and_chat_models_receive_protocol_specific_options(monkeypatch):
    captured = []

    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr("langchain_openai.ChatOpenAI", _FakeChatOpenAI)
    cfg = _config()

    get_chat_model_openai(
        cfg,
        callbacks=[object()],
        rate_limiter=None,
        api_mode="responses",
    )
    get_chat_model_openai(
        cfg,
        callbacks=None,
        rate_limiter=None,
        api_mode="chat_completions",
    )

    responses, chat = captured
    assert responses["use_responses_api"] is True
    assert responses["output_version"] == "responses/v1"
    assert responses["streaming"] is True
    assert responses["stream_usage"] is True
    assert responses["reasoning"] == {"effort": "xhigh"}
    assert "reasoning_effort" not in responses
    assert "seed" not in responses
    assert "stop" not in responses
    assert chat["use_responses_api"] is False
    assert chat["use_previous_response_id"] is False
    assert chat["reasoning_effort"] == "xhigh"
    assert "reasoning" not in chat
    assert chat["seed"] == 42
    assert chat["stop"] == ["END"]
    assert "output_version" not in chat


def test_real_chat_openai_payloads_use_the_selected_protocol():
    cfg = _config()
    original_config = cfg.as_dict()
    responses_model = get_chat_model_openai(
        cfg, callbacks=None, rate_limiter=None, api_mode="responses"
    )
    chat_model = get_chat_model_openai(
        cfg, callbacks=None, rate_limiter=None, api_mode="chat_completions"
    )

    responses_payload = responses_model._get_request_payload("hello")
    chat_payload = chat_model._get_request_payload("hello")

    assert isinstance(responses_model, ChatOpenAI)
    assert responses_model._use_responses_api(responses_payload) is True
    assert "input" in responses_payload
    assert "messages" not in responses_payload
    assert "seed" not in responses_payload
    assert "stop" not in responses_payload
    assert responses_payload["reasoning"] == {"effort": "xhigh"}
    assert "reasoning_effort" not in responses_payload
    assert chat_model._use_responses_api(chat_payload) is False
    assert "messages" in chat_payload
    assert "input" not in chat_payload
    assert chat_payload["seed"] == 42
    assert chat_payload["stop"] == ["END"]
    assert chat_payload["reasoning_effort"] == "xhigh"
    assert "reasoning" not in chat_payload
    assert cfg.as_dict() == original_config


def test_responses_reasoning_effort_preserves_other_reasoning_options(monkeypatch):
    captured = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("langchain_openai.ChatOpenAI", _FakeChatOpenAI)
    cfg = _config()
    cfg.openai.reasoning = {"summary": "auto", "effort": "low"}

    get_chat_model_openai(
        cfg,
        callbacks=None,
        rate_limiter=None,
        api_mode="responses",
    )

    assert captured["reasoning"] == {"summary": "auto", "effort": "xhigh"}
    assert "reasoning_effort" not in captured


def test_responses_content_blocks_render_without_protocol_dicts():
    backend = UCAgentLangChainBackend.__new__(UCAgentLangChainBackend)
    content = [
        {
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": "Reasoning summary. "}],
        },
        {"type": "text", "text": "Final answer."},
        {
            "type": "function_call",
            "name": "Check",
            "arguments": "{}",
            "call_id": "call-1",
        },
    ]

    assert (
        backend._process_msg_content(content)
        == "Reasoning summary. Final answer."
    )


def test_default_openai_mode_environment_values_parse(monkeypatch):
    setting_path = Path(__file__).parents[1] / "ucagent" / "setting.yaml"
    monkeypatch.delenv("OPENAI_API_MODE", raising=False)
    monkeypatch.delenv("OPENAI_RESPONSES_PROBE_TIMEOUT", raising=False)
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)

    defaults = load_yaml_with_env_vars(setting_path)["openai"]
    assert defaults["api_mode"] == "auto"
    assert defaults["responses_probe_timeout"] == 10
    assert defaults["reasoning_effort"] == "xhigh"

    monkeypatch.setenv("OPENAI_API_MODE", "chat_completions")
    monkeypatch.setenv("OPENAI_RESPONSES_PROBE_TIMEOUT", "2.5")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "vendor-deep-think")
    overridden = load_yaml_with_env_vars(setting_path)["openai"]
    assert overridden["api_mode"] == "chat_completions"
    assert overridden["responses_probe_timeout"] == 2.5
    assert overridden["reasoning_effort"] == "vendor-deep-think"
