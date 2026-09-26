"""集卡调度业务规则：确认派车、确认返回、取消调度共用同一份判断。

三处动作的放行口径、缺字段说明、状态流转与重复提交处理都收在
``evaluate_action`` 一处，列表与明细再经 ``present_entry`` 统一呈现，
保证同一张调度单无论从哪里看、点哪个动作，结论都一样。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "truck"
REQUIRED_FIELDS = ["调度单号", "集卡牌号", "司机姓名"]
STATUS_ORDER = ["待派车", "作业中", "已返回", "已取消"]
ACTION_RULES: dict[str, str] = {
    "确认派车": "作业中",
    "确认返回": "已返回",
    "取消调度": "已取消",
}
# 每个动作允许出发的状态；三处动作共用一张流转表，不再各写一套。
ACTION_FROM_STATES: dict[str, set[str]] = {
    "确认派车": {"待派车"},
    "确认返回": {"作业中"},
    "取消调度": {"待派车", "作业中"},
}
# 终态不再允许任何动作把单子拉回去（含「已返回」不得重新派车）。
TERMINAL_STATES = {"已返回", "已取消"}

MISSING_INFO_MESSAGE = "司机姓名或所属车队为空，无法确认派车，请补全后再试"
MISSING_INFO_FIELDS = ("司机姓名", "所属车队")


def _is_blank(value: Any) -> bool:
    return not str(value or "").strip()


def present_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """对外呈现：以真实 status 为准回填「调度状态」，列表和明细走同一口径。"""
    view = dict(entry)
    view["调度状态"] = entry.get("status")
    return view


def evaluate_action(
    entry: dict[str, Any], action: str
) -> tuple[bool, str, str | None]:
    """三个动作共用的判断，返回 (是否放行, 说明, 目标状态)。

    放行才返回目标状态；拦下时目标状态为 None。重复提交到达同一状态时
    视为放行但不重复落结果，只回一句说明。
    """
    if action not in ACTION_RULES:
        return False, f"动作「{action}」不属于集卡调度可执行范围", None

    current = str(entry.get("status") or "")
    target = ACTION_RULES[action]

    # 重复提交优先识别：当前状态已是该动作的目标状态，只留这一条结果，
    # 不重复变更、也不当作错误，例如已交回后再次「确认返回」。
    # 但缺司机/车队属于前置资料不全，即便状态恰好相同也要先给同一句说明。
    missing_info = any(_is_blank(entry.get(field)) for field in MISSING_INFO_FIELDS)
    if not missing_info and current == target:
        return True, f"该调度单已是「{target}」，无需重复{action}", None

    # 三处动作共用同一条前置：司机、车队缺一即拦下，并给同一句说明。
    if missing_info:
        return False, MISSING_INFO_MESSAGE, None

    # 其余终态（如「已取消」）以及「已返回」对非返回动作，都不能再拉回作业。
    if current in TERMINAL_STATES:
        return False, f"该调度单状态为「{current}」，不能再执行「{action}」", None

    if current not in ACTION_FROM_STATES[action]:
        return False, f"当前状态为「{current}」，不能执行「{action}」", None

    return True, f"集卡已{action}", target


class TruckService:
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
        page_rows = rows[start:start + size]
        return [present_entry(row) for row in page_rows], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return present_entry(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if _is_blank(values.get(field))]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 车队可在登记后补录；未补录前任何流转动作都会被共用判断拦下。
        entry["所属车队"] = str(values.get("所属车队") or "").strip()
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return present_entry(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"集卡 {entry_id} 不存在或已归档"
        allowed, message, target = evaluate_action(entry, action)
        if not allowed:
            return None, message
        if target is not None:
            entry["status"] = target
            entry["pending"] = target not in TERMINAL_STATES
            entry["abnormal"] = False
        return present_entry(entry), message
