from __future__ import annotations

import os
import time
from typing import Any, Callable, Protocol

from .config import Settings

_RATE_LIMIT_MARKERS = ("429", "resource_exhausted", "rate limit", "ratelimit", "too many requests")

class ChatModel(Protocol):
    def invoke(self, messages: list, **kwargs: Any) -> Any: ...

def is_rate_limit_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _RATE_LIMIT_MARKERS)

class RetryingLLM:
    """Repete chamadas recusadas por limite de taxa, com espera exponencial."""

    def __init__(self, llm: ChatModel, attempts: int = 5, base_delay: float = 2.0,
                 max_delay: float = 30.0, sleep: Callable[[float], None] = time.sleep):
        self.llm = llm
        self.attempts = attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.sleep = sleep

    def invoke(self, messages: list, **kwargs: Any) -> Any:
        for attempt in range(1, self.attempts + 1):
            try:
                return self.llm.invoke(messages, **kwargs)
            except Exception as exc:
                if attempt == self.attempts or not is_rate_limit_error(exc):
                    raise
                self.sleep(min(self.base_delay * 2 ** (attempt - 1), self.max_delay))

def build_llm(settings: Settings) -> RetryingLLM:
    """Instancia o chat model do provedor configurado.

    Importa cada SDK de forma preguicosa para nao exigir todos instalados.
    """
    return RetryingLLM(_build_chat_model(settings))

def _build_chat_model(settings: Settings) -> ChatModel:
    provider = settings.provider
    extra: dict[str, Any] = {}
    if settings.requests_per_second > 0:
        from langchain_core.rate_limiters import InMemoryRateLimiter

        extra["rate_limiter"] = InMemoryRateLimiter(
            requests_per_second=settings.requests_per_second,
            check_every_n_seconds=0.1,
            max_bucket_size=1,
        )

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.model,
            temperature=settings.temperature,
            base_url=settings.ollama_base_url,
            num_predict=1024,
            **extra,
        )

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        _require("GEMINI_API_KEY", provider)
        return ChatGoogleGenerativeAI(
            model=settings.model,
            temperature=settings.temperature,
            api_key=os.environ["GEMINI_API_KEY"],
            **extra,
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        _require("OPENAI_API_KEY", provider)
        return ChatOpenAI(model=settings.model, temperature=settings.temperature, **extra)

    if provider == "groq":
        from langchain_groq import ChatGroq

        _require("GROQ_API_KEY", provider)
        return ChatGroq(model=settings.model, temperature=settings.temperature, **extra)

    raise ValueError(
        f"Provedor de LLM desconhecido: '{provider}'. "
        "Use um de: ollama | gemini | openai | groq."
    )

def _require(env_var: str, provider: str) -> None:
    if not os.getenv(env_var):
        raise RuntimeError(
            f"O provedor '{provider}' exige a variavel {env_var} no .env. "
            "Para rodar sem nenhuma chave, use LLM_PROVIDER=ollama."
        )
