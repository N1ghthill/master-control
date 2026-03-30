from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import socket
import subprocess
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from master_control.config import Settings
from master_control.core.runtime import MasterControlRuntime
from master_control.interfaces.agent.chat import MasterControlChatInterface


@dataclass(frozen=True, slots=True)
class BaselineCommand:
    argv: tuple[str, ...]
    extra_env: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        return shlex.join(self.argv)


DEFAULT_BASELINE_COMMANDS = (
    BaselineCommand(argv=("python3", "-m", "ruff", "check", ".")),
    BaselineCommand(argv=("python3", "-m", "mypy", "src")),
    BaselineCommand(
        argv=("python3", "-m", "unittest", "discover", "-s", "tests"),
        extra_env={"PYTHONPATH": "src"},
    ),
    BaselineCommand(
        argv=("python3", "-m", "pytest", "-q"),
        extra_env={"PYTHONPATH": "src"},
    ),
    BaselineCommand(argv=("python3", "-m", "compileall", "src")),
    BaselineCommand(
        argv=("python3", "-m", "master_control", "--json", "doctor"),
        extra_env={"PYTHONPATH": "src"},
    ),
)


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True, slots=True)
class HostValidationRun:
    report_path: Path
    report: dict[str, Any]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run repeatable Master Control host-profile validation and write a JSON report.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path.cwd() / "artifacts" / "host-validation"),
        help="Directory where the validation report will be written.",
    )
    parser.add_argument(
        "--provider",
        default="heuristic",
        help="MC provider to use for host workflow validation. Default: heuristic.",
    )
    parser.add_argument(
        "--run-baseline",
        action="store_true",
        help="Also rerun the local engineering baseline commands on this host.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Render the generated report as JSON instead of printing the report path.",
    )
    return parser


def cli_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_host_validation(
        output_dir=args.output_dir,
        provider=args.provider,
        run_baseline=args.run_baseline,
    )
    if args.json:
        print(json.dumps(result.report, indent=2, sort_keys=True))
    else:
        print(result.report_path)
    return 0 if result.report["overall_ok"] else 1


def run_host_validation(
    *,
    output_dir: str | Path,
    provider: str = "heuristic",
    run_baseline: bool = False,
    base_settings: Settings | None = None,
) -> HostValidationRun:
    report_dir = Path(output_dir).expanduser().resolve()
    run_id = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    host_slug = _slugify(socket.gethostname())
    run_dir = report_dir / f"{run_id}-{host_slug}"
    state_dir = run_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    base = base_settings or Settings.from_env()
    settings = replace(
        base,
        provider=provider,
        state_dir=state_dir,
        db_path=state_dir / "mc.sqlite3",
    )

    runtime = _build_validation_runtime(settings)
    chat = _build_validation_chat(runtime)
    runtime.bootstrap()

    baseline_results = _run_baseline_commands() if run_baseline else ()
    report: dict[str, Any] = {
        "generated_at": _utc_now().isoformat(),
        "repo_root": str(Path.cwd().resolve()),
        "run_dir": str(run_dir),
        "host_profile": _build_host_profile(),
        "settings": {
            "provider": settings.provider,
            "state_dir": str(settings.state_dir),
            "db_path": str(settings.db_path),
        },
        "doctor": runtime.doctor(),
        "baseline": {
            "enabled": run_baseline,
            "all_ok": all(item.ok for item in baseline_results),
            "commands": [asdict(item) | {"ok": item.ok} for item in baseline_results],
        },
        "workflows": {
            "slow_host": _validate_slow_host_workflow(runtime, chat),
            "failed_service": _validate_failed_service_workflow(runtime, chat),
            "managed_config": _validate_managed_config_workflow(runtime),
        },
    }
    report["overall_ok"] = _is_report_green(report)

    report_path = run_dir / "report.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return HostValidationRun(report_path=report_path, report=report)


def _build_host_profile() -> dict[str, str]:
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "python": platform.python_version(),
    }


def _build_validation_runtime(settings: Settings) -> MasterControlRuntime:
    return MasterControlRuntime(settings)


def _build_validation_chat(runtime: MasterControlRuntime) -> MasterControlChatInterface:
    return MasterControlChatInterface(runtime)


def _validate_slow_host_workflow(
    runtime: MasterControlRuntime,
    chat: MasterControlChatInterface,
) -> dict[str, Any]:
    try:
        payload = chat.chat("o host esta lento", new_session=True)
        session_id = _as_int(payload.get("session_id"))
        recommendations = (
            runtime.list_session_recommendations(session_id=session_id)["recommendations"]
            if session_id is not None
            else []
        )
        return {
            "ok": True,
            "session_id": session_id,
            "executed_tools": _extract_executed_tools(payload),
            "turn_decision": payload.get("turn_decision"),
            "recommendation_keys": _extract_recommendation_keys(recommendations),
            "message_excerpt": _excerpt(payload.get("message")),
        }
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc)}


