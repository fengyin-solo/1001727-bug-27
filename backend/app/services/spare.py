"""备件器材业务规则：库位级冻结校验、出入库与盘点都在这里落库。

与旧实现的关键区别：
1. 冻结标记挂在「存放库位」上，出库在服务端同一事务里校验，冻结库位拒绝出库；
2. 结存数量由库位明细实时汇总，盘点调整同时改库位明细并追加台账，二者必然对得上；
3. 每个写接口都接受 ``idem_key``（前端以「单号 + 批次号」生成），重复提交直接回放
   首次结果，同一批备件不会被扣两次；
4. 出入库台账只追加、不修改、不删除，历史永久保留。
"""
from __future__ import annotations

import sqlite3
from typing import Any

from app.db import db, now_text

MODULE = "spare"
REQUIRED_FIELDS = ["备件编号", "备件名称", "适用设备"]
STATUS_AVAILABLE = "正常可用"
STATUS_LOW = "储备不足"
STATUS_FROZEN = "已冻结"
STATUS_EMPTY = "已耗尽"
STATUS_ORDER = [STATUS_AVAILABLE, STATUS_LOW, STATUS_FROZEN, STATUS_EMPTY]

LEDGER_OUT = "出库"
LEDGER_IN = "入库"
LEDGER_CHECK = "盘点调整"

# 初次启动时灌入的示例备件与库位（含一个已冻结库位，用于演示拒绝出库）。
SEED_SPARES = [
    {
        "备件编号": "SPAR-0001", "备件名称": "高压密封垫圈", "适用设备": "锅炉 BOIL-0002",
        "计量单位": "个", "保管人员": "王建国", "安全库存": 10,
        "库位": [
            {"存放库位": "A区-01架-03位", "数量": 8, "冻结": False},
            {"存放库位": "A区-02架-01位", "数量": 6, "冻结": False},
        ],
    },
    {
        "备件编号": "SPAR-0002", "备件名称": "耐高温轴承", "适用设备": "起重机械 CRAN-0001",
        "计量单位": "套", "保管人员": "李秀英", "安全库存": 5,
        "库位": [
            {"存放库位": "B区-01架-02位", "数量": 3, "冻结": False},
        ],
    },
    {
        "备件编号": "SPAR-0003", "备件名称": "防冻液压油", "适用设备": "场内机动车辆 FORK-0002",
        "计量单位": "桶", "保管人员": "赵德柱", "安全库存": 8,
        "库位": [
            {"存放库位": "C区-冷库-01位", "数量": 30, "冻结": True},
        ],
    },
]


class BusinessError(Exception):
    """业务规则被拒绝（冻结库位出库、库存不足等），由路由层转成可读响应。"""


