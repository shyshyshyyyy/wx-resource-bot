# -*- coding: utf-8 -*-
"""PySide6 主窗口：侧边导航 + 页面栈 + 启停控制 + 运行日志"""

import json
import os
import sys
import time
import traceback

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

from core import paths
from . import schema as S
from . import widgets as W
from . import icons as ICONS
from .pages import build_page

try:
    from .pages.about import VERSION as APP_VERSION, BUILD as APP_BUILD
except Exception:          # about 页不可用时兜底
    APP_VERSION, APP_BUILD = "1.0.0", "dev"


class LogBus(QObject):
    """全局日志总线（线程安全：信号投递到主线程）"""
    line = Signal(str, str)   # level, text


LOG_BUS = LogBus()


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("微信资源搜索机器人")
        self.resize(1180, 780)
        self.setMinimumSize(1020, 680)

        self.config = {}
        self._pages = {}          # page_id -> widget
        self._nav_buttons = {}

        # 必须先接上日志总线，否则建页期间的报错（load 失败等）会被丢掉
        LOG_BUS.line.connect(self._append_log)

        self._load_config()
        self._build_ui()

        # 底座日志桥接到面板
        try:
            import logger as _bot_logger
            _bot_logger.register_ui_hook(
                lambda lvl, msg: LOG_BUS.line.emit(str(lvl).upper(), str(msg)))
        except Exception:
            pass

        # 主动发送器（群发 / 转链用）
        from .sender import MessageSender
        self.sender = MessageSender(self)
        self.sender.log.connect(self._append_log)

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(2000)

        self._refresh_license_side()

    # ----------------------------------------------------------
    # 配置
    # ----------------------------------------------------------
    def _load_config(self):
        path = paths.config_file()
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
            else:
                self.config = {}
        except Exception:
            self.config = {}

    def _save_config(self, silent=False):
        """收集所有页面数据 -> 合并 -> 落盘

        安全约束：只收集 **已经成功 load 过** 的页面。
        没 load 过的页面，控件里装的是出厂默认值（SpinBox=最小值、
        CheckBox=未勾选、LineEdit=空），拿去 collect 会把用户真实配置
        冲掉 —— 这就是"盘搜接口重启后没了"的元凶。
        """
        try:
            skipped = []
            for pid, w in self._pages.items():
                if not hasattr(w, "collect"):
                    continue
                if hasattr(w, "load") and not getattr(w, "_loaded", False):
                    skipped.append(pid)
                    continue
                try:
                    self.config.update(w.collect() or {})
                except Exception as e:
                    LOG_BUS.line.emit("ERROR", f"[{pid}] 收集配置失败: {e}")
            if skipped:
                LOG_BUS.line.emit(
                    "WARN", f"{len(skipped)} 个页面未载入配置，已跳过收集："
                            f"{', '.join(skipped)}")
            os.makedirs(os.path.dirname(paths.config_file()), exist_ok=True)
            with open(paths.config_file(), "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
            LOG_BUS.line.emit("INFO", f"配置已保存到 {paths.config_file()}")
            return True
        except Exception as e:
            LOG_BUS.line.emit("ERROR", f"保存配置失败: {e}\n{traceback.format_exc()}")
            return False

    # ----------------------------------------------------------
    # 授权
    # ----------------------------------------------------------
    def _check_license(self):
        """返回 (ok, msg)。未配置授权文件时返回未激活。"""
        try:
            import license as lic
            code = ""
            if os.path.exists(paths.license_file()):
                with open(paths.license_file(), "r", encoding="utf-8") as f:
                    code = f.read().strip()
            if not code:
                return False, "软件未激活"
            r = lic.verify_license(code, current_code=lic.get_machine_code())
            return bool(r.get("ok")), r.get("msg", "")
        except Exception as e:
            return False, f"授权校验失败：{e}"

    def _refresh_license_side(self):
        """刷新侧边栏底部的授权状态"""
        lab = getattr(self, "lab_lic_side", None)
        if lab is None:
            return
        try:
            ok, msg = self._check_license()
            import license as _lic
            code = ""
            if os.path.exists(paths.license_file()):
                with open(paths.license_file(), "r", encoding="utf-8") as f:
                    code = f.read().strip()
            if not code:
                lab.setText("未激活")
                lab.setStyleSheet("color:#F76965;font-weight:600;")
                return
            r = _lic.verify_license(code, current_code=_lic.get_machine_code())
            if r.get("ok"):
                left = _lic.days_left(r)
                lab.setText("永久" if left < 0 else f"剩余 {left} 天")
                lab.setStyleSheet("color:#49CB7F;font-weight:600;")
            else:
                lab.setText("已失效")
                lab.setStyleSheet("color:#F76965;font-weight:600;")
        except Exception:
            lab.setText("-")
            lab.setStyleSheet("color:#6E7A8F;font-weight:600;")

    # ----------------------------------------------------------
    # 界面
    # ----------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self._build_topbar())

        self.stack = QStackedWidget()
        for p in S.PAGES:
            w = build_page(p, self)
            self._pages[p.id] = w
            if isinstance(w, QWidget) and not isinstance(w, QScrollArea):
                sa = QScrollArea()
                sa.setWidgetResizable(True)
                sa.setFrameShape(QScrollArea.NoFrame)
                w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                sa.setWidget(w)
                self.stack.addWidget(sa)
            else:
                self.stack.addWidget(w)

        rl.addWidget(self.stack, 1)
        rl.addWidget(self._build_log_panel())
        root.addWidget(right, 1)

        # 默认首页
        self._switch_page("status")

    def _build_sidebar(self):
        """对齐 SiverWXbot_plus 原版：深灰侧栏 + 图标导航 + 分组用分隔线"""
        sb = QWidget()
        sb.setObjectName("sidebar")
        sb.setFixedWidth(220)
        outer = QVBoxLayout(sb)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 25 个菜单项 + 分隔线总高远超窗口高度，必须可滚动
        # （原版 CSS 也是 .sidebar{overflow-y:auto}）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setObjectName("navScroll")

        inner = QWidget()
        inner.setObjectName("navBox")
        lay = QVBoxLayout(inner)
        # 原版 .sidebar padding: 16px 0；.nav-item margin-bottom: 2px
        lay.setContentsMargins(0, 16, 0, 16)
        lay.setSpacing(2)

        for idx, (section, pages) in enumerate(S.pages_by_section().items()):
            if idx > 0:
                lay.addSpacing(11)
                d = W.NavDivider()
                lay.addWidget(d)
                lay.addSpacing(11)
            for p in pages:
                b = W.NavItem(p.title, ICONS.PAGE_ICON.get(p.id, "grid-1x2"))
                b.setToolTip(p.desc or p.title)
                b.clicked.connect(lambda _=None, pid=p.id: self._switch_page(pid))
                lay.addWidget(b)
                self._nav_buttons[p.id] = b

        lay.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        # ---------- 底部：版本 / 授权（固定不滚动） ----------
        d2 = W.NavDivider()
        outer.addWidget(d2)

        foot = QWidget()
        foot.setObjectName("sideFoot")
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(16, 10, 16, 10)
        fl.setSpacing(3)
        v_lab = QLabel("版本 %s" % APP_VERSION)
        v_lab.setObjectName("sideFootLabel")
        self.lab_lic_side = QLabel("未激活")
        self.lab_lic_side.setObjectName("sideFootValue")
        fl.addWidget(v_lab)
        fl.addWidget(self.lab_lic_side)
        outer.addWidget(foot)
        return sb

    def _build_topbar(self):
        """对齐原版 .topbar：深灰 56px，左侧品牌，右侧操作"""
        bar = QWidget()
        bar.setObjectName("topbar")
        bar.setFixedHeight(56)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(10)

        logo = QLabel()
        logo.setFixedSize(22, 22)
        try:
            logo.setPixmap(ICONS.pixmap("grid-1x2", "#07C160", 20))
        except Exception:
            pass
        lay.addWidget(logo)

        brand = QLabel("微信资源搜索机器人")
        brand.setObjectName("brandTitle")
        lay.addWidget(brand)

        lay.addSpacing(14)
        self.lab_page_title = QLabel("状态面板")
        self.lab_page_title.setObjectName("pageTitle")
        lay.addWidget(self.lab_page_title)

        self.lab_page_desc = QLabel("")
        self.lab_page_desc.setObjectName("pageDescTop")
        lay.addWidget(self.lab_page_desc)

        lay.addStretch(1)

        self.lab_state = QLabel("未启动")
        self.lab_state.setObjectName("runState")
        self.lab_state.setProperty("state", "stopped")
        lay.addWidget(self.lab_state)
        lay.addSpacing(10)

        self.btn_start = QPushButton("启动机器人")
        self.btn_start.setObjectName("btnStart")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self.on_start)

        self.btn_stop = QPushButton("停止机器人")
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.on_stop)

        self.btn_restart = QPushButton("重启载入")
        self.btn_restart.setObjectName("btnRestart")
        self.btn_restart.setCursor(Qt.PointingHandCursor)
        self.btn_restart.setToolTip("重启机器人并重新载入配置")
        self.btn_restart.clicked.connect(self.on_restart)

        self.btn_load = QPushButton("加载配置")
        self.btn_load.setObjectName("btnGhost")
        self.btn_load.setCursor(Qt.PointingHandCursor)
        self.btn_load.clicked.connect(self.on_load)

        self.btn_save = QPushButton("保存配置")
        self.btn_save.setObjectName("btnPrimary")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.clicked.connect(self.on_save)

        lay.addWidget(self.btn_start)
        lay.addWidget(self.btn_stop)
        lay.addWidget(self.btn_restart)
        lay.addWidget(self.btn_load)
        lay.addWidget(self.btn_save)
        return bar

    def _build_log_panel(self):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(18, 8, 18, 12)
        lay.setSpacing(6)

        head = QHBoxLayout()
        lab = QLabel("运行日志")
        lab.setObjectName("hint")
        self.btn_clear_log = QPushButton("清空")
        self.btn_clear_log.setObjectName("btnGhost")
        self.btn_clear_log.setFixedWidth(64)
        self.btn_clear_log.clicked.connect(lambda: self.log_view.clear())
        head.addWidget(lab)
        head.addStretch(1)
        head.addWidget(self.btn_clear_log)

        self.log_view = QTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(150)

        lay.addLayout(head)
        lay.addWidget(self.log_view)
        return box

    # ----------------------------------------------------------
    # 页面切换
    # ----------------------------------------------------------
    def _switch_page(self, pid: str):
        cur = None
        for i, p in enumerate(S.PAGES):
            if p.id == pid:
                self.stack.setCurrentIndex(i)
                cur = p
                break
        for k, b in self._nav_buttons.items():
            b.set_active(k == pid)
        if cur is not None:
            self.lab_page_title.setText(cur.title)
            self.lab_page_desc.setText(cur.desc or "")
            self.lab_page_desc.setVisible(bool(cur.desc))

    # ----------------------------------------------------------
    # 日志
    # ----------------------------------------------------------
    def _append_log(self, level: str, text: str):
        ts = time.strftime("%H:%M:%S")
        # 日志面板是深色底（#1A1A1A），这里一律用浅色前景
        color = {"INFO": "#C8C8C8", "WARN": "#FFC300",
                 "ERROR": "#FA5151", "SUCCESS": "#38D98A"}.get(level, "#C8C8C8")
        self.log_view.append(
            f'<span style="color:#888888">[{ts}]</span> '
            f'<span style="color:{color}">{text}</span>'
        )
        c = self.log_view.textCursor()
        c.movePosition(QTextCursor.End)
        self.log_view.setTextCursor(c)

    def log(self, text, level="INFO"):
        LOG_BUS.line.emit(level, text)

    # ----------------------------------------------------------
    # 按钮动作
    # ----------------------------------------------------------
    def on_save(self):
        if self._save_config():
            W.info(self, "保存成功", f"配置已写入：\n{paths.config_file()}")

    def on_load(self):
        self._load_config()
        bad = 0
        for pid, w in self._pages.items():
            if hasattr(w, "load"):
                try:
                    w.load(self.config)
                    w._loaded = True
                except Exception as e:
                    bad += 1
                    w._loaded = False
                    self.log(f"[{pid}] 载入配置失败: {e}", "ERROR")
        self.log("配置已从磁盘重新载入" + (f"（{bad} 个页面失败）" if bad else ""),
                 "ERROR" if bad else "SUCCESS")

    # ----------------------------------------------------------
    # 机器人启停
    # ----------------------------------------------------------
    def on_start(self):
        if getattr(self, "worker", None) and self.worker.isRunning():
            self.log("机器人已在运行中", "WARN")
            return

        ok, msg = self._check_license()
        if not ok:
            from PySide6.QtWidgets import QMessageBox
            self.log(f"授权校验未通过：{msg}", "ERROR")
            QMessageBox.warning(
                self, "未授权",
                f"{msg}\n\n请到「授权激活」页面完成激活后再启动机器人。")
            self._switch_page("license")
            return

        self._save_config(silent=True)

        # 首次使用保护：没有任何监听对象时机器人不会回复任何人
        try:
            no_target = (not (self.config.get("listen_list") or [])
                         and not (self.config.get("group") or []))
            if no_target:
                from PySide6.QtWidgets import QMessageBox
                ret = QMessageBox.question(
                    self, "没有监听对象",
                    "当前没有配置任何监听好友或群聊，机器人启动后不会回复任何人。\n\n"
                    "建议先到「私聊监听」或「群组管理」添加对象。\n\n仍要启动吗？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if ret != QMessageBox.Yes:
                    self.log("已取消启动：请先配置监听对象", "WARN")
                    return
        except Exception:
            pass

        from .bot_runner import BotWorker
        self.worker = BotWorker(self)
        self.worker.logged.connect(self._append_log)
        self.worker.state_changed.connect(self._on_state)
        self.worker.start()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._set_state("running", "启动中…")

    def on_stop(self):
        if not getattr(self, "worker", None):
            return
        self.log("正在停止机器人…", "WARN")
        self.worker.stop_bot()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._set_state("stopped", "已停止")

    def on_restart(self):
        self.on_stop()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1200, self.on_start)

    def _on_state(self, state, detail):
        self._set_state(state, detail)

    def _set_state(self, state, text):
        if not hasattr(self, "lab_state"):
            return
        self.lab_state.setText(text)
        self.lab_state.setProperty("state", state)
        self.lab_state.style().unpolish(self.lab_state)
        self.lab_state.style().polish(self.lab_state)

    def _refresh_status(self):
        """定时刷新运行状态"""
        w = getattr(self, "worker", None)
        if w is None:
            return
        alive = w.isRunning()
        if not alive and self.btn_stop.isEnabled():
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self._set_state("stopped", "已停止")
