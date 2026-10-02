"""A small, explicit function-calling loop for the SUMMARY_MODEL agent calls (04-07).

We run the loop ourselves (not the SDK's automatic function calling) so that every tool
call is validated, logged and bounded: at most `max_rounds` model turns, and a failing
tool returns an error message to the model instead of crashing the whole update.
"""

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from google.genai import types

from app.llm import generate


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON schema of the arguments
    handler: Callable[[dict], dict]  # args -> result (raise ValueError for bad input)

    def declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name, description=self.description, parameters_json_schema=self.parameters
        )


@dataclass
class ToolCallRecord:
    name: str
    args: dict
    ok: bool
    result: dict


@dataclass
class AgentRun:
    calls: list[ToolCallRecord] = field(default_factory=list)
    final_text: str = ""
    rounds: int = 0
    models: list[str] = field(default_factory=list)
    attempts: int = 0
    hit_round_limit: bool = False


def _log(message: str) -> None:
    print(f"[agent] {message}", file=sys.stderr, flush=True)


def run_tool_loop(
    client,
    models: Sequence[str],
    system_instruction: str,
    user_content: str,
    tools: Sequence[Tool],
    *,
    max_rounds: int = 8,
    generate_fn=generate,
) -> AgentRun:
    registry = {tool.name: tool for tool in tools}
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=[types.Tool(function_declarations=[t.declaration() for t in tools])],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0.2,  # careful bookkeeping, not creativity
    )
    contents: list[types.Content] = [types.Content(role="user", parts=[types.Part(text=user_content)])]
    run = AgentRun()

    for _ in range(max_rounds):
        result = generate_fn(client, models, contents, config)
        run.rounds += 1
        run.attempts += result.attempts
        run.models.append(result.model)
        response = result.response
        calls = response.function_calls or []
        if not calls:
            run.final_text = response.text or ""
            return run
        # Keep the model's turn (with its function calls) in the history, then answer each.
        contents.append(response.candidates[0].content)
        reply_parts = []
        for call in calls:
            args = dict(call.args or {})
            tool = registry.get(call.name)
            try:
                if tool is None:
                    raise ValueError(f"unknown tool {call.name!r}")
                output, ok = tool.handler(args), True
            except Exception as exc:  # noqa: BLE001 -- reported back to the model
                output, ok = {"error": str(exc)[:300]}, False
            run.calls.append(ToolCallRecord(name=call.name, args=args, ok=ok, result=output))
            _log(f"{call.name}({str(args)[:120]}) -> {'ok' if ok else output['error'][:120]}")
            reply_parts.append(types.Part(function_response=types.FunctionResponse(
                id=call.id, name=call.name, response=output,
            )))
        contents.append(types.Content(role="user", parts=reply_parts))

    run.hit_round_limit = True
    _log(f"stopped after {max_rounds} rounds")
    return run
