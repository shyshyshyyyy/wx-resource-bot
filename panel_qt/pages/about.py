# -*- coding: utf-8 -*-
"""关于：版本、内核、能力清单、数据位置"""

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from . import register
from core import paths

VERSION = "1.0.0"
BUILD = "2026-09-09"


def _kv(label, value):
    v = QLabel(str(value))
    v.setTextInteractionFlags(Qt.TextSelectableByMouse)
    v.setStyleSheet("font-weight:500;")
    l = QLabel(label)
    l.setStyleSheet("color:#86909C;")
    return l, v


@register("about")
def build(page, mw):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)

    g1 = QGroupBox("版本信息")
    gl = QGridLayout(g1)
    gl.setContentsMargins(14, 16, 14, 16)
    gl.setVerticalSpacing(8)

    kernel = "未知"
    try:
        from core import wx_compat
        kernel = wx_compat.CORE_LABEL
    except Exception:
        pass

    rows = [
        ("软件名称", "微信资源搜索机器人"),
        ("版本", f"v{VERSION}（{BUILD}）"),
        ("Python", f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"),
        ("微信内核", kernel),
    ]
    r = 0
    for k, v in rows:
        l, vl = _kv(k, v)
        gl.addWidget(l, r, 0)
        gl.addWidget(vl, r, 1)
        r += 1
    gl.setColumnStretch(1, 1)
    lay.addWidget(g1)

    g2 = QGroupBox("数据位置")
    g2l = QGridLayout(g2)
    g2l.setContentsMargins(14, 16, 14, 16)
    g2l.setVerticalSpacing(8)
    rows2 = [
        ("数据目录", paths.data_dir()),
        ("底座配置", paths.config_file()),
        ("网盘配置", os.path.join(paths.config_dir(), "netdisk.json")),
        ("提示词目录", paths.prompt_dir()),
        ("对话记忆", paths.memory_dir()),
    ]
    r = 0
    for k, v in rows2:
        l, vl = _kv(k, v)
        vl.setStyleSheet("font-weight:400;")
        g2l.addWidget(l, r, 0)
        g2l.addWidget(vl, r, 1)
        r += 1
    g2l.setColumnStretch(1, 1)
    lay.addWidget(g2)

    row = QHBoxLayout()
    b_open = QPushButton("打开数据目录")
    b_copy = QPushButton("复制诊断信息")
    b_open.setFixedWidth(140)
    b_copy.setFixedWidth(140)
    row.addWidget(b_open)
    row.addWidget(b_copy)
    row.addStretch(1)
    lay.addLayout(row)

    lay.addStretch(1)

    def on_open():
        try:
            os.startfile(paths.data_dir())
        except Exception as e:
            mw.log(f"打开目录失败：{e}", "ERROR")

    def on_copy():
        caps = {}
        try:
            from core import wx_compat
            caps = wx_compat.CAPS
        except Exception:
            pass
        info = "\n".join([
            f"版本: v{VERSION} ({BUILD})",
            f"Python: {sys.version}",
            f"内核: {kernel}",
            f"能力: {caps}",
            f"数据目录: {paths.data_dir()}",
        ])
        QApplication.clipboard().setText(info)
        mw.log("诊断信息已复制", "SUCCESS")

    b_open.clicked.connect(on_open)
    b_copy.clicked.connect(on_copy)

    w.load = lambda cfg: None
    w.collect = lambda: {}
    return w
