from __future__ import annotations

import argparse
import json
import platform
import shlex
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class BootstrapCommandResult:
    name: str
    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    stdout_path: Path
    stderr_path: Path

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True, slots=True)
class BootstrapValidationRun:
    report_path: Path
    report: dict[str, Any]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the operator bootstrap lifecycle in an isolated prefix and write a JSON report."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path.cwd() / "artifacts" / "bootstrap-validation"),
        help="Directory where the bootstrap validation report will be written.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path.cwd()),
        help="Repository root that contains install.sh and uninstall.sh. Default: current directory.",
    )
    parser.add_argument(
        "--provider",
        default="heuristic",
        help="MC provider to bake into the temporary wrapper. Default: heuristic.",
    )
    parser.add_argument(
        "--python",
        default="python3",
        help="Python interpreter passed through to install.sh. Default: python3.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Render the generated report as JSON instead of printing the report path.",
    )
    return parser


def cli_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_bootstrap_validation(
        output_dir=args.output_dir,
        repo_root=args.repo_root,
        provider=args.provider,
        python_bin=args.python,
    )
    if args.json:
        print(json.dumps(result.report, indent=2, sort_keys=True))
    else:
        print(result.report_path)
    return 0 if result.report["overall_ok"] else 1


def run_bootstrap_validation(
    *,
    output_dir: str | Path,
    repo_root: str | Path,
    provider: str = "heuristic",
    python_bin: str = "python3",
) -> BootstrapValidationRun:
    repo_root_path = Path(repo_root).expanduser().resolve()
    install_script = repo_root_path / "install.sh"
    uninstall_script = repo_root_path / "uninstall.sh"
    if not install_script.is_file():
        raise ValueError(f"install.sh not found under {repo_root_path}")
    if not uninstall_script.is_file():
        raise ValueError(f"uninstall.sh not found under {repo_root_path}")

    report_dir = Path(output_dir).expanduser().resolve()
    run_id = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    host_slug = _slugify(socket.gethostname())
    run_dir = report_dir / f"{run_id}-{host_slug}"
    workspace_dir = run_dir / "workspace"
    log_dir = run_dir / "command-logs"
    host_validation_dir = run_dir / "host-validation"
    log_dir.mkdir(parents=True, exist_ok=True)

    prefix = workspace_dir / "prefix"
    bin_dir = workspace_dir / "bin"
    state_dir = workspace_dir / "state"
    wrapper_path = bin_dir / "mc"
    venv_dir = prefix / "venv"
    manifest_path = prefix / "install-manifest.env"

    command_reports: dict[str, dict[str, Any]] = {}
    notes: list[str] = []

    install_command = (
        str(install_script),
        "--prefix",
        str(prefix),
        "--bin-dir",
        str(bin_dir),
        "--state-dir",
        str(state_dir),
        "--python",
        python_bin,
        "--provider",
        provider,
    )
    install_result = _run_logged_command(
        "install",
        install_command,
        cwd=repo_root_path,
        log_dir=log_dir,
    )
    command_reports["install"] = _command_report_payload(install_result)

    doctor_command = (str(wrapper_path), "--json", "doctor")
    doctor_payload: dict[str, Any] | None = None
    if install_result.ok and wrapper_path.exists():
        doctor_result = _run_logged_command(
            "doctor",
            doctor_command,
            cwd=repo_root_path,
            log_dir=log_dir,
        )
        doctor_payload, doctor_parse_error = _parse_json_output(doctor_result.stdout)
        command_reports["doctor"] = _command_report_payload(
            doctor_result,
            payload=doctor_payload,
            parse_error=doctor_parse_error,
        )
    else:
        reason = "Install step did not produce an executable wrapper."
        notes.append(reason)
        command_reports["doctor"] = _skipped_command_payload(doctor_command, reason=reason)

    validate_command = (
        str(wrapper_path),
        "--json",
        "validate-host-profile",
        "--output-dir",
        str(host_validation_dir),
    )
    host_validation_payload: dict[str, Any] | None = None
    if install_result.ok and wrapper_path.exists():
        validate_result = _run_logged_command(
            "validate_host_profile",
            validate_command,
            cwd=repo_root_path,
            log_dir=log_dir,
        )
        host_validation_payload, validate_parse_error = _parse_json_output(validate_result.stdout)
        command_reports["validate_host_profile"] = _command_report_payload(
            validate_result,
            payload=host_validation_payload,
            parse_error=validate_parse_error,
        )
    else:
        reason = "Host-profile validation was skipped because install did not complete."
        notes.append(reason)
        command_reports["validate_host_profile"] = _skipped_command_payload(
            validate_command,
            reason=reason,
        )

    uninstall_command = (
        str(uninstall_script),
        "--prefix",
        str(prefix),
        "--bin-dir",
        str(bin_dir),
        "--state-dir",
        str(state_dir),
        "--purge-state",
    )
    has_install_artifacts = any(
        path.exists() for path in (prefix, bin_dir, state_dir, wrapper_path, manifest_path, venv_dir)
    )
    if has_install_artifacts:
        uninstall_result = _run_logged_command(
            "uninstall",
            uninstall_command,
            cwd=repo_root_path,
            log_dir=log_dir,
        )
        command_reports["uninstall"] = _command_report_payload(uninstall_result)
    else:
        reason = "Uninstall step was skipped because no bootstrap artifacts were created."
        notes.append(reason)
        command_reports["uninstall"] = _skipped_command_payload(uninstall_command, reason=reason)

    cleanup = {
        "wrapper_missing": not wrapper_path.exists(),
        "venv_missing": not venv_dir.exists(),
        "state_missing": not state_dir.exists(),
        "manifest_missing": not manifest_path.exists(),
    }
    cleanup["ok"] = all(cleanup.values())

    report: dict[str, Any] = {
        "generated_at": _utc_now().isoformat(),
        "repo_root": str(repo_root_path),
        "run_dir": str(run_dir),
        "host_profile": _build_host_profile(),
        "artifacts": {
            "workspace_dir": str(workspace_dir),
            "prefix": str(prefix),
            "bin_dir": str(bin_dir),
            "state_dir": str(state_dir),
            "wrapper_path": str(wrapper_path),
            "venv_dir": str(venv_dir),
            "manifest_path": str(manifest_path),
            "log_dir": str(log_dir),
            "host_validation_dir": str(host_validation_dir),
        },
        "settings": {
            "provider": provider,
            "python_bin": python_bin,
        },
        "commands": command_reports,
        "cleanup": cleanup,
        "notes": notes,
    }
    report["overall_ok"] = _is_report_green(
        report,
        doctor_payload=doctor_payload,
        host_validation_payload=host_validation_payload,
    )

    report_path = run_dir / "report.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return BootstrapValidationRun(report_path=report_path, report=report)


