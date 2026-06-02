"""SafetyMiddleware 骨架 — 安全中间件。

实现 Ch10 定义的安全机制:
- 反依赖保护（Anti-Dependency）
- 深夜使用限制
- 过度使用检测
- 情绪困扰检测
- 硬熔断机制
"""

from __future__ import annotations

import abc
from typing import Any

from remnant_core.models import SafetyDirective, SafetyEventType, SafetySeverity


class SafetyMiddleware:
    """安全中间件 — 在响应返回给用户前进行安全评估。

    使用示例::

        safety = SafetyMiddleware(safety_policy=policy)
        directive = await safety.evaluate(query, response_text, session_stats)
        if directive.action == "COOL_DOWN_ENFORCED":
            # 触发冷却期
            ...
    """

    def __init__(self, safety_policy: dict[str, Any] | None = None) -> None:
        self.safety_policy = safety_policy or {}

    async def evaluate(
        self,
        query: str,
        response_text: str,
        session_stats: dict[str, Any] | None = None,
    ) -> SafetyDirective | None:
        """评估当前交互的安全性。

        Args:
            query: 用户查询
            response_text: AI 响应文本
            session_stats: 会话统计（时长、消息数等）

        Returns:
            SafetyDirective 如果检测到安全风险，否则 None
        """
        stats = session_stats or {}

        # 检查会话时长
        max_minutes = self.safety_policy.get("max_session_minutes", 60)
        session_minutes = stats.get("session_minutes", 0)
        if session_minutes > max_minutes:
            return SafetyDirective(
                event_type=SafetyEventType.EXCESSIVE_USAGE,
                severity=SafetySeverity.WARNING,
                action="SESSION_PAUSED",
                message="本次会话已超过时间限制，建议休息一下。",
                cooldown_minutes=self.safety_policy.get("cooldown_minutes", 30),
            )

        return None

    async def check_late_night(
        self,
        current_hour: int,
        session_count_today: int = 0,
    ) -> SafetyDirective | None:
        """检查深夜使用限制。

        Args:
            current_hour: 当前小时（0~23）
            session_count_today: 今日深夜会话数

        Returns:
            SafetyDirective 如果超过深夜限额，否则 None
        """
        late_night_start = self.safety_policy.get("late_night_start", "22:00")
        late_night_end = self.safety_policy.get("late_night_end", "06:00")
        max_late_night = self.safety_policy.get("max_late_night_sessions", 2)

        start_hour = int(late_night_start.split(":")[0])
        end_hour = int(late_night_end.split(":")[0])

        is_late_night = current_hour >= start_hour or current_hour < end_hour
        if is_late_night and session_count_today >= max_late_night:
            return SafetyDirective(
                event_type=SafetyEventType.LATE_NIGHT_USAGE,
                severity=SafetySeverity.WARNING,
                action="COOL_DOWN_ENFORCED",
                message="深夜使用已达上限，请休息。",
                cooldown_minutes=self.safety_policy.get("cooldown_minutes", 30),
            )

        return None