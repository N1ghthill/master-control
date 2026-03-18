from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from master_control.tools.base import (
    RiskLevel,
    Tool,
    ToolArgumentError,
    ToolSpec,
    get_string_argument,
)


class DiskUsageTool(Tool):
    spec = ToolSpec(
        name="disk_usage",
        description="Return disk usage metrics for a given path.",
        risk=RiskLevel.READ_ONLY,
        arguments=("path",),
    )

    def invoke(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        raw_path = get_string_argument(arguments, "path", default="/")
        path = Path(raw_path or "/").expanduser()
        if not path.exists():
            raise ToolArgumentError(f"Path does not exist: {path}")

        usage = shutil.disk_usage(path)
        used_bytes = usage.total - usage.free
        used_percent = (used_bytes / usage.total * 100) if usage.total else 0.0
        return {
            "path": str(path.resolve()),
            "total_bytes": usage.total,
            "used_bytes": used_bytes,
            "free_bytes": usage.free,
            "used_percent": round(used_percent, 2),
        }
