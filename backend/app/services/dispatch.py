"""调度台账：备件器材的整改结论闭环后必须在这里留痕。

台账记录只在整改单「确认闭环」时由服务端生成，一张整改单最多生成一条，
重复提交闭环不会重复建账；生成后不提供修改、删除入口。
"""
from __future__ import annotations

import sqlite3
from typing import Any

from app.db import db, now_text

STATUS_PENDING = "待调度"
STATUS_DONE = "已调度"


class DispatchError(Exception):
    pass


class DispatchService:
    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "调度单号": row["dispatch_no"],
            "来源": row["source"],
            "关联整改单": row["rectify_id"],
            "备件编号": row["spare_code"],
            "备件名称": row["spare_name"],
            "调度内容": row["content"],
            "整改结论": row["conclusion"],
            "调度数量": row["dispatch_qty"],
            "调度状态": row["status"],
            "经办人员": row["operator"],
            "登记时间": row["created_at"],
        }

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        spare_code: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        where, params = [], []
        if keyword:
            where.append("(dispatch_no LIKE ? OR content LIKE ? OR conclusion LIKE ?)")
            like = f"%{keyword}%"
            params.extend([like, like, like])
        if spare_code:
            where.append("spare_code = ?")
            params.append(spare_code)
        clause = f"WHERE {' AND '.join(where)}" if where else ""

        def _txn(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], int]:
            total = conn.execute(
                f"SELECT COUNT(*) AS c FROM dispatch_ledger {clause}", params
            ).fetchone()["c"]
            start = max(page - 1, 0) * size
            rows = conn.execute(
                f"SELECT * FROM dispatch_ledger {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                (*params, size, start),
            ).fetchall()
            return [self._row_to_dict(row) for row in rows], total

        return db.write(_txn)

    def find_by_rectify(self, conn: sqlite3.Connection, rectify_id: int) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM dispatch_ledger WHERE source = '整改闭环' AND rectify_id = ?",
            (rectify_id,),
        ).fetchone()

    def create_from_rectify(
        self,
        conn: sqlite3.Connection,
        *,
        rectify_id: int,
        rectify_no: str,
        spare_code: str,
        conclusion: str,
        operator: str = "",
        dispatch_qty: int = 0,
    ) -> dict[str, Any]:
        """在整改闭环事务内部调用：校验备件并生成调度台账（幂等）。"""
        existing = self.find_by_rectify(conn, rectify_id)
        if existing is not None:
            return self._row_to_dict(existing)

        spare = conn.execute("SELECT * FROM spare WHERE spare_code = ?", (spare_code,)).fetchone()
        if spare is None:
            raise DispatchError(f"备件编号「{spare_code}」不存在，整改结论无法落到调度台账")

        seq = conn.execute("SELECT COUNT(*) AS c FROM dispatch_ledger").fetchone()["c"] + 1
        dispatch_no = f"DISP-{now_text()[:4]}-{seq:04d}"
        content = f"整改单 {rectify_no} 闭环，依据整改结论调度备件「{spare['spare_name']}」"
        cur = conn.execute(
            "INSERT INTO dispatch_ledger (dispatch_no, source, rectify_id, spare_code, spare_name, "
            "content, conclusion, dispatch_qty, status, operator, created_at) "
            "VALUES (?, '整改闭环', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (dispatch_no, rectify_id, spare_code, spare["spare_name"], content,
             conclusion, dispatch_qty, STATUS_PENDING, operator, now_text()),
        )
        row = conn.execute("SELECT * FROM dispatch_ledger WHERE id = ?", (cur.lastrowid,)).fetchone()
        return self._row_to_dict(row)


dispatch_service = DispatchService()
