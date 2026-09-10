# -*- coding: utf-8 -*-
"""状态面板：内核 / 授权 / 运行 / 能力清单"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)

from . import register
from ..widgets import info
import os

try:
    from core import wx_compat
except Exception:
    wx_compat = None


def _kv(label, value, color=None):
    v = QLabel(str(value))
    v.setTextInteractionFlags(Qt.TextSelectableByMouse)
    if color:
        v.setStyleSheet(f"color:{color};font-weight:600;")
    else:
        v.setStyleSheet("font-weight:600;")
    l = QLabel(label)
    l.setStyleSheet("color:#86909C;")
    return l, v


@register("status")
def build(page, mw):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)

    # ---- 微信内核 ----
    g1 = QGroupBox("微信内核")
    g = QGridLayout(g1)
    g.setContentsMargins(14, 16, 14, 14)
    g.setVerticalSpacing(8)
    r = 0
    if wx_compat:
        rows = [
            ("当前内核", wx_compat.CORE_LABEL),
            ("说明", wx_compat.CORE_DETAIL),
        ]
        for k, v in rows:
            l, vl = _kv(k, v)
            g.addWidget(l, r, 0)
            g.addWidget(vl, r, 1)
            r += 1
    else:
        l, vl = _kv("当前内核", "加载失败")
        g.addWidget(l, r, 0)
        g.addWidget(vl, r, 1)
        r += 1
    g.setColumnStretch(1, 1)
    lay.addWidget(g1)

    # ---- 能力清单 ----
    g2 = QGroupBox("内核能力")
    g2l = QGridLayout(g2)
    g2l.setContentsMargins(14, 16, 14, 14)
    caps = getattr(wx_compat, "CAPS", {}) if wx_compat else {}
    names = {
        "listen": "消息监听", "send": "发送消息",
        "moments": "朋友圈", "global_listen": "全局监听",
        "download_media": "下载媒体", "quote_reply": "引用回复",
        "forward_msg": "消息转发", "new_friends": "新好友管理",
        "url_card": "URL 卡片",
    }
    row, col = 0, 0
    for k, label in names.items():
        ok = bool(caps.get(k, False))
        mark = QLabel("●")
        mark.setStyleSheet(f"color:{'#00B42A' if ok else '#C9CDD4'};")
        txt = QLabel(f"{label}{'' if ok else '（需 wxautox4）'}")
        h = QHBoxLayout()
        h.setSpacing(6)
        h.addWidget(mark)
        h.addWidget(txt)
        h.addStretch(1)
        cell = QWidget()
        cell.setLayout(h)
        g2l.addWidget(cell, row, col)
        col += 1
        if col >= 3:
            col = 0
            row += 1
    lay.addWidget(g2)

    # ---- 数据路径 ----
    from core import paths
    g3 = QGroupBox("数据位置")
    g3l = QGridLayout(g3)
    g3l.setContentsMargins(14, 16, 14, 14)
    r = 0
    for k, v in [("配置文件", paths.config_file()),
                 ("数据目录", paths.data_dir()),
                 ("日志目录", paths.log_dir())]:
        l, vl = _kv(k, v)
        vl.setStyleSheet("font-weight:400;")
        g3l.addWidget(l, r, 0)
        g3l.addWidget(vl, r, 1)
        r += 1
    g3l.setColumnStretch(1, 1)
    lay.addWidget(g3)

    btn = QPushButton("检查微信窗口")
    btn.setFixedWidth(140)
    btn.clicked.connect(lambda: _check_wx(mw))
    lay.addWidget(btn)
    lay.addStretch(1)

    w.load = lambda cfg: None
    w.collect = lambda: {}
    return w


def _check_wx(mw):
    try:
        from core.wx_compat import WeChat
        wx = WeChat()
        mw.log("微信窗口已就绪", "SUCCESS")
    except Exception as e:
        mw.log(f"未检测到微信窗口：{e}", "ERROR")
