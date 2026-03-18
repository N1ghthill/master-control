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

    if args.command == "recommendations":
        try:
            payload = app.list_session_recommendations(
                session_id=args.session_id,
                status=args.status,
            )
        except ValueError as exc:
            parser.error(str(exc))
            return 2
        _print_json(payload)
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

    parser.error("Unknown command.")
    return 2
