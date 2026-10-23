from __future__ import annotations

import os

from langchain_core.language_models.chat_models import BaseChatModel

from .config import Settings

def build_llm(settings: Settings) -> BaseChatModel:
    """Instancia o chat model do provedor configurado.

    Importa cada SDK de forma preguicosa para nao exigir todos instalados.
    """
    provider = settings.provider

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.model,
            temperature=settings.temperature,
            base_url=settings.ollama_base_url,
            num_predict=1024,
        )

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        _require("GEMINI_API_KEY", provider)
        return ChatGoogleGenerativeAI(
            model=settings.model,
            temperature=settings.temperature,
            api_key=os.environ["GEMINI_API_KEY"],
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        _require("OPENAI_API_KEY", provider)
        return ChatOpenAI(model=settings.model, temperature=settings.temperature)

    if provider == "groq":
        from langchain_groq import ChatGroq

        _require("GROQ_API_KEY", provider)
        return ChatGroq(model=settings.model, temperature=settings.temperature)

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

