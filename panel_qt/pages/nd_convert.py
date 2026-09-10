# -*- coding: utf-8 -*-
"""分享文案转链：把别人的分享链接转存成自己的，再群发"""

import re
import threading

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QPlainTextEdit, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import register
from ..widgets import info, warn

try:
    import config_manager as CM
except Exception:
    CM = None

PAN_PATTERNS = [
    ("quark", r"pan\.quark\.cn/s/[0-9a-zA-Z]+"),
    ("uc", r"drive\.uc\.cn/s/[0-9a-zA-Z]+"),
    ("baidu", r"pan\.baidu\.com/s/[0-9a-zA-Z_\-]+"),
    ("aliyun", r"(?:www\.)?alipan\.com/s/[0-9a-zA-Z]+"),
    ("xunlei", r"pan\.xunlei\.com/s/[0-9a-zA-Z\-]+"),
    ("mobile", r"(?:caiyun|yun)\.139\.com[^\s]*"),
    ("guangya", r"guangya[^\s]*"),
]
LINK_RE = re.compile("|".join(f"(?P<{k}>{p})" for k, p in PAN_PATTERNS), re.I)

PAN_NAMES = {
    "quark": "夸克", "baidu": "百度", "uc": "UC", "aliyun": "阿里云",
    "xunlei": "迅雷", "guangya": "光鸭", "mobile": "移动",
}


def extract_links(text):
    """从文案中提取 (网盘key, 链接) 列表，保持出现顺序并去重"""
    out, seen = [], set()
    for m in LINK_RE.finditer(text or ""):
        key = m.lastgroup
        url = m.group(0).rstrip("，,。）)】]")
        if url in seen:
            continue
        seen.add(url)
        out.append((key, url))
    return out


