"""混合检索合并模块 — 实现白皮书 RAG Pipeline Steps 5-7。

核心函数 hybrid_retrieve:
  Step 5: 并行执行 FTS5 + 向量搜索（各取 top_k*2），合并去重
  Step 6: Time-aware 加权 — 时间匹配度 time_boost
  Step 7: Speaker-aware 加权 — 说话人匹配加分

权重规则:
  - 无时间引用: 0.5*fts + 0.5*vector
  - 有时间引用: 0.4*fts + 0.4*vector + 0.2*time_boost
  - 有说话人: +0.15 speaker_boost
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any


def _normalize_fts_score(rank: float | None) -> float:
    """将 FTS5 BM25 rank 分数标准化到 [0, 1] 范围。

    FTS5 BM25 rank 可以为负值（更负 = 更相关）。
    使用 sigmoid 函数映射: score = 1.0 / (1.0 + e^rank)
    - rank → -∞ 时 score → 1.0 (最佳匹配)
    - rank = 0 时 score = 0.5
    - rank → +∞ 时 score → 0.0

    Args:
        rank: FTS5 BM25 rank 值

    Returns:
        标准化后的分数，范围 [0, 1]
    """
    if rank is None:
        return 0.0
    import math
    return 1.0 / (1.0 + math.exp(float(rank)))


def _parse_time_reference(
    time_ref: str | None,
) -> datetime | None:
    """解析时间引用字符串为 datetime 对象。

    支持 ISO 8601 格式（如 '2023-06-15' 或 '2023-06-15T10:30:00'）。

    Args:
        time_ref: 时间引用字符串

    Returns:
        解析后的 datetime 对象，解析失败返回 None
    """
    if time_ref is None:
        return None

    try:
        # 尝试多种 ISO 8601 格式
        dt_str = time_ref.replace("Z", "+00:00")
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        pass

    # 尝试常见日期格式
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(time_ref, fmt)
        except ValueError:
            continue

    return None


def _compute_time_boost(
    chunk_time_start: str | None,
    chunk_time_end: str | None,
    time_references: list[str] | None,
) -> float:
    """计算时间匹配度加权系数。

    对于每个时间引用，检查是否落在 chunk 的时间范围内。
    匹配的时间引用越多，boost 越高。

    公式: time_boost = min(1.0, matched_count * 0.5)

    Args:
        chunk_time_start: chunk 时间范围起始
        chunk_time_end: chunk 时间范围结束
        time_references: 查询中的时间引用列表

    Returns:
        时间 boost 值，范围 [0, 1]
    """
    if not time_references or len(time_references) == 0:
        return 0.0

    parsed_refs: list[datetime] = []
    for ref in time_references:
        dt = _parse_time_reference(ref)
        if dt is not None:
            parsed_refs.append(dt)

    if not parsed_refs:
        return 0.0

    chunk_start = _parse_time_reference(chunk_time_start)
    chunk_end = _parse_time_reference(chunk_time_end)

    matched = 0
    for ref_dt in parsed_refs:
        # 判断是否为仅日期引用（无时间部分）
        is_date_only = (
            ref_dt.hour == 0
            and ref_dt.minute == 0
            and ref_dt.second == 0
            and ref_dt.microsecond == 0
        )

        if chunk_start is not None and chunk_end is not None:
            # 检查时间引用是否在 chunk 的时间范围内
            if is_date_only:
                # 仅日期引用: 比较日期范围
                if chunk_start.date() <= ref_dt.date() <= chunk_end.date():
                    matched += 1
            elif chunk_start <= ref_dt <= chunk_end:
                matched += 1
        elif chunk_start is not None:
            # 仅有起始时间: 宽松匹配（前后 30 天）
            delta = abs((ref_dt - chunk_start).days)
            if delta <= 30:
                matched += 1
        elif chunk_end is not None:
            # 仅有结束时间: 宽松匹配（前后 30 天）
            delta = abs((ref_dt - chunk_end).days)
            if delta <= 30:
                matched += 1
        else:
            # chunk 无时间信息: 微弱 boost
            matched += 0.2

    return min(1.0, matched * 0.5)


def _compute_speaker_boost(
    chunk_metadata: str | dict[str, Any] | None,
    target_speaker: str | None,
) -> float:
    """计算说话人匹配加权系数。

    检查 chunk 的 metadata 中是否包含目标说话人。
    匹配说话人返回 boost 值，否则返回 0。

    Args:
        chunk_metadata: chunk 的 metadata（JSON 字符串或字典）
        target_speaker: 查询中指定的目标说话人

    Returns:
        说话人 boost 值: 匹配返回 0.15，否则返回 0.0
    """
    if target_speaker is None:
        return 0.0

    # 解析 metadata
    if isinstance(chunk_metadata, str):
        try:
            meta = json.loads(chunk_metadata) if chunk_metadata else {}
        except (json.JSONDecodeError, TypeError):
            meta = {}
    elif isinstance(chunk_metadata, dict):
        meta = chunk_metadata
    else:
        meta = {}

    # 检查 speakers 列表
    speakers: list[str] = meta.get("speakers", [])
    if isinstance(speakers, list):
        for speaker in speakers:
            if isinstance(speaker, str) and target_speaker.lower() in speaker.lower():
                return 0.15

    # 检查 dominant_speaker
    dominant = meta.get("dominant_speaker", "")
    if isinstance(dominant, str) and target_speaker.lower() in dominant.lower():
        return 0.15

    return 0.0


def _filter_chunks(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """过滤候选 chunk。

    过滤条件:
    - provenance_level != 'user_provided_context'（即 chunk_type 检查）
    - confidence >= 0.3（combined_score 作为代理）

    Args:
        candidates: 候选 chunk 列表

    Returns:
        过滤后的候选列表
    """
    filtered: list[dict[str, Any]] = []
    for item in candidates:
        chunk_type = item.get("chunk_type", "")
        if chunk_type == "user_provided_context":
            continue

        combined = item.get("combined_score", 0.0)
        if combined < 0.3:
            continue

        filtered.append(item)

    return filtered


def hybrid_retrieve(
    query: str,
    scope_id: str,
    conn: sqlite3.Connection | None = None,
    query_embedding: list[float] | None = None,
    top_k: int = 20,
    query_class: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """混合检索 — FTS5 + Vector 合并去重 + 时间/说话人加权。

    实现白皮书 RAG Pipeline Steps 5-7:

    Step 5: 并行执行 FTS5 和向量搜索（各取 top_k*2），
            以 chunk_id 为 key 合并去重。
    Step 6: Time-aware 加权 — 如果 query_class 中有 time_references，
            计算时间匹配度 time_boost。
    Step 7: Speaker-aware 加权 — 如果 query_class 中有 target_speaker，
            匹配说话人加 speaker_boost。

    权重计算:
      - 无时间引用: combined_score = 0.5*fts_norm + 0.5*vector_norm
      - 有时间引用: combined_score = 0.4*fts_norm + 0.4*vector_norm + 0.2*time_boost
      - 有说话人时追加: combined_score += speaker_boost

    过滤条件:
      - chunk_type != 'user_provided_context'
      - combined_score >= 0.3

    Args:
        query: 用户查询文本
        scope_id: 关系作用域 ID
        conn: 数据库连接（context manager 外部管理）
        query_embedding: 查询的 embedding 向量（可选，None 时跳过向量搜索）
        top_k: 最终返回数量上限
        query_class: 查询分类结果，可包含:
            - time_references: list[str] 时间引用列表
            - target_speaker: str 目标说话人

    Returns:
        合并加权后的候选 chunk 列表，按 combined_score 降序排列
    """
    if conn is None:
        return []

    from remnant_store.fts import fts5_search
    from remnant_store.vector import vector_search

    # 解析 query_class
    qc = query_class or {}
    time_references: list[str] | None = qc.get("time_references")
    target_speaker: str | None = qc.get("target_speaker")
    has_time_refs = time_references is not None and len(time_references) > 0

    # Step 5: 并行执行 FTS5 和向量搜索（各取 top_k*2）
    fetch_k = top_k * 2
    fts_results = fts5_search(conn, query, scope_id, top_k=fetch_k)
    vec_results = vector_search(conn, query_embedding, scope_id, top_k=fetch_k)

    # 合并去重: 以 chunk_id 为 key
    merged: dict[str, dict[str, Any]] = {}

    # 处理 FTS5 结果
    for item in fts_results:
        chunk_id = item["id"]
        fts_rank = item.get("rank", 10.0)
        fts_score = _normalize_fts_score(fts_rank)
        source = "fts"

        if chunk_id in merged:
            merged[chunk_id]["fts_score"] = fts_score
            merged[chunk_id]["fts_rank"] = fts_rank
            existing_source = merged[chunk_id].get("source", "fts")
            merged[chunk_id]["source"] = "hybrid" if existing_source != source else source
        else:
            item["fts_score"] = fts_score
            item["fts_rank"] = fts_rank
            item["vector_score"] = 0.0
            item["source"] = source
            item["combined_score"] = 0.0
            merged[chunk_id] = item

    # 处理向量搜索结果
    for item in vec_results:
        chunk_id = item["id"]
        vector_score = item.get("vector_score", 0.0)
        source = "vector"

        if chunk_id in merged:
            merged[chunk_id]["vector_score"] = vector_score
            existing_source = merged[chunk_id].get("source", "vector")
            merged[chunk_id]["source"] = "hybrid" if existing_source != source else source
        else:
            item["fts_score"] = 0.0
            item["fts_rank"] = None
            item["vector_score"] = vector_score
            item["source"] = source
            item["combined_score"] = 0.0
            merged[chunk_id] = item

    # Step 6 & 7: 计算 weighted combined_score
    for chunk_id, item in merged.items():
        fts_score = item.get("fts_score", 0.0)
        vector_score = item.get("vector_score", 0.0)

        # 时间感知权重
        if has_time_refs:
            time_boost = _compute_time_boost(
                item.get("time_range_start"),
                item.get("time_range_end"),
                time_references,
            )
            combined = 0.4 * fts_score + 0.4 * vector_score + 0.2 * time_boost
        else:
            combined = 0.5 * fts_score + 0.5 * vector_score

        # 说话人感知权重
        chunk_metadata = item.get("metadata", "{}")
        speaker_boost = _compute_speaker_boost(chunk_metadata, target_speaker)
        combined += speaker_boost

        item["combined_score"] = combined
        item["time_boost"] = time_boost if has_time_refs else 0.0
        item["speaker_boost"] = speaker_boost

    # 转换为列表并过滤
    candidates = list(merged.values())
    candidates = _filter_chunks(candidates)

    # 按 combined_score 降序排序
    candidates.sort(key=lambda x: x.get("combined_score", 0.0), reverse=True)

    return candidates[:top_k]


def get_hybrid_results_for_trace(
    query: str,
    scope_id: str,
    conn: sqlite3.Connection,
    query_embedding: list[float] | None = None,
    top_k: int = 20,
    query_class: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """获取 FTS5 和向量搜索的原始结果（用于追踪记录）。

    返回 (fts_raw_results, vector_raw_results) 以便记录到 retrieval_trace。

    Args:
        query: 查询文本
        scope_id: 作用域 ID
        conn: 数据库连接
        query_embedding: 查询向量
        top_k: 每路搜索数量
        query_class: 查询分类

    Returns:
        (fts_results, vector_results) 元组
    """
    from remnant_store.fts import fts5_search
    from remnant_store.vector import vector_search

    fts_raw = fts5_search(conn, query, scope_id, top_k=top_k * 2)
    vec_raw = vector_search(conn, query_embedding, scope_id, top_k=top_k * 2)

    return fts_raw, vec_raw
