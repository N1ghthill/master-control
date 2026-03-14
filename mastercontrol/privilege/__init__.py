"""Privileged execution plane for MasterControl."""

from __future__ import annotations

from typing import Any

__all__ = [
    "BootstrapPkexecTransport",
    "DEFAULT_BROKER_SOCKET",
    "PExecPlanner",
    "PrivilegeBrokerClient",
    "PrivilegeBrokerServer",
    "PrivilegeBrokerTransport",
    "broker_socket_available",
]


def __getattr__(name: str) -> Any:
    if name in {"BootstrapPkexecTransport", "PExecPlanner", "PrivilegeBrokerTransport"}:
        from mastercontrol.privilege.pexec import (
            BootstrapPkexecTransport,
            PExecPlanner,
            PrivilegeBrokerTransport,
        )

        mapping = {
            "BootstrapPkexecTransport": BootstrapPkexecTransport,
            "PExecPlanner": PExecPlanner,
            "PrivilegeBrokerTransport": PrivilegeBrokerTransport,
        }
        return mapping[name]
    if name in {
        "DEFAULT_BROKER_SOCKET",
        "PrivilegeBrokerClient",
        "PrivilegeBrokerServer",
        "broker_socket_available",
    }:
        from mastercontrol.privilege.broker import (
            DEFAULT_BROKER_SOCKET,
            PrivilegeBrokerClient,
            PrivilegeBrokerServer,
            broker_socket_available,
        )

        mapping = {
            "DEFAULT_BROKER_SOCKET": DEFAULT_BROKER_SOCKET,
            "PrivilegeBrokerClient": PrivilegeBrokerClient,
            "PrivilegeBrokerServer": PrivilegeBrokerServer,
            "broker_socket_available": broker_socket_available,
        }
        return mapping[name]
    raise AttributeError(name)
