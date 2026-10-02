"""The single place that calls Gemini for text: retries, backoff and a model fallback chain.

During planning, gemini-3.8-flash repeatedly answered `503 high demand` on the free tier,
so every text call goes through `generate()`: a few attempts per model with backoff, then
the next model. Only transient errors (429/5xx, timeouts) are retried; a 4xx means our
request is wrong, and retrying would not help.
"""

import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache

from google import genai
from google.genai import errors, types

RETRYABLE_CODES = {429, 500, 502, 503, 504}
# "Model not found / no longer available to new users" (seen live for gemini-2.5-flash):
# no point retrying that model, but the next model in the chain may well work.
SKIP_MODEL_CODES = {404}
REQUEST_TIMEOUT_MS = 90_000


class LLMUnavailable(Exception):
    """Every model in the chain failed (after retries)."""


@dataclass(frozen=True)
class LLMResult:
    response: types.GenerateContentResponse
    model: str
    attempts: int


def _log(message: str) -> None:
    print(f"[llm] {message}", file=sys.stderr, flush=True)


@lru_cache
def text_client(api_key: str) -> genai.Client:
    # The SDK's own retries are disabled: generate() owns retry + fallback, so they
    # don't multiply. Each request has a hard timeout.
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=REQUEST_TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1)
        ),
    )


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, errors.APIError):
        return exc.code in RETRYABLE_CODES
    return isinstance(exc, (TimeoutError, ConnectionError)) or "timeout" in type(exc).__name__.lower()


def generate(
    client,
    models: Sequence[str],
    contents,
    config: types.GenerateContentConfig | None = None,
    *,
    attempts_per_model: int = 3,
    backoff_s: Sequence[float] = (2, 6),
    sleep: Callable[[float], None] | None = None,  # default: time.sleep (looked up at call time)
    deadline: float | None = None,  # time.monotonic() value; stop trying after it
) -> LLMResult:
    sleep = sleep or time.sleep
    attempts = 0
    last_error: Exception | None = None
    for model in models:
        for attempt in range(attempts_per_model):
            if deadline is not None and time.monotonic() > deadline:
                raise LLMUnavailable(f"time budget exhausted after {attempts} attempts: {last_error!s:.200}")
            attempts += 1
            try:
                response = client.models.generate_content(model=model, contents=contents, config=config)
                return LLMResult(response=response, model=model, attempts=attempts)
            except Exception as exc:  # noqa: BLE001 -- classified just below
                last_error = exc
                if isinstance(exc, errors.APIError) and exc.code in SKIP_MODEL_CODES:
                    _log(f"{model} unavailable ({exc.code}): trying the next model")
                    break
                if not _is_retryable(exc):
                    raise
                _log(f"{model} attempt {attempt + 1} failed: {exc!s:.120}")
                if attempt < attempts_per_model - 1:
                    sleep(backoff_s[min(attempt, len(backoff_s) - 1)])
    raise LLMUnavailable(f"all models failed after {attempts} attempts: {last_error!s:.200}")
