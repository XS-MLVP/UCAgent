# -*- coding: utf-8 -*-
"""Model utilities for UCAgent chat models."""

from typing import Any
from .config import Config
from langchain_core.rate_limiters import InMemoryRateLimiter
from ucagent.util.log import echo_g


def get_chat_model_openai(cfg: Config, callbacks, rate_limiter) -> Any:
    """Get OpenAI chat model instance.

    Args:
        cfg: Configuration object containing OpenAI settings.

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
    kw = dict(
        openai_api_key=cfg.openai.openai_api_key,
        openai_api_base=cfg.openai.openai_api_base,
        model=cfg.openai.model_name,
        seed=cfg.seed,
    )
    if callbacks:
        kw.update({"callbacks": callbacks, "streaming": True})
    if rate_limiter:
        kw.update({"rate_limiter": rate_limiter})
    return ChatOpenAI(**kw)


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
    if callbacks:
        kw.update(
            {
                "callbacks": callbacks,
            }
        )
    if rate_limiter:
        kw.update({"rate_limiter": rate_limiter})
    return ChatGoogleGenerativeAI(**kw)


def get_chat_model(cfg: Config, callbacks: Any = None) -> Any:
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
        return globals()[func](cfg, callbacks, rate_limiter)
    else:
        raise ValueError(
            f"Unsupported model type: {model_type}. Supported types are: "
            f"{', '.join([ f.removeprefix('get_chat_model_') for f in globals().keys() if f.startswith('get_chat_model_') ])}."
        )
