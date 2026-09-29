"""调度台账业务规则：备件器材整改结论落到这里，供调度环节跟踪。"""
from __future__ import annotations

from typing import Any

from app.db import row_to_dict, transaction

MODULE = "dispatch"


class DispatchService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        where: list[str] = []
        params: list[Any] = []
        if keyword:
            where.append("(调度单号 LIKE ? OR 备件编号 LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if status:
            where.append("状态 = ?")
            params.append(status)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        with transaction() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS c FROM dispatch_ledger{where_sql}", params
            ).fetchone()["c"]
            rows = conn.execute(
                f"SELECT * FROM dispatch_ledger{where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
                [*params, size, max(page - 1, 0) * size],
            ).fetchall()
        return [row_to_dict(row) for row in rows], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        with transaction() as conn:
            row = conn.execute(
                "SELECT * FROM dispatch_ledger WHERE id = ?", (entry_id,)
            ).fetchone()
        return row_to_dict(row)
