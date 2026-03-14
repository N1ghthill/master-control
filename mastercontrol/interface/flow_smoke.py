#!/usr/bin/env python3
"""Smoke runner for real interactive MasterControl flows."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REQUEST_ID_RE = re.compile(r"^\[request_id\]\s+(\S+)\s*$", flags=re.MULTILINE)


@dataclass(frozen=True)
class InteractiveStep:
    wait_for: str
    send: str


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    command: tuple[str, ...]
    expected_substrings: tuple[str, ...]
    interactive_steps: tuple[InteractiveStep, ...] = ()
    require_reused_request_id: bool = False


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _entrypoint() -> Path:
    return _repo_root() / "scripts" / "mc-ai"


def _extract_request_ids(output: str) -> list[str]:
    return REQUEST_ID_RE.findall(output or "")


def _normalize_output(output: str) -> str:
    text = (output or "").replace("\r\n", "\n").replace("\r", "\n")
    return text


def _run_once(command: tuple[str, ...], timeout_s: float) -> tuple[int, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.run(
        list(command),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_s,
        env=env,
    )
    output = _normalize_output((proc.stdout or "") + (proc.stderr or ""))
    return proc.returncode, output


def _run_interactive(command: tuple[str, ...], steps: tuple[InteractiveStep, ...], timeout_s: float) -> tuple[int, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    scripted_input = "".join(step.send for step in steps)
    proc = subprocess.run(
        list(command),
        input=scripted_input,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_s,
        env=env,
    )
    output = _normalize_output((proc.stdout or "") + (proc.stderr or ""))
    return proc.returncode, output


def _assert_output(scenario: Scenario, returncode: int, output: str) -> None:
    if returncode != 0:
        raise AssertionError(f"scenario '{scenario.name}' exited with code {returncode}")
    for step in scenario.interactive_steps:
        if step.wait_for not in output:
            raise AssertionError(f"scenario '{scenario.name}' missing interactive prompt: {step.wait_for!r}")
    for expected in scenario.expected_substrings:
        if expected not in output:
            raise AssertionError(f"scenario '{scenario.name}' missing expected text: {expected!r}")
    if scenario.require_reused_request_id:
        request_ids = _extract_request_ids(output)
        if len(request_ids) < 2:
            raise AssertionError(
                f"scenario '{scenario.name}' expected at least two request ids, found {request_ids}"
            )
        if request_ids[0] != request_ids[1]:
            raise AssertionError(
                f"scenario '{scenario.name}' expected request id reuse, got {request_ids[:2]}"
            )


def _scenario_catalog() -> dict[str, Scenario]:
    entrypoint = str(_entrypoint())
    return {
        "plan-route-once": Scenario(
            name="plan-route-once",
            description="Validate non-interactive plan flow through the real AI wrapper.",
            command=(
                entrypoint,
                "--no-llm",
                "--mode",
                "plan",
                "--once",
                "mostre a rota default",
            ),
            expected_substrings=(
                "[path]",
                "[action] network.diagnose.route_default",
            ),
        ),
        "confirm-route-execute": Scenario(
            name="confirm-route-execute",
            description="Run a real REPL confirm flow with direct safe execution and request_id reuse.",
            command=(
                entrypoint,
                "--no-llm",
                "--mode",
                "confirm",
            ),
            interactive_steps=(
                InteractiveStep(wait_for="mc-ai> ", send="mostre a rota default\n"),
                InteractiveStep(wait_for="Escolha [n]ao / [d]ry-run / [e]xecutar:", send="e\n"),
                InteractiveStep(wait_for="mc-ai> ", send="/quit\n"),
            ),
            expected_substrings=(
                "[action] network.diagnose.route_default",
                "Action 'network.diagnose.route_default' executed successfully",
            ),
            require_reused_request_id=True,
        ),
        "execute-step-up-cancel": Scenario(
            name="execute-step-up-cancel",
            description="Exercise real high-risk step-up gating without allowing the final mutation.",
            command=(
                entrypoint,
                "--no-llm",
                "--mode",
                "execute",
            ),
            interactive_steps=(
                InteractiveStep(wait_for="mc-ai> ", send="restart unbound.service\n"),
                InteractiveStep(wait_for="Acao de alto risco. Digite EXECUTAR para confirmar:", send="cancelar\n"),
                InteractiveStep(wait_for="mc-ai> ", send="/quit\n"),
            ),
            expected_substrings=(
                "Blocked stepped-up action 'service.systemctl.restart'.",
                "Execucao cancelada.",
            ),
        ),
    }


def _run_scenario(scenario: Scenario, timeout_s: float) -> str:
    if scenario.interactive_steps:
        returncode, output = _run_interactive(scenario.command, scenario.interactive_steps, timeout_s)
    else:
        returncode, output = _run_once(scenario.command, timeout_s)
    _assert_output(scenario, returncode, output)
    return output


def _print_result(name: str, description: str, command: tuple[str, ...], output: str) -> None:
    request_ids = _extract_request_ids(output)
    request_note = f" request_ids={','.join(request_ids[:2])}" if request_ids else ""
    print(f"[ok] {name}{request_note}")
    print(f"  {description}")
    print(f"  cmd: {shlex.join(command)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mc-flow-smoke",
        description="Run real smoke scenarios against the interactive MasterControl flow",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenarios",
        default=[],
        help="Scenario name to run (default: all scenarios)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=12.0,
        help="Per-scenario timeout in seconds (default: 12)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available scenarios and exit",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print the full captured transcript for each scenario",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    catalog = _scenario_catalog()

    if args.list:
        for scenario in catalog.values():
            print(f"{scenario.name}: {scenario.description}")
        return 0

    selected = args.scenarios or list(catalog.keys())
    for name in selected:
        if name not in catalog:
            print(f"[error] unknown scenario: {name}", file=sys.stderr)
            return 2

    for name in selected:
        scenario = catalog[name]
        output = _run_scenario(scenario, timeout_s=max(float(args.timeout), 1.0))
        _print_result(scenario.name, scenario.description, scenario.command, output)
        if args.verbose:
            print("  transcript:")
            for line in output.splitlines():
                print(f"    {line}")
    print(f"[summary] {len(selected)} scenario(s) passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
