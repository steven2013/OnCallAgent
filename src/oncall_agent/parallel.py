"""告警并行分诊。

一次告警会拆成多项检查。`dispatch` 为每一项返回一个 `Send`，
LangGraph 在同一步里并行执行这些 `inspect`。
各项检查只把自己的结果追加进 `findings`，所以这个字段必须带 reducer。
`write_report` 设了 `defer=True`，会等所有并行检查结束再写一份报告。
"""

from __future__ import annotations

import operator
import time
from typing import Annotated, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from oncall_agent.fleet import DISKS, LOGS, SERVICES
from oncall_agent.rag import get_retriever

CHECKS = ("logs", "resources", "runbook")


class Finding(TypedDict):
    service: str
    check: str
    detail: str
    started: float
    finished: float


class TriageState(TypedDict):
    alert: str
    services: NotRequired[list[str]]
    # 并行节点各自返回一段列表，reducer 负责拼在一起，而不是互相覆盖。
    findings: Annotated[list[Finding], operator.add]
    report: NotRequired[str]


class InspectTask(TypedDict):
    service: str
    check: str
    alert: str


def services_for(alert: str) -> list[str]:
    """从告警原文里找出要同时排查的服务。"""

    if any(word in alert for word in ("全部", "所有服务", "整个集群")):
        return list(SERVICES)
    named = [name for name in SERVICES if name in alert]
    if named:
        return named
    return ["payment-api"]


def intake(state: TriageState) -> dict[str, list[str]]:
    return {"services": services_for(state["alert"])}


def dispatch(state: TriageState) -> list[Send]:
    """每个服务的每项检查都是一份独立任务，下一步并行执行。"""

    alert = state["alert"]
    return [
        Send("inspect", {"service": service, "check": check, "alert": alert})
        for service in state["services"]
        for check in CHECKS
    ]


def _logs(service: str) -> str:
    entries = LOGS.get(service)
    if not entries:
        return f"{service} 没有日志"
    return " | ".join(entries[-3:])


def _resources(service: str) -> str:
    spec = SERVICES.get(service)
    if spec is None:
        return f"未知服务 {service}"
    host = str(spec["host"])
    disk = DISKS.get(host, 0)
    return (
        f"{service} status={spec['status']} cpu={spec['cpu']}% "
        f"mem={spec['mem']}% {host} 磁盘 {disk}%"
    )


def _runbook(service: str, alert: str) -> str:
    hint = " ".join(LOGS.get(service, []))
    documents = get_retriever().invoke(f"{alert} {service} {hint}")
    if not documents:
        return "手册里没有相关内容"
    top = documents[0]
    source = top.metadata.get("source", "unknown")
    title = top.page_content.strip().splitlines()[0]
    return f"{source} {title}"


def _detail(task: InspectTask) -> str:
    check = task["check"]
    service = task["service"]
    if check == "logs":
        return _logs(service)
    if check == "resources":
        return _resources(service)
    if check == "runbook":
        return _runbook(service, task["alert"])
    return f"未知检查项 {check}"


def make_inspect(pause_seconds: float):
    """暂停时间只给测试用，用来观察这些任务的时间区间是否重叠。"""

    def inspect(task: InspectTask) -> dict[str, list[Finding]]:
        started = time.perf_counter()
        if pause_seconds:
            time.sleep(pause_seconds)
        finding: Finding = {
            "service": task["service"],
            "check": task["check"],
            "detail": _detail(task),
            "started": started,
            "finished": time.perf_counter(),
        }
        return {"findings": [finding]}

    return inspect


def _advice(findings: list[Finding]) -> str:
    text = "\n".join(item["detail"] for item in findings)
    notes: list[str] = []
    if "no space" in text or "磁盘 9" in text or "磁盘 100" in text:
        notes.append("磁盘高的机器先清理已轮转日志，不要靠重启解决。")
    if "Out of memory" in text or "Killed" in text:
        notes.append("出现 OOM 的进程如需拉起，要走人工批准。")
    if not notes:
        notes.append("没有需要立即重启的迹象，继续观察错误率。")
    return "".join(notes)


def write_report(state: TriageState) -> dict[str, str]:
    findings = sorted(state["findings"], key=lambda item: (item["service"], item["check"]))
    lines = [f"- {item['service']} / {item['check']}: {item['detail']}" for item in findings]
    report = (
        f"告警：{state['alert']}\n"
        f"并行完成 {len(findings)} 项检查。\n"
        + "\n".join(lines)
        + f"\n建议：{_advice(findings)}"
    )
    return {"report": report}


def build_triage_graph(*, pause_seconds: float = 0.0):
    builder = StateGraph(TriageState)
    builder.add_node("intake", intake)
    builder.add_node("inspect", make_inspect(pause_seconds))
    builder.add_node("write_report", write_report, defer=True)

    builder.add_edge(START, "intake")
    builder.add_conditional_edges("intake", dispatch)
    builder.add_edge("inspect", "write_report")
    builder.add_edge("write_report", END)
    return builder.compile()


def run_parallel(alert: str, *, echo=print) -> str:
    """跑一遍分诊，并按节点打印。返回最终报告。"""

    report = ""
    graph = build_triage_graph()
    for update in graph.stream({"alert": alert}, stream_mode="updates"):
        for node, writes in update.items():
            if node == "intake":
                echo(f"[intake] 同时排查：{', '.join(writes['services'])}")
            elif node == "inspect":
                for item in writes.get("findings", []):
                    echo(f"[inspect] {item['service']} / {item['check']}: {item['detail']}")
            elif node == "write_report":
                report = writes["report"]
                echo("[write_report]")
                echo(report)
    return report
