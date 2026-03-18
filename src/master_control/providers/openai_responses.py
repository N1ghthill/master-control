from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from master_control.agent.observations import format_observation_freshness
from master_control.agent.planner import (
    PLANNING_DECISION_KINDS_BY_STATE,
    PLANNING_DECISION_STATES,
    ExecutionPlan,
    PlanningDecision,
    PlanStep,
)
from master_control.config import Settings
from master_control.providers.base import (
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    SynthesisRequest,
)
from master_control.tools.base import ToolSpec

OPENAI_PLAN_FUNCTION_NAME = "submit_plan"
OPENAI_USER_AGENT = "master-control/0.1.0a1"
DEFAULT_MAX_OUTPUT_TOKENS = 1200
DEFAULT_SYNTHESIS_MAX_OUTPUT_TOKENS = 700
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
        decision_payload = arguments.get("decision")
        if (
            not isinstance(message, str)
            or not isinstance(intent, str)
            or not isinstance(steps_payload, list)
        ):
            raise ProviderError("OpenAI provider returned a malformed plan payload.")
        decision = self._build_decision(decision_payload, steps_payload)

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
            decision=decision,
            metadata=metadata,
        )

    def synthesize(self, request: SynthesisRequest) -> ProviderResponse:
        if not self.api_key:
            raise ProviderError("OPENAI_API_KEY is not set for the OpenAI provider.")

        payload = self._build_synthesis_payload(request)
        headers = self._build_headers()
        endpoint = f"{self.base_url}/responses"
        response = self.transport(endpoint, payload, headers, self.timeout_s)

        try:
            body = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise ProviderError("OpenAI provider returned invalid JSON.") from exc

        message = self._extract_output_text(body)
        request_id = response.headers.get("x-request-id")
        metadata = {
            "model": body.get("model", self.model),
            "request_id": request_id,
            "usage": body.get("usage"),
            "purpose": "response_synthesis",
        }
        return ProviderResponse(
            message=message,
            plan=None,
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

    def _build_synthesis_payload(self, request: SynthesisRequest) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model,
            "input": self._build_synthesis_input_messages(request),
            "instructions": self._build_synthesis_instructions(),
            "store": self.store,
            "max_output_tokens": DEFAULT_SYNTHESIS_MAX_OUTPUT_TOKENS,
            "text": {"verbosity": "low"},
            "metadata": {
                "application": "master-control",
                "purpose": "response_synthesis",
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

    def _build_synthesis_input_messages(
        self,
        request: SynthesisRequest,
    ) -> list[dict[str, object]]:
        sections = [
            "Original user request:",
            request.user_message,
        ]
        if request.planning_message.strip():
            sections.extend(
                [
                    "Latest planning message:",
                    request.planning_message,
                ]
            )
        if request.execution_observations:
            sections.extend(
                [
                    "Execution observations:",
                    *[f"- {item}" for item in request.execution_observations],
                ]
            )
        if request.rendered_results:
            sections.extend(
                [
                    "Rendered tool results:",
                    *[f"- {item}" for item in request.rendered_results],
                ]
            )
        return [
            {
                "role": "user",
                "content": "\n".join(sections),
            }
        ]

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
            "Always set decision.state to exactly one of: needs_tools, complete, blocked.",
            "Always set decision.kind to a valid subtype for that state.",
            "For needs_tools use one of: inspection_request, diagnostic_step, refresh_required.",
            "For complete use: evidence_sufficient.",
            "For blocked use one of: unsupported_request, missing_safe_tool.",
            "Use needs_tools only when you are returning one or more tool steps.",
            "Use complete when the current context already supports the final answer and no more tools are needed.",
            "Use blocked when the request cannot be satisfied safely with the available tools.",
            "For live host inspection requests, do not answer from memory alone. Use the matching read-only tool first unless current-turn observations already provide the evidence.",
            "Write the message in the same language as the user.",
            "When previous session context is provided in the input, use it to resolve safe follow-up requests.",
            "You may receive current-turn execution observations in the extra instructions. Use them to continue the same request without repeating completed steps.",
            "If the current-turn observations are already enough, return decision.state=complete and an empty steps array.",
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

    def _build_synthesis_instructions(self) -> str:
        return "\n".join(
            [
                "You are the response synthesis layer for Master Control, a Linux agent with controlled execution.",
                "Write a concise operator-facing answer in the same language as the user.",
                "Use only the supplied execution observations and rendered tool results.",
                "Do not invent values, states, or actions that are not present in the evidence.",
                "If a tool requires confirmation, make it clear that the action has not run yet.",
                "If a tool failed, state that clearly and avoid over-claiming.",
                "Prefer one or two short paragraphs. Use bullets only when the result is inherently list-shaped.",
            ]
        )

    def _build_plan_function_schema(
        self, available_tools: tuple[ToolSpec, ...]
    ) -> dict[str, object]:
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
                    "decision": {
                        "type": "object",
                        "additionalProperties": False,
                        "description": "Explicit planner decision for this turn.",
                        "properties": {
                            "state": {
                                "type": "string",
                                "enum": list(PLANNING_DECISION_STATES),
                            },
                            "kind": {
                                "type": "string",
                                "enum": sorted(
                                    {
                                        kind
                                        for kinds in PLANNING_DECISION_KINDS_BY_STATE.values()
                                        for kind in kinds
                                    }
                                ),
                            },
                            "reason": {
                                "type": "string",
                                "description": "Short reason for continuing, completing, or blocking.",
                            },
                        },
                        "required": ["state", "kind", "reason"],
                    },
                    "steps": {
                        "type": "array",
                        "description": "Ordered tool plan. Must be non-empty only when decision.state=needs_tools.",
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
                "required": ["message", "intent", "decision", "steps"],
            },
        }

    def _extract_function_call(self, body: dict[str, object]) -> dict[str, Any]:
        output = body.get("output")
        if not isinstance(output, list):
            raise ProviderError("OpenAI provider response is missing output items.")

        for item in output:
            if not isinstance(item, dict):
                continue
            if (
                item.get("type") == "function_call"
                and item.get("name") == OPENAI_PLAN_FUNCTION_NAME
            ):
                return item

        raise ProviderError("OpenAI provider did not return the submit_plan function call.")

    def _extract_output_text(self, body: dict[str, object]) -> str:
        output_text = body.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        output = body.get("output")
        if not isinstance(output, list):
            raise ProviderError("OpenAI provider response is missing output items.")

        chunks: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())

        if not chunks:
            raise ProviderError("OpenAI provider did not return synthesized output text.")
        return "\n".join(chunks)

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
            if (
                not isinstance(tool_name, str)
                or not isinstance(rationale, str)
                or not isinstance(arguments, dict)
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

    def _build_decision(
        self,
        raw_decision: object,
        steps_payload: list[object],
    ) -> PlanningDecision:
        if not isinstance(raw_decision, dict):
            raise ProviderError("OpenAI provider returned a malformed planning decision.")
        state = raw_decision.get("state")
        kind = raw_decision.get("kind")
        reason = raw_decision.get("reason")
        if not isinstance(state, str) or not isinstance(kind, str) or not isinstance(reason, str):
            raise ProviderError("OpenAI provider returned an invalid planning decision.")
        try:
            decision = PlanningDecision(state=state, kind=kind, reason=reason)
        except ValueError as exc:
            raise ProviderError(str(exc)) from exc

        has_steps = bool(steps_payload)
        if decision.state == "needs_tools" and not has_steps:
            raise ProviderError("OpenAI provider declared needs_tools without any steps.")
        if decision.state != "needs_tools" and has_steps:
            raise ProviderError("OpenAI provider returned steps for a non-needs_tools decision.")
        return decision

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
