# -*- coding: utf-8 -*-
"""侧边栏图标：Bootstrap Icons SVG（与 SiverWXbot_plus 原版面板同一套图标）。

为什么用 SVG 而不是图标字体：
Windows 分数缩放下，给控件单独设字号 / 用图标字体会出现文字压扁重影。
SVG 走 QSvgRenderer 矢量渲染，与字体无关，任何 DPI 都稳定。
SVG 里的 fill="currentColor" 在渲染前替换成实际颜色，所以能跟随选中状态变色。
"""

import os

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from core import paths

_DIR = os.path.join(paths.assets_dir(), "icons")
_cache = {}


def _svg_text(name, color):
    p = os.path.join(_DIR, name + ".svg")
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            t = f.read()
    except Exception:
        return None
    return t.replace("currentColor", color)


def icon(name, color="#C8C8C8", size=16, dpr=1.0):
    """渲染一个 Bootstrap Icon 为 QIcon。找不到时返回空 QIcon。"""
    key = (name, color, size, round(dpr, 2))
    if key in _cache:
        return _cache[key]
    txt = _svg_text(name, color)
    if txt is None:
        ic = QIcon()
        _cache[key] = ic
        return ic
    r = QSvgRenderer(QByteArray(txt.encode("utf-8")))
    px = max(1, int(round(size * dpr)))
    pm = QPixmap(px, px)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    pa = QPainter(pm)
    r.render(pa)
    pa.end()
    ic = QIcon(pm)
    _cache[key] = ic
    return ic


def pixmap(name, color="#C8C8C8", size=16, dpr=1.0):
    return icon(name, color, size, dpr).pixmap(size, size)


# 页面 id -> Bootstrap Icons 名称（与原版 dashboard.html 一一对应，
# 新增的网盘/授权页面沿用同系列图标）
PAGE_ICON = {
    "status": "speedometer2",
    "license": "patch-check",
    "siver_panel": "router",
    "api": "cloud",
    "prompt": "chat-square-text",
    "admin": "shield-lock",
    "listen": "ear",
    "group": "people",
    "friend": "person-plus",
    "keyword": "key",
    "forward": "share",
    "schedule": "alarm",
    "moments": "image",
    "startstop": "clock-history",
    "memory": "journal-text",
    "backup": "shield-check",
    "nd_search": "search",
    "nd_account": "hdd-network",
    "nd_template": "file-earmark-text",
    "nd_convert": "link-45deg",
    "other": "sliders",
    "account": "person-gear",
    "email": "envelope-at",
    "webhook": "broadcast-pin",
    "about": "info-circle",
}


def page_pixmap(page_id, color="#C8C8C8", size=16, dpr=1.0):
    return pixmap(PAGE_ICON.get(page_id, "grid-1x2"), color, size, dpr)
