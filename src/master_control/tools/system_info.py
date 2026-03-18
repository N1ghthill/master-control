from __future__ import annotations

import getpass
import platform
import socket
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from master_control.tools.base import RiskLevel, Tool, ToolSpec


class SystemInfoTool(Tool):
    spec = ToolSpec(
        name="system_info",
        description="Return basic host metadata for bootstrap diagnostics.",
        risk=RiskLevel.READ_ONLY,
    )

    def invoke(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        del arguments
        return {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "kernel": platform.release(),
            "python": sys.version.split()[0],
            "user": getpass.getuser(),
            "cwd": str(Path.cwd()),
        }
