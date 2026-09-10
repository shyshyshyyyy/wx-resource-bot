# -*- coding: utf-8 -*-
"""面板入口"""

import os
import sys

from PySide6.QtWidgets import QApplication

from .theme import apply as apply_theme


def run_panel():
    # 高分屏：分数缩放不做取整，避免 125%/150% 下文字渲染异常
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

    app = QApplication(sys.argv)
    app.setApplicationName("微信资源搜索机器人")
    # Fusion 样式：完全走 Qt 自绘，绕开 Windows 原生样式（windowsvista）
    # 在分数缩放下 QPushButton 文字重影的问题
    app.setStyle("Fusion")

    # 全局字体用 QFont 显式设置（QSS 的多字体 fallback 在部分环境下渲染异常）
    from PySide6.QtGui import QFont
    f = QFont("Microsoft YaHei UI", 10)
    f.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(f)

    apply_theme(app)

    from .main_window import MainWindow
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run_panel())
