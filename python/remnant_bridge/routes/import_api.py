"""POST /api/v1/import — 数据导入 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from remnant_core.models import ImportRequest, ImportResponse

router = APIRouter(prefix="/api/v1", tags=["import"])


@router.post("/import", response_model=ImportResponse)
async def import_data(request: ImportRequest) -> ImportResponse:
    """导入数据文件到 Remnant 系统。

    接受文件路径和类型，触发 ETL 管道处理。
    """
    # M1 阶段实现 ETL 管道调用
    return ImportResponse(
        artifact_id="",
        file_hash="",
        message_count=0,
        chunk_count=0,
        parse_status="PENDING",
    )