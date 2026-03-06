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


if __name__ == "__main__":
    unittest.main()
