#!/usr/bin/env python3
"""Interactive AI-style interface for MasterControl."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import platform
import re
import shlex
import sys
import time
import unicodedata
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
DEFAULT_LLM_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
DEFAULT_LLM_TIMEOUT_S = 25
LOCAL_OLLAMA_BIN = Path.home() / ".local/ollama-latest/bin/ollama"
LOCAL_OLLAMA_HOST = "127.0.0.1:11435"
IDENTITY_HINTS = (
    "quem e voce",
    "quem voce e",
    "who are you",
    "qual seu nome",
    "qual e seu nome",
    "quem e vc",
)
LOCATION_HINTS = (
    "onde voce esta",
    "onde vc esta",
    "where are you",
    "em qual host",
    "em qual servidor",
    "onde estamos",
)
RUNTIME_CONTEXT_HINTS = (
    "o que esta acontecendo agora",
    "qual o contexto atual",
    "estado atual do sistema",
)
DATE_HINTS = (
    "que dia e hoje",
    "qual a data de hoje",
    "data de hoje",
    "what day is today",
    "today date",
)
YEAR_REMAINING_HINTS = (
    "quantos dias faltam para acabar o ano",
    "quantos dias faltam para o fim do ano",
    "dias restantes para acabar o ano",
    "dias restam para acabar esse ano",
    "days left in the year",
)
SYSTEM_CONFIG_HINTS = (
    "configuracoes do meu computador",
    "configuracoes do computador",
    "config do meu computador",
    "especificacoes do meu computador",
    "hardware do meu computador",
    "configuracao da maquina",
)
EXTERNAL_IDENTITY_TERMS = (
    "alibaba",
    "chatgpt",
    "openai",
    "qwen",
    "gemini",
    "claude",
)
OPERATIONAL_ACTION_HINTS = {
    "restart",
    "reiniciar",
    "start",
    "iniciar",
    "stop",
    "parar",
    "reload",
    "install",
    "instalar",
    "remove",
    "remover",
    "desinstalar",
    "purge",
    "update",
    "upgrade",
    "ping",
    "resolve",
    "resolver",
    "lookup",
    "route",
    "rota",
    "gateway",
    "flush",
    "limpar",
}
OPERATIONAL_OBJECT_HINTS = {
    "dns",
    "unbound",
    "cache",
    "service",
    "servico",
    "apt",
    "apt-get",
    "package",
    "pacote",
    "default",
}
EXPLANATION_PREFIXES = (
    "o que",
    "oque",
    "what is",
    "como funciona",
    "me explica",
    "explique",
    "qual a diferenca",
)
DNS_SCOPE_HINTS = {"bogus", "negative", "nxdomain", "all", "todo", "tudo"}
EXPLICIT_COMMAND_RE = re.compile(
    r"\b(?:"
    r"apt(?:-get)?\s+(?:update|install|remove|purge)"
    r"|systemctl\s+(?:restart|start|stop)"
    r"|ping\s+[a-z0-9_.:-]+"
    r"|(?:nslookup|getent|dig|host)\s+[a-z0-9_.:-]+"
    r")\b"
)
IP_RE = re.compile(
    r"\b((?:25[0-5]|2[0-4][0-9]|[01]?[0-9]?[0-9])"
    r"(?:\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9]?[0-9])){3})\b"
)
DOMAIN_RE = re.compile(r"\b[a-z0-9][a-z0-9.-]*\.[a-z]{2,}\b")
SERVICE_RE = re.compile(r"\b([a-z0-9@_.:-]+\.service)\b")
APT_PACKAGE_RE = re.compile(
    r"\bapt(?:-get)?\s+(?:install|remove|purge)\s+(?:-y\s+)?(?:--\s+)?([a-z0-9][a-z0-9+.-]*)\b"
)
PACKAGE_TAIL_RE = re.compile(
    r"\b(?:install|instalar|remove|remover|desinstalar|purge)\b(?P<tail>.*)$"
)
PACKAGE_STOPWORDS = {"package", "pacote", "apt", "apt-get", "de", "o", "a", "no", "na"}
OP_KIND_GROUPS: tuple[tuple[str, set[str]], ...] = (
    ("remove", {"remove", "remover", "desinstalar", "purge"}),
    ("install", {"install", "instalar"}),
    ("update", {"update", "upgrade"}),
    ("restart", {"restart", "reiniciar", "reload"}),
    ("start", {"start", "iniciar"}),
    ("stop", {"stop", "parar"}),
    ("ping", {"ping"}),
    ("resolve", {"resolve", "resolver", "lookup", "nslookup", "dig", "host", "getent"}),
    ("route", {"route", "rota", "gateway", "default"}),
    ("flush", {"flush", "limpar", "cache"}),
)
CANONICAL_TARGET_TOKEN = {"todo": "all", "tudo": "all"}
LLM_WARMUP_PROMPT = "oi"
PT_WEEKDAYS = (
    "segunda-feira",
    "terca-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sabado",
    "domingo",
)
PT_MONTHS = (
    "",
    "janeiro",
    "fevereiro",
    "marco",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


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


def _normalize_text(text: str) -> str:
    raw = (text or "").strip().lower()
    folded = unicodedata.normalize("NFKD", raw)
    plain = "".join(ch for ch in folded if not unicodedata.combining(ch))
    plain = re.sub(r"\s+", " ", plain)
    return plain.strip()


def _tokenize_text(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_.:-]+", _normalize_text(text)))


def _looks_like_explanatory_question(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(normalized.startswith(prefix) for prefix in EXPLANATION_PREFIXES)


def _looks_like_explicit_operational_command(text: str) -> bool:
    normalized = _normalize_text(text)
    return bool(EXPLICIT_COMMAND_RE.search(normalized))


def _looks_like_operational_request(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    if _looks_like_identity_question(normalized) or _looks_like_location_question(normalized):
        return False
    if _looks_like_runtime_context_question(normalized):
        return False
    if _looks_like_explanatory_question(normalized):
        return False
    if _looks_like_explicit_operational_command(normalized):
        return True

    tokens = _tokenize_text(normalized)
    if tokens.intersection(OPERATIONAL_ACTION_HINTS):
        return True
    if tokens.intersection({"mostrar", "mostre", "show", "check", "verifique", "verificar"}):
        return bool(tokens.intersection(OPERATIONAL_OBJECT_HINTS))
    return False


def _extract_operation_kind(text: str) -> str | None:
    tokens = _tokenize_text(text)
    for kind, group in OP_KIND_GROUPS:
        if tokens.intersection(group):
            return kind
    return None


def _extract_package_target(text: str) -> str | None:
    normalized = _normalize_text(text)
    cmd_match = APT_PACKAGE_RE.search(normalized)
    if cmd_match:
        return cmd_match.group(1)

    tail_match = PACKAGE_TAIL_RE.search(normalized)
    if not tail_match:
        return None
    tail = tail_match.group("tail")
    for token in re.findall(r"[a-z0-9+.-]+", tail):
        if token in PACKAGE_STOPWORDS:
            continue
        if re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", token):
            return token
    return None


def _extract_operational_targets(text: str) -> set[str]:
    normalized = _normalize_text(text)
    targets: set[str] = set()

    for match in IP_RE.findall(normalized):
        targets.add(match)
    for match in DOMAIN_RE.findall(normalized):
        targets.add(match)
    for match in SERVICE_RE.findall(normalized):
        targets.add(match)

    package = _extract_package_target(normalized)
    if package:
        targets.add(package)

    tokens = _tokenize_text(normalized)
    for token in tokens.intersection(DNS_SCOPE_HINTS):
        targets.add(CANONICAL_TARGET_TOKEN.get(token, token))
    return targets


def _should_keep_raw_intent(raw: str, normalized: str) -> bool:
    raw_clean = (raw or "").strip()
    normalized_clean = (normalized or "").strip()
    if not raw_clean or raw_clean == normalized_clean:
        return False
    if _looks_like_explicit_operational_command(raw_clean):
        return True
    if not _looks_like_operational_request(raw_clean):
        return False

    raw_op = _extract_operation_kind(raw_clean)
    normalized_op = _extract_operation_kind(normalized_clean)
    if raw_op and normalized_op and raw_op != normalized_op:
        return True
    if raw_op and not normalized_op:
        return True

    raw_targets = _extract_operational_targets(raw_clean)
    normalized_targets = _extract_operational_targets(normalized_clean)
    missing_targets = raw_targets - normalized_targets
    return bool(missing_targets)


def _looks_like_identity_question(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(hint in normalized for hint in IDENTITY_HINTS)


def _looks_like_location_question(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(hint in normalized for hint in LOCATION_HINTS)


def _looks_like_runtime_context_question(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(hint in normalized for hint in RUNTIME_CONTEXT_HINTS)


def _looks_like_date_question(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(hint in normalized for hint in DATE_HINTS)


def _looks_like_year_remaining_question(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(hint in normalized for hint in YEAR_REMAINING_HINTS)


def _looks_like_system_config_question(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(hint in normalized for hint in SYSTEM_CONFIG_HINTS)


def _reply_violates_identity_contract(reply: str) -> bool:
    normalized = _normalize_text(reply)
    if "criado por irving" in normalized or "mastercontrol" in normalized:
        return False
    return any(term in normalized for term in EXTERNAL_IDENTITY_TERMS)


def _read_mem_total_gib() -> str:
    try:
        with open("/proc/meminfo", encoding="utf-8") as fp:
            for line in fp:
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        kb = float(parts[1])
                        gib = kb / (1024.0 * 1024.0)
                        return f"{gib:.1f} GiB"
    except Exception:  # noqa: BLE001
        return "desconhecida"
    return "desconhecida"


def _local_system_summary(context: dict[str, str]) -> str:
    host = context.get("hostname", "unknown-host")
    os_name = context.get("os_pretty", platform.platform())
    kernel = platform.release()
    arch = platform.machine() or "unknown-arch"
    cpu_count = os.cpu_count() or 0
    mem_total = _read_mem_total_gib()
    user = context.get("user", "unknown-user")
    cwd = context.get("cwd", "unknown-cwd")
    return (
        f"Host='{host}', SO='{os_name}', kernel='{kernel}', arquitetura='{arch}', "
        f"CPUs_logicas={cpu_count}, RAM_total~{mem_total}, usuario='{user}', cwd='{cwd}'."
    )


def _guardrailed_chat_reply(
    user_text: str,
    model_reply: str,
    *,
    profile_name: str,
    profile_creator: str,
    profile_role: str,
    context: dict[str, str],
) -> str:
    identity_line = f"Sou o {profile_name}, criado por {profile_creator}, no papel de {profile_role}."

    if _looks_like_identity_question(user_text):
        return identity_line

    if _looks_like_location_question(user_text) or _looks_like_runtime_context_question(user_text):
        host = context.get("hostname", "unknown-host")
        os_name = context.get("os_pretty", "unknown-os")
        user = context.get("user", "unknown-user")
        cwd = context.get("cwd", "unknown-cwd")
        ts_local = context.get("timestamp_local", "unknown-time")
        return (
            f"{identity_line} Estou no host local '{host}' ({os_name}), "
            f"usuario '{user}', cwd '{cwd}', hora_local '{ts_local}'."
        )

    if _looks_like_date_question(user_text):
        now = dt.datetime.now().astimezone()
        weekday = PT_WEEKDAYS[now.weekday()]
        month = PT_MONTHS[now.month]
        return f"{identity_line} Hoje e {weekday}, {now.day:02d} de {month} de {now.year}."

    if _looks_like_year_remaining_question(user_text):
        today = dt.datetime.now().astimezone().date()
        end_of_year = dt.date(today.year, 12, 31)
        remaining = (end_of_year - today).days
        return f"{identity_line} Restam {remaining} dia(s) para acabar {today.year}."

    if _looks_like_system_config_question(user_text):
        return f"{identity_line} {_local_system_summary(context)}"

    reply = (model_reply or "").strip()
    if not reply:
        return "Posso ajudar com comandos operacionais quando voce quiser."
    if _reply_violates_identity_contract(reply):
        return identity_line
    return reply


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
        self._warmed_models: set[str] = set()
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

    def warmup_llm(self, announce: bool = False, force: bool = False) -> None:
        if not self.state.llm_enabled:
            return
        self._sync_adapter()
        if self.adapter is None:
            return

        model = self.state.llm_model
        if not force and model in self._warmed_models:
            return

        started = time.monotonic()
        try:
            self.adapter.interpret(LLM_WARMUP_PROMPT, operator_name=self.state.operator_name)
        except OllamaAdapterError as exc:
            if announce:
                print(
                    f"[ai] Warm-up do modelo '{model}' falhou ({exc}). "
                    "Seguindo com fallback dinamico."
                )
            return

        elapsed_s = time.monotonic() - started
        self._warmed_models.add(model)
        if announce:
            print(f"[ai] Warm-up do modelo '{model}' concluido em {elapsed_s:.1f}s.")

    def _prepare_intent(self, text: str, use_llm: bool = True) -> str | None:
        raw = (text or "").strip()
        if not raw:
            return None
        if not use_llm or not self.state.llm_enabled:
            return raw
        if (
            _looks_like_date_question(raw)
            or _looks_like_year_remaining_question(raw)
            or _looks_like_system_config_question(raw)
        ):
            profile = self.daemon.soul.profile
            runtime_context = self.daemon.runtime_context_snapshot(self.state.operator_name)
            reply = _guardrailed_chat_reply(
                raw,
                "",
                profile_name=profile.name,
                profile_creator=profile.creator,
                profile_role=profile.role,
                context=runtime_context,
            )
            print(f"[ai] {reply}")
            return None
        if _looks_like_explicit_operational_command(raw):
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
            if _looks_like_operational_request(raw):
                print("[ai] Guardrail operacional: mantendo fluxo intent para comando operacional.")
                return raw
            profile = self.daemon.soul.profile
            runtime_context = self.daemon.runtime_context_snapshot(self.state.operator_name)
            reply = _guardrailed_chat_reply(
                raw,
                interpreted.chat_reply,
                profile_name=profile.name,
                profile_creator=profile.creator,
                profile_role=profile.role,
                context=runtime_context,
            )
            print(f"[ai] {reply}")
            return None

        normalized = interpreted.intent.strip() if interpreted.intent else raw
        if _should_keep_raw_intent(raw, normalized):
            print("[ai] Guardrail de contexto: mantendo intent original para preservar alvo operacional.")
            return raw
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
    p.add_argument(
        "--no-llm-warmup",
        action="store_true",
        help="Skip startup warm-up probe for LLM in interactive mode",
    )
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
            if cmd == "model" and interface.state.llm_enabled:
                interface.warmup_llm(announce=True)
            if cmd == "llm" and args and args[0] == "on":
                interface.warmup_llm(announce=True)
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
    if not args.no_llm_warmup:
        interface.warmup_llm(announce=True)
    return repl(interface)


if __name__ == "__main__":
    raise SystemExit(main())
