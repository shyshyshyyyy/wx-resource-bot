# -*- coding: utf-8 -*-
"""机器人运行线程：底座 WXBot 跑在 QThread 里，避免卡死界面"""

import traceback

from PySide6.QtCore import QThread, Signal


class BotWorker(QThread):
    logged = Signal(str, str)          # level, text
    state_changed = Signal(str, str)   # state(running/stopped/error), detail

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bot = None
        self._stopping = False

    def run(self):
        try:
            self.logged.emit("INFO", "正在初始化微信内核…")
            import wxbot_core
            bot = wxbot_core.WXBot()
            self._bot = bot
            self.state_changed.emit("running", "运行中")
            self.logged.emit("SUCCESS", "机器人已启动")
            bot.run()          # 阻塞主循环
            if not self._stopping:
                self.logged.emit("WARN", "机器人主循环已退出")
        except Exception as e:
            self.logged.emit("ERROR", f"机器人启动失败：{e}")
            self.logged.emit("ERROR", traceback.format_exc()[-1500:])
            self.state_changed.emit("error", str(e)[:120])
        finally:
            if not self._stopping:
                self.state_changed.emit("stopped", "已停止")

    def stop_bot(self, timeout_ms=8000):
        self._stopping = True
        try:
            if self._bot is not None:
                self._bot.stop()
        except Exception as e:
            self.logged.emit("ERROR", f"停止异常：{e}")
        self.requestInterruption()
        self.wait(timeout_ms)
        if self.isRunning():
            self.terminate()
        self._bot = None
        self.state_changed.emit("stopped", "已停止")
