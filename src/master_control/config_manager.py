from __future__ import annotations

import configparser
import fnmatch
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from master_control.executor.command_runner import CommandExecutionError, CommandRunner
from master_control.tools.base import ToolError

MAX_CONFIG_FILE_BYTES = 128 * 1024


@dataclass(frozen=True, slots=True)
class ConfigTarget:
    name: str
    description: str
    roots: tuple[Path, ...]
    file_globs: tuple[str, ...]
    validator_kind: str
    validator_command: tuple[str, ...] | None = None

    def matches(self, path: Path) -> bool:
        for root in self.roots:
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            relative_posix = relative.as_posix()
            if any(
                fnmatch.fnmatch(relative_posix, pattern) or fnmatch.fnmatch(path.name, pattern)
                for pattern in self.file_globs
            ):
                return True
        return False


@dataclass(frozen=True, slots=True)
class ConfigResolution:
    path: Path
    target: ConfigTarget


class ConfigManager:
    def __init__(
        self,
        state_dir: Path,
        runner: CommandRunner,
        *,
        targets: tuple[ConfigTarget, ...] | None = None,
    ) -> None:
        self.state_dir = state_dir
        self.runner = runner
        self.targets = targets or build_default_config_targets(state_dir)
        self.backup_root = state_dir / "config-backups"

    def read_text(self, path_text: str) -> dict[str, Any]:
        resolution = self.resolve_target(path_text)
        content = self._read_text_file(resolution.path)
        return {
            "status": "ok",
            "path": str(resolution.path),
            "target": resolution.target.name,
            "line_count": len(content.splitlines()),
            "content": content,
        }

    def write_text(self, path_text: str, content: str) -> dict[str, Any]:
        resolution = self.resolve_target(path_text)
        self._validate_content_size(content)

        target_path = resolution.path
        current_content = target_path.read_text(encoding="utf-8") if target_path.exists() else None
        if current_content == content:
            validation = self.validate_content(resolution, content)
            return {
                "status": "ok",
                "path": str(target_path),
                "target": resolution.target.name,
                "changed": False,
                "backup_path": None,
                "validation": validation,
            }

        target_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path = self._create_backup(target_path, resolution.target.name)
        temp_path = self._write_temp_file(target_path, content)

        try:
            validation = self.validate_path(resolution, temp_path)
            self._apply_temp_file(temp_path, target_path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        return {
            "status": "ok",
            "path": str(target_path),
            "target": resolution.target.name,
            "changed": True,
            "backup_path": str(backup_path) if backup_path else None,
            "validation": validation,
        }

    def restore_backup(self, path_text: str, backup_path_text: str) -> dict[str, Any]:
        resolution = self.resolve_target(path_text)
        backup_path = Path(backup_path_text).expanduser().resolve(strict=False)
        if not backup_path.exists():
            raise ToolError(f"Backup file `{backup_path}` does not exist.")
        if not self._is_within(backup_path, self.backup_root.resolve(strict=False)):
            raise ToolError("Backup path is outside the managed backup directory.")

        content = self._read_text_file(backup_path)
        self._validate_content_size(content)

        target_path = resolution.path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        rollback_backup = self._create_backup(target_path, resolution.target.name)
        temp_path = self._write_temp_file(target_path, content)

        try:
            validation = self.validate_path(resolution, temp_path)
            self._apply_temp_file(temp_path, target_path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        return {
            "status": "ok",
            "path": str(target_path),
            "target": resolution.target.name,
            "restored_from": str(backup_path),
            "rollback_backup_path": str(rollback_backup) if rollback_backup else None,
            "validation": validation,
        }

    def resolve_target(self, path_text: str) -> ConfigResolution:
        candidate = Path(path_text).expanduser()
        resolved_path = candidate.resolve(strict=False)

        for target in self.targets:
            if target.matches(resolved_path):
                return ConfigResolution(path=resolved_path, target=target)

        raise ToolError(f"Path `{resolved_path}` is not managed by the config policy.")

    def validate_content(self, resolution: ConfigResolution, content: str) -> dict[str, Any]:
        temp_path = self._write_temp_file(resolution.path, content)
        try:
            return self.validate_path(resolution, temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

    def validate_path(self, resolution: ConfigResolution, candidate_path: Path) -> dict[str, Any]:
        target = resolution.target
        if target.validator_kind == "ini_parse":
            try:
                parser = configparser.ConfigParser()
                parser.read(candidate_path, encoding="utf-8")
            except configparser.Error as exc:
                raise ToolError(f"INI validation failed for `{resolution.path}`: {exc}") from exc
            return {
                "kind": target.validator_kind,
                "status": "ok",
            }

        if target.validator_kind == "json_parse":
            try:
                raw_text = candidate_path.read_text(encoding="utf-8")
                json.loads(raw_text)
            except json.JSONDecodeError as exc:
                raise ToolError(f"JSON validation failed for `{resolution.path}`: {exc}") from exc
            return {
                "kind": target.validator_kind,
                "status": "ok",
            }

        if target.validator_kind == "command":
            if not target.validator_command:
                raise ToolError(f"Target `{target.name}` is missing a validator command.")
            command = [part.format(path=str(candidate_path)) for part in target.validator_command]
            try:
                result = self.runner.run(command, timeout_s=10.0)
            except CommandExecutionError as exc:
                raise ToolError(str(exc)) from exc

            if result.returncode != 0:
                stderr = (result.stderr or result.stdout).strip()
                raise ToolError(stderr or f"Validation failed for `{resolution.path}`.")

            return {
                "kind": target.validator_kind,
                "status": "ok",
                "command": command,
            }

        raise ToolError(f"Unknown validator kind: {target.validator_kind}")

    def _read_text_file(self, path: Path) -> str:
        if not path.exists():
            raise ToolError(f"File `{path}` does not exist.")
        if path.is_dir():
            raise ToolError(f"Path `{path}` is a directory, not a file.")
        file_size = path.stat().st_size
        if file_size > MAX_CONFIG_FILE_BYTES:
            raise ToolError(
                f"File `{path}` exceeds the maximum managed size of {MAX_CONFIG_FILE_BYTES} bytes."
            )
        return path.read_text(encoding="utf-8")

    def _validate_content_size(self, content: str) -> None:
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_CONFIG_FILE_BYTES:
            raise ToolError(
                f"Content exceeds the maximum managed size of {MAX_CONFIG_FILE_BYTES} bytes."
            )

    def _write_temp_file(self, target_path: Path, content: str) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=".mc-",
            suffix=target_path.suffix or ".tmp",
            dir=target_path.parent,
            text=True,
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return temp_path

    def _apply_temp_file(self, temp_path: Path, target_path: Path) -> None:
        if target_path.exists():
            mode = target_path.stat().st_mode & 0o777
            os.chmod(temp_path, mode)
        else:
            os.chmod(temp_path, 0o644)
        os.replace(temp_path, target_path)

    def _create_backup(self, target_path: Path, target_name: str) -> Path | None:
        if not target_path.exists():
            return None

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        safe_relative = target_path.resolve(strict=False).as_posix().lstrip("/").replace("/", "__")
        backup_dir = self.backup_root / target_name
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{timestamp}__{safe_relative}.bak"
        backup_path.write_text(target_path.read_text(encoding="utf-8"), encoding="utf-8")
        return backup_path

    def _is_within(self, candidate: Path, root: Path) -> bool:
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            return False


def build_default_config_targets(state_dir: Path) -> tuple[ConfigTarget, ...]:
    managed_root = (state_dir / "managed-configs").resolve(strict=False)
    return (
        ConfigTarget(
            name="managed_ini",
            description="MC-managed INI or CFG files.",
            roots=(managed_root,),
            file_globs=("*.ini", "*.cfg"),
            validator_kind="ini_parse",
        ),
        ConfigTarget(
            name="managed_json",
            description="MC-managed JSON files.",
            roots=(managed_root,),
            file_globs=("*.json",),
            validator_kind="json_parse",
        ),
        ConfigTarget(
            name="systemd_unit",
            description="Systemd unit files under /etc/systemd/system.",
            roots=(Path("/etc/systemd/system"),),
            file_globs=("*.service", "*.timer"),
            validator_kind="command",
            validator_command=("systemd-analyze", "verify", "{path}"),
        ),
    )
