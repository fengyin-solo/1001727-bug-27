"""SQLite 持久化层。

之前的数据全部挂在进程内存里：服务一重启调整结果就丢了，刷新页面自然还看到旧数字。
这里用标准库 sqlite3 建一个文件库，所有写操作都在同一把锁里串行提交，
既保证落库，也保证「同一批重复提交只生效一次」的幂等判断和业务扣减处于同一事务。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Callable, Iterable, TypeVar

from app.config import settings

T = TypeVar("T")


def now_text() -> str:
    """台账时间戳：精确到秒，便于人读，也便于按批次排序。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    module      TEXT NOT NULL,
    entry_id    INTEGER NOT NULL,
    data        TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (module, entry_id)
);

CREATE TABLE IF NOT EXISTS spare (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    spare_code    TEXT NOT NULL UNIQUE,
    spare_name    TEXT NOT NULL,
    fit_device    TEXT NOT NULL DEFAULT '',
    unit          TEXT NOT NULL DEFAULT '',
    keeper        TEXT NOT NULL DEFAULT '',
    safety_stock  INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS spare_location (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    spare_id    INTEGER NOT NULL REFERENCES spare(id),
    location    TEXT NOT NULL,
    quantity    INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    frozen      INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    UNIQUE (spare_id, location)
);

CREATE TABLE IF NOT EXISTS spare_ledger (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    spare_id      INTEGER NOT NULL,
    spare_code    TEXT NOT NULL,
    location      TEXT NOT NULL,
    change_type   TEXT NOT NULL,
    change_qty    INTEGER NOT NULL,
    balance_qty   INTEGER NOT NULL,
    batch_no      TEXT NOT NULL DEFAULT '',
    idem_key      TEXT NOT NULL UNIQUE,
    operator      TEXT NOT NULL DEFAULT '',
    remark        TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dispatch_ledger (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    dispatch_no     TEXT NOT NULL UNIQUE,
    source          TEXT NOT NULL,
    rectify_id      INTEGER,
    spare_code      TEXT NOT NULL DEFAULT '',
    spare_name      TEXT NOT NULL DEFAULT '',
    content         TEXT NOT NULL DEFAULT '',
    conclusion      TEXT NOT NULL DEFAULT '',
    dispatch_qty    INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT '待调度',
    operator        TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idem_result (
    idem_key    TEXT PRIMARY KEY,
    result_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


class Database:
    """线程安全的 SQLite 封装：写事务串行执行，读操作开短连接。"""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or settings.db_path
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute("PRAGMA journal_mode = WAL")

    # ---------- 通用读写 ----------
    def write(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """在全局写锁里执行一个事务；fn 抛错则整体回滚。"""
        with self._lock, self._connect() as conn:
            return fn(conn)

    def read_all(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return list(conn.execute(sql, tuple(params)).fetchall())

    def read_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(sql, tuple(params)).fetchone()

    # ---------- 幂等 ----------
    def idem_lookup(self, conn: sqlite3.Connection, idem_key: str | None) -> dict[str, Any] | None:
        """命中已处理过的提交键时，直接回放上次结果，保证重复提交只生效一次。"""
        if not idem_key:
            return None
        row = conn.execute(
            "SELECT result_json FROM idem_result WHERE idem_key = ?", (idem_key,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["result_json"])

    def idem_store(
        self, conn: sqlite3.Connection, idem_key: str | None, result: dict[str, Any]
    ) -> None:
        if not idem_key:
            return
        conn.execute(
            "INSERT OR IGNORE INTO idem_result (idem_key, result_json, created_at) VALUES (?, ?, ?)",
            (idem_key, json.dumps(result, ensure_ascii=False), now_text()),
        )


db = Database()
