from __future__ import annotations

import unittest

from master_control.interfaces.agent.tool_result_views import build_tool_result_view
from master_control.interfaces.agent.turn_planning import summarize_execution_for_planner
from master_control.interfaces.agent.turn_rendering import render_execution_summary


class ToolResultViewsTest(unittest.TestCase):
    def test_agent_namespace_re_exports_preferred_interface_helpers(self) -> None:
        from master_control.agent.tool_result_views import (
            build_tool_result_view as compat_build_tool_result_view,
        )
        from master_control.agent.turn_planning import (
            summarize_execution_for_planner as compat_summarize_execution_for_planner,
        )
        from master_control.agent.turn_rendering import (
            render_execution_summary as compat_render_execution_summary,
        )

        self.assertIs(compat_build_tool_result_view, build_tool_result_view)
        self.assertIs(
            compat_summarize_execution_for_planner,
            summarize_execution_for_planner,
        )
        self.assertIs(compat_render_execution_summary, render_execution_summary)

    def test_config_read_evidence_includes_excerpt_for_planner_and_renderer(self) -> None:
        execution = {
            "ok": True,
            "tool": "read_config_file",
            "arguments": {"path": "/tmp/app.ini"},
            "result": {
                "status": "ok",
                "path": "/tmp/app.ini",
                "target": "managed_ini",
                "line_count": 3,
                "content": "[main]\nkey=value\nmode=prod\n",
            },
        }

        planner_summary = summarize_execution_for_planner(execution)
        rendered_summary = render_execution_summary(execution)

        self.assertIn("excerpt=", planner_summary)
        self.assertIn("key=value", planner_summary)
        self.assertIn("Trecho:", rendered_summary)
        self.assertIn("mode=prod", rendered_summary)

    def test_top_processes_summary_deduplicates_repeated_commands(self) -> None:
        view = build_tool_result_view(
            "top_processes",
            {"limit": 5},
            {
                "status": "ok",
                "processes": [
                    {"command": "python3", "cpu_percent": 91.0},
                    {"command": "python3", "cpu_percent": 88.0},
                    {"command": "nginx", "cpu_percent": 30.0},
                ],
            },
        )

        self.assertEqual(view.rendered_summary.count("python3"), 1)
        self.assertIn("python3 x2", view.rendered_summary)
        self.assertEqual(view.summary_updates["processes"], "python3(91.0%), nginx(30.0%)")

    def test_config_write_and_restore_update_summary_context(self) -> None:
        write_view = build_tool_result_view(
            "write_config_file",
            {"path": "/etc/app.ini"},
            {
                "status": "ok",
                "path": "/etc/app.ini",
                "target": "managed_ini",
                "changed": True,
                "backup_path": "/tmp/app.bak",
                "validation": {"kind": "ini_parse", "status": "ok"},
            },
        )
        restore_view = build_tool_result_view(
            "restore_config_backup",
            {"path": "/etc/app.ini", "backup_path": "/tmp/app.bak"},
            {
                "status": "ok",
                "path": "/etc/app.ini",
                "target": "managed_ini",
                "restored_from": "/tmp/app.bak",
                "rollback_backup_path": "/tmp/rollback.bak",
                "validation": {"kind": "ini_parse", "status": "ok"},
            },
        )

        self.assertEqual(write_view.summary_updates["config_target"], "managed_ini")
        self.assertEqual(write_view.summary_updates["config_validation"], "ini_parse")
        self.assertEqual(write_view.summary_updates["last_backup_path"], "/tmp/app.bak")
        self.assertEqual(restore_view.summary_updates["config_target"], "managed_ini")
        self.assertEqual(restore_view.summary_updates["config_validation"], "ini_parse")
        self.assertEqual(restore_view.summary_updates["last_backup_path"], "/tmp/rollback.bak")
        self.assertIn("rollback", restore_view.rendered_summary)


if __name__ == "__main__":
    unittest.main()