def _validate_failed_service_workflow(
    runtime: MasterControlRuntime,
    chat: MasterControlChatInterface,
) -> dict[str, Any]:
    try:
        payload = chat.chat("quais servicos com falha eu tenho?", new_session=True)
        session_id = _as_int(payload.get("session_id"))
        recommendations = (
            runtime.list_session_recommendations(session_id=session_id)["recommendations"]
            if session_id is not None
            else []
        )
        failed_services_result = runtime.run_tool(
            "failed_services",
            {"scope": "system", "limit": 5},
            audit_context={"source": "host_profile_validation"},
        )
        result_payload = failed_services_result.get("result")
        unit_count = (
            result_payload.get("unit_count")
            if failed_services_result.get("ok") and isinstance(result_payload, dict)
            else None
        )
        notes: list[str] = []
        if unit_count == 0:
            notes.append("Host returned no failed system services during this validation run.")
        status = result_payload.get("status") if isinstance(result_payload, dict) else None
        return {
            "ok": bool(payload.get("message")) and bool(failed_services_result.get("ok")),
            "session_id": session_id,
            "executed_tools": _extract_executed_tools(payload),
            "recommendation_keys": _extract_recommendation_keys(recommendations),
            "failed_services_tool": {
                "unit_count": unit_count,
                "status": status,
            },
            "message_excerpt": _excerpt(payload.get("message")),
            "notes": notes,
        }
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc)}


def _validate_managed_config_workflow(runtime: MasterControlRuntime) -> dict[str, Any]:
    try:
        session_id = runtime.store.create_session()
        config_path = runtime.settings.state_dir / "managed-configs" / "host-profile-validation.ini"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("[service]\nmode=old\n", encoding="utf-8")
        audit_context = {
            "source": "host_profile_validation",
            "session_id": session_id,
        }

        read_before = runtime.run_tool(
            "read_config_file",
            {"path": str(config_path)},
            audit_context=audit_context,
        )
        write_result = runtime.run_tool(
            "write_config_file",
            {"path": str(config_path), "content": "[service]\nmode=new\n"},
            confirmed=True,
            audit_context=audit_context,
        )
        recommendation_sync = runtime.reconcile_recommendations(session_id=session_id)
        read_after_write = runtime.run_tool(
            "read_config_file",
            {"path": str(config_path)},
            audit_context=audit_context,
        )
        write_payload = write_result.get("result")
        backup_path = write_payload.get("backup_path") if isinstance(write_payload, dict) else None
        restore_result = runtime.run_tool(
            "restore_config_backup",
            {"path": str(config_path), "backup_path": str(backup_path)},
            confirmed=True,
            audit_context=audit_context,
        )
        read_after_restore = runtime.run_tool(
            "read_config_file",
            {"path": str(config_path)},
            audit_context=audit_context,
        )

        sync_sessions = recommendation_sync.get("sessions")
        active_recommendations: object = []
        if isinstance(sync_sessions, list) and sync_sessions:
            first_session = sync_sessions[0]
            if isinstance(first_session, dict):
                recommendations = first_session.get("recommendations")
                if isinstance(recommendations, dict):
                    active_recommendations = recommendations.get("active", [])
        final_content = _read_tool_content(read_after_restore)
        return {
            "ok": all(
                item.get("ok")
                for item in (
                    read_before,
                    write_result,
                    read_after_write,
                    restore_result,
                    read_after_restore,
                )
            )
            and "mode=old" in final_content,
            "session_id": session_id,
            "config_path": str(config_path),
            "backup_path": str(backup_path) if backup_path else None,
            "recommendation_keys_after_write": _extract_recommendation_keys(active_recommendations),
            "content_after_write": _read_tool_content(read_after_write),
            "content_after_restore": final_content,
        }
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc)}


def _run_baseline_commands() -> tuple[CommandResult, ...]:
    results: list[CommandResult] = []
    for command in DEFAULT_BASELINE_COMMANDS:
        env = dict(os.environ)
        env.update(command.extra_env)
        completed = subprocess.run(
            command.argv,
            cwd=Path.cwd(),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        results.append(
            CommandResult(
                command=command.render(),
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        )
    return tuple(results)


def _extract_executed_tools(payload: dict[str, Any]) -> list[str]:
    executions = payload.get("executions")
    if not isinstance(executions, list):
        return []
    tools: list[str] = []
    for item in executions:
        if not isinstance(item, dict):
            continue
        tool = item.get("tool")
        if isinstance(tool, str):
            tools.append(tool)
    return tools


def _extract_recommendation_keys(recommendations: object) -> list[str]:
    if not isinstance(recommendations, list):
        return []
    keys: list[str] = []
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        key = item.get("source_key")
        if isinstance(key, str):
            keys.append(key)
    return keys


def _read_tool_content(payload: dict[str, Any]) -> str:
    result = payload.get("result")
    if not isinstance(result, dict):
        return ""
    content = result.get("content")
    return content if isinstance(content, str) else ""


def _excerpt(value: object, *, limit: int = 240) -> str | None:
    if not isinstance(value, str):
        return None
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _is_report_green(report: dict[str, Any]) -> bool:
    doctor = report.get("doctor")
    workflows = report.get("workflows")
    baseline = report.get("baseline")
    if (
        not isinstance(doctor, dict)
        or not isinstance(workflows, dict)
        or not isinstance(baseline, dict)
    ):
        return False
    workflow_ok = all(
        isinstance(item, dict) and bool(item.get("ok")) for item in workflows.values()
    )
    baseline_ok = True
    if baseline.get("enabled"):
        baseline_ok = bool(baseline.get("all_ok"))
    return bool(doctor.get("ok")) and workflow_ok and baseline_ok


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _slugify(value: str) -> str:
    characters = [char.lower() if char.isalnum() else "-" for char in value]
    collapsed = "".join(characters)
    while "--" in collapsed:
        collapsed = collapsed.replace("--", "-")
    return collapsed.strip("-") or "host"


def _as_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None
