"""Llm runtime for the Bug Review workflow."""
from __future__ import annotations

import atexit
import os
import re
import threading
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, Iterable, List, Optional

from .llm_request_observability import (
    LLMRequestObserver,
    ObservedLLMClient,
    llm_request_context,
)
from .utils import get_logger

logger = get_logger(__name__)

_LANGFUSE_WARNED: set[str] = set()
_LANGFUSE_CLIENTS: Dict[tuple, object] = {}
_LANGFUSE_CLIENT_LOCK = threading.Lock()


def _warn_once(key: str, message: str, *args) -> None:
    if key in _LANGFUSE_WARNED:
        return
    _LANGFUSE_WARNED.add(key)
    logger.warning(message, *args)


@dataclass(frozen=True)
class SemanticLLMRuntimeConfig:
    provider: str = ""
    backend: str = ""
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    request_timeout_seconds: float = 120.0
    sdk_max_retries: int = 0
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = ""
    langfuse_environment: str = ""
    langfuse_tags: str = ""
    request_observation_dir: str = ""


def load_semantic_llm_config(overrides: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, Optional[str]]:
    overrides = overrides or {}
    return {
        "provider": overrides.get("provider") or os.environ.get("BENCHMARK_SEMANTIC_LLM_PROVIDER"),
        "backend": overrides.get("backend") or os.environ.get("BENCHMARK_SEMANTIC_LLM_BACKEND"),
        "model": overrides.get("model") or os.environ.get("BENCHMARK_SEMANTIC_LLM_MODEL"),
        "base_url": overrides.get("base_url") or os.environ.get("BENCHMARK_SEMANTIC_LLM_BASE_URL"),
        "proxy_url": overrides.get("proxy_url") or os.environ.get("BENCHMARK_SEMANTIC_LLM_PROXY_URL"),
        "api_key": overrides.get("api_key") or os.environ.get("BENCHMARK_SEMANTIC_LLM_API_KEY"),
        "request_timeout_seconds": overrides.get("request_timeout_seconds") or os.environ.get(
            "BENCHMARK_SEMANTIC_LLM_REQUEST_TIMEOUT_SECONDS"
        ),
        "sdk_max_retries": (
            overrides["sdk_max_retries"]
            if overrides.get("sdk_max_retries") is not None
            else os.environ.get("BENCHMARK_SEMANTIC_LLM_SDK_MAX_RETRIES")
        ),
        "failure_mode_task_store_dir": (
            overrides.get("failure_mode_task_store_dir")
            or os.environ.get("BENCHMARK_FAILURE_MODE_TASK_STORE_DIR")
        ),
        "rtl_root_appeal_task_store_dir": (
            overrides.get("rtl_root_appeal_task_store_dir")
            or os.environ.get("BENCHMARK_RTL_ROOT_APPEAL_TASK_STORE_DIR")
        ),
        "request_observation_dir": (
            overrides.get("request_observation_dir")
            or os.environ.get("BENCHMARK_LLM_REQUEST_OBSERVATION_DIR")
        ),
        # Internal immutable ownership metadata; never sourced from the
        # environment and never contains credentials.
        "task_revision_scope": overrides.get("task_revision_scope"),
        # langfuse
        "langfuse_public_key": overrides.get("langfuse_public_key") or os.environ.get("LANGFUSE_PUBLIC_KEY"),
        "langfuse_secret_key": overrides.get("langfuse_secret_key") or os.environ.get("LANGFUSE_SECRET_KEY"),
        "langfuse_base_url": overrides.get("langfuse_base_url") or os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST"),
        "langfuse_environment": overrides.get("langfuse_environment") or os.environ.get("LANGFUSE_TRACING_ENVIRONMENT"),
        "langfuse_tags": overrides.get("langfuse_tags") or os.environ.get("LANGFUSE_TAGS"),
    }


def validate_profile_api_key(config: Optional[Dict[str, Optional[str]]]) -> None:
    """Fail before batch work when an explicitly selected profile has no key."""
    config = config or {}
    profile = str(config.get("active_profile") or "").strip()
    provider = str(config.get("provider") or "").strip().lower()
    model = str(config.get("model") or "").strip()
    if not profile or provider in {"", "local", "offline", "none"} or not model:
        return
    if str(config.get("api_key") or "").strip():
        return
    profile_token = re.sub(r"[^A-Za-z0-9]+", "_", profile).strip("_").upper()
    expected_env = f"BENCHMARK_{profile_token}_API_KEY"
    raise ValueError(
        f"semantic LLM profile {profile!r} has no API key; set {expected_env} "
        "or pass --semantic-llm-api-key. Generic BENCHMARK_SEMANTIC_LLM_API_KEY "
        "is not used for an explicitly selected profile."
    )


