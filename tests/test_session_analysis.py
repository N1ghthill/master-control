from __future__ import annotations

import unittest

from master_control.agent.observations import build_observation_freshness
from master_control.agent.session_analysis import build_session_analysis


class SessionAnalysisTest(unittest.TestCase):
    def test_build_session_analysis_reuses_structured_context_for_insights(self) -> None:
        freshness = build_observation_freshness(
            (
                {
                    "source": "service_status",
                    "key": "service",
                    "value": {"service": "nginx.service", "scope": "system"},
                    "observed_at": "2100-03-18T01:00:00Z",
                    "expires_at": "2100-03-18T01:03:00Z",
                },
            )
        )

        analysis = build_session_analysis(
            "service: nginx.service: active=failed, sub=failed",
            freshness,
        )

        self.assertEqual(analysis.session_context.service.name, "nginx.service")
        self.assertEqual(len(analysis.insights), 2)
        self.assertEqual(analysis.insights[0].key, "service_state")


if __name__ == "__main__":
    unittest.main()
