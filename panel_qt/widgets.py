# -*- coding: utf-8 -*-
"""
通用控件工厂与表单渲染器

把 schema.F 声明自动渲染为 Qt 控件，并在 config 字典与控件之间双向同步。
任何 form 类型页面都用这一套，保证"配置字段 <=> 界面控件"一一对应。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox,
    QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QTextEdit,
    QTimeEdit, QVBoxLayout, QWidget, QHeaderView, QAbstractItemView,
    QMessageBox, QFileDialog, QMenu,
)
from PySide6.QtCore import QTime

from . import schema as S


# ============================================================
# 基础控件工厂
# ============================================================

def make_widget(f: "S.F"):
    """根据字段类型创建控件，返回 (widget, getter, setter)"""
    if f.type == "switch":
        w = QCheckBox()
        w.setCursor(Qt.PointingHandCursor)
        return w, w.isChecked, w.setChecked

    if f.type == "int":
        w = QSpinBox()
        w.setRange(f.min_value, f.max_value)
        w.setMinimumWidth(120)
        return w, w.value, w.setValue

    if f.type == "select":
        w = QComboBox()
        w.addItems(f.options or [])
        w.setMinimumWidth(140)
        get = lambda: w.currentText()          # noqa: E731
        set_ = lambda v: w.setCurrentText(str(v) if v is not None else "")  # noqa: E731
        return w, get, set_

    if f.type == "area":
        w = QTextEdit()
        w.setMinimumHeight(22 * f.rows)
        w.setMaximumHeight(22 * f.rows + 40)
        get = lambda: w.toPlainText()          # noqa: E731
        return w, get, w.setPlainText

    if f.type == "list":
        w = QPlainTextEdit()
        w.setMinimumHeight(90)
        w.setPlaceholderText(f.placeholder or "一行一条")
        get = lambda: [x.strip() for x in w.toPlainText().splitlines() if x.strip()]  # noqa: E731
        set_ = lambda v: w.setPlainText("\n".join(str(x) for x in (v or [])))         # noqa: E731
        return w, get, set_

    if f.type == "dict":
        w = DictEditor()
        return w, w.collect, w.load

    if f.type == "time":
        w = QTimeEdit()
        w.setDisplayFormat("HH:mm")
        w.setCalendarPopup(False)
        w.setMinimumWidth(110)
        get = lambda: w.time().toString("HH:mm")   # noqa: E731
        def set_(v):
            t = QTime.fromString(str(v or "00:00"), "HH:mm")
            w.setTime(t if t.isValid() else QTime(0, 0))
        return w, get, set_

    # 默认 text
    w = QLineEdit()
    w.setPlaceholderText(f.placeholder or "")
    if f.secret:
        w.setEchoMode(QLineEdit.Password)
    if f.span >= 2:
        w.setMinimumWidth(260)
    return w, w.text, w.setText


# ============================================================
# 键值对编辑器（关键词字典等）
# ============================================================

class DictEditor(QWidget):
    """两列表格：键 -> 值，支持增删"""

    def __init__(self, key_header="键", value_header="值", parent=None):
        super().__init__(parent)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([key_header, value_header])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)

        btns = QHBoxLayout()
        b_add = QPushButton("新增")
        b_del = QPushButton("删除选中")
        b_add.clicked.connect(self._add)
        b_del.clicked.connect(self._del)
        btns.addWidget(b_add)
        btns.addWidget(b_del)
        btns.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.table)
        lay.addLayout(btns)

    def _add(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(""))
        self.table.setItem(r, 1, QTableWidgetItem(""))
        self.table.editItem(self.table.item(r, 0))

    def _del(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def load(self, data):
        self.table.setRowCount(0)
        if not isinstance(data, dict):
            return
        for k, v in data.items():
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(str(k)))
            self.table.setItem(r, 1, QTableWidgetItem(str(v)))

    def collect(self):
        out = {}
        for r in range(self.table.rowCount()):
            k = self.table.item(r, 0)
            v = self.table.item(r, 1)
            if k is None:
                continue
            key = k.text().strip()
            if key:
                out[key] = (v.text() if v else "")
        return out


# ============================================================
# 通用列表编辑器（字符串列表）
# ============================================================

class ListEditor(QWidget):
    """带增删按钮的字符串列表编辑（比纯文本框更直观）"""

    def __init__(self, header="名称", parent=None):
        super().__init__(parent)
        self.table = QTableWidget(0, 1)
        self.table.setHorizontalHeaderLabels([header])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)

        btns = QHBoxLayout()
        b_add = QPushButton("新增")
        b_del = QPushButton("删除选中")
        b_add.clicked.connect(self._add)
        b_del.clicked.connect(self._del)
        btns.addWidget(b_add)
        btns.addWidget(b_del)
        btns.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.table)
        lay.addLayout(btns)

    def _add(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(""))
        self.table.editItem(self.table.item(r, 0))

    def _del(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def load(self, data):
        self.table.setRowCount(0)
        for x in (data or []):
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(str(x)))

    def collect(self):
        out = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it is None:
                continue
            v = it.text().strip()
            if v:
                out.append(v)
        return out


# ============================================================
# 表单页面渲染器
# ============================================================

class FormPage(QWidget):
    """按 schema.Page 自动渲染的表单页"""

    changed = Signal()

    def __init__(self, page: "S.Page", parent=None):
        super().__init__(parent)
        self.page = page
        self._getters = {}
        self._setters = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(12)

        if page.desc:
            tip = QLabel(page.desc)
            tip.setWordWrap(True)
            tip.setObjectName("pageDesc")
            tip.setContentsMargins(0, 2, 0, 6)   # QSS padding 有渲染 bug，用代码控制
            outer.addWidget(tip)

        for g in page.groups:
            outer.addWidget(self._build_group(g))
        outer.addStretch(1)

    def _build_group(self, g: "S.Group"):
        box = QGroupBox(g.title)
        grid = QGridLayout(box)
        grid.setContentsMargins(14, 16, 14, 14)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        if g.desc:
            d = QLabel(g.desc)
            d.setWordWrap(True)
            d.setObjectName("groupDesc")
            d.setContentsMargins(0, 0, 0, 6)
            grid.addWidget(d, 0, 0, 1, 2)

        row, col = 1, 0
        for f in g.fields:
            w, get, set_ = make_widget(f)
            self._getters[f.key] = get
            self._setters[f.key] = set_

            if f.type == "switch":
                lab = QLabel(f.label)
                cell = QHBoxLayout()
                cell.setSpacing(8)
                cell.addWidget(w)
                cell.addSpacing(4)
                lab_mouse = ClickableLabel(f.label)
                lab_mouse.clicked.connect(lambda _=None, ww=w: ww.setChecked(not ww.isChecked()))
                if f.tip:
                    lab_mouse.setToolTip(f.tip)
                cell.addWidget(lab_mouse)
                cell.addStretch(1)
                holder = QWidget()
                holder.setLayout(cell)
                item = holder
            else:
                lab = QLabel(f.label)
                lab.setObjectName("fieldLabel")
                if f.tip:
                    lab.setToolTip(f.tip)
                item = w

            span = 2 if (f.span >= 2 or f.type in ("area", "list", "dict")) else 1
            if span == 2:
                if col != 0:
                    row += 1
                    col = 0
                if f.type in ("area", "list", "dict"):
                    grid.addWidget(QLabel(f.label), row, 0, 1, 2)
                    row += 1
                    grid.addWidget(item, row, 0, 1, 2)
                else:
                    grid.addWidget(QLabel(f.label), row, 0)
                    grid.addWidget(item, row, 1)
                row += 1
                col = 0
            else:
                grid.addWidget(QLabel(f.label), row, col * 2)
                grid.addWidget(item, row, col * 2 + 1)
                col += 1
                if col >= 2:
                    col = 0
                    row += 1

            if isinstance(w, QCheckBox):
                w.stateChanged.connect(lambda _=None: self.changed.emit())
            if f.tip and f.type != "switch":
                w.setToolTip(f.tip)

        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        return box

    # ---------- 数据同步 ----------
    def load(self, config: dict):
        for f in self._all_fields():
            val = config.get(f.key, f.default)
            if val is None:
                val = f.default
            set_ = self._setters.get(f.key)
            if not set_:
                continue
            try:
                if f.type == "switch":
                    set_(bool(val))
                elif f.type == "int":
                    set_(int(val))
                else:
                    set_(val)
            except Exception:
                set_(f.default)

    def collect(self) -> dict:
        out = {}
        for f in self._all_fields():
            get = self._getters.get(f.key)
            if not get:
                continue
            try:
                out[f.key] = get()
            except Exception:
                out[f.key] = f.default
        return out

    def _all_fields(self):
        for g in self.page.groups:
            for f in g.fields:
                yield f


class ClickableLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, ev):
        self.clicked.emit()
        super().mouseReleaseEvent(ev)


class NavItem(QFrame):
    """侧边栏导航项：图标 + 文字（对齐 SiverWXbot_plus 原版 .nav-link）。

    样式全部交给 app 级 QSS（QFrame#navItem / [active="true"] / :hover），
    这里只负责：
      - 用布局 margins 做内边距（不用 QSS padding，避免分数缩放文字重影）
      - 按状态换 SVG 图标颜色（图标是矢量渲染，不受字体缩放影响）
    """

    clicked = Signal()

    C_ICON = "#C8C8C8"
    C_ICON_ON = "#FFFFFF"

    def __init__(self, text, icon_name="grid-1x2", parent=None):
        super().__init__(parent)
        from . import icons as _ic
        self._icons = _ic
        self._icon_name = icon_name
        self._active = False
        self._hover = False
        self.setObjectName("navItem")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(36)

        lay = QHBoxLayout(self)
        # 原版 .nav-link padding: 10px 12px; gap: 10px; i{width:20px}
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(10)

        self.icon_lab = QLabel()
        self.icon_lab.setFixedSize(20, 20)
        self.icon_lab.setAlignment(Qt.AlignCenter)

        self.text_lab = QLabel(text)
        self.text_lab.setObjectName("navText")
        self.text_lab.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.text_lab.setWordWrap(False)
        # 不要用 addStretch：stretch 优先级高于 QLabel 的 Preferred 策略，
        # 会把文字挤到最小宽度导致换行（"Webhook 通知" 就被压成两行）
        self.text_lab.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        lay.addWidget(self.icon_lab)
        lay.addWidget(self.text_lab)

        self.setProperty("active", False)
        self._repaint_icon()

    # ---------- 状态 ----------
    def _dpr(self):
        try:
            app = QApplication.instance()
            return max(1.0, float(app.devicePixelRatio())) if app else 1.0
        except Exception:
            return 1.0

    def _repaint_icon(self):
        color = self.C_ICON_ON if (self._active or self._hover) else self.C_ICON
        try:
            self.icon_lab.setPixmap(
                self._icons.pixmap(self._icon_name, color, 16, self._dpr()))
        except Exception:
            pass

    def set_active(self, on: bool):
        self._active = bool(on)
        self.setProperty("active", self._active)
        self.style().unpolish(self)
        self.style().polish(self)
        self._repaint_icon()

    def enterEvent(self, ev):
        self._hover = True
        self._repaint_icon()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hover = False
        self._repaint_icon()
        super().leaveEvent(ev)

    def mouseReleaseEvent(self, ev):
        self.clicked.emit()
        super().mouseReleaseEvent(ev)


class NavDivider(QWidget):
    """侧边栏分隔线（原版 .nav-divider：1px #3a3a3a，margin 12px 16px）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("navDividerWrap")
        self.setFixedHeight(1)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(0)
        line = QFrame()
        line.setObjectName("navDivider")
        line.setFixedHeight(1)
        lay.addWidget(line)


# ============================================================
# 小工具
# ============================================================

def hline():
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    return line


def ask_yes_no(parent, title, text):
    return QMessageBox.question(
        parent, title, text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
    ) == QMessageBox.Yes


def info(parent, title, text):
    QMessageBox.information(parent, title, text)


def warn(parent, title, text):
    QMessageBox.warning(parent, title, text)
