"""图的共享状态。

LangGraph 里，每个节点读同一份状态，并返回「要写回去的部分」。
`messages` 使用 `add_messages` reducer：新消息追加，相同 id 的消息覆盖。
`memories` 没有 reducer：节点返回这个字段时，整段被替换。
"""

from dataclasses import dataclass
from typing import NotRequired

from langgraph.graph import MessagesState


class OpsState(MessagesState):
    """运维助手在一次运行中的状态。"""

    # 本轮开始时从长期记忆里取出的文本。输入可以不带它。
    memories: NotRequired[str]


@dataclass(frozen=True)
class OpsContext:
    """一次调用的不可变上下文，不进 checkpoint。

    `user_id` 用来隔离长期记忆。不同用户可以共用一个 store，
    只要命名空间是 `(user_id, "memories")`。
    """

    user_id: str = "default"
