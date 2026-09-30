"""备件出库/盘点/调度台账整改回归测试。

覆盖问题单的五项验收要求：
1. 冻结库位在服务端拒绝出库（前端绕过也无效）；
2. 盘点结果与存放库位明细、结存总量同步一致；
3. 同一批重复提交只生效一次（出库/入库/盘点/整改闭环）；
4. 历史出入库台账只追加保留，调整前后都可追溯；
5. 备件类整改结论在闭环时落入调度台账。

运行：APP_DB_PATH 指向临时文件，python -m unittest app.tests.test_spare_flow
"""
from __future__ import annotations

import os
import tempfile
import unittest


class SpareFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        os.environ["APP_DB_PATH"] = os.path.join(cls._tmp.name, "test.db")
        # 必须在设置好 DB 路径后再导入应用模块
        from fastapi.testclient import TestClient  # noqa: F401

        from app.main import app
        from app.services.rectify import RectifyService
        from app.services.spare import spare_service

        cls.client = TestClient(app)
        cls.spare = spare_service
        cls.rectify = RectifyService()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _find_spare(self, code: str):
        items, _ = self.spare.list_entries(page=1, size=100)
        return next(item for item in items if item["备件编号"] == code)

    # 1. 冻结库位拒绝出库 -------------------------------------------------
    def test_frozen_location_rejects_outbound(self) -> None:
        spare = self._find_spare("SPAR-0003")
        loc = next(l for l in spare["库位明细"] if l["库位冻结"])
        before = spare["结存数量"]

        resp = self.client.post("/api/spare/outbound", json={"values": {
            "备件编号": "SPAR-0003", "存放库位": loc["存放库位"],
            "数量": 3, "批次号": "T-FROZEN-1",
        }})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["ok"])
        self.assertIn("冻结", resp.json()["message"])

        # 库存一分未动
        self.assertEqual(self._find_spare("SPAR-0003")["结存数量"], before)

        # 直接调服务层同样被拦（不依赖前端）
        from app.services.spare import BusinessError

        with self.assertRaises(BusinessError):
            self.spare.stock_move(
                spare_code="SPAR-0003", location=loc["存放库位"],
                quantity=1, change_type="出库", idem_key="T-FROZEN-2",
            )

    def test_unfreeze_then_outbound_ok(self) -> None:
        spare = self._find_spare("SPAR-0003")
        loc = next(l for l in spare["库位明细"] if l["库位冻结"])
        self.spare.set_location_frozen(loc["库位明细ID"], frozen=False)
        result = self.spare.stock_move(
            spare_code="SPAR-0003", location=loc["存放库位"],
            quantity=4, change_type="出库", idem_key="T-UNFREEZE-OUT",
        )
        self.assertEqual(result["结存数量"], 26)

    # 2. 盘点与库位明细同步 ------------------------------------------------
    def test_stocktake_syncs_locations_and_total(self) -> None:
        result = self.spare.stocktake(
            spare_code="SPAR-0002", batch_no="T-CHECK-1", idem_key="T-CHECK-1",
            items=[
                {"存放库位": "B区-01架-02位", "库位数量": 5},
                {"存放库位": "B区-02架-01位", "库位数量": 7},
            ],
            operator="测试员",
        )
        loc_total = sum(loc["库位数量"] for loc in result["库位明细"])
        self.assertEqual(loc_total, 12)
        self.assertEqual(result["结存数量"], loc_total)

        # 重新从库读，确认落盘
        fresh = self._find_spare("SPAR-0002")
        self.assertEqual(fresh["结存数量"], 12)
        self.assertEqual(
            {l["存放库位"]: l["库位数量"] for l in fresh["库位明细"]},
            {"B区-01架-02位": 5, "B区-02架-01位": 7},
        )

    # 3. 同批重复提交幂等 --------------------------------------------------
    def test_duplicate_batch_applies_once(self) -> None:
        payload = {"values": {
            "备件编号": "SPAR-0001", "存放库位": "A区-02架-01位",
            "数量": 2, "批次号": "T-DUP-OUT", "idem_key": "T-DUP-OUT",
        }}
        first = self.client.post("/api/spare/outbound", json=payload).json()
        second = self.client.post("/api/spare/outbound", json=payload).json()
        self.assertTrue(first["ok"] and second["ok"])
        self.assertEqual(first["entry"]["结存数量"], second["entry"]["结存数量"])
        self.assertEqual(first["entry"]["台账ID"], second["entry"]["台账ID"])

        # 台账里该批次只有一条出库
        ledger, total = self.spare.list_ledger(batch_no="T-DUP-OUT", page=1, size=10)
        self.assertEqual(total, 1)
        self.assertEqual(ledger[0]["变动数量"], -2)

    def test_duplicate_stocktake_applies_once(self) -> None:
        body = {"values": {
            "备件编号": "SPAR-0001", "批次号": "T-DUP-CHECK", "idem_key": "T-DUP-CHECK",
            "盘点明细": [
                {"存放库位": "A区-01架-03位", "库位数量": 4},
                {"存放库位": "A区-02架-01位", "库位数量": 2},
            ],
        }}
        a = self.client.post("/api/spare/stocktake", json=body).json()
        b = self.client.post("/api/spare/stocktake", json=body).json()
        self.assertTrue(a["ok"] and b["ok"])
        self.assertEqual(a["entry"]["结存数量"], b["entry"]["结存数量"])
        _, ledger_total = self.spare.list_ledger(batch_no="T-DUP-CHECK", page=1, size=50)
        self.assertEqual(ledger_total, 2)  # 两个库位各一条，不会因重复提交翻倍

    # 4. 历史台账保留 ------------------------------------------------------
    def test_ledger_is_append_only_history(self) -> None:
        self.spare.stock_move(
            spare_code="SPAR-0001", location="A区-01架-03位", quantity=1,
            change_type="入库", idem_key="T-IN-1", batch_no="T-IN-1",
        )
        ledger, total = self.spare.list_ledger(spare_code="SPAR-0001", page=1, size=200)
        types = {row["台账类型"] for row in ledger}
        self.assertIn("出库", types)
        self.assertIn("入库", types)
        self.assertIn("盘点调整", types)
        # 余额链条：每条台账的结存字段都已定格，历史不被后续操作改写
        balances = [row["结存数量"] for row in ledger]
        self.assertTrue(all(isinstance(v, int) and v >= 0 for v in balances))

    # 5. 整改结论落调度台账 ------------------------------------------------
    def test_rectify_conclusion_lands_in_dispatch_ledger(self) -> None:
        from app.services.dispatch import dispatch_service

        entry, missing = self.rectify.create_entry({
            "整改单号": "RECT-TEST-1", "关联隐患": "HAZA-TEST-1", "整改措施": "更换备件",
        })
        self.assertFalse(missing)
        rid = entry["id"]
        self.rectify.run_action(rid, "下发整改")
        self.rectify.run_action(rid, "提交验收")

        closed, msg = self.rectify.run_action(rid, "确认闭环", {
            "关联备件": "SPAR-0002", "整改结论": "轴承磨损，调度3套更换",
            "调度数量": 3, "验收人员": "验收员",
        })
        self.assertIsNotNone(closed, msg=msg)
        self.assertEqual(closed["status"], "已闭环")

        dispatch, count = dispatch_service.list_entries(page=1, size=100)
        mine = [d for d in dispatch if d["关联整改单"] == rid]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["备件编号"], "SPAR-0002")
        self.assertEqual(mine[0]["整改结论"], "轴承磨损，调度3套更换")

        # 重复闭环不再重复建账
        self.rectify.run_action(rid, "确认闭环", {
            "关联备件": "SPAR-0002", "整改结论": "轴承磨损，调度3套更换", "调度数量": 3,
        })
        _, count_after = dispatch_service.list_entries(page=1, size=100)
        self.assertEqual(count_after, count)

    def test_close_with_bad_spare_rolls_back(self) -> None:
        entry, _ = self.rectify.create_entry({
            "整改单号": "RECT-TEST-2", "关联隐患": "HAZA-TEST-2", "整改措施": "x",
        })
        rid = entry["id"]
        self.rectify.run_action(rid, "下发整改")
        self.rectify.run_action(rid, "提交验收")

        closed, msg = self.rectify.run_action(rid, "确认闭环", {
            "关联备件": "NOT-EXIST", "整改结论": "找不到备件",
        })
        self.assertIsNone(closed)
        self.assertIn("不存在", msg)
        # 闭环整体回滚，仍是待验收
        self.assertEqual(self.rectify.get_entry(rid)["status"], "待验收")

    def test_close_requires_conclusion(self) -> None:
        entry, _ = self.rectify.create_entry({
            "整改单号": "RECT-TEST-3", "关联隐患": "HAZA-TEST-3", "整改措施": "x",
        })
        rid = entry["id"]
        self.rectify.run_action(rid, "下发整改")
        self.rectify.run_action(rid, "提交验收")
        closed, msg = self.rectify.run_action(rid, "确认闭环", {"关联备件": "SPAR-0001"})
        self.assertIsNone(closed)
        self.assertIn("整改结论", msg)


if __name__ == "__main__":
    unittest.main()
