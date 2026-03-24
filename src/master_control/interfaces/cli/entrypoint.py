from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import Any, cast

from master_control.config import Settings
from master_control.core.runtime import MasterControlRuntime
from master_control.host_validation import run_host_validation
from master_control.interfaces.agent.chat import MasterControlChatInterface
from master_control.interfaces.mcp.server import MasterControlMCPServer
from master_control.logging_utils import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mc",
        description="Master Control CLI bootstrap.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Render supported output as JSON.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_host_parser = subparsers.add_parser(
        "validate-host-profile",
        help="Run the bounded host-profile validation and write a JSON report.",
    )
    validate_host_parser.add_argument(
        "--output-dir",
        default="artifacts/host-validation",
        help="Directory where the validation report will be written.",
    )
    validate_host_parser.add_argument(
        "--provider",
        default="heuristic",
        help="MC provider to use for host validation. Default: heuristic.",
    )
    validate_host_parser.add_argument(
        "--run-baseline",
        action="store_true",
        help="Also rerun the engineering baseline commands on this host.",
    )
    subparsers.add_parser("doctor", help="Validate local bootstrap state.")
    subparsers.add_parser("tools", help="List registered tools.")
    audit_parser = subparsers.add_parser("audit", help="Show recent audit events.")
    audit_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of events to return.",
    )

    sessions_parser = subparsers.add_parser("sessions", help="List known chat sessions.")
    sessions_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of sessions to return.",
    )

    insights_parser = subparsers.add_parser(
        "insights", help="Show proactive insights for a session."
    )
    insights_parser.add_argument(
        "--session-id",
        type=int,
        help="Target session id. Defaults to the latest known session.",
    )

    observations_parser = subparsers.add_parser(
        "observations",
        help="Show stored observations and freshness for a session.",
    )
    observations_parser.add_argument(
        "--session-id",
        type=int,
        help="Target session id. Defaults to the latest known session.",
    )
    observations_parser.add_argument(
        "--stale-only",
        action="store_true",
        help="Show only stale observations.",
    )

    recommendations_parser = subparsers.add_parser(
        "recommendations",
        help="Show tracked recommendations for a session.",
    )
    recommendations_parser.add_argument(
        "--session-id",
        type=int,
        help="Target session id. Defaults to the latest known session.",
    )
    recommendations_parser.add_argument(
        "--status",
        choices=["open", "accepted", "dismissed", "resolved"],
        help="Filter recommendations by status.",
    )

    reconcile_parser = subparsers.add_parser(
        "reconcile",
        help="Recompute recommendation state from summaries and observation freshness.",
    )
    reconcile_group = reconcile_parser.add_mutually_exclusive_group()
    reconcile_group.add_argument(
        "--session-id",
        type=int,
        help="Target session id. Defaults to the latest known session.",
    )
    reconcile_group.add_argument(
        "--all",
        action="store_true",
        help="Reconcile all known sessions.",
    )

    recommendation_parser = subparsers.add_parser(
        "recommendation",
        help="Update the status of a recommendation.",
    )
    recommendation_parser.add_argument("id", type=int, help="Recommendation id.")
    recommendation_parser.add_argument(
        "status",
        choices=["open", "accepted", "dismissed", "resolved"],
        help="New recommendation status.",
    )

    recommendation_run_parser = subparsers.add_parser(
        "recommendation-run",
        help="Execute the suggested action for an accepted recommendation.",
    )
    recommendation_run_parser.add_argument("id", type=int, help="Recommendation id.")
    recommendation_run_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Explicitly confirm execution for mutating or privileged actions.",
    )

    tool_parser = subparsers.add_parser("tool", help="Run a registered tool.")
    tool_parser.add_argument("name", help="Tool name.")
    tool_parser.add_argument(
        "--arg",
        action="append",
        default=[],
        help="Tool argument in key=value format. Can be repeated.",
    )
    tool_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Explicitly confirm execution for mutating or privileged tools.",
    )

    chat_parser = subparsers.add_parser("chat", help="Start the bootstrap chat loop.")
    chat_parser.add_argument(
        "--once",
        help="Process one message and exit.",
    )
    chat_session_group = chat_parser.add_mutually_exclusive_group()
    chat_session_group.add_argument(
        "--session-id",
        type=int,
        help="Resume an existing session by id.",
    )
    chat_session_group.add_argument(
        "--new-session",
        action="store_true",
        help="Force creation of a new session.",
    )
    chat_session_group.add_argument(
        "--continue-latest",
        action="store_true",
        help="Resume the latest known session.",
    )

    timer_parser = subparsers.add_parser(
        "reconcile-timer",
        help="Render or manage the systemd timer that runs `mc reconcile --all`.",
    )
    timer_subparsers = timer_parser.add_subparsers(dest="timer_command", required=True)

    timer_render = timer_subparsers.add_parser(
        "render", help="Render unit files without installing."
    )
    timer_install = timer_subparsers.add_parser(
        "install", help="Install and enable the reconcile timer."
    )
    timer_remove = timer_subparsers.add_parser(
        "remove", help="Disable and remove the reconcile timer."
    )

    for subparser in (timer_render, timer_install, timer_remove):
        subparser.add_argument(
            "--scope",
            choices=["user", "system"],
            default="user",
            help="systemd scope for the unit files.",
        )
        subparser.add_argument(
            "--target-dir",
            help="Override the unit directory. Useful for dry runs and tests.",
        )

    for subparser in (timer_render, timer_install):
        subparser.add_argument(
            "--on-calendar",
            default="hourly",
            help="systemd OnCalendar expression for the timer.",
        )
        subparser.add_argument(
            "--randomized-delay",
            default="5m",
            help="systemd RandomizedDelaySec value.",
        )
        subparser.add_argument(
            "--python",
            help="Override the Python executable used in ExecStart.",
        )

    timer_install.add_argument(
        "--skip-systemctl",
        action="store_true",
        help="Write unit files without running systemctl daemon-reload/enable.",
    )
    timer_remove.add_argument(
        "--skip-systemctl",
        action="store_true",
        help="Remove unit files without running systemctl disable/daemon-reload.",
    )

    subparsers.add_parser(
        "mcp-serve",
        help="Run the experimental MCP interface with approval-mediated write operations.",
    )
    return parser


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _parse_kv_arguments(items: list[str]) -> dict[str, object]:
    arguments: dict[str, object] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"Invalid --arg value: {item!r}. Expected key=value.")
        key, value = item.split("=", maxsplit=1)
        key = key.strip()
        if not key:
            raise ValueError("Argument keys cannot be empty.")
        arguments[key] = value.strip()
    return arguments


