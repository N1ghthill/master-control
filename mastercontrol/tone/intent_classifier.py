#!/usr/bin/env python3
"""Local-first intent classifier for MasterControl."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import argparse
import unicodedata
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LABELS = {
    "dns.flush",
    "dns.inspect",
    "service.restart",
    "service.start",
    "service.stop",
    "service.inspect",
    "package.update",
    "package.install",
    "package.remove",
    "security.audit",
    "security.incident",
    "security.vigilance",
    "network.diagnose",
    "general.assist",
}


def default_db_path() -> Path:
    return Path.home() / ".local" / "share" / "mastercontrol" / "mastercontrol.db"


@dataclass
class IntentPrediction:
    intent_cluster: str
    confidence: float
    source: str


class IntentClassifier:
    """Classify intent using local model, local history, and heuristic fallback."""

    RULES: dict[str, tuple[set[str], tuple[str, ...]]] = {
        "dns.flush": (
            {
                "dns",
                "unbound",
                "flush",
                "cache",
                "nxdomain",
                "bogus",
                "clear",
                "limpar",
                "reset",
            },
            (r"\bflush\b.*\b(cache|dns|unbound|nxdomain|bogus)\b", r"\b(limpar|reset)\b.*\b(cache|dns)\b"),
        ),
        "dns.inspect": (
            {"dns", "unbound", "resolver", "resolve", "lookup", "dig", "nslookup"},
            (r"\b(diagnose|check|verify|inspecionar)\b.*\b(dns|resolver)\b",),
        ),
        "service.restart": (
            {"service", "servico", "systemctl", "restart", "reiniciar", "reload"},
            (r"\b(restart|reiniciar|reload)\b.*\b(service|servico|systemctl|daemon)\b",),
        ),
        "service.start": (
            {"service", "servico", "systemctl", "start", "iniciar", "up"},
            (r"\b(start|iniciar)\b.*\b(service|servico|systemctl)\b",),
        ),
        "service.stop": (
            {"service", "servico", "systemctl", "stop", "parar", "down"},
            (r"\b(stop|parar)\b.*\b(service|servico|systemctl)\b",),
        ),
        "service.inspect": (
            {"service", "servico", "systemctl", "status", "health", "enabled", "logs", "journalctl"},
            (r"\b(status|health|logs|journalctl)\b.*\b(service|servico|systemctl)\b",),
        ),
        "package.update": (
            {"apt", "update", "upgrade", "packages", "pacotes", "repositorio"},
            (r"\bapt(-get)?\s+update\b", r"\b(atualizar|update)\b.*\b(pacote|apt|repositorio)\b"),
        ),
        "package.install": (
            {"apt", "install", "instalar", "package", "pacote"},
            (r"\bapt(-get)?\s+install\b", r"\b(instalar|install)\b.*\b(package|pacote|apt)\b"),
        ),
        "package.remove": (
            {"apt", "remove", "remover", "purge", "desinstalar"},
            (r"\bapt(-get)?\s+(remove|purge)\b", r"\b(remove|remover|desinstalar)\b.*\b(package|pacote|apt)\b"),
        ),
        "security.audit": (
            {"security", "seguranca", "audit", "auditar", "hardening", "vuln", "acesso"},
            (r"\b(audit|auditar|hardening|vulnerability)\b",),
        ),
        "security.incident": (
            {
                "incident",
                "incidente",
                "incidentes",
                "response",
                "resposta",
                "respond",
                "responder",
                "responda",
                "contain",
                "containment",
                "conter",
                "contencao",
                "mitigar",
                "mitigue",
                "security",
                "seguranca",
            },
            (
                r"\b(incident(e)?|resposta|response|contain(ment)?|conter|mitigar)\b",
                r"\b(responda|responder|mitigue|contenha)\b.*\b(incidente|incident|alerta|alert)\b",
            ),
        ),
        "security.vigilance": (
            {
                "vigia",
                "vigiar",
                "vigie",
                "monitor",
                "monitore",
                "monitorar",
                "vigilancia",
                "intruso",
                "intrusos",
                "proteger",
                "protecao",
                "security",
                "seguranca",
            },
            (
                r"\b(vigiar|vigie|monitor(ar|e)?|watch)\b.*\b(seguranca|sistema|intruso|intrusos|acesso)\b",
                r"\b(intruso|intrusos)\b",
            ),
        ),
        "network.diagnose": (
            {
                "network",
                "rede",
                "latency",
                "ping",
                "route",
                "traceroute",
                "gateway",
                "resolve",
                "lookup",
                "nslookup",
                "getent",
                "ip",
            },
            (r"\b(ping|route|traceroute|latency|lookup|resolve|getent)\b",),
        ),
    }

    def __init__(
        self,
        db_path: Path | None = None,
        model_dir: Path | None = None,
        mode: str = "auto",
    ) -> None:
        self.db_path = db_path or default_db_path()
        env_model_dir = os.environ.get("MC_INTENT_MODEL_DIR", "").strip()
        self.model_dir = model_dir or (Path(env_model_dir) if env_model_dir else None)
        self.mode = mode
        self._transformer = None
        self._label_map: dict[str, str] = {}
        if self.mode in {"auto", "transformer"}:
            self._try_load_transformer()

    def classify(self, text: str) -> IntentPrediction:
        t = (text or "").strip()
        if not t:
            return IntentPrediction(intent_cluster="general.assist", confidence=0.35, source="empty")

        heuristic_pred = self._predict_heuristic(t)

        if self._transformer is not None:
            pred = self._predict_transformer(t)
            if pred is not None:
                return pred

        hist_pred = self._predict_from_history(t)
        if hist_pred is None:
            return heuristic_pred

        explicit_override = self._prefer_explicit_mutation(
            text=t,
            heuristic_pred=heuristic_pred,
            history_pred=hist_pred,
        )
        if explicit_override is not None:
            return explicit_override

        if hist_pred.intent_cluster == "general.assist" and heuristic_pred.intent_cluster != "general.assist":
            return heuristic_pred
        if heuristic_pred.intent_cluster != "general.assist" and heuristic_pred.confidence >= hist_pred.confidence + 0.08:
            return heuristic_pred
        return hist_pred

    def _try_load_transformer(self) -> None:
        if self.model_dir is None:
            return
        try:
            from transformers import pipeline  # type: ignore
        except Exception:  # noqa: BLE001
            return

        if not self.model_dir.exists():
            return
        try:
            self._transformer = pipeline(
                task="text-classification",
                model=str(self.model_dir),
                tokenizer=str(self.model_dir),
                top_k=1,
                truncation=True,
                local_files_only=True,
            )
        except Exception:  # noqa: BLE001
            self._transformer = None
            return

        label_map_path = self.model_dir / "label_map.json"
        if label_map_path.exists():
            try:
                raw = json.loads(label_map_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._label_map = {str(k): str(v) for k, v in raw.items()}
            except Exception:  # noqa: BLE001
                self._label_map = {}

    def _predict_transformer(self, text: str) -> IntentPrediction | None:
        if self._transformer is None:
            return None
        try:
            out = self._transformer(text)
        except Exception:  # noqa: BLE001
            return None
        if not out:
            return None
        item = out[0]
        if isinstance(item, list) and item:
            item = item[0]
        if not isinstance(item, dict):
            return None
        raw_label = str(item.get("label", "")).strip()
        score = float(item.get("score", 0.0))
        label = self._label_map.get(raw_label, raw_label).strip().lower()
        if label not in DEFAULT_LABELS:
            return None
        return IntentPrediction(intent_cluster=label, confidence=max(0.05, min(score, 0.99)), source="transformer")

    def _predict_from_history(self, text: str) -> IntentPrediction | None:
        if not self.db_path.exists():
            return None
        tokens = self._tokenize(self._normalize_text(text))
        if len(tokens) < 2:
            return None

        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT intent_text, intent_cluster
                FROM command_events
                WHERE intent_cluster <> '' AND intent_cluster <> 'unknown'
                ORDER BY id DESC
                LIMIT 500
                """
            ).fetchall()
        except Exception:  # noqa: BLE001
            return None
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

        if not rows:
            return None

        best_by_cluster: dict[str, float] = {}
        for row in rows:
            cluster = str(row["intent_cluster"]).strip().lower()
            if cluster not in DEFAULT_LABELS:
                continue
            sample_tokens = self._tokenize(self._normalize_text(str(row["intent_text"])))
            if not sample_tokens:
                continue
            overlap = len(tokens.intersection(sample_tokens))
            if overlap == 0:
                continue
            jaccard = overlap / len(tokens.union(sample_tokens))
            score = jaccard + (0.1 if overlap >= 3 else 0.0)
            prev = best_by_cluster.get(cluster, 0.0)
            if score > prev:
                best_by_cluster[cluster] = score

        if not best_by_cluster:
            return None

        cluster, score = max(best_by_cluster.items(), key=lambda x: x[1])
        if score < 0.25:
            return None
        confidence = 0.55 + min(score, 0.35)
        return IntentPrediction(
            intent_cluster=cluster,
            confidence=round(max(0.05, min(confidence, 0.92)), 3),
            source="history",
        )

    def _predict_heuristic(self, text: str) -> IntentPrediction:
        norm_text = self._normalize_text(text)
        tokens = self._tokenize(norm_text)
        joined = " ".join(sorted(tokens))
        scores: dict[str, float] = {}

        for cluster, (keywords, patterns) in self.RULES.items():
            score = 0.0
            overlap = len(tokens.intersection(keywords))
            score += overlap * 0.22
            if any(re.search(p, norm_text, flags=re.IGNORECASE) for p in patterns):
                score += 0.55
            if cluster.startswith("service") and any(tok.endswith(".service") for tok in tokens):
                score += 0.25
            if cluster.startswith("package") and re.search(r"\bapt(-get)?\b", joined):
                score += 0.20
            if score > 0:
                scores[cluster] = score

        if not scores:
            return IntentPrediction(intent_cluster="general.assist", confidence=0.5, source="heuristic")

        cluster, score = max(scores.items(), key=lambda x: x[1])
        confidence = 0.45 + min(score, 0.45)
        return IntentPrediction(
            intent_cluster=cluster,
            confidence=round(max(0.05, min(confidence, 0.9)), 3),
            source="heuristic",
        )

    def _prefer_explicit_mutation(
        self,
        text: str,
        heuristic_pred: IntentPrediction,
        history_pred: IntentPrediction,
    ) -> IntentPrediction | None:
        if heuristic_pred.intent_cluster == history_pred.intent_cluster:
            return None

        explicit_cluster = self._explicit_mutation_cluster(text)
        if not explicit_cluster:
            return None
        if heuristic_pred.intent_cluster != explicit_cluster:
            return None
        if history_pred.intent_cluster == explicit_cluster:
            return None

        boosted = round(min(0.95, heuristic_pred.confidence + 0.05), 3)
        return IntentPrediction(
            intent_cluster=heuristic_pred.intent_cluster,
            confidence=max(heuristic_pred.confidence, boosted),
            source="heuristic_explicit",
        )

    def _explicit_mutation_cluster(self, text: str) -> str:
        norm_text = self._normalize_text(text)

        if re.search(r"\b(restart|reiniciar|reload)\b", norm_text):
            return "service.restart"
        if re.search(r"\b(start|iniciar)\b", norm_text):
            return "service.start"
        if re.search(r"\b(stop|parar)\b", norm_text):
            return "service.stop"
        if re.search(r"\bapt(-get)?\s+update\b", norm_text):
            return "package.update"
        if re.search(r"\bapt(-get)?\s+install\b", norm_text):
            return "package.install"
        if re.search(r"\bapt(-get)?\s+(remove|purge)\b", norm_text):
            return "package.remove"
        return ""

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return set(re.findall(r"[a-z0-9_.:-]+", (text or "").lower()))

    @staticmethod
    def _normalize_text(text: str) -> str:
        raw = (text or "").lower()
        return "".join(
            ch for ch in unicodedata.normalize("NFKD", raw) if not unicodedata.combining(ch)
        )


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mc-intent-classifier",
        description="Classify intent using local-first strategy",
    )
    p.add_argument("--text", required=True, help="Operator text")
    p.add_argument("--mode", default="auto", choices=["auto", "transformer", "heuristic"])
    p.add_argument("--db", default=None, help="SQLite path for history-based classification")
    p.add_argument("--model-dir", default=None, help="Local fine-tuned model directory")
    return p


def main() -> int:
    args = parser().parse_args()
    mode = "transformer" if args.mode == "transformer" else ("auto" if args.mode == "auto" else "disabled")
    clf = IntentClassifier(
        db_path=Path(args.db) if args.db else None,
        model_dir=Path(args.model_dir) if args.model_dir else None,
        mode=mode,
    )
    result = clf.classify(args.text)
    if args.mode == "heuristic":
        result = clf._predict_heuristic(args.text)
    print(
        json.dumps(
            {
                "intent_cluster": result.intent_cluster,
                "confidence": result.confidence,
                "source": result.source,
            },
            ensure_ascii=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
