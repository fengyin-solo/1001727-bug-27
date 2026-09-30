"""备件器材接口：备件台账、库位冻结、出入库、盘点与历史台账查询。

所有业务校验都在服务端完成并落库；业务规则被拒绝时返回 ``ok=false`` 与可读原因，
HTTP 层保持 200，与平台其他模块的响应风格一致。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, LedgerPageResult, PageResult
from app.services.spare import (
    LEDGER_CHECK,
    LEDGER_IN,
    LEDGER_OUT,
    BusinessError,
    spare_service,
)

router = APIRouter(prefix="/api/spare", tags=["备件器材"])

LIST_FIELDS = ["备件编号", "备件名称", "适用设备", "结存数量", "计量单位", "存放库位", "保管人员", "备件状态"]
STATUSES = ["正常可用", "储备不足", "已冻结", "已耗尽"]


def _fail(message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=message)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按备件编号检索"),
    status: str | None = Query(default=None, description="正常可用、储备不足、已冻结、已耗尽"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按备件编号与状态过滤备件；结存数量由存放库位明细实时汇总。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = spare_service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/ledger", response_model=LedgerPageResult)
def list_ledger(
    spare_code: str | None = Query(default=None, description="按备件编号过滤"),
    change_type: str | None = Query(default=None, description="出库、入库、盘点调整"),
    batch_no: str | None = Query(default=None, description="出入库/盘点批次号"),
    page: int = 1,
    size: int = 20,
) -> LedgerPageResult:
    """历史出入库台账：只追加、不修改，用于盘点核对与重复提交追溯。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = spare_service.list_ledger(
        spare_code=spare_code, change_type=change_type, batch_no=batch_no, page=page, size=size
    )
    return LedgerPageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出备件清单（含库位明细）：返回全量数据。"""
    items, total = spare_service.list_entries(page=1, size=10000)
    return {"module": "spare", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条备件器材明细（含全部存放库位明细）。"""
    entry = spare_service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"备件器材 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条备件器材，缺字段或编号重复时说明原因而不是静默丢弃。"""
    try:
        entry, missing = spare_service.create_entry(payload.values)
    except BusinessError as exc:
        return ActionResult(ok=False, message=str(exc))
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="备件器材已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """备件级冻结/解冻（作用于该备件的全部存放库位）。"""
    action = str(payload.values.get("action") or "").strip()
    if action == "冻结备件":
        try:
            entry, message = spare_service.set_frozen(entry_id, frozen=True)
        except BusinessError as exc:
            return ActionResult(ok=False, message=str(exc))
        return ActionResult(ok=True, message=message, entry=entry)
    if action == "解冻备件":
        try:
            entry, message = spare_service.set_frozen(entry_id, frozen=False)
        except BusinessError as exc:
            return ActionResult(ok=False, message=str(exc))
        return ActionResult(ok=True, message=message, entry=entry)
    return ActionResult(ok=False, message=f"动作「{action}」不属于备件器材可执行范围")


@router.post("/locations/{location_id}/actions", response_model=ActionResult)
def run_location_action(location_id: int, payload: EntryPayload) -> ActionResult:
    """库位级冻结/解冻：只影响指定存放库位。"""
    action = str(payload.values.get("action") or "").strip()
    if action not in ("冻结库位", "解冻库位"):
        return ActionResult(ok=False, message=f"动作「{action}」不属于库位可执行范围")
    try:
        entry = spare_service.set_location_frozen(
            location_id, frozen=(action == "冻结库位")
        )
    except BusinessError as exc:
        return ActionResult(ok=False, message=str(exc))
    return ActionResult(ok=True, message=f"库位已{action[2:]}", entry=entry)


def _parse_move(values: dict[str, Any], change_type: str) -> dict[str, Any]:
    spare_code = str(values.get("备件编号") or "").strip()
    location = str(values.get("存放库位") or "").strip()
    if not spare_code:
        raise _fail("必须填写备件编号")
    if not location:
        raise _fail("必须填写存放库位")
    return {
        "spare_code": spare_code,
        "location": location,
        "quantity": values.get("数量"),
        "change_type": change_type,
        "batch_no": str(values.get("批次号") or "").strip(),
        "idem_key": str(values.get("idem_key") or values.get("批次号") or "").strip() or None,
        "operator": str(values.get("经办人员") or "").strip(),
        "remark": str(values.get("备注") or "").strip(),
    }


@router.post("/outbound", response_model=ActionResult)
def outbound(payload: EntryPayload) -> ActionResult:
    """备件出库：冻结库位在服务端被拒绝；同批次重复提交只扣减一次。"""
    try:
        kwargs = _parse_move(payload.values, LEDGER_OUT)
        entry = spare_service.stock_move(**kwargs)
    except BusinessError as exc:
        return ActionResult(ok=False, message=str(exc))
    return ActionResult(ok=True, message="出库已登记并扣减库存", entry=entry)


@router.post("/inbound", response_model=ActionResult)
def inbound(payload: EntryPayload) -> ActionResult:
    """备件入库：回补库位数量并追加台账；同批次重复提交只生效一次。"""
    try:
        kwargs = _parse_move(payload.values, LEDGER_IN)
        entry = spare_service.stock_move(**kwargs)
    except BusinessError as exc:
        return ActionResult(ok=False, message=str(exc))
    return ActionResult(ok=True, message="入库已登记并回补库存", entry=entry)


@router.post("/stocktake", response_model=ActionResult)
def stocktake(payload: EntryPayload) -> ActionResult:
    """盘点提交：库位明细与结存总量在同一事务内同步更新，差异逐库位入台账。"""
    values = payload.values
    spare_code = str(values.get("备件编号") or "").strip()
    batch_no = str(values.get("批次号") or "").strip()
    idem_key = str(values.get("idem_key") or batch_no).strip() or None
    if not spare_code:
        return ActionResult(ok=False, message="必须填写备件编号")
    if not batch_no:
        return ActionResult(ok=False, message="盘点必须填写批次号，用于重复提交校验")
    raw_items = values.get("盘点明细")
    if not isinstance(raw_items, list) or not raw_items:
        return ActionResult(ok=False, message="盘点明细不能为空，至少提交一个库位的实盘数量")
    try:
        entry = spare_service.stocktake(
            spare_code=spare_code,
            items=raw_items,
            batch_no=batch_no,
            idem_key=idem_key,
            operator=str(values.get("经办人员") or "").strip(),
            remark=str(values.get("备注") or "").strip(),
        )
    except BusinessError as exc:
        return ActionResult(ok=False, message=str(exc))
    return ActionResult(ok=True, message="盘点已落库，库位明细与结存总量已同步", entry=entry)
