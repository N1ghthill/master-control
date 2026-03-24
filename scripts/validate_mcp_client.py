#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class StepResult:
    name: str
    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    parsed: dict[str, object] | None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate mc mcp-serve against the official MCP Inspector CLI and write a report."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path.cwd() / "artifacts" / "mcp-client-validation"),
        help="Directory where the report and command logs will be written.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter used to start mc mcp-serve. Default: current interpreter.",
    )
    parser.add_argument(
        "--npx",
        default="npx",
        help="NPX binary used to run the official MCP Inspector CLI. Default: npx.",
    )
    parser.add_argument(
        "--inspector-package",
        default="@modelcontextprotocol/inspector",
        help="Inspector package used for CLI validation. Default: @modelcontextprotocol/inspector.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the generated report as JSON instead of only the report path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_validation(
        output_dir=Path(args.output_dir),
        python_bin=args.python,
        npx_bin=args.npx,
        inspector_package=args.inspector_package,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(report["report_path"])
    return 0 if report["overall_ok"] else 1


def run_validation(
    *,
    output_dir: Path,
    python_bin: str,
    npx_bin: str,
    inspector_package: str,
) -> dict[str, object]:
    run_id = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    host_slug = _slugify(socket.gethostname())
    run_dir = output_dir.expanduser().resolve() / f"{run_id}-{host_slug}"
    state_dir = run_dir / "state"
    managed_root = state_dir / "managed-configs"
    log_dir = run_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    managed_root.mkdir(parents=True, exist_ok=True)

    config_path = managed_root / "demo.ini"
    config_path.write_text("[main]\nkey=old\n", encoding="utf-8")

    base_env = {
        "MC_STATE_DIR": str(state_dir),
        "MC_DB_PATH": str(state_dir / "mc.sqlite3"),
        "MC_PROVIDER": "heuristic",
        "PYTHONPATH": str(REPO_ROOT / "src"),
    }

    inspector_base = [
        npx_bin,
        "-y",
        inspector_package,
        "--cli",
        "--transport",
        "stdio",
    ]
    for key, value in base_env.items():
        inspector_base.extend(["-e", f"{key}={value}"])
    inspector_base.extend(["--", python_bin, "-m", "master_control", "mcp-serve"])

    steps: list[StepResult] = []
    steps.append(
        _run_step(
            name="tools_list",
            command=[*inspector_base, "--method", "tools/list"],
            cwd=REPO_ROOT,
            log_dir=log_dir,
        )
    )
    steps.append(
        _run_step(
            name="system_info",
            command=[
                *inspector_base,
                "--method",
                "tools/call",
                "--tool-name",
                "system_info",
            ],
            cwd=REPO_ROOT,
            log_dir=log_dir,
        )
    )
    pending = _run_step(
        name="write_config_pending",
        command=[
            *inspector_base,
            "--method",
            "tools/call",
            "--tool-name",
            "write_config_file",
            "--tool-arg",
            f"path={config_path}",
            "--tool-arg",
            'content="[main]\\nkey=new\\n"',
        ],
        cwd=REPO_ROOT,
        log_dir=log_dir,
    )
    steps.append(pending)

    approval_id = _extract_approval_id(pending.parsed)
    if approval_id is None:
        report = _build_report(
            run_dir=run_dir,
            state_dir=state_dir,
            config_path=config_path,
            inspector_package=inspector_package,
            python_bin=python_bin,
            steps=steps,
            notes=["Could not extract approval id from the pending write response."],
        )
        _write_report(report, run_dir)
        return report

    steps.append(
        _run_step(
            name="approval_get",
            command=[
                *inspector_base,
                "--method",
                "tools/call",
                "--tool-name",
                "approval_get",
                "--tool-arg",
                f"id={approval_id}",
            ],
            cwd=REPO_ROOT,
            log_dir=log_dir,
        )
    )
    steps.append(
        _run_step(
            name="approval_approve",
            command=[
                *inspector_base,
                "--method",
                "tools/call",
                "--tool-name",
                "approval_approve",
                "--tool-arg",
                f"id={approval_id}",
            ],
            cwd=REPO_ROOT,
            log_dir=log_dir,
        )
    )

    report = _build_report(
        run_dir=run_dir,
        state_dir=state_dir,
        config_path=config_path,
        inspector_package=inspector_package,
        python_bin=python_bin,
        steps=steps,
        notes=[],
    )
    _write_report(report, run_dir)
    return report


def _run_step(
    *,
    name: str,
    command: list[str],
    cwd: Path,
    log_dir: Path,
) -> StepResult:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    stdout_path = log_dir / f"{name}.stdout.log"
    stderr_path = log_dir / f"{name}.stderr.log"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")

    parsed = _parse_json_output(completed.stdout)
    return StepResult(
        name=name,
        command=tuple(command),
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        parsed=parsed,
    )


def _parse_json_output(stdout: str) -> dict[str, object] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _extract_approval_id(payload: dict[str, object] | None) -> int | None:
    if not isinstance(payload, dict):
        return None
    structured = payload.get("structuredContent")
    if not isinstance(structured, dict):
        return None
    approval = structured.get("approval")
    if not isinstance(approval, dict):
        return None
    approval_id = approval.get("id")
    if isinstance(approval_id, int) and not isinstance(approval_id, bool):
        return approval_id
    return None


def _build_report(
    *,
    run_dir: Path,
    state_dir: Path,
    config_path: Path,
    inspector_package: str,
    python_bin: str,
    steps: list[StepResult],
    notes: list[str],
) -> dict[str, object]:
    step_reports = [
        {
            "name": step.name,
            "command": list(step.command),
            "exit_code": step.exit_code,
            "ok": step.ok,
            "parsed": step.parsed,
            "stdout_log": str(run_dir / "logs" / f"{step.name}.stdout.log"),
            "stderr_log": str(run_dir / "logs" / f"{step.name}.stderr.log"),
        }
        for step in steps
    ]

    overall_ok = _evaluate_report(steps, config_path)
    return {
        "generated_at": _utc_now().isoformat(),
        "repo_root": str(REPO_ROOT),
        "run_dir": str(run_dir),
        "state_dir": str(state_dir),
        "config_path": str(config_path),
        "inspector_package": inspector_package,
        "python_bin": python_bin,
        "steps": step_reports,
        "final_config_content": config_path.read_text(encoding="utf-8"),
        "overall_ok": overall_ok,
        "notes": notes,
        "report_path": str(run_dir / "report.json"),
    }


def _evaluate_report(steps: list[StepResult], config_path: Path) -> bool:
    if not all(step.ok and step.parsed is not None for step in steps):
        return False

    tools_list = steps[0].parsed
    system_info = steps[1].parsed
    pending = steps[2].parsed
    approval_get = steps[3].parsed if len(steps) > 3 else None
    approval_approve = steps[4].parsed if len(steps) > 4 else None

    if not isinstance(tools_list, dict) or not isinstance(system_info, dict):
        return False
    if not isinstance(pending, dict) or not isinstance(approval_get, dict):
        return False
    if not isinstance(approval_approve, dict):
        return False

    tools = tools_list.get("tools")
    if not isinstance(tools, list):
        return False
    tool_names = [item.get("name") for item in tools if isinstance(item, dict)]
    required_tools = {"system_info", "write_config_file", "approval_get", "approval_approve"}
    if not required_tools.issubset(set(name for name in tool_names if isinstance(name, str))):
        return False

    pending_structured = pending.get("structuredContent")
    if not isinstance(pending_structured, dict) or not pending_structured.get("pending_confirmation"):
        return False

    fetched_structured = approval_get.get("structuredContent")
    if not isinstance(fetched_structured, dict) or fetched_structured.get("status") != "pending":
        return False

    approved_structured = approval_approve.get("structuredContent")
    if not isinstance(approved_structured, dict):
        return False
    approval = approved_structured.get("approval")
    execution = approved_structured.get("execution")
    if not isinstance(approval, dict) or approval.get("status") != "completed":
        return False
    if not isinstance(execution, dict) or not bool(execution.get("ok")):
        return False
    if config_path.read_text(encoding="utf-8") != "[main]\nkey=new\n":
        return False
    return True


def _write_report(report: dict[str, object], run_dir: Path) -> None:
    report_path = run_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _slugify(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value.lower()).strip("-")


if __name__ == "__main__":
    raise SystemExit(main())
