# -*- coding: utf-8 -*-
"""Model utilities for UCAgent chat models."""

from typing import Any
from .config import Config
from langchain_core.rate_limiters import InMemoryRateLimiter
from ucagent.util.log import echo_g, warning


OPENAI_API_MODES = {"auto", "responses", "chat_completions"}


def get_chat_model_openai(
    cfg: Config,
    callbacks,
    rate_limiter,
    api_mode: str | None = None,
    probe: bool = False,
    streaming: bool | None = None,
) -> Any:
    """Get OpenAI chat model instance.

    Args:
        cfg: Configuration object containing OpenAI settings.
        callbacks: LangChain callbacks for the model.
        rate_limiter: Optional LangChain rate limiter.
        api_mode: Negotiated protocol, if the backend selected one.
        probe: Whether to build a bounded startup-probe model.
        streaming: Explicit streaming mode; defaults to the historical callback behavior.

    Returns:
        ChatOpenAI instance.

    Raises:
        ImportError: If langchain_openai is not installed.
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        raise ImportError(
            "Please install langchain_openai to use OpenAI chat model. "
            "You can install it with: pip3 install langchain_openai"
        )
    kw = cfg.openai.as_dict()
    kw.pop("api_mode", None)
    probe_timeout = kw.pop("responses_probe_timeout", 10)
    model_name = kw.pop("model_name")
    if model_name:
        kw["model"] = model_name
    model_kwargs = kw.get("model_kwargs")
    if isinstance(model_kwargs, dict) and "stop" in model_kwargs:
        kw.setdefault("stop", model_kwargs.pop("stop"))
        if not model_kwargs:
            kw.pop("model_kwargs")
    if "seed" not in kw and not (
        isinstance(model_kwargs, dict) and "seed" in model_kwargs
    ):
        kw["seed"] = cfg.seed
    if api_mode == "responses":
        # These Chat Completions parameters are absent from the Responses API.
        unsupported_options = (
            "frequency_penalty",
            "logit_bias",
            "logprobs",
            "n",
            "presence_penalty",
            "seed",
            "stop",
        )
        for key in unsupported_options:
            kw.pop(key, None)
            if isinstance(model_kwargs, dict):
                model_kwargs.pop(key, None)
        kw["use_responses_api"] = True
        kw["output_version"] = "responses/v1"
    elif api_mode == "chat_completions":
        kw["use_responses_api"] = False
        kw["use_previous_response_id"] = False
        if kw.get("output_version") == "responses/v1":
            kw.pop("output_version")
        for key in (
            "context_management",
            "include",
            "previous_response_id",
            "reasoning",
            "text",
            "truncation",
        ):
            kw.pop(key, None)
            if isinstance(model_kwargs, dict):
                model_kwargs.pop(key, None)
    if callbacks:
        kw["callbacks"] = callbacks
    request_stream_usage = False
    if streaming is None:
        if callbacks:
            kw["streaming"] = True
            request_stream_usage = True
    else:
        kw["streaming"] = streaming
        request_stream_usage = streaming
    if request_stream_usage:
        # Request usage in the final streaming chunk when the provider supports
        # the OpenAI stream-options contract.
        kw.setdefault("stream_usage", True)
    if rate_limiter:
        kw.update({"rate_limiter": rate_limiter})
    if probe:
        kw.pop("request_timeout", None)
        kw.update(
            {
                "callbacks": None,
                "max_retries": 0,
                "streaming": False,
                "timeout": probe_timeout,
            }
        )
    return ChatOpenAI(**kw)


def negotiate_openai_api_mode(cfg: Config) -> str:
    """Select the OpenAI API protocol before the LangChain agent starts."""
    requested_mode = cfg.openai.get_value("api_mode", "auto")
    if requested_mode not in OPENAI_API_MODES:
        raise ValueError(
            "openai.api_mode must be one of: auto, responses, chat_completions"
        )
    probe_timeout = cfg.openai.get_value("responses_probe_timeout", 10)
    if (
        isinstance(probe_timeout, bool)
        or not isinstance(probe_timeout, (int, float))
        or probe_timeout <= 0
    ):
        raise ValueError("openai.responses_probe_timeout must be a positive number")
    if requested_mode == "chat_completions":
        echo_g("Using OpenAI Chat Completions API (configured).")
        return requested_mode

    probe_model = get_chat_model_openai(
        cfg,
        callbacks=None,
        rate_limiter=None,
        api_mode="responses",
        probe=True,
    )
    try:
        probe_model.invoke("Reply with OK.", max_tokens=8)
    except Exception as probe_error:
        response = getattr(probe_error, "response", None)
        status_code = getattr(probe_error, "status_code", None)
        if status_code is None:
            status_code = getattr(response, "status_code", None)
        body = getattr(probe_error, "body", None)
        error_text = f"{probe_error} {body or ''}".lower()
        model_lookup_failure = any(
            marker in error_text
            for marker in (
                "model_not_found",
                "model not found",
                "model does not exist",
                "model you requested does not exist",
                "you do not have access to the model",
            )
        ) or (
            "model" in error_text
            and any(
                marker in error_text
                for marker in ("does not exist", "do not have access")
            )
        )
        unknown_response_field = (
            any(marker in error_text for marker in ("unknown field", "unknown parameter"))
            and any(
                marker in error_text
                for marker in ("'input'", '"input"', "max_output_tokens")
            )
        )
        # Downgrade only when the response proves a protocol capability gap.
        explicit_protocol_failure = (
            (status_code == 404 and not model_lookup_failure)
            or status_code in {405, 410, 501}
            or isinstance(status_code, int) and 200 <= status_code < 300
            or unknown_response_field
            or any(
                marker in error_text
                for marker in (
                    "responses api is not supported",
                    "responses api not supported",
                    "unsupported responses api",
                    "does not support the responses api",
                    "does not support responses api",
                    "not supported for the responses api",
                    "responses api is not available",
                    "unsupported endpoint",
                    "endpoint is not supported",
                    "method not allowed",
                    "route not found",
                    "unknown endpoint",
                    "unknown url",
                    "not implemented",
                )
            )
        )
        if requested_mode == "auto" and explicit_protocol_failure:
            warning(
                "OpenAI Responses API is unavailable"
                f" (status={status_code or 'unknown'}); probing Chat Completions "
                "before falling back."
            )
            chat_probe_model = get_chat_model_openai(
                cfg,
                callbacks=None,
                rate_limiter=None,
                api_mode="chat_completions",
                probe=True,
            )
            try:
                chat_probe_model.invoke("Reply with OK.", max_tokens=8)
            except Exception as chat_probe_error:
                chat_reason = str(chat_probe_error).strip().splitlines()[0]
                if len(chat_reason) > 500:
                    chat_reason = chat_reason[:497] + "..."
                raise RuntimeError(
                    "OpenAI Responses API is unsupported and the Chat Completions "
                    "startup fallback probe also failed. Cause: "
                    f"{chat_reason or type(chat_probe_error).__name__}"
                ) from chat_probe_error
            echo_g("Using OpenAI Chat Completions API (fallback probe succeeded).")
            return "chat_completions"
        reason = str(probe_error).strip().splitlines()[0]
        if len(reason) > 500:
            reason = reason[:497] + "..."
        if requested_mode == "responses":
            raise RuntimeError(
                "OpenAI Responses API was required by openai.api_mode but its "
                f"startup probe failed: {reason or type(probe_error).__name__}"
            ) from probe_error
        raise RuntimeError(
            "OpenAI Responses API startup probe failed without proving that the "
            "protocol is unsupported; Chat Completions fallback was not attempted. "
            f"Cause: {reason or type(probe_error).__name__}"
        ) from probe_error

    echo_g("Using OpenAI Responses API (startup probe succeeded).")
    return "responses"


def get_chat_model_anthropic(cfg: Config, callbacks, rate_limiter) -> Any:
    """Get Anthropic chat model instance.

    Args:
        cfg: Configuration object containing Anthropic settings.

    Returns:
        ChatAnthropic instance.

    Raises:
        ImportError: If langchain_anthropic is not installed.
    """
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        raise ImportError(
            "Please install langchain_anthropic to use Anthropic chat model. "
            "You can install it with: pip3 install langchain_anthropic"
        )
    kw = cfg.anthropic.as_dict()
    if rate_limiter:
        kw.update({"rate_limiter": rate_limiter})
    if callbacks:
        kw.update(
            {
                "callbacks": callbacks,
            }
        )
    llm = ChatAnthropic(**kw)
    return llm


def get_chat_model_google_genai(cfg: Config, callbacks, rate_limiter) -> Any:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError:
        raise ImportError(
            "Please install langchain_google_genai to use Google GenAI chat model. "
            "You can install it with: pip3 install langchain_google_genai"
        )
    kw = cfg.google_genai.as_dict()
    model_name = kw.pop("model_name")
    if model_name:
        kw["model"] = model_name
    if callbacks:
        kw.update(
            {
                "callbacks": callbacks,
            }
        )
    if rate_limiter:
        kw.update({"rate_limiter": rate_limiter})
    return ChatGoogleGenerativeAI(**kw)


def get_chat_model(
    cfg: Config,
    callbacks: Any = None,
    openai_api_mode: str | None = None,
    streaming: bool | None = None,
) -> Any:
    if not cfg.rate_limiter.enabled:
        rate_limiter = None
    else:
        rate_limiter = InMemoryRateLimiter(
            requests_per_second=cfg.rate_limiter.requests_per_second,
            check_every_n_seconds=cfg.rate_limiter.check_every_n_seconds,
            max_bucket_size=cfg.rate_limiter.max_bucket_size,
        )
        echo_g(
            "Rate limiter enabled with %d requests per minute (RPM)."
            % (cfg.rate_limiter.requests_per_second * 60)
        )
    model_type = cfg.get_value("model_type", "openai")
    func = "get_chat_model_%s" % model_type
    echo_g(f"Using model type: {model_type} in get_chat_model.")
    if func in globals():
        if model_type == "openai":
            return get_chat_model_openai(
                cfg,
                callbacks,
                rate_limiter,
                api_mode=openai_api_mode,
                streaming=streaming,
            )
        return globals()[func](cfg, callbacks, rate_limiter)
    else:
        raise ValueError(
            f"Unsupported model type: {model_type}. Supported types are: "
            f"{', '.join([ f.removeprefix('get_chat_model_') for f in globals().keys() if f.startswith('get_chat_model_') ])}."
        )
