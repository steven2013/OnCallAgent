"""Agent 可以调用的工具。

`runtime` 这个参数名是保留的：LangGraph 看到类型标注 `ToolRuntime` 后，
会在执行时注入，并且不会把它放进给模型看的参数 schema。
"""

import uuid

from langchain.tools import ToolRuntime, tool

from oncall_agent.fleet import DISKS, LOGS, SERVICES
from oncall_agent.rag import get_retriever
from oncall_agent.state import OpsContext

MEMORY_NS = "memories"


def user_id_from(runtime: ToolRuntime[OpsContext, dict]) -> str:
    context = runtime.context
    if isinstance(context, OpsContext):
        return context.user_id or "default"
    if isinstance(context, dict):
        return str(context.get("user_id") or "default")
    return "default"


@tool
def search_runbooks(query: str) -> str:
    """搜索运维手册。处理步骤、磁盘、CPU、OOM、回滚、重启策略都先查这里。"""

    documents = get_retriever().invoke(query)
    if not documents:
        return "手册里没有相关内容。"
    blocks = []
    for document in documents:
        source = document.metadata.get("source", "unknown")
        blocks.append(f"[{source}]\n{document.page_content}")
    return "\n\n---\n\n".join(blocks)


@tool
def list_services() -> str:
    """列出模拟集群里的服务和当前状态。"""

    lines = []
    for name, spec in SERVICES.items():
        lines.append(
            f"{name} host={spec['host']} status={spec['status']} "
            f"cpu={spec['cpu']}% mem={spec['mem']}% restarts={spec['restarts']}"
        )
    return "\n".join(lines)


@tool
def service_status(service: str) -> str:
    """查看单个服务的状态。service 取 payment-api、order-worker 或 redis。"""

    spec = SERVICES.get(service)
    if spec is None:
        known = "、".join(SERVICES)
        return f"未知服务 {service}。已知服务：{known}"
    return (
        f"{service} host={spec['host']} status={spec['status']} "
        f"cpu={spec['cpu']}% mem={spec['mem']}% restarts={spec['restarts']}"
    )


@tool
def tail_logs(service: str, lines: int = 5) -> str:
    """查看某个服务最近的模拟日志。"""

    entries = LOGS.get(service)
    if entries is None:
        known = "、".join(LOGS)
        return f"没有 {service} 的日志。已知服务：{known}"
    clipped = entries[-max(1, lines) :]
    return "\n".join(clipped)


@tool
def disk_usage(host: str = "") -> str:
    """查看主机磁盘使用率。host 为空时返回全部主机。"""

    if not host:
        return "\n".join(f"{name} {used}%" for name, used in DISKS.items())
    used = DISKS.get(host)
    if used is None:
        known = "、".join(DISKS)
        return f"未知主机 {host}。已知主机：{known}"
    return f"{host} 磁盘使用率 {used}%"


@tool
def remember(fact: str, runtime: ToolRuntime[OpsContext, dict]) -> str:
    """记住一条跨会话事实，例如负责人、变更窗口、已知故障。

    `runtime` 会在执行时注入。写成 ToolRuntime[OpsContext, dict]，
    是为了让上下文类型和 OpsContext 对齐；它不会出现在模型看到的参数里。
    """

    text = fact.strip()
    if not text:
        return "没有可记的内容。"
    if runtime.store is None:
        return "图没有配置 store，无法写入长期记忆。"
    namespace = (user_id_from(runtime), MEMORY_NS)
    runtime.store.put(namespace, uuid.uuid4().hex, {"text": text})
    return f"已写入长期记忆：{text}"


@tool
def recall(query: str, runtime: ToolRuntime[OpsContext, dict]) -> str:
    """按当前问题检索这个用户的长期记忆。"""

    if runtime.store is None:
        return "图没有配置 store。"
    namespace = (user_id_from(runtime), MEMORY_NS)
    items = runtime.store.search(namespace, query=query, limit=5)
    if not items:
        items = list(runtime.store.search(namespace, limit=5))
    lines = [str(item.value.get("text", "")) for item in items if item.value.get("text")]
    if not lines:
        return "没有相关长期记忆。"
    return "\n".join(f"- {line}" for line in lines)


@tool
def request_restart(service: str) -> str:
    """申请重启服务。只有图的 approve 节点放行后，这个函数才会被调用。"""

    spec = SERVICES.get(service)
    if spec is None:
        known = "、".join(SERVICES)
        return f"未知服务 {service}。已知服务：{known}"
    spec["status"] = "running"
    spec["restarts"] = int(spec["restarts"]) + 1
    spec["cpu"] = 15
    return (
        f"已模拟重启 {service}。当前 status=running，restarts={spec['restarts']}。"
        "这不是真实主机操作。"
    )


SAFE_TOOLS = [
    search_runbooks,
    list_services,
    service_status,
    tail_logs,
    disk_usage,
    remember,
    recall,
]
DANGEROUS_TOOLS = [request_restart]
ALL_TOOLS = SAFE_TOOLS + DANGEROUS_TOOLS
DANGEROUS_TOOL_NAMES = {item.name for item in DANGEROUS_TOOLS}
