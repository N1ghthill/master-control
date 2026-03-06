#!/usr/bin/env python3
"""Local LLM adapter backed by Ollama."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMInterpretation:
    route: str
    intent: str
    chat_reply: str
    confidence: float
    raw: str


class OllamaAdapterError(RuntimeError):
    """Raised when Ollama execution fails."""


class OllamaAdapter:
    """Thin, safe adapter for local model calls through Ollama."""

    ROUTES = {"intent", "chat"}

    def __init__(
        self,
        model: str = "qwen2.5:7b",
        ollama_bin: str = "ollama",
        timeout_s: int = 25,
    ) -> None:
        self.model = (model or "qwen2.5:7b").strip()
        self.ollama_bin = (ollama_bin or "ollama").strip()
        self.timeout_s = max(int(timeout_s), 5)
        self.disable_thinking = True

    def set_model(self, model: str) -> None:
        self.model = (model or self.model).strip()

    def interpret(self, user_text: str, operator_name: str) -> LLMInterpretation:
        text = (user_text or "").strip()
        if not text:
            return LLMInterpretation(
                route="chat",
                intent="",
                chat_reply="",
                confidence=1.0,
                raw="",
            )

        prompt = self._build_prompt(user_text=text, operator_name=operator_name)
        raw = self._run(prompt)
        parsed = self._parse(raw=raw, fallback_intent=text)
        return parsed

    def _run(self, prompt: str) -> str:
        cmd = self._build_cmd(prompt=prompt, with_thinking_flags=self.disable_thinking)
        try:
            proc = self._invoke(cmd)
        except FileNotFoundError as exc:
            raise OllamaAdapterError(f"binary '{self.ollama_bin}' nao encontrado") from exc
        except subprocess.TimeoutExpired as exc:
            raise OllamaAdapterError(
                f"timeout no modelo '{self.model}' apos {self.timeout_s}s"
            ) from exc

        if proc.returncode != 0 and self._is_thinking_flag_error(proc.stderr):
            # Older runtimes may not support --think/--hidethinking.
            proc = self._invoke(self._build_cmd(prompt=prompt, with_thinking_flags=False))

        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            detail = stderr or stdout or f"returncode={proc.returncode}"
            raise OllamaAdapterError(detail)

        out = (proc.stdout or "").strip()
        if not out:
            raise OllamaAdapterError("resposta vazia do modelo")
        return out

    def _build_cmd(self, prompt: str, with_thinking_flags: bool) -> list[str]:
        cmd = [self.ollama_bin, "run", self.model]
        if with_thinking_flags:
            cmd.extend(["--think=false", "--hidethinking"])
        cmd.append(prompt)
        return cmd

    def _invoke(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            check=False,
            timeout=self.timeout_s,
        )

    @staticmethod
    def _is_thinking_flag_error(stderr: str) -> bool:
        text = (stderr or "").lower()
        return "unknown flag" in text and ("--think" in text or "--hidethinking" in text)

    def _parse(self, raw: str, fallback_intent: str) -> LLMInterpretation:
        payload = self._load_json(raw)
        if not isinstance(payload, dict):
            return LLMInterpretation(
                route="intent",
                intent=fallback_intent,
                chat_reply="",
                confidence=0.0,
                raw=raw,
            )

        route = str(payload.get("route", "intent")).strip().lower()
        if route not in self.ROUTES:
            route = "intent"

        intent = str(payload.get("intent", "")).strip()
        if route == "intent" and not intent:
            intent = fallback_intent

        chat_reply = str(payload.get("chat_reply", "")).strip()
        if route == "chat" and not chat_reply:
            chat_reply = "Posso ajudar com operacoes do sistema quando voce quiser."

        confidence = self._parse_confidence(payload.get("confidence", 0.5))
        return LLMInterpretation(
            route=route,
            intent=intent,
            chat_reply=chat_reply,
            confidence=confidence,
            raw=raw,
        )

    @staticmethod
    def _parse_confidence(value: object) -> float:
        try:
            conf = float(value)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            return 0.5
        return max(0.0, min(conf, 1.0))

    @staticmethod
    def _load_json(raw: str) -> dict[str, object] | None:
        text = (raw or "").strip()
        if not text:
            return None

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None

        candidate = text[start : end + 1]
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _build_prompt(user_text: str, operator_name: str) -> str:
        return (
            "Voce eh um adaptador de intencao para o MasterControl. "
            "Responda APENAS JSON valido com as chaves: route, intent, chat_reply, confidence. "
            "route deve ser 'intent' ou 'chat'. "
            "Use 'intent' quando o operador pedir diagnostico/acao no Linux. "
            "Use 'chat' para conversa, explicacao ou pergunta geral sem acao operacional. "
            "Para route='intent', escreva intent curta e objetiva em portugues, sem shell inline. "
            "Para route='chat', chat_reply deve ser resposta curta em portugues e intent pode ficar vazia. "
            "confidence deve ser numero entre 0 e 1. "
            f"Operador: {operator_name}. "
            f"Entrada: {user_text}"
        )