def _has_langfuse_config(config: Dict[str, Optional[str]]) -> bool:
    return bool(config.get("langfuse_public_key") and config.get("langfuse_secret_key"))


def _langfuse_client_key(config: Dict[str, Optional[str]]) -> tuple:
    return (
        config.get("langfuse_public_key"),
        config.get("langfuse_secret_key"),
        config.get("langfuse_base_url"),
        config.get("langfuse_environment"),
    )


def shutdown_langfuse_clients() -> None:
    """Flush and stop cached Langfuse workers once at process shutdown."""
    with _LANGFUSE_CLIENT_LOCK:
        clients = list({id(client): client for client in _LANGFUSE_CLIENTS.values()}.values())
        _LANGFUSE_CLIENTS.clear()
    for client in clients:
        try:
            # v2 recommends an explicit blocking flush for short-lived
            # processes; shutdown then joins its worker threads.
            client.flush()
            client.shutdown()
        except Exception as exc:
            _warn_once("langfuse_shutdown", "Langfuse client shutdown failed: %s", exc)


atexit.register(shutdown_langfuse_clients)


def build_langfuse_client(config: Optional[Dict[str, Optional[str]]] = None):
    config = config or load_semantic_llm_config()
    if not _has_langfuse_config(config):
        return None
    try:
        from langfuse import Langfuse  # type: ignore
    except Exception as exc:
        _warn_once("langfuse_import", "Langfuse tracing disabled: failed to import langfuse package: %s", exc)
        return None
    key = _langfuse_client_key(config)
    with _LANGFUSE_CLIENT_LOCK:
        cached = _LANGFUSE_CLIENTS.get(key)
        if cached is not None:
            return cached
        kwargs = {
            "public_key": config.get("langfuse_public_key"),
            "secret_key": config.get("langfuse_secret_key"),
        }
        if config.get("langfuse_base_url"):
            kwargs["host"] = config.get("langfuse_base_url")
        if config.get("langfuse_environment"):
            kwargs["release"] = config.get("langfuse_environment")
        try:
            import httpx  # type: ignore
            # Langfuse is commonly hosted on localhost in this workflow.  A
            # shell-wide SOCKS proxy must not prevent its client from being
            # constructed or route local traces through an external proxy.
            kwargs["httpx_client"] = httpx.Client(trust_env=False)
            client = Langfuse(**kwargs)
        except Exception as exc:
            _warn_once(
                "langfuse_client",
                "Langfuse tracing disabled: failed to create client for host=%s: %s",
                config.get("langfuse_base_url") or "<default>",
                exc,
            )
            return None
        _LANGFUSE_CLIENTS[key] = client
        return client


class _TraceGeneration:
    """Collect output so both the generation and parent trace can be updated."""

    __slots__ = ("_gen", "output")

    def __init__(self, gen: object) -> None:
        self._gen = gen
        self.output: object = None


