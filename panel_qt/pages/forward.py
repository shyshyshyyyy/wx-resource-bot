# -*- coding: utf-8 -*-
"""自定义转发：把指定会话的消息转发到目标会话"""

from PySide6.QtWidgets import (
    QGroupBox, QLabel, QVBoxLayout, QWidget, QCheckBox,
)

from . import register
from .common import RuleTable


@register("forward")
def build(page, mw):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)

    g1 = QGroupBox("总开关")
    g1l = QVBoxLayout(g1)
    g1l.setContentsMargins(14, 16, 14, 16)
    ck = QCheckBox("启用自定义转发")
    g1l.addWidget(ck)
    lay.addWidget(g1)

    g2 = QGroupBox("转发规则")
    g2l = QVBoxLayout(g2)
    g2l.setContentsMargins(14, 16, 14, 16)
    hint = QLabel("来源/目标/关键词/发送人 多个之间用英文逗号分隔。"
                  "type 决定匹配方式：all=全部转发，keyword=命中关键词，sender=指定发送人。")
    hint.setObjectName("groupDesc")
    hint.setWordWrap(True)
    g2l.addWidget(hint)

    tbl = RuleTable(
        columns=[
            {"key": "sources", "label": "来源会话", "type": "list",
             "placeholder": "群名或好友昵称"},
            {"key": "all_sources", "label": "全部来源", "type": "switch", "stretch": False},
            {"key": "type", "label": "匹配方式", "type": "select",
             "options": ["all", "keyword", "sender"], "default": "all"},
            {"key": "keywords", "label": "关键词", "type": "list"},
            {"key": "senders", "label": "发送人", "type": "list"},
            {"key": "targets", "label": "转发目标", "type": "list"},
            {"key": "forward_with_source", "label": "附带来源", "type": "switch", "stretch": False},
        ],
        defaults={"sources": [], "all_sources": False, "type": "all",
                  "keywords": [], "senders": [], "targets": [],
                  "forward_with_source": False, "enabled": True},
    )
    g2l.addWidget(tbl)
    lay.addWidget(g2, 1)

    def load(cfg):
        ck.setChecked(bool(cfg.get("custom_forward_switch", False)))
        tbl.load(cfg.get("custom_forward_list", []) or [])

    def collect():
        return {
            "custom_forward_switch": ck.isChecked(),
            "custom_forward_list": tbl.collect(),
        }

    w.load = load
    w.collect = collect
    return w
