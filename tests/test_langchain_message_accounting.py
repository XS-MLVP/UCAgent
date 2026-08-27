from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)

from ucagent.abackend.langchain.middleware.messages import (
    MessageStatistic,
    StreamedOutputCallbackHandler,
    TrimAndSummaryMiddleware,
    _raw_estimated_tokens,
    retain_skill_read_messages_as_human,
    summarize_messages,
)
from ucagent.abackend.langchain.agent import UCAgentLangChainBackend
from ucagent.verify_agent import VerifyAgent
from ucagent.util.config import load_yaml_with_env_vars
from ucagent.util.models import get_chat_model_openai


class _FakeSummaryModel:
    def __init__(self, content="SUMMARY", usage_metadata=None):
        self.content = content
        self.usage_metadata = usage_metadata
        self.calls = []

    def invoke(self, messages, **kwargs):
        self.calls.append((list(messages), dict(kwargs)))
        return AIMessage(
            content=self.content,
            usage_metadata=self.usage_metadata,
        )


def _middleware(
    model,
    *,
    max_summary_tokens=32,
    max_keep_msgs=10,
    max_tokens=1_000_000,
    tail_keep_msgs=2,
    tools=None,
):
    return TrimAndSummaryMiddleware(
        msg_stat=MessageStatistic(),
        max_summary_tokens=max_summary_tokens,
        max_keep_msgs=max_keep_msgs,
        max_tokens=max_tokens,
        tail_keep_msgs=tail_keep_msgs,
        model=model,
        tools=tools,
    )


def _apply_message_replacement(update):
    return [
        message
        for message in update["messages"]
        if not isinstance(message, RemoveMessage)
    ]


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_summary_tokens": 0},
        {"max_tokens": -1},
        {"max_keep_msgs": -1},
        {"tail_keep_msgs": -1},
        {"max_keep_msgs": 1, "tail_keep_msgs": 2},
    ],
)
def test_message_limits_reject_invalid_values(overrides):
    with pytest.raises(ValueError):
        _middleware(_FakeSummaryModel(), **overrides)


def test_message_statistics_separate_characters_from_provider_tokens():
    statistic = MessageStatistic()
    messages = [
        SystemMessage(content="sys", id="system"),
        HumanMessage(content="human", id="human"),
        AIMessage(
            content="answer",
            id="answer",
            usage_metadata={
                "input_tokens": 120,
                "output_tokens": 12,
                "total_tokens": 132,
                "input_token_details": {"cache_read": 20},
            },
        ),
    ]

    statistic.update_message(messages)
    statistic.update_message(messages)
    stats = statistic.get_statistics()

    assert stats["total_count_messages"] == 3
    assert stats["total_text_size_messages"] == len("syshumananswer")
    assert stats["message_in"] == len("syshuman")
    assert stats["message_out"] == len("answer")
    assert stats["provider_usage"]["main"] == {
        "responses": 1,
        "responses_with_usage": 1,
        "responses_without_usage": 0,
        "input_tokens": 120,
        "output_tokens": 12,
        "total_tokens": 132,
        "cache_read_tokens": 20,
    }


def test_stream_callback_counts_characters_and_handles_missing_chunk():
    callback = StreamedOutputCallbackHandler()

    callback.on_llm_new_token("加法器")
    callback.on_llm_new_token("abc")

    assert callback.total() == 6


def test_provider_usage_can_arrive_after_an_initial_response_without_usage():
    statistic = MessageStatistic()
    initial = AIMessage(content="answer", id="same-response")
    final = initial.model_copy(
        update={
            "usage_metadata": {
                "input_tokens": 10,
                "output_tokens": 2,
                "total_tokens": 12,
            }
        }
    )

    statistic.update_message(initial)
    statistic.update_message(final)
    usage = statistic.get_statistics()["provider_usage"]["main"]

    assert usage["responses"] == 1
    assert usage["responses_with_usage"] == 1
    assert usage["responses_without_usage"] == 0
    assert usage["total_tokens"] == 12


