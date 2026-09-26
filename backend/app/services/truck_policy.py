"""集卡派车统一判定：确认派车、确认返回、取消调度三处共用一份结论。

接口执行动作、列表渲染动作按钮、详情渲染动作按钮都走 ``evaluate``，
保证同一张调度单无论从哪个入口提交，得到的允许/拦结论与说明完全一致。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 调度状态
STATUS_PENDING = "待派车"
STATUS_WORKING = "作业中"
STATUS_RETURNED = "已返回"
STATUS_CANCELLED = "已取消"

# 可执行动作
ACTION_DISPATCH = "确认派车"
ACTION_RETURN = "确认返回"
ACTION_CANCEL = "取消调度"

ACTION_ORDER = (ACTION_DISPATCH, ACTION_RETURN, ACTION_CANCEL)

# 动作对应的目标状态
ACTION_TARGETS: dict[str, str] = {
    ACTION_DISPATCH: STATUS_WORKING,
    ACTION_RETURN: STATUS_RETURNED,
    ACTION_CANCEL: STATUS_CANCELLED,
}

# 各动作允许的前置状态：确认派车只能从待派车发出，确认返回只能在作业中，
# 取消调度在派车前与作业中都可以；已返回、已取消均为终态。
ACTION_SOURCE_STATUSES: dict[str, set[str]] = {
    ACTION_DISPATCH: {STATUS_PENDING},
    ACTION_RETURN: {STATUS_WORKING},
    ACTION_CANCEL: {STATUS_PENDING, STATUS_WORKING},
}

# 司机名册：登记在册即视为在岗，同时给出司机所属车队，供确认返回核对。
# 未列入名册（例如休假）的司机按不在岗处理。
DRIVER_ROSTER: dict[str, dict[str, str]] = {
    "张伟": {"fleet": "一队"},
    "李娜": {"fleet": "一队"},
    "王强": {"fleet": "二队"},
    "赵敏": {"fleet": "二队"},
}

# 统一说明文案：三个动作、列表与详情共用同一句话。
MSG_MISSING_INFO = "司机姓名或所属车队为空，无法执行该调度动作"
MSG_DRIVER_OFF_DUTY = "司机当前不在岗，不能确认派车"
MSG_FLEET_MISMATCH = "所属车队与司机所在车队不一致，不能确认返回"
MSG_ALREADY_RETURNED = "调度单已交回，不能再拉回作业"


@dataclass(frozen=True)
class Decision:
    """一次判定的唯一结论。"""

    allowed: bool
    reason: str
    target: str | None = None
    repeated: bool = False


def _is_blank(value: Any) -> bool:
    return not str(value or "").strip()


def evaluate(entry: dict[str, Any], action: str) -> Decision:
    """对一张调度单评估某个动作是否可执行，所有入口共用此函数。"""
    if action not in ACTION_TARGETS:
        return Decision(False, f"动作「{action}」不属于集卡调度可执行范围")

    status = str(entry.get("status") or "")
    target = ACTION_TARGETS[action]

    # 1. 司机姓名或所属车队为空：三个动作给出同一句说明。
    if _is_blank(entry.get("司机姓名")) or _is_blank(entry.get("所属车队")):
        return Decision(False, MSG_MISSING_INFO)

    # 2. 重复提交：已经处于目标状态时只留一条结果，不再重复执行。
    if status == target:
        return Decision(True, f"调度单已是「{target}」状态，重复提交未重复执行", target, repeated=True)

    # 3. 状态流转口径（含终态保护）：已交回的不能再被拉回作业中。
    if status not in ACTION_SOURCE_STATUSES[action]:
        if action == ACTION_DISPATCH and status == STATUS_RETURNED:
            return Decision(False, MSG_ALREADY_RETURNED)
        return Decision(False, f"当前状态「{status}」不允许执行{action}")

    # 4. 动作本身的业务条件：派车看在岗，返回比车队。
    if action == ACTION_DISPATCH:
        driver = DRIVER_ROSTER.get(str(entry.get("司机姓名")).strip())
        if driver is None:
            return Decision(False, MSG_DRIVER_OFF_DUTY)
    elif action == ACTION_RETURN:
        driver = DRIVER_ROSTER.get(str(entry.get("司机姓名")).strip())
        if driver is None or driver["fleet"] != str(entry.get("所属车队")).strip():
            return Decision(False, MSG_FLEET_MISMATCH)

    return Decision(True, f"集卡已{action}", target)


def allowed_actions(entry: dict[str, Any]) -> list[str]:
    """列表与详情据此渲染动作按钮，结论与真正提交时完全一致。"""
    actions: list[str] = []
    for action in ACTION_ORDER:
        decision = evaluate(entry, action)
        if decision.allowed and not decision.repeated:
            actions.append(action)
    return actions
