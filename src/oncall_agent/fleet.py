"""模拟集群。

工具只读写这份内存数据，不会执行 shell，也不会连真实主机。
"""

from __future__ import annotations

import copy

_TEMPLATE: dict[str, dict[str, object]] = {
    "payment-api": {
        "host": "pay-1",
        "status": "degraded",
        "cpu": 92,
        "mem": 71,
        "restarts": 1,
    },
    "order-worker": {
        "host": "ord-2",
        "status": "running",
        "cpu": 22,
        "mem": 84,
        "restarts": 4,
    },
    "redis": {
        "host": "cache-1",
        "status": "running",
        "cpu": 11,
        "mem": 48,
        "restarts": 0,
    },
}

SERVICES: dict[str, dict[str, object]] = {}

LOGS: dict[str, list[str]] = {
    "payment-api": [
        "WARN pay-1 disk usage 94%",
        "ERROR no space left on device while writing access log",
        "ERROR upstream timeout redis",
    ],
    "order-worker": [
        "INFO batch reconcile started size=5000",
        "ERROR Out of memory: Killed process order-worker",
        "WARN restarts increased after deploy",
    ],
    "redis": [
        "INFO ready to accept connections",
        "WARN slowlog 12ms",
    ],
}

DISKS: dict[str, int] = {"pay-1": 94, "ord-2": 41, "cache-1": 55}


def reset_fleet() -> None:
    """把模拟集群恢复成初始故障场景。"""

    SERVICES.clear()
    SERVICES.update(copy.deepcopy(_TEMPLATE))


reset_fleet()
