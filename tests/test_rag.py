from oncall_agent.rag import get_retriever


def _top_source(query: str) -> str:
    documents = get_retriever().invoke(query)
    assert documents
    return documents[0].metadata["source"]


def test_disk_question_hits_disk_runbook():
    assert _top_source("磁盘满了，日志里有 no space left on device") == "disk_full.md"


def test_oom_question_hits_oom_runbook():
    assert _top_source("order-worker 被 Killed，Out of memory") == "oom.md"


def test_rollback_question_hits_rollback_runbook():
    assert _top_source("发布失败以后如何回滚到上一版") == "rollback.md"
