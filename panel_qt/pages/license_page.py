# -*- coding: utf-8 -*-
"""授权激活：软件授权（RSA 离线）+ wxautox4 内核激活"""

import os
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from . import register
from ..widgets import info, warn
from core import paths

import license as lic


def _kv(label, value, color=None):
    v = QLabel(str(value))
    v.setTextInteractionFlags(Qt.TextSelectableByMouse)
    v.setStyleSheet(f"color:{color or '#1F2329'};font-weight:600;")
    l = QLabel(label)
    l.setStyleSheet("color:#86909C;")
    return l, v


@register("license")
def build(page, mw):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)

    # ---------- 软件授权 ----------
    g1 = QGroupBox("软件授权")
    gl = QGridLayout(g1)
    gl.setContentsMargins(14, 16, 14, 16)
    gl.setVerticalSpacing(10)

    g1_tip = QLabel(
        "激活流程：① 复制下面的机器码发给作者 → "
        "② 作者在「授权生成器 → 我的软件 → %s」里签发 → "
        "③ 把生成的整段授权码粘贴到下方，点激活。"
        % getattr(lic, "APP_ID", "本软件")
    )
    g1_tip.setWordWrap(True)
    g1_tip.setObjectName("groupDesc")
    gl.addWidget(g1_tip, 0, 0, 1, 3)

    try:
        machine = lic.get_machine_code()
    except Exception as e:
        machine = f"获取失败: {e}"

    code_edit = QLineEdit(machine)
    code_edit.setReadOnly(True)
    btn_copy = QPushButton("复制")
    btn_copy.setFixedWidth(64)
    btn_copy.clicked.connect(
        lambda: (QApplication.clipboard().setText(machine),
                 mw.log("机器码已复制", "SUCCESS")))

    gl.addWidget(QLabel("本机机器码"), 1, 0)
    gl.addWidget(code_edit, 1, 1)
    gl.addWidget(btn_copy, 1, 2)

    app_id = str(getattr(lic, "APP_ID", "") or "")
    app_edit = QLineEdit(app_id)
    app_edit.setReadOnly(True)
    btn_copy_app = QPushButton("复制")
    btn_copy_app.setFixedWidth(64)
    btn_copy_app.clicked.connect(
        lambda: (QApplication.clipboard().setText(app_id),
                 mw.log(f"软件标识已复制：{app_id}", "SUCCESS")))
    gl.addWidget(QLabel("软件标识"), 2, 0)
    gl.addWidget(app_edit, 2, 1)
    gl.addWidget(btn_copy_app, 2, 2)

    lic_edit = QLineEdit()
    lic_edit.setPlaceholderText(
        "粘贴授权码（生成器生成的整段 JSON，直接全选复制粘贴即可）")
    gl.addWidget(QLabel("授权码"), 3, 0)
    gl.addWidget(lic_edit, 3, 1, 1, 2)

    lb_state, vb_state = _kv("状态", "未激活", "#86909C")
    lb_exp, vb_exp = _kv("到期时间", "-")
    lb_left, vb_left = _kv("剩余天数", "-")
    lb_lid, vb_lid = _kv("授权编号", "-")
    gl.addWidget(lb_state, 4, 0)
    gl.addWidget(vb_state, 4, 1, 1, 2)
    gl.addWidget(lb_exp, 5, 0)
    gl.addWidget(vb_exp, 5, 1, 1, 2)
    gl.addWidget(lb_left, 6, 0)
    gl.addWidget(vb_left, 6, 1, 1, 2)
    gl.addWidget(lb_lid, 7, 0)
    gl.addWidget(vb_lid, 7, 1, 1, 2)

    btn_active = QPushButton("激活")
    btn_active.setObjectName("btnPrimary")
    btn_active.setFixedWidth(120)
    gl.addWidget(btn_active, 8, 1, alignment=Qt.AlignLeft)
    gl.setColumnStretch(1, 1)
    lay.addWidget(g1)

    # ---------- wxautox4 内核激活 ----------
    g2 = QGroupBox("wxautox4 内核激活（付费版内核）")
    g2l = QGridLayout(g2)
    g2l.setContentsMargins(14, 16, 14, 16)
    g2l.setVerticalSpacing(10)

    tip = QLabel(
        "激活后可使用朋友圈、全局监听、图片/文件下载、引用回复、消息转发、"
        "新好友管理、URL 卡片等高级能力；未激活时自动回落免费版内核，"
        "基础收发消息不受影响。"
    )
    tip.setWordWrap(True)
    tip.setObjectName("groupDesc")
    g2l.addWidget(tip, 0, 0, 1, 3)

    wx_edit = QLineEdit()
    wx_edit.setPlaceholderText("输入 wxautox4 授权码")
    g2l.addWidget(QLabel("内核授权码"), 1, 0)
    g2l.addWidget(wx_edit, 1, 1, 1, 2)

    lb_core, vb_core = _kv("内核状态", "检测中")
    g2l.addWidget(lb_core, 2, 0)
    g2l.addWidget(vb_core, 2, 1, 1, 2)

    btn_wx = QPushButton("激活内核")
    btn_wx.setFixedWidth(120)
    g2l.addWidget(btn_wx, 3, 1, alignment=Qt.AlignLeft)
    g2l.setColumnStretch(1, 1)
    lay.addWidget(g2)

    lay.addStretch(1)

    # ---------- 逻辑 ----------
    def refresh_license():
        try:
            saved = lic.load_license({"license": _read_saved()})
        except Exception:
            saved = ""
        if saved:
            lic_edit.setText(saved)
        r = lic.verify_license(saved, current_code=machine) if saved else {"ok": False, "msg": "未激活"}
        if r.get("ok"):
            vb_state.setText("已激活")
            vb_state.setStyleSheet("color:#00B42A;font-weight:600;")
            exp = r.get("expiry")
            vb_exp.setText(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(exp)) if exp else "永久")
            left = lic.days_left(r)
            vb_left.setText("永久" if left < 0 else f"{left} 天")
            vb_left.setStyleSheet(
                "color:%s;font-weight:600;"
                % ("#F53F3F" if 0 <= left <= 7 else "#1F2329"))
            vb_lid.setText(r.get("licenseId") or r.get("type") or "-")
        else:
            vb_state.setText(r.get("msg", "未激活"))
            vb_state.setStyleSheet("color:#F53F3F;font-weight:600;")
            vb_exp.setText("-")
            vb_left.setText("-")
            vb_lid.setText("-")

    def _read_saved():
        p = paths.license_file()
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                return ""
        return ""

    def on_active():
        code = lic_edit.text().strip()
        if not code:
            warn(mw, "提示", "请先粘贴授权码")
            return
        r = lic.verify_license(code, current_code=machine)
        if not r.get("ok"):
            warn(mw, "激活失败", r.get("msg", "未知错误"))
            return
        try:
            with open(paths.license_file(), "w", encoding="utf-8") as f:
                f.write(code)
        except Exception as e:
            warn(mw, "写入失败", str(e))
            return
        mw.log("软件授权已激活", "SUCCESS")
        info(mw, "激活成功", "授权已生效，重启软件后完整功能可用。")
        refresh_license()
        try:
            mw._refresh_license_side()
        except Exception:
            pass

    def refresh_core():
        try:
            from core import wx_compat
            label = getattr(wx_compat, "CORE_LABEL", "未知")
            vb_core.setText(label)
            vb_core.setStyleSheet(
                "color:%s;font-weight:600;"
                % ("#00B42A" if "wxautox4" in label or "Plus" in label else "#86909C"))
        except Exception as e:
            vb_core.setText(f"检测失败: {e}")

    def on_wx_active():
        code = wx_edit.text().strip()
        if not code:
            warn(mw, "提示", "请输入 wxautox4 授权码")
            return
        try:
            from core import wx_compat
            ok, msg = wx_compat.activate_plus(code)
            if ok:
                mw.log(f"wxautox4 激活成功：{msg}", "SUCCESS")
                info(mw, "激活成功", str(msg))
            else:
                warn(mw, "激活失败", str(msg))
            refresh_core()
        except Exception as e:
            warn(mw, "激活失败", str(e))

    btn_active.clicked.connect(on_active)
    btn_wx.clicked.connect(on_wx_active)

    refresh_license()
    refresh_core()

    w.load = lambda cfg: None
    w.collect = lambda: {}
    return w
