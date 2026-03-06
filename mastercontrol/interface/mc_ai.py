#!/usr/bin/env python3
"""Interactive AI-style interface for MasterControl."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from mastercontrol.core.mastercontrold import MasterControlD, OperatorRequest
    from mastercontrol.core.path_selector import VALID_PATH, VALID_RISK
    from mastercontrol.llm.ollama_adapter import OllamaAdapter, OllamaAdapterError
except ImportError:  # pragma: no cover
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from mastercontrol.core.mastercontrold import MasterControlD, OperatorRequest  # type: ignore
    from mastercontrol.core.path_selector import VALID_PATH, VALID_RISK  # type: ignore
    from mastercontrol.llm.ollama_adapter import OllamaAdapter, OllamaAdapterError  # type: ignore


VALID_MODES = {"confirm", "plan", "dry-run", "execute"}
DEFAULT_LLM_MODEL = "qwen3.5:4b"
DEFAULT_LLM_TIMEOUT_S = 45
LOCAL_OLLAMA_BIN = Path.home() / ".local/ollama-latest/bin/ollama"
LOCAL_OLLAMA_HOST = "127.0.0.1:11435"


@dataclass
class InterfaceState:
    operator_name: str = "Irving"
    risk_level: str = "medium"
    path_mode: str = "auto"
    mode: str = "confirm"
    incident: bool = False
    llm_enabled: bool = True
    llm_model: str = DEFAULT_LLM_MODEL
    llm_timeout_s: int = DEFAULT_LLM_TIMEOUT_S
    ollama_bin: str = "ollama"


def parse_directive(line: str) -> tuple[str, list[str]] | None:
    raw = (line or "").strip()
    if not raw.startswith("/"):
        return None
    try:
        parts = shlex.split(raw[1:])
    except ValueError:
        return ("invalid", [])
    if not parts:
        return ("help", [])
    return (parts[0].lower(), parts[1:])


def apply_directive(state: InterfaceState, command: str, args: list[str]) -> tuple[str, bool]:
    if command in {"quit", "exit"}:
        return ("Encerrando interface.", True)
    if command == "help":
        return (
            "Comandos: /help, /status, /risk <low|medium|high|critical>, "
            "/path <auto|fast|deep|fast_with_confirm>, /mode <confirm|plan|dry-run|execute>, "
            "/incident <on|off>, /operator <nome>, /llm <on|off|status>, /model <nome>, "
            "/raw <comando natural>, /quit",
            False,
        )
    if command == "status":
        return (
            "Estado: "
            f"operator={state.operator_name}, risk={state.risk_level}, path={state.path_mode}, "
            f"mode={state.mode}, incident={state.incident}, llm={state.llm_enabled}, "
            f"model={state.llm_model}",
            False,
        )
    if command == "risk":
        if len(args) != 1 or args[0] not in VALID_RISK:
            return ("Uso: /risk <low|medium|high|critical>", False)
        state.risk_level = args[0]
        return (f"Risco padrao atualizado para '{state.risk_level}'.", False)
    if command == "path":
        allowed = {"auto"} | VALID_PATH
        if len(args) != 1 or args[0] not in allowed:
            return ("Uso: /path <auto|fast|deep|fast_with_confirm>", False)
        state.path_mode = args[0]
        return (f"Path padrao atualizado para '{state.path_mode}'.", False)
    if command == "mode":
        if len(args) != 1 or args[0] not in VALID_MODES:
            return ("Uso: /mode <confirm|plan|dry-run|execute>", False)
        state.mode = args[0]
        return (f"Modo de interacao atualizado para '{state.mode}'.", False)
    if command == "incident":
        if len(args) != 1 or args[0] not in {"on", "off"}:
            return ("Uso: /incident <on|off>", False)
        state.incident = args[0] == "on"
        return (f"Flag incident atualizada para '{state.incident}'.", False)
    if command == "operator":
        if not args:
            return ("Uso: /operator <nome>", False)
        state.operator_name = " ".join(args).strip()
        return (f"Operador atualizado para '{state.operator_name}'.", False)
    if command == "llm":
        if len(args) != 1 or args[0] not in {"on", "off", "status"}:
            return ("Uso: /llm <on|off|status>", False)
        if args[0] == "status":
            return (
                f"LLM: enabled={state.llm_enabled}, model={state.llm_model}, timeout={state.llm_timeout_s}s.",
                False,
            )
        state.llm_enabled = args[0] == "on"
        return (f"LLM {'ativado' if state.llm_enabled else 'desativado'}.", False)
    if command == "model":
        if len(args) != 1:
            return ("Uso: /model <nome>", False)
        state.llm_model = args[0].strip()
        return (f"Modelo LLM atualizado para '{state.llm_model}'.", False)
    return (f"Comando desconhecido: /{command}. Use /help.", False)


def _format_result(result: dict[str, Any]) -> str:
    mapped = result.get("mapped_action")
    action_id = mapped["action_id"] if mapped else "none"
    action_risk = mapped["action_risk"] if mapped else "-"
    lines = [
        "",
        f"[request_id] {result.get('request_id', '')}",
        f"[path] {result['path']['path']} ({result['path']['source']}) conf={result['path']['confidence']:.2f}",
        f"[intent] {result['tone']['intent_cluster']} ({result['tone']['intent_source']})",
        f"[action] {action_id} risk={action_risk}",
        f"[outcome] {result['execution']['outcome']}",
    ]
    return "\n".join(lines)


class MasterControlInterface:
    def __init__(self, state: InterfaceState, profile_path: Path | None = None) -> None:
        self.state = state
        self.daemon = MasterControlD(profile_path)
        self.adapter: OllamaAdapter | None = None
        self._llm_error_reported = False
        self._sync_adapter()

    def _sync_adapter(self) -> None:
        if not self.state.llm_enabled:
            self.adapter = None
            return
        if self.adapter is not None and self.adapter.model == self.state.llm_model:
            return
        self.adapter = OllamaAdapter(
            model=self.state.llm_model,
            ollama_bin=self.state.ollama_bin,
            timeout_s=self.state.llm_timeout_s,
        )

    def _prepare_intent(self, text: str, use_llm: bool = True) -> str | None:
        raw = (text or "").strip()
        if not raw:
            return None
        if not use_llm or not self.state.llm_enabled:
            return raw

        self._sync_adapter()
        if self.adapter is None:
            return raw

        try:
            interpreted = self.adapter.interpret(raw, operator_name=self.state.operator_name)
        except OllamaAdapterError as exc:
            if not self._llm_error_reported:
                print(f"[ai] LLM indisponivel ({exc}). Fallback para fluxo local.")
                self._llm_error_reported = True
            return raw

        self._llm_error_reported = False
        if interpreted.route == "chat":
            if interpreted.chat_reply:
                print(f"[ai] {interpreted.chat_reply}")
            else:
                print("[ai] Posso ajudar com comandos operacionais quando voce quiser.")
            return None

        normalized = interpreted.intent.strip() if interpreted.intent else raw
        if normalized != raw:
            print(f"[ai] Intencao normalizada: {normalized}")
        return normalized

    def run_intent(self, intent: str, execute: bool, dry_run: bool) -> dict[str, Any]:
        req = OperatorRequest(
            operator_name=self.state.operator_name,
            intent=intent,
            risk_level=self.state.risk_level,
            incident=self.state.incident,
            requested_path=self.state.path_mode,
            execute=execute,
            dry_run=dry_run,
            approve=execute,
            allow_high_risk=execute,
            request_id="",
            simulate_failure=False,
        )
        return self.daemon.handle(req)

    def _confirm_execution(self, mapped_action: dict[str, Any]) -> str:
        action_id = str(mapped_action.get("action_id", "unknown"))
        action_risk = str(mapped_action.get("action_risk", "unknown"))
        prompt = (
            f"Acao mapeada '{action_id}' (risk={action_risk}). "
            "Escolha [n]ao / [d]ry-run / [e]xecutar: "
        )
        while True:
            answer = input(prompt).strip().lower()
            if answer in {"n", "d", "e"}:
                return answer
            print("Opcao invalida. Use n, d ou e.")

    @staticmethod
    def _require_high_risk_confirmation(mapped_action: dict[str, Any]) -> bool:
        action_risk = str(mapped_action.get("action_risk", "unknown"))
        if action_risk not in {"high", "critical"}:
            return True
        phrase = input("Acao de alto risco. Digite EXECUTAR para confirmar: ").strip()
        return phrase == "EXECUTAR"

    def handle_intent(self, intent: str, use_llm: bool = True) -> None:
        prepared = self._prepare_intent(intent, use_llm=use_llm)
        if prepared is None:
            return

        initial = self.run_intent(intent=prepared, execute=False, dry_run=False)
        print(initial["message"])
        print(_format_result(initial))

        mapped = initial.get("mapped_action")
        if not mapped:
            return

        if self.state.mode == "plan":
            return

        choice = "n"
        if self.state.mode == "dry-run":
            choice = "d"
        elif self.state.mode == "execute":
            choice = "e"
        else:
            choice = self._confirm_execution(mapped)

        if choice == "n":
            return
        if choice == "e" and not self._require_high_risk_confirmation(mapped):
            print("Execucao cancelada.")
            return

        run = self.run_intent(
            intent=prepared,
            execute=True,
            dry_run=(choice == "d"),
        )
        print(run["message"])
        print(_format_result(run))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mc-ai",
        description="Interactive AI-style interface for MasterControl",
    )
    p.add_argument("--profile", default=None, help="Path to soul profile YAML")
    p.add_argument("--operator-name", default="Irving")
    p.add_argument("--risk-level", default="medium", choices=sorted(VALID_RISK))
    p.add_argument("--path", default="auto", choices=["auto"] + sorted(VALID_PATH))
    p.add_argument("--mode", default="confirm", choices=sorted(VALID_MODES))
    p.add_argument("--incident", action="store_true")
    p.add_argument("--no-llm", action="store_true", help="Disable Ollama intent assistant")
    p.add_argument("--llm-model", default=DEFAULT_LLM_MODEL, help="Ollama model to use in interface")
    p.add_argument("--llm-timeout", type=int, default=DEFAULT_LLM_TIMEOUT_S, help="LLM timeout in seconds")
    p.add_argument("--ollama-bin", default="ollama", help="Path/name of ollama binary")
    p.add_argument("--once", default="", help="Run a single intent and exit")
    return p


def _resolve_ollama_bin(ollama_bin: str) -> str:
    binary = (ollama_bin or "ollama").strip() or "ollama"
    if binary != "ollama":
        return binary
    if LOCAL_OLLAMA_BIN.exists() and os.access(LOCAL_OLLAMA_BIN, os.X_OK):
        os.environ.setdefault("OLLAMA_HOST", LOCAL_OLLAMA_HOST)
        return str(LOCAL_OLLAMA_BIN)
    return binary


def repl(interface: MasterControlInterface) -> int:
    print("MasterControl IA Interface")
    llm_status = "on" if interface.state.llm_enabled else "off"
    print(
        f"Digite o comando natural ou /help para comandos de controle. LLM={llm_status} ({interface.state.llm_model})."
    )
    while True:
        try:
            line = input("mc-ai> ").strip()
        except EOFError:
            print("\nEncerrando interface.")
            return 0
        except KeyboardInterrupt:
            print("\nEncerrando interface.")
            return 0

        if not line:
            continue

        parsed = parse_directive(line)
        if parsed is not None:
            cmd, args = parsed
            if cmd == "raw":
                if not args:
                    print("Uso: /raw <comando natural>")
                else:
                    interface.handle_intent(" ".join(args), use_llm=False)
                continue
            message, should_exit = apply_directive(interface.state, cmd, args)
            print(message)
            if cmd in {"llm", "model"}:
                interface._sync_adapter()
            if should_exit:
                return 0
            continue

        interface.handle_intent(line)


def main() -> int:
    args = build_parser().parse_args()
    ollama_bin = _resolve_ollama_bin(args.ollama_bin)
    state = InterfaceState(
        operator_name=args.operator_name,
        risk_level=args.risk_level,
        path_mode=args.path,
        mode=args.mode,
        incident=bool(args.incident),
        llm_enabled=not bool(args.no_llm),
        llm_model=args.llm_model,
        llm_timeout_s=max(args.llm_timeout, 5),
        ollama_bin=ollama_bin,
    )
    interface = MasterControlInterface(
        state=state,
        profile_path=Path(args.profile) if args.profile else None,
    )

    if args.once:
        interface.handle_intent(args.once)
        return 0
    return repl(interface)


if __name__ == "__main__":
    raise SystemExit(main())
