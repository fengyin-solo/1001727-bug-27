"""调度台账接口：只提供列表与明细查询，记录由整改闭环自动生成。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import DispatchPageResult
from app.services.dispatch import dispatch_service

router = APIRouter(prefix="/api/dispatch", tags=["调度台账"])


@router.get("", response_model=DispatchPageResult)
def list_entries(
    keyword: str | None = Query(default=None, description="按调度单号/内容/结论检索"),
    spare_code: str | None = Query(default=None, description="按备件编号过滤"),
    page: int = 1,
    size: int = 20,
) -> DispatchPageResult:
    """查询调度台账；备件整改结论在整改单闭环时自动落到这里。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = dispatch_service.list_entries(
        keyword=keyword, spare_code=spare_code, page=page, size=size
    )
    return DispatchPageResult(items=items, total=total, page=page, size=size)
