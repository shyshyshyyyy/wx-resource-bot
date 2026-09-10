# -*- coding: utf-8 -*-
"""模型配置：多 AI 接口管理"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import register
from ..widgets import info

SDK_OPTIONS = ["OpenAI API 格式兼容接口", "Dify", "Coze", "DusAPI"]


@register("api")
def build(page, mw):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)

    tip = QLabel("配置多个 AI 接口，可在私聊/群聊/图片识别中分别指定使用哪一个。")
    tip.setObjectName("pageDesc")
    tip.setWordWrap(True)
    lay.addWidget(tip)

    g = QGroupBox("接口列表")
    gl = QVBoxLayout(g)
    gl.setContentsMargins(14, 16, 14, 14)

    table = QTableWidget(0, 4)
    table.setHorizontalHeaderLabels(["类型", "API Key", "接口地址", "模型 / 标识"])
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
    table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
    table.setMinimumHeight(240)
    gl.addWidget(table)

    btns = QHBoxLayout()
    b_add = QPushButton("新增接口")
    b_del = QPushButton("删除选中")
    b_test = QPushButton("测试选中接口")
    b_add.clicked.connect(lambda: _add(table))
    b_del.clicked.connect(lambda: _del(table))
    b_test.clicked.connect(lambda: _test(table, mw))
    btns.addWidget(b_add)
    btns.addWidget(b_del)
    btns.addWidget(b_test)
    btns.addStretch(1)
    gl.addLayout(btns)
    lay.addWidget(g)

    g2 = QGroupBox("当前默认接口")
    g2l = QHBoxLayout(g2)
    g2l.setContentsMargins(14, 16, 14, 14)
    g2l.addWidget(QLabel("默认使用"))
    combo = QComboBox()
    combo.setMinimumWidth(220)
    g2l.addWidget(combo)
    g2l.addStretch(1)
    lay.addWidget(g2)

    lay.addStretch(1)

    def _refresh_combo(n):
        combo.blockSignals(True)
        combo.clear()
        for i in range(n):
            combo.addItem(f"接口 {i + 1}")
        combo.blockSignals(False)

    def load(cfg):
        items = cfg.get("api_configs", []) or []
        table.setRowCount(0)
        for it in items:
            r = table.rowCount()
            table.insertRow(r)
            cb = QComboBox()
            cb.addItems(SDK_OPTIONS)
            cb.setCurrentText(str(it.get("sdk", "") or SDK_OPTIONS[0]))
            table.setCellWidget(r, 0, cb)
            for c, key in enumerate(("key", "url", "model"), start=1):
                le = QLineEdit(str(it.get(key, "") or ""))
                if key == "key":
                    le.setEchoMode(QLineEdit.Password)
                table.setCellWidget(r, c, le)
        _refresh_combo(table.rowCount())
        idx = int(cfg.get("api_index", 0) or 0)
        if 0 <= idx < combo.count():
            combo.setCurrentIndex(idx)

    def collect():
        out = []
        for r in range(table.rowCount()):
            sdkw = table.cellWidget(r, 0)
            kw = table.cellWidget(r, 1)
            uw = table.cellWidget(r, 2)
            mw_ = table.cellWidget(r, 3)
            out.append({
                "sdk": sdkw.currentText() if sdkw else "",
                "key": kw.text().strip() if kw else "",
                "url": uw.text().strip() if uw else "",
                "model": mw_.text().strip() if mw_ else "",
            })
        return {"api_configs": out, "api_index": combo.currentIndex()}

    _add(table)
    w.load = load
    w.collect = collect
    return w


def _add(table):
    r = table.rowCount()
    table.insertRow(r)
    cb = QComboBox()
    cb.addItems(SDK_OPTIONS)
    table.setCellWidget(r, 0, cb)
    for c in range(1, 4):
        le = QLineEdit()
        if c == 1:
            le.setEchoMode(QLineEdit.Password)
            le.setPlaceholderText("sk-...")
        elif c == 2:
            le.setPlaceholderText("https://api.xxx.com/v1")
        else:
            le.setPlaceholderText("gpt-4o-mini")
        table.setCellWidget(r, c, le)


def _del(table):
    for r in sorted({i.row() for i in table.selectedIndexes()}, reverse=True):
        table.removeRow(r)


def _test(table, mw):
    r = table.currentRow()
    if r < 0:
        info(mw, "提示", "请先选中一个接口")
        return
    sdkw = table.cellWidget(r, 0)
    kw = table.cellWidget(r, 1)
    uw = table.cellWidget(r, 2)
    mww = table.cellWidget(r, 3)
    cfg = {
        "api_configs": [{
            "sdk": sdkw.currentText() if sdkw else "",
            "key": kw.text() if kw else "",
            "url": uw.text() if uw else "",
            "model": mww.text() if mww else "",
        }],
        "api_index": 0,
    }
    try:
        import wxbot_core  # 延迟导入，避免面板启动时就拉起微信内核
        bot = wxbot_core.WXBot.__new__(wxbot_core.WXBot)
        conf = wxbot_core.WXBotConfig.__new__(wxbot_core.WXBotConfig)
        conf.api_configs = cfg["api_configs"]
        conf.api_index = 0
        conf.api_sdk = cfg["api_configs"][0]["sdk"]
        conf.api_key = cfg["api_configs"][0]["key"]
        conf.base_url = cfg["api_configs"][0]["url"]
        conf.model1 = cfg["api_configs"][0]["model"]
        bot.config = conf
        api = bot._init_api()
        reply = api.chat("你好，请用一句话回复：测试成功")
        info(mw, "测试成功", str(reply)[:300])
    except Exception as e:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(mw, "测试失败", str(e)[:500])
