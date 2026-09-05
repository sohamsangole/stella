import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional, Type, Union

import requests
try:
    from pydantic import BaseModel
except ImportError:  # pragma: no cover
    BaseModel = None

from stella.core.config import settings


class LLMError(Exception):
    """Base exception for all LLM client errors."""
    pass


class LLMConfigurationError(LLMError):
    """Raised when API credentials or model cannot be resolved."""
    pass


class LLMAuthenticationError(LLMError):
    """Raised when authentication with the provider fails."""
    pass


class LLMSchemaError(LLMError):
    """Raised when LLM response cannot be parsed or validated against the schema."""
    pass


@dataclass
class LLMResponse:
    """Unified response object returned by LLMClient."""
    content: str
    structured_data: Optional[Any] = None
    model: str = ""
    raw_response: Optional[dict] = None
    usage: Optional[dict] = None


def _strip_markdown_fences(text: str) -> str:
    """Strip markdown code block fences (e.g. ```json ... ```) from model output."""
    pattern = r"^```(?:json)?\s*\n(.*?)\n```$"
    match = re.search(pattern, text.strip(), re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _normalize_schema(
    schema: Optional[Union[dict, Any]]
) -> tuple[Optional[dict], Optional[Any]]:
    """Normalize Pydantic model or dict into a JSON schema dict and optional Pydantic type."""
    if schema is None:
        return None, None
    if BaseModel is not None and isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_json_schema(), schema
    if isinstance(schema, dict):
        return schema, None
    raise ValueError(f"Schema must be a Pydantic BaseModel class or a dict, got {type(schema)}")


def _validate_and_parse_json(
    raw_text: str,
    schema_model: Optional[Type[Any]] = None,
) -> tuple[Any, str]:
    """Parse JSON string and validate against Pydantic model if provided."""
    cleaned = _strip_markdown_fences(raw_text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as err:
        raise LLMSchemaError(f"Failed to decode JSON from model response: {err}\nOutput: {raw_text}") from err

    if schema_model is not None:
        try:
            validated = schema_model.model_validate(parsed)
            return validated, cleaned
        except Exception as err:
            raise LLMSchemaError(f"Failed to validate response against Pydantic schema {schema_model.__name__}: {err}") from err

    return parsed, cleaned


class LLMClient:
    """
    Model-agnostic LLM client supporting any completions endpoint with structured JSON outputs.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 60,
        request_runner: Optional[Callable] = None,
    ) -> None:
        resolved_model = (
            model
            or getattr(settings, "llm_model", "")
            or os.environ.get("LLM_MODEL", "")
        )
        if not resolved_model:
            raise LLMConfigurationError(
                "No LLM model specified. Please pass 'model' or set LLM_MODEL in your environment."
            )
        self.model = resolved_model

        resolved_key = (
            api_key
            or getattr(settings, "llm_api_key", "")
            or os.environ.get("LLM_API_KEY", "")
        )
        self.api_key = resolved_key

        resolved_base_url = (
            base_url
            or getattr(settings, "llm_base_url", "")
            or os.environ.get("LLM_BASE_URL", "")
            or "https://api.openai.com/v1"
        )
        self.base_url = resolved_base_url.rstrip("/")
        self.timeout = timeout
        self._request_runner = request_runner or requests.request

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        schema: Optional[Union[dict, Any]] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Generate completion from the LLM, optionally enforcing and validating a structured JSON schema.
        Unified linear execution: _build_request -> _request -> _parse_response.
        """
        json_schema, schema_model = _normalize_schema(schema)

        url, headers, payload = self._build_request(
            prompt=prompt,
            system_prompt=system_prompt,
            json_schema=json_schema,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

        response = self._request(method="POST", url=url, headers=headers, json=payload)
        try:
            data = response.json()
        except Exception as err:
            raise LLMError(f"Failed to parse JSON response from LLM endpoint: {err}\nResponse body: {response.text}") from err

        return self._parse_response(
            data=data,
            json_schema=json_schema,
            schema_model=schema_model,
        )

    def _build_request(
        self,
        prompt: str,
        system_prompt: Optional[str],
        json_schema: Optional[dict],
        temperature: float,
        max_tokens: Optional[int],
        **kwargs: Any,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        """Construct universal completions endpoint URL, headers, and request payload."""
        url = f"{self.base_url}/chat/completions"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        messages = []
        eff_system_prompt = system_prompt or ""
        if json_schema:
            schema_inst = (
                f"\nYou must respond ONLY with a valid JSON object strictly matching this schema:\n"
                f"{json.dumps(json_schema)}"
            )
            eff_system_prompt = (eff_system_prompt + schema_inst).strip()

        if eff_system_prompt:
            messages.append({"role": "system", "content": eff_system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if json_schema:
            payload["response_format"] = {"type": "json_object"}

        return url, headers, payload

    def _parse_response(
        self,
        data: dict[str, Any],
        json_schema: Optional[dict],
        schema_model: Optional[Type[Any]],
    ) -> LLMResponse:
        """Extract response text, validate structured output against schema, and return LLMResponse."""
        choices = data.get("choices", [])
        if not choices:
            raise LLMError(f"LLM endpoint returned no choices: {data}")

        message = choices[0].get("message", {})
        if message.get("refusal"):
            raise LLMError(f"LLM endpoint refused request: {message['refusal']}")

        content = message.get("content") or ""
        usage = data.get("usage")

        structured_data = None
        if json_schema:
            structured_data, content = _validate_and_parse_json(content, schema_model)

        return LLMResponse(
            content=content,
            structured_data=structured_data,
            model=self.model,
            raw_response=data,
            usage=usage,
        )

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Execute HTTP request with error checking and timeout."""
        try:
            response = self._request_runner(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException as err:
            raise LLMError(f"Network error connecting to LLM endpoint: {err}") from err

        if response.status_code in (401, 403):
            raise LLMAuthenticationError(
                f"Authentication failed ({response.status_code}): {response.text}"
            )
        if not response.ok:
            raise LLMError(
                f"LLM request failed with status {response.status_code}: {response.text}"
            )

        return response