def test_message_limit_triggers_compression_and_previous_summary_is_not_duplicated():
    model = _FakeSummaryModel()
    middleware = _middleware(model)
    first_state = {
        "messages": [SystemMessage(content="system")]
        + [HumanMessage(content=f"old-{index}") for index in range(11)]
    }

    first_update = middleware.before_model(first_state)
    compressed_state = _apply_message_replacement(first_update)
    compressed_state.extend(
        HumanMessage(content=f"new-{index}") for index in range(8)
    )
    second_update = middleware.before_model({"messages": compressed_state})

    assert second_update
    assert len(model.calls) == 2
    assert model.calls[0][1] == {"max_tokens": 32}
    second_summary_input = model.calls[1][0][:-1]
    assert sum(message.content == "SUMMARY" for message in second_summary_input) == 1
    assert middleware.last_compression["reason"] == "message_limit"
    assert middleware.last_compression["summarized_messages"] > 0


def test_retained_skill_messages_are_deduplicated():
    prefix = "Use this skill to complete tasks:\n"
    messages = [
        HumanMessage(content=prefix + "skill body"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "ReadTextFile",
                    "args": {"path": ".ucagent/skills/example/SKILL.md"},
                    "id": "skill-read",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content="skill body",
            tool_call_id="skill-read",
            name="ReadTextFile",
        ),
    ]

    retained = retain_skill_read_messages_as_human(
        messages, use_skill=True, skill_list=["example"]
    )
    retained_again = retain_skill_read_messages_as_human(
        retained, use_skill=True, skill_list=["example"]
    )

    assert [message.content for message in retained] == [prefix + "skill body"]
    assert [message.content for message in retained_again] == [
        prefix + "skill body"
    ]


def test_token_limit_can_trigger_when_message_limit_is_disabled():
    model = _FakeSummaryModel()
    middleware = _middleware(
        model,
        max_keep_msgs=0,
        max_tokens=20,
        tail_keep_msgs=1,
    )
    state = {
        "messages": [
            SystemMessage(content="system"),
            HumanMessage(content="x" * 500),
            HumanMessage(content="tail"),
        ]
    }

    update = middleware.before_model(state)

    assert update
    assert middleware.last_compression["reason"] == "token_limit"


def test_missing_system_message_is_restored_without_dropping_first_human():
    middleware = _middleware(_FakeSummaryModel())
    middleware.set_system_message(SystemMessage(content="system"))
    first_human = HumanMessage(content="first human")

    update = middleware.before_model({"messages": [first_human]})
    updated_state = _apply_message_replacement(update)

    assert [type(message) for message in updated_state] == [
        SystemMessage,
        HumanMessage,
    ]
    assert updated_state[1].content == "first human"


def test_forced_summary_replaces_history_with_the_generated_summary():
    model = _FakeSummaryModel(content="forced summary")
    middleware = _middleware(model)
    messages = [
        SystemMessage(content="system"),
        HumanMessage(content="old history"),
    ]

    middleware.force_summary(messages)
    update = middleware.before_model({"messages": messages})
    updated_state = _apply_message_replacement(update)

    assert [message.content for message in updated_state] == [
        "system",
        "forced summary",
    ]
    assert isinstance(updated_state[-1], HumanMessage)
    assert middleware.last_compression["reason"] == "manual"


def test_context_estimate_is_calibrated_by_provider_input_usage():
    model = _FakeSummaryModel()
    middleware = _middleware(model)
    messages = [
        SystemMessage(content="system"),
        HumanMessage(content="中文内容" * 20),
        AIMessage(
            content="ok",
            usage_metadata={
                "input_tokens": 400,
                "output_tokens": 1,
                "total_tokens": 401,
            },
        ),
        HumanMessage(content="next"),
    ]

    estimated = middleware.estimate_context_tokens(messages)

    assert middleware.token_estimate_scale > 1
    assert estimated > _raw_estimated_tokens(messages)