@register("nd_convert")
def build(page, mw):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)

    tip = QLabel("粘贴别人的资源分享文案 → 自动识别其中的网盘链接 → 转存到你的网盘并生成新链接 → "
                 "替换原文案后群发。")
    tip.setObjectName("pageDesc")
    tip.setWordWrap(True)
    lay.addWidget(tip)

    # ---------- 文案输入 ----------
    g1 = QGroupBox("① 粘贴原文案")
    g1l = QVBoxLayout(g1)
    g1l.setContentsMargins(14, 16, 14, 16)
    src = QPlainTextEdit()
    src.setPlaceholderText("把别人的分享文案粘贴到这里…")
    src.setMinimumHeight(110)
    g1l.addWidget(src)
    row = QHBoxLayout()
    b_parse = QPushButton("解析链接")
    b_parse.setObjectName("btnPrimary")
    b_parse.setFixedWidth(120)
    lab_count = QLabel("")
    lab_count.setObjectName("groupDesc")
    row.addWidget(b_parse)
    row.addWidget(lab_count)
    row.addStretch(1)
    g1l.addLayout(row)
    lay.addWidget(g1)

    # ---------- 链接表 ----------
    g2 = QGroupBox("② 识别到的链接")
    g2l = QVBoxLayout(g2)
    g2l.setContentsMargins(14, 16, 14, 16)
    table = QTableWidget(0, 4)
    table.setHorizontalHeaderLabels(["网盘", "原链接", "状态", "新链接"])
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
    table.setMinimumHeight(200)
    g2l.addWidget(table)

    prog = QProgressBar()
    prog.setVisible(False)
    prog.setFixedHeight(8)
    prog.setTextVisible(False)
    g2l.addWidget(prog)

    row2 = QHBoxLayout()
    b_run = QPushButton("开始转链")
    b_run.setObjectName("btnPrimary")
    b_copy = QPushButton("复制新文案")
    b_send = QPushButton("群发")
    for b in (b_run, b_copy, b_send):
        b.setFixedWidth(120)
        row2.addWidget(b)
    row2.addStretch(1)
    g2l.addLayout(row2)
    lay.addWidget(g2, 1)

    # ---------- 群发目标 ----------
    g3 = QGroupBox("③ 群发目标")
    g3l = QVBoxLayout(g3)
    g3l.setContentsMargins(14, 16, 14, 16)
    targets = QPlainTextEdit()
    targets.setPlaceholderText("一行一个群名或好友昵称，例如：\n资源分享群\n张三")
    targets.setMinimumHeight(80)
    g3l.addWidget(targets)
    row3 = QHBoxLayout()
    b_import = QPushButton("从监听列表导入")
    b_import.setFixedWidth(150)
    row3.addWidget(b_import)
    row3.addStretch(1)
    g3l.addLayout(row3)
    lay.addWidget(g3)

    links = []

    def on_parse():
        links.clear()
        table.setRowCount(0)
        found = extract_links(src.toPlainText())
        for key, url in found:
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QTableWidgetItem(PAN_NAMES.get(key, key)))
            table.setItem(r, 1, QTableWidgetItem(url))
            table.setItem(r, 2, QTableWidgetItem("待转存"))
            table.setItem(r, 3, QTableWidgetItem(""))
            links.append((key, url))
        lab_count.setText(f"共识别到 {len(found)} 条链接")
        mw.log(f"解析到 {len(found)} 条网盘链接", "SUCCESS" if found else "WARN")

    def on_run():
        if not links:
            warn(mw, "提示", "请先解析链接")
            return
        if CM and not CM.load_config().get("transfer", {}).get("accounts"):
            warn(mw, "提示", "请先在「网盘账号」中配置至少一个账号")
            return
        prog.setVisible(True)
        prog.setRange(0, len(links))
        prog.setValue(0)

        def work():
            try:
                from transfer import base as TB
            except Exception as e:
                mw.log(f"转存引擎加载失败：{e}", "ERROR")
                return
            mapping = {}
            for i, (key, url) in enumerate(links):
                try:
                    adapter_cls = TB.get_adapter(key)
                    if adapter_cls is None:
                        raise RuntimeError(f"暂不支持 {key}")
                    acc = _pick_account(key)
                    if not acc:
                        raise RuntimeError("没有可用账号")
                    res = adapter_cls(acc, cfg=CM.load_config(),
                                       save_fn=CM.save_config).transfer_and_share(url, title="")
                    new_url = res.get("share_url", "")
                    mapping[url] = new_url
                    _set_row(i, "成功", new_url, "#00B42A")
                    mw.log(f"[{PAN_NAMES.get(key, key)}] 转链成功", "SUCCESS")
                except Exception as e:
                    mapping[url] = ""
                    _set_row(i, f"失败：{str(e)[:40]}", "", "#F53F3F")
                    mw.log(f"[{PAN_NAMES.get(key, key)}] 转链失败：{e}", "ERROR")
                prog.setValue(i + 1)
            w._mapping = mapping
            prog.setVisible(False)
            mw.log("转链任务结束", "INFO")

        threading.Thread(target=work, daemon=True).start()

    def _set_row(i, status, new_url, color):
        def _f():
            if i >= table.rowCount():
                return
            it = QTableWidgetItem(status)
            it.setForeground(QColor(color))
            table.setItem(i, 2, it)
            table.setItem(i, 3, QTableWidgetItem(new_url))

        _safe_call(_f)  # 工作线程 -> 主线程

    def on_copy():
        text = src.toPlainText()
        mapping = getattr(w, "_mapping", {}) or {}
        if not mapping:
            warn(mw, "提示", "还没有可替换的新链接，请先转链")
            return
        for old, new in mapping.items():
            if new:
                text = text.replace(old, new)
        QApplication.clipboard().setText(text)
        mw.log("新文案已复制到剪贴板", "SUCCESS")
        info(mw, "已复制", "新文案已复制到剪贴板")

    def on_send():
        tg = [x.strip() for x in targets.toPlainText().splitlines() if x.strip()]
        if not tg:
            warn(mw, "提示", "请填写至少一个群发目标")
            return
        text = src.toPlainText()
        for old, new in (getattr(w, "_mapping", {}) or {}).items():
            if new:
                text = text.replace(old, new)
        if not text.strip():
            warn(mw, "提示", "文案内容为空")
            return

        src_wx = "机器人" if getattr(mw, "sender", None) and mw.sender.using_bot() else "独立微信实例"
        mw.log(f"开始群发到 {len(tg)} 个目标（发送通道：{src_wx}）", "INFO")

        def work():
            try:
                ok, fail = mw.sender.broadcast(tg, text)
                mw.log(f"群发结束：成功 {ok} 个，失败 {fail} 个",
                       "SUCCESS" if fail == 0 else "WARN")
            except Exception as e:
                mw.log(f"群发异常：{e}", "ERROR")

        threading.Thread(target=work, daemon=True).start()

    def on_import():
        names = []
        cfg = getattr(mw, "config", {}) or {}
        names += list(cfg.get("group", []) or [])
        names += list(cfg.get("listen_list", []) or [])
        if not names:
            warn(mw, "提示", "监听列表为空，请先在「群组管理 / 私聊监听」中添加")
            return
        targets.setPlainText("\n".join(names))
        mw.log(f"已导入 {len(names)} 个目标", "SUCCESS")

    b_parse.clicked.connect(on_parse)
    b_run.clicked.connect(on_run)
    b_copy.clicked.connect(on_copy)
    b_send.clicked.connect(on_send)
    b_import.clicked.connect(on_import)

    def load(cfg):
        saved = (CM.load_config().get("convert", {}) if CM else {})
        targets.setPlainText("\n".join(saved.get("targets", []) or []))

    def collect():
        if CM:
            c = CM.load_config()
            c["convert"] = {
                "targets": [x.strip() for x in targets.toPlainText().splitlines() if x.strip()],
            }
            CM.save_config(c)
        return {}

    w.load = load
    w.collect = collect
    return w


def _pick_account(pan):
    if CM is None:
        return None
    for acc in CM.load_config().get("transfer", {}).get("accounts", []):
        if acc.get("pan") == pan and acc.get("enabled", True) and acc.get("cookie"):
            return acc
    return None


def _safe_call(fn):
    """跨线程 UI 更新：投递到主线程执行"""
    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, fn)
