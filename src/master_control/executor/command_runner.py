from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT_CHARS = 16_000


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    truncated_stdout: bool
    truncated_stderr: bool


class CommandExecutionError(RuntimeError):
    """Raised when a command cannot be executed safely."""


class CommandRunner:
    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: float = 5.0,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        safe_env = {
            "PATH": os.getenv("PATH", ""),
            "LANG": os.getenv("LANG", "C.UTF-8"),
            "LC_ALL": os.getenv("LC_ALL", "C.UTF-8"),
        }
        if env:
            safe_env.update(env)

        try:
            completed = subprocess.run(
                args,
                cwd=cwd,
                env=safe_env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except FileNotFoundError as exc:
            raise CommandExecutionError(f"Command not found: {args[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise CommandExecutionError(
                f"Command timed out after {timeout_s:.1f}s: {' '.join(args)}"
            ) from exc

        stdout = completed.stdout[:MAX_OUTPUT_CHARS]
        stderr = completed.stderr[:MAX_OUTPUT_CHARS]
        return CommandResult(
            returncode=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            truncated_stdout=len(completed.stdout) > MAX_OUTPUT_CHARS,
            truncated_stderr=len(completed.stderr) > MAX_OUTPUT_CHARS,
        )
