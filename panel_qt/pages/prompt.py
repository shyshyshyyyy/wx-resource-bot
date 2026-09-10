# -*- coding: utf-8 -*-
"""Prompt 管理：多提示词文件"""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QSplitter, QTextEdit,
    QVBoxLayout, QWidget,
)

from . import register
from ..widgets import info, warn
from core import paths


@register("prompt")
def build(page, mw):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)

    tip = QLabel("多套提示词，可按私聊好友 / 群聊分别指定使用哪一套。文件保存在 data/config/prompt/")
    tip.setObjectName("pageDesc")
    tip.setWordWrap(True)
    lay.addWidget(tip)

    g = QGroupBox("提示词")
    gl = QVBoxLayout(g)
    gl.setContentsMargins(14, 16, 14, 16)

    split = QSplitter(Qt.Horizontal)
    lst = QListWidget()
    lst.setFixedWidth(180)
    right = QWidget()
    rl = QVBoxLayout(right)
    rl.setContentsMargins(12, 0, 0, 0)
    editor = QTextEdit()
    editor.setMinimumHeight(300)
    rl.addWidget(editor, 1)

    btns = QHBoxLayout()
    b_save = QPushButton("保存当前")
    b_save.setObjectName("btnPrimary")
    btns.addStretch(1)
    btns.addWidget(b_save)
    rl.addLayout(btns)

    split.addWidget(lst)
    split.addWidget(right)
    split.setStretchFactor(1, 1)
    gl.addWidget(split)

    row = QHBoxLayout()
    b_new = QPushButton("新建")
    b_del = QPushButton("删除")
    for b in (b_new, b_del):
        b.setFixedWidth(90)
        row.addWidget(b)
    row.addStretch(1)
    gl.addLayout(row)
    lay.addWidget(g, 1)

    g2 = QGroupBox("默认提示词")
    g2l = QHBoxLayout(g2)
    g2l.setContentsMargins(14, 16, 14, 16)
    combo = QComboBox()
    combo.setMinimumWidth(200)
    g2l.addWidget(QLabel("未单独指定时使用"))
    g2l.addWidget(combo)
    g2l.addStretch(1)
    lay.addWidget(g2)

    cur = {"name": ""}

    def pdir():
        return paths.prompt_dir()

    def refresh():
        lst.clear()
        combo.blockSignals(True)
        combo.clear()
        d = pdir()
        os.makedirs(d, exist_ok=True)
        names = sorted(f[:-3] for f in os.listdir(d) if f.endswith(".md"))
        for n in names:
            lst.addItem(QListWidgetItem(n))
            combo.addItem(n)
        combo.blockSignals(False)
        saved = (mw.config or {}).get("default_prompt", "默认")
        if saved in names:
            combo.setCurrentText(saved)
        if names:
            lst.setCurrentRow(0)
            _show_current()

    def _show_current():
        it = lst.currentItem()
        if not it:
            return
        name = it.text()
        cur["name"] = name
        p = os.path.join(pdir(), name + ".md")
        try:
            with open(p, "r", encoding="utf-8") as f:
                editor.setPlainText(f.read())
        except Exception:
            editor.setPlainText("")

    def _save_current():
        if not cur["name"]:
            return
        p = os.path.join(pdir(), cur["name"] + ".md")
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(editor.toPlainText())
            mw.log(f"提示词已保存：{cur['name']}", "SUCCESS")
        except Exception as e:
            warn(mw, "保存失败", str(e))

    def on_new():
        name, ok = QInputDialog.getText(mw, "新建提示词", "名称（不含 .md）")
        if not ok or not name.strip():
            return
        name = name.strip()
        p = os.path.join(pdir(), name + ".md")
        if os.path.exists(p):
            warn(mw, "提示", "已存在同名提示词")
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write("你是一个ai回复助手，请根据用户的问题给出回答,回复尽量保持在30字以内")
        except Exception as e:
            warn(mw, "创建失败", str(e))
            return
        refresh()
        mw.log(f"已新建提示词：{name}", "SUCCESS")

    def on_del():
        it = lst.currentItem()
        if not it:
            return
        name = it.text()
        if name == "默认":
            warn(mw, "提示", "默认提示词不可删除")
            return
        try:
            os.remove(os.path.join(pdir(), name + ".md"))
        except Exception as e:
            warn(mw, "删除失败", str(e))
            return
        refresh()
        mw.log(f"已删除提示词：{name}", "WARN")

    lst.currentItemChanged.connect(lambda *_: _show_current())
    b_new.clicked.connect(on_new)
    b_del.clicked.connect(on_del)
    b_save.clicked.connect(_save_current)

    def load(cfg):
        refresh()

    def collect():
        return {"default_prompt": combo.currentText()}

    refresh()
    w.load = load
    w.collect = collect
    return w