def _format_observation_duration(seconds: object) -> str:
    if not isinstance(seconds, int):
        return "-"
    if seconds < 60:
        return f"{seconds}s"
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{rem:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _render_observation_target(item: dict[str, Any]) -> str | None:
    value = item.get("value")
    if not isinstance(value, dict):
        return None
    for key in ("service", "path", "unit"):
        target = value.get(key)
        if isinstance(target, str) and target:
            return target
    return None


def _format_recommendation_action(item: dict[str, Any]) -> str | None:
    action = item.get("action")
    if not isinstance(action, dict):
        return None
    tool_name = action.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name:
        return None
    arguments = action.get("arguments")
    if isinstance(arguments, dict) and arguments:
        rendered_arguments = " ".join(f"{key}={value}" for key, value in arguments.items())
        return f"{tool_name} {rendered_arguments}"
    return tool_name


def _render_timer_payload(payload: dict[str, Any]) -> None:
    print(f"scope={payload['scope']}")
    service = payload.get("service")
    timer = payload.get("timer")
    service_path = payload.get("service_path")
    timer_path = payload.get("timer_path")
    if isinstance(service, dict):
        service_path = service.get("path")
    if isinstance(timer, dict):
        timer_path = timer.get("path")
    if isinstance(service_path, str):
        print(f"service: {service_path}")
    if isinstance(timer_path, str):
        print(f"timer:   {timer_path}")
    if "on_calendar" in payload:
        print(f"schedule: {payload['on_calendar']} randomized={payload['randomized_delay']}")


def _render_timer_units(payload: dict[str, Any]) -> None:
    _render_timer_payload(payload)
    print()
    service = cast(dict[str, Any], payload["service"])
    timer = cast(dict[str, Any], payload["timer"])
    print(f"# {service['name']}")
    print(service["content"], end="")
    print()
    print(f"# {timer['name']}")
    print(timer["content"], end="")


def _render_host_validation_payload(payload: dict[str, Any]) -> None:
    print("Master Control host validation")
    print(f"report:    {payload['report_path']}")
    print(f"overall:   {'ok' if payload['overall_ok'] else 'failed'}")

    host_profile = payload.get("host_profile")
    if isinstance(host_profile, dict):
        hostname = host_profile.get("hostname")
        system = host_profile.get("system")
        release = host_profile.get("release")
        if isinstance(hostname, str) and hostname:
            host_summary = hostname
            if isinstance(system, str) and system:
                host_summary = f"{host_summary} ({system}"
                if isinstance(release, str) and release:
                    host_summary = f"{host_summary} {release}"
                host_summary = f"{host_summary})"
            print(f"host:      {host_summary}")

    settings_payload = payload.get("settings")
    if isinstance(settings_payload, dict):
        provider = settings_payload.get("provider")
        if isinstance(provider, str) and provider:
            print(f"provider:  {provider}")

    baseline = payload.get("baseline")
    if isinstance(baseline, dict):
        if baseline.get("enabled"):
            print(f"baseline:  {'ok' if baseline.get('all_ok') else 'failed'}")
        else:
            print("baseline:  skipped")

    workflows = payload.get("workflows")
    if isinstance(workflows, dict) and workflows:
        rendered_statuses: list[str] = []
        for key, item in workflows.items():
            status = "failed"
            if isinstance(item, dict) and item.get("ok"):
                status = "ok"
            rendered_statuses.append(f"{key}={status}")
        print(f"workflows: {', '.join(rendered_statuses)}")

        failures = [
            (key, item)
            for key, item in workflows.items()
            if isinstance(item, dict) and not item.get("ok")
        ]
        if failures:
            failed_key, failed_payload = failures[0]
            error = failed_payload.get("error")
            if isinstance(error, str) and error:
                print(f"detail:    {failed_key} -> {error}")


def _run_chat(
    chat: MasterControlChatInterface,
    once: str | None,
    *,
    as_json: bool = False,
    session_id: int | None = None,
    new_session: bool = False,
) -> int:
    if once is not None:
        if once.startswith("/"):
            chat.start_chat_session(session_id=session_id, new_session=new_session)
            command_output = chat.handle_message(once)
            print(command_output)
        else:
            chat_payload: dict[str, Any] = chat.chat(
                once,
                session_id=session_id,
                new_session=new_session,
            )
            if as_json:
                _print_json(chat_payload)
            else:
                print(chat_payload["message"])
        return 0

    active_session_id = chat.start_chat_session(session_id=session_id, new_session=new_session)
    print(f"Master Control chat. Session {active_session_id}. Type /help or exit.")
    while True:
        try:
            user_input = input("mc> ").strip()
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            return 130

        if user_input in {"exit", "quit"}:
            return 0
        if not user_input:
            continue
        print(chat.handle_message(user_input))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    configure_logging(settings.log_level)

    if args.command == "validate-host-profile":
        validation_result = run_host_validation(
            output_dir=args.output_dir,
            provider=args.provider,
            run_baseline=args.run_baseline,
            base_settings=settings,
        )
        if args.json:
            _print_json(validation_result.report)
        else:
            _render_host_validation_payload(validation_result.report)
        return 0 if validation_result.report["overall_ok"] else 1

    runtime = MasterControlRuntime(settings)
    chat = MasterControlChatInterface(runtime)

    if args.command == "doctor":
        doctor_payload: dict[str, Any] = runtime.doctor()
        if args.json:
            _print_json(doctor_payload)
        else:
            print("Master Control doctor")
            print(f"state_dir: {doctor_payload['state_dir']}")
            print(f"db_path:   {doctor_payload['db_path']}")
            print(
                f"provider:  {doctor_payload['provider']} -> {doctor_payload['provider_backend']}"
            )
            print(f"planner:   {doctor_payload['planner_mode']}")
            print(f"llm_ready: {'yes' if doctor_payload['llm_provider_available'] else 'no'}")
            store_diagnostics = cast(dict[str, Any], doctor_payload["store_diagnostics"])
            store_status = "ok" if store_diagnostics["ok"] else "error"
            print(
                "store:     "
                f"{store_status} journal={store_diagnostics['journal_mode']} "
                f"integrity={store_diagnostics['integrity_check']}"
            )
            policy_diagnostics = cast(dict[str, Any], doctor_payload["policy_diagnostics"])
            print(f"policy:    {policy_diagnostics['summary']}")
            bootstrap_diagnostics = cast(
                dict[str, Any],
                doctor_payload["bootstrap_python_diagnostics"],
            )
            print(f"bootstrap: {bootstrap_diagnostics['summary']}")
            timer_diagnostics = cast(dict[str, Any], doctor_payload["reconcile_timer_diagnostics"])
            timer_summary = "ready" if timer_diagnostics["available"] else "missing systemctl"
            if not timer_diagnostics["user_scope_ready"]:
                missing = ", ".join(cast(list[str], timer_diagnostics["user_scope_missing_env"]))
                timer_summary = f"{timer_summary}; user_env_missing={missing}"
            print(f"timer:     {timer_summary}")
            active_check = cast(dict[str, Any], doctor_payload["active_provider_check"])
            print(f"active:    {active_check['summary']}")
            provider_checks = cast(dict[str, Any], doctor_payload["provider_checks"])
            for name in ("ollama", "openai"):
                check = cast(dict[str, Any], provider_checks[name])
                print(f"{name}:    {check['summary']}")
            print(f"audit:     {doctor_payload['audit_event_count']}")
            print(f"sessions:  {doctor_payload['session_count']}")
            tools = cast(list[str], doctor_payload["tools"])
            print(f"tools:     {', '.join(tools)}")
        return 0 if doctor_payload["ok"] else 1

    if args.command == "tools":
        runtime.bootstrap()
        tools_payload: list[dict[str, Any]] = [spec.as_dict() for spec in runtime.list_tools()]
        if args.json:
            _print_json(tools_payload)
        else:
            for spec in tools_payload:
                arguments = ", ".join(cast(list[str], spec["arguments"])) or "-"
                print(f"{spec['name']}({arguments}): {spec['risk']} - {spec['description']}")
        return 0

    if args.command == "audit":
        audit_payload = runtime.list_audit_events(limit=args.limit)
        _print_json(audit_payload)
        return 0

    if args.command == "sessions":
        sessions_payload = runtime.list_sessions(limit=args.limit)
        _print_json(sessions_payload)
        return 0

    if args.command == "insights":
        try:
            insights_payload = runtime.get_session_insights(session_id=args.session_id)
        except ValueError as exc:
            parser.error(str(exc))
            return 2
        _print_json(insights_payload)
        return 0

    if args.command == "observations":
        try:
            observations_payload: dict[str, Any] = runtime.list_session_observations(
                session_id=args.session_id,
                stale_only=args.stale_only,
            )
        except ValueError as exc:
            parser.error(str(exc))
            return 2
        if args.json:
            _print_json(observations_payload)
        else:
            print(f"Session {observations_payload['session_id']} observations")
            print(
                "total="
                f"{observations_payload['total_count']} "
                f"fresh={observations_payload['fresh_count']} "
                f"stale={observations_payload['stale_count']}"
            )
            if not observations_payload["observations"]:
                if observations_payload["stale_only"]:
                    print("No stale observations matched this session.")
                else:
                    print("No stored observations for this session yet.")
                return 0
            observations = cast(list[dict[str, Any]], observations_payload["observations"])
            for item in observations:
                status = "stale" if item["stale"] else "fresh"
                target = _render_observation_target(item)
                target_text = f" target={target}" if target else ""
                print(
                    f"{item['key']}: {status} age={_format_observation_duration(item['age_seconds'])} "
                    f"ttl={_format_observation_duration(item['ttl_seconds'])} "
                    f"source={item['source']}{target_text}"
                )
        return 0

    if args.command == "recommendations":
        try:
            recommendations_payload: dict[str, Any] = runtime.list_session_recommendations(
                session_id=args.session_id,
                status=args.status,
            )
        except ValueError as exc:
            parser.error(str(exc))
            return 2
        if args.json:
            _print_json(recommendations_payload)
        else:
            print(f"Session {recommendations_payload['session_id']} recommendations")
            if recommendations_payload["status_filter"]:
                print(f"filter={recommendations_payload['status_filter']}")
            if not recommendations_payload["recommendations"]:
                print("No recommendations matched this session.")
                return 0
            recommendations = cast(
                list[dict[str, Any]],
                recommendations_payload["recommendations"],
            )
            for item in recommendations:
                print(
                    f"#{item['id']} [{item['status']} {item['severity']}] "
                    f"{item['source_key']} confidence={item.get('confidence', 'unknown')}"
                )
                print(item["message"])
                evidence = item.get("evidence_summary")
                if isinstance(evidence, str) and evidence.strip():
                    print(f"evidence: {evidence}")
                target_summary = item.get("target_summary")
                if isinstance(target_summary, str) and target_summary.strip():
                    print(f"target: {target_summary}")
                freshness = item.get("signal_freshness")
                if isinstance(freshness, dict):
                    print(
                        "signal:"
                        f" {freshness.get('observation_key')} "
                        f"status={freshness.get('status')} "
                        f"age={_format_observation_duration(freshness.get('age_seconds'))} "
                        f"ttl={_format_observation_duration(freshness.get('ttl_seconds'))}"
                    )
                action_text = _format_recommendation_action(item)
                if action_text:
                    print(f"action: {action_text}")
                next_step = item.get("next_step")
                if isinstance(next_step, dict):
                    summary = next_step.get("summary")
                    cli_command = next_step.get("cli_command")
                    if isinstance(summary, str) and summary.strip():
                        print(f"next: {summary}")
                    if isinstance(cli_command, str) and cli_command.strip():
                        print(f"next_cli: {cli_command}")
        return 0

    if args.command == "reconcile":
        try:
            reconcile_payload: dict[str, Any] = runtime.reconcile_recommendations(
                session_id=args.session_id,
                all_sessions=args.all,
            )
        except ValueError as exc:
            parser.error(str(exc))
            return 2
        if args.json:
            _print_json(reconcile_payload)
        else:
            print(
                f"Reconcile mode={reconcile_payload['mode']} "
                f"sessions={reconcile_payload['session_count']}"
            )
            sessions = cast(list[dict[str, Any]], reconcile_payload["sessions"])
            for item in sessions:
                print(
                    f"session={item['session_id']} "
                    f"insights={item['insight_count']} "
                    f"observations={item['observation_count']} "
                    f"stale={item['stale_observation_count']} "
                    f"active={item['active_count']} "
                    f"new={item['new_count']} "
                    f"reopened={item['reopened_count']} "
                    f"resolved={item['auto_resolved_count']}"
                )
        return 0

    if args.command == "recommendation":
        try:
            recommendation_payload: dict[str, Any] = runtime.update_recommendation_status(
                args.id,
                args.status,
            )
        except ValueError as exc:
            parser.error(str(exc))
            return 2
        _print_json(recommendation_payload)
        return 0

    if args.command == "recommendation-run":
        try:
            recommendation_run_payload: dict[str, Any] = runtime.run_recommendation_action(
                args.id,
                confirmed=args.confirm,
            )
        except ValueError as exc:
            parser.error(str(exc))
            return 2
        _print_json(recommendation_run_payload)
        return 0

    if args.command == "tool":
        try:
            tool_payload: dict[str, Any] = runtime.run_tool(
                args.name,
                _parse_kv_arguments(args.arg),
                confirmed=args.confirm,
                audit_context={"source": "tool_command"},
            )
        except ValueError as exc:
            parser.error(str(exc))
            return 2

        _print_json(tool_payload)
        return 0

    if args.command == "chat":
        runtime.bootstrap()
        try:
            session_id = args.session_id
            if args.continue_latest:
                session_id = runtime.latest_session_id()
            return _run_chat(
                chat,
                args.once,
                as_json=args.json,
                session_id=session_id,
                new_session=args.new_session,
            )
        except ValueError as exc:
            parser.error(str(exc))
            return 2

    if args.command == "reconcile-timer":
        try:
            timer_payload: dict[str, Any]
            if args.timer_command == "render":
                timer_payload = runtime.render_reconcile_timer(
                    scope=args.scope,
                    on_calendar=args.on_calendar,
                    randomized_delay=args.randomized_delay,
                    target_dir=args.target_dir,
                    python_executable=args.python,
                )
            elif args.timer_command == "install":
                timer_payload = runtime.install_reconcile_timer(
                    scope=args.scope,
                    on_calendar=args.on_calendar,
                    randomized_delay=args.randomized_delay,
                    target_dir=args.target_dir,
                    python_executable=args.python,
                    run_systemctl=not args.skip_systemctl,
                )
            elif args.timer_command == "remove":
                timer_payload = runtime.remove_reconcile_timer(
                    scope=args.scope,
                    target_dir=args.target_dir,
                    run_systemctl=not args.skip_systemctl,
                )
            else:
                parser.error("Unknown reconcile-timer command.")
                return 2
        except ValueError as exc:
            parser.error(str(exc))
            return 2

        if args.json:
            _print_json(timer_payload)
        elif args.timer_command == "render":
            _render_timer_units(timer_payload)
        else:
            _render_timer_payload(timer_payload)
            if args.timer_command == "remove":
                removed = timer_payload.get("removed_paths", [])
                if not isinstance(removed, list):
                    removed = []
                print(f"removed={len(removed)}")
        return 0

    if args.command == "mcp-serve":
        runtime.bootstrap()
        MasterControlMCPServer(runtime).run()
        return 0

    parser.error("Unknown command.")
    return 2
