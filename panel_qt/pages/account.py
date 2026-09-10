# -*- coding: utf-8 -*-
"""面板账号密码"""

from PySide6.QtWidgets import (
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QVBoxLayout, QWidget, QCheckBox,
)

from . import register
from ..widgets import info, warn
from core import paths


@register("account")
def build(page, mw):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)

    tip = QLabel("设置面板登录账号与访问端口。本地使用可不开启登录校验。")
    tip.setObjectName("pageDesc")
    tip.setWordWrap(True)
    lay.addWidget(tip)

    g = QGroupBox("面板访问")
    form = QFormLayout(g)
    form.setContentsMargins(14, 16, 14, 16)
    form.setSpacing(10)

    e_user = QLineEdit()
    e_pwd = QLineEdit()
    e_pwd.setEchoMode(QLineEdit.Password)
    e_pwd2 = QLineEdit()
    e_pwd2.setEchoMode(QLineEdit.Password)
    e_pwd2.setPlaceholderText("再次输入以确认")
    sp_port = QSpinBox()
    sp_port.setRange(1, 65535)
    ck_open = QCheckBox("启动后自动打开浏览器（仅 Web 面板模式）")

    form.addRow("用户名", e_user)
    form.addRow("新密码", e_pwd)
    form.addRow("确认密码", e_pwd2)
    form.addRow("端口", sp_port)
    form.addRow("", ck_open)
    lay.addWidget(g)

    row = QHBoxLayout()
    b_save = QPushButton("保存账号设置")
    b_save.setObjectName("btnPrimary")
    b_save.setFixedWidth(150)
    row.addWidget(b_save)
    row.addStretch(1)
    lay.addLayout(row)
    lay.addStretch(1)

    def load(cfg):
        p = cfg.get("panel", {}) or {}
        e_user.setText(str(p.get("username", "admin")))
        e_pwd.setText("")
        e_pwd2.setText("")
        sp_port.setValue(int(p.get("port", 8765) or 8765))
        ck_open.setChecked(bool(p.get("auto_open_browser", True)))

    def collect():
        pwd = e_pwd.text()
        if pwd or e_pwd2.text():
            if pwd != e_pwd2.text():
                warn(mw, "提示", "两次输入的密码不一致")
                return {}
        p = {"host": "127.0.0.1", "port": sp_port.value(),
             "auto_open_browser": ck_open.isChecked(),
             "username": e_user.text().strip() or "admin"}
        if pwd:
            p["password"] = pwd
        out = {"panel": p}
        e_pwd.setText("")
        e_pwd2.setText("")
        return out

    def on_save():
        if collect():
            info(mw, "已保存", "账号设置已保存（下次启动生效）。")

    b_save.clicked.connect(on_save)

    w.load = load
    w.collect = collect
    return w