def _to_int(value: Any, field: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise BusinessError(f"「{field}」必须是整数") from None
    if result < 0:
        raise BusinessError(f"「{field}」不能为负数")
    return result


class SpareService:
    # ---------- 初始化示例数据 ----------
    def seed_if_empty(self) -> None:
        def _txn(conn: sqlite3.Connection) -> None:
            if conn.execute("SELECT COUNT(*) AS c FROM spare").fetchone()["c"]:
                return
            stamp = now_text()
            for item in SEED_SPARES:
                cur = conn.execute(
                    "INSERT INTO spare (spare_code, spare_name, fit_device, unit, keeper, "
                    "safety_stock, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (item["备件编号"], item["备件名称"], item["适用设备"], item["计量单位"],
                     item["保管人员"], item["安全库存"], stamp),
                )
                spare_id = cur.lastrowid
                for loc in item["库位"]:
                    conn.execute(
                        "INSERT INTO spare_location (spare_id, location, quantity, frozen, updated_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (spare_id, loc["存放库位"], loc["数量"], 1 if loc["冻结"] else 0, stamp),
                    )

        db.write(_txn)

    # ---------- 读取与组装 ----------
    def _load_row(self, conn: sqlite3.Connection, spare_id: int) -> sqlite3.Row | None:
        return conn.execute("SELECT * FROM spare WHERE id = ?", (spare_id,)).fetchone()

    def _find_by_code(self, conn: sqlite3.Connection, code: str) -> sqlite3.Row | None:
        return conn.execute("SELECT * FROM spare WHERE spare_code = ?", (code.strip(),)).fetchone()

    def _derive_status(self, locations: list[sqlite3.Row], safety_stock: int) -> str:
        total = sum(row["quantity"] for row in locations)
        if total <= 0:
            return STATUS_EMPTY
        if all(row["frozen"] for row in locations if row["quantity"] > 0):
            return STATUS_FROZEN
        if total <= safety_stock:
            return STATUS_LOW
        return STATUS_AVAILABLE

    def _assemble(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        loc_rows = conn.execute(
            "SELECT * FROM spare_location WHERE spare_id = ? ORDER BY id", (row["id"],)
        ).fetchall()
        total = sum(loc["quantity"] for loc in loc_rows)
        status = self._derive_status(loc_rows, row["safety_stock"])
        return {
            "id": row["id"],
            "备件编号": row["spare_code"],
            "备件名称": row["spare_name"],
            "适用设备": row["fit_device"],
            "结存数量": total,
            "计量单位": row["unit"],
            "存放库位": "、".join(loc["location"] for loc in loc_rows) if loc_rows else "—",
            "保管人员": row["keeper"],
            "安全库存": row["safety_stock"],
            "备件状态": status,
            "status": status,
            "pending": status not in (STATUS_FROZEN, STATUS_EMPTY),
            "abnormal": status in (STATUS_LOW, STATUS_FROZEN),
            "库位明细": [
                {
                    "库位明细ID": loc["id"],
                    "存放库位": loc["location"],
                    "库位数量": loc["quantity"],
                    "库位冻结": bool(loc["frozen"]),
                    "库位状态": "已冻结" if loc["frozen"] else "正常",
                }
                for loc in loc_rows
            ],
        }

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        def _txn(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], int]:
            rows = conn.execute("SELECT * FROM spare ORDER BY id").fetchall()
            entries = [self._assemble(conn, row) for row in rows]
            if keyword:
                entries = [e for e in entries if keyword in e["备件编号"]]
            if status:
                entries = [e for e in entries if e["备件状态"] == status]
            total = len(entries)
            start = max(page - 1, 0) * size
            return entries[start:start + size], total

        return db.write(_txn)

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        def _txn(conn: sqlite3.Connection) -> dict[str, Any] | None:
            row = self._load_row(conn, entry_id)
            return self._assemble(conn, row) if row else None

        return db.write(_txn)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [f for f in REQUIRED_FIELDS if not str(values.get(f) or "").strip()]
        if missing:
            return None, missing

        def _txn(conn: sqlite3.Connection) -> dict[str, Any]:
            code = str(values["备件编号"]).strip()
            if self._find_by_code(conn, code):
                raise BusinessError(f"备件编号「{code}」已存在，不能重复登记")
            safety = _to_int(values.get("安全库存", 0), "安全库存")
            cur = conn.execute(
                "INSERT INTO spare (spare_code, spare_name, fit_device, unit, keeper, "
                "safety_stock, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (code, str(values["备件名称"]).strip(), str(values["适用设备"]).strip(),
                 str(values.get("计量单位") or "").strip(), str(values.get("保管人员") or "").strip(),
                 safety, now_text()),
            )
            row = self._load_row(conn, cur.lastrowid)
            assert row is not None
            return self._assemble(conn, row)

        return db.write(_txn), []

    # ---------- 备件级冻结/解冻（对全部库位生效） ----------
    def set_frozen(self, entry_id: int, frozen: bool) -> tuple[dict[str, Any] | None, str]:
        def _txn(conn: sqlite3.Connection) -> tuple[dict[str, Any], str]:
            row = self._load_row(conn, entry_id)
            if row is None:
                raise BusinessError(f"备件器材 {entry_id} 不存在或已归档")
            conn.execute(
                "UPDATE spare_location SET frozen = ?, updated_at = ? WHERE spare_id = ?",
                (1 if frozen else 0, now_text(), entry_id),
            )
            return self._assemble(conn, row), "已冻结全部存放库位" if frozen else "已解冻全部存放库位"

        entry, msg = db.write(_txn)
        return entry, f"备件器材{msg}"

    # ---------- 库位级冻结/解冻 ----------
    def set_location_frozen(self, location_id: int, frozen: bool) -> dict[str, Any]:
        def _txn(conn: sqlite3.Connection) -> dict[str, Any]:
            loc = conn.execute(
                "SELECT * FROM spare_location WHERE id = ?", (location_id,)
            ).fetchone()
            if loc is None:
                raise BusinessError(f"库位 {location_id} 不存在")
            conn.execute(
                "UPDATE spare_location SET frozen = ?, updated_at = ? WHERE id = ?",
                (1 if frozen else 0, now_text(), location_id),
            )
            row = self._load_row(conn, loc["spare_id"])
            assert row is not None
            return self._assemble(conn, row)

        return db.write(_txn)

    # ---------- 出库 / 入库 ----------
    def stock_move(
        self,
        *,
        spare_code: str,
        location: str,
        quantity: Any,
        change_type: str,
        batch_no: str = "",
        idem_key: str | None = None,
        operator: str = "",
        remark: str = "",
    ) -> dict[str, Any]:
        """出库/入库统一入口；冻结库位出库与超扣都在这个事务里拦下。"""
        qty = _to_int(quantity, "数量")
        if qty <= 0:
            raise BusinessError("出入库数量必须大于 0")
        if change_type not in (LEDGER_OUT, LEDGER_IN):
            raise BusinessError(f"不支持的台账类型：{change_type}")
        location = str(location or "").strip()
        if not location:
            raise BusinessError("必须指定存放库位")

        def _txn(conn: sqlite3.Connection) -> dict[str, Any]:
            replay = self._idem_get(conn, idem_key)
            if replay is not None:
                return replay

            spare = self._find_by_code(conn, spare_code)
            if spare is None:
                raise BusinessError(f"备件编号「{spare_code}」不存在")
            loc = conn.execute(
                "SELECT * FROM spare_location WHERE spare_id = ? AND location = ?",
                (spare["id"], location),
            ).fetchone()
            if loc is None:
                if change_type == LEDGER_IN:
                    cur = conn.execute(
                        "INSERT INTO spare_location (spare_id, location, quantity, frozen, updated_at) "
                        "VALUES (?, ?, 0, 0, ?)",
                        (spare["id"], location, now_text()),
                    )
                    loc = conn.execute(
                        "SELECT * FROM spare_location WHERE id = ?", (cur.lastrowid,)
                    ).fetchone()
                else:
                    raise BusinessError(f"备件「{spare_code}」在库位「{location}」没有存放明细，无法出库")
            assert loc is not None

            if change_type == LEDGER_OUT:
                # 核心修复：冻结标记在服务端强校验，前端绕过也出不了库。
                if loc["frozen"]:
                    raise BusinessError(
                        f"库位「{location}」已冻结，备件「{spare_code}」禁止出库，请先解冻"
                    )
                if loc["quantity"] < qty:
                    raise BusinessError(
                        f"库位「{location}」可用库存仅 {loc['quantity']}，不足出库 {qty}"
                    )
                new_qty = loc["quantity"] - qty
            else:
                new_qty = loc["quantity"] + qty

            conn.execute(
                "UPDATE spare_location SET quantity = ?, updated_at = ? WHERE id = ?",
                (new_qty, now_text(), loc["id"]),
            )
            ledger_id = self._append_ledger(
                conn,
                spare=spare,
                location=location,
                change_type=change_type,
                change_qty=qty if change_type == LEDGER_IN else -qty,
                balance=new_qty,
                batch_no=batch_no,
                idem_key=idem_key,
                operator=operator,
                remark=remark,
            )
            result = self._assemble(conn, spare)
            result["台账ID"] = ledger_id
            self._idem_put(conn, idem_key, result)
            return result

        return db.write(_txn)

    # ---------- 盘点：库位明细与总量一次事务同步 ----------
    def stocktake(
        self,
        *,
        spare_code: str,
        items: list[dict[str, Any]],
        batch_no: str = "",
        idem_key: str | None = None,
        operator: str = "",
        remark: str = "",
    ) -> dict[str, Any]:
        """按实盘数量整体覆盖库位明细；有差异的库位追加盘点调整台账。

        整批在同一事务提交：要么库位明细、结存总量、台账全部更新，要么全部不动，
        不会再出现「明细与总量对不上」。
        """
        if not items:
            raise BusinessError("盘点明细不能为空，至少需要一个库位的实盘数量")
        normalized: list[tuple[str, int]] = []
        seen: set[str] = set()
        for item in items:
            loc_name = str(item.get("存放库位") or "").strip()
            if not loc_name:
                raise BusinessError("盘点明细中存在未填写的存放库位")
            if loc_name in seen:
                raise BusinessError(f"库位「{loc_name}」在同一次盘点里出现了多次")
            seen.add(loc_name)
            normalized.append((loc_name, _to_int(item.get("库位数量", 0), "库位数量")))

        def _txn(conn: sqlite3.Connection) -> dict[str, Any]:
            replay = self._idem_get(conn, idem_key)
            if replay is not None:
                return replay

            spare = self._find_by_code(conn, spare_code)
            if spare is None:
                raise BusinessError(f"备件编号「{spare_code}」不存在")

            existing = {
                row["location"]: row
                for row in conn.execute(
                    "SELECT * FROM spare_location WHERE spare_id = ?", (spare["id"],)
                ).fetchall()
            }
            ledger_ids: list[int] = []
            stamp = now_text()
            for loc_name, actual_qty in normalized:
                old = existing.get(loc_name)
                old_qty = old["quantity"] if old else 0
                if old is None:
                    conn.execute(
                        "INSERT INTO spare_location (spare_id, location, quantity, frozen, updated_at) "
                        "VALUES (?, ?, ?, 0, ?)",
                        (spare["id"], loc_name, actual_qty, stamp),
                    )
                else:
                    conn.execute(
                        "UPDATE spare_location SET quantity = ?, updated_at = ? WHERE id = ?",
                        (actual_qty, stamp, old["id"]),
                    )
                # 实盘与账存一致也留痕（change_qty=0），保证盘点批次完整可追溯。
                ledger_ids.append(
                    self._append_ledger(
                        conn,
                        spare=spare,
                        location=loc_name,
                        change_type=LEDGER_CHECK,
                        change_qty=actual_qty - old_qty,
                        balance=actual_qty,
                        batch_no=batch_no,
                        idem_key=None,  # 明细行共享批次幂等，由外层统一登记
                        operator=operator,
                        remark=remark or f"盘点批次 {batch_no}".strip(),
                    )
                )
            result = self._assemble(conn, spare)
            result["台账ID"] = ledger_ids
            self._idem_put(conn, idem_key, result)
            return result

        return db.write(_txn)

    # ---------- 台账（只追加、只查询） ----------
    def _append_ledger(
        self,
        conn: sqlite3.Connection,
        *,
        spare: sqlite3.Row,
        location: str,
        change_type: str,
        change_qty: int,
        balance: int,
        batch_no: str,
        idem_key: str | None,
        operator: str,
        remark: str,
    ) -> int:
        # 明细行没有独立幂等键时，用库内自增序号补一个唯一键，避免同秒多行互相撞键。
        if idem_key:
            unique_key = idem_key
        else:
            seq = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM spare_ledger").fetchone()["next_id"]
            unique_key = f"{change_type}:{spare['id']}:{location}:line-{seq}"
        cur = conn.execute(
            "INSERT INTO spare_ledger (spare_id, spare_code, location, change_type, change_qty, "
            "balance_qty, batch_no, idem_key, operator, remark, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (spare["id"], spare["spare_code"], location, change_type, change_qty,
             balance, batch_no, unique_key, operator, remark, now_text()),
        )
        return int(cur.lastrowid)

    def _idem_get(self, conn: sqlite3.Connection, idem_key: str | None) -> dict[str, Any] | None:
        return db.idem_lookup(conn, f"spare:{idem_key}" if idem_key else "")

    def _idem_put(self, conn: sqlite3.Connection, idem_key: str | None, result: dict[str, Any]) -> None:
        db.idem_store(conn, f"spare:{idem_key}" if idem_key else "", result)

    def list_ledger(
        self,
        *,
        spare_code: str | None = None,
        change_type: str | None = None,
        batch_no: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        where, params = [], []
        if spare_code:
            where.append("spare_code = ?")
            params.append(spare_code)
        if change_type:
            where.append("change_type = ?")
            params.append(change_type)
        if batch_no:
            where.append("batch_no = ?")
            params.append(batch_no)
        clause = f"WHERE {' AND '.join(where)}" if where else ""

        def _txn(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], int]:
            total = conn.execute(
                f"SELECT COUNT(*) AS c FROM spare_ledger {clause}", params
            ).fetchone()["c"]
            start = max(page - 1, 0) * size
            rows = conn.execute(
                f"SELECT * FROM spare_ledger {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                (*params, size, start),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "备件编号": row["spare_code"],
                    "存放库位": row["location"],
                    "台账类型": row["change_type"],
                    "变动数量": row["change_qty"],
                    "结存数量": row["balance_qty"],
                    "批次号": row["batch_no"],
                    "经办人员": row["operator"],
                    "备注": row["remark"],
                    "发生时间": row["created_at"],
                }
                for row in rows
            ], total

        return db.write(_txn)


spare_service = SpareService()
spare_service.seed_if_empty()
