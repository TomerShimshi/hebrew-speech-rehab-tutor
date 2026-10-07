"""The single place that calls Gemini for text: retries, backoff and a model fallback chain.

During planning, gemini-3.8-flash repeatedly answered `503 high demand` on the free tier,
so every text call goes through `generate()` with a model fallback chain:

- overloaded (503 high demand, 504 deadline, a client timeout) -> the NEXT model at once;
  retrying an overloaded model within seconds rarely helps, and each try can hang for long
- quota / not available (429 / 404) -> the next model at once
- other transient errors (500 / 502) -> retried on the same model with backoff
- anything else (4xx) -> raised: our request is wrong, retrying would not help
If the whole chain failed, one more pass after a short pause (time budget permitting).

A model that was overloaded / out of quota is remembered as "cooling down" for 10 minutes and
skipped -- otherwise every step of a multi-call update waits on it again (seen live: each
tool round lost 45 s to a hung 3.8-flash and the update ran out of time). If every model is
cooling down, all are tried anyway.

Seen live on 7.10.26: 3.8-flash hung ~90 s per try and answered 504 / 503; the old "3 tries
per model" spent the whole budget on it and the working fallback (flash-lite) was never tried.
"""

import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache

from google import genai
from google.genai import errors, types

RETRYABLE_CODES = {500, 502}
# Skip straight to the next model (retrying the same one can't help):
#  404 = model not available (seen live: gemini-2.5-flash "no longer available to new users")
#  429 = quota exhausted (seen live: free-tier daily limits) -- doesn't recover in seconds
#  503 / 504 = overloaded ("high demand" / deadline exceeded) -- try another model now
SKIP_MODEL_CODES = {404, 429, 503, 504}
REQUEST_TIMEOUT_MS = 45_000  # these calls normally take 5-20 s; a hung one must not eat the budget
CHAIN_PASSES = 2
PASS_PAUSE_S = 10
COOLDOWN_S = 600
_cooling_until: dict[str, float] = {}  # model -> time.monotonic() until which it's skipped


def _order(models: Sequence[str]) -> list[str]:
    """The chain without models that are cooling down (all of them if every one is)."""
    now = time.monotonic()
    ready = [m for m in models if _cooling_until.get(m, 0) <= now]
    return ready or list(models)


def reset_cooldowns() -> None:
    _cooling_until.clear()


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


def _is_timeout(exc: Exception) -> bool:
    return isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower()


def _skips_model(exc: Exception) -> bool:
    return (isinstance(exc, errors.APIError) and exc.code in SKIP_MODEL_CODES) or _is_timeout(exc)


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, errors.APIError):
        return exc.code in RETRYABLE_CODES
    return isinstance(exc, ConnectionError)


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
    for chain_pass in range(CHAIN_PASSES):
        if chain_pass:
            if deadline is not None and time.monotonic() + PASS_PAUSE_S > deadline:
                break
            _log(f"every model failed; one more pass in {PASS_PAUSE_S}s")
            sleep(PASS_PAUSE_S)
        for model in _order(models):
            for attempt in range(attempts_per_model):
                if deadline is not None and time.monotonic() > deadline:
                    raise LLMUnavailable(f"time budget exhausted after {attempts} attempts: {last_error!s:.200}")
                attempts += 1
                try:
                    response = client.models.generate_content(model=model, contents=contents, config=config)
                    return LLMResult(response=response, model=model, attempts=attempts)
                except Exception as exc:  # noqa: BLE001 -- classified just below
                    last_error = exc
                    if _skips_model(exc):
                        _cooling_until[model] = time.monotonic() + COOLDOWN_S
                        _log(f"{model} unavailable ({getattr(exc, 'code', type(exc).__name__)}): "
                             f"skipped for {COOLDOWN_S // 60} min; trying the next model")
                        break
                    if not _is_retryable(exc):
                        raise
                    _log(f"{model} attempt {attempt + 1} failed: {exc!s:.120}")
                    if attempt < attempts_per_model - 1:
                        sleep(backoff_s[min(attempt, len(backoff_s) - 1)])
    raise LLMUnavailable(f"all models failed after {attempts} attempts: {last_error!s:.200}")
