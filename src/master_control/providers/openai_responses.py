from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from master_control.agent.planner import ExecutionPlan, PlanStep
from master_control.agent.observations import format_observation_freshness
from master_control.config import Settings
from master_control.providers.base import ProviderError, ProviderRequest, ProviderResponse
from master_control.tools.base import ToolSpec


OPENAI_PLAN_FUNCTION_NAME = "submit_plan"
OPENAI_USER_AGENT = "master-control/0.1.0a1"
DEFAULT_MAX_OUTPUT_TOKENS = 1200
ALLOWED_ARGUMENT_VALUE_SCHEMAS: list[dict[str, str]] = [
    {"type": "string"},
    {"type": "integer"},
    {"type": "number"},
    {"type": "boolean"},
]


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status_code: int
    body: str
    headers: dict[str, str]


Transport = Callable[[str, dict[str, object], dict[str, str], float], TransportResponse]


class OpenAIResponsesProvider:
    name = "openai"

    def __init__(
        self,
        settings: Settings,
        *,
        transport: Transport | None = None,
    ) -> None:
        self.api_key = settings.openai_api_key
        self.base_url = settings.openai_base_url.rstrip("/")
        self.model = settings.openai_model
        self.reasoning_effort = settings.openai_reasoning_effort
        self.timeout_s = settings.openai_timeout_s
        self.store = settings.openai_store
        self.organization = settings.openai_organization
        self.project = settings.openai_project
        self.transport = transport or self._default_transport

    def diagnostics(self) -> dict[str, object]:
        return {
            "name": self.name,
            "configured": bool(self.api_key),
            "base_url": self.base_url,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "store": self.store,
        }

    def plan(self, request: ProviderRequest) -> ProviderResponse:
        if not self.api_key:
            raise ProviderError("OPENAI_API_KEY is not set for the OpenAI provider.")

        payload = self._build_payload(request)
        headers = self._build_headers()
        endpoint = f"{self.base_url}/responses"
        response = self.transport(endpoint, payload, headers, self.timeout_s)

        try:
            body = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise ProviderError("OpenAI provider returned invalid JSON.") from exc

        function_call = self._extract_function_call(body)
        try:
            arguments = json.loads(function_call["arguments"])
        except json.JSONDecodeError as exc:
            raise ProviderError("OpenAI provider returned invalid function arguments.") from exc

        message = arguments.get("message")
        intent = arguments.get("intent")
        steps_payload = arguments.get("steps")
        if not isinstance(message, str) or not isinstance(intent, str) or not isinstance(
            steps_payload, list
        ):
            raise ProviderError("OpenAI provider returned a malformed plan payload.")

        plan = self._build_plan(intent, steps_payload)
        request_id = response.headers.get("x-request-id")
        metadata = {
            "model": body.get("model", self.model),
            "request_id": request_id,
            "usage": body.get("usage"),
        }
        return ProviderResponse(
            message=message,
            plan=plan,
            response_id=body.get("id"),
            metadata=metadata,
        )

    def _build_payload(self, request: ProviderRequest) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model,
            "input": self._build_input_messages(request),
            "instructions": self._build_instructions(request),
            "tools": [self._build_plan_function_schema(request.available_tools)],
            "tool_choice": "required",
            "parallel_tool_calls": False,
            "store": self.store,
            "max_output_tokens": DEFAULT_MAX_OUTPUT_TOKENS,
            "text": {"verbosity": "low"},
            "metadata": {
                "application": "master-control",
                "purpose": "tool_planning",
            },
        }
        if request.previous_response_id:
            payload["previous_response_id"] = request.previous_response_id
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        return payload

    def _build_input_messages(self, request: ProviderRequest) -> list[dict[str, object]]:
        messages: list[dict[str, object]] = []
        if not request.previous_response_id:
            for item in request.conversation_history:
                messages.append(
                    {
                        "role": item.role,
                        "content": item.content,
                    }
                )
        messages.append(
            {
                "role": "user",
                "content": request.user_message,
            }
        )
        return messages

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": OPENAI_USER_AGENT,
        }
        if self.organization:
            headers["OpenAI-Organization"] = self.organization
        if self.project:
            headers["OpenAI-Project"] = self.project
        return headers

    def _build_instructions(self, request: ProviderRequest) -> str:
        tool_lines = []
        for spec in request.available_tools:
            arguments = ", ".join(spec.arguments) if spec.arguments else "no arguments"
            tool_lines.append(
                f"- {spec.name}({arguments}): {spec.description}. risk={spec.risk.value}"
            )

        sections = [
            "You are the planning layer for Master Control, a Linux agent with controlled execution.",
            "Return exactly one function call to submit_plan.",
            "Use only the provided tools. Never invent tools or arguments.",
            "Prefer the smallest sufficient plan.",
            "If the request cannot be satisfied safely with the available tools, return an empty steps array and explain that clearly in message.",
            "Write the message in the same language as the user.",
            "When previous session context is provided in the input, use it to resolve safe follow-up requests.",
            "You may receive current-turn execution observations in the extra instructions. Use them to continue the same request without repeating completed steps.",
            "If the current-turn observations are already enough, return an empty steps array and summarize the findings.",
            "Available tools:",
            *tool_lines,
        ]
        if request.session_summary:
            sections.extend(
                [
                    "Local session summary:",
                    request.session_summary,
                ]
            )
        freshness_block = format_observation_freshness(request.observation_freshness)
        if freshness_block:
            sections.extend(
                [
                    "Observation freshness:",
                    freshness_block,
                    "If a relevant observation is stale, prefer refreshing it with the matching read-only tool before relying on it.",
                ]
            )
        if request.system_prompt:
            sections.append(request.system_prompt)
        return "\n".join(sections)

    def _build_plan_function_schema(self, available_tools: tuple[ToolSpec, ...]) -> dict[str, object]:
        return {
            "type": "function",
            "name": OPENAI_PLAN_FUNCTION_NAME,
            "description": (
                "Return a safe execution plan using only the listed Master Control tools."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Short assistant message in the user's language.",
                    },
                    "intent": {
                        "type": "string",
                        "description": "Short snake_case summary of the request.",
                    },
                    "steps": {
                        "type": "array",
                        "description": "Ordered tool plan. Use an empty array if no safe plan exists.",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "tool_name": {
                                    "type": "string",
                                    "enum": [spec.name for spec in available_tools],
                                },
                                "rationale": {
                                    "type": "string",
                                    "description": "Why this tool is being used.",
                                },
                                "arguments": {
                                    "type": "object",
                                    "description": "Tool arguments as simple key/value pairs.",
                                    "additionalProperties": {
                                        "anyOf": ALLOWED_ARGUMENT_VALUE_SCHEMAS,
                                    },
                                },
                            },
                            "required": ["tool_name", "rationale", "arguments"],
                        },
                    },
                },
                "required": ["message", "intent", "steps"],
            },
        }

    def _extract_function_call(self, body: dict[str, object]) -> dict[str, Any]:
        output = body.get("output")
        if not isinstance(output, list):
            raise ProviderError("OpenAI provider response is missing output items.")

        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "function_call" and item.get("name") == OPENAI_PLAN_FUNCTION_NAME:
                return item

        raise ProviderError("OpenAI provider did not return the submit_plan function call.")

    def _build_plan(self, intent: str, steps_payload: list[object]) -> ExecutionPlan | None:
        if not steps_payload:
            return None

        steps: list[PlanStep] = []
        for raw_step in steps_payload:
            if not isinstance(raw_step, dict):
                raise ProviderError("OpenAI provider returned a malformed step.")
            tool_name = raw_step.get("tool_name")
            rationale = raw_step.get("rationale")
            arguments = raw_step.get("arguments")
            if not isinstance(tool_name, str) or not isinstance(rationale, str) or not isinstance(
                arguments, dict
            ):
                raise ProviderError("OpenAI provider returned an invalid step shape.")
            steps.append(
                PlanStep(
                    tool_name=tool_name,
                    rationale=rationale,
                    arguments=arguments,
                )
            )
        return ExecutionPlan(intent=intent, steps=tuple(steps))

    def _default_transport(
        self,
        url: str,
        payload: dict[str, object],
        headers: dict[str, str],
        timeout_s: float,
    ) -> TransportResponse:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                body = response.read().decode("utf-8")
                response_headers = {key.lower(): value for key, value in response.headers.items()}
                return TransportResponse(
                    status_code=response.status,
                    body=body,
                    headers=response_headers,
                )
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            message = self._extract_error_message(error_body)
            request_id = exc.headers.get("x-request-id")
            request_id_suffix = f" request_id={request_id}" if request_id else ""
            raise ProviderError(
                f"OpenAI API error {exc.code}: {message}.{request_id_suffix}".rstrip(".")
            ) from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"OpenAI API request failed: {exc.reason}") from exc

    def _extract_error_message(self, body: str) -> str:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return body.strip() or "unknown error"

        if isinstance(parsed, dict):
            error = parsed.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                return error["message"]
        return body.strip() or "unknown error"
