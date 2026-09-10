# -*- coding: utf-8 -*-
"""SiverWXbot_plus 原版配色主题（QSS）

配色全部取自原版 dashboard.html 的 :root 变量，保持一致：
  --primary      #07C160   （微信绿，选中态/主按钮）
  --sidebar-bg   #2C2C2C   （侧边栏与顶栏）
  --sidebar-fg   #C8C8C8   （侧边栏文字）
  --bg           #F7F7F7   （内容区）
  --card         #FFFFFF
  --card-fg      #191919
  --muted        #888888
  --border       #E5E5E5
  --danger       #FA5151
  --warning      #FFC300

重要约束（血泪教训，勿删）：
Windows 分数缩放（125% / 150%）下，QSS 里的 `font-size`、控件级 setFont、
以及 QLabel 上的 `padding` 都会导致文字压扁重影。
所以：QSS 里一个 font-size 都不写；导航项的内边距一律用布局
setContentsMargins；全程序只在 app.py 里 setFont 一次。
"""

QSS = """
/* ---------- 全局 ---------- */
QWidget {
    background: #F7F7F7;
    color: #191919;
    font-family: "Microsoft YaHei UI";
}
QMainWindow, QDialog { background: #F7F7F7; }

QLabel { background: transparent; color: #191919; }
QLabel#fieldLabel { color: #333333; }
QLabel#pageDesc { color: #888888; }
QLabel#groupDesc { color: #888888; }
QLabel#hint { color: #888888; }
QLabel#sectionTitle { color: #888888; }

/* ---------- 顶栏（原版 .topbar） ---------- */
QWidget#topbar {
    background: #2C2C2C;
    border-bottom: 1px solid #3A3A3A;
}
QWidget#topbar QWidget { background: transparent; }
QLabel#brandTitle { color: #FFFFFF; font-weight: 700; }
QLabel#brandSub { color: rgba(255,255,255,0.55); }
QLabel#pageTitle { color: #FFFFFF; font-weight: 600; }
QLabel#pageDescTop { color: rgba(255,255,255,0.55); }

/* ---------- 侧边栏（原版 .sidebar / .nav-link） ---------- */
QWidget#sidebar {
    background: #2C2C2C;
    border-right: 1px solid #3A3A3A;
}
/* Qt 的 QWidget 类型选择器只匹配纯 QWidget（不匹配 QFrame/QLabel 等子类），
   所以侧边栏里的裸 QWidget 容器会被全局规则刷成浅灰，这里显式兜底。 */
QWidget#sidebar QWidget,
QWidget#sidebar QScrollArea,
QWidget#sidebar QAbstractScrollArea,
QWidget#sidebar QScrollArea > QWidget > QWidget { background: transparent; }
QWidget#sidebar QScrollArea { border: none; }
/* 深色侧栏上的滚动条 */
QWidget#sidebar QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QWidget#sidebar QScrollBar::handle:vertical {
    background: rgba(255,255,255,0.18); border-radius: 4px; min-height: 40px;
}
QWidget#sidebar QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.3); }
QWidget#sidebar QScrollBar::add-line:vertical,
QWidget#sidebar QScrollBar::sub-line:vertical { height: 0; }

QFrame#navItem { background: transparent; border-radius: 6px; }
QFrame#navItem:hover { background: rgba(255,255,255,0.08); }
QFrame#navItem[active="true"] { background: #07C160; }

QLabel#navText { background: transparent; color: #C8C8C8; }
QFrame#navItem:hover QLabel#navText { color: #FFFFFF; }
QFrame#navItem[active="true"] QLabel#navText { color: #FFFFFF; font-weight: 500; }

QFrame#navDivider { background: #3A3A3A; }

QLabel#sideFootLabel { color: #888888; }
QLabel#sideFootValue { color: #C8C8C8; font-weight: 600; }

/* ---------- 按钮（原版 .action-bar .btn） ---------- */
QPushButton#btnStart { background: #07C160; color: #fff; border: none; border-radius: 6px; padding: 8px 20px; font-weight: 600; }
QPushButton#btnStart:hover { background: #06AD56; }
QPushButton#btnStart:disabled { background: #8FD9B4; }
QPushButton#btnStop { background: #FA5151; color: #fff; border: none; border-radius: 6px; padding: 8px 20px; font-weight: 600; }
QPushButton#btnStop:hover { background: #E04040; }
QPushButton#btnStop:disabled { background: #F5B3B3; }
QPushButton#btnRestart { background: #FF8C00; color: #fff; border: none; border-radius: 6px; padding: 8px 20px; font-weight: 600; }
QPushButton#btnRestart:hover { background: #E07A00; }
QPushButton#btnGhost { background: #FFFFFF; color: #4E5969; border: 1px solid #E5E5E5; border-radius: 6px; padding: 8px 16px; }
QPushButton#btnGhost:hover { background: #F2F2F2; }
QPushButton#btnPrimary { background: #07C160; color: #fff; border: none; border-radius: 6px; padding: 8px 20px; font-weight: 600; }
QPushButton#btnPrimary:hover { background: #06AD56; }

QLabel#runState { font-weight: 600; }
QLabel#runState[state="running"] { color: #07C160; }
QLabel#runState[state="stopped"] { color: #888888; }
QLabel#runState[state="error"] { color: #FA5151; }

/* ---------- 卡片（原版 .cfg-card） ---------- */
QGroupBox {
    background: #FFFFFF; border: 1px solid #E5E5E5; border-radius: 8px;
    margin-top: 12px; padding: 4px 0 0 0; font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 14px; padding: 0 6px; color: #191919;
}

/* ---------- 输入控件 ---------- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox, QTimeEdit {
    background: #FFFFFF; border: 1px solid #E5E5E5; border-radius: 6px;
    padding: 6px 9px; selection-background-color: #07C160;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QComboBox:focus, QTimeEdit:focus { border-color: #07C160; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: none; border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #4E5969; width: 0px; height: 0px; }
QComboBox QAbstractItemView { border: 1px solid #E5E5E5; selection-background-color: #E8F5EE; }

QCheckBox { spacing: 6px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 9px; background: #C9CDD4; }
QCheckBox::indicator:checked { background: #07C160; }
QCheckBox::indicator:hover { background: #B7BDC7; }
QCheckBox::indicator:checked:hover { background: #38D98A; }

QPushButton { background: #FFFFFF; border: 1px solid #E5E5E5; border-radius: 6px; padding: 6px 14px; }
QPushButton:hover { background: #F2F2F2; }
QPushButton:pressed { background: #E8E8E8; }
QPushButton:disabled { color: #C9CDD4; }

/* ---------- 表格 ---------- */
QTableWidget {
    background: #FFFFFF; border: 1px solid #E5E5E5; border-radius: 8px;
    gridline-color: #F0F0F0; alternate-background-color: #FAFAFA;
    selection-background-color: #E8F5EE; selection-color: #191919;
}
QHeaderView::section {
    background: #F7F7F7; border: none; border-right: 1px solid #E5E5E5;
    border-bottom: 1px solid #E5E5E5; padding: 8px 10px; font-weight: 600; color: #333333;
}
QTableWidget::item { padding: 4px 8px; }

QTabWidget::pane { border: none; background: #F7F7F7; }

/* ---------- 滚动条 ---------- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #D6D8DD; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #C0C4CC; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #D6D8DD; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ---------- 日志（原版 .log-panel 深色） ---------- */
QTextEdit#logView {
    background: #1A1A1A; border: 1px solid #333333; border-radius: 8px;
    font-family: Consolas; color: #C8C8C8;
}
"""


def apply(app):
    app.setStyleSheet(QSS)
