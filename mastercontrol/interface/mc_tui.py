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
        parse_directive,
    )
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
        parse_directive,
    )
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
        self.pending_choice: dict[str, Any] | None = None
        self.pending_high_risk: dict[str, Any] | None = None
        self._events: queue.Queue[Any] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._busy_label = ""
        self._spinner_index = 0

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
        return (
            f"mode={state.mode} risk={state.risk_level} path={state.path_mode} "
            f"incident={state.incident} llm={llm} model={state.llm_model}"
        )

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

        _add_clipped(stdscr, 0, 0, "MasterControl Terminal UI", curses.A_BOLD)
        _add_clipped(stdscr, 1, 0, self._status_line(), curses.A_DIM)
        _add_clipped(stdscr, 2, 0, "Commands: /help /status /mode /risk /llm /model /raw /quit", curses.A_DIM)

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

    def _job_execute(self, prepared: str, *, dry_run: bool) -> None:
        out = self.interface.run_intent(prepared, execute=True, dry_run=dry_run)
        self._post(lambda out=out: self._log_result(out))

    def _job_handle_intent(self, line: str, *, use_llm: bool = True) -> None:
        prepared, captured = self._capture_stdout(self.interface._prepare_intent, line, use_llm)
        if captured:
            self._post(lambda captured=captured: self._log_captured(captured))
        if prepared is None:
            return

        initial = self.interface.run_intent(prepared, execute=False, dry_run=False)
        self._post(lambda initial=initial: self._log_result(initial))

        mapped = initial.get("mapped_action")
        if not mapped:
            return
        mapped = dict(mapped)
        mode = self.interface.state.mode

        if mode == "plan":
            return
        if mode == "dry-run":
            execute_out = self.interface.run_intent(prepared, execute=True, dry_run=True)
            self._post(lambda execute_out=execute_out: self._log_result(execute_out))
            return
        if mode == "execute":
            risk = str(mapped.get("action_risk", "unknown"))
            if risk in {"high", "critical"}:
                self._post(
                    lambda prepared=prepared: self._set_pending_high_risk(prepared)
                )
                return
            execute_out = self.interface.run_intent(prepared, execute=True, dry_run=False)
            self._post(lambda execute_out=execute_out: self._log_result(execute_out))
            return

        action_id = str(mapped.get("action_id", "unknown"))
        action_risk = str(mapped.get("action_risk", "unknown"))
        self._post(
            lambda prepared=prepared, mapped=mapped, action_id=action_id, action_risk=action_risk: self._set_pending_choice(
                prepared=prepared,
                mapped=mapped,
                action_id=action_id,
                action_risk=action_risk,
            )
        )

    def _set_pending_choice(
        self,
        *,
        prepared: str,
        mapped: dict[str, Any],
        action_id: str,
        action_risk: str,
    ) -> None:
        self.pending_choice = {"prepared": prepared, "mapped": dict(mapped)}
        self._log(f"[sys] Acao '{action_id}' (risk={action_risk}). Escolha n/d/e.")

    def _set_pending_high_risk(self, prepared: str) -> None:
        self.pending_high_risk = {"prepared": prepared}
        self._log("[sys] Acao de alto risco. Digite EXECUTAR para confirmar.")

    def _handle_pending_choice(self, line: str) -> bool:
        pending = self.pending_choice
        if pending is None:
            return False
        choice = line.strip().lower()
        if choice not in {"n", "d", "e"}:
            self._log("[sys] Confirmacao invalida. Use n, d ou e.")
            return True

        prepared = str(pending["prepared"])
        mapped = dict(pending["mapped"])
        self.pending_choice = None
        if choice == "n":
            self._log("[sys] Execucao cancelada.")
            return True
        if choice == "d":
            self._start_job("execucao dry-run", lambda prepared=prepared: self._job_execute(prepared, dry_run=True))
            return True

        risk = str(mapped.get("action_risk", "unknown"))
        if risk in {"high", "critical"}:
            self._set_pending_high_risk(prepared)
            return True
        self._start_job("execucao", lambda prepared=prepared: self._job_execute(prepared, dry_run=False))
        return True

    def _handle_pending_high_risk(self, line: str) -> bool:
        pending = self.pending_high_risk
        if pending is None:
            return False
        self.pending_high_risk = None
        if line.strip() != "EXECUTAR":
            self._log("[sys] Execucao de alto risco cancelada.")
            return True
        prepared = str(pending["prepared"])
        self._start_job("execucao alto risco", lambda prepared=prepared: self._job_execute(prepared, dry_run=False))
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
