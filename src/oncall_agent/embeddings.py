"""不依赖外部 API 的哈希向量。

真实项目应换成 `langchain.embeddings.init_embeddings(...)`。
这里用字符和词的哈希桶，让手册检索和长期记忆在没有密钥时也能演示语义搜索的接口。
它只对词面重叠敏感，所以手册里写了「关键词」行。
"""

from __future__ import annotations

import hashlib
import math
import re

from langchain_core.embeddings import Embeddings

DIMS = 256
_TOKEN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")


def _tokens(text: str) -> list[str]:
    pieces = _TOKEN.findall(text.lower())
    cjk = [piece for piece in pieces if len(piece) == 1 and "\u4e00" <= piece <= "\u9fff"]
    bigrams = [cjk[index] + cjk[index + 1] for index in range(len(cjk) - 1)]
    return pieces + bigrams or ["empty"]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """InMemoryStore 的 index.embed 需要这个签名。"""

    vectors: list[list[float]] = []
    for text in texts:
        bucket = [0.0] * DIMS
        for token in _tokens(text):
            digest = hashlib.md5(token.encode("utf-8")).hexdigest()
            bucket[int(digest, 16) % DIMS] += 1.0
        norm = math.sqrt(sum(value * value for value in bucket)) or 1.0
        vectors.append([value / norm for value in bucket])
    return vectors


class LocalHashEmbeddings(Embeddings):
    """给 InMemoryVectorStore 用的 Embeddings 适配器。"""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return embed_texts(texts)

    def embed_query(self, text: str) -> list[float]:
        return embed_texts([text])[0]
