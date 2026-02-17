import httpx
import pytest

from app.adapters.llm import LLMConfigurationError, OllamaLLMClient, OpenAILLMClient, get_llm_client
from app.config import get_settings


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("request failed", request=httpx.Request("GET", "http://test"), response=httpx.Response(self.status_code))

    def json(self) -> dict:
        return self._payload


class _FakeHttpxClient:
    def __init__(self, states: dict[str, dict], timeout: int | float | None = None) -> None:
        self.states = states
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def get(self, url: str) -> _FakeResponse:
        endpoint = url.split("/api/")[0]
        state = self.states.get(endpoint, {})
        if state.get("health") == "error":
            raise httpx.ConnectError("connection failed")
        status = state.get("health_status", 200)
        payload = state.get("health_payload")
        if payload is None:
            payload = {"models": [{"name": "qwen2.5:7b-instruct"}]}
        return _FakeResponse(status_code=status, payload=payload)

    def post(self, url: str, json: dict) -> _FakeResponse:
        endpoint = url.split("/api/")[0]
        state = self.states.get(endpoint, {})
        calls = state.get("post_calls", 0)
        state["post_calls"] = calls + 1
        self.states[endpoint] = state
        if state.get("post_error"):
            raise httpx.ConnectError("post failed")
        payload = state.get("post_payload")
        if payload is None:
            payload = {"response": '{"summary":"ok","mode":"normal","facts":[],"hypotheses":[],"next_checks":[],"mitigations":[],"claims":[],"uncertainty_note":null}'}
        return _FakeResponse(status_code=state.get("post_status", 200), payload=payload)


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


def test_ollama_prefers_first_healthy_endpoint(monkeypatch) -> None:
    states = {
        "http://host.docker.internal:11434": {"health_status": 200},
        "http://ollama:11434": {"health_status": 200},
    }
    monkeypatch.setattr(httpx, "Client", lambda timeout=None: _FakeHttpxClient(states, timeout=timeout))
    monkeypatch.setenv("OLLAMA_ENDPOINTS", "http://host.docker.internal:11434,http://ollama:11434")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    get_settings.cache_clear()

    client = OllamaLLMClient()
    report = client.generate_triage_report({"foo": "bar"}, {"type": "object"})
    assert report["summary"] == "ok"
    meta = client.generation_metadata()
    assert meta["llm_endpoint_used"] == "http://host.docker.internal:11434"
    assert meta["endpoint_failover_count"] == 0
    assert states["http://host.docker.internal:11434"]["post_calls"] == 1


def test_ollama_falls_back_to_second_endpoint_when_first_unhealthy(monkeypatch) -> None:
    states = {
        "http://host.docker.internal:11434": {"health_status": 200, "health_payload": {"models": []}},
        "http://ollama:11434": {"health_status": 200},
    }
    monkeypatch.setattr(httpx, "Client", lambda timeout=None: _FakeHttpxClient(states, timeout=timeout))
    monkeypatch.setenv("OLLAMA_ENDPOINTS", "http://host.docker.internal:11434,http://ollama:11434")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    get_settings.cache_clear()

    client = OllamaLLMClient()
    report = client.generate_triage_report({"foo": "bar"}, {"type": "object"})
    assert report["summary"] == "ok"
    meta = client.generation_metadata()
    assert meta["llm_endpoint_used"] == "http://ollama:11434"
    assert meta["endpoint_failover_count"] == 0


def test_ollama_midrun_failover_retries_once_on_next_endpoint(monkeypatch) -> None:
    states = {
        "http://host.docker.internal:11434": {"health_status": 200, "post_error": True},
        "http://ollama:11434": {"health_status": 200},
    }
    monkeypatch.setattr(httpx, "Client", lambda timeout=None: _FakeHttpxClient(states, timeout=timeout))
    monkeypatch.setenv("OLLAMA_ENDPOINTS", "http://host.docker.internal:11434,http://ollama:11434")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    get_settings.cache_clear()

    client = OllamaLLMClient()
    report = client.generate_triage_report({"foo": "bar"}, {"type": "object"})
    assert report["summary"] == "ok"
    meta = client.generation_metadata()
    assert meta["llm_endpoint_used"] == "http://ollama:11434"
    assert meta["endpoint_failover_count"] == 1
    assert states["http://host.docker.internal:11434"]["post_calls"] == 1
    assert states["http://ollama:11434"]["post_calls"] == 1


def test_ollama_fails_when_all_endpoints_unavailable(monkeypatch) -> None:
    states = {
        "http://host.docker.internal:11434": {"health_status": 200, "health_payload": {"models": []}},
        "http://ollama:11434": {"health": "error"},
    }
    monkeypatch.setattr(httpx, "Client", lambda timeout=None: _FakeHttpxClient(states, timeout=timeout))
    monkeypatch.setenv("OLLAMA_ENDPOINTS", "http://host.docker.internal:11434,http://ollama:11434")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    get_settings.cache_clear()

    client = OllamaLLMClient()
    with pytest.raises(LLMConfigurationError, match="failed to reach any Ollama endpoint"):
        client.generate_triage_report({"foo": "bar"}, {"type": "object"})


def test_ollama_skips_endpoint_without_configured_model(monkeypatch) -> None:
    states = {
        "http://host.docker.internal:11434": {"health_status": 200, "health_payload": {"models": [{"name": "other:latest"}]}},
        "http://ollama:11434": {"health_status": 200, "health_payload": {"models": [{"name": "qwen2.5:7b-instruct"}]}},
    }
    monkeypatch.setattr(httpx, "Client", lambda timeout=None: _FakeHttpxClient(states, timeout=timeout))
    monkeypatch.setenv("OLLAMA_ENDPOINTS", "http://host.docker.internal:11434,http://ollama:11434")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("LOCAL_LLM_MODEL", "qwen2.5:7b-instruct")
    get_settings.cache_clear()

    client = OllamaLLMClient()
    _ = client.generate_triage_report({"foo": "bar"}, {"type": "object"})
    meta = client.generation_metadata()
    assert meta["llm_endpoint_used"] == "http://ollama:11434"


def test_ollama_prepends_deprecated_base_url(monkeypatch) -> None:
    states = {
        "http://legacy-ollama:11434": {"health_status": 200},
        "http://host.docker.internal:11434": {"health_status": 200},
    }
    monkeypatch.setattr(httpx, "Client", lambda timeout=None: _FakeHttpxClient(states, timeout=timeout))
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://legacy-ollama:11434")
    monkeypatch.setenv("OLLAMA_ENDPOINTS", "http://host.docker.internal:11434")
    get_settings.cache_clear()

    client = OllamaLLMClient()
    _ = client.generate_triage_report({"foo": "bar"}, {"type": "object"})
    meta = client.generation_metadata()
    assert meta["llm_endpoint_used"] == "http://legacy-ollama:11434"
