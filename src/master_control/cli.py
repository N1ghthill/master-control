from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from master_control.app import MasterControlApp
from master_control.config import Settings
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

    insights_parser = subparsers.add_parser("insights", help="Show proactive insights for a session.")
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
    chat_parser.add_argument(
        "--session-id",
        type=int,
        help="Resume an existing session by id.",
    )
    chat_parser.add_argument(
        "--new-session",
        action="store_true",
        help="Force creation of a new session.",
    )

    timer_parser = subparsers.add_parser(
        "reconcile-timer",
        help="Render or manage the systemd timer that runs `mc reconcile --all`.",
    )
    timer_subparsers = timer_parser.add_subparsers(dest="timer_command", required=True)

    timer_render = timer_subparsers.add_parser("render", help="Render unit files without installing.")
    timer_install = timer_subparsers.add_parser("install", help="Install and enable the reconcile timer.")
    timer_remove = timer_subparsers.add_parser("remove", help="Disable and remove the reconcile timer.")

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
    return parser


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _parse_kv_arguments(items: list[str]) -> dict[str, str]:
    arguments: dict[str, str] = {}
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


def _render_observation_target(item: dict[str, object]) -> str | None:
    value = item.get("value")
    if not isinstance(value, dict):
        return None
    for key in ("service", "path", "unit"):
        target = value.get(key)
        if isinstance(target, str) and target:
            return target
    return None


def _format_recommendation_action(item: dict[str, object]) -> str | None:
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


def _render_timer_payload(payload: dict[str, object]) -> None:
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


def _render_timer_units(payload: dict[str, object]) -> None:
    _render_timer_payload(payload)
    print()
    print(f"# {payload['service']['name']}")
    print(payload["service"]["content"], end="")
    print()
    print(f"# {payload['timer']['name']}")
    print(payload["timer"]["content"], end="")


