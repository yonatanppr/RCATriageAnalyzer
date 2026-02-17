"""LLM provider interface and implementations."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx
from openai import OpenAI

from app.config import get_settings


class LLMConfigurationError(RuntimeError):
    """Raised when LLM provider credentials/configuration are invalid."""


class LLMClient(Protocol):
    """LLM client contract."""

    model_name: str

    def generate_triage_report(self, evidence_digest: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        """Generate a triage report in strict JSON."""

    def generation_metadata(self) -> dict[str, Any]:
        """Return provider/runtime metadata for the last generation call."""


class OpenAILLMClient:
    """OpenAI-backed implementation for triage generation."""

    def __init__(self) -> None:
        self.settings = get_settings()
        if not self.settings.openai_api_key:
            raise LLMConfigurationError("OPENAI_API_KEY is not configured")
        self.client = OpenAI(api_key=self.settings.openai_api_key)
        self.model_name = self.settings.openai_model
        self._last_generation_metadata: dict[str, Any] = {"llm_provider": "openai"}

    def generate_triage_report(self, evidence_digest: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            "You are producing an incident triage report with strict evidence-citation rules. "
            "Do not invent any fact. Every fact must include evidence_refs with artifact_id and pointer. "
            "Separate facts from hypotheses. Include claims[] that map all key statements to evidence_refs. "
            "If evidence is weak, set mode=insufficient_evidence and only propose next_checks with citations. "
            "Return JSON only and strictly follow the provided schema."
        )
        response = self.client.responses.create(
            model=self.settings.openai_model,
            input=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "evidence_pack_digest": evidence_digest,
                            "json_schema": schema,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            text={"format": {"type": "json_object"}},
        )

        if not response.output_text:
            raise RuntimeError("LLM response was empty")
        self._last_generation_metadata = {"llm_provider": "openai"}
        return json.loads(response.output_text)

    def generation_metadata(self) -> dict[str, Any]:
        return dict(self._last_generation_metadata)


class OllamaLLMClient:
    """Local Ollama-backed implementation for private/offline triage."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.model_name = self.settings.local_llm_model
        self._cached_endpoint: str | None = None
        self._cache_expires_at: datetime | None = None
        self._last_generation_metadata: dict[str, Any] = {"llm_provider": "local"}

    def _configured_endpoints(self) -> list[str]:
        endpoints = [url.strip().rstrip("/") for url in self.settings.ollama_endpoints.split(",") if url.strip()]
        if self.settings.ollama_base_url:
            legacy = self.settings.ollama_base_url.strip().rstrip("/")
            if legacy:
                endpoints = [legacy, *endpoints]
        unique: list[str] = []
        for endpoint in endpoints:
            if endpoint not in unique:
                unique.append(endpoint)
        return unique

    def _cache_endpoint(self, endpoint: str) -> None:
        self._cached_endpoint = endpoint
        self._cache_expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.settings.ollama_endpoint_cache_ttl_seconds)

    def _cached_endpoint_valid(self, candidates: list[str]) -> bool:
        if not self._cached_endpoint or not self._cache_expires_at:
            return False
        if datetime.now(timezone.utc) >= self._cache_expires_at:
            return False
        return self._cached_endpoint in candidates

    def _is_healthy(self, client: httpx.Client, endpoint: str) -> bool:
        try:
            resp = client.get(f"{endpoint}/api/tags")
            resp.raise_for_status()
            payload = resp.json()
            models = payload.get("models", []) if isinstance(payload, dict) else []
            if not isinstance(models, list):
                return False
            model_names = {
                str(item.get("name", "")).strip()
                for item in models
                if isinstance(item, dict) and item.get("name")
            }
            return self.settings.local_llm_model in model_names
        except httpx.HTTPError:
            return False
        except ValueError:
            return False

    def _first_healthy(self, client: httpx.Client, endpoints: list[str], start_index: int = 0) -> tuple[str | None, int]:
        for index in range(start_index, len(endpoints)):
            endpoint = endpoints[index]
            if self._is_healthy(client, endpoint):
                return endpoint, index
        return None, -1

    def generate_triage_report(self, evidence_digest: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            "You are producing an incident triage report with strict evidence-citation rules. "
            "Do not invent any fact. Every fact must include evidence_refs with artifact_id and pointer. "
            "Separate facts from hypotheses. Include claims[] that map all key statements to evidence_refs. "
            "If evidence is weak, set mode=insufficient_evidence and only propose next_checks with citations. "
            "Return JSON only, matching the provided JSON schema."
        )
        payload = {
            "model": self.settings.local_llm_model,
            "stream": False,
            "format": schema,
            "prompt": json.dumps(
                {
                    "system_instruction": prompt,
                    "evidence_pack_digest": evidence_digest,
                    "json_schema": schema,
                },
                ensure_ascii=False,
            ),
            "options": {
                "temperature": 0.2,
            },
        }

        health_timeout = self.settings.ollama_healthcheck_timeout_seconds
        endpoints = self._configured_endpoints()
        if not endpoints:
            raise LLMConfigurationError("no Ollama endpoint configured; set OLLAMA_ENDPOINTS")

        with httpx.Client(timeout=health_timeout) as health_client:
            if self._cached_endpoint_valid(endpoints):
                selected_endpoint = self._cached_endpoint
                selected_index = endpoints.index(selected_endpoint)
            else:
                selected_endpoint, selected_index = self._first_healthy(health_client, endpoints)
                if not selected_endpoint:
                    raise LLMConfigurationError(
                        f"failed to reach any Ollama endpoint: {', '.join(endpoints)}"
                    )
                self._cache_endpoint(selected_endpoint)

        failover_count = 0
        response: httpx.Response | None = None
        errors: list[str] = []

        try:
            with httpx.Client(timeout=self.settings.local_llm_timeout_seconds) as client:
                try:
                    response = client.post(f"{selected_endpoint}/api/generate", json=payload)
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    errors.append(f"{selected_endpoint}: {exc}")
                    next_endpoint, _ = self._first_healthy(client, endpoints, selected_index + 1)
                    if not next_endpoint:
                        raise
                    failover_count = 1
                    self._cache_endpoint(next_endpoint)
                    response = client.post(f"{next_endpoint}/api/generate", json=payload)
                    response.raise_for_status()
                    selected_endpoint = next_endpoint
        except httpx.HTTPError as exc:
            suffix = f" ({'; '.join(errors)})" if errors else ""
            raise LLMConfigurationError(
                f"failed to generate from configured Ollama endpoints: {exc}{suffix}"
            ) from exc

        if response is None:
            raise RuntimeError("Local LLM call did not return a response")

        data = response.json()
        text = data.get("response", "")
        if not text:
            raise RuntimeError("Local LLM response was empty")

        try:
            output = json.loads(text)
            self._last_generation_metadata = {
                "llm_provider": "local",
                "llm_endpoint_used": selected_endpoint,
                "endpoint_failover_count": failover_count,
            }
            return output
        except json.JSONDecodeError as exc:
            raise RuntimeError("Local LLM returned invalid JSON") from exc

    def generation_metadata(self) -> dict[str, Any]:
        return dict(self._last_generation_metadata)


def get_llm_client() -> LLMClient:
    """Factory for configured LLM provider."""

    settings = get_settings()
    if settings.llm_provider == "openai":
        return OpenAILLMClient()
    if settings.llm_provider == "local":
        return OllamaLLMClient()
    raise LLMConfigurationError(f"unsupported LLM_PROVIDER={settings.llm_provider}")
