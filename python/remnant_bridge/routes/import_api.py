"""POST /api/v1/import — 数据导入 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from remnant_bridge.config import DEFAULT_DB_PATH
from remnant_bridge.runtime import run_import_pipeline
from remnant_core.models import ImportRequest, ImportResponse

router = APIRouter(prefix="/api/v1", tags=["import"])


@router.post("/import", response_model=ImportResponse)
async def import_data(request: ImportRequest) -> ImportResponse:
    """导入数据文件到 Remnant 系统。

    接受文件路径和类型，触发 ETL 管道处理。
    """
    try:
        result = run_import_pipeline(DEFAULT_DB_PATH, request)
        return ImportResponse(**result)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
