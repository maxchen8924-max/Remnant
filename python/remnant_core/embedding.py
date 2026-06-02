"""本地 Embedding 服务 — 实现白皮书 RAG Pipeline 的 embedding 生成。

提供 EmbeddingService 单例类:
- load_model(model_name="bge-small-zh") — 加载模型
- embed(text_or_list) — 生成 embedding 向量
- 回退策略: 如果 sentence-transformers 不可用，使用 sklearn TfidfVectorizer
- 单例模式，模型只加载一次
"""

from __future__ import annotations

import threading
from typing import Any


class EmbeddingService:
    """本地 Embedding 服务 — 单例模式。

    自动检测可用后端:
    1. sentence-transformers (优先): 使用 BGE/GTE 等高质量模型
    2. sklearn TfidfVectorizer (回退): 轻量级 TF-IDF 向量化

    使用示例::

        service = EmbeddingService()
        service.load_model("bge-small-zh")
        vec = service.embed("爸爸喜欢喝茶")
        vecs = service.embed(["文本1", "文本2"])
    """

    _instance: EmbeddingService | None = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> EmbeddingService:
        """单例模式 — 确保全局只有一个实例。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._model: Any = None
        self._model_name: str | None = None
        self._backend: str = "none"  # 'sentence_transformers' | 'sklearn' | 'none'
        self._dimension: int = 0

    def load_model(self, model_name: str = "bge-small-zh") -> None:
        """加载 embedding 模型。

        按优先级尝试:
        1. sentence-transformers (BGE/GTE 模型)
        2. sklearn TfidfVectorizer (回退)

        Args:
            model_name: 模型名称，默认 'bge-small-zh'
        """
        if self._model is not None and self._model_name == model_name:
            return  # 模型已加载

        # 尝试加载 sentence-transformers
        try:
            from sentence_transformers import SentenceTransformer

            model_path = _resolve_model_path(model_name)
            self._model = SentenceTransformer(model_path)
            self._model_name = model_name
            self._backend = "sentence_transformers"
            self._dimension = self._model.get_sentence_embedding_dimension()
            return
        except ImportError:
            pass
        except Exception:
            pass

        # 回退: sklearn TfidfVectorizer
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer

            # TfidfVectorizer 需要 fit 后才能 transform
            # 使用预定义的 token_pattern 支持中文
            vectorizer = TfidfVectorizer(
                analyzer="char_wb",
                ngram_range=(2, 4),
                max_features=512,
            )
            self._model = vectorizer  # 注意: 需要 fit 后才能使用
            self._model_name = model_name
            self._backend = "sklearn"
            self._dimension = 512
            # sklearn 后端需要在第一次 embed 时 fit
            self._sklearn_fitted = False
            return
        except ImportError:
            pass

        raise RuntimeError(
            "无法加载 embedding 模型: "
            "sentence-transformers 和 sklearn 均不可用。"
            "请安装: pip install sentence-transformers 或 pip install scikit-learn"
        )

    def embed(self, text_or_list: str | list[str]) -> list[float] | list[list[float]]:
        """生成文本的 embedding 向量。

        Args:
            text_or_list: 单个文本字符串或文本列表

        Returns:
            单个文本 → list[float]；文本列表 → list[list[float]]
        """
        if self._model is None:
            self.load_model()

        if self._backend == "sentence_transformers":
            return self._embed_sentence_transformers(text_or_list)
        elif self._backend == "sklearn":
            return self._embed_sklearn(text_or_list)
        else:
            raise RuntimeError("Embedding 模型未加载")

    def _embed_sentence_transformers(
        self, text_or_list: str | list[str]
    ) -> list[float] | list[list[float]]:
        """使用 sentence-transformers 生成 embedding。"""
        is_single = isinstance(text_or_list, str)
        texts = [text_or_list] if is_single else text_or_list

        # sentence-transformers 返回 numpy array
        embeddings = self._model.encode(texts, normalize_embeddings=True)

        result = embeddings.tolist()
        if is_single:
            return result[0]
        return result

    def _embed_sklearn(
        self, text_or_list: str | list[str]
    ) -> list[float] | list[list[float]]:
        """使用 sklearn TfidfVectorizer 生成 embedding。

        首次调用时自动 fit vectorizer。
        """
        is_single = isinstance(text_or_list, str)
        texts = [text_or_list] if is_single else text_or_list
        all_texts = list(texts)

        if not self._sklearn_fitted:
            # 首次使用: fit vectorizer
            # 如果只有 1 个文本，需要补充虚拟数据以 fit
            if len(all_texts) < 2:
                all_texts = list(all_texts) + ["placeholder text for fitting"]
            self._model.fit(all_texts)
            self._sklearn_fitted = True
            self._dimension = len(self._model.get_feature_names_out())

        # transform
        sparse_matrix = self._model.transform(texts)
        dense = sparse_matrix.toarray()

        # 标准化为 L2 单位向量
        import math

        result: list[list[float]] = []
        for row in dense:
            norm = math.sqrt(sum(v * v for v in row))
            if norm > 0:
                result.append([float(v / norm) for v in row])
            else:
                result.append([0.0] * len(row))

        if is_single:
            return result[0]
        return result

    @property
    def backend(self) -> str:
        """返回当前使用的后端名称。"""
        return self._backend

    @property
    def dimension(self) -> int:
        """返回当前模型的向量维度。"""
        return self._dimension

    @property
    def model_name(self) -> str | None:
        """返回当前加载的模型名称。"""
        return self._model_name

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例实例（主要用于测试）。"""
        with cls._lock:
            cls._instance = None


def _resolve_model_path(model_name: str) -> str:
    """解析模型名称到实际路径。

    支持简写名称映射到 HuggingFace 模型 ID。

    Args:
        model_name: 简写模型名称

    Returns:
        实际模型路径或 HuggingFace ID
    """
    _MODEL_MAP: dict[str, str] = {
        "bge-small-zh": "BAAI/bge-small-zh-v1.5",
        "bge-small-en": "BAAI/bge-small-en-v1.5",
        "bge-base-zh": "BAAI/bge-base-zh-v1.5",
        "gte-small": "thenlper/gte-small",
        "all-MiniLM": "sentence-transformers/all-MiniLM-L6-v2",
    }
    return _MODEL_MAP.get(model_name, model_name)


# 便捷函数
def get_embedding_service() -> EmbeddingService:
    """获取 EmbeddingService 单例实例。

    Returns:
        EmbeddingService 单例
    """
    return EmbeddingService()
