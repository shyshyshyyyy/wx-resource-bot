# -*- coding: utf-8 -*-
"""记忆管理：按微信号 / 会话浏览与清理对话记忆"""

import json
import os
import shutil

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget, QTreeWidget, QTreeWidgetItem,
)

from . import register
from ..widgets import ask_yes_no, info
from core import paths


@register("memory")
def build(page, mw):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)

    tip = QLabel("对话记忆按「微信号 / 会话」分文件存储。上限与带入条数在「其他配置 → 对话记忆」中调整。")
    tip.setObjectName("pageDesc")
    tip.setWordWrap(True)
    lay.addWidget(tip)

    g = QGroupBox("记忆数据")
    gl = QVBoxLayout(g)
    gl.setContentsMargins(14, 16, 14, 16)

    split = QSplitter(Qt.Horizontal)

    tree = QTreeWidget()
    tree.setHeaderLabels(["微信号 / 会话"])
    tree.setFixedWidth(300)
    tree.setAlternatingRowColors(False)

    right = QWidget()
    rl = QVBoxLayout(right)
    rl.setContentsMargins(12, 0, 0, 0)
    lab = QLabel("选择左侧会话查看内容")
    lab.setObjectName("groupDesc")
    view = QTextEdit()
    view.setReadOnly(True)
    view.setMinimumHeight(320)
    rl.addWidget(lab)
    rl.addWidget(view, 1)
    row = QHBoxLayout()
    b_del_chat = QPushButton("删除该会话记忆")
    b_del_wx = QPushButton("删除该微信号全部记忆")
    for b in (b_del_chat, b_del_wx):
        b.setFixedWidth(180)
        row.addWidget(b)
    row.addStretch(1)
    rl.addLayout(row)

    split.addWidget(tree)
    split.addWidget(right)
    split.setStretchFactor(1, 1)
    gl.addWidget(split)
    lay.addWidget(g, 1)

    def refresh():
        tree.clear()
        base = paths.memory_dir()
        if not os.path.isdir(base):
            return
        for wx_id in sorted(os.listdir(base)):
            p1 = os.path.join(base, wx_id)
            if not os.path.isdir(p1):
                continue
            root = QTreeWidgetItem(tree, [wx_id])
            root.setData(0, Qt.UserRole, ("wx", p1))
            for chat in sorted(os.listdir(p1)):
                p2 = os.path.join(p1, chat)
                if not os.path.isdir(p2):
                    continue
                it = QTreeWidgetItem(root, [chat])
                it.setData(0, Qt.UserRole, ("chat", p2))
            root.setExpanded(True)

    def _show(item):
        data = item.data(0, Qt.UserRole) if item else None
        if not data:
            return
        kind, p = data
        if kind == "wx":
            lab.setText(f"微信号目录：{p}")
            view.setPlainText("\n".join(sorted(os.listdir(p))))
            return
        f = os.path.join(p, os.path.basename(p) + "_memory.json")
        lab.setText(f"会话记忆：{f}")
        if not os.path.exists(f):
            view.setPlainText("（无记忆文件）")
            return
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if isinstance(data, list):
                lines = []
                for m in data[-200:]:
                    role = m.get("role", "")
                    content = m.get("content", "")
                    lines.append(f"[{role}] {content}")
                view.setPlainText("\n".join(lines))
            else:
                view.setPlainText(json.dumps(data, ensure_ascii=False, indent=2)[:20000])
        except Exception as e:
            view.setPlainText(f"读取失败：{e}")

    def on_del_chat():
        it = tree.currentItem()
        data = it.data(0, Qt.UserRole) if it else None
        if not data or data[0] != "chat":
            info(mw, "提示", "请先选择一个会话")
            return
        if not ask_yes_no(mw, "确认删除", f"确定删除该会话的全部记忆？\n{data[1]}"):
            return
        shutil.rmtree(data[1], ignore_errors=True)
        refresh()
        mw.log("会话记忆已删除", "WARN")

    def on_del_wx():
        it = tree.currentItem()
        if not it:
            return
        root = it
        while root.parent():
            root = root.parent()
        data = root.data(0, Qt.UserRole)
        if not data or data[0] != "wx":
            return
        if not ask_yes_no(mw, "确认删除", f"确定删除该微信号的全部记忆？\n{data[1]}"):
            return
        shutil.rmtree(data[1], ignore_errors=True)
        refresh()
        mw.log("微信号记忆已全部删除", "WARN")

    tree.currentItemChanged.connect(lambda cur, _: _show(cur))
    b_del_chat.clicked.connect(on_del_chat)
    b_del_wx.clicked.connect(on_del_wx)

    refresh()
    w.load = lambda cfg: None
    w.collect = lambda: {}
    return w
