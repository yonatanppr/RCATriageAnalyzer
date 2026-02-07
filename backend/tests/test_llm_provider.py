import pytest

from app.adapters.llm import LLMConfigurationError, OllamaLLMClient, OpenAILLMClient, get_llm_client
from app.config import get_settings


def test_get_llm_client_local_provider(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "qwen2.5:7b-instruct")
    get_settings.cache_clear()

    client = get_llm_client()
    assert isinstance(client, OllamaLLMClient)


def test_get_llm_client_openai_requires_key(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()

    with pytest.raises(LLMConfigurationError):
        get_llm_client()


def test_get_llm_client_openai_provider_with_key(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    get_settings.cache_clear()

    client = get_llm_client()
    assert isinstance(client, OpenAILLMClient)
