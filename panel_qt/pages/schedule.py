# -*- coding: utf-8 -*-
"""定时消息：固定时间群发 + 随机时间群发"""

from PySide6.QtWidgets import (
    QGroupBox, QLabel, QVBoxLayout, QWidget, QCheckBox,
)

from . import register
from .common import RuleTable

REPEAT = ["daily", "weekly", "monthly", "custom", "once"]


def _ints(xs):
    out = []
    for x in xs:
        try:
            out.append(int(x))
        except Exception:
            pass
    return out


@register("schedule")
def build(page, mw):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)

    # ---------- 固定时间 ----------
    g1 = QGroupBox("定时消息（固定时间）")
    g1l = QVBoxLayout(g1)
    g1l.setContentsMargins(14, 16, 14, 16)
    ck1 = QCheckBox("启用定时消息")
    g1l.addWidget(ck1)
    hint = QLabel("weekly 时「星期」填 1-7（1=周一）；monthly 时「日期」填几号；"
                  "custom 时「日期」填 2026-03-20 这样的完整日期，多个用逗号分隔。")
    hint.setObjectName("groupDesc")
    hint.setWordWrap(True)
    g1l.addWidget(hint)

    t1 = RuleTable(
        columns=[
            {"key": "targets", "label": "发送目标", "type": "list", "placeholder": "群名/昵称"},
            {"key": "time", "label": "时间", "type": "text", "default": "08:00"},
            {"key": "repeat_type", "label": "重复", "type": "select",
             "options": REPEAT, "default": "daily"},
            {"key": "weekdays", "label": "星期", "type": "list"},
            {"key": "dates", "label": "日期", "type": "list"},
            {"key": "msgs", "label": "消息内容（一行一条，随机选发）", "type": "lines"},
        ],
        defaults={"targets": [], "time": "08:00", "repeat_type": "daily",
                  "weekdays": [], "dates": [], "msgs": [], "enabled": True},
    )
    g1l.addWidget(t1)
    lay.addWidget(g1, 1)

    # ---------- 随机时间 ----------
    g2 = QGroupBox("随机定时消息（时间段内随机触发）")
    g2l = QVBoxLayout(g2)
    g2l.setContentsMargins(14, 16, 14, 16)
    ck2 = QCheckBox("启用随机定时消息")
    g2l.addWidget(ck2)
    hint2 = QLabel("每日模式每天必发；每周/每月模式会在周期开始时随机抽取「随机天数」天来发送。")
    hint2.setObjectName("groupDesc")
    hint2.setWordWrap(True)
    g2l.addWidget(hint2)

    t2 = RuleTable(
        columns=[
            {"key": "targets", "label": "发送目标", "type": "list"},
            {"key": "repeat_type", "label": "周期", "type": "select",
             "options": ["daily", "weekly", "monthly"], "default": "daily"},
            {"key": "random_days_count", "label": "随机天数", "type": "int",
             "default": 1, "min": 1, "max": 31},
            {"key": "time_start", "label": "开始时间", "type": "text", "default": "09:00"},
            {"key": "time_end", "label": "结束时间", "type": "text", "default": "21:00"},
            {"key": "msgs", "label": "消息内容（一行一条）", "type": "lines"},
        ],
        defaults={"targets": [], "repeat_type": "daily", "random_days_count": 1,
                  "time_start": "09:00", "time_end": "21:00", "msgs": [], "enabled": True},
    )
    g2l.addWidget(t2)
    lay.addWidget(g2, 1)

    def load(cfg):
        ck1.setChecked(bool(cfg.get("scheduled_msg_switch", False)))
        ck2.setChecked(bool(cfg.get("random_msg_switch", False)))
        t1.load(cfg.get("scheduled_msg_list", []) or [])
        t2.load(cfg.get("random_msg_list", []) or [])

    def collect():
        fixed = t1.collect()
        for task in fixed:
            task["weekdays"] = _ints(task.get("weekdays", []))
            if task.get("repeat_type") == "monthly":
                task["dates"] = _ints(task.get("dates", []))
        return {
            "scheduled_msg_switch": ck1.isChecked(),
            "scheduled_msg_list": fixed,
            "random_msg_switch": ck2.isChecked(),
            "random_msg_list": t2.collect(),
        }

    w.load = load
    w.collect = collect
    return w
