"""调度台账接口：查看备件器材整改结论等调度记录。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import PageResult
from app.services.dispatch import DispatchService

router = APIRouter(prefix="/api/dispatch", tags=["调度台账"])

service = DispatchService()


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按调度单号或备件编号检索"),
    status: str | None = Query(default=None, description="待调度、已调度、已完成"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """调度台账列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条调度台账明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"调度记录 {entry_id} 不存在或已归档")
    return entry