def _run_chat(
    app: MasterControlApp,
    once: str | None,
    *,
    as_json: bool = False,
    session_id: int | None = None,
    new_session: bool = False,
) -> int:
    if once is not None:
        if once.startswith("/"):
            app.start_chat_session(session_id=session_id, new_session=new_session)
            payload = app.handle_message(once)
            print(payload)
        else:
            payload = app.chat(once, session_id=session_id, new_session=new_session)
            if as_json:
                _print_json(payload)
            else:
                print(payload["message"])
        return 0

    active_session_id = app.start_chat_session(session_id=session_id, new_session=new_session)
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
        print(app.handle_message(user_input))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    configure_logging(settings.log_level)
    app = MasterControlApp(settings)

    if args.command == "doctor":
        payload = app.doctor()
        if args.json:
            _print_json(payload)
        else:
            print("Master Control doctor")
            print(f"state_dir: {payload['state_dir']}")
            print(f"db_path:   {payload['db_path']}")
            print(f"provider:  {payload['provider']} -> {payload['provider_backend']}")
            print(f"planner:   {payload['planner_mode']}")
            print(f"llm_ready: {'yes' if payload['llm_provider_available'] else 'no'}")
            active_check = payload["active_provider_check"]
            print(f"active:    {active_check['summary']}")
            for name in ("ollama", "openai"):
                check = payload["provider_checks"][name]
                print(f"{name}:    {check['summary']}")
            print(f"audit:     {payload['audit_event_count']}")
            print(f"sessions:  {payload['session_count']}")
            print(f"tools:     {', '.join(payload['tools'])}")
        return 0 if payload["ok"] else 1

    if args.command == "tools":
        app.bootstrap()
        payload = [spec.as_dict() for spec in app.list_tools()]
        if args.json:
            _print_json(payload)
        else:
            for spec in payload:
                arguments = ", ".join(spec["arguments"]) or "-"
                print(
                    f"{spec['name']}({arguments}): {spec['risk']} - {spec['description']}"
                )
        return 0

    if args.command == "audit":
        payload = app.list_audit_events(limit=args.limit)
        _print_json(payload)
        return 0

    if args.command == "sessions":
        payload = app.list_sessions(limit=args.limit)
        _print_json(payload)
        return 0

    if args.command == "insights":
        try:
            payload = app.get_session_insights(session_id=args.session_id)
        except ValueError as exc:
            parser.error(str(exc))
            return 2
        _print_json(payload)
        return 0

    if args.command == "observations":
        try:
            payload = app.list_session_observations(
                session_id=args.session_id,
                stale_only=args.stale_only,
            )
        except ValueError as exc:
            parser.error(str(exc))
            return 2
        if args.json:
            _print_json(payload)
        else:
            print(f"Session {payload['session_id']} observations")
            print(
                f"total={payload['total_count']} fresh={payload['fresh_count']} stale={payload['stale_count']}"
            )
            if not payload["observations"]:
                if payload["stale_only"]:
                    print("No stale observations matched this session.")
                else:
                    print("No stored observations for this session yet.")
                return 0
            for item in payload["observations"]:
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
            payload = app.list_session_recommendations(
                session_id=args.session_id,
                status=args.status,
            )
        except ValueError as exc:
            parser.error(str(exc))
            return 2
        if args.json:
            _print_json(payload)
        else:
            print(f"Session {payload['session_id']} recommendations")
            if payload["status_filter"]:
                print(f"filter={payload['status_filter']}")
            if not payload["recommendations"]:
                print("No recommendations matched this session.")
                return 0
            for item in payload["recommendations"]:
                print(
                    f"#{item['id']} [{item['status']} {item['severity']}] "
                    f"{item['source_key']} confidence={item.get('confidence', 'unknown')}"
                )
                print(item["message"])
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
        return 0

    if args.command == "reconcile":
        try:
            payload = app.reconcile_recommendations(
                session_id=args.session_id,
                all_sessions=args.all,
            )
        except ValueError as exc:
            parser.error(str(exc))
            return 2
        if args.json:
            _print_json(payload)
        else:
            print(f"Reconcile mode={payload['mode']} sessions={payload['session_count']}")
            for item in payload["sessions"]:
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
            payload = app.update_recommendation_status(args.id, args.status)
        except ValueError as exc:
            parser.error(str(exc))
            return 2
        _print_json(payload)
        return 0

    if args.command == "recommendation-run":
        try:
            payload = app.run_recommendation_action(
                args.id,
                confirmed=args.confirm,
            )
        except ValueError as exc:
            parser.error(str(exc))
            return 2
        _print_json(payload)
        return 0

    if args.command == "tool":
        try:
            payload = app.run_tool(
                args.name,
                _parse_kv_arguments(args.arg),
                confirmed=args.confirm,
                audit_context={"source": "tool_command"},
            )
        except ValueError as exc:
            parser.error(str(exc))
            return 2

        _print_json(payload)
        return 0

    if args.command == "chat":
        app.bootstrap()
        try:
            return _run_chat(
                app,
                args.once,
                as_json=args.json,
                session_id=args.session_id,
                new_session=args.new_session,
            )
        except ValueError as exc:
            parser.error(str(exc))
            return 2

    if args.command == "reconcile-timer":
        try:
            if args.timer_command == "render":
                payload = app.render_reconcile_timer(
                    scope=args.scope,
                    on_calendar=args.on_calendar,
                    randomized_delay=args.randomized_delay,
                    target_dir=args.target_dir,
                    python_executable=args.python,
                )
            elif args.timer_command == "install":
                payload = app.install_reconcile_timer(
                    scope=args.scope,
                    on_calendar=args.on_calendar,
                    randomized_delay=args.randomized_delay,
                    target_dir=args.target_dir,
                    python_executable=args.python,
                    run_systemctl=not args.skip_systemctl,
                )
            elif args.timer_command == "remove":
                payload = app.remove_reconcile_timer(
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
            _print_json(payload)
        elif args.timer_command == "render":
            _render_timer_units(payload)
        else:
            _render_timer_payload(payload)
            if args.timer_command == "remove":
                removed = payload.get("removed_paths", [])
                print(f"removed={len(removed)}")
        return 0

    parser.error("Unknown command.")
    return 2
