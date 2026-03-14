#!/usr/bin/env python3
"""Curses-based terminal UI for MasterControl."""

from __future__ import annotations

import argparse
import contextlib
import curses
import io
import os
import queue
import sys
import threading
import textwrap
import traceback
from pathlib import Path
from typing import Any

try:
    from mastercontrol.interface.mc_ai import (
        DEFAULT_LLM_MODEL,
        DEFAULT_LLM_TIMEOUT_S,
        InterfaceState,
        MasterControlInterface,
        _format_result,
        _resolve_ollama_bin,
        apply_directive,
        build_directive_intent,
        directive_usage,
        parse_directive,
    )
    from mastercontrol.interface.flow_orchestrator import FlowOrchestrator, PendingChoice, PendingHighRisk
    from mastercontrol.core.path_selector import VALID_PATH, VALID_RISK
except ImportError:  # pragma: no cover
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from mastercontrol.interface.mc_ai import (  # type: ignore
        DEFAULT_LLM_MODEL,
        DEFAULT_LLM_TIMEOUT_S,
        InterfaceState,
        MasterControlInterface,
        _format_result,
        _resolve_ollama_bin,
        apply_directive,
        build_directive_intent,
        directive_usage,
        parse_directive,
    )
    from mastercontrol.interface.flow_orchestrator import FlowOrchestrator, PendingChoice, PendingHighRisk  # type: ignore
    from mastercontrol.core.path_selector import VALID_PATH, VALID_RISK  # type: ignore


VALID_MODES = {"confirm", "plan", "dry-run", "execute"}


def _add_clipped(stdscr: Any, y: int, x: int, text: str, attr: int = 0) -> None:
    max_y, max_x = stdscr.getmaxyx()
    if y < 0 or y >= max_y or x >= max_x:
        return
    clipped = text[: max(0, max_x - x - 1)]
    if not clipped:
        return
    try:
        stdscr.addstr(y, x, clipped, attr)
    except curses.error:
        return


def _safe_curs_set(value: int) -> None:
    try:
        curses.curs_set(value)
    except curses.error:
        return


