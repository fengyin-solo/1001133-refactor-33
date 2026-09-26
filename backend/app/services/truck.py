"""集卡调度业务规则：状态流转、字段校验与筛选口径都收在这里。

确认派车、确认返回、取消调度三处的判定统一委托给 ``truck_policy``，
列表与详情也共用同一份序列化结果，避免两边填得一样却结论两样。
"""
from __future__ import annotations

from typing import Any

from app.services import truck_policy
from app.store import store

MODULE = "truck"
REQUIRED_FIELDS = ["调度单号", "集卡牌号", "司机姓名"]
# 所属车队是动作判定的必要信息；登记时允许先空着，执行动作会被统一拦下。
OPTIONAL_FIELDS = ["作业任务", "派车时间", "返回时间", "所属车队"]


class TruckService:
    def _present(self, entry: dict[str, Any]) -> dict[str, Any]:
        """列表行与详情共用的呈现：调度状态取权威状态字段，并附上统一判定出的可执行动作。"""
        view = dict(entry)
        view["调度状态"] = entry.get("status")
        view["可执行动作"] = truck_policy.allowed_actions(entry)
        return view

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
            rows = [row for row in rows if keyword in str(row.get("调度单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._present(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._present(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in [*REQUIRED_FIELDS, *OPTIONAL_FIELDS]})
        entry["status"] = truck_policy.STATUS_PENDING
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._present(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str, bool]:
        """执行动作，返回（最新明细、说明、是否成功）。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"集卡 {entry_id} 不存在或已归档", False

        decision = truck_policy.evaluate(entry, action)
        if not decision.allowed:
            return self._present(entry), decision.reason, False

        assert decision.target is not None
        if not decision.repeated:
            entry["status"] = decision.target
            entry["pending"] = decision.target not in (
                truck_policy.STATUS_RETURNED,
                truck_policy.STATUS_CANCELLED,
            )
            entry["abnormal"] = False
        # 重复提交只返回同一条结果，不改动数据。
        return self._present(entry), decision.reason, True
