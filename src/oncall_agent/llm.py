"""选择聊天模型。

默认的 KeywordRouterModel 按用户原话选择工具，并在看到 ToolMessage 后停止。
它让图的分支可以在没有 API key 时被测试和观察。
设置 OPS_AGENT_MODEL（例如 openai:gpt-4o-mini）后改走真实模型，图的代码不变。
"""

from __future__ import annotations

import os
import uuid

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable

_SERVICES = ("payment-api", "order-worker", "redis")


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return str(content)


def _latest_human(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if message.type == "human":
            return _text(message)
    return ""


def _system_text(messages: list[BaseMessage]) -> str:
    parts = [_text(message) for message in messages if message.type == "system"]
    return "\n".join(parts)


def _service_in(text: str) -> str:
    for name in _SERVICES:
        if name in text:
            return name
    if "支付" in text:
        return "payment-api"
    if "订单" in text or "对账" in text:
        return "order-worker"
    if "redis" in text.lower() or "缓存" in text:
        return "redis"
    return ""


def _host_in(text: str) -> str:
    for host in ("pay-1", "ord-2", "cache-1"):
        if host in text:
            return host
    service = _service_in(text)
    return {"payment-api": "pay-1", "order-worker": "ord-2", "redis": "cache-1"}.get(service, "")


def _tool_call(name: str, args: dict[str, object]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": name,
                "args": args,
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "tool_call",
            }
        ],
    )


def _summarize_tools(messages: list[BaseMessage]) -> AIMessage:
    """工具已经返回。再发起工具调用会让图循环，所以这里直接收束成回答。"""

    chunks: list[str] = []
    for message in reversed(messages):
        if message.type == "tool":
            chunks.append(_text(message))
            continue
        if message.type == "ai":
            break
    body = "\n".join(reversed(chunks))
    return AIMessage(content=f"根据工具结果：\n{body}")


class KeywordRouterModel(BaseChatModel):
    """用关键词代替模型决策的聊天模型，接口与真实模型一致。"""

    @property
    def _llm_type(self) -> str:
        return "keyword-router"

    def bind_tools(self, tools, *, tool_choice: str | None = None, **kwargs: object) -> Runnable:
        """真实模型会在这里生成工具 schema。关键词模型只把调用接口留成一样的形状。"""

        return self.bind(tools=list(tools), tool_choice=tool_choice, **kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object | None = None,
        **kwargs: object,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        reply = self._reply(messages)
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def _reply(self, messages: list[BaseMessage]) -> AIMessage:
        if messages and messages[-1].type == "tool":
            return _summarize_tools(messages)

        text = _latest_human(messages)
        system = _system_text(messages)
        service = _service_in(text)
        host = _host_in(text)

        if "记住" in text:
            fact = text.split("记住", 1)[1].lstrip("：:").strip() or text
            return _tool_call("remember", {"fact": fact})

        if "重启" in text:
            return _tool_call("request_restart", {"service": service or "payment-api"})

        if any(word in text for word in ("刚才", "我刚才", "我是谁", "这次会话")):
            prior = [_text(message) for message in messages if message.type == "human"][:-1]
            if not prior:
                return AIMessage(content="这次会话里没有更早的说明。")
            joined = "\n".join(prior)
            return AIMessage(content=f"这次会话里你说过：\n{joined}")

        if any(word in text for word in ("谁负责", "负责人", "记得", "长期记忆")):
            marker = "长期记忆（跨会话，仅供参考）："
            if marker in system:
                remembered = system.split(marker, 1)[1].strip()
                if remembered:
                    return AIMessage(content=f"根据长期记忆：\n{remembered}")
            return _tool_call("recall", {"query": text})

        if any(word in text for word in ("怎么办", "如何", "怎么处理", "手册", "回滚", "OOM", "内存")):
            return _tool_call("search_runbooks", {"query": text})

        if "日志" in text:
            return _tool_call("tail_logs", {"service": service or "payment-api", "lines": 5})

        if any(word in text for word in ("磁盘", "空间", "disk")):
            return _tool_call("disk_usage", {"host": host})

        if any(word in text for word in ("哪些服务", "服务列表", "有哪些")):
            return _tool_call("list_services", {})

        if "状态" in text or (service and "服务" in text):
            if not service:
                return _tool_call("list_services", {})
            return _tool_call("service_status", {"service": service})

        return AIMessage(
            content=(
                "我可以查手册、看服务状态、看日志、看磁盘，"
                "也可以记住一条事实，或申请重启（需要人工批准）。"
            )
        )


def get_model(name: str | None = None) -> BaseChatModel:
    """`name` 优先，其次读 OPS_AGENT_MODEL，都没有就用关键词模型。"""

    chosen = (name if name is not None else os.environ.get("OPS_AGENT_MODEL", "")).strip()
    if not chosen:
        return KeywordRouterModel()
    from langchain.chat_models import init_chat_model

    return init_chat_model(chosen, temperature=0)