@contextmanager
def _trace_langfuse_call(
    name: str,
    config: Optional[Dict[str, Optional[str]]] = None,
    input_payload: Optional[Dict[str, object]] = None,
    metadata: Optional[Dict[str, object]] = None,
    model: Optional[str] = None,
):
    client = build_langfuse_client(config)
    if client is None:
        yield None
        return
    trace_input = input_payload or {}
    trace_metadata = metadata or {}
    tags = [
        tag.strip()
        for tag in str((config or {}).get("langfuse_tags") or "").split(",")
        if tag.strip()
    ]
    trace = None
    generation = None
    wrapper = None
    try:
        trace_kwargs: Dict[str, object] = {
            "name": name,
            "input": trace_input,
            "metadata": trace_metadata,
        }
        if tags:
            trace_kwargs["tags"] = tags
        trace = client.trace(**trace_kwargs)
        gen_kwargs: Dict[str, object] = {
            "name": name,
            "input": trace_input,
            "metadata": trace_metadata,
        }
        if model:
            gen_kwargs["model"] = model
        generation = trace.generation(**gen_kwargs)
        wrapper = _TraceGeneration(generation)
    except Exception as exc:
        _warn_once(
            "langfuse_generation",
            "Langfuse tracing disabled for %s: failed to create trace/generation on host=%s: %s",
            name,
            (config or {}).get("langfuse_base_url") or "<default>",
            exc,
        )
    if wrapper is None:
        yield None
        return

    error_output: object = None
    try:
        yield wrapper
    except BaseException as exc:
        error_output = {
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        raise
    finally:
        output = wrapper.output if wrapper.output is not None else error_output
        if output is None:
            output = {"status": "completed_without_output"}
        try:
            generation.end(output=output)
            trace.update(output=output)
        except Exception as exc:
            _warn_once(
                "langfuse_update",
                "Langfuse trace update failed for %s on host=%s: %s",
                name,
                (config or {}).get("langfuse_base_url") or "<default>",
                exc,
            )


@contextmanager
def trace_semantic_llm_call(
    name: str,
    config: Optional[Dict[str, Optional[str]]] = None,
    input_payload: Optional[Dict[str, object]] = None,
    metadata: Optional[Dict[str, object]] = None,
    model: Optional[str] = None,
):
    """Trace one semantic operation and label its underlying SDK requests."""
    with llm_request_context(name):
        with _trace_langfuse_call(
            name,
            config=config,
            input_payload=input_payload,
            metadata=metadata,
            model=model,
        ) as traced:
            yield traced


class _LangChainChatCompletionsAdapter:
    def __init__(self, model, callbacks: Optional[List[object]] = None, metadata: Optional[Dict[str, object]] = None):
        self._model = model
        self._callbacks = callbacks or []
        self._metadata = metadata or {}

    def create(self, model: str, messages, temperature: float = 0, response_format=None):  # noqa: ARG002
        try:
            from langchain_core.messages import HumanMessage, SystemMessage  # type: ignore
        except Exception as exc:
            raise TypeError("langchain backend requires langchain_core.messages") from exc

        lc_messages = []
        for message in messages:
            role = str(message.get("role") or "").lower()
            content = message.get("content") or ""
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            else:
                lc_messages.append(HumanMessage(content=content))

        invoke_kwargs = {}
        if self._callbacks or self._metadata:
            invoke_kwargs["config"] = {}
            if self._callbacks:
                invoke_kwargs["config"]["callbacks"] = self._callbacks
            if self._metadata:
                invoke_kwargs["config"]["metadata"] = self._metadata

        result = self._model.invoke(lc_messages, **invoke_kwargs)
        content = getattr(result, "content", None)
        if content is None:
            content = str(result)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            model=model,
            raw=result,
        )


class _LangChainResponsesAdapter:
    def __init__(self, chat_completions: _LangChainChatCompletionsAdapter):
        self._chat_completions = chat_completions

    def create(self, model: str, input, temperature: float = 0, response_format=None):  # noqa: ARG002
        return self._chat_completions.create(model=model, messages=input, temperature=temperature, response_format=response_format)


class LangChainOpenAIClientAdapter:
    def __init__(self, model, callbacks: Optional[List[object]] = None, metadata: Optional[Dict[str, object]] = None):
        chat = _LangChainChatCompletionsAdapter(model, callbacks=callbacks, metadata=metadata)
        self.chat = SimpleNamespace(completions=chat)
        self.responses = _LangChainResponsesAdapter(chat)


def _build_langchain_callbacks(config: Dict[str, Optional[str]]) -> List[object]:
    if not _has_langfuse_config(config):
        return []
    try:
        from langfuse.callback.langchain import CallbackHandler  # type: ignore
    except Exception:
        return []
    return [CallbackHandler()]


def _build_langchain_chat_model(provider: str, model: str, init_kwargs: Dict[str, str]):
    try:
        from langchain.chat_models import init_chat_model  # type: ignore
    except Exception:
        init_chat_model = None
    if init_chat_model is not None:
        try:
            return init_chat_model(model, model_provider=provider or "openai", **init_kwargs)
        except Exception:
            pass

    try:
        from langchain_openai import ChatOpenAI  # type: ignore
    except Exception as exc:
        raise ImportError("langchain backend requires langchain or langchain_openai") from exc

    chat_kwargs = dict(init_kwargs)
    chat_kwargs["model"] = model
    try:
        return ChatOpenAI(**chat_kwargs)
    except TypeError:
        legacy_kwargs = dict(chat_kwargs)
        legacy_kwargs["model_name"] = legacy_kwargs.pop("model")
        return ChatOpenAI(**legacy_kwargs)


