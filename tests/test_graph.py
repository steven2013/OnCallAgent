import pytest
from langgraph.types import Command

from oncall_agent.fleet import SERVICES, reset_fleet
from oncall_agent.graph import build_graph
from oncall_agent.llm import KeywordRouterModel
from oncall_agent.state import OpsContext
from oncall_agent.tools import remember


@pytest.fixture()
def graph():
    reset_fleet()
    built = build_graph(model=KeywordRouterModel())
    yield built
    reset_fleet()


def _invoke(graph, text: str, thread_id: str, user_id: str = "alice"):
    return graph.invoke(
        {"messages": [{"role": "user", "content": text}]},
        {"configurable": {"thread_id": thread_id}},
        context=OpsContext(user_id=user_id),
    )


def _tool_names(result) -> list[str]:
    names: list[str] = []
    for message in result["messages"]:
        for call in getattr(message, "tool_calls", None) or []:
            names.append(call["name"])
    return names


def _final(result) -> str:
    content = result["messages"][-1].content
    assert isinstance(content, str)
    return content


def test_graph_contains_learning_nodes(graph):
    nodes = set(graph.get_graph().nodes)
    assert {"recall_memory", "agent", "tools", "approve"} <= nodes


def test_runtime_argument_is_hidden_from_model():
    schema = remember.tool_call_schema.model_json_schema()
    assert "fact" in schema["properties"]
    assert "runtime" not in schema.get("properties", {})


def test_how_to_question_uses_runbook(graph):
    result = _invoke(graph, "磁盘满了怎么处理？", "rag")
    assert "search_runbooks" in _tool_names(result)
    assert "no space left" in _final(result)


def test_disk_tool(graph):
    result = _invoke(graph, "看一下 pay-1 的磁盘", "disk")
    assert _tool_names(result) == ["disk_usage"]
    assert "94%" in _final(result)


def test_short_term_memory_stays_on_one_thread(graph):
    _invoke(graph, "我是值班同学小陈，今天负责 payment-api", "shift")
    result = _invoke(graph, "我刚才说我负责哪个服务？", "shift")
    assert "payment-api" in _final(result)

    other = _invoke(graph, "我刚才说我负责哪个服务？", "another-shift")
    assert "没有更早的说明" in _final(other)


def test_long_term_memory_crosses_threads(graph):
    wrote = _invoke(graph, "记住：支付服务的负责人是小陈", "notes")
    assert "remember" in _tool_names(wrote)

    read = _invoke(graph, "支付服务的负责人是谁？", "next-day")
    humans = [message.content for message in read["messages"] if message.type == "human"]
    assert humans == ["支付服务的负责人是谁？"]
    assert "小陈" in _final(read)


def test_restart_can_be_rejected(graph):
    config = {"configurable": {"thread_id": "reject"}}
    context = OpsContext(user_id="alice")
    paused = graph.invoke(
        {"messages": [{"role": "user", "content": "请重启 payment-api"}]},
        config,
        context=context,
    )
    assert paused.get("__interrupt__")
    assert SERVICES["payment-api"]["status"] == "degraded"

    finished = graph.invoke(Command(resume={"approved": False}), config, context=context)
    assert "拒绝" in _final(finished)
    assert SERVICES["payment-api"]["status"] == "degraded"
    assert SERVICES["payment-api"]["restarts"] == 1


def test_restart_runs_only_after_approval(graph):
    config = {"configurable": {"thread_id": "approve"}}
    context = OpsContext(user_id="alice")
    graph.invoke(
        {"messages": [{"role": "user", "content": "请重启 payment-api"}]},
        config,
        context=context,
    )
    finished = graph.invoke(Command(resume={"approved": True}), config, context=context)
    assert "模拟重启" in _final(finished)
    assert SERVICES["payment-api"]["status"] == "running"
    assert SERVICES["payment-api"]["restarts"] == 2
