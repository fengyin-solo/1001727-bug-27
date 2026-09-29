"""备件器材接口：维护备件器材，覆盖冻结/解冻/登记耗尽、入库、出库、盘点与整改。

库存类操作都带幂等键，同一批重复提交只生效一次；出库在服务端校验冻结标记，
已冻结库位拒绝出库；盘点结果直接回写结存数量，与存放库位明细同步；
整改结论落到调度台账。所有变动落库，刷新后数字不回退。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.spare import SpareService

router = APIRouter(prefix="/api/spare", tags=["备件器材"])

service = SpareService()

LIST_FIELDS = ["备件编号", "备件名称", "适用设备", "结存数量", "计量单位", "存放库位", "保管人员", "备件状态"]
STATUSES = ["正常可用", "储备不足", "已冻结", "已耗尽"]
LEDGER_TYPES = ["入库", "出库", "盘盈", "盘亏"]


def _num(values: dict[str, Any], key: str) -> float:
    try:
        return float(values.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


# ---- 静态路径必须在 /{entry_id} 之前注册，否则会被当成 entry_id 解析 ----

@router.get("/ledger", response_model=PageResult[dict])
def list_ledger(
    keyword: str | None = Query(default=None, description="按备件编号检索"),
    biz_type: str | None = Query(default=None, description="入库、出库、盘盈、盘亏"),
    batch_no: str | None = Query(default=None, description="按批次号检索"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """出入库台账：历史记录只增不改，始终保留。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_ledger(
        keyword=keyword, biz_type=biz_type, batch_no=batch_no, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/stocktake", response_model=ActionResult)
def stocktake(payload: EntryPayload) -> ActionResult:
    """盘点：按实盘数量回写结存，差异计入台账，结果与存放库位明细同步。"""
    values = payload.values
    items = values.get("明细") or []
    if not isinstance(items, list) or not items:
        return ActionResult(ok=False, message="盘点明细不能为空")
    stocktake_no = str(values.get("盘点单号", "") or "").strip()
    stocktake_date = str(values.get("盘点日期", "") or "").strip() or datetime.now().strftime("%Y-%m-%d")
    operator = str(values.get("盘点人", "") or "").strip()
    remark = str(values.get("备注", "") or "").strip()
    idem = str(values.get("幂等键", "") or "").strip() or f"stocktake:{stocktake_no or datetime.now().strftime('%Y%m%d%H%M%S')}"
    result, message, duplicated = service.stocktake(
        items, stocktake_no, stocktake_date, operator, remark, idem
    )
    if result is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=result)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按备件编号检索"),
    status: str | None = Query(default=None, description="正常可用、储备不足、已冻结、已耗尽"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按备件编号与状态过滤备件器材列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条备件器材明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"备件器材 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条备件器材，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="备件器材已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条备件器材执行冻结备件、解冻备件、登记耗尽；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/stock-in", response_model=ActionResult)
def stock_in(entry_id: int, payload: EntryPayload) -> ActionResult:
    """入库：增加结存数量并写入台账；同一幂等键只生效一次。"""
    values = payload.values
    qty = _num(values, "数量")
    batch_no = str(values.get("批次号", "") or "").strip()
    remark = str(values.get("备注", "") or "").strip()
    idem = str(values.get("幂等键", "") or "").strip() or f"in:{entry_id}:{batch_no}:{qty}"
    entry, message, duplicated = service.stock_in(entry_id, qty, batch_no, remark, idem)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/stock-out", response_model=ActionResult)
def stock_out(entry_id: int, payload: EntryPayload) -> ActionResult:
    """出库：服务端校验冻结标记与结存不足，冻结库位拒绝出库；同一幂等键只生效一次。"""
    values = payload.values
    qty = _num(values, "数量")
    batch_no = str(values.get("批次号", "") or "").strip()
    remark = str(values.get("备注", "") or "").strip()
    idem = str(values.get("幂等键", "") or "").strip() or f"out:{entry_id}:{batch_no}:{qty}"
    entry, message, duplicated = service.stock_out(entry_id, qty, batch_no, remark, idem)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/rectify", response_model=ActionResult)
def rectify(entry_id: int, payload: EntryPayload) -> ActionResult:
    """整改：登记整改结论并落到调度台账，同时解除冻结恢复正常可用。"""
    values = payload.values
    conclusion = str(values.get("整改结论", "") or "").strip()
    dispatch_content = str(values.get("调度内容", "") or "").strip()
    remark = str(values.get("备注", "") or "").strip()
    entry, message = service.rectify(entry_id, conclusion, dispatch_content, remark)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出备件器材清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "spare", "total": total, "items": items}
