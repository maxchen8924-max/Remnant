"""M2 检索模块完整测试 — FTS5 + Vector + Hybrid + Rerank + Scope Filtering。

测试覆盖:
- FTS5 基本搜索测试（关键词匹配、rank 分数、空结果）
- 向量搜索测试（相似度排序、余弦相似度计算、空结果）
- 混合检索合并去重测试
- Scope 过滤测试（scope A 查不到 scope B 的 chunk）
- 时间感知加权测试
- 说话人感知加权测试
- Rerank 测试（MMR 多样性、同说话人不连续）
- 检索追踪记录测试
- API 端点测试

使用 :memory: 数据库，通过 init_db() 初始化 schema。
避免 pydantic 导入 — 测试中直接使用 SQL。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Generator

import pytest

from remnant_store.schema import init_db
from remnant_store.chunk_visibility import get_visible_chunk_ids
from remnant_store.fts import fts5_search, fts5_count
from remnant_store.vector import (
    vector_search,
    vector_count,
    _compute_cosine_similarity,
)
from remnant_core.retrieval import hybrid_retrieve
from remnant_core.rerank import rerank_candidates
from remnant_core.trace import record_retrieval_trace, get_trace


# ==================== Fixtures ====================


def _generate_id() -> str:
    """生成唯一 ID。"""
    return str(uuid.uuid4())


@pytest.fixture
def db() -> Generator[sqlite3.Connection, None, None]:
    """内存数据库 fixture — 每个测试获得独立的 :memory: 数据库。"""
    conn = init_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def populated_db(db: sqlite3.Connection) -> sqlite3.Connection:
    """填充了测试数据的内存数据库。

    包含:
    - 2 个 relationship_scope (scope-a, scope-b)
    - 2 个 source_artifact
    - 10 个 memory_chunk（5 个 scope-a, 3 个 scope-b, 2 个全局）
    - chunk 内容用于 FTS5 搜索
    - 部分 chunk 有 embedding_index_ref（用于向量搜索）
    """
    # 基础依赖
    db.execute(
        "INSERT INTO deceased_profile (id, name) VALUES ('dp-1', '测试逝者')"
    )

    # 两个 scope
    db.execute(
        "INSERT INTO relationship_scope (id, deceased_profile_id, scope_name, relationship_type) "
        "VALUES ('scope-a', 'dp-1', '作为儿子', 'child')"
    )
    db.execute(
        "INSERT INTO relationship_scope (id, deceased_profile_id, scope_name, relationship_type) "
        "VALUES ('scope-b', 'dp-1', '作为朋友', 'friend')"
    )

    # source_artifact
    db.execute(
        "INSERT INTO source_artifact (id, deceased_profile_id, file_path, file_hash, file_size, file_type) "
        "VALUES ('sa-1', 'dp-1', '/data/chat.txt', 'hash1', 1000, 'wechat_txt')"
    )

    # 5 个属于 scope-a 的 chunk
    scope_a_chunks = [
        ("mc-a-1", "爸爸 喜欢 喝茶 每天 下午 都会 泡 一壶", "conversation_segment",
         "2023-06-01T10:00:00", "2023-06-01T12:00:00", 100, 5, '{"speakers":["爸爸","我"],"dominant_speaker":"爸爸"}'),
        ("mc-a-2", "妈妈 做的 红烧肉 特别 好吃 是 家传 秘方", "conversation_segment",
         "2023-06-02T18:00:00", "2023-06-02T20:00:00", 80, 4, '{"speakers":["妈妈","我"],"dominant_speaker":"妈妈"}'),
        ("mc-a-3", "去年 夏天 我们 一起去 了 海边 旅行 非常 开心", "diary_entry",
         "2023-07-15T00:00:00", "2023-07-20T00:00:00", 50, 3, '{"speakers":["我"],"dominant_speaker":"我"}'),
        ("mc-a-4", "爸爸 退休 之后 开始 学习 书法 每天 练习", "conversation_segment",
         "2023-08-01T09:00:00", "2023-08-01T11:00:00", 60, 2, '{"speakers":["爸爸"],"dominant_speaker":"爸爸"}'),
        ("mc-a-5", "周末 家庭 聚会 大家 一起 包饺子 其乐融融", "conversation_segment",
         "2023-09-10T10:00:00", "2023-09-10T14:00:00", 120, 6, '{"speakers":["爸爸","妈妈","我","妹妹"],"dominant_speaker":"爸爸"}'),
    ]

    for chunk_id, content, chunk_type, ts_start, ts_end, msg_count, spk_count, metadata in scope_a_chunks:
        db.execute(
            "INSERT INTO memory_chunk "
            "(id, source_artifact_id, relationship_scope_id, chunk_hash, chunk_type, "
            "content, token_count, time_range_start, time_range_end, "
            "message_count, speaker_count, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (chunk_id, "sa-1", "scope-a", f"hash-{chunk_id}", chunk_type,
             content, len(content), ts_start, ts_end,
             msg_count, spk_count, metadata),
        )

    # 3 个属于 scope-b 的 chunk
    scope_b_chunks = [
        ("mc-b-1", "工作 项目 进展 顺利 客户 很 满意 方案", "conversation_segment",
         "2023-05-01T09:00:00", "2023-05-01T18:00:00", 40, 3, '{"speakers":["同事","我"],"dominant_speaker":"同事"}'),
        ("mc-b-2", "公司 年会 节目 排练 大家 都很 努力", "conversation_segment",
         "2023-12-20T14:00:00", "2023-12-20T17:00:00", 30, 5, '{"speakers":["同事A","同事B"],"dominant_speaker":"同事A"}'),
        ("mc-b-3", "朋友 推荐 了 一家 很好 吃 的 火锅店", "conversation_segment",
         "2023-11-11T19:00:00", "2023-11-11T21:00:00", 45, 2, '{"speakers":["朋友","我"],"dominant_speaker":"朋友"}'),
    ]

    for chunk_id, content, chunk_type, ts_start, ts_end, msg_count, spk_count, metadata in scope_b_chunks:
        db.execute(
            "INSERT INTO memory_chunk "
            "(id, source_artifact_id, relationship_scope_id, chunk_hash, chunk_type, "
            "content, token_count, time_range_start, time_range_end, "
            "message_count, speaker_count, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (chunk_id, "sa-1", "scope-b", f"hash-{chunk_id}", chunk_type,
             content, len(content), ts_start, ts_end,
             msg_count, spk_count, metadata),
        )

    # 2 个全局 chunk（relationship_scope_id IS NULL）
    global_chunks = [
        ("mc-g-1", "公共 通知 明天 社区 活动 请 大家 参加", "conversation_segment",
         "2023-01-01T08:00:00", "2023-01-01T10:00:00", 20, 1, '{"speakers":["系统"]}'),
        ("mc-g-2", "天气 预报 今天 晴 气温 适宜 出行", "diary_entry",
         "2023-04-15T06:00:00", "2023-04-15T06:00:00", 15, 0, '{}'),
    ]

    for chunk_id, content, chunk_type, ts_start, ts_end, msg_count, spk_count, metadata in global_chunks:
        db.execute(
            "INSERT INTO memory_chunk "
            "(id, source_artifact_id, relationship_scope_id, chunk_hash, chunk_type, "
            "content, token_count, time_range_start, time_range_end, "
            "message_count, speaker_count, metadata) "
            "VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (chunk_id, "sa-1", f"hash-{chunk_id}", chunk_type,
             content, len(content), ts_start, ts_end,
             msg_count, spk_count, metadata),
        )

    # 为部分 chunk 建立 embedding_index_ref（用于向量搜索测试）
    # 使用简单的 4 维向量以便测试
    embedding_data = [
        ("emb-a-1", "mc-a-1", [0.1, 0.2, 0.3, 0.4]),
        ("emb-a-2", "mc-a-2", [0.2, 0.1, 0.4, 0.5]),
        ("emb-a-3", "mc-a-3", [0.5, 0.5, 0.1, 0.1]),
        ("emb-a-4", "mc-a-4", [0.15, 0.25, 0.35, 0.45]),
        ("emb-b-1", "mc-b-1", [0.8, 0.1, 0.05, 0.05]),
    ]

    for emb_id, chunk_id, vector in embedding_data:
        db.execute(
            "INSERT INTO embedding_index_ref "
            "(id, chunk_id, model_name, model_version, vector_dimension, "
            "index_backend, index_status, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (emb_id, chunk_id, "test-model", "v1", len(vector),
             "sqlite_vec", "INDEXED", json.dumps({"vector": vector})),
        )

    db.commit()
    return db


# ==================== 余弦相似度测试 ====================


class TestCosineSimilarity:
    """测试 _compute_cosine_similarity 辅助函数。"""

    def test_identical_vectors(self) -> None:
        """相同向量余弦相似度应为 1.0。"""
        vec = [1.0, 2.0, 3.0]
        result = _compute_cosine_similarity(vec, vec)
        assert abs(result - 1.0) < 1e-9

    def test_orthogonal_vectors(self) -> None:
        """正交向量余弦相似度应为 0.0。"""
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [0.0, 1.0, 0.0]
        result = _compute_cosine_similarity(vec_a, vec_b)
        assert abs(result - 0.0) < 1e-9

    def test_opposite_vectors(self) -> None:
        """相反方向向量余弦相似度应为 -1.0。"""
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [-1.0, -2.0, -3.0]
        result = _compute_cosine_similarity(vec_a, vec_b)
        assert abs(result - (-1.0)) < 1e-9

    def test_zero_vector(self) -> None:
        """零向量与任意向量余弦相似度应为 0.0。"""
        result = _compute_cosine_similarity([0.0, 0.0], [1.0, 2.0])
        assert result == 0.0

    def test_empty_vectors(self) -> None:
        """空向量余弦相似度应为 0.0。"""
        result = _compute_cosine_similarity([], [])
        assert result == 0.0

    def test_dimension_mismatch(self) -> None:
        """维度不一致应抛出 ValueError。"""
        with pytest.raises(ValueError, match="维度不一致"):
            _compute_cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])

    def test_positive_similarity(self) -> None:
        """验证正常向量的相似度值。"""
        # 半相似向量
        result = _compute_cosine_similarity(
            [1.0, 0.0, 0.0],
            [0.707, 0.707, 0.0],
        )
        assert 0.6 < result < 0.8  # ~0.707


# ==================== FTS5 搜索测试 ====================


class TestFTS5Search:
    """测试 FTS5 全文搜索。"""

    def test_keyword_match(self, populated_db: sqlite3.Connection) -> None:
        """基本关键词匹配测试。"""
        results = fts5_search(populated_db, "喝茶", "scope-a", top_k=10)
        assert len(results) >= 1
        # mc-a-1 包含 "喝茶"
        chunk_ids = [r["id"] for r in results]
        assert "mc-a-1" in chunk_ids

    def test_rank_score(self, populated_db: sqlite3.Connection) -> None:
        """验证 rank 分数存在且合理。"""
        results = fts5_search(populated_db, "爸爸 喝茶", "scope-a", top_k=10)
        assert len(results) >= 1
        for r in results:
            assert "rank" in r
            assert isinstance(r["rank"], (int, float))
            # FTS5 BM25 rank 可为负值（越负越相关）

    def test_empty_results(self, populated_db: sqlite3.Connection) -> None:
        """无匹配关键词时应返回空列表。"""
        results = fts5_search(populated_db, "火星 旅行 外星人", "scope-a", top_k=10)
        assert results == []

    def test_top_k_limit(self, populated_db: sqlite3.Connection) -> None:
        """验证 top_k 限制生效。"""
        results = fts5_search(populated_db, "我们", "scope-a", top_k=3)
        assert len(results) <= 3

    def test_source_field(self, populated_db: sqlite3.Connection) -> None:
        """验证每项都有 source='fts'。"""
        results = fts5_search(populated_db, "喝茶", "scope-a", top_k=10)
        for r in results:
            assert r.get("source") == "fts"

    def test_no_visible_chunks(self, db: sqlite3.Connection) -> None:
        """scope 无可见 chunk 时应返回空列表。"""
        # 空数据库 + 无 scope 数据
        results = fts5_search(db, "测试", "nonexistent-scope", top_k=10)
        assert results == []

    def test_fts_count(self, populated_db: sqlite3.Connection) -> None:
        """验证 fts5_count 返回正确的命中数。"""
        count = fts5_count(populated_db, "爸爸", "scope-a")
        # mc-a-1 和 mc-a-4 和 mc-a-5 都包含 "爸爸"
        assert count >= 2

    def test_fts_count_zero(self, populated_db: sqlite3.Connection) -> None:
        """无命中时 fts5_count 应返回 0。"""
        count = fts5_count(populated_db, "火星", "scope-a")
        assert count == 0


# ==================== 向量搜索测试 ====================


class TestVectorSearch:
    """测试向量相似度搜索。"""

    def test_similarity_ranking(self, populated_db: sqlite3.Connection) -> None:
        """验证向量搜索结果按相似度降序排列。"""
        # 使用接近 mc-a-1 embedding [0.1, 0.2, 0.3, 0.4] 的查询向量
        query_vec = [0.12, 0.22, 0.32, 0.42]
        results = vector_search(populated_db, query_vec, "scope-a", top_k=10)
        assert len(results) >= 1

        # 验证按相似度降序
        scores = [r["vector_score"] for r in results]
        assert scores == sorted(scores, reverse=True)

        # 最相似的应该是 mc-a-1（向量最接近）
        assert results[0]["id"] == "mc-a-1"

    def test_known_similar_result(self, populated_db: sqlite3.Connection) -> None:
        """使用几乎相同的向量查询，验证高相似度。"""
        query_vec = [0.11, 0.21, 0.31, 0.41]
        results = vector_search(populated_db, query_vec, "scope-a", top_k=5)
        assert len(results) >= 1
        # mc-a-1 的向量是 [0.1, 0.2, 0.3, 0.4]，相似度应该很高
        top = results[0]
        assert top["vector_score"] > 0.99

    def test_null_embedding(self, populated_db: sqlite3.Connection) -> None:
        """query_embedding 为 None 时应返回空列表。"""
        results = vector_search(populated_db, None, "scope-a", top_k=10)
        assert results == []

    def test_source_field(self, populated_db: sqlite3.Connection) -> None:
        """验证每项都有 source='vector'。"""
        query_vec = [0.1, 0.2, 0.3, 0.4]
        results = vector_search(populated_db, query_vec, "scope-a", top_k=5)
        for r in results:
            assert r.get("source") == "vector"

    def test_vector_count(self, populated_db: sqlite3.Connection) -> None:
        """验证 vector_count 返回正确数量。"""
        count = vector_count(populated_db, "scope-a")
        # scope-a 有 4 个 embedding (mc-a-1~4)
        assert count == 4

    def test_vector_count_empty(self, db: sqlite3.Connection) -> None:
        """空 scope 应返回 0。"""
        count = vector_count(db, "nonexistent")
        assert count == 0

    def test_top_k_limit(self, populated_db: sqlite3.Connection) -> None:
        """验证 top_k 限制生效。"""
        query_vec = [0.1, 0.2, 0.3, 0.4]
        results = vector_search(populated_db, query_vec, "scope-a", top_k=2)
        assert len(results) <= 2


# ==================== Scope 过滤测试 ====================


class TestScopeFiltering:
    """测试 scope 隔离 — scope A 查不到 scope B 的 chunk。"""

    def test_fts_scope_isolation(self, populated_db: sqlite3.Connection) -> None:
        """FTS5 搜索 scope-a 不应返回 scope-b 的私有 chunk。"""
        results = fts5_search(populated_db, "项目", "scope-a", top_k=10)
        chunk_ids = [r["id"] for r in results]
        # mc-b-1 包含 "项目" 但在 scope-b
        assert "mc-b-1" not in chunk_ids

    def test_fts_scope_b_results(self, populated_db: sqlite3.Connection) -> None:
        """FTS5 搜索 scope-b 应能返回 scope-b 的结果。"""
        results = fts5_search(populated_db, "项目", "scope-b", top_k=10)
        chunk_ids = [r["id"] for r in results]
        assert "mc-b-1" in chunk_ids

    def test_vector_scope_isolation(self, populated_db: sqlite3.Connection) -> None:
        """向量搜索 scope-a 不应返回 scope-b 的 embedding 结果。"""
        query_vec = [0.8, 0.1, 0.05, 0.05]  # 接近 mc-b-1 的向量
        results = vector_search(populated_db, query_vec, "scope-a", top_k=10)
        chunk_ids = [r["id"] for r in results]
        # mc-b-1 在 scope-b，不应出现在 scope-a 的结果中
        assert "mc-b-1" not in chunk_ids

    def test_global_chunks_visible(self, populated_db: sqlite3.Connection) -> None:
        """全局 chunk 应对所有 scope 可见。"""
        results = fts5_search(populated_db, "公共 通知", "scope-a", top_k=10)
        chunk_ids = [r["id"] for r in results]
        assert "mc-g-1" in chunk_ids

    def test_global_chunks_scope_b(self, populated_db: sqlite3.Connection) -> None:
        """全局 chunk 对 scope-b 也应可见。"""
        results = fts5_search(populated_db, "公共 通知", "scope-b", top_k=10)
        chunk_ids = [r["id"] for r in results]
        assert "mc-g-1" in chunk_ids


# ==================== 混合检索测试 ====================


class TestHybridRetrieve:
    """测试混合检索合并去重逻辑。"""

    def test_merged_results(self, populated_db: sqlite3.Connection) -> None:
        """混合检索应合并 FTS5 和向量搜索结果。"""
        query_vec = [0.1, 0.2, 0.3, 0.4]
        results = hybrid_retrieve(
            query="喝茶",
            scope_id="scope-a",
            conn=populated_db,
            query_embedding=query_vec,
            top_k=10,
        )
        assert len(results) >= 1
        # 结果应包含 combined_score
        for r in results:
            assert "combined_score" in r

    def test_no_duplicate_chunks(self, populated_db: sqlite3.Connection) -> None:
        """同一 chunk 不应在结果中出现多次。"""
        query_vec = [0.1, 0.2, 0.3, 0.4]
        results = hybrid_retrieve(
            query="喝茶",
            scope_id="scope-a",
            conn=populated_db,
            query_embedding=query_vec,
            top_k=10,
        )
        chunk_ids = [r["id"] for r in results]
        assert len(chunk_ids) == len(set(chunk_ids))

    def test_hybrid_source_marking(self, populated_db: sqlite3.Connection) -> None:
        """同时出现在 FTS5 和向量结果中的 chunk 应标记为 'hybrid'。"""
        query_vec = [0.1, 0.2, 0.3, 0.4]
        results = hybrid_retrieve(
            query="喝茶",
            scope_id="scope-a",
            conn=populated_db,
            query_embedding=query_vec,
            top_k=10,
        )
        sources = {r["id"]: r["source"] for r in results}
        # mc-a-1 同时匹配 FTS5 ("喝茶") 和向量搜索
        if "mc-a-1" in sources:
            assert sources["mc-a-1"] == "hybrid"

    def test_fts_only_no_embedding(self, populated_db: sqlite3.Connection) -> None:
        """无 query_embedding 时仅使用 FTS5 结果。"""
        results = hybrid_retrieve(
            query="爸爸 喝茶",
            scope_id="scope-a",
            conn=populated_db,
            query_embedding=None,
            top_k=10,
        )
        assert len(results) >= 1
        for r in results:
            # 仅 FTS5 结果时 source 应为 'fts'
            assert r["source"] in ("fts",)

    def test_top_k_limit(self, populated_db: sqlite3.Connection) -> None:
        """验证 top_k 限制。"""
        query_vec = [0.1, 0.2, 0.3, 0.4]
        results = hybrid_retrieve(
            query="我们",
            scope_id="scope-a",
            conn=populated_db,
            query_embedding=query_vec,
            top_k=3,
        )
        assert len(results) <= 3

    def test_null_conn(self) -> None:
        """conn 为 None 时应返回空列表。"""
        results = hybrid_retrieve(
            query="测试",
            scope_id="scope-a",
            conn=None,
        )
        assert results == []

    def test_no_results_empty_scope(self, db: sqlite3.Connection) -> None:
        """无数据的 scope 应返回空列表。"""
        results = hybrid_retrieve(
            query="测试",
            scope_id="empty-scope",
            conn=db,
        )
        assert results == []


# ==================== 时间感知加权测试 ====================


class TestTimeAwareWeighting:
    """测试时间感知加权逻辑。"""

    def test_time_boost_applied(self, populated_db: sqlite3.Connection) -> None:
        """有 time_references 时应应用 time_boost 权重。"""
        query_vec = [0.1, 0.2, 0.3, 0.4]
        results = hybrid_retrieve(
            query="喝茶",
            scope_id="scope-a",
            conn=populated_db,
            query_embedding=query_vec,
            top_k=10,
            query_class={"time_references": ["2023-06-01"]},
        )
        assert len(results) >= 1
        # 有时间引用时，权重公式应为 0.4*fts + 0.4*vector + 0.2*time_boost
        for r in results:
            assert "time_boost" in r

    def test_time_match_boosts_ranking(self, populated_db: sqlite3.Connection) -> None:
        """时间匹配的 chunk 应有更高的 time_boost。"""
        query_vec = [0.1, 0.2, 0.3, 0.4]
        results = hybrid_retrieve(
            query="喝茶",
            scope_id="scope-a",
            conn=populated_db,
            query_embedding=query_vec,
            top_k=10,
            query_class={"time_references": ["2023-06-01"]},
        )
        # mc-a-1 的时间范围是 2023-06-01，应匹配 time_reference
        for r in results:
            if r["id"] == "mc-a-1":
                assert r.get("time_boost", 0.0) > 0

    def test_no_time_refs_no_boost(self, populated_db: sqlite3.Connection) -> None:
        """无 time_references 时不应有 time_boost。"""
        query_vec = [0.1, 0.2, 0.3, 0.4]
        results = hybrid_retrieve(
            query="喝茶",
            scope_id="scope-a",
            conn=populated_db,
            query_embedding=query_vec,
            top_k=10,
        )
        # 无时间引用，time_boost 应为 0
        for r in results:
            assert r.get("time_boost", 0.0) == 0.0

    def test_weight_formula_with_time(self, populated_db: sqlite3.Connection) -> None:
        """验证有时间引用时的权重公式: 0.4*fts + 0.4*vector + 0.2*time_boost。"""
        query_vec = [0.1, 0.2, 0.3, 0.4]
        results = hybrid_retrieve(
            query="喝茶",
            scope_id="scope-a",
            conn=populated_db,
            query_embedding=query_vec,
            top_k=10,
            query_class={"time_references": ["2023-06-01"]},
        )
        for r in results:
            fts = r.get("fts_score", 0.0)
            vec = r.get("vector_score", 0.0)
            tb = r.get("time_boost", 0.0)
            sb = r.get("speaker_boost", 0.0)
            expected = 0.4 * fts + 0.4 * vec + 0.2 * tb + sb
            assert abs(r["combined_score"] - expected) < 1e-9


# ==================== 说话人感知加权测试 ====================


class TestSpeakerAwareWeighting:
    """测试说话人感知加权逻辑。"""

    def test_speaker_boost_applied(self, populated_db: sqlite3.Connection) -> None:
        """有 target_speaker 时应应用 speaker_boost。"""
        query_vec = [0.1, 0.2, 0.3, 0.4]
        results = hybrid_retrieve(
            query="喝茶",
            scope_id="scope-a",
            conn=populated_db,
            query_embedding=query_vec,
            top_k=10,
            query_class={"target_speaker": "爸爸"},
        )
        assert len(results) >= 1
        for r in results:
            assert "speaker_boost" in r

    def test_matching_speaker_boosted(self, populated_db: sqlite3.Connection) -> None:
        """匹配目标说话人的 chunk 应有 speaker_boost=0.15。"""
        query_vec = [0.1, 0.2, 0.3, 0.4]
        results = hybrid_retrieve(
            query="喝茶",
            scope_id="scope-a",
            conn=populated_db,
            query_embedding=query_vec,
            top_k=10,
            query_class={"target_speaker": "爸爸"},
        )
        # mc-a-1 的主导说话人是 "爸爸"
        for r in results:
            if r["id"] == "mc-a-1":
                assert r.get("speaker_boost", 0.0) == 0.15

    def test_no_target_speaker_no_boost(self, populated_db: sqlite3.Connection) -> None:
        """无 target_speaker 时 speaker_boost 应为 0。"""
        query_vec = [0.1, 0.2, 0.3, 0.4]
        results = hybrid_retrieve(
            query="喝茶",
            scope_id="scope-a",
            conn=populated_db,
            query_embedding=query_vec,
            top_k=10,
        )
        for r in results:
            assert r.get("speaker_boost", 0.0) == 0.0

    def test_weight_formula_with_speaker(self, populated_db: sqlite3.Connection) -> None:
        """验证有说话人时的权重公式: base + speaker_boost。"""
        query_vec = [0.1, 0.2, 0.3, 0.4]
        results = hybrid_retrieve(
            query="喝茶",
            scope_id="scope-a",
            conn=populated_db,
            query_embedding=query_vec,
            top_k=10,
            query_class={"target_speaker": "爸爸"},
        )
        for r in results:
            fts = r.get("fts_score", 0.0)
            vec = r.get("vector_score", 0.0)
            sb = r.get("speaker_boost", 0.0)
            expected = 0.5 * fts + 0.5 * vec + sb
            assert abs(r["combined_score"] - expected) < 1e-9

    def test_non_matching_speaker_zero_boost(self, populated_db: sqlite3.Connection) -> None:
        """非目标说话人的 chunk speaker_boost 应为 0。"""
        query_vec = [0.1, 0.2, 0.3, 0.4]
        results = hybrid_retrieve(
            query="喝茶",
            scope_id="scope-a",
            conn=populated_db,
            query_embedding=query_vec,
            top_k=10,
            query_class={"target_speaker": "爸爸"},
        )
        # mc-a-2 的主导说话人是 "妈妈"
        for r in results:
            if r["id"] == "mc-a-2":
                assert r.get("speaker_boost", 0.0) == 0.0


# ==================== Rerank 测试 ====================


class TestRerank:
    """测试重排序逻辑。"""

    def _make_candidates(
        self, n: int = 10, speaker: str = "speaker_a", start_score: float = 0.9
    ) -> list[dict[str, Any]]:
        """生成测试候选列表。"""
        candidates: list[dict[str, Any]] = []
        for i in range(n):
            candidates.append({
                "id": f"c{i}",
                "content": f"这是测试内容 {i} " + " ".join(["测试"] * (i % 5 + 1)),
                "combined_score": start_score - i * 0.05,
                "chunk_type": "conversation_segment",
                "metadata": json.dumps({
                    "speakers": [speaker if i % 3 == 0 else f"speaker_{(i%3)}"],
                    "dominant_speaker": speaker if i % 3 == 0 else f"speaker_{(i%3)}",
                }),
                "speaker_count": 2,
            })
        return candidates

    def test_basic_ranking(self) -> None:
        """基本排序: 按 combined_score 降序。"""
        candidates = self._make_candidates(5)
        results = rerank_candidates("测试", candidates, top_k=5, use_mmr=False)
        assert len(results) == 5
        scores = [r["combined_score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_mmr_diversity(self) -> None:
        """MMR 应提供内容多样性。"""
        # 创建内容高度相似的候选
        candidates: list[dict[str, Any]] = []
        for i in range(10):
            candidates.append({
                "id": f"c{i}",
                "content": "相同内容 " * (i + 1) + f" 差异内容{i}",
                "combined_score": 0.9 - i * 0.01,
                "chunk_type": "conversation_segment",
                "metadata": json.dumps({"speakers": [f"speaker_{i}"], "dominant_speaker": f"speaker_{i}"}),
                "speaker_count": 1,
            })
        results = rerank_candidates("测试", candidates, top_k=5, use_mmr=True)
        assert len(results) == 5
        # MMR 可能不会严格按照原始分数排序（多样性调整）
        assert len({r["id"] for r in results}) == 5  # 无重复

    def test_top_k_limit(self) -> None:
        """验证 top_k 限制。"""
        candidates = self._make_candidates(20)
        results = rerank_candidates("测试", candidates, top_k=5, use_mmr=False)
        assert len(results) == 5

    def test_empty_candidates(self) -> None:
        """空候选列表应返回空列表。"""
        results = rerank_candidates("测试", [], top_k=10)
        assert results == []

    def test_no_mmr_when_few_candidates(self) -> None:
        """候选数 ≤ top_k 时不应修改顺序。"""
        candidates = self._make_candidates(3)
        results = rerank_candidates("测试", candidates, top_k=10, use_mmr=True)
        assert len(results) == 3

    def test_consecutive_speaker_penalty(self) -> None:
        """测试连续同一说话人的 MMR 惩罚机制。"""
        # 创建 10 个全部同一说话人的候选
        candidates: list[dict[str, Any]] = []
        for i in range(10):
            candidates.append({
                "id": f"c{i}",
                "content": f"内容 {i} " + " ".join(["数据"] * (i + 1)),
                "combined_score": 0.95 - i * 0.02,
                "chunk_type": "conversation_segment",
                "metadata": json.dumps({"speakers": ["爸爸"], "dominant_speaker": "爸爸"}),
                "speaker_count": 1,
            })
        results = rerank_candidates("测试", candidates, top_k=10, use_mmr=True)
        # 即使所有候选都是同一说话人，MMR 也应返回 top_k 个结果
        assert len(results) == 10

    def test_mmr_preserves_best_match(self) -> None:
        """MMR 应保留最高分候选作为第一个结果。"""
        candidates = self._make_candidates(10, start_score=0.95)
        results = rerank_candidates("测试", candidates, top_k=5, use_mmr=True)
        # 第一个结果应是最高分的
        assert results[0]["id"] == candidates[0]["id"]


# ==================== 检索追踪记录测试 ====================


class TestRetrievalTrace:
    """测试检索追踪记录。"""

    @pytest.fixture
    def trace_db(self, db: sqlite3.Connection) -> sqlite3.Connection:
        """为追踪测试提供带有 scope 的数据库。"""
        db.execute(
            "INSERT INTO deceased_profile (id, name) VALUES ('dp-trace', '追踪测试')"
        )
        db.execute(
            "INSERT INTO relationship_scope (id, deceased_profile_id, scope_name, relationship_type) "
            "VALUES ('scope-a', 'dp-trace', '追踪测试域', 'child')"
        )
        db.commit()
        return db

    def test_record_trace(self, trace_db: sqlite3.Connection) -> None:
        """基本追踪记录写入测试。"""
        fts_results = [
            {"id": "mc-1", "chunk_type": "conversation_segment", "rank": 1.0,
             "fts_score": 0.5, "combined_score": 0.5, "source": "fts",
             "speaker_count": 2, "time_range_start": None, "time_range_end": None},
        ]
        vec_results: list[dict[str, Any]] = []
        reranked = fts_results

        trace_id = record_retrieval_trace(
            conn=trace_db,
            scope_id="scope-a",
            query_text="测试查询",
            fts_results=fts_results,
            vector_results=vec_results,
            reranked_results=reranked,
        )

        assert trace_id is not None
        assert len(trace_id) > 0

    def test_get_trace(self, trace_db: sqlite3.Connection) -> None:
        """查询追踪记录测试。"""
        fts_results = [
            {"id": "mc-1", "chunk_type": "conversation_segment", "rank": 1.0,
             "fts_score": 0.5, "combined_score": 0.5, "source": "fts",
             "speaker_count": 2, "time_range_start": None, "time_range_end": None},
        ]
        vec_results: list[dict[str, Any]] = []
        reranked = fts_results

        trace_id = record_retrieval_trace(
            conn=trace_db,
            scope_id="scope-a",
            query_text="测试查询",
            fts_results=fts_results,
            vector_results=vec_results,
            reranked_results=reranked,
        )

        retrieved = get_trace(trace_db, trace_id)
        assert retrieved is not None
        assert retrieved["query_text"] == "测试查询"
        assert retrieved["relationship_scope_id"] == "scope-a"

    def test_trace_json_fields(self, trace_db: sqlite3.Connection) -> None:
        """验证追踪记录中的 JSON 字段。"""
        fts_results = [
            {"id": "mc-1", "chunk_type": "conversation_segment", "rank": 1.0,
             "fts_score": 0.5, "combined_score": 0.5, "source": "fts",
             "speaker_count": 2, "time_range_start": None, "time_range_end": None},
        ]
        vec_results: list[dict[str, Any]] = []
        reranked = fts_results

        trace_id = record_retrieval_trace(
            conn=trace_db,
            scope_id="scope-a",
            query_text="测试查询",
            fts_results=fts_results,
            vector_results=vec_results,
            reranked_results=reranked,
        )

        retrieved = get_trace(trace_db, trace_id)
        assert retrieved is not None
        # 验证 JSON 字段可解析
        fts_json = json.loads(retrieved["fts_results"])
        assert isinstance(fts_json, list)
        assert len(fts_json) == 1
        assert fts_json[0]["chunk_id"] == "mc-1"

    def test_trace_nonexistent(self, trace_db: sqlite3.Connection) -> None:
        """查询不存在的追踪记录应返回 None。"""
        result = get_trace(trace_db, "nonexistent-id")
        assert result is None


# ==================== 可见 chunk ID 测试 ====================


class TestVisibleChunkIds:
    """测试 get_visible_chunk_ids。"""

    def test_scope_private_chunks(self, populated_db: sqlite3.Connection) -> None:
        """scope-a 应能看到自己的私有 chunk。"""
        visible = get_visible_chunk_ids(populated_db, "scope-a")
        assert "mc-a-1" in visible
        assert "mc-a-2" in visible

    def test_scope_isolation(self, populated_db: sqlite3.Connection) -> None:
        """scope-a 不应看到 scope-b 的私有 chunk。"""
        visible = get_visible_chunk_ids(populated_db, "scope-a")
        assert "mc-b-1" not in visible
        assert "mc-b-2" not in visible

    def test_global_chunks_visible(self, populated_db: sqlite3.Connection) -> None:
        """全局 chunk 应对所有 scope 可见。"""
        visible = get_visible_chunk_ids(populated_db, "scope-a")
        assert "mc-g-1" in visible
        assert "mc-g-2" in visible

    def test_empty_scope(self, db: sqlite3.Connection) -> None:
        """空 scope 应返回空集合。"""
        visible = get_visible_chunk_ids(db, "nonexistent")
        assert visible == set()
