from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from master_control.tools.base import RiskLevel, Tool, ToolSpec


MEMINFO_PATH = Path("/proc/meminfo")


class MemoryUsageTool(Tool):
    spec = ToolSpec(
        name="memory_usage",
        description="Return memory and swap usage from /proc/meminfo.",
        risk=RiskLevel.READ_ONLY,
    )

    def invoke(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        del arguments
        fields = self._read_meminfo()

        total = fields["MemTotal"] * 1024
        available = fields.get("MemAvailable", fields["MemFree"]) * 1024
        used = total - available

        swap_total = fields.get("SwapTotal", 0) * 1024
        swap_free = fields.get("SwapFree", 0) * 1024
        swap_used = swap_total - swap_free

        memory_used_percent = (used / total * 100) if total else 0.0
        swap_used_percent = (swap_used / swap_total * 100) if swap_total else 0.0

        return {
            "source": str(MEMINFO_PATH),
            "memory_total_bytes": total,
            "memory_used_bytes": used,
            "memory_available_bytes": available,
            "memory_used_percent": round(memory_used_percent, 2),
            "swap_total_bytes": swap_total,
            "swap_used_bytes": swap_used,
            "swap_free_bytes": swap_free,
            "swap_used_percent": round(swap_used_percent, 2),
        }

    def _read_meminfo(self) -> dict[str, int]:
        fields: dict[str, int] = {}
        with MEMINFO_PATH.open(encoding="utf-8") as handle:
            for line in handle:
                key, raw_value = line.split(":", maxsplit=1)
                value = int(raw_value.strip().split()[0])
                fields[key] = value
        return fields

