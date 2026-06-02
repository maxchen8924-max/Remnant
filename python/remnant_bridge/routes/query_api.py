"""POST /api/v1/query (SSE) — 查询 API。"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from remnant_core.models import QueryRequest, QueryResponse

router = APIRouter(prefix="/api/v1", tags=["query"])


@router.post("/query")
async def query_memory(request: QueryRequest) -> StreamingResponse:
    """查询记忆 — 基于 RAG 管道检索并生成响应。

    支持 SSE（Server-Sent Events）流式返回。
    """
    if request.stream:
        return StreamingResponse(
            _stream_response(request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        # 非流式响应
        result = QueryResponse(
            session_id="pending",
            message_id="pending",
            content="M1 阶段实现 RAG 管道",
        )
        return result


async def _stream_response(request: QueryRequest) -> AsyncGenerator[str, None]:
    """SSE 流式响应生成器。

    Args:
        request: 查询请求

    Yields:
        SSE 格式的事件数据
    """
    # M1 阶段实现 RAG 管道调用
    # 当前仅返回占位数据
    data = {
        "session_id": "pending",
        "message_id": "pending",
        "content": "M1 阶段实现",
        "done": True,
    }
    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"