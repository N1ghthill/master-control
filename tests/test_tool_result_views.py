from __future__ import annotations

import unittest

from master_control.agent.turn_planning import summarize_execution_for_planner
from master_control.agent.turn_rendering import render_execution_summary


class ToolResultViewsTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
