"""OnCallAgent：一个用来学习 LangGraph 的运维助手。"""

from oncall_agent.graph import build_graph
from oncall_agent.parallel import build_triage_graph

__all__ = ["build_graph", "build_triage_graph"]
