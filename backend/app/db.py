"""持久化层：用 SQLite 把备件器材的库存调整落库，刷新后数字不回退。

之前的实现把备件数据放在全局内存 dict 里，入库、出库、盘点共用同一份可变数据，
既不校验冻结标记，也不保留历史台账，重复提交还会重复扣减。这里换成 SQLite 事务：
每次库存变动都是一次原子事务，台账只增不改，幂等键挡住重复提交。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.seed import SEED_ROWS

DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DB_DIR / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS spare (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    备件编号 TEXT UNIQUE NOT NULL,
    备件名称 TEXT NOT NULL,
    适用设备 TEXT NOT NULL DEFAULT '',
    结存数量 REAL NOT NULL DEFAULT 0,
    计量单位 TEXT NOT NULL DEFAULT '',
    存放库位 TEXT NOT NULL DEFAULT '',
    保管人员 TEXT NOT NULL DEFAULT '',
    备件状态 TEXT NOT NULL DEFAULT '正常可用',
    frozen INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS spare_stock_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    备件编号 TEXT NOT NULL,
    业务类型 TEXT NOT NULL,
    批次号 TEXT NOT NULL DEFAULT '',
    数量 REAL NOT NULL,
    结存后数量 REAL NOT NULL,
    库位 TEXT NOT NULL DEFAULT '',
    备注 TEXT NOT NULL DEFAULT '',
    幂等键 TEXT UNIQUE NOT NULL,
    发生时间 TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS spare_stocktake (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    盘点单号 TEXT UNIQUE NOT NULL,
    盘点日期 TEXT NOT NULL,
    盘点人 TEXT NOT NULL DEFAULT '',
    状态 TEXT NOT NULL DEFAULT '已完成',
    备注 TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS spare_stocktake_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    盘点单号 TEXT NOT NULL,
    备件编号 TEXT NOT NULL,
    账面数量 REAL NOT NULL,
    实盘数量 REAL NOT NULL,
    差异数量 REAL NOT NULL,
    库位 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS dispatch_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    调度单号 TEXT UNIQUE NOT NULL,
    来源模块 TEXT NOT NULL,
    备件编号 TEXT NOT NULL DEFAULT '',
    备件名称 TEXT NOT NULL DEFAULT '',
    整改结论 TEXT NOT NULL,
    调度内容 TEXT NOT NULL DEFAULT '',
    状态 TEXT NOT NULL DEFAULT '待调度',
    登记时间 TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    备注 TEXT NOT NULL DEFAULT ''
);
"""


def _connect() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """事务上下文：正常退出提交，异常回滚，保证库存变动要么全成要么全不成。"""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """建表并写入备件种子数据（仅首次空库时）。"""
    with transaction() as conn:
        conn.executescript(SCHEMA)
        count = conn.execute("SELECT COUNT(*) AS c FROM spare").fetchone()["c"]
        if count:
            return
        for row in SEED_ROWS.get("spare", []):
            status = str(row.get("备件状态") or "正常可用")
            conn.execute(
                """INSERT INTO spare (备件编号, 备件名称, 适用设备, 结存数量, 计量单位, 存放库位, 保管人员, 备件状态, frozen)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(row.get("备件编号") or ""),
                    str(row.get("备件名称") or ""),
                    str(row.get("适用设备") or ""),
                    float(row.get("结存数量", 0) or 0),
                    str(row.get("计量单位") or ""),
                    str(row.get("存放库位") or ""),
                    str(row.get("保管人员") or ""),
                    status,
                    1 if status == "已冻结" else 0,
                ),
            )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}
