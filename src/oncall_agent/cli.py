"""命令行：观察每个节点的更新，并在 interrupt 处询问是否批准。"""

from __future__ import annotations

import argparse
import json

from langchain_core.messages import BaseMessage
from langgraph.types import Command

from oncall_agent.fleet import SERVICES, reset_fleet
from oncall_agent.graph import build_graph
from oncall_agent.llm import KeywordRouterModel, get_model
from oncall_agent.state import OpsContext


def _brief(message: BaseMessage, limit: int = 500) -> str:
    content = message.content if isinstance(message.content, str) else str(message.content)
    calls = getattr(message, "tool_calls", None) or []
    if calls:
        rendered = ", ".join(
            f"{call['name']}({json.dumps(call['args'], ensure_ascii=False)})" for call in calls
        )
        return f"调用工具 {rendered}"
    collapsed = " ".join(content.split())
    if len(collapsed) > limit:
        return collapsed[:limit] + "..."
    return collapsed


def _print_stream(graph, payload, config, context) -> None:
    for update in graph.stream(payload, config, context=context, stream_mode="updates"):
        for node, writes in update.items():
            if node == "__interrupt__":
                print(f"[{node}] 图已暂停，等待批准")
                continue
            messages = writes.get("messages") if isinstance(writes, dict) else None
            if messages:
                print(f"[{node}] {_brief(messages[-1])}")
            elif isinstance(writes, dict) and "memories" in writes:
                preview = writes["memories"] or "（空）"
                print(f"[{node}] 长期记忆 {preview}")
            else:
                print(f"[{node}]")


def _pending(graph, config):
    snapshot = graph.get_state(config)
    return snapshot.interrupts


def run_turn(graph, text: str, *, thread_id: str, user_id: str) -> None:
    config = {"configurable": {"thread_id": thread_id}}
    context = OpsContext(user_id=user_id)
    _print_stream(
        graph,
        {"messages": [{"role": "user", "content": text}]},
        config,
        context,
    )
    interrupts = _pending(graph, config)
    if not interrupts:
        return
    payload = interrupts[0].value
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    answer = input("批准这个操作？[y/N] ").strip().lower()
    _print_stream(
        graph,
        Command(resume={"approved": answer in {"y", "yes"}}),
        config,
        context,
    )


def run_demo() -> None:
    """固定剧本，全部走关键词模型。"""

    reset_fleet()
    graph = build_graph(model=KeywordRouterModel(), store=None, checkpointer=None)
    user_id = "demo-user"

    def turn(title: str, text: str, thread_id: str) -> None:
        print(f"\n## {title}")
        print(f"you> {text}")
        run_scripted(graph, text, thread_id=thread_id, user_id=user_id)

    turn("手册检索", "磁盘满了怎么处理？", "incident")
    turn("查看磁盘", "看一下 pay-1 的磁盘", "incident")
    turn("短期记忆", "我刚才说的是哪台机器？", "incident")
    turn("写入长期记忆", "记住：支付服务的负责人是小陈", "notebook")
    turn("另一条会话读取长期记忆", "支付服务的负责人是谁？", "other-shift")
    print("\n## 重启需要批准，先拒绝")
    print("you> 请重启 payment-api")
    resume_restart(graph, approved=False, thread_id="change-1", user_id=user_id)
    print(f"payment-api status={SERVICES['payment-api']['status']}")
    print("\n## 同一申请在新会话里批准")
    print("you> 请重启 payment-api")
    resume_restart(graph, approved=True, thread_id="change-2", user_id=user_id)
    print(
        "payment-api "
        f"status={SERVICES['payment-api']['status']} "
        f"restarts={SERVICES['payment-api']['restarts']}"
    )


def run_scripted(graph, text: str, *, thread_id: str, user_id: str) -> None:
    config = {"configurable": {"thread_id": thread_id}}
    context = OpsContext(user_id=user_id)
    _print_stream(
        graph,
        {"messages": [{"role": "user", "content": text}]},
        config,
        context,
    )


def resume_restart(graph, *, approved: bool, thread_id: str, user_id: str) -> None:
    config = {"configurable": {"thread_id": thread_id}}
    context = OpsContext(user_id=user_id)
    _print_stream(
        graph,
        {"messages": [{"role": "user", "content": "请重启 payment-api"}]},
        config,
        context,
    )
    interrupts = _pending(graph, config)
    if not interrupts:
        print("没有进入审批节点。")
        return
    print(json.dumps(interrupts[0].value, ensure_ascii=False))
    _print_stream(graph, Command(resume={"approved": approved}), config, context)


def print_mermaid() -> None:
    graph = build_graph(model=KeywordRouterModel())
    print(graph.get_graph().draw_mermaid())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="学习用的 LangGraph 运维 Agent")
    sub = parser.add_subparsers(dest="command", required=True)

    chat = sub.add_parser("chat", help="多轮对话")
    chat.add_argument("--thread", default="demo")
    chat.add_argument("--user", default="local")
    chat.add_argument("--model", default=None, help="例如 openai:gpt-4o-mini")
    chat.add_argument("--scripted", action="store_true", help="强制使用关键词模型")

    sub.add_parser("demo", help="跑一遍固定剧本")
    sub.add_parser("graph", help="打印 mermaid 图")

    args = parser.parse_args(argv)
    if args.command == "graph":
        print_mermaid()
        return 0
    if args.command == "demo":
        run_demo()
        return 0

    model = KeywordRouterModel() if args.scripted else get_model(args.model)
    graph = build_graph(model=model)
    label = "关键词模型" if isinstance(model, KeywordRouterModel) else args.model or "环境变量中的模型"
    print(f"OnCallAgent（{label}）。thread={args.thread} user={args.user}。输入 exit 退出。")
    while True:
        try:
            text = input("you> ").strip()
        except EOFError:
            print()
            return 0
        if text in {"exit", "quit"}:
            return 0
        if not text:
            continue
        run_turn(graph, text, thread_id=args.thread, user_id=args.user)
    return 0