def _build_host_profile() -> dict[str, str]:
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "python": platform.python_version(),
    }


def _run_logged_command(
    name: str,
    command: tuple[str, ...],
    *,
    cwd: Path,
    log_dir: Path,
) -> BootstrapCommandResult:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout_text = completed.stdout or ""
    stderr_text = completed.stderr or ""
    stdout_path = log_dir / f"{name}.stdout.txt"
    stderr_path = log_dir / f"{name}.stderr.txt"
    stdout_path.write_text(stdout_text, encoding="utf-8")
    stderr_path.write_text(stderr_text, encoding="utf-8")
    return BootstrapCommandResult(
        name=name,
        command=command,
        exit_code=completed.returncode,
        stdout=stdout_text,
        stderr=stderr_text,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )


def _command_report_payload(
    result: BootstrapCommandResult,
    *,
    payload: dict[str, Any] | None = None,
    parse_error: str | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "name": result.name,
        "command": shlex.join(result.command),
        "exit_code": result.exit_code,
        "ok": result.ok,
        "stdout_path": str(result.stdout_path),
        "stderr_path": str(result.stderr_path),
        "stdout_excerpt": _excerpt_block(result.stdout),
        "stderr_excerpt": _excerpt_block(result.stderr),
    }
    if payload is not None:
        report["payload"] = payload
    if parse_error is not None:
        report["parse_error"] = parse_error
    return report


def _skipped_command_payload(
    command: tuple[str, ...],
    *,
    reason: str,
) -> dict[str, Any]:
    return {
        "command": shlex.join(command),
        "exit_code": None,
        "ok": False,
        "skipped": True,
        "reason": reason,
    }


def _parse_json_output(text: str) -> tuple[dict[str, Any] | None, str | None]:
    stripped = text.strip()
    if not stripped:
        return None, "stdout was empty"
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        return None, f"stdout did not contain valid JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "stdout JSON was not an object"
    return payload, None


def _excerpt_block(text: str, *, max_chars: int = 600) -> str:
    compact = text.strip()
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _is_report_green(
    report: dict[str, Any],
    *,
    doctor_payload: dict[str, Any] | None,
    host_validation_payload: dict[str, Any] | None,
) -> bool:
    commands = report.get("commands")
    cleanup = report.get("cleanup")
    if not isinstance(commands, dict) or not isinstance(cleanup, dict):
        return False
    install_ok = _command_ok(commands.get("install"))
    doctor_ok = (
        _command_ok(commands.get("doctor"))
        and isinstance(doctor_payload, dict)
        and bool(doctor_payload.get("ok"))
    )
    validate_ok = (
        _command_ok(commands.get("validate_host_profile"))
        and isinstance(host_validation_payload, dict)
        and bool(host_validation_payload.get("overall_ok"))
    )
    uninstall_ok = _command_ok(commands.get("uninstall"))
    return install_ok and doctor_ok and validate_ok and uninstall_ok and bool(cleanup.get("ok"))


def _command_ok(payload: object) -> bool:
    return isinstance(payload, dict) and bool(payload.get("ok")) and not bool(payload.get("skipped"))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _slugify(value: str) -> str:
    characters = [char.lower() if char.isalnum() else "-" for char in value]
    collapsed = "".join(characters)
    while "--" in collapsed:
        collapsed = collapsed.replace("--", "-")
    return collapsed.strip("-") or "host"
