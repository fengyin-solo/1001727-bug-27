"""备件器材业务规则：库存校验、台账留痕、盘点同步与整改落调度台账都收在这里。

关键约束：
- 出库必须在服务端校验冻结标记，已冻结库位一律拒绝；
- 入库/出库/盘点都带幂等键，同一批重复提交只生效一次；
- 盘点结果直接回写结存数量，存放库位明细与总量保持同步；
- 出入库历史只追加不改写，台账始终保留；
- 备件器材的整改结论落到调度台账，供调度环节跟踪。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.db import row_to_dict, transaction

MODULE = "spare"
REQUIRED_FIELDS = ["备件编号", "备件名称", "适用设备"]
STATUS_ORDER = ["正常可用", "储备不足", "已冻结", "已耗尽"]
ACTION_RULES = {"冻结备件": "已冻结", "解冻备件": "正常可用", "登记耗尽": "已耗尽"}
NEGATIVE_ACTIONS: list[str] = []

LEDGER_TYPES = ("入库", "出库", "盘盈", "盘亏")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _next_no(conn, prefix: str, table: str, col: str) -> str:
    """按前缀生成下一个单号，如 DD0001。"""
    row = conn.execute(
        f"SELECT {col} AS no FROM {table} WHERE {col} LIKE ? ORDER BY {col} DESC LIMIT 1",
        (f"{prefix}%",),
    ).fetchone()
    if row and row["no"]:
        try:
            num = int(str(row["no"]).replace(prefix, "")) + 1
        except ValueError:
            num = 1
    else:
        num = 1
    return f"{prefix}{num:04d}"


class SpareService:
    # ---------------- 查询 ----------------
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
            where.append("备件编号 LIKE ?")
            params.append(f"%{keyword}%")
        if status:
            where.append("备件状态 = ?")
            params.append(status)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        with transaction() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS c FROM spare{where_sql}", params
            ).fetchone()["c"]
            rows = conn.execute(
                f"SELECT * FROM spare{where_sql} ORDER BY id LIMIT ? OFFSET ?",
                [*params, size, max(page - 1, 0) * size],
            ).fetchall()
        return [row_to_dict(row) for row in rows], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        with transaction() as conn:
            row = conn.execute("SELECT * FROM spare WHERE id = ?", (entry_id,)).fetchone()
        return row_to_dict(row)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        with transaction() as conn:
            exists = conn.execute(
                "SELECT 1 FROM spare WHERE 备件编号 = ?", (values.get("备件编号"),)
            ).fetchone()
            if exists:
                return None, [f"备件编号 {values.get('备件编号')} 已存在，不能重复登记"]
            cur = conn.execute(
                """INSERT INTO spare (备件编号, 备件名称, 适用设备, 结存数量, 计量单位, 存放库位, 保管人员, 备件状态, frozen)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (
                    str(values.get("备件编号") or ""),
                    str(values.get("备件名称") or ""),
                    str(values.get("适用设备") or ""),
                    float(values.get("结存数量", 0) or 0),
                    str(values.get("计量单位") or ""),
                    str(values.get("存放库位") or ""),
                    str(values.get("保管人员") or ""),
                    str(values.get("备件状态") or STATUS_ORDER[0]),
                ),
            )
            row = conn.execute("SELECT * FROM spare WHERE id = ?", (cur.lastrowid,)).fetchone()
        return row_to_dict(row), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于备件器材可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        with transaction() as conn:
            row = conn.execute("SELECT * FROM spare WHERE id = ?", (entry_id,)).fetchone()
            if row is None:
                return None, f"备件器材 {entry_id} 不存在或已归档"
            frozen = 1 if target == "已冻结" else 0
            conn.execute(
                "UPDATE spare SET 备件状态 = ?, frozen = ?, updated_at = ? WHERE id = ?",
                (target, frozen, _now(), entry_id),
            )
            row = conn.execute("SELECT * FROM spare WHERE id = ?", (entry_id,)).fetchone()
        return row_to_dict(row), f"备件器材已{action}"

    # ---------------- 入库 ----------------
    def stock_in(
        self,
        entry_id: int,
        qty: float,
        batch_no: str,
        remark: str,
        idempotency_key: str,
    ) -> tuple[dict[str, Any] | None, str, bool]:
        if qty <= 0:
            return None, "入库数量必须大于 0", False
        with transaction() as conn:
            dup = conn.execute(
                "SELECT * FROM spare_stock_ledger WHERE 幂等键 = ?", (idempotency_key,)
            ).fetchone()
            if dup:
                entry = conn.execute("SELECT * FROM spare WHERE id = ?", (entry_id,)).fetchone()
                return row_to_dict(entry), "该入库申请已处理，请勿重复提交", True
            row = conn.execute("SELECT * FROM spare WHERE id = ?", (entry_id,)).fetchone()
            if row is None:
                return None, f"备件器材 {entry_id} 不存在或已归档", False
            before = float(row["结存数量"])
            after = before + qty
            conn.execute(
                "UPDATE spare SET 结存数量 = ?, updated_at = ? WHERE id = ?",
                (after, _now(), entry_id),
            )
            conn.execute(
                """INSERT INTO spare_stock_ledger (备件编号, 业务类型, 批次号, 数量, 结存后数量, 库位, 备注, 幂等键)
                   VALUES (?, '入库', ?, ?, ?, ?, ?, ?)""",
                (row["备件编号"], batch_no, qty, after, row["存放库位"], remark, idempotency_key),
            )
            entry = conn.execute("SELECT * FROM spare WHERE id = ?", (entry_id,)).fetchone()
        return row_to_dict(entry), f"入库成功，结存 {after}", False

    # ---------------- 出库 ----------------
    def stock_out(
        self,
        entry_id: int,
        qty: float,
        batch_no: str,
        remark: str,
        idempotency_key: str,
    ) -> tuple[dict[str, Any] | None, str, bool]:
        if qty <= 0:
            return None, "出库数量必须大于 0", False
        with transaction() as conn:
            dup = conn.execute(
                "SELECT * FROM spare_stock_ledger WHERE 幂等键 = ?", (idempotency_key,)
            ).fetchone()
            if dup:
                entry = conn.execute("SELECT * FROM spare WHERE id = ?", (entry_id,)).fetchone()
                return row_to_dict(entry), "该出库申请已处理，请勿重复提交", True
            row = conn.execute("SELECT * FROM spare WHERE id = ?", (entry_id,)).fetchone()
            if row is None:
                return None, f"备件器材 {entry_id} 不存在或已归档", False
            # 服务端校验冻结标记：冻结库位拒绝出库
            if row["frozen"] or row["备件状态"] == "已冻结":
                return None, f"备件 {row['备件编号']} 所在库位已冻结，拒绝出库；请先解冻后再操作", False
            before = float(row["结存数量"])
            if before < qty:
                return None, f"备件 {row['备件编号']} 结存不足：当前 {before}，申请出库 {qty}", False
            after = before - qty
            conn.execute(
                "UPDATE spare SET 结存数量 = ?, updated_at = ? WHERE id = ?",
                (after, _now(), entry_id),
            )
            conn.execute(
                """INSERT INTO spare_stock_ledger (备件编号, 业务类型, 批次号, 数量, 结存后数量, 库位, 备注, 幂等键)
                   VALUES (?, '出库', ?, ?, ?, ?, ?, ?)""",
                (row["备件编号"], batch_no, -qty, after, row["存放库位"], remark, idempotency_key),
            )
            entry = conn.execute("SELECT * FROM spare WHERE id = ?", (entry_id,)).fetchone()
        return row_to_dict(entry), f"出库成功，结存 {after}", False

    # ---------------- 盘点 ----------------
    def stocktake(
        self,
        items: list[dict[str, Any]],
        stocktake_no: str,
        stocktake_date: str,
        operator: str,
        remark: str,
        idempotency_key: str,
    ) -> tuple[dict[str, Any] | None, str, bool]:
        if not items:
            return None, "盘点明细不能为空", False
        with transaction() as conn:
            if stocktake_no:
                dup = conn.execute(
                    "SELECT 1 FROM spare_stocktake WHERE 盘点单号 = ?", (stocktake_no,)
                ).fetchone()
                if dup:
                    return None, f"盘点单 {stocktake_no} 已存在，请勿重复提交", True
            dup_key = conn.execute(
                "SELECT 1 FROM spare_stock_ledger WHERE 幂等键 = ?", (idempotency_key,)
            ).fetchone()
            if dup_key:
                return None, "该盘点申请已处理，请勿重复提交", True
            if not stocktake_no:
                stocktake_no = _next_no("PD", conn, "spare_stocktake", "盘点单号")
            conn.execute(
                """INSERT INTO spare_stocktake (盘点单号, 盘点日期, 盘点人, 状态, 备注)
                   VALUES (?, ?, ?, '已完成', ?)""",
                (stocktake_no, stocktake_date, operator, remark),
            )
            results: list[dict[str, Any]] = []
            for item in items:
                code = str(item.get("备件编号") or "").strip()
                actual = float(item.get("实盘数量", 0) or 0)
                row = conn.execute("SELECT * FROM spare WHERE 备件编号 = ?", (code,)).fetchone()
                if row is None:
                    return None, f"备件编号 {code} 不存在", False
                book = float(row["结存数量"])
                diff = actual - book
                conn.execute(
                    """INSERT INTO spare_stocktake_item (盘点单号, 备件编号, 账面数量, 实盘数量, 差异数量, 库位)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (stocktake_no, code, book, actual, diff, row["存放库位"]),
                )
                if diff != 0:
                    biz_type = "盘盈" if diff > 0 else "盘亏"
                    conn.execute(
                        "UPDATE spare SET 结存数量 = ?, updated_at = ? WHERE id = ?",
                        (actual, _now(), row["id"]),
                    )
                    conn.execute(
                        """INSERT INTO spare_stock_ledger (备件编号, 业务类型, 批次号, 数量, 结存后数量, 库位, 备注, 幂等键)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            code,
                            biz_type,
                            stocktake_no,
                            diff,
                            actual,
                            row["存放库位"],
                            f"盘点调整({stocktake_no})",
                            f"{idempotency_key}:{code}",
                        ),
                    )
                results.append({"备件编号": code, "账面数量": book, "实盘数量": actual, "差异数量": diff})
        return (
            {"盘点单号": stocktake_no, "明细": results},
            "盘点完成，结存已与存放库位明细同步",
            False,
        )

    # ---------------- 整改（结论落调度台账） ----------------
    def rectify(
        self,
        entry_id: int,
        conclusion: str,
        dispatch_content: str,
        remark: str,
    ) -> tuple[dict[str, Any] | None, str]:
        if not conclusion or not str(conclusion).strip():
            return None, "整改结论不能为空"
        with transaction() as conn:
            row = conn.execute("SELECT * FROM spare WHERE id = ?", (entry_id,)).fetchone()
            if row is None:
                return None, f"备件器材 {entry_id} 不存在或已归档"
            # 整改完成：解除冻结，恢复正常可用
            conn.execute(
                "UPDATE spare SET 备件状态 = '正常可用', frozen = 0, updated_at = ? WHERE id = ?",
                (_now(), entry_id),
            )
            dispatch_no = _next_no(conn, "DD", "dispatch_ledger", "调度单号")
            conn.execute(
                """INSERT INTO dispatch_ledger (调度单号, 来源模块, 备件编号, 备件名称, 整改结论, 调度内容, 状态, 备注)
                   VALUES (?, '备件器材整改', ?, ?, ?, ?, '待调度', ?)""",
                (
                    dispatch_no,
                    row["备件编号"],
                    row["备件名称"],
                    conclusion,
                    dispatch_content or "",
                    remark or "",
                ),
            )
            entry = conn.execute("SELECT * FROM spare WHERE id = ?", (entry_id,)).fetchone()
        return row_to_dict(entry), f"整改结论已落到调度台账（{dispatch_no}）"

    # ---------------- 出入库台账 ----------------
    def list_ledger(
        self,
        *,
        keyword: str | None = None,
        biz_type: str | None = None,
        batch_no: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        where: list[str] = []
        params: list[Any] = []
        if keyword:
            where.append("备件编号 LIKE ?")
            params.append(f"%{keyword}%")
        if biz_type:
            where.append("业务类型 = ?")
            params.append(biz_type)
        if batch_no:
            where.append("批次号 = ?")
            params.append(batch_no)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        with transaction() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS c FROM spare_stock_ledger{where_sql}", params
            ).fetchone()["c"]
            rows = conn.execute(
                f"SELECT * FROM spare_stock_ledger{where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
                [*params, size, max(page - 1, 0) * size],
            ).fetchall()
        return [row_to_dict(row) for row in rows], total