def test_context_estimate_includes_bound_tool_schemas():
    model = _FakeSummaryModel()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "LongTool",
                "description": "d" * 400,
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    middleware = _middleware(model, tools=tools)
    messages = [SystemMessage(content="system"), HumanMessage(content="run")]

    assert middleware.estimate_context_tokens(messages) > _raw_estimated_tokens(
        messages
    )


def test_backend_binds_tools_after_verify_agent_finishes_tool_setup(monkeypatch):
    model = _FakeSummaryModel()
    created = {}
    vagent = SimpleNamespace(
        stream_output=False,
        context_management_strategy="TrimAndSummaryMiddleware",
        max_summary_tokens=32,
        max_keep_msgs=10,
        max_token=1_000_000,
        tail_keep_msgs=2,
    )

    monkeypatch.setattr(
        "ucagent.abackend.langchain.agent.get_chat_model",
        lambda config, callbacks: model,
    )

    def fake_create_agent(**kwargs):
        created.update(kwargs)
        return object()

    monkeypatch.setattr(
        "ucagent.abackend.langchain.agent.create_agent", fake_create_agent
    )

    backend = UCAgentLangChainBackend(vagent, SimpleNamespace())
    assert backend.message_manage_node.tools == []

    vagent.test_tools = [{"type": "function", "function": {"name": "Read"}}]
    backend.init()

    assert backend.message_manage_node.tools == vagent.test_tools
    assert created["tools"] == vagent.test_tools


def test_compression_does_not_recalibrate_from_usage_for_the_old_context():
    model = _FakeSummaryModel()
    middleware = _middleware(model)
    state = {
        "messages": [SystemMessage(content="system")]
        + [HumanMessage(content=f"old-{index}") for index in range(10)]
        + [
            AIMessage(
                content="last answer",
                usage_metadata={
                    "input_tokens": 200,
                    "output_tokens": 2,
                    "total_tokens": 202,
                },
            )
        ]
    }

    update = middleware.before_model(state)
    scale_after_compression = middleware.token_estimate_scale
    compressed_state = _apply_message_replacement(update)
    middleware.estimate_context_tokens(compressed_state)

    assert middleware.token_estimate_scale == scale_after_compression


def test_summary_output_budget_is_sent_and_enforced_if_model_ignores_it():
    model = _FakeSummaryModel(content="x" * 1000)

    summary = summarize_messages(
        [HumanMessage(content="source")],
        summarization_size=20,
        model=model,
    )

    assert model.calls[0][1] == {"max_tokens": 20}
    assert _raw_estimated_tokens(summary.content) <= 20
    assert len(summary.content) < 1000


def test_runtime_message_config_accepts_legacy_alias_and_updates_live_values():
    agent = VerifyAgent.__new__(VerifyAgent)
    agent.message_manage_node = _middleware(
        _FakeSummaryModel(),
        max_tokens=100,
        max_summary_tokens=10,
        max_keep_msgs=20,
        tail_keep_msgs=5,
    )
    agent.max_token = 100
    agent.max_summary_tokens = 10
    agent.context_management_strategy = "TrimAndSummaryMiddleware"

    updated = agent.set_messages_cfg(
        {"max_token": "200", "max_keep_msgs": "40", "tail_keep_msgs": -1}
    )

    assert updated == {"max_token": 200, "max_keep_msgs": 40}
    assert agent.message_manage_node.max_tokens == 200
    assert agent.message_manage_node.max_keep_msgs == 40
    assert agent.max_token == 200
    assert agent.summary_mode() == "TrimAndSummaryMiddleware"
    assert agent.set_messages_cfg({"max_keep_msgs": 4}) == {}


