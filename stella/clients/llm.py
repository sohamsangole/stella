import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional, Type, Union

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
