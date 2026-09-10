# -*- coding: utf-8 -*-
"""消息发送器

优先复用正在运行的机器人所持有的微信实例（避免多实例抢占微信窗口），
机器人未运行时才自己创建一个。
"""

import time

from PySide6.QtCore import QObject, Signal


class MessageSender(QObject):
    log = Signal(str, str)   # level, text

    def __init__(self, mw):
        super().__init__(mw)
        self.mw = mw
        self._own_wx = None

    # ---------------- 实例获取 ----------------
    def _bot_wx(self):
        worker = getattr(self.mw, "worker", None)
        bot = getattr(worker, "_bot", None) if worker else None
        wx = getattr(bot, "wx", None) if bot else None
        running = bool(worker is not None and worker.isRunning())
        return wx if (wx is not None and running) else None

    def _wx(self):
        wx = self._bot_wx()
        if wx is not None:
            return wx, True
        if self._own_wx is None:
            from core.wx_compat import WeChat
            self._own_wx = WeChat()
        return self._own_wx, False

    def using_bot(self):
        return self._bot_wx() is not None

    # ---------------- 发送 ----------------
    def send(self, who: str, text: str) -> bool:
        """发送文本到指定会话（群名或好友昵称）"""
        if not who or not text:
            return False
        try:
            wx, _ = self._wx()
            wx.SendMsg(msg=text, who=who)
            return True
        except Exception as e:
            self.log.emit("ERROR", f"发送到「{who}」失败：{e}")
            return False

    def broadcast(self, targets, text, interval=1.5):
        """批量群发，返回 (成功数, 失败数)"""
        ok = fail = 0
        for i, t in enumerate(targets):
            if self.send(t, text):
                ok += 1
                self.log.emit("SUCCESS", f"已发送到「{t}」")
            else:
                fail += 1
            if i < len(targets) - 1:
                time.sleep(interval)
        return ok, fail
