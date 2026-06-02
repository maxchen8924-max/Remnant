"""重排序模块 — 实现白皮书 RAG Pipeline Step 8。

核心函数 rerank_candidates:
- 按 combined_score 降序排序
- 可选 MMR (Maximal Marginal Relevance) 多样性重排
- λ=0.7（相关性 70% + 多样性 30%）
- MMR 确保不出现连续 5+ 条同一说话人的结果
"""

from __future__ import annotations

import json
from typing import Any


def _extract_content_tokens(content: str) -> set[str]:
    """从 content 文本中提取简单的 token 集合。

    用于 MMR 多样性计算中的内容相似度比较。
    使用字符级 bigram 作为 token，对中文和英文都有效。

    Args:
        content: 文本内容

    Returns:
        bigram token 集合
    """
    if not content:
        return set()

    # 使用字符级 bigram
    tokens: set[str] = set()
    chars = list(content)
    for i in range(len(chars) - 1):
        tokens.add(chars[i] + chars[i + 1])
    return tokens


def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """计算两个集合的 Jaccard 相似度。

    Jaccard(A, B) = |A ∩ B| / |A ∪ B|

    Args:
        set_a: 集合 A
        set_b: 集合 B

    Returns:
        Jaccard 相似度，范围 [0, 1]
    """
    if not set_a and not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    if union == 0:
        return 0.0
    return intersection / union


def _extract_dominant_speaker(metadata: str | dict[str, Any] | None) -> str:
    """从 chunk metadata 中提取主导说话人。

    Args:
        metadata: chunk 的 metadata

    Returns:
        主导说话人名称，无法提取时返回空字符串
    """
    if metadata is None:
        return ""

    if isinstance(metadata, str):
        try:
            meta = json.loads(metadata) if metadata else {}
        except (json.JSONDecodeError, TypeError):
            meta = {}
    elif isinstance(metadata, dict):
        meta = metadata
    else:
        meta = {}

    # 尝试多个可能的字段名
    for key in ("dominant_speaker", "speaker", "main_speaker"):
        val = meta.get(key, "")
        if val:
            return str(val)

    # 检查 speakers 列表
    speakers = meta.get("speakers", [])
    if isinstance(speakers, list) and len(speakers) > 0:
        return str(speakers[0])

    return ""


def _mmr_rerank(
    candidates: list[dict[str, Any]],
    top_k: int = 10,
    lambda_param: float = 0.7,
    max_consecutive_same_speaker: int = 5,
) -> list[dict[str, Any]]:
    """MMR (Maximal Marginal Relevance) 多样性重排序。

    贪婪选择算法:
    1. 从最高 combined_score 的候选开始
    2. 每次选择 MMR 分数最高的候选:
       MMR = λ * relevance_score - (1-λ) * max_similarity_to_selected
    3. 如果连续出现 max_consecutive_same_speaker 条同一说话人的结果，
       则强制跳过该说话人，选择下一个不同说话人的候选

    Args:
        candidates: 候选 chunk 列表（已按 combined_score 排序）
        top_k: 返回数量上限
        lambda_param: 相关性权重（0~1），默认 0.7
        max_consecutive_same_speaker: 最大连续同一说话人数量，默认 5

    Returns:
        重排序后的 top_k 候选列表
    """
    if not candidates:
        return []

    n = len(candidates)

    # 预计算每个候选的 content tokens
    content_tokens: list[set[str]] = []
    for item in candidates:
        content = item.get("content", "")
        content_tokens.append(_extract_content_tokens(content))

    # 预计算每个候选的主导说话人
    speakers: list[str] = []
    for item in candidates:
        metadata = item.get("metadata", "{}")
        speakers.append(_extract_dominant_speaker(metadata))

    # 预计算两两之间的 Jaccard 相似度（上三角矩阵）
    similarity_cache: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            sim = _jaccard_similarity(content_tokens[i], content_tokens[j])
            similarity_cache[(i, j)] = sim
            similarity_cache[(j, i)] = sim

    def _get_sim(i: int, j: int) -> float:
        return similarity_cache.get((i, j), 0.0)

    # MMR 贪婪选择
    selected_indices: list[int] = []
    remaining = set(range(n))

    # 第一步: 选择 combined_score 最高的候选
    first_idx = 0  # candidates 已按 combined_score 降序排列
    selected_indices.append(first_idx)
    remaining.remove(first_idx)

    # 迭代选择
    while len(selected_indices) < top_k and remaining:
        best_idx = -1
        best_mmr = -float("inf")

        for idx in remaining:
            relevance = candidates[idx].get("combined_score", 0.0)

            # 计算与已选中的最大相似度
            max_sim = 0.0
            for sel_idx in selected_indices:
                sim = _get_sim(idx, sel_idx)
                if sim > max_sim:
                    max_sim = sim

            mmr_score = lambda_param * relevance - (1.0 - lambda_param) * max_sim

            # 说话人多样性惩罚:
            # 如果该候选的说话人已经在最近 N 条结果中出现过，
            # 施加额外惩罚
            current_speaker = speakers[idx]
            if current_speaker:
                consecutive_count = 0
                # 从最近选中的开始往前数
                for sel_idx in reversed(selected_indices):
                    if speakers[sel_idx] == current_speaker:
                        consecutive_count += 1
                    else:
                        break
                if consecutive_count >= max_consecutive_same_speaker:
                    mmr_score -= 10.0  # 强惩罚，基本排除

            if mmr_score > best_mmr:
                best_mmr = mmr_score
                best_idx = idx

        if best_idx == -1:
            break

        selected_indices.append(best_idx)
        remaining.remove(best_idx)

    return [candidates[i] for i in selected_indices]


def rerank_candidates(
    query: str,
    candidates: list[dict[str, Any]],
    query_class: dict[str, Any] | None = None,
    top_k: int = 10,
    use_mmr: bool = True,
) -> list[dict[str, Any]]:
    """对候选 chunk 进行重排序。

    实现白皮书 RAG Pipeline Step 8:
    1. 按 combined_score 降序排序
    2. 可选 MMR 多样性重排（λ=0.7）
    3. 确保不出现连续 5+ 条同一说话人的结果
    4. 返回 top_k 结果

    Args:
        query: 用户查询文本（保留参数，供后续扩展使用）
        candidates: 候选 chunk 列表
        query_class: 查询分类（可选）
        top_k: 返回数量上限
        use_mmr: 是否启用 MMR 多样性，默认 True

    Returns:
        重排序后的 top_k 候选列表
    """
    if not candidates:
        return []

    # 1. 按 combined_score 降序排序
    sorted_candidates = sorted(
        candidates,
        key=lambda x: x.get("combined_score", 0.0),
        reverse=True,
    )

    if not use_mmr or len(sorted_candidates) <= top_k:
        return sorted_candidates[:top_k]

    # 2. MMR 多样性重排
    reranked = _mmr_rerank(
        sorted_candidates,
        top_k=top_k,
        lambda_param=0.7,
        max_consecutive_same_speaker=5,
    )

    return reranked
