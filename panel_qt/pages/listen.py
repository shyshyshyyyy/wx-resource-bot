# -*- coding: utf-8 -*-
"""私聊监听：模式、名单、按人绑定接口与提示词"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import register
from ..widgets import ListEditor, warn


@register("listen")
def build(page, mw):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)

    # ---------- 模式 ----------
    g1 = QGroupBox("监听模式")
    gl = QGridLayout(g1)
    gl.setContentsMargins(14, 16, 14, 16)
    gl.setVerticalSpacing(10)

    combo = QComboBox()
    combo.addItem("白名单模式（只处理名单内的人）", False)
    combo.addItem("全局模式（处理所有人，名单内的人反而屏蔽）", True)
    combo.setMinimumWidth(360)

    ck_mute = QCheckBox("过滤免打扰会话")
    ck_only = QCheckBox("私聊只监听不回复")

    gl.addWidget(QLabel("模式"), 0, 0)
    gl.addWidget(combo, 0, 1, 1, 2)
    gl.addWidget(ck_mute, 1, 1)
    gl.addWidget(ck_only, 1, 2)
    gl.setColumnStretch(3, 1)
    lay.addWidget(g1)

    # ---------- 名单 ----------
    g2 = QGroupBox("好友名单")
    g2l = QVBoxLayout(g2)
    g2l.setContentsMargins(14, 16, 14, 16)
    hint = QLabel("白名单模式下=要处理的人；全局模式下=要屏蔽的人。填微信昵称，一行一个。")
    hint.setObjectName("groupDesc")
    hint.setWordWrap(True)
    g2l.addWidget(hint)
    lst = ListEditor("微信昵称")
    g2l.addWidget(lst)
    lay.addWidget(g2)

    # ---------- 按人绑定 ----------
    g3 = QGroupBox("按好友单独指定（留空=使用全局默认）")
    g3l = QVBoxLayout(g3)
    g3l.setContentsMargins(14, 16, 14, 16)
    tbl = QTableWidget(0, 4)
    tbl.setHorizontalHeaderLabels(["好友昵称", "提示词", "接口序号（0 起）", "最大轮数（0=不限）"])
    tbl.verticalHeader().setVisible(False)
    tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
    tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
    tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    tbl.setMinimumHeight(200)
    g3l.addWidget(tbl)
    row = QHBoxLayout()
    b_add = QPushButton("新增")
    b_del = QPushButton("删除选中")
    b_add.clicked.connect(lambda: _add(tbl))
    b_del.clicked.connect(lambda: _del(tbl))
    for b in (b_add, b_del):
        b.setFixedWidth(100)
        row.addWidget(b)
    row.addStretch(1)
    g3l.addLayout(row)
    lay.addWidget(g3, 1)

    lay.addStretch(1)

    def _add(t, name="", prompt="", api=0, rounds=0):
        r = t.rowCount()
        t.insertRow(r)
        t.setCellWidget(r, 0, QLineEdit(name))
        t.setCellWidget(r, 1, QLineEdit(prompt))
        sp = QSpinBox()
        sp.setRange(0, 99)
        sp.setValue(int(api or 0))
        t.setCellWidget(r, 2, sp)
        sp2 = QSpinBox()
        sp2.setRange(0, 99999)
        sp2.setValue(int(rounds or 0))
        t.setCellWidget(r, 3, sp2)

    def _del(t):
        for r in sorted({i.row() for i in t.selectedIndexes()}, reverse=True):
            t.removeRow(r)

    def load(cfg):
        combo.setCurrentIndex(1 if cfg.get("AllListen_switch") else 0)
        ck_mute.setChecked(bool(cfg.get("AllListen_filter_mute", True)))
        ck_only.setChecked(bool(cfg.get("chat_listen_only", False)))
        lst.load(cfg.get("listen_list", []) or [])

        pmap = cfg.get("chat_prompt_map", {}) or {}
        amap = cfg.get("chat_api_map", {}) or {}
        rmap = cfg.get("chat_max_round_map", {}) or {}
        tbl.setRowCount(0)
        for name in pmap.keys() | amap.keys() | rmap.keys():
            _add(tbl, name, str(pmap.get(name, "")), int(amap.get(name, 0) or 0),
                 int(rmap.get(name, 0) or 0))

    def collect():
        pmap, amap, rmap = {}, {}, {}
        for r in range(tbl.rowCount()):
            name_w = tbl.cellWidget(r, 0)
            p_w = tbl.cellWidget(r, 1)
            a_w = tbl.cellWidget(r, 2)
            r_w = tbl.cellWidget(r, 3)
            name = name_w.text().strip() if name_w else ""
            if not name:
                continue
            p = p_w.text().strip() if p_w else ""
            a = a_w.value() if a_w else 0
            rr = r_w.value() if r_w else 0
            if p:
                pmap[name] = p
            if a:
                amap[name] = a
            if rr:
                rmap[name] = rr
        return {
            "AllListen_switch": bool(combo.currentData()),
            "AllListen_filter_mute": ck_mute.isChecked(),
            "chat_listen_only": ck_only.isChecked(),
            "listen_list": lst.collect(),
            "chat_prompt_map": pmap,
            "chat_api_map": amap,
            "chat_max_round_map": rmap,
        }

    w.load = load
    w.collect = collect
    return w
