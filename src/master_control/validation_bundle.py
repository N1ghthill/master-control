from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ABSOLUTE_PATH_RE = re.compile(r"(?:(?<=^)|(?<=[\s(=:'\"`]))/(?:[^/\s'\"`]+/)*[^/\s'\"`]+")


@dataclass(frozen=True, slots=True)
class ValidationBundleArtifacts:
    report_path: Path
    bundle_dir: Path
    archive_path: Path
    redacted_report_path: Path
    summary_path: Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a redacted host-validation bundle that can be attached to a GitHub issue."
        ),
    )
    parser.add_argument(
        "--report",
        help="Exact host-validation report.json path to bundle.",
    )
    parser.add_argument(
        "--latest-under",
        default=str(Path.cwd() / "artifacts" / "host-validation"),
        help=(
            "Directory that contains timestamped host-validation runs. "
            "Used when --report is not provided."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path.cwd() / "artifacts" / "validation-bundles"),
        help="Directory where the redacted bundle and zip archive will be written.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the generated artifact paths as JSON.",
    )
    return parser


def cli_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report_path = resolve_report_path(report=args.report, latest_under=args.latest_under)
    artifacts = create_validation_bundle(report_path=report_path, output_dir=args.output_dir)
    if args.json:
        print(
            json.dumps(
                {
                    "report_path": str(artifacts.report_path),
                    "bundle_dir": str(artifacts.bundle_dir),
                    "archive_path": str(artifacts.archive_path),
                    "redacted_report_path": str(artifacts.redacted_report_path),
                    "summary_path": str(artifacts.summary_path),
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(f"report:          {artifacts.report_path}")
        print(f"bundle_dir:      {artifacts.bundle_dir}")
        print(f"archive:         {artifacts.archive_path}")
        print(f"redacted_report: {artifacts.redacted_report_path}")
        print(f"summary:         {artifacts.summary_path}")
    return 0


def resolve_report_path(*, report: str | Path | None, latest_under: str | Path) -> Path:
    if report:
        report_path = Path(report).expanduser().resolve()
        if not report_path.is_file():
            raise ValueError(f"report.json not found: {report_path}")
        return report_path

    search_root = Path(latest_under).expanduser().resolve()
    report_paths = sorted(search_root.glob("*/report.json"))
    if not report_paths:
        raise ValueError(f"no host-validation report.json found under {search_root}")
    return report_paths[-1]


def create_validation_bundle(
    *,
    report_path: str | Path,
    output_dir: str | Path,
) -> ValidationBundleArtifacts:
    resolved_report_path = Path(report_path).expanduser().resolve()
    report = _load_report(resolved_report_path)

    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    bundle_name = _build_bundle_name(report, resolved_report_path)
    bundle_dir = output_root / bundle_name
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    redacted_report = redact_host_validation_report(report)
    redacted_report_path = bundle_dir / "report.redacted.json"
    redacted_report_path.write_text(
        json.dumps(redacted_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    summary_path = bundle_dir / "SUMMARY.md"
    summary_path.write_text(render_validation_summary(redacted_report), encoding="utf-8")

    archive_path = Path(
        shutil.make_archive(
            str(bundle_dir),
            "zip",
            root_dir=bundle_dir.parent,
            base_dir=bundle_dir.name,
        )
    )

    return ValidationBundleArtifacts(
        report_path=resolved_report_path,
        bundle_dir=bundle_dir,
        archive_path=archive_path,
        redacted_report_path=redacted_report_path,
        summary_path=summary_path,
    )


def redact_host_validation_report(report: dict[str, Any]) -> dict[str, Any]:
    hostname = _string_at(report, ("host_profile", "hostname"))
    replacements = _build_redaction_replacements(report)
    redacted = _redact_value(report, replacements=replacements, hostname=hostname)
    if not isinstance(redacted, dict):
        raise ValueError("redacted report must remain a JSON object")
    return redacted


def render_validation_summary(report: dict[str, Any]) -> str:
    host_profile = report.get("host_profile")
    settings = report.get("settings")
    workflows = report.get("workflows")
    baseline = report.get("baseline")
    if not isinstance(host_profile, dict) or not isinstance(settings, dict):
        raise ValueError("report is missing host_profile or settings")
    if not isinstance(workflows, dict) or not isinstance(baseline, dict):
        raise ValueError("report is missing workflows or baseline")

    lines = [
        "# Host Validation Summary",
        "",
        "This summary is generated from `report.redacted.json`.",
        "Review the files before sharing them publicly.",
        "",
        "## Snapshot",
        "",
        f"- overall_ok: {bool(report.get('overall_ok'))}",
        f"- system: {_string_or_fallback(host_profile.get('system'), 'unknown')}",
        f"- release: {_string_or_fallback(host_profile.get('release'), 'unknown')}",
        f"- python: {_string_or_fallback(host_profile.get('python'), 'unknown')}",
        f"- provider: {_string_or_fallback(settings.get('provider'), 'unknown')}",
        f"- baseline_enabled: {bool(baseline.get('enabled'))}",
        f"- baseline_all_ok: {bool(baseline.get('all_ok'))}",
        "",
        "## Workflow Results",
        "",
    ]
    for workflow_name in ("slow_host", "failed_service", "managed_config"):
        item = workflows.get(workflow_name)
        if not isinstance(item, dict):
            continue
        lines.append(_render_workflow_summary(workflow_name, item))

    caveat_lines = _render_caveats(workflows)
    if caveat_lines:
        lines.extend(("", "## Caveats", "", *caveat_lines))

    lines.extend(
        (
            "",
            "## Share",
            "",
            "- Attach the generated `.zip` bundle or `report.redacted.json` to the GitHub issue.",
            "- Paste this summary into the issue body.",
            "- Say whether the host is bare metal, live USB or external SSD, VM, container, or another setup.",
        )
    )
    return "\n".join(lines) + "\n"


def _render_workflow_summary(name: str, item: dict[str, Any]) -> str:
    status = "ok" if bool(item.get("ok")) else "not_ok"
    fragments = [f"- {name}: {status}"]

    executed_tools = item.get("executed_tools")
    if isinstance(executed_tools, list) and executed_tools:
        rendered_tools = ", ".join(str(tool) for tool in executed_tools)
        fragments.append(f"tools={rendered_tools}")

    if name == "failed_service":
        payload = item.get("failed_services_tool")
        if isinstance(payload, dict):
            unit_count = payload.get("unit_count")
            if isinstance(unit_count, int):
                fragments.append(f"unit_count={unit_count}")

    if name == "managed_config":
        recommendation_keys = item.get("recommendation_keys_after_write")
        if isinstance(recommendation_keys, list) and recommendation_keys:
            rendered_keys = ", ".join(str(key) for key in recommendation_keys)
            fragments.append(f"post_write_recommendations={rendered_keys}")

    return "; ".join(fragments)


def _render_caveats(workflows: dict[str, Any]) -> list[str]:
    caveats: list[str] = []
    for workflow_name, item in workflows.items():
        if not isinstance(item, dict):
            continue
        notes = item.get("notes")
        if not isinstance(notes, list):
            continue
        for note in notes:
            if isinstance(note, str) and note.strip():
                caveats.append(f"- {workflow_name}: {note.strip()}")
    return caveats


def _build_bundle_name(report: dict[str, Any], report_path: Path) -> str:
    generated_at = report.get("generated_at")
    if isinstance(generated_at, str):
        try:
            timestamp = (
                datetime.fromisoformat(generated_at)
                .astimezone(timezone.utc)
                .strftime("%Y%m%dT%H%M%SZ")
            )
            return f"host-validation-bundle-{timestamp}"
        except ValueError:
            pass
    return f"host-validation-bundle-{report_path.parent.name}"


def _load_report(report_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"report.json did not contain valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("report.json must contain a JSON object")
    return payload


def _build_redaction_replacements(report: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    candidates = (
        (("repo_root",), "<repo-root>"),
        (("run_dir",), "<validation-run>"),
        (("report_path",), "<report-path>"),
        (("settings", "state_dir"), "<state-dir>"),
        (("settings", "db_path"), "<db-path>"),
        (("doctor", "state_dir"), "<state-dir>"),
        (("doctor", "db_path"), "<db-path>"),
        (("doctor", "store_diagnostics", "path"), "<db-path>"),
        (("workflows", "managed_config", "config_path"), "<managed-config-path>"),
        (("workflows", "managed_config", "backup_path"), "<managed-config-backup>"),
    )
    unique: dict[str, str] = {}
    for path, placeholder in candidates:
        value = _string_at(report, path)
        if value:
            unique[value] = placeholder
    return tuple(
        sorted(
            unique.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        )
    )


def _redact_value(
    value: object,
    *,
    replacements: tuple[tuple[str, str], ...],
    hostname: str | None,
) -> object:
    if isinstance(value, dict):
        return {
            key: _redact_value(
                item,
                replacements=replacements,
                hostname=hostname,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _redact_value(
                item,
                replacements=replacements,
                hostname=hostname,
            )
            for item in value
        ]
    if isinstance(value, str):
        return _redact_text(value, replacements=replacements, hostname=hostname)
    return value


def _redact_text(
    text: str,
    *,
    replacements: tuple[tuple[str, str], ...],
    hostname: str | None,
) -> str:
    rendered = text
    for source, replacement in replacements:
        rendered = rendered.replace(source, replacement)
    if hostname:
        rendered = rendered.replace(hostname, "<redacted-host>")
    return ABSOLUTE_PATH_RE.sub("<abs-path>", rendered)


def _string_at(payload: dict[str, Any], path: tuple[str, ...]) -> str | None:
    current: object = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current if isinstance(current, str) and current else None


def _string_or_fallback(value: object, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    return fallback
