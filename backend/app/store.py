"""数据仓库：业务记录统一落在 SQLite，服务重启后调整结果仍在。

通用模块（锅炉、整改等）仍按原来的 ``store.rows(module)`` 取一批字典来用，
但这些字典是 :class:`TrackedDict`——任意字段赋值都会立刻 UPDATE 回库；
:meth:`Store.add` 负责 INSERT。备件器材库位/台账有独立的表结构，不走这里，
见 :mod:`app.services.spare`。
"""
from __future__ import annotations

import json
from typing import Any

from app.db import db, now_text
from app.seed import SEED_ROWS


class TrackedDict(dict):
    """字段一改就落库的字典，保持旧代码 ``entry["status"] = ...`` 的写法不变。"""

    def __init__(self, module: str, entry_id: int, data: dict[str, Any]) -> None:
        super().__init__(data)
        self._module = module
        self._entry_id = entry_id

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        Store.instance.persist(self._module, self._entry_id, dict(self))


class TrackedList(list):
    """append 即 INSERT；append 之外的原地改动目前业务里没有用到。"""

    def __init__(self, module: str, items: list[TrackedDict]) -> None:
        super().__init__(items)
        self._module = module

    def append(self, item: dict[str, Any]) -> None:
        entry_id = int(item.get("id") or 0) or Store.instance.next_id(self._module)
        item["id"] = entry_id
        payload = {k: v for k, v in item.items() if k != "id"}
        Store.instance.insert(self._module, entry_id, payload)
        tracked = TrackedDict(self._module, entry_id, {"id": entry_id, **payload})
        super().append(tracked)
        item.clear()
        item.update(tracked)


# 备件器材使用独立的库位/台账表，不参与通用字典表的示例数据初始化。
DEDICATED_MODULES = {"spare", "dispatch"}


class Store:
    instance: "Store"

    def __init__(self) -> None:
        Store.instance = self
        self._seed_if_empty()

    # ---------- 初始化 ----------
    def _seed_if_empty(self) -> None:
        def _txn(conn):
            count = conn.execute("SELECT COUNT(*) AS c FROM entries").fetchone()["c"]
            if count:
                return
            stamp = now_text()
            for module, rows in SEED_ROWS.items():
                if module in DEDICATED_MODULES:
                    continue
                for row in rows:
                    row = dict(row)
                    entry_id = int(row.pop("id"))
                    conn.execute(
                        "INSERT INTO entries (module, entry_id, data, updated_at) "
                        "VALUES (?, ?, ?, ?)",
                        (module, entry_id, json.dumps(row, ensure_ascii=False), stamp),
                    )

        db.write(_txn)

    # ---------- 基础持久化 ----------
    def insert(self, module: str, entry_id: int, data: dict[str, Any]) -> None:
        db.write(
            lambda conn: conn.execute(
                "INSERT INTO entries (module, entry_id, data, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (module, entry_id, json.dumps(data, ensure_ascii=False), now_text()),
            )
        )

    def persist(self, module: str, entry_id: int, data: dict[str, Any]) -> None:
        payload = {k: v for k, v in data.items() if k != "id"}
        db.write(
            lambda conn: conn.execute(
                "UPDATE entries SET data = ?, updated_at = ? WHERE module = ? AND entry_id = ?",
                (json.dumps(payload, ensure_ascii=False), now_text(), module, entry_id),
            )
        )

    def next_id(self, module: str) -> int:
        row = db.read_one(
            "SELECT COALESCE(MAX(entry_id), 0) + 1 AS next_id FROM entries WHERE module = ?",
            (module,),
        )
        return int(row["next_id"])

    # ---------- 查询 ----------
    def module_names(self) -> list[str]:
        rows = db.read_all("SELECT DISTINCT module FROM entries")
        names = {row["module"] for row in rows}
        names.add("spare")
        names.add("dispatch")
        return sorted(names)

    def rows(self, module: str) -> TrackedList:
        records = db.read_all(
            "SELECT entry_id, data FROM entries WHERE module = ? ORDER BY entry_id",
            (module,),
        )
        items: list[TrackedDict] = []
        for row in records:
            data = json.loads(row["data"])
            data["id"] = row["entry_id"]
            items.append(TrackedDict(module, row["entry_id"], data))
        return TrackedList(module, items)

    def find(self, module: str, entry_id: int) -> TrackedDict | None:
        row = db.read_one(
            "SELECT entry_id, data FROM entries WHERE module = ? AND entry_id = ?",
            (module, entry_id),
        )
        if row is None:
            return None
        data = json.loads(row["data"])
        data["id"] = row["entry_id"]
        return TrackedDict(module, row["entry_id"], data)

    def add(self, module: str, data: dict[str, Any]) -> TrackedDict:
        """给新登记入口用的 INSERT 辅助。"""
        entry_id = self.next_id(module)
        self.insert(module, entry_id, data)
        result = self.find(module, entry_id)
        assert result is not None
        return result

    # ---------- 看板 ----------
    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })

        def _spare_stats(conn):
            total_qty = conn.execute(
                "SELECT COALESCE(SUM(quantity), 0) AS q, COUNT(*) AS c FROM spare_location"
            ).fetchone()
            frozen_locs = conn.execute(
                "SELECT COUNT(*) AS c FROM spare_location WHERE frozen = 1"
            ).fetchone()["c"]
            return total_qty["q"], total_qty["c"], frozen_locs

        spare_qty, loc_count, frozen_locs = db.write(_spare_stats)
        for module in modules:
            if module["name"] == "spare":
                module["created"] = loc_count
                module["abnormal"] = frozen_locs
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        _ = spare_qty
        return {"cards": cards, "modules": modules}


store = Store()