def _build_openai_client(
    api_key: Optional[str],
    base_url: Optional[str],
    proxy_url: Optional[str] = None,
    request_timeout_seconds: object = 120.0,
    sdk_max_retries: object = 0,
    request_observer: Optional[LLMRequestObserver] = None,
) -> Optional[object]:
    try:
        from openai import OpenAI  # type: ignore
    except Exception:
        return None
    try:
        timeout = max(0.001, float(request_timeout_seconds or 120.0))
    except (TypeError, ValueError):
        timeout = 120.0
    try:
        max_retries = max(0, int(sdk_max_retries if sdk_max_retries is not None else 0))
    except (TypeError, ValueError):
        max_retries = 0
    kwargs: Dict[str, object] = {
        "timeout": timeout,
        # The workflow owns retry/backoff and adaptive concurrency. Keeping the
        # SDK retry-free prevents its long internal waits from hiding failures.
        "max_retries": max_retries,
    }
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    try:
        import httpx  # type: ignore
        http_kwargs: Dict[str, object] = {
            "timeout": timeout,
            "trust_env": False,
        }
        if request_observer:
            http_kwargs["event_hooks"] = {
                "request": [request_observer.on_http_request],
                "response": [request_observer.on_http_response],
            }
        if proxy_url:
            http_kwargs["proxy"] = proxy_url
            kwargs["http_client"] = httpx.Client(**http_kwargs)
        else:
            # Isolate the semantic client from shell-wide proxy variables.
            # In particular, httpx rejects inherited ``socks://`` URLs before
            # the first request.  Explicit proxy configuration above remains
            # fully supported and strict.
            kwargs["http_client"] = httpx.Client(**http_kwargs)
    except Exception as exc:
        if proxy_url:
            _warn_once("semantic_proxy", "failed to configure semantic LLM proxy %s: %s", proxy_url, exc)
        raise
    return OpenAI(**kwargs)


def build_semantic_llm_client(config: Optional[Dict[str, Optional[str]]] = None):
    config = config or load_semantic_llm_config()
    provider = str(config.get("provider") or "").strip().lower()
    backend = str(config.get("backend") or "").strip().lower()
    # "local" is an explicit metadata-only mode for offline deterministic runs.
    if provider in {"local", "offline", "none"}:
        return None
    if not backend:
        backend = "langchain" if provider in {"langchain", "langchain-openai"} else "openai"

    api_key = (
        config.get("api_key")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("BENCHMARK_SEMANTIC_LLM_API_KEY")
    )
    base_url = (
        config.get("base_url")
        or os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("BENCHMARK_SEMANTIC_LLM_BASE_URL")
    )
    model = config.get("model")
    if not provider and not model:
        return None

    # The fixed resource ceiling applies even when request-metric persistence
    # is disabled. The observer's store is optional and fail-open.
    request_observer = LLMRequestObserver(config)
    primary_client: Optional[object] = None
    if backend in {"openai", "openai-compatible"}:
        primary_client = _build_openai_client(
            api_key,
            base_url,
            proxy_url=config.get("proxy_url"),
            request_timeout_seconds=config.get("request_timeout_seconds") or 120.0,
            sdk_max_retries=config.get("sdk_max_retries") if config.get("sdk_max_retries") is not None else 0,
            request_observer=(request_observer if request_observer.store is not None else None),
        )
    elif backend in {"langchain", "langchain-openai"}:
        if not model:
            return None
        init_kwargs = {}
        if api_key:
            init_kwargs["api_key"] = api_key
        if base_url:
            init_kwargs["base_url"] = base_url
        try:
            chat_model = _build_langchain_chat_model(provider or "openai", model, init_kwargs)
        except Exception:
            return None
        callbacks = _build_langchain_callbacks(config)
        metadata = {
            "bench_backend": backend,
            "bench_provider": provider or "openai",
            "bench_model": model,
        }
        if config.get("langfuse_tags"):
            metadata["langfuse_tags"] = [tag.strip() for tag in str(config.get("langfuse_tags") or "").split(",") if tag.strip()]
        primary_client = LangChainOpenAIClientAdapter(chat_model, callbacks=callbacks, metadata=metadata)

    if primary_client is not None:
        return ObservedLLMClient(
            primary_client,
            request_observer,
            transport_hooks=(
                request_observer.store is not None
                and backend in {"openai", "openai-compatible"}
            ),
        )
    return primary_client
