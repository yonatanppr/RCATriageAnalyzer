"""LLM provider interface and implementations."""

import json
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


class OpenAILLMClient:
    """OpenAI-backed implementation for triage generation."""

    def __init__(self) -> None:
        self.settings = get_settings()
        if not self.settings.openai_api_key:
            raise LLMConfigurationError("OPENAI_API_KEY is not configured")
        self.client = OpenAI(api_key=self.settings.openai_api_key)
        self.model_name = self.settings.openai_model

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
        return json.loads(response.output_text)


class OllamaLLMClient:
    """Local Ollama-backed implementation for private/offline triage."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.model_name = self.settings.local_llm_model

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

        try:
            with httpx.Client(timeout=self.settings.local_llm_timeout_seconds) as client:
                resp = client.post(f"{self.settings.ollama_base_url}/api/generate", json=payload)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMConfigurationError(f"failed to reach local Ollama service: {exc}") from exc

        data = resp.json()
        text = data.get("response", "")
        if not text:
            raise RuntimeError("Local LLM response was empty")

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Local LLM returned invalid JSON") from exc


def get_llm_client() -> LLMClient:
    """Factory for configured LLM provider."""

    settings = get_settings()
    if settings.llm_provider == "openai":
        return OpenAILLMClient()
    if settings.llm_provider == "local":
        return OllamaLLMClient()
    raise LLMConfigurationError(f"unsupported LLM_PROVIDER={settings.llm_provider}")
