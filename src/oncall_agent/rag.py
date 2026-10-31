"""把本地手册切块、嵌入，并做成检索器。

这是 RAG 的索引侧。检索本身是普通函数；要让 Agent 决定「要不要查」，
再把它包成工具，交给 LangGraph 的 ToolNode。见 tools.search_runbooks。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

from oncall_agent.embeddings import LocalHashEmbeddings

KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"


def load_runbooks() -> list[Document]:
    documents: list[Document] = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        documents.append(
            Document(
                page_content=path.read_text(encoding="utf-8"),
                metadata={"source": path.name},
            )
        )
    if not documents:
        raise FileNotFoundError(f"没有找到手册：{KNOWLEDGE_DIR}")
    return documents


def split_runbooks(documents: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", "。", "，", " ", ""],
        chunk_size=500,
        chunk_overlap=80,
    )
    return splitter.split_documents(documents)


@lru_cache(maxsize=1)
def get_retriever():
    """进程内只建一次索引。手册是随包发布的静态文件。"""

    vector_store = InMemoryVectorStore.from_documents(
        split_runbooks(load_runbooks()),
        LocalHashEmbeddings(),
    )
    return vector_store.as_retriever(search_kwargs={"k": 3})
