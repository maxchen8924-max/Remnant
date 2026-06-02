"""Prompt 构建骨架。

负责为不同场景构建 LLM Prompt:
1. 问答 Prompt — 基于 RAG 检索结果 + scope 级 Prompt 策略
2. Claim 提取 Prompt
3. 安全评估 Prompt
4. 声音合成文本 Prompt（v0.1 预留）
"""

from __future__ import annotations

from typing import Any

from remnant_core.models import ClaimSchema, MemoryChunkSchema


class PromptBuilder:
    """Prompt 构建器 — 根据场景组装 LLM 输入。"""

    # 系统提示词模板
    SYSTEM_TEMPLATE = (
        "你是 Remnant 纪念系统，一个帮助用户回忆逝去亲人的数字记忆助手。\n"
        "你必须严格基于提供的记忆证据回答问题，不能编造或推测。\n"
        "如果证据不足，明确告知用户，不要猜测。\n\n"
        "当前关系作用域: {scope_name}（{relationship_type}）\n"
    )

    def build_qa_prompt(
        self,
        query: str,
        chunks: list[MemoryChunkSchema],
        scope_name: str = "",
        relationship_type: str = "",
        prompt_policy: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        """构建问答 Prompt。

        Args:
            query: 用户查询
            chunks: RAG 检索到的记忆分块
            scope_name: 作用域名称
            relationship_type: 关系类型
            prompt_policy: 作用域级 Prompt 策略

        Returns:
            消息列表 [{role, content}] 供 LLM 调用
        """
        system_content = self.SYSTEM_TEMPLATE.format(
            scope_name=scope_name or "未知",
            relationship_type=relationship_type or "未知",
        )

        if prompt_policy:
            extra = prompt_policy.get("system_extra", "")
            if extra:
                system_content += f"\n额外指令:\n{extra}\n"

        evidence_text = "\n\n".join(
            f"[记忆片段 {i+1}] (时间: {c.time_range_start or '未知'} - {c.time_range_end or '未知'})\n{c.content}"
            for i, c in enumerate(chunks)
        )

        user_content = f"基于以下记忆证据回答问题:\n\n{evidence_text}\n\n问题: {query}"

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

    def build_claim_extraction_prompt(
        self, response_text: str
    ) -> list[dict[str, str]]:
        """构建 Claim 提取 Prompt。"""
        system_content = (
            "请从以下 AI 响应中提取所有事实声明（claims）。\n"
            "每个声明应该是一个可以被独立验证的事实陈述。\n"
            "以 JSON 数组格式返回，每个元素包含 claim_text 和 confidence。"
        )
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": response_text},
        ]

    def build_safety_evaluation_prompt(
        self, query: str, response_text: str
    ) -> list[dict[str, str]]:
        """构建安全评估 Prompt。"""
        system_content = (
            "你是一个安全评估系统。请评估以下对话是否存在:\n"
            "1. 情绪依赖风险（过度依赖 AI 模拟的逝者）\n"
            "2. 反依赖触发（试图通过对话否认死亡事实）\n"
            "3. 其他安全风险\n\n"
            "以 JSON 格式返回评估结果。"
        )
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"用户问题: {query}\nAI 回复: {response_text}"},
        ]