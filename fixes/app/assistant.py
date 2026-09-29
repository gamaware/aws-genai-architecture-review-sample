"""Fixed request path for the ask and compare routes (closes the guardrail, PII-in-logs and prompt-caching findings).

Changes against the as-found handler:

- every request carries the route's guardrail by ID and version, and the shopper's question is marked as guard
  content, so input filters (prompt attack, PII) run on the question and output filters on the answer;
- on routes whose system prompt reaches the model's minimum cacheable length (1,024 tokens for Claude Sonnet 4.5,
  4,096 for Claude Haiku 4.5), a cache point follows it, so repeated requests read that prefix from the prompt cache.
  The compare route (Sonnet, 2,400 tokens) sets `cache_system_prompt`; the ask route (Haiku, 2,400 tokens) does not,
  because Bedrock ignores a checkpoint on a shorter prefix;
- the response length is capped per route;
- logs carry request metadata and token counts only, never the prompt or the answer; error text is redacted;
- throttling is retried with capped exponential backoff instead of surfacing as a 500 to the shopper.

The Bedrock client is injected (boto3 `bedrock-runtime` in the function, a stub in the tests).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

PII_PATTERNS = (
    (re.compile(r"\b\d{3}[-. ]?\d{3}[-. ]?\d{4}\b"), "[PHONE]"),
    (re.compile(r"\bHG-LOY-\d{8}\b"), "[LOYALTY]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
)
MAX_TOKENS_CEILING = 2048
RETRYABLE = frozenset({"ThrottlingException", "ServiceUnavailableException", "ModelNotReadyException"})


class BedrockRuntime(Protocol):
    def converse(self, **kwargs: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RouteConfig:
    route: str
    model_id: str
    guardrail_id: str
    guardrail_version: str
    max_tokens: int
    system_prompt: str
    cache_system_prompt: bool = False

    def __post_init__(self) -> None:
        if not self.guardrail_id or not self.guardrail_version:
            raise ValueError(f"route {self.route}: a guardrail ID and version are required")
        if not 0 < self.max_tokens <= MAX_TOKENS_CEILING:
            raise ValueError(f"route {self.route}: max_tokens must be between 1 and {MAX_TOKENS_CEILING}")


@dataclass(frozen=True)
class Question:
    request_id: str
    text: str
    context: tuple[str, ...]


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_delay: float = 0.2
    sleep: Callable[[float], None] = time.sleep


def redact(text: str) -> str:
    for pattern, label in PII_PATTERNS:
        text = pattern.sub(label, text)
    return text


def build_request(config: RouteConfig, question: Question) -> dict[str, Any]:
    context_text = "\n\n".join(question.context)
    system: list[dict[str, Any]] = [{"text": config.system_prompt}]
    if config.cache_system_prompt:
        system.append({"cachePoint": {"type": "default"}})
    return {
        "modelId": config.model_id,
        "system": system,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"text": f"Catalog excerpts:\n{context_text}"},
                    {"guardContent": {"text": {"text": question.text}}},
                ],
            }
        ],
        "inferenceConfig": {"maxTokens": config.max_tokens},
        "guardrailConfig": {
            "guardrailIdentifier": config.guardrail_id,
            "guardrailVersion": config.guardrail_version,
            "trace": "disabled",
        },
    }


def _error_code(error: Exception) -> str | None:
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        return response.get("Error", {}).get("Code")
    return None


def answer(
    client: BedrockRuntime,
    config: RouteConfig,
    question: Question,
    logger: logging.Logger,
    retry: RetryPolicy | None = None,
) -> dict[str, Any]:
    retry = retry or RetryPolicy()
    request = build_request(config, question)
    for attempt in range(retry.attempts):
        try:
            response = client.converse(**request)
            break
        except Exception as error:
            if _error_code(error) not in RETRYABLE or attempt == retry.attempts - 1:
                failure = {"request_id": question.request_id, "route": config.route, "error": redact(str(error))}
                logger.error(json.dumps(failure))
                raise
            retry.sleep(retry.base_delay * 2**attempt)

    usage = response.get("usage", {})
    record = {
        "request_id": question.request_id,
        "route": config.route,
        "model_id": config.model_id,
        "stop_reason": response.get("stopReason"),
        "input_tokens": usage.get("inputTokens", 0),
        "output_tokens": usage.get("outputTokens", 0),
        "cache_read_tokens": usage.get("cacheReadInputTokens", 0),
        "cache_write_tokens": usage.get("cacheWriteInputTokens", 0),
    }
    logger.info(json.dumps(record, sort_keys=True))
    blocks = response["output"]["message"]["content"]
    return {
        "text": "".join(block.get("text", "") for block in blocks),
        "guardrail_intervened": response.get("stopReason") == "guardrail_intervened",
        "usage": record,
    }
