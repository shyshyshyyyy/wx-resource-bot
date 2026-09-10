# -*- coding: utf-8 -*-
"""群组管理：监听群、回复规则、欢迎语、按群绑定接口与提示词"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QSpinBox, QTableWidget, QVBoxLayout, QWidget, QTextEdit,
)

from . import register
from ..widgets import ListEditor


@register("group")
def build(page, mw):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)

    # ---------- 群列表 ----------
    g0 = QGroupBox("监听群列表")
    g0l = QVBoxLayout(g0)
    g0l.setContentsMargins(14, 16, 14, 16)
    hint = QLabel("填写群聊名称（需与微信中显示的群名完全一致），一行一个。")
    hint.setObjectName("groupDesc")
    hint.setWordWrap(True)
    g0l.addWidget(hint)
    lst = ListEditor("群聊名称")
    g0l.addWidget(lst)
    lay.addWidget(g0)

    # ---------- 开关 ----------
    g1 = QGroupBox("群聊回复规则")
    gl = QGridLayout(g1)
    gl.setContentsMargins(14, 16, 14, 16)
    gl.setVerticalSpacing(10)

    ck_switch = QCheckBox("启用群机器人")
    ck_only = QCheckBox("只监听不回复")
    ck_at = QCheckBox("仅被 @ 时回复")
    ck_at_msg = QCheckBox("回复时 @ 发言人")
    ck_quote = QCheckBox("引用原消息回复")

    gl.addWidget(ck_switch, 0, 0)
    gl.addWidget(ck_only, 0, 1)
    gl.addWidget(ck_at, 1, 0)
    gl.addWidget(ck_at_msg, 1, 1)
    gl.addWidget(ck_quote, 2, 0)
    gl.setColumnStretch(2, 1)
    lay.addWidget(g1)

    # ---------- 欢迎语 ----------
    g2 = QGroupBox("新人欢迎")
    g2l = QGridLayout(g2)
    g2l.setContentsMargins(14, 16, 14, 16)
    ck_welcome = QCheckBox("启用群新人欢迎语")
    sp_rate = QDoubleSpinBox()
    sp_rate.setRange(0.0, 1.0)
    sp_rate.setSingleStep(0.1)
    sp_rate.setDecimals(2)
    e_msg = QTextEdit()
    e_msg.setMinimumHeight(70)
    e_msg.setMaximumHeight(90)
    g2l.addWidget(ck_welcome, 0, 0)
    g2l.addWidget(QLabel("触发概率"), 0, 1)
    g2l.addWidget(sp_rate, 0, 2)
    g2l.addWidget(QLabel("欢迎语"), 1, 0, alignment=Qt.AlignTop)
    g2l.addWidget(e_msg, 1, 1, 1, 2)
    g2l.setColumnStretch(2, 1)
    lay.addWidget(g2)

    # ---------- 按群绑定 ----------
    g3 = QGroupBox("按群单独指定（留空=使用全局默认）")
    g3l = QVBoxLayout(g3)
    g3l.setContentsMargins(14, 16, 14, 16)
    tbl = QTableWidget(0, 3)
    tbl.setHorizontalHeaderLabels(["群名称", "提示词", "接口序号（0 起）"])
    tbl.verticalHeader().setVisible(False)
    tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
    tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
    tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    tbl.setMinimumHeight(180)
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

    def _add(t, name="", prompt="", api=0):
        r = t.rowCount()
        t.insertRow(r)
        t.setCellWidget(r, 0, QLineEdit(name))
        t.setCellWidget(r, 1, QLineEdit(prompt))
        sp = QSpinBox()
        sp.setRange(0, 99)
        sp.setValue(int(api or 0))
        t.setCellWidget(r, 2, sp)

    def _del(t):
        for r in sorted({i.row() for i in t.selectedIndexes()}, reverse=True):
            t.removeRow(r)

    def load(cfg):
        lst.load(cfg.get("group", []) or [])
        ck_switch.setChecked(bool(cfg.get("group_switch", False)))
        ck_only.setChecked(bool(cfg.get("group_listen_only", False)))
        ck_at.setChecked(bool(cfg.get("group_reply_at", False)))
        ck_at_msg.setChecked(bool(cfg.get("group_reply_at_msg", True)))
        ck_quote.setChecked(bool(cfg.get("group_reply_quote", False)))
        ck_welcome.setChecked(bool(cfg.get("group_welcome", False)))
        try:
            sp_rate.setValue(float(cfg.get("group_welcome_random", 1.0)))
        except Exception:
            sp_rate.setValue(1.0)
        e_msg.setPlainText(str(cfg.get("group_welcome_msg", "") or ""))

        pmap = cfg.get("group_prompt_map", {}) or {}
        amap = cfg.get("group_api_map", {}) or {}
        tbl.setRowCount(0)
        for name in pmap.keys() | amap.keys():
            _add(tbl, name, str(pmap.get(name, "")), int(amap.get(name, 0) or 0))

    def collect():
        pmap, amap = {}, {}
        for r in range(tbl.rowCount()):
            nw = tbl.cellWidget(r, 0)
            pw = tbl.cellWidget(r, 1)
            aw = tbl.cellWidget(r, 2)
            name = nw.text().strip() if nw else ""
            if not name:
                continue
            p = pw.text().strip() if pw else ""
            a = aw.value() if aw else 0
            if p:
                pmap[name] = p
            if a:
                amap[name] = a
        return {
            "group": lst.collect(),
            "group_switch": ck_switch.isChecked(),
            "group_listen_only": ck_only.isChecked(),
            "group_reply_at": ck_at.isChecked(),
            "group_reply_at_msg": ck_at_msg.isChecked(),
            "group_reply_quote": ck_quote.isChecked(),
            "group_welcome": ck_welcome.isChecked(),
            "group_welcome_random": round(sp_rate.value(), 2),
            "group_welcome_msg": e_msg.toPlainText(),
            "group_prompt_map": pmap,
            "group_api_map": amap,
        }

    w.load = load
    w.collect = collect
    return w
