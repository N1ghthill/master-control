from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from master_control.config import Settings

RECONCILE_SERVICE_NAME = "master-control-reconcile.service"
RECONCILE_TIMER_NAME = "master-control-reconcile.timer"
DEFAULT_RECONCILE_ON_CALENDAR = "hourly"
DEFAULT_RECONCILE_RANDOMIZED_DELAY = "5m"


@dataclass(frozen=True, slots=True)
class RenderedSystemdUnit:
    name: str
    path: Path
    content: str

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": str(self.path),
            "content": self.content,
        }


def render_reconcile_units(
    settings: Settings,
    *,
    scope: str = "user",
    on_calendar: str = DEFAULT_RECONCILE_ON_CALENDAR,
    randomized_delay: str = DEFAULT_RECONCILE_RANDOMIZED_DELAY,
    target_dir: Path | None = None,
    python_executable: str | None = None,
    project_root: Path | None = None,
) -> dict[str, RenderedSystemdUnit]:
    resolved_scope = _normalize_scope(scope)
    resolved_target_dir = target_dir or systemd_unit_dir_for_scope(resolved_scope)
    resolved_python = python_executable or sys.executable
    resolved_project_root = project_root or Path(__file__).resolve().parents[2]

    service_path = resolved_target_dir / RECONCILE_SERVICE_NAME
    timer_path = resolved_target_dir / RECONCILE_TIMER_NAME
    service_content = _render_reconcile_service(
        settings,
        scope=resolved_scope,
        python_executable=resolved_python,
        project_root=resolved_project_root,
    )
    timer_content = _render_reconcile_timer(
        on_calendar=on_calendar,
        randomized_delay=randomized_delay,
    )
    return {
        "service": RenderedSystemdUnit(
            name=RECONCILE_SERVICE_NAME,
            path=service_path,
            content=service_content,
        ),
        "timer": RenderedSystemdUnit(
            name=RECONCILE_TIMER_NAME,
            path=timer_path,
            content=timer_content,
        ),
    }


def install_reconcile_timer(
    settings: Settings,
    *,
    scope: str = "user",
    on_calendar: str = DEFAULT_RECONCILE_ON_CALENDAR,
    randomized_delay: str = DEFAULT_RECONCILE_RANDOMIZED_DELAY,
    target_dir: Path | None = None,
    python_executable: str | None = None,
    project_root: Path | None = None,
    run_systemctl: bool = True,
) -> dict[str, object]:
    units = render_reconcile_units(
        settings,
        scope=scope,
        on_calendar=on_calendar,
        randomized_delay=randomized_delay,
        target_dir=target_dir,
        python_executable=python_executable,
        project_root=project_root,
    )
    units["service"].path.parent.mkdir(parents=True, exist_ok=True)
    for unit in units.values():
        unit.path.write_text(unit.content, encoding="utf-8")

    if run_systemctl:
        _run_systemctl(scope, "daemon-reload")
        _run_systemctl(scope, "enable", "--now", RECONCILE_TIMER_NAME)

    return {
        "scope": _normalize_scope(scope),
        "run_systemctl": run_systemctl,
        "service": units["service"].as_dict(),
        "timer": units["timer"].as_dict(),
        "on_calendar": on_calendar,
        "randomized_delay": randomized_delay,
    }


def remove_reconcile_timer(
    *,
    scope: str = "user",
    target_dir: Path | None = None,
    run_systemctl: bool = True,
) -> dict[str, object]:
    resolved_scope = _normalize_scope(scope)
    resolved_target_dir = target_dir or systemd_unit_dir_for_scope(resolved_scope)
    service_path = resolved_target_dir / RECONCILE_SERVICE_NAME
    timer_path = resolved_target_dir / RECONCILE_TIMER_NAME
    removed_paths: list[str] = []

    if run_systemctl:
        _run_systemctl(resolved_scope, "disable", "--now", RECONCILE_TIMER_NAME, check=False)

    for path in (service_path, timer_path):
        if path.exists():
            path.unlink()
            removed_paths.append(str(path))

    if run_systemctl:
        _run_systemctl(resolved_scope, "daemon-reload")

    return {
        "scope": resolved_scope,
        "run_systemctl": run_systemctl,
        "removed_paths": removed_paths,
        "service_path": str(service_path),
        "timer_path": str(timer_path),
    }


def systemd_unit_dir_for_scope(scope: str) -> Path:
    resolved_scope = _normalize_scope(scope)
    if resolved_scope == "user":
        return Path.home() / ".config" / "systemd" / "user"
    return Path("/etc/systemd/system")


def _render_reconcile_service(
    settings: Settings,
    *,
    scope: str,
    python_executable: str,
    project_root: Path,
) -> str:
    src_path = project_root / "src"
    lines = [
        "[Unit]",
        "Description=Master Control recommendation reconciliation",
        "",
        "[Service]",
        "Type=oneshot",
        f"WorkingDirectory={project_root}",
        f"Environment=PYTHONPATH={src_path}",
        f"Environment=MC_STATE_DIR={settings.state_dir}",
        f"Environment=MC_DB_PATH={settings.db_path}",
        "Environment=MC_PROVIDER=noop",
        f"Environment=MC_LOG_LEVEL={settings.log_level}",
        f"ExecStart={python_executable} -m master_control reconcile --all",
    ]
    if scope == "user":
        lines.append("Slice=app.slice")
    lines.extend(
        [
            "",
            "[Install]",
            "WantedBy=default.target" if scope == "user" else "WantedBy=multi-user.target",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_reconcile_timer(
    *,
    on_calendar: str,
    randomized_delay: str,
) -> str:
    return "\n".join(
        [
            "[Unit]",
            "Description=Run Master Control reconciliation periodically",
            "",
            "[Timer]",
            f"OnCalendar={on_calendar}",
            f"RandomizedDelaySec={randomized_delay}",
            "Persistent=true",
            f"Unit={RECONCILE_SERVICE_NAME}",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    )


def _run_systemctl(scope: str, *args: str, check: bool = True) -> None:
    command = ["systemctl"]
    if _normalize_scope(scope) == "user":
        command.append("--user")
    command.extend(args)
    subprocess.run(command, check=check, text=True, capture_output=True)


def _normalize_scope(scope: str) -> str:
    normalized = scope.strip().lower()
    if normalized not in {"user", "system"}:
        raise ValueError(f"Unsupported systemd scope: {scope}")
    return normalized
