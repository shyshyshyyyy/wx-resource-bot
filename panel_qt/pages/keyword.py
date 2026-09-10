# -*- coding: utf-8 -*-
"""关键词回复"""

from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QGroupBox, QVBoxLayout, QWidget, QLabel,
)

from . import register
from ..widgets import DictEditor


@register("keyword")
def build(page, mw):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)

    g1 = QGroupBox("开关")
    gl = QGridLayout(g1)
    gl.setContentsMargins(14, 16, 14, 16)
    gl.setVerticalSpacing(10)
    ck_chat = QCheckBox("私聊关键词回复")
    ck_group = QCheckBox("群聊关键词回复")
    ck_at_only = QCheckBox("群聊仅被 @ 时触发")
    ck_quote = QCheckBox("引用原消息回复")
    ck_at_sender = QCheckBox("群聊回复时 @ 发言人")
    gl.addWidget(ck_chat, 0, 0)
    gl.addWidget(ck_group, 0, 1)
    gl.addWidget(ck_at_only, 1, 0)
    gl.addWidget(ck_quote, 1, 1)
    gl.addWidget(ck_at_sender, 2, 0)
    gl.setColumnStretch(2, 1)
    lay.addWidget(g1)

    g2 = QGroupBox("关键词 → 回复内容")
    g2l = QVBoxLayout(g2)
    g2l.setContentsMargins(14, 16, 14, 16)
    hint = QLabel("消息内容包含关键词即触发。多个同义词可用竖线分隔，例如：价格|多少钱|怎么卖")
    hint.setObjectName("groupDesc")
    hint.setWordWrap(True)
    g2l.addWidget(hint)
    editor = DictEditor("关键词", "回复内容")
    g2l.addWidget(editor)
    lay.addWidget(g2, 1)

    def load(cfg):
        ck_chat.setChecked(bool(cfg.get("chat_keyword_switch", False)))
        ck_group.setChecked(bool(cfg.get("group_keyword_switch", False)))
        ck_at_only.setChecked(bool(cfg.get("group_keyword_at_only", False)))
        ck_quote.setChecked(bool(cfg.get("keyword_reply_quote", False)))
        ck_at_sender.setChecked(bool(cfg.get("group_keyword_reply_at_msg", False)))
        editor.load(cfg.get("keyword_dict", {}) or {})

    def collect():
        return {
            "chat_keyword_switch": ck_chat.isChecked(),
            "group_keyword_switch": ck_group.isChecked(),
            "group_keyword_at_only": ck_at_only.isChecked(),
            "keyword_reply_quote": ck_quote.isChecked(),
            "group_keyword_reply_at_msg": ck_at_sender.isChecked(),
            "keyword_dict": editor.collect(),
        }

    w.load = load
    w.collect = collect
    return w