class TerminalUI:
    SPINNER_FRAMES = ("|", "/", "-", "\\")

    def __init__(self, interface: MasterControlInterface, *, warmup_on_start: bool) -> None:
        self.interface = interface
        self.warmup_on_start = warmup_on_start
        self.running = True
        self.input_buffer = ""
        self.logs: list[str] = []
        self.flow = FlowOrchestrator(self.interface.run_intent, self.interface._is_high_risk_action)
        self.pending_choice: PendingChoice | None = None
        self.pending_high_risk: PendingHighRisk | None = None
        self._events: queue.Queue[Any] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._busy_label = ""
        self._spinner_index = 0
        self._incident_rows: list[dict[str, Any]] = []
        self._incident_detail: dict[str, Any] | None = None
        self._incident_selected = 0
        self._incident_error = ""

    def _log(self, text: str) -> None:
        for line in (text or "").splitlines() or [""]:
            self.logs.append(line.rstrip())

    def _log_block(self, title: str, body: str) -> None:
        self._log(title)
        for line in body.splitlines():
            self._log(f"  {line}")

    def _capture_stdout(self, fn: Any, *args: Any, **kwargs: Any) -> tuple[Any, list[str]]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = fn(*args, **kwargs)
        lines = [line.rstrip() for line in buf.getvalue().splitlines() if line.strip()]
        return result, lines

    def _log_captured(self, lines: list[str]) -> None:
        for line in lines:
            self._log(line)

    def _post(self, event: Any) -> None:
        self._events.put(event)

    def _drain_events(self) -> None:
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            if callable(event):
                event()

    def _is_busy(self) -> bool:
        worker = self._worker
        return bool(worker is not None and worker.is_alive())

    def _mark_idle(self) -> None:
        self._busy_label = ""
        self._worker = None

    def _start_job(self, label: str, job_fn: Any) -> bool:
        if self._is_busy():
            self._log("[sys] Processando requisicao anterior. Aguarde.")
            return False

        self._busy_label = label

        def _runner() -> None:
            try:
                job_fn()
            except Exception as exc:  # noqa: BLE001
                tb_last = traceback.format_exc().strip().splitlines()[-1]
                self._post(
                    lambda exc=exc, tb_last=tb_last: self._log(
                        f"[sys] Erro interno na UI: {exc} ({tb_last})."
                    )
                )
            finally:
                self._post(self._mark_idle)

        self._worker = threading.Thread(target=_runner, daemon=True)
        self._worker.start()
        return True

    def _status_line(self) -> str:
        state = self.interface.state
        llm = "on" if state.llm_enabled else "off"
        base = (
            f"mode={state.mode} risk={state.risk_level} path={state.path_mode} "
            f"incident={state.incident} llm={llm} model={state.llm_model}"
        )
        alert_line = ""
        status_fn = getattr(self.interface, "active_alert_status_line", None)
        if callable(status_fn):
            alert_line = str(status_fn())
        return f"{base} {alert_line}".strip()

    def _selected_incident_id(self) -> str:
        if not self._incident_rows:
            return ""
        index = min(max(self._incident_selected, 0), len(self._incident_rows) - 1)
        return str(self._incident_rows[index].get("incident_id", "")).strip().lower()

    def _apply_incident_snapshot(self, snapshot: dict[str, Any] | None) -> None:
        payload = snapshot or {}
        rows = [dict(row) for row in list(payload.get("incidents", []))]
        detail = payload.get("detail")
        selected_id = str(payload.get("selected_incident_id", "")).strip().lower()
        self._incident_rows = rows
        self._incident_detail = dict(detail) if isinstance(detail, dict) else None
        self._incident_error = ""

        if not rows:
            self._incident_selected = 0
            self._incident_detail = None
            return

        if selected_id:
            for idx, row in enumerate(rows):
                if str(row.get("incident_id", "")).strip().lower() == selected_id:
                    self._incident_selected = idx
                    break
            else:
                self._incident_selected = min(self._incident_selected, len(rows) - 1)
        else:
            self._incident_selected = min(self._incident_selected, len(rows) - 1)

    def _load_incident_snapshot(
        self,
        *,
        force: bool = False,
        incident_id: str = "",
    ) -> dict[str, Any]:
        snapshot_fn = getattr(self.interface, "active_incident_snapshot", None)
        if not callable(snapshot_fn):
            return {"incidents": [], "detail": None, "selected_incident_id": ""}
        return dict(snapshot_fn(force=force, incident_id=incident_id))

    def _refresh_incident_snapshot(
        self,
        *,
        force: bool = False,
        incident_id: str = "",
    ) -> None:
        try:
            snapshot = self._load_incident_snapshot(force=force, incident_id=incident_id)
        except Exception as exc:  # noqa: BLE001
            self._incident_rows = []
            self._incident_detail = None
            self._incident_selected = 0
            self._incident_error = str(exc)
            return
        self._apply_incident_snapshot(snapshot)

    def _job_refresh_incidents(
        self,
        *,
        force: bool = False,
        incident_id: str = "",
    ) -> None:
        try:
            snapshot = self._load_incident_snapshot(force=force, incident_id=incident_id)
        except Exception as exc:  # noqa: BLE001
            self._post(lambda exc=exc: self._set_incident_error(str(exc)))
            return
        self._post(lambda snapshot=snapshot: self._apply_incident_snapshot(snapshot))

    def _set_incident_error(self, error: str) -> None:
        self._incident_rows = []
        self._incident_detail = None
        self._incident_selected = 0
        self._incident_error = error

    def _move_incident_selection(self, delta: int) -> bool:
        if not self._incident_rows:
            return False
        next_index = min(max(self._incident_selected + delta, 0), len(self._incident_rows) - 1)
        if next_index == self._incident_selected:
            return False
        self._incident_selected = next_index
        self._refresh_incident_snapshot(incident_id=self._selected_incident_id())
        return True

    @staticmethod
    def _wrap_panel_text(prefix: str, text: str, width: int) -> list[str]:
        safe_width = max(12, width)
        wrapped = textwrap.wrap(
            f"{prefix}{text}".strip(),
            width=safe_width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
            drop_whitespace=False,
        )
        return wrapped or [prefix.strip()]

    def _incident_detail_lines(self, width: int, height: int) -> list[str]:
        if height <= 0:
            return []
        if self._incident_error:
            return self._wrap_panel_text("Erro: ", self._incident_error, width)[:height]
        detail = self._incident_detail
        if detail is None:
            if self._incident_rows:
                return ["Detalhe indisponivel."][:height]
            return ["Sem incidentes ativos."][:height]

        lines = [
            "Detalhe",
            f"id: {detail.get('incident_id', '')}",
            (
                "estado: "
                f"{detail.get('status', 'unknown')} "
                f"sev={detail.get('severity', 'unknown')} "
                f"cat={detail.get('category', 'unknown')}"
            ),
        ]
        fingerprint = str(detail.get("fingerprint", "")).strip()
        if fingerprint:
            lines.extend(self._wrap_panel_text("fingerprint: ", fingerprint, width))
        units = [str(item) for item in detail.get("correlated_units", ()) if str(item).strip()]
        if units:
            lines.extend(self._wrap_panel_text("unidades: ", ", ".join(units), width))
        latest_summary = str(detail.get("latest_summary", "")).strip()
        if latest_summary:
            lines.extend(self._wrap_panel_text("resumo: ", latest_summary, width))
        alerts = list(detail.get("alerts", []))
        activity = list(detail.get("activity", []))
        lines.append(f"alerts={len(alerts)} activity={len(activity)}")
        if activity:
            latest = dict(activity[0])
            action_line = f"{latest.get('action_id', '')} {latest.get('status_from', '')}->{latest.get('status_to', '')}".strip()
            if action_line:
                lines.extend(self._wrap_panel_text("ultima: ", action_line, width))
            resolution = str(latest.get("resolution_summary", "")).strip()
            if resolution:
                lines.extend(self._wrap_panel_text("acao: ", resolution, width))
        return lines[:height]

    def _build_incident_panel_lines(self, width: int, height: int) -> list[str]:
        if width <= 0 or height <= 0:
            return []
        lines = [f"Incidentes ativos ({len(self._incident_rows)})"]
        remaining = height - 1
        if remaining <= 0:
            return lines[:height]

        list_height = min(max(2, min(4, remaining // 3 + 1)), remaining)
        if not self._incident_rows:
            lines.extend(["Sem incidentes ativos."][:list_height])
        else:
            for idx in range(list_height):
                if idx >= len(self._incident_rows):
                    lines.append("")
                    continue
                row = self._incident_rows[idx]
                marker = ">" if idx == self._incident_selected else " "
                incident_id = str(row.get("incident_id", "")).strip()
                severity = str(row.get("severity", "")).strip() or "unknown"
                status = str(row.get("status", "")).strip() or "unknown"
                fingerprint = str(row.get("fingerprint", "")).strip()
                label = f"{marker} {status}/{severity} {incident_id} {fingerprint}".strip()
                lines.append(label[:width])

        detail_height = max(0, height - len(lines))
        if detail_height > 0:
            detail_lines = self._incident_detail_lines(width, detail_height)
            lines.extend(detail_lines[:detail_height])
        if len(lines) < height:
            lines.extend("" for _ in range(height - len(lines)))
        return [line[:width] for line in lines[:height]]

    def _wrapped_logs(self, width: int) -> list[str]:
        wrapped: list[str] = []
        safe_width = max(1, width)
        for line in self.logs:
            text = (line or "").expandtabs(2)
            if not text:
                wrapped.append("")
                continue
            wrapped.extend(
                textwrap.wrap(
                    text,
                    width=safe_width,
                    break_long_words=True,
                    break_on_hyphens=False,
                    replace_whitespace=False,
                    drop_whitespace=False,
                )
            )
        return wrapped

    @staticmethod
    def _layout(
        *,
        max_x: int,
        body_height: int,
    ) -> dict[str, int | str] | None:
        if max_x >= 120 and body_height >= 10:
            panel_width = min(48, max(34, max_x // 3))
            return {
                "mode": "side",
                "panel_width": panel_width,
                "log_width": max(1, max_x - panel_width - 1),
            }
        if body_height >= 12:
            panel_height = min(9, max(6, body_height // 3))
            return {
                "mode": "bottom",
                "panel_height": panel_height,
            }
        return None

    def _render(self, stdscr: Any) -> None:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()
        body_top = 3
        if self._is_busy():
            spinner = self.SPINNER_FRAMES[self._spinner_index % len(self.SPINNER_FRAMES)]
            self._spinner_index += 1
            _add_clipped(stdscr, 3, 0, f"[{spinner}] processando: {self._busy_label}", curses.A_DIM)
            body_top = 4
        body_bottom = max_y - 2
        body_height = max(1, body_bottom - body_top)
        layout = self._layout(max_x=max_x, body_height=body_height)

        _add_clipped(stdscr, 0, 0, "MasterControl Terminal UI", curses.A_BOLD)
        _add_clipped(stdscr, 1, 0, self._status_line(), curses.A_DIM)
        _add_clipped(
            stdscr,
            2,
            0,
            "Commands: /help /status /mode /risk /incidents /incident-show /raw /quit | Up/Down: incidentes",
            curses.A_DIM,
        )

        if layout is not None and layout["mode"] == "side":
            log_width = int(layout["log_width"])
            panel_width = int(layout["panel_width"])
            panel_x = log_width + 1
            visible = self._wrapped_logs(log_width - 1)[-body_height:]
            for idx, line in enumerate(visible):
                _add_clipped(stdscr, body_top + idx, 0, line)
            for y in range(body_top, body_bottom):
                _add_clipped(stdscr, y, log_width, "|", curses.A_DIM)
            panel_lines = self._build_incident_panel_lines(panel_width - 1, body_height)
            for idx, line in enumerate(panel_lines):
                _add_clipped(stdscr, body_top + idx, panel_x, line)
        elif layout is not None and layout["mode"] == "bottom":
            panel_height = int(layout["panel_height"])
            log_height = max(1, body_height - panel_height - 1)
            visible = self._wrapped_logs(max_x - 1)[-log_height:]
            for idx, line in enumerate(visible):
                _add_clipped(stdscr, body_top + idx, 0, line)
            separator_y = body_top + log_height
            _add_clipped(stdscr, separator_y, 0, "-" * max(1, max_x - 1), curses.A_DIM)
            panel_lines = self._build_incident_panel_lines(max_x - 1, max(1, body_bottom - separator_y - 1))
            for idx, line in enumerate(panel_lines):
                _add_clipped(stdscr, separator_y + 1 + idx, 0, line)
        else:
            visible = self._wrapped_logs(max_x - 1)[-body_height:]
            for idx, line in enumerate(visible):
                _add_clipped(stdscr, body_top + idx, 0, line)

        _add_clipped(stdscr, max_y - 2, 0, "-" * max(1, max_x - 1), curses.A_DIM)
        prompt = "mc> "
        buffer_view = self.input_buffer
        space = max(1, max_x - len(prompt) - 1)
        if len(buffer_view) > space:
            buffer_view = buffer_view[-space:]
        _add_clipped(stdscr, max_y - 1, 0, prompt + buffer_view)
        _safe_curs_set(1)
        try:
            stdscr.move(max_y - 1, min(max_x - 1, len(prompt + buffer_view)))
        except curses.error:
            pass
        stdscr.refresh()

    def _log_result(self, result: dict[str, Any]) -> None:
        self._log_block("[mc] message", result.get("message", "").rstrip())
        self._log(_format_result(result).strip())

    def _job_warmup(self, *, force: bool = False) -> None:
        _out, lines = self._capture_stdout(self.interface.warmup_llm, announce=True, force=force)
        if lines:
            self._post(lambda lines=lines: self._log_captured(lines))
        self._job_refresh_incidents(force=True, incident_id=self._selected_incident_id())

    def _apply_flow_outcome(self, *, results: list[dict[str, Any]], pending_choice: PendingChoice | None, pending_high_risk: PendingHighRisk | None) -> None:
        for result in results:
            self._log_result(result)
        self.pending_choice = pending_choice
        self.pending_high_risk = pending_high_risk
        if pending_choice is not None:
            action_id = str(pending_choice.mapped_action.get("action_id", "unknown"))
            action_risk = str(pending_choice.mapped_action.get("action_risk", "unknown"))
            self._log(f"[sys] Acao '{action_id}' (risk={action_risk}). Escolha n/d/e.")
        if pending_high_risk is not None:
            self._log("[sys] Acao de alto risco. Digite EXECUTAR para confirmar.")

    def _job_apply_outcome(self, outcome: Any) -> None:
        self._post(
            lambda outcome=outcome: self._apply_flow_outcome(
                results=list(outcome.results),
                pending_choice=outcome.pending_choice,
                pending_high_risk=outcome.pending_high_risk,
            )
        )
        self._job_refresh_incidents(force=True, incident_id=self._selected_incident_id())

    def _job_handle_intent(self, line: str, *, use_llm: bool = True) -> None:
        prepared, captured = self._capture_stdout(self.interface._prepare_intent, line, use_llm)
        if captured:
            self._post(lambda captured=captured: self._log_captured(captured))
        if prepared is None:
            return

        outcome = self.flow.begin(prepared, mode=self.interface.state.mode)
        self._job_apply_outcome(outcome)

    def _handle_pending_choice(self, line: str) -> bool:
        pending = self.pending_choice
        if pending is None:
            return False
        choice = line.strip().lower()
        if choice not in {"n", "d", "e"}:
            self._log("[sys] Confirmacao invalida. Use n, d ou e.")
            return True

        self.pending_choice = None
        if choice == "n":
            self._log("[sys] Execucao cancelada.")
            return True
        if choice == "e" and self.interface._is_high_risk_action(pending.mapped_action):
            outcome = self.flow.choose(pending, choice=choice)
            self._apply_flow_outcome(
                results=list(outcome.results),
                pending_choice=outcome.pending_choice,
                pending_high_risk=outcome.pending_high_risk,
            )
            return True

        label = "execucao dry-run" if choice == "d" else "execucao"
        self._start_job(
            label,
            lambda pending=pending, choice=choice: self._job_apply_outcome(
                self.flow.choose(pending, choice=choice)
            ),
        )
        return True

    def _handle_pending_high_risk(self, line: str) -> bool:
        pending = self.pending_high_risk
        if pending is None:
            return False
        self.pending_high_risk = None
        confirmed = line.strip() == "EXECUTAR"
        if not confirmed:
            self._log("[sys] Execucao de alto risco cancelada.")
            return True
        self._start_job(
            "execucao alto risco",
            lambda pending=pending: self._job_apply_outcome(
                self.flow.confirm_high_risk(pending, confirmed=True)
            ),
        )
        return True

    def _handle_directive(self, line: str) -> bool:
        parsed = parse_directive(line)
        if parsed is None:
            return False
        command, args = parsed

        if command == "raw":
            if not args:
                self._log("[sys] Uso: /raw <comando natural>")
                return True
            line_raw = " ".join(args)
            self._start_job("intent(raw)", lambda line_raw=line_raw: self._job_handle_intent(line_raw, use_llm=False))
            return True
        directive_intent = build_directive_intent(command, args)
        if directive_intent is not None:
            self._start_job(
                f"intent({command})",
                lambda directive_intent=directive_intent: self._job_handle_intent(directive_intent, use_llm=False),
            )
            return True
        directive_help = directive_usage(command)
        if directive_help is not None:
            self._log(f"[sys] {directive_help}")
            return True

        message, should_exit = apply_directive(self.interface.state, command, args)
        self._log(f"[sys] {message}")
        if command in {"llm", "model"}:
            self.interface._sync_adapter()
        if command == "model" and self.interface.state.llm_enabled:
            self._start_job("warm-up modelo", lambda: self._job_warmup(force=True))
        if command == "llm" and args and args[0] == "on":
            self._start_job("warm-up llm", self._job_warmup)
        if should_exit:
            self.running = False
        return True

    def _submit(self) -> None:
        line = self.input_buffer.strip()
        self.input_buffer = ""
        if not line:
            return
        self._log(f"> {line}")

        if self._is_busy():
            parsed = parse_directive(line)
            if parsed is None or parsed[0] not in {"quit", "exit"}:
                self._log("[sys] Processando requisicao anterior. Aguarde.")
                return

        if self._handle_pending_high_risk(line):
            return
        if self._handle_pending_choice(line):
            return
        if self._handle_directive(line):
            return
        self._start_job("processando intent", lambda line=line: self._job_handle_intent(line, use_llm=True))

    def run(self, stdscr: Any) -> int:
        stdscr.keypad(True)
        stdscr.timeout(200)
        _safe_curs_set(1)

        self._log("[sys] MasterControl UI iniciada. Digite /help para comandos.")
        self._refresh_incident_snapshot(force=True)
        if self.warmup_on_start and self.interface.state.llm_enabled:
            self._log("[sys] Iniciando warm-up do modelo...")
            self._start_job("warm-up inicial", self._job_warmup)

        while self.running:
            self._drain_events()
            self._render(stdscr)
            try:
                key = stdscr.get_wch()
            except curses.error:
                continue
            if key == curses.KEY_RESIZE:
                continue
            if isinstance(key, str):
                if key in {"\n", "\r"}:
                    self._submit()
                    continue
                if key in {"\b", "\x7f"}:
                    self.input_buffer = self.input_buffer[:-1]
                    continue
                if key == "\x03":
                    self.running = False
                    continue
                if key.isprintable():
                    self.input_buffer += key
                    continue
            if key == curses.KEY_UP and not self.input_buffer:
                self._move_incident_selection(-1)
                continue
            if key == curses.KEY_DOWN and not self.input_buffer:
                self._move_incident_selection(1)
                continue
            if key in {curses.KEY_BACKSPACE, curses.KEY_DC}:
                self.input_buffer = self.input_buffer[:-1]
                continue
        return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mc-tui",
        description="Curses terminal UI for MasterControl",
    )
    p.add_argument("--profile", default=None, help="Path to soul profile YAML")
    p.add_argument("--operator-name", default="Irving")
    p.add_argument("--risk-level", default="medium", choices=sorted(VALID_RISK))
    p.add_argument("--path", default="auto", choices=["auto"] + sorted(VALID_PATH))
    p.add_argument("--mode", default="confirm", choices=sorted(VALID_MODES))
    p.add_argument("--incident", action="store_true")
    p.add_argument("--no-llm", action="store_true", help="Disable Ollama intent assistant")
    p.add_argument("--no-llm-warmup", action="store_true", help="Skip startup warm-up probe")
    p.add_argument("--llm-model", default=DEFAULT_LLM_MODEL, help="Ollama model to use in interface")
    p.add_argument("--llm-timeout", type=int, default=DEFAULT_LLM_TIMEOUT_S, help="LLM timeout in seconds")
    p.add_argument("--ollama-bin", default="ollama", help="Path/name of ollama binary")
    return p


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
    ui = TerminalUI(interface, warmup_on_start=not bool(args.no_llm_warmup))
    return curses.wrapper(ui.run)


if __name__ == "__main__":
    raise SystemExit(main())