def test_status_keeps_token_and_compression_metrics_compact():
    agent = VerifyAgent.__new__(VerifyAgent)
    middleware = _middleware(
        _FakeSummaryModel(), max_tokens=1000, max_keep_msgs=10
    )
    middleware.last_compression = {
        "reason": "token_limit",
        "before_tokens_estimated": 1200,
        "before_messages": 12,
        "after_tokens_estimated": 300,
        "after_messages": 3,
    }
    messages = [SystemMessage(content="system"), HumanMessage(content="run")]
    provider_usage = {
        "responses": 1,
        "responses_with_usage": 1,
        "responses_without_usage": 0,
        "input_tokens": 120,
        "output_tokens": 12,
        "total_tokens": 132,
        "cache_read_tokens": 0,
    }
    agent.__version__ = "test"
    agent.backend = SimpleNamespace(
        model_name=lambda: "test-model",
        temperature=lambda: 0,
        get_statistics=lambda: {"provider_usage": {"all": provider_usage}},
        _stat_msg_count_ai=1,
        _stat_msg_count_tool=0,
        _stat_msg_count_system=1,
    )
    agent.message_manage_node = middleware
    agent.message_info = lambda: {"count": 2, "size": 9}
    agent.messages_get_raw = lambda: messages
    agent.is_break = lambda: False
    agent.stream_output = True
    agent.seed = 1
    agent.interaction_mode = "standard"
    agent._time_start = 0
    agent.stage_manager = SimpleNamespace(get_time_cost=lambda: 1)

    status = agent.status_info()

    assert len(status) == 18
    assert status["SummaryMode"] == "TrimAndSummaryMiddleware"
    assert status["ProviderTokens"] == "complete 120/12/132"
    assert status["Context"].endswith("/1000,msg=1/10")
    assert status["Compression"] == "token_limit tok=1200>300,msg=12>3"
    assert not {
        "ProviderInputTokens",
        "MainProviderInputTokens",
        "StreamedOutputChars",
        "TokenEstimateScale",
        "LastCompression",
    }.intersection(status)


def test_live_middleware_max_token_setter_updates_the_active_limit():
    middleware = _middleware(_FakeSummaryModel())

    middleware.set_max_token(321)

    assert middleware.max_tokens == 321
    assert middleware.get_max_token() == 321


def test_conversation_summary_defaults_and_disabled_limits_parse(monkeypatch):
    setting_path = Path(__file__).parents[1] / "ucagent" / "setting.yaml"
    env_names = (
        "SUMMARY_MAX_CTX_TOKEN",
        "SUMMARY_MAX_SUM_TOKEN",
        "SUMMARY_MAX_KEEP_MSG",
        "SUMMARY_TAIL_KEEP_MSG",
    )
    for name in env_names:
        monkeypatch.delenv(name, raising=False)

    defaults = load_yaml_with_env_vars(setting_path)["conversation_summary"]

    assert defaults["max_tokens"] == 204800
    assert defaults["max_summary_tokens"] == 8192
    assert defaults["max_keep_msgs"] == 100
    assert defaults["tail_keep_msgs"] == 1

    monkeypatch.setenv("SUMMARY_MAX_CTX_TOKEN", "0")
    monkeypatch.setenv("SUMMARY_MAX_KEEP_MSG", "0")
    disabled = load_yaml_with_env_vars(setting_path)["conversation_summary"]

    assert disabled["max_tokens"] == 0
    assert disabled["max_keep_msgs"] == 0


def test_openai_streaming_requests_provider_usage(monkeypatch):
    captured = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("langchain_openai.ChatOpenAI", _FakeChatOpenAI)
    cfg = SimpleNamespace(
        openai=SimpleNamespace(
            as_dict=lambda: {
                "model_name": "test-model",
                "openai_api_key": "test-key",
                "model_kwargs": {
                    "stop": ["END"],
                    "extra_body_option": "value",
                },
            }
        ),
        seed=1,
    )

    get_chat_model_openai(cfg, callbacks=[object()], rate_limiter=None)

    assert captured["streaming"] is True
    assert captured["stream_usage"] is True
    assert captured["stop"] == ["END"]
    assert captured["model_kwargs"] == {"extra_body_option": "value"}
