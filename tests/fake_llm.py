"""A scriptable stand-in for the Gemini text client (tests never call the real API)."""

from types import SimpleNamespace

from google.genai import errors, types


def server_error(code: int = 503) -> errors.APIError:
    return errors.ServerError(code, {"error": {"code": code, "message": "high demand", "status": "UNAVAILABLE"}})


def client_error(code: int = 400) -> errors.APIError:
    return errors.ClientError(code, {"error": {"code": code, "message": "bad request", "status": "INVALID_ARGUMENT"}})


def tool_calls(*calls: tuple[str, dict]) -> SimpleNamespace:
    """A response in which the model calls tools: tool_calls(("name", {args}), ...)."""
    fcs = [types.FunctionCall(id=f"c{i}", name=name, args=args) for i, (name, args) in enumerate(calls)]
    content = types.Content(role="model", parts=[types.Part(function_call=fc) for fc in fcs])
    return SimpleNamespace(function_calls=fcs, text=None, candidates=[SimpleNamespace(content=content)], parsed=None)


def text(value: str, parsed=None) -> SimpleNamespace:
    content = types.Content(role="model", parts=[types.Part(text=value)])
    return SimpleNamespace(function_calls=None, text=value, candidates=[SimpleNamespace(content=content)], parsed=parsed)


class FakeClient:
    """Returns (or raises) the scripted items in order; records every request."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[dict] = []
        self.models = self

    def generate_content(self, *, model, contents, config=None):
        self.requests.append({"model": model, "contents": list(contents) if isinstance(contents, list) else contents, "config": config})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
