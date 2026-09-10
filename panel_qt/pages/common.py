# -*- coding: utf-8 -*-
"""通用列表/规则表格编辑组件，供自定义转发、定时任务、朋友圈等复用"""

import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView,
    QLineEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)


def new_id():
    return uuid.uuid4().hex[:8]


class RuleTable(QWidget):
    """
    编辑 list[dict] 类型的配置。
    columns: [{"key","label","type","options","width"}]
    type 支持: text | int | switch | select | list(逗号分隔)
    """

    def __init__(self, columns, defaults=None, parent=None, min_height=240):
        super().__init__(parent)
        self.columns = columns
        self.defaults = defaults or {}

        self.table = QTableWidget(0, len(columns) + 1)
        headers = [c["label"] for c in columns] + ["启用"]
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setMinimumHeight(min_height)

        for i, c in enumerate(columns):
            if c.get("stretch", True):
                self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.Stretch)
            else:
                self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            len(columns), QHeaderView.ResizeToContents)

        btns = QHBoxLayout()
        self.b_add = QPushButton("新增")
        self.b_del = QPushButton("删除选中")
        self.b_add.clicked.connect(self._add)
        self.b_del.clicked.connect(self._del)
        btns.addWidget(self.b_add)
        btns.addWidget(self.b_del)
        btns.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.table)
        lay.addLayout(btns)

        self._ids = []

    # ---------------- 行操作 ----------------
    def _add(self, data=None):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self._ids.append(data.get("id") if data and data.get("id") else new_id())
        d = dict(self.defaults)
        if data:
            d.update(data)
        for c, col in enumerate(self.columns):
            val = d.get(col["key"], col.get("default", ""))
            t = col.get("type", "text")
            if t == "switch":
                ck = QCheckBox()
                ck.setChecked(bool(val))
                cell = QWidget()
                h = QHBoxLayout(cell)
                h.setContentsMargins(0, 0, 0, 0)
                h.setAlignment(Qt.AlignCenter)
                h.addWidget(ck)
                self.table.setCellWidget(r, c, cell)
            elif t == "int":
                sp = QSpinBox()
                sp.setRange(col.get("min", 0), col.get("max", 999999))
                sp.setValue(int(val or 0))
                self.table.setCellWidget(r, c, sp)
            elif t == "select":
                cb = QComboBox()
                cb.addItems(col.get("options", []))
                if val in col.get("options", []):
                    cb.setCurrentText(str(val))
                self.table.setCellWidget(r, c, cb)
            elif t == "lines":
                te = QTextEdit()
                te.setPlainText("\n".join(str(x) for x in (val or [])))
                te.setMinimumHeight(col.get("height", 54))
                te.setPlaceholderText(col.get("placeholder", "一行一条"))
                self.table.setCellWidget(r, c, te)
            else:
                le = QLineEdit(self._fmt(val))
                le.setPlaceholderText(col.get("placeholder", ""))
                self.table.setCellWidget(r, c, le)

        ck = QCheckBox()
        ck.setChecked(bool(d.get("enabled", True)))
        cell = QWidget()
        h = QHBoxLayout(cell)
        h.setContentsMargins(0, 0, 0, 0)
        h.setAlignment(Qt.AlignCenter)
        h.addWidget(ck)
        self.table.setCellWidget(r, len(self.columns), cell)

    @staticmethod
    def _fmt(val):
        if isinstance(val, (list, tuple)):
            return ",".join(str(x) for x in val)
        return "" if val is None else str(val)

    def _del(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            if 0 <= r < len(self._ids):
                self._ids.pop(r)
            self.table.removeRow(r)

    # ---------------- 数据 ----------------
    def load(self, data):
        self.table.setRowCount(0)
        self._ids = []
        for item in (data or []):
            self._add(item)

    def collect(self):
        out = []
        for r in range(self.table.rowCount()):
            row = {}
            if r < len(self._ids):
                row["id"] = self._ids[r]
            for c, col in enumerate(self.columns):
                w = self.table.cellWidget(r, c)
                t = col.get("type", "text")
                if t == "switch":
                    row[col["key"]] = w.findChild(QCheckBox).isChecked()
                elif t == "int":
                    row[col["key"]] = w.value()
                elif t == "select":
                    row[col["key"]] = w.currentText()
                elif t == "list":
                    row[col["key"]] = [x.strip() for x in w.text().split(",") if x.strip()]
                elif t == "lines":
                    row[col["key"]] = [x.strip() for x in w.toPlainText().splitlines() if x.strip()]
                else:
                    row[col["key"]] = w.text().strip()
            en = self.table.cellWidget(r, len(self.columns))
            row["enabled"] = en.findChild(QCheckBox).isChecked()
            out.append(row)
        return out
