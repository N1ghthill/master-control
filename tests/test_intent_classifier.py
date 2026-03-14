#!/usr/bin/env python3
"""Tests for intent classification precedence rules."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from mastercontrol.tone.intent_classifier import IntentClassifier, IntentPrediction


class IntentClassifierPrecedenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = IntentClassifier(mode="disabled")

    def test_explicit_service_restart_overrides_history_bias(self) -> None:
        history_pred = IntentPrediction(
            intent_cluster="service.start",
            confidence=0.9,
            source="history",
        )
        with patch.object(self.classifier, "_predict_from_history", return_value=history_pred):
            pred = self.classifier.classify("restart nginx service")

        self.assertEqual(pred.intent_cluster, "service.restart")
        self.assertEqual(pred.source, "heuristic_explicit")

    def test_matching_history_cluster_is_kept(self) -> None:
        history_pred = IntentPrediction(
            intent_cluster="service.restart",
            confidence=0.9,
            source="history",
        )
        with patch.object(self.classifier, "_predict_from_history", return_value=history_pred):
            pred = self.classifier.classify("restart nginx service")

        self.assertEqual(pred.intent_cluster, "service.restart")
        self.assertEqual(pred.source, "history")

    def test_security_vigilance_is_detected_heuristically(self) -> None:
        pred = self.classifier.classify("vigie o sistema contra intrusos")

        self.assertEqual(pred.intent_cluster, "security.vigilance")
        self.assertEqual(pred.source, "heuristic")

    def test_security_incident_is_detected_heuristically(self) -> None:
        pred = self.classifier.classify("responda ao incidente reiniciando nginx.service")

        self.assertEqual(pred.intent_cluster, "security.incident")
        self.assertEqual(pred.source, "heuristic")


if __name__ == "__main__":
    unittest.main()
