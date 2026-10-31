"""把节点和边收成一张图。

一次用户消息的路径：

    START -> recall_memory -> agent -> tools 或 approve 或 END
    tools -> agent
    approve 拒绝 -> agent
    approve 批准 -> tools

短期记忆是 checkpointer：同一个 thread_id 会把上一轮的 messages 合并进来。
长期记忆是 store：按 user_id 分命名空间，跨 thread 还能读到。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.types import interrupt

from oncall_agent.embeddings import DIMS, embed_texts
from oncall_agent.llm import get_model
from oncall_agent.state import OpsContext, OpsState
from oncall_agent.tools import ALL_TOOLS, DANGEROUS_TOOL_NAMES, MEMORY_NS

SYSTEM_PROMPT = """你是 OnCallAgent，一个谨慎的运维助手。

先取证再下结论。依据来自手册检索或模拟集群工具时，在回答里保留关键原文。
request_restart 必须经过人工批准，不要假装已经重启。
不知道就说不知道。用简体中文回答。
模拟数据不是生产环境。
"""


def build_store() -> InMemoryStore:
    """带向量索引的内存 store。进程退出后数据消失。"""

    return InMemoryStore(
        index={
            "dims": DIMS,
            "embed": embed_texts,
            "fields": ["text"],
        }
    )


def _user_id(runtime: Runtime[OpsContext]) -> str:
    context = runtime.context
    if isinstance(context, OpsContext) and context.user_id:
        return context.user_id
    return "default"


def _latest_user_text(messages: Sequence[BaseMessage]) -> str:
    for message in reversed(messages):
        if message.type == "human" and isinstance(message.content, str):
            return message.content
    return ""


def recall_memory(state: OpsState, runtime: Runtime[OpsContext]) -> dict[str, str]:
    """每轮开始时把长期记忆写进状态，供 agent 节点放进系统提示。

    这一轮里 remember 工具写入的内容，要到下一轮才会出现在这里。
    工具返回值本身仍在 messages 里，所以当前轮也能看见刚写下的句子。
    """

    store = runtime.store
    if store is None:
        return {"memories": ""}
    namespace = (_user_id(runtime), MEMORY_NS)
    query = _latest_user_text(state["messages"])
    items = store.search(namespace, query=query, limit=5) if query else []
    if not items:
        items = list(store.search(namespace, limit=5))
    lines = [str(item.value.get("text", "")) for item in items if item.value.get("text")]
    return {"memories": "\n".join(f"- {line}" for line in lines)}


def _window(messages: Sequence[BaseMessage], limit: int = 40) -> list[BaseMessage]:
    """留住最近消息，并避免窗口从一条失去配对的 ToolMessage 开始。"""

    if len(messages) <= limit:
        return list(messages)
    sliced = list(messages[-limit:])
    while sliced and sliced[0].type == "tool":
        sliced = sliced[1:]
    return sliced


def _system_message(state: OpsState) -> SystemMessage:
    memories = state.get("memories", "").strip()
    if not memories:
        return SystemMessage(content=SYSTEM_PROMPT)
    return SystemMessage(
        content=SYSTEM_PROMPT + "\n\n长期记忆（跨会话，仅供参考）：\n" + memories
    )


def make_agent(model: BaseChatModel):
    """闭包把模型固定在节点上。节点本身只接收 state。"""

    bound = model.bind_tools(ALL_TOOLS)

    def agent(state: OpsState) -> dict[str, list[BaseMessage]]:
        reply = bound.invoke([_system_message(state), *_window(state["messages"])])
        return {"messages": [reply]}

    return agent


def route_after_agent(state: OpsState) -> Literal["tools", "approve", "__end__"]:
    """条件边：看模型这条消息里有没有工具调用，以及是不是危险工具。"""

    last = state["messages"][-1]
    calls = getattr(last, "tool_calls", None) or []
    if not calls:
        return "__end__"
    if any(call["name"] in DANGEROUS_TOOL_NAMES for call in calls):
        return "approve"
    return "tools"


def approve(state: OpsState) -> dict[str, list[ToolMessage]]:
    """在危险工具真正执行前暂停。

    interrupt 会把 payload 交给调用方，并在此处停下。
    恢复时本节点从头再跑，interrupt(...) 直接返回 Command(resume=...) 的值。
    """

    last = state["messages"][-1]
    calls = getattr(last, "tool_calls", None) or []
    decision = interrupt(
        {
            "question": "即将执行需要人工批准的操作。",
            "calls": [{"name": call["name"], "args": call["args"]} for call in calls],
        }
    )
    approved = isinstance(decision, dict) and bool(decision.get("approved"))
    if approved:
        return {}
    return {
        "messages": [
            ToolMessage(
                content=f"已拒绝执行 {call['name']}：没有人工批准。",
                tool_call_id=call["id"],
                name=call["name"],
            )
            for call in calls
        ]
    }


def route_after_approve(state: OpsState) -> Literal["tools", "agent"]:
    last = state["messages"][-1]
    if last.type == "tool":
        return "agent"
    return "tools"


def build_graph(
    *,
    model: BaseChatModel | None = None,
    store: BaseStore | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """编译图。checkpointer 负责短期记忆，store 负责长期记忆。"""

    builder = StateGraph(OpsState, context_schema=OpsContext)
    builder.add_node("recall_memory", recall_memory)
    builder.add_node("agent", make_agent(model or get_model()))
    builder.add_node("tools", ToolNode(ALL_TOOLS))
    builder.add_node("approve", approve)

    builder.add_edge(START, "recall_memory")
    builder.add_edge("recall_memory", "agent")
    builder.add_conditional_edges("agent", route_after_agent)
    builder.add_conditional_edges("approve", route_after_approve)
    builder.add_edge("tools", "agent")

    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else InMemorySaver(),
        store=store if store is not None else build_store(),
    )
