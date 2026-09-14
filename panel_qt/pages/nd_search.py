# -*- coding: utf-8 -*-
"""盘搜接口配置：数据源 + 启用的网盘类型"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget, QComboBox, QPlainTextEdit,
    QFileDialog,
)

from . import register
from ..widgets import info, warn

try:
    import config_manager as CM
except Exception:
    CM = None
try:
    from search import pansou_client as PC
except Exception:
    PC = None
try:
    from search import imported as IMP
except Exception:
    IMP = None


def _norm(url: str) -> str:
    """保存前把地址归一化（去掉重复的 /api/search）"""
    u = (url or "").strip().rstrip("/")
    if PC is not None and hasattr(PC, "norm_base"):
        return PC.norm_base(u)
    return u

PAN_TYPES = [
    ("quark", "夸克"), ("baidu", "百度"), ("uc", "UC"), ("aliyun", "阿里云"),
    ("xunlei", "迅雷"), ("guangya", "光鸭"), ("mobile", "移动"),
]


class ChipButton(QPushButton):
    def __init__(self, key, text):
        super().__init__(text)
        self.key = key
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(30)
        self.setMinimumWidth(78)
        # setChecked 不是虚函数，C++ 点击路径不会走到 Python override，
        # 但 toggled 信号一定会发，靠它刷新样式才能保证点击后外观跟着变。
        self.toggled.connect(self._style)
        self._style()

    def _style(self):
        if self.isChecked():
            self.setStyleSheet(
                "background:#E8F3FF;color:#1664FF;border:1px solid #1664FF;"
                "border-radius:15px;font-weight:600;")
        else:
            self.setStyleSheet(
                "background:#FFFFFF;color:#86909C;border:1px solid #E5E6EB;"
                "border-radius:15px;")

    def setChecked(self, v):
        # 保留 override 保证程序化设值（如 load()）也能立刻刷新。
        super().setChecked(v)
        self._style()


@register("nd_search")
def build(page, mw):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)

    tip = QLabel("资源搜索的数据源。默认使用远程盘搜接口（你已经部署好的那台），"
                 "也可接入本地 pansou。")
    tip.setObjectName("pageDesc")
    tip.setWordWrap(True)
    lay.addWidget(tip)

    # ---------- 数据源 ----------
    g1 = QGroupBox("搜索数据源")
    gl = QGridLayout(g1)
    gl.setContentsMargins(14, 16, 14, 16)
    gl.setVerticalSpacing(10)

    combo_mode = QComboBox()
    combo_mode.addItems(["remote", "local", "both"])
    combo_mode.setToolTip("remote=仅远程接口；local=仅本地 pansou；both=两者合并")
    gl.addWidget(QLabel("搜索模式"), 0, 0)
    gl.addWidget(combo_mode, 0, 1)

    e_url = QLineEdit()
    e_url.setPlaceholderText("http://38.92.9.77:8888")
    gl.addWidget(QLabel("接口地址"), 1, 0)
    gl.addWidget(e_url, 1, 1, 1, 2)

    e_token = QLineEdit()
    e_token.setPlaceholderText("可留空")
    e_token.setEchoMode(QLineEdit.Password)
    gl.addWidget(QLabel("接口 Token"), 2, 0)
    gl.addWidget(e_token, 2, 1, 1, 2)

    sp_timeout = QSpinBox()
    sp_timeout.setRange(3, 120)
    gl.addWidget(QLabel("超时（秒）"), 3, 0)
    gl.addWidget(sp_timeout, 3, 1)

    btn_test = QPushButton("测试接口")
    btn_test.setFixedWidth(120)
    gl.addWidget(btn_test, 4, 1, alignment=Qt.AlignLeft)
    gl.setColumnStretch(2, 1)
    lay.addWidget(g1)

    # ---------- 本地 pansou ----------
    g2 = QGroupBox("本地 pansou（可选）")
    g2l = QGridLayout(g2)
    g2l.setContentsMargins(14, 16, 14, 16)
    g2l.setVerticalSpacing(10)
    e_exe = QLineEdit()
    e_exe.setPlaceholderText("bin/pansou.exe")
    sp_port = QSpinBox()
    sp_port.setRange(1, 65535)
    e_ch = QLineEdit()
    e_ch.setPlaceholderText("tgsearchers3")
    ck_auto = QPushButton("随程序启动")
    ck_auto.setCheckable(True)
    ck_auto.setFixedHeight(30)
    ck_auto.setMinimumWidth(110)

    g2l.addWidget(QLabel("程序路径"), 0, 0)
    g2l.addWidget(e_exe, 0, 1, 1, 2)
    g2l.addWidget(QLabel("服务端口"), 1, 0)
    g2l.addWidget(sp_port, 1, 1)
    g2l.addWidget(QLabel("频道"), 2, 0)
    g2l.addWidget(e_ch, 2, 1, 1, 2)
    g2l.addWidget(QLabel(""), 3, 0)
    g2l.addWidget(ck_auto, 3, 1, alignment=Qt.AlignLeft)
    g2l.setColumnStretch(2, 1)
    lay.addWidget(g2)

    # ---------- 网盘类型 ----------
    g3 = QGroupBox("启用的网盘类型")
    g3l = QVBoxLayout(g3)
    g3l.setContentsMargins(14, 16, 14, 16)
    chips_row = QHBoxLayout()
    chips_row.setSpacing(8)
    chips = {}
    for key, name in PAN_TYPES:
        c = ChipButton(key, name)
        chips[key] = c
        chips_row.addWidget(c)
    chips_row.addStretch(1)
    g3l.addLayout(chips_row)
    hint = QLabel("只有勾选的类型才会参与搜索；某个类型没有配置可用账号时，"
                 "会自动回落返回原始链接。")
    hint.setObjectName("groupDesc")
    hint.setWordWrap(True)
    g3l.addWidget(hint)
    lay.addWidget(g3)

    # ---------- 结果条数 ----------
    g4 = QGroupBox("结果展示")
    g4l = QGridLayout(g4)
    g4l.setContentsMargins(14, 16, 14, 16)
    sp_page = QSpinBox()
    sp_page.setRange(1, 50)
    sp_max = QSpinBox()
    sp_max.setRange(10, 500)
    sp_ttl = QSpinBox()
    sp_ttl.setRange(30, 3600)
    g4l.addWidget(QLabel("每页条数"), 0, 0)
    g4l.addWidget(sp_page, 0, 1)
    g4l.addWidget(QLabel("最多结果"), 0, 2)
    g4l.addWidget(sp_max, 0, 3)
    g4l.addWidget(QLabel("选号上下文有效期（秒）"), 1, 0)
    g4l.addWidget(sp_ttl, 1, 1)
    ad_lbl = QLabel("广告词过滤")
    ad_lbl.setToolTip("搜索结果中，标题含这些词的资源会被剔除（去广告/引流）。\n每行一个，或用逗号分隔；留空表示不过滤。")
    e_ad = QPlainTextEdit()
    e_ad.setPlaceholderText("每行一个广告词，例如：\n加微信\n关注公众号\n点击链接")
    e_ad.setFixedHeight(64)
    g4l.addWidget(ad_lbl, 2, 0, alignment=Qt.AlignTop)
    g4l.addWidget(e_ad, 2, 1, 1, 4)

    ck_req_pan = QPushButton("指令必须指定网盘类型")
    ck_req_pan.setCheckable(True)
    ck_req_pan.setFixedHeight(30)
    ck_req_pan.setMinimumWidth(160)
    ck_req_pan.setToolTip("开启后，用户发「搜索 关键词」不带网盘类型时，"
                          "会提示先选类型，而不是直接返回混合结果。")
    g4l.addWidget(ck_req_pan, 3, 0, 1, 2)
    g4l.setColumnStretch(4, 1)
    lay.addWidget(g4)

    # ---------- 本地资源导入 ----------
    g5 = QGroupBox("本地资源导入（顾客需求：自有资源跳过转存）")
    g5l = QVBoxLayout(g5)
    g5l.setContentsMargins(14, 16, 14, 16)
    g5l.setSpacing(10)
    tip_imp = QLabel(
        "支持 xlsx / csv。标准列（表头含关键字即可，顺序不限）：\n"
        "名称、链接（必填）；提取码（可选）；网盘类型（可选，留空按链接自动识别）；"
        "是否自己的（是/否/1/0，默认否）。\n"
        "导入后，用户发「搜索 关键词」会混排这些资源；标「是自己的」项获取时跳过转存、直接给原链。")
    tip_imp.setObjectName("groupDesc")
    tip_imp.setWordWrap(True)
    g5l.addWidget(tip_imp)

    row_imp = QHBoxLayout()
    b_imp = QPushButton("选择表格导入")
    b_imp.setFixedWidth(140)
    b_clear_imp = QPushButton("清空导入")
    b_clear_imp.setFixedWidth(110)
    row_imp.addWidget(b_imp)
    row_imp.addWidget(b_clear_imp)
    row_imp.addStretch(1)
    g5l.addLayout(row_imp)

    lab_imp = QLabel("当前导入：0 条")
    lab_imp.setObjectName("groupDesc")
    lab_imp.setWordWrap(True)
    g5l.addWidget(lab_imp)
    lay.addWidget(g5)

    lay.addStretch(1)

    # ---------- 数据同步 ----------
    def load(cfg):
        if CM is None:
            return
        c = CM.load_config(True)
        s = c.get("search", {})
        combo_mode.setCurrentText(str(s.get("mode", "remote")))
        r = s.get("remote", {})
        e_url.setText(str(r.get("base_url", "")))
        e_token.setText(str(r.get("token", "")))
        sp_timeout.setValue(int(r.get("timeout", 20) or 20))
        l = s.get("local", {})
        e_exe.setText(str(l.get("exe", "bin/pansou.exe")))
        sp_port.setValue(int(l.get("port", 8888) or 8888))
        e_ch.setText(str(l.get("channels", "") or ""))
        ck_auto.setChecked(bool(l.get("autostart", True)))
        ck_auto._style() if hasattr(ck_auto, "_style") else None
        types = set(s.get("default_types", []))
        for k, c2 in chips.items():
            c2.setChecked(k in types)
        sp_page.setValue(int(s.get("page_size", 10) or 10))
        sp_max.setValue(int(s.get("max_results", 60) or 60))
        sp_ttl.setValue(int(s.get("session_ttl", 300) or 300))
        e_ad.setPlainText(str(s.get("ad_words", "") or ""))
        ck_req_pan.setChecked(bool(s.get("require_pan_type", False)))
        # 刷新「本地资源导入」计数
        try:
            n = IMP.count_imported() if IMP else 0
        except Exception:
            n = 0
        ipath = (c.get("imported", {}).get("path", "") if CM else "") or ""
        lab_imp.setText("当前导入：%d 条" % n +
                        ("\n来源：%s" % ipath if ipath else ""))

    def collect():
        if CM is None:
            return {}
        c = CM.load_config()
        sel = [k for k, c2 in chips.items() if c2.isChecked()]
        c["search"] = {
            "mode": combo_mode.currentText(),
            "local": {
                "enabled": combo_mode.currentText() in ("local", "both"),
                "exe": e_exe.text().strip(),
                "port": sp_port.value(),
                "channels": e_ch.text().strip(),
                "extra_env": c.get("search", {}).get("local", {}).get("extra_env", {}),
                "autostart": ck_auto.isChecked(),
            },
            "remote": {
                "enabled": combo_mode.currentText() in ("remote", "both"),
                "base_url": _norm(e_url.text()),
                "token": e_token.text().strip(),
                "timeout": sp_timeout.value(),
            },
            "page_size": sp_page.value(),
            "max_results": sp_max.value(),
            "session_ttl": sp_ttl.value(),
            "ad_words": e_ad.toPlainText().strip(),
            "default_types": sel,
            "require_pan_type": ck_req_pan.isChecked(),
        }
        CM.save_config(c)
        return {}

    def on_test():
        url = _norm(e_url.text())
        if not url:
            warn(mw, "提示", "请先填写接口地址")
            return
        # 地址填的是根地址，这里再拼接口路径（与实际搜索走同一套拼接规则）
        api = url + "/api/search"
        try:
            import requests
            headers = {"Content-Type": "application/json"}
            tok = e_token.text().strip()
            if tok:
                headers["Authorization"] = "Bearer %s" % tok
            to = max(3, sp_timeout.value())
            r = requests.post(api, json={"kw": "测试", "res": "merge", "src": "all"},
                              headers=headers, timeout=to)
            if r.status_code == 405:      # 个别部署只开了 GET
                r = requests.get(api, params={"kw": "测试", "cloud_types": "quark"},
                                 headers=headers, timeout=to)
            r.raise_for_status()
            data = r.json()
            merged = (data.get("data") or {}).get("merged_by_type", {})
            total = sum(len(v) for v in merged.values()) if merged else 0
            info(mw, "接口可用",
                 f"请求地址：{api}\nHTTP {r.status_code}\n"
                 f"返回网盘类型：{list(merged.keys())}\n结果条数：{total}")
            mw.log(f"盘搜接口测试通过，{total} 条结果", "SUCCESS")
        except Exception as e:
            warn(mw, "测试失败", f"请求地址：{api}\n\n{str(e)[:400]}")
            mw.log(f"盘搜接口测试失败：{e}", "ERROR")

    btn_test.clicked.connect(on_test)

    def _refresh_imp_label():
        try:
            n = IMP.count_imported() if IMP else 0
        except Exception:
            n = 0
        path = ""
        if CM:
            path = CM.load_config().get("imported", {}).get("path", "") or ""
        lab_imp.setText(
            "当前导入：%d 条" % n +
            ("\n来源：%s" % path if path else ""))

    def on_import():
        if IMP is None:
            warn(mw, "提示", "导入模块加载失败")
            return
        path, _ = QFileDialog.getOpenFileName(
            mw, "选择资源表格", "", "表格文件 (*.xlsx *.csv)")
        if not path:
            return
        try:
            count, errs = IMP.import_table(path)
        except Exception as e:
            warn(mw, "导入失败", str(e)[:400])
            mw.log("本地资源导入失败：%s" % e, "ERROR")
            return
        if CM:
            c = CM.load_config()
            c.setdefault("imported", {})["path"] = path
            c["imported"]["enabled"] = True
            CM.save_config(c)
        _refresh_imp_label()
        msg = "成功导入 %d 条资源" % count
        if errs:
            msg += "\n\n跳过 %d 行：\n%s" % (len(errs), "\n".join(errs[:20]))
        info(mw, "导入完成", msg)
        mw.log("本地资源导入 %d 条（来自 %s）" % (count, path), "SUCCESS")

    def on_clear_import():
        if IMP is None:
            warn(mw, "提示", "导入模块加载失败")
            return
        if IMP.clear_imported():
            _refresh_imp_label()
            info(mw, "已清空", "本地导入的资源已全部清除。")
            mw.log("已清空本地导入资源", "WARN")
        else:
            warn(mw, "提示", "清空失败")

    b_imp.clicked.connect(on_import)
    b_clear_imp.clicked.connect(on_clear_import)

    w.load = load
    w.collect = collect
    return w
