# -*- coding: utf-8 -*-
"""数据备份与恢复"""

import os
import zipfile
from datetime import datetime

from PySide6.QtWidgets import (
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)

from . import register
from ..widgets import ask_yes_no, info, warn
from core import paths


@register("backup")
def build(page, mw):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)

    tip = QLabel("把配置、提示词、对话记忆、网盘账号打包成一个 zip，换机或重装时一键恢复。")
    tip.setObjectName("pageDesc")
    tip.setWordWrap(True)
    lay.addWidget(tip)

    g1 = QGroupBox("备份")
    g1l = QVBoxLayout(g1)
    g1l.setContentsMargins(14, 16, 14, 16)
    row = QHBoxLayout()
    b_now = QPushButton("立即备份到…")
    b_now.setObjectName("btnPrimary")
    b_now.setFixedWidth(160)
    row.addWidget(b_now)
    row.addStretch(1)
    g1l.addLayout(row)
    lay.addWidget(g1)

    g2 = QGroupBox("恢复")
    g2l = QVBoxLayout(g2)
    g2l.setContentsMargins(14, 16, 14, 16)
    hint = QLabel("恢复会覆盖当前 data 目录下的同名文件，建议先备份一次。恢复后需重启软件。")
    hint.setObjectName("groupDesc")
    hint.setWordWrap(True)
    g2l.addWidget(hint)
    row2 = QHBoxLayout()
    b_restore = QPushButton("从备份文件恢复…")
    b_restore.setFixedWidth(160)
    row2.addWidget(b_restore)
    row2.addStretch(1)
    g2l.addLayout(row2)
    lay.addWidget(g2)

    log_box = QTextEdit()
    log_box.setReadOnly(True)
    log_box.setMinimumHeight(200)
    log_box.setObjectName("logView")
    lay.addWidget(log_box, 1)

    def _log(t):
        log_box.append(t)

    def on_backup():
        default = os.path.join(
            os.path.expanduser("~"),
            f"wxbot_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
        path, _ = QFileDialog.getSaveFileName(mw, "保存备份", default, "ZIP 文件 (*.zip)")
        if not path:
            return
        base = paths.data_dir()
        n = 0
        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
                for root, dirs, files in os.walk(base):
                    for f in files:
                        fp = os.path.join(root, f)
                        try:
                            z.write(fp, os.path.relpath(fp, base))
                            n += 1
                        except Exception as e:
                            _log(f"跳过 {fp}: {e}")
            _log(f"备份完成：{n} 个文件 -> {path}")
            mw.log(f"数据已备份到 {path}", "SUCCESS")
            info(mw, "备份完成", f"共 {n} 个文件\n{path}")
        except Exception as e:
            warn(mw, "备份失败", str(e))

    def on_restore():
        path, _ = QFileDialog.getOpenFileName(mw, "选择备份文件", "", "ZIP 文件 (*.zip)")
        if not path:
            return
        if not ask_yes_no(mw, "确认恢复", "恢复将覆盖当前数据，确定继续？"):
            return
        base = paths.data_dir()
        try:
            with zipfile.ZipFile(path, "r") as z:
                z.extractall(base)
            _log(f"已从 {path} 恢复")
            mw.log("数据已恢复，请重启软件", "SUCCESS")
            info(mw, "恢复完成", "请重启软件使配置生效。")
        except Exception as e:
            warn(mw, "恢复失败", str(e))

    b_now.clicked.connect(on_backup)
    b_restore.clicked.connect(on_restore)

    w.load = lambda cfg: None
    w.collect = lambda: {}
    return w
