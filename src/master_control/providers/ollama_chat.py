from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from master_control.config import Settings
from master_control.core.observations import format_observation_freshness
from master_control.providers.base import (
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    SynthesisRequest,
    validate_http_url,
)
from master_control.shared.planning import (
    PLANNING_DECISION_KINDS_BY_STATE,
    PLANNING_DECISION_STATES,
    ExecutionPlan,
    PlanningDecision,
    PlanStep,
)
from master_control.tools.base import ToolSpec

OLLAMA_USER_AGENT = "master-control/0.1.0a2"
DEFAULT_OLLAMA_OPTIONS = {
    "temperature": 0,
}
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


class OllamaChatProvider:
    name = "ollama"

    def __init__(
        self,
        settings: Settings,
        *,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model
        self.timeout_s = settings.ollama_timeout_s
        self.keep_alive = settings.ollama_keep_alive
        self.api_key = settings.ollama_api_key
        self.transport = transport or self._default_transport

    def diagnostics(self) -> dict[str, object]:
        return {
            "name": self.name,
            "configured": True,
            "base_url": self.base_url,
            "model": self.model,
            "keep_alive": self.keep_alive,
        }

    def plan(self, request: ProviderRequest) -> ProviderResponse:
        payload = self._build_payload(request)
        headers = self._build_headers()
        endpoint = self._build_endpoint("/chat")
        response = self.transport(endpoint, payload, headers, self.timeout_s)

        try:
            body = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise ProviderError("Ollama provider returned invalid JSON.") from exc

        message_payload = body.get("message")
        if not isinstance(message_payload, dict):
            raise ProviderError("Ollama provider response is missing the assistant message.")
        content = message_payload.get("content")
        if not isinstance(content, str):
            raise ProviderError("Ollama provider returned non-text content.")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderError("Ollama provider returned invalid structured plan JSON.") from exc

        message = parsed.get("message")
        intent = parsed.get("intent")
        steps_payload = parsed.get("steps")
        decision_payload = parsed.get("decision")
        if (
            not isinstance(message, str)
            or not isinstance(intent, str)
            or not isinstance(steps_payload, list)
        ):
            raise ProviderError("Ollama provider returned a malformed plan payload.")
        decision = self._build_decision(decision_payload, steps_payload)

        metadata = {
            "model": body.get("model", self.model),
            "done": body.get("done"),
            "done_reason": body.get("done_reason"),
            "eval_count": body.get("eval_count"),
            "prompt_eval_count": body.get("prompt_eval_count"),
        }
        return ProviderResponse(
            message=message,
            plan=self._build_plan(intent, steps_payload),
            response_id=None,
            decision=decision,
            metadata=metadata,
        )

    def synthesize(self, request: SynthesisRequest) -> ProviderResponse:
        payload = self._build_synthesis_payload(request)
        headers = self._build_headers()
        endpoint = self._build_endpoint("/chat")
        response = self.transport(endpoint, payload, headers, self.timeout_s)

        try:
            body = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise ProviderError("Ollama provider returned invalid JSON.") from exc

        message_payload = body.get("message")
        if not isinstance(message_payload, dict):
            raise ProviderError("Ollama provider response is missing the assistant message.")
        content = message_payload.get("content")
        if not isinstance(content, str):
            raise ProviderError("Ollama provider returned non-text content.")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderError("Ollama provider returned invalid synthesis JSON.") from exc

        message = parsed.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ProviderError("Ollama provider returned an empty synthesis message.")

        metadata = {
            "model": body.get("model", self.model),
            "done": body.get("done"),
            "done_reason": body.get("done_reason"),
            "eval_count": body.get("eval_count"),
            "prompt_eval_count": body.get("prompt_eval_count"),
            "purpose": "response_synthesis",
        }
        return ProviderResponse(
            message=message.strip(),
            plan=None,
            response_id=None,
            metadata=metadata,
        )

    def _build_payload(self, request: ProviderRequest) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": self._build_messages(request),
            "stream": False,
            "format": self._build_response_schema(request.available_tools),
            "options": dict(DEFAULT_OLLAMA_OPTIONS),
        }
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive
        return payload

    def _build_synthesis_payload(self, request: SynthesisRequest) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": self._build_synthesis_instructions(),
                },
                {
                    "role": "user",
                    "content": self._build_synthesis_user_message(request),
                },
            ],
            "stream": False,
            "format": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "message": {
                        "type": "string",
                    }
                },
                "required": ["message"],
            },
            "options": dict(DEFAULT_OLLAMA_OPTIONS),
        }
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive
        return payload

    def _build_messages(self, request: ProviderRequest) -> list[dict[str, str]]:
        messages = [
            {
                "role": "system",
                "content": self._build_instructions(request),
            }
        ]
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
            "Content-Type": "application/json",
            "User-Agent": OLLAMA_USER_AGENT,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
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
            "Return a JSON object that matches the provided schema.",
            "Interpret informal operator phrasing when it clearly maps to an existing safe workflow.",
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
            "When structured session context includes recent observations for the same target, you may answer comparative follow-ups about whether it changed, improved, or worsened.",
            "For focused log follow-ups, compress recurring journal patterns such as restart or crash loops, dependency failures, environment failures, timeouts, permission failures, and recovery signals instead of echoing long raw excerpts.",
            "For config comparison follow-ups, only compare tracked managed files from session context and prefer read_config_file when a fresh comparable read is missing.",
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
        session_context_payload = (
            request.session_context.as_dict() if request.session_context is not None else {}
        )
        if session_context_payload:
            sections.extend(
                [
                    "Structured session context:",
                    json.dumps(
                        session_context_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
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
                "Return a JSON object with a single `message` field.",
                "Write a concise operator-facing answer in the same language as the user.",
                "Use only the supplied execution observations and rendered tool results.",
                "Do not invent values, states, or actions that are not present in the evidence.",
                "If an action still needs confirmation, state that clearly.",
                "If a tool failed, state that clearly.",
            ]
        )

    def _build_synthesis_user_message(self, request: SynthesisRequest) -> str:
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
        return "\n".join(sections)

    def _build_response_schema(self, available_tools: tuple[ToolSpec, ...]) -> dict[str, object]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "message": {
                    "type": "string",
                },
                "intent": {
                    "type": "string",
                },
                "decision": {
                    "type": "object",
                    "additionalProperties": False,
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
                        },
                    },
                    "required": ["state", "kind", "reason"],
                },
                "steps": {
                    "type": "array",
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
                            },
                            "arguments": {
                                "type": "object",
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
        }

    def _build_plan(self, intent: str, steps_payload: list[object]) -> ExecutionPlan | None:
        if not steps_payload:
            return None

        steps: list[PlanStep] = []
        for raw_step in steps_payload:
            if not isinstance(raw_step, dict):
                raise ProviderError("Ollama provider returned a malformed step.")
            tool_name = raw_step.get("tool_name")
            rationale = raw_step.get("rationale")
            arguments = raw_step.get("arguments")
            if (
                not isinstance(tool_name, str)
                or not isinstance(rationale, str)
                or not isinstance(arguments, dict)
            ):
                raise ProviderError("Ollama provider returned an invalid step shape.")
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
            raise ProviderError("Ollama provider returned a malformed planning decision.")
        state = raw_decision.get("state")
        kind = raw_decision.get("kind")
        reason = raw_decision.get("reason")
        if not isinstance(state, str) or not isinstance(kind, str) or not isinstance(reason, str):
            raise ProviderError("Ollama provider returned an invalid planning decision.")
        try:
            decision = PlanningDecision(state=state, kind=kind, reason=reason)
        except ValueError as exc:
            raise ProviderError(str(exc)) from exc

        has_steps = bool(steps_payload)
        if decision.state == "needs_tools" and not has_steps:
            raise ProviderError("Ollama provider declared needs_tools without any steps.")
        if decision.state != "needs_tools" and has_steps:
            raise ProviderError("Ollama provider returned steps for a non-needs_tools decision.")
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
            with urllib.request.urlopen(request, timeout=timeout_s) as response:  # nosec B310
                body = response.read().decode("utf-8")
                response_headers = {key.lower(): value for key, value in response.headers.items()}
                return TransportResponse(
                    status_code=response.status,
                    body=body,
                    headers=response_headers,
                )
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(
                f"Ollama API error {exc.code}: {self._extract_error_message(error_body)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Ollama API request failed: {exc.reason}") from exc

    def _build_endpoint(self, suffix: str) -> str:
        endpoint = f"{self.base_url}{suffix}"
        try:
            return validate_http_url(endpoint, label="Ollama endpoint")
        except ValueError as exc:
            raise ProviderError(str(exc)) from exc

    def _extract_error_message(self, body: str) -> str:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return body.strip() or "unknown error"

        if isinstance(parsed, dict):
            if isinstance(parsed.get("error"), str):
                return parsed["error"]
        return body.strip() or "unknown error"
