"""POST /api/v1/query (SSE) — 查询 API。"""

from __future__ import annotations

import json
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from remnant_bridge.config import DEFAULT_DB_PATH
from remnant_bridge.runtime import open_bridge_connection, run_query_retrieval
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
        payload = _query_payload(request)
        return QueryResponse(**payload)


async def _stream_response(request: QueryRequest) -> AsyncGenerator[str, None]:
    """SSE 流式响应生成器。

    Args:
        request: 查询请求

    Yields:
        SSE 格式的事件数据
    """
    data = _query_payload(request)
    data["done"] = True
    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _query_payload(request: QueryRequest) -> dict:
    conn = open_bridge_connection(DEFAULT_DB_PATH)
    try:
        return run_query_retrieval(
            conn=conn,
            scope_id=request.scope_id,
            query=request.query,
            top_k=request.top_k,
        )
    finally:
        conn.close()
