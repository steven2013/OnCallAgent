from oncall_agent.fleet import reset_fleet
from oncall_agent.parallel import CHECKS, build_triage_graph, services_for


def setup_function() -> None:
    reset_fleet()


def test_alert_selects_every_named_service():
    assert services_for("payment-api 和 order-worker 告警") == ["payment-api", "order-worker"]
    assert services_for("整个集群抖动") == ["payment-api", "order-worker", "redis"]


def test_checks_run_in_parallel_and_join_once():
    graph = build_triage_graph(pause_seconds=0.2)
    result = graph.invoke({"alert": "payment-api 磁盘告警"})

    findings = result["findings"]
    assert len(findings) == len(CHECKS)
    assert {item["check"] for item in findings} == set(CHECKS)
    assert {item["service"] for item in findings} == {"payment-api"}
    # 三项检查的时间区间互相重叠，说明不是串行排队。
    assert max(item["started"] for item in findings) < min(item["finished"] for item in findings)

    assert result["report"].count("并行完成 3 项检查") == 1
    assert "no space" in result["report"]
    assert "先清理已轮转日志" in result["report"]
    assert "disk_full.md" in result["report"]


def test_two_services_fan_out_and_keep_every_finding():
    graph = build_triage_graph()
    result = graph.invoke({"alert": "payment-api 和 order-worker 告警"})

    pairs = {(item["service"], item["check"]) for item in result["findings"]}
    assert pairs == {
        (service, check) for service in ("payment-api", "order-worker") for check in CHECKS
    }
    assert "并行完成 6 项检查" in result["report"]
    assert "Out of memory" in result["report"]
    assert "要走人工批准" in result["report"]
    assert "oom.md" in result["report"]
