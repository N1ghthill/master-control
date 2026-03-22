from collections.abc import Sequence

from master_control.host_validation import run_host_validation
from master_control.interfaces.cli import entrypoint as _entrypoint

build_parser = _entrypoint.build_parser


def main(argv: Sequence[str] | None = None) -> int:
    original = _entrypoint.run_host_validation
    _entrypoint.run_host_validation = run_host_validation
    try:
        return _entrypoint.main(argv)
    finally:
        _entrypoint.run_host_validation = original


__all__ = ["build_parser", "main", "run_host_validation"]
