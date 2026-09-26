"""集卡派车统一判定测试：三处入口必须得出同一份结论。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import truck_policy
from app.services.truck import TruckService
from app.store import store


def make_entry(
    status: str = truck_policy.STATUS_PENDING,
    *,
    driver: str = "张伟",
    fleet: str = "一队",
) -> dict:
    return {"id": 1, "status": status, "司机姓名": driver, "所属车队": fleet}


class PolicyTest(unittest.TestCase):
    def test_dispatch_requires_driver_on_duty(self) -> None:
        on_duty = truck_policy.evaluate(make_entry(), truck_policy.ACTION_DISPATCH)
        self.assertTrue(on_duty.allowed)

        off_duty = truck_policy.evaluate(
            make_entry(driver="陈晨", fleet="三队"), truck_policy.ACTION_DISPATCH
        )
        self.assertFalse(off_duty.allowed)
        self.assertEqual(off_duty.reason, truck_policy.MSG_DRIVER_OFF_DUTY)

    def test_return_compares_fleet(self) -> None:
        working = make_entry(status=truck_policy.STATUS_WORKING, driver="王强", fleet="二队")
        self.assertTrue(truck_policy.evaluate(working, truck_policy.ACTION_RETURN).allowed)

        working["所属车队"] = "一队"
        decision = truck_policy.evaluate(working, truck_policy.ACTION_RETURN)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, truck_policy.MSG_FLEET_MISMATCH)

    def test_missing_name_or_fleet_shares_one_message(self) -> None:
        for action in truck_policy.ACTION_ORDER:
            no_fleet = truck_policy.evaluate(
                make_entry(fleet=""), action
            )
            no_name = truck_policy.evaluate(
                make_entry(driver=""), action
            )
            self.assertFalse(no_fleet.allowed)
            self.assertFalse(no_name.allowed)
            self.assertEqual(no_fleet.reason, truck_policy.MSG_MISSING_INFO)
            self.assertEqual(no_name.reason, truck_policy.MSG_MISSING_INFO)
            self.assertEqual(no_fleet.reason, no_name.reason)

    def test_returned_cannot_be_pulled_back(self) -> None:
        returned = make_entry(status=truck_policy.STATUS_RETURNED)
        decision = truck_policy.evaluate(returned, truck_policy.ACTION_DISPATCH)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, truck_policy.MSG_ALREADY_RETURNED)
        # 已交回后取消同样不允许，终态只能保持。
        self.assertFalse(truck_policy.evaluate(returned, truck_policy.ACTION_CANCEL).allowed)

    def test_repeated_submit_is_idempotent(self) -> None:
        working = make_entry(status=truck_policy.STATUS_WORKING, driver="王强", fleet="二队")
        first = truck_policy.evaluate(working, truck_policy.ACTION_RETURN)
        second = truck_policy.evaluate(
            {**working, "status": truck_policy.STATUS_RETURNED},
            truck_policy.ACTION_RETURN,
        )
        self.assertTrue(first.allowed)
        self.assertFalse(first.repeated)
        self.assertTrue(second.allowed)
        self.assertTrue(second.repeated)
        self.assertEqual(second.target, truck_policy.STATUS_RETURNED)


class ServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        # 每次用独立仓库，避免种子数据顺序影响断言。
        from app.seed import SEED_ROWS

        store._tables = {"truck": [dict(row) for row in SEED_ROWS["truck"]]}
        self.service = TruckService()

    def test_list_and_detail_share_same_conclusion(self) -> None:
        items, total = self.service.list_entries(page=1, size=100)
        for item in items:
            detail = self.service.get_entry(int(item["id"]))
            self.assertEqual(detail["调度状态"], item["调度状态"])
            self.assertEqual(detail["可执行动作"], item["可执行动作"])
            # 列表给出的可执行动作与逐动作判定一致。
            self.assertEqual(
                detail["可执行动作"], truck_policy.allowed_actions(detail)
            )

    def test_repeated_submit_keeps_single_result(self) -> None:
        entry, message, ok = self.service.run_action(1, truck_policy.ACTION_DISPATCH)
        self.assertTrue(ok)
        self.assertEqual(entry["status"], truck_policy.STATUS_WORKING)

        again, again_message, again_ok = self.service.run_action(
            1, truck_policy.ACTION_DISPATCH
        )
        self.assertTrue(again_ok)
        self.assertIn("重复提交", again_message)
        # 状态与明细不被第二次提交改动。
        self.assertEqual(again["status"], truck_policy.STATUS_WORKING)

    def test_dispatched_then_returned_is_locked(self) -> None:
        self.service.run_action(1, truck_policy.ACTION_DISPATCH)
        entry, _, ok = self.service.run_action(1, truck_policy.ACTION_RETURN)
        # id=1 的张伟属一队，车队匹配，可以正常交回。
        self.assertTrue(ok)
        self.assertEqual(entry["status"], truck_policy.STATUS_RETURNED)

        pulled, reason, ok = self.service.run_action(
            1, truck_policy.ACTION_DISPATCH
        )
        self.assertFalse(ok)
        self.assertEqual(reason, truck_policy.MSG_ALREADY_RETURNED)
        self.assertEqual(pulled["status"], truck_policy.STATUS_RETURNED)

    def test_empty_fleet_seed_blocked_everywhere(self) -> None:
        # id=5 所属车队为空：三个动作都被同一句说明拦下。
        detail = self.service.get_entry(5)
        self.assertEqual(detail["可执行动作"], [])
        for action in truck_policy.ACTION_ORDER:
            _, reason, ok = self.service.run_action(5, action)
            self.assertFalse(ok)
            self.assertEqual(reason, truck_policy.MSG_MISSING_INFO)


if __name__ == "__main__":
    unittest.main()
