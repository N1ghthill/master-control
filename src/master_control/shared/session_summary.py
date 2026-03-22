from __future__ import annotations

from collections import OrderedDict


def parse_session_summary(existing_summary: str | None) -> OrderedDict[str, str]:
    parsed: OrderedDict[str, str] = OrderedDict()
    if not existing_summary:
        return parsed

    for line in existing_summary.splitlines():
        if ":" not in line:
            continue
        key, raw_value = line.split(":", maxsplit=1)
        normalized_key = key.strip()
        value = raw_value.strip()
        if not normalized_key or not value:
            continue
        parsed[normalized_key] = value
    return parsed
