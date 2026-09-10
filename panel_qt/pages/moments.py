# -*- coding: utf-8 -*-
"""朋友圈：定时发布、随机发布、随机点赞"""

from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QGroupBox, QLabel, QSpinBox, QVBoxLayout, QWidget,
)

from . import register
from .common import RuleTable
from .schedule import _ints

REPEAT = ["daily", "weekly", "monthly", "custom", "once"]


@register("moments")
def build(page, mw):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)

    tip = QLabel("朋友圈相关能力需要 wxautox4 内核并激活后可用；未激活时这些任务不会执行。")
    tip.setObjectName("pageDesc")
    tip.setWordWrap(True)
    lay.addWidget(tip)

    # ---------- 定时发布 ----------
    g1 = QGroupBox("定时朋友圈")
    g1l = QVBoxLayout(g1)
    g1l.setContentsMargins(14, 16, 14, 16)
    ck1 = QCheckBox("启用定时朋友圈")
    g1l.addWidget(ck1)
    t1 = RuleTable(
        columns=[
            {"key": "time", "label": "时间", "type": "text", "default": "09:00"},
            {"key": "repeat_type", "label": "重复", "type": "select",
             "options": REPEAT, "default": "daily"},
            {"key": "weekdays", "label": "星期", "type": "list"},
            {"key": "dates", "label": "日期", "type": "list"},
            {"key": "text", "label": "文字内容", "type": "lines"},
            {"key": "images", "label": "图片路径（一行一个，最多9张）", "type": "lines"},
            {"key": "privacy", "label": "可见范围", "type": "select",
             "options": ["public", "whitelist", "blacklist"], "default": "public"},
            {"key": "tags", "label": "标签", "type": "list"},
        ],
        defaults={"time": "09:00", "repeat_type": "daily", "weekdays": [], "dates": [],
                  "text": "", "images": [], "privacy": "public", "tags": [], "enabled": True},
    )
    g1l.addWidget(t1)
    lay.addWidget(g1, 1)

    # ---------- 随机发布 ----------
    g2 = QGroupBox("随机定时朋友圈")
    g2l = QVBoxLayout(g2)
    g2l.setContentsMargins(14, 16, 14, 16)
    ck2 = QCheckBox("启用随机定时朋友圈")
    g2l.addWidget(ck2)
    t2 = RuleTable(
        columns=[
            {"key": "repeat_type", "label": "周期", "type": "select",
             "options": ["daily", "weekly", "monthly"], "default": "daily"},
            {"key": "random_days_count", "label": "随机天数", "type": "int",
             "default": 1, "min": 1, "max": 31},
            {"key": "time_start", "label": "开始时间", "type": "text", "default": "09:00"},
            {"key": "time_end", "label": "结束时间", "type": "text", "default": "21:00"},
            {"key": "text", "label": "文字内容", "type": "lines"},
            {"key": "images", "label": "图片路径（一行一个）", "type": "lines"},
            {"key": "privacy", "label": "可见范围", "type": "select",
             "options": ["public", "whitelist", "blacklist"], "default": "public"},
            {"key": "tags", "label": "标签", "type": "list"},
        ],
        defaults={"repeat_type": "daily", "random_days_count": 1,
                  "time_start": "09:00", "time_end": "21:00", "text": "",
                  "images": [], "privacy": "public", "tags": [], "enabled": True},
    )
    g2l.addWidget(t2)
    lay.addWidget(g2, 1)

    # ---------- 随机点赞 ----------
    g3 = QGroupBox("随机朋友圈点赞")
    g3l = QGridLayout(g3)
    g3l.setContentsMargins(14, 16, 14, 16)
    ck3 = QCheckBox("启用随机点赞")
    sp_min = QSpinBox()
    sp_min.setRange(1, 100000)
    sp_max = QSpinBox()
    sp_max.setRange(1, 100000)
    g3l.addWidget(ck3, 0, 0)
    g3l.addWidget(QLabel("最小间隔（分钟）"), 0, 1)
    g3l.addWidget(sp_min, 0, 2)
    g3l.addWidget(QLabel("最大间隔（分钟）"), 0, 3)
    g3l.addWidget(sp_max, 0, 4)
    g3l.setColumnStretch(5, 1)
    lay.addWidget(g3)

    def load(cfg):
        ck1.setChecked(bool(cfg.get("scheduled_moments_switch", False)))
        ck2.setChecked(bool(cfg.get("random_moments_switch", False)))
        ck3.setChecked(bool(cfg.get("moments_like_switch", False)))
        sp_min.setValue(int(cfg.get("moments_like_min", 60) or 60))
        sp_max.setValue(int(cfg.get("moments_like_max", 120) or 120))
        t1.load(cfg.get("scheduled_moments_list", []) or [])
        t2.load(cfg.get("random_moments_list", []) or [])

    def collect():
        fixed = t1.collect()
        for task in fixed:
            task["weekdays"] = _ints(task.get("weekdays", []))
            if task.get("repeat_type") == "monthly":
                task["dates"] = _ints(task.get("dates", []))
            # text 用 lines 存成了 list，底座需要字符串
            if isinstance(task.get("text"), list):
                task["text"] = "\n".join(task["text"])
        rnd = t2.collect()
        for task in rnd:
            if isinstance(task.get("text"), list):
                task["text"] = "\n".join(task["text"])
        return {
            "scheduled_moments_switch": ck1.isChecked(),
            "scheduled_moments_list": fixed,
            "random_moments_switch": ck2.isChecked(),
            "random_moments_list": rnd,
            "moments_like_switch": ck3.isChecked(),
            "moments_like_min": min(sp_min.value(), sp_max.value()),
            "moments_like_max": max(sp_min.value(), sp_max.value()),
        }

    w.load = load
    w.collect = collect
    return w
