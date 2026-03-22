from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

MIN_PYTHON_VERSION = (3, 13)
OS_RELEASE_PATH = Path("/etc/os-release")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect Python bootstrap prerequisites for Master Control.",
    )
    parser.add_argument(
        "--python-bin",
        default="python3",
        help="Python interpreter to inspect. Default: python3.",
    )
    parser.add_argument(
        "--install-hint",
        action="store_true",
        help="Print only the actionable install hint if one is available.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Render diagnostics as JSON.",
    )
    return parser


def cli_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    diagnostics = collect_bootstrap_python_diagnostics(args.python_bin)
    if args.install_hint:
        hint = diagnostics.get("install_hint")
        if isinstance(hint, str) and hint:
            print(hint)
            return 0
        return 1
    if args.json:
        print(json.dumps(diagnostics, indent=2, sort_keys=True))
    else:
        print(diagnostics["summary"])
    return 0


def collect_bootstrap_python_diagnostics(python_bin: str = "python3") -> dict[str, object]:
    resolved_python = _resolve_python_bin(python_bin)
    os_release = _read_os_release()
    os_id = os_release.get("ID")

    if resolved_python is None:
        return {
            "python_bin": python_bin,
            "resolved_path": None,
            "python_found": False,
            "version": None,
            "meets_minimum": False,
            "ensurepip_available": False,
            "venv_ready": False,
            "os_id": os_id,
            "install_hint": None,
            "summary": f"{python_bin} not found on PATH.",
        }

    version_text = _python_version(resolved_python)
    version_tuple = _parse_version(version_text)
    meets_minimum = version_tuple is not None and version_tuple >= MIN_PYTHON_VERSION
    ensurepip_available = _ensurepip_available(resolved_python)
    install_hint = None

    if meets_minimum and not ensurepip_available:
        install_hint = _install_hint(os_id=os_id, version_text=version_text)

    summary = _build_summary(
        python_bin=python_bin,
        version_text=version_text,
        meets_minimum=meets_minimum,
        ensurepip_available=ensurepip_available,
        install_hint=install_hint,
    )

    return {
        "python_bin": python_bin,
        "resolved_path": resolved_python,
        "python_found": True,
        "version": version_text,
        "meets_minimum": meets_minimum,
        "ensurepip_available": ensurepip_available,
        "venv_ready": meets_minimum and ensurepip_available,
        "os_id": os_id,
        "install_hint": install_hint,
        "summary": summary,
    }


def _resolve_python_bin(python_bin: str) -> str | None:
    candidate = Path(python_bin)
    if candidate.is_absolute() and candidate.exists():
        return str(candidate)
    return shutil.which(python_bin)


def _python_version(resolved_python: str) -> str | None:
    try:
        completed = subprocess.run(
            [
                resolved_python,
                "-c",
                (
                    "import sys; "
                    "print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
                ),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    version_text = completed.stdout.strip()
    return version_text or None


def _ensurepip_available(resolved_python: str) -> bool:
    try:
        completed = subprocess.run(
            [resolved_python, "-c", "import ensurepip"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return completed.returncode == 0


def _read_os_release(path: Path = OS_RELEASE_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    payload: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", maxsplit=1)
        payload[key] = value.strip().strip('"')
    return payload


def _parse_version(version_text: str | None) -> tuple[int, int] | None:
    if not isinstance(version_text, str):
        return None
    parts = version_text.split(".")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _install_hint(*, os_id: str | None, version_text: str | None) -> str:
    version_tuple = _parse_version(version_text)
    if os_id in {"debian", "ubuntu"} and version_tuple is not None:
        major, minor = version_tuple
        return f"run: apt install python{major}.{minor}-venv"
    return "install the matching stdlib venv package or virtualenv for this interpreter"


def _build_summary(
    *,
    python_bin: str,
    version_text: str | None,
    meets_minimum: bool,
    ensurepip_available: bool,
    install_hint: str | None,
) -> str:
    if version_text is None:
        return f"{python_bin} is present but its version could not be determined."
    if not meets_minimum:
        minimum = ".".join(str(item) for item in MIN_PYTHON_VERSION)
        return f"{python_bin} {version_text} found; MC requires Python {minimum}+."
    if ensurepip_available:
        return f"{python_bin} {version_text} ready for stdlib venv bootstrap."
    if install_hint:
        return f"{python_bin} {version_text} found, but stdlib venv is unavailable; {install_hint}."
    return f"{python_bin} {version_text} found, but stdlib venv is unavailable."


if __name__ == "__main__":
    raise SystemExit(cli_main())
