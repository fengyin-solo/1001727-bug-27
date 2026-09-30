"""整改闭环业务规则：状态流转、字段校验与筛选口径都收在这里。

与备件器材相关的整改，在「确认闭环」时必须把整改结论落到调度台账：
闭环状态更新与调度台账生成放在同一个数据库事务里，要么一起成功要么一起回滚；
同一张整改单重复提交闭环不会重复建账。
"""
from __future__ import annotations

import json
from typing import Any

from app.db import db, now_text
from app.services.dispatch import DispatchError, dispatch_service
from app.store import store

MODULE = "rectify"
REQUIRED_FIELDS = ["整改单号", "关联隐患", "整改措施"]
STATUS_ORDER = ["待下发", "整改中", "待验收", "已闭环"]
ACTION_RULES = {"下发整改": "整改中", "提交验收": "待验收", "确认闭环": "已闭环"}
NEGATIVE_ACTIONS = []


class RectifyService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("整改单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def _close_with_dispatch(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        spare_code = str(values.get("关联备件") or values.get("备件编号") or "").strip()
        conclusion = str(values.get("整改结论") or "").strip()
        operator = str(values.get("验收人员") or values.get("经办人员") or "").strip()
        qty_raw = values.get("调度数量", 0)
        try:
            dispatch_qty = max(int(qty_raw or 0), 0)
        except (TypeError, ValueError):
            return None, "调度数量必须是整数"

        def _txn(conn) -> str:
            existing_dispatch = dispatch_service.find_by_rectify(conn, entry_id)
            row = conn.execute(
                "SELECT data FROM entries WHERE module = ? AND entry_id = ?",
                (MODULE, entry_id),
            ).fetchone()
            if row is None:
                raise DispatchError(f"整改单 {entry_id} 不存在或已归档")
            data = json.loads(row["data"])
            rectify_no = str(data.get("整改单号") or entry_id)

            if data.get("status") == STATUS_ORDER[-1] or existing_dispatch is not None:
                # 重复闭环提交：台账已生成过，只回写补充信息，不再重复落账。
                data["关联备件"] = spare_code or data.get("关联备件", "")
                data["整改结论"] = conclusion or data.get("整改结论", "")
                conn.execute(
                    "UPDATE entries SET data = ?, updated_at = ? WHERE module = ? AND entry_id = ?",
                    (json.dumps(data, ensure_ascii=False), now_text(), MODULE, entry_id),
                )
                return "整改单已闭环，调度台账已存在，重复提交未再生效"

            if not conclusion:
                raise DispatchError("确认闭环必须填写整改结论，结论需随闭环落到调度台账")
            if spare_code:
                # 备件类整改：结论落调度台账；备件编号不存在时整个闭环回滚。
                dispatch_service.create_from_rectify(
                    conn,
                    rectify_id=entry_id,
                    rectify_no=rectify_no,
                    spare_code=spare_code,
                    conclusion=conclusion,
                    operator=operator,
                    dispatch_qty=dispatch_qty,
                )

            data["status"] = STATUS_ORDER[-1]
            data["pending"] = False
            data["abnormal"] = False
            data["关联备件"] = spare_code
            data["整改结论"] = conclusion
            if operator:
                data["验收人员"] = operator
            conn.execute(
                "UPDATE entries SET data = ?, updated_at = ? WHERE module = ? AND entry_id = ?",
                (json.dumps(data, ensure_ascii=False), now_text(), MODULE, entry_id),
            )
            return "整改单已确认闭环，整改结论已落入调度台账" if spare_code else "整改单已确认闭环"

        try:
            message = db.write(_txn)
        except DispatchError as exc:
            return None, str(exc)
        # 事务提交后再从库里读，保证返回的是落库后的最新内容。
        return store.find(MODULE, entry_id), message

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于整改闭环可执行范围"
        if action == "确认闭环":
            return self._close_with_dispatch(entry_id, values or {})

        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"整改单 {entry_id} 不存在或已归档"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"整改单已{action}"
