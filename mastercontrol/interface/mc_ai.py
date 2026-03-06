#!/usr/bin/env python3
"""Interactive AI-style interface for MasterControl."""

from __future__ import annotations

import argparse
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from mastercontrol.core.mastercontrold import MasterControlD, OperatorRequest
    from mastercontrol.core.path_selector import VALID_PATH, VALID_RISK
except ImportError:  # pragma: no cover
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from mastercontrol.core.mastercontrold import MasterControlD, OperatorRequest  # type: ignore
    from mastercontrol.core.path_selector import VALID_PATH, VALID_RISK  # type: ignore


VALID_MODES = {"confirm", "plan", "dry-run", "execute"}


@dataclass
class InterfaceState:
    operator_name: str = "Irving"
    risk_level: str = "medium"
    path_mode: str = "auto"
    mode: str = "confirm"
    incident: bool = False


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
            "/incident <on|off>, /operator <nome>, /quit",
            False,
        )
    if command == "status":
        return (
            "Estado: "
            f"operator={state.operator_name}, risk={state.risk_level}, path={state.path_mode}, "
            f"mode={state.mode}, incident={state.incident}",
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

    def handle_intent(self, intent: str) -> None:
        initial = self.run_intent(intent=intent, execute=False, dry_run=False)
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
            intent=intent,
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
    p.add_argument("--once", default="", help="Run a single intent and exit")
    return p


def repl(interface: MasterControlInterface) -> int:
    print("MasterControl IA Interface")
    print("Digite o comando natural ou /help para comandos de controle.")
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
            message, should_exit = apply_directive(interface.state, cmd, args)
            print(message)
            if should_exit:
                return 0
            continue

        interface.handle_intent(line)


def main() -> int:
    args = build_parser().parse_args()
    state = InterfaceState(
        operator_name=args.operator_name,
        risk_level=args.risk_level,
        path_mode=args.path,
        mode=args.mode,
        incident=bool(args.incident),
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

