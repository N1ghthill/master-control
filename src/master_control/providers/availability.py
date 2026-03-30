from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from master_control.config import Settings
from master_control.providers.base import validate_http_url

PROBE_USER_AGENT = "master-control/0.1.0a2"


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    body: str
    headers: dict[str, str]


HttpTransport = Callable[[str, dict[str, str], float], HttpResponse]
BinaryLookup = Callable[[str], str | None]


def collect_provider_checks(settings: Settings) -> dict[str, dict[str, object]]:
    return {
        "ollama": probe_ollama(settings),
        "openai": probe_openai(settings),
        "heuristic": probe_heuristic(),
        "noop": probe_noop(),
    }


def resolve_auto_provider_backend(
    settings: Settings,
    *,
    checks: dict[str, dict[str, object]] | None = None,
) -> str:
    provider_checks = checks or collect_provider_checks(settings)
    if provider_checks["ollama"]["available"]:
        return "ollama"
    if provider_checks["openai"]["available"]:
        return "openai"
    return "heuristic"


def probe_ollama(
    settings: Settings,
    *,
    transport: HttpTransport | None = None,
    binary_lookup: BinaryLookup | None = None,
    timeout_s: float | None = None,
) -> dict[str, object]:
    http_transport = transport or _default_http_get
    lookup = binary_lookup or shutil.which
    probe_timeout_s = timeout_s if timeout_s is not None else settings.provider_probe_timeout_s
    base_url = settings.ollama_base_url.rstrip("/")
    binary_path = lookup("ollama")
    check: dict[str, object] = {
        "name": "ollama",
        "available": False,
        "base_url": base_url,
        "model": settings.ollama_model,
        "binary_in_path": bool(binary_path),
        "probe_timeout_s": probe_timeout_s,
    }
    if binary_path:
        check["binary_path"] = binary_path
    try:
        tags_url = validate_http_url(f"{base_url}/tags", label="Ollama probe URL")
    except ValueError as exc:
        check["summary"] = str(exc)
        return check
    check["tags_url"] = tags_url

    try:
        response = http_transport(
            tags_url,
            {"User-Agent": PROBE_USER_AGENT},
            probe_timeout_s,
        )
    except urllib.error.URLError as exc:
        reason = exc.reason if getattr(exc, "reason", None) else str(exc)
        check["summary"] = f"endpoint unavailable: {reason}"
        return check
    except TimeoutError:
        check["summary"] = "endpoint probe timed out"
        return check
    except OSError as exc:
        check["summary"] = f"endpoint unavailable: {exc}"
        return check

    try:
        payload = json.loads(response.body)
    except json.JSONDecodeError:
        check["summary"] = "endpoint reachable but returned invalid JSON"
        check["reachable"] = True
        return check

    models = _extract_ollama_models(payload)
    check["reachable"] = True
    check["available_models"] = models
    model_present = settings.ollama_model in models
    check["model_present"] = model_present
    if model_present:
        check["available"] = True
        check["summary"] = f"endpoint reachable and model `{settings.ollama_model}` is installed"
    else:
        check["summary"] = (
            f"endpoint reachable but model `{settings.ollama_model}` is not installed"
        )
    return check


def probe_openai(settings: Settings) -> dict[str, object]:
    base_url = settings.openai_base_url.rstrip("/")
    try:
        validate_http_url(f"{base_url}/responses", label="OpenAI endpoint")
    except ValueError as exc:
        return {
            "name": "openai",
            "available": False,
            "base_url": base_url,
            "model": settings.openai_model,
            "summary": str(exc),
            "network_probe": "skipped",
        }

    available = bool(settings.openai_api_key)
    summary = (
        f"API key configured for model `{settings.openai_model}`"
        if available
        else "OPENAI_API_KEY is not set"
    )
    return {
        "name": "openai",
        "available": available,
        "base_url": base_url,
        "model": settings.openai_model,
        "summary": summary,
        "network_probe": "skipped",
    }


def probe_heuristic() -> dict[str, object]:
    return {
        "name": "heuristic",
        "available": True,
        "summary": "offline structured planner available",
    }


def probe_noop() -> dict[str, object]:
    return {
        "name": "noop",
        "available": True,
        "summary": "static disabled provider available",
    }


def _extract_ollama_models(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    raw_models = payload.get("models")
    if not isinstance(raw_models, list):
        return []
    models: list[str] = []
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name:
            models.append(name)
    return models


def _default_http_get(url: str, headers: dict[str, str], timeout_s: float) -> HttpResponse:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_s) as response:  # nosec B310
        body = response.read().decode("utf-8")
        response_headers = {key.lower(): value for key, value in response.headers.items()}
        return HttpResponse(
            status_code=response.status,
            body=body,
            headers=response_headers,
        )
