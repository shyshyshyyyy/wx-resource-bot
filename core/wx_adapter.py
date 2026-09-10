# -*- coding: utf-8 -*-
"""
wxauto4 / wxautox4 自适应适配层。

设计要点：
- 两个包 API 同名同签名，所以对外只暴露一个 WeChatClient，上层代码不关心用的哪个内核。
- 启动时按 auto 策略探测：wxautox4 装了且已激活 → plus；否则 → free。
- Plus 独有能力（后台模式、链接卡片、朋友圈等）通过 caps 查询，
  免费版下自动降级为等价实现或跳过，绝不抛异常打断业务流程。
- 打包成 exe 后没有 python.exe，无法用 `python -m wxautox4 -k` 检查激活，
  所以走 main.py 的隐藏 CLI 转发（--wx-cli），由自身 exe 代跑内核命令行。
"""

import os
import sys
import time
import logging
import subprocess

log = logging.getLogger("wx")

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

CORE_FREE = "free"
CORE_PLUS = "plus"
CORE_NONE = "none"

# Plus 独有能力清单。免费版下这些统一为 False。
PLUS_ONLY_CAPS = (
    "background_mode",     # 后台模式，不抢鼠标
    "send_url_card",       # 发送链接卡片
    "multi_instance",      # WeChat(nickname=...) 多开
    "get_sender_detail",   # 获取发送者详情
    "moments",             # 朋友圈
    "auto_accept_friend",  # 自动通过好友
)


class WxError(Exception):
    pass


# ----------------------------------------------------------
# 内核命令行转发
# ----------------------------------------------------------
def _run_core_cli(args, timeout=25):
    """
    执行内核命令行（wxautox4 -k / -a 激活码 / --export 等）。
    源码运行：直接调 sys.executable -m wxautox4
    打包运行：调自身 exe 的隐藏入口 --wx-cli，由 main.py 转发到模块 main
    返回 (returncode, output)
    """
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--wx-cli"] + list(args)
    else:
        cmd = [sys.executable, "-m", "wxautox4"] + list(args)
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           creationflags=_CREATE_NO_WINDOW)
        out = (p.stdout or b"").decode("utf-8", "ignore") + \
              (p.stderr or b"").decode("utf-8", "ignore")
        return p.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return -1, "内核命令行超时"
    except Exception as e:
        return -1, "内核命令行调用失败: %s" % e


_ACTIVE_WORDS = ("已激活", "已授权", "activated", "valid", "licensed", "有效")
_INACTIVE_WORDS = ("未激活", "未授权", "not activated", "invalid",
                   "expired", "已过期", "no license", "unlicensed")


def _looks_activated(text):
    low = (text or "").lower()
    for w in _INACTIVE_WORDS:
        if w in low or w in (text or ""):
            return False
    for w in _ACTIVE_WORDS:
        if w in low or w in (text or ""):
            return True
    return None  # 无法判断


def probe_plus_activation():
    """
    返回 (activated: bool, detail: str)。
    多策略，任一策略给出明确结论就采信。
    """
    try:
        import wxautox4  # noqa
    except Exception:
        return False, "未安装 wxautox4"

    # 策略 1：包内可能直接暴露的检查函数
    try:
        import wxautox4 as x
        for name in ("check_activation", "is_activated", "check_license",
                     "license_info", "get_license"):
            fn = getattr(x, name, None)
            if callable(fn):
                try:
                    r = fn()
                except Exception:
                    continue
                if isinstance(r, bool):
                    return r, "wxautox4.%s() -> %s" % (name, r)
                if isinstance(r, dict):
                    ok = bool(r.get("ok") or r.get("valid") or r.get("activated"))
                    return ok, "wxautox4.%s() -> %s" % (name, r)
                verdict = _looks_activated(str(r))
                if verdict is not None:
                    return verdict, "wxautox4.%s() -> %s" % (name, r)
    except Exception:
        pass

    # 策略 2：命令行 -k
    rc, out = _run_core_cli(["-k"], timeout=20)
    verdict = _looks_activated(out)
    if verdict is not None:
        return verdict, out
    if rc == 0 and out:
        return True, out

    # 策略 3：尝试实例化，看异常信息里有没有授权字样
    try:
        import wxautox4 as x
        x.WeChat()
        return True, "实例化成功"
    except Exception as e:
        msg = str(e)
        verdict = _looks_activated(msg)
        if verdict is not None:
            return verdict, msg
        # 实例化失败但不是授权问题（比如微信没登录），无法判定激活状态
        return False, "无法确认激活状态：%s" % msg


def activate_plus(code):
    """用激活码激活 wxautox4 内核。返回 (ok, msg)。"""
    code = (code or "").strip()
    if not code:
        return False, "激活码为空"
    rc, out = _run_core_cli(["-a", code], timeout=40)
    ok, _ = probe_plus_activation()
    return ok, (out or ("激活成功" if ok else "激活失败"))


def export_core_machine_code():
    """导出 wxautox4 内核所需的机器码（和本程序自身的授权机器码是两回事）。"""
    rc, out = _run_core_cli(["--export"], timeout=20)
    return out


# ----------------------------------------------------------
# 内核选择
# ----------------------------------------------------------
def detect_core(prefer="auto"):
    """
    返回 (core, WeChatClass, detail)
    prefer: auto | free | plus
    """
    if prefer == "free":
        try:
            from wxauto4 import WeChat
            return CORE_FREE, WeChat, "手动指定免费版"
        except Exception as e:
            return CORE_NONE, None, "wxauto4 导入失败: %s" % e

    if prefer in ("auto", "plus"):
        activated, detail = probe_plus_activation()
        if activated:
            try:
                from wxautox4 import WeChat
                return CORE_PLUS, WeChat, detail
            except Exception as e:
                detail = "wxautox4 导入失败: %s" % e
        if prefer == "plus":
            return CORE_NONE, None, "Plus 版不可用：%s" % detail

    try:
        from wxauto4 import WeChat
        return CORE_FREE, WeChat, "回落到免费版"
    except Exception as e:
        return CORE_NONE, None, "wxauto4 / wxautox4 都不可用: %s" % e


# ----------------------------------------------------------
# 统一客户端
# ----------------------------------------------------------
class WeChatClient:
    """
    对上层暴露稳定接口。上层只调这里的方法，不直接 import wxauto4/wxautox4。
    """

    def __init__(self, prefer="auto", nickname="", reply_interval_ms=1200):
        self.prefer = prefer
        self.nickname = (nickname or "").strip()
        self.reply_interval = max(0, reply_interval_ms) / 1000.0
        self.core = CORE_NONE
        self.core_detail = ""
        self._wx = None
        self._cls = None
        self._last_send = 0.0
        self.caps = {c: False for c in PLUS_ONLY_CAPS}

    # ---------- 生命周期 ----------
    def connect(self):
        core, cls, detail = detect_core(self.prefer)
        self.core, self._cls, self.core_detail = core, cls, detail
        if cls is None:
            raise WxError(detail)

        kwargs = {}
        if core == CORE_PLUS and self.nickname:
            kwargs["nickname"] = self.nickname

        try:
            self._wx = cls(**kwargs) if kwargs else cls()
        except TypeError:
            # 免费版不接受 nickname 参数
            self._wx = cls()

        if core == CORE_PLUS:
            for c in PLUS_ONLY_CAPS:
                self.caps[c] = True
            # 有些能力即便 Plus 也未必有，实测存在性
            self.caps["send_url_card"] = hasattr(self._wx, "SendUrlCard")
            self.caps["moments"] = hasattr(self._wx, "Moments") or hasattr(self._wx, "GetMoments")

        log.info("微信内核: %s (%s)", core, detail)
        return self

    @property
    def connected(self):
        return self._wx is not None

    def is_online(self):
        if not self._wx:
            return False
        fn = getattr(self._wx, "IsOnline", None)
        if callable(fn):
            try:
                return bool(fn())
            except Exception:
                return False
        # 免费版可能没有 IsOnline，用 ChatInfo 兜底
        try:
            return bool(self._wx.ChatInfo())
        except Exception:
            return False

    def close(self):
        try:
            if self._wx and hasattr(self._wx, "StopListening"):
                self._wx.StopListening()
        except Exception:
            pass
        self._wx = None

    # ---------- 发送 ----------
    def _throttle(self):
        gap = time.time() - self._last_send
        if gap < self.reply_interval:
            time.sleep(self.reply_interval - gap)
        self._last_send = time.time()

    def send(self, text, who=None, at=None):
        """发文本。自动限速，失败重试一次。

        at：群聊里 @ 的昵称。Plus 内核走 SendMsg 的 at 参数（真 @）；
        免费内核不支持该参数，捕获 TypeError 后降级为纯文本，由调用方
        决定是否自己在正文里补 "@昵称"。
        返回 True/False；at 被降级时返回 "noat"，方便上层兜底。
        """
        if not self._wx:
            raise WxError("微信未连接")
        self._throttle()
        degraded = False
        for attempt in (1, 2):
            try:
                if at:
                    try:
                        self._wx.SendMsg(text, who=who, at=at)
                        return True
                    except TypeError:
                        # 免费版 wxauto4 的 SendMsg 不认 at 参数
                        degraded = True
                        self._wx.SendMsg(text, who=who) if who \
                            else self._wx.SendMsg(text)
                        return "noat"
                if who:
                    self._wx.SendMsg(text, who=who)
                else:
                    self._wx.SendMsg(text)
                return True
            except Exception as e:
                log.warning("发送失败(第%d次): %s", attempt, e)
                if attempt == 2:
                    return "noat" if (at and degraded) else False
                time.sleep(1.0)
        return False

    def send_url_card(self, url, title="", who=None):
        """Plus 独有。免费版自动降级为发送纯文本链接。"""
        if self.caps.get("send_url_card") and self._wx:
            try:
                self._wx.SendUrlCard(url, who=who) if who else self._wx.SendUrlCard(url)
                return True
            except Exception as e:
                log.warning("链接卡片失败，降级为文本: %s", e)
        return self.send(("%s\n%s" % (title, url)).strip(), who=who)

    def send_files(self, paths, who=None):
        if not self._wx:
            return False
        self._throttle()
        try:
            if who:
                self._wx.SendFiles(paths, who)
            else:
                self._wx.SendFiles(paths)
            return True
        except Exception as e:
            log.warning("发送文件失败: %s", e)
            return False

    # ---------- 监听 ----------
    def add_listen(self, nickname, callback):
        if not self._wx:
            raise WxError("微信未连接")
        try:
            self._wx.AddListenChat(nickname=nickname, callback=callback)
            return True
        except TypeError:
            try:
                self._wx.AddListenChat(nickname, callback)
                return True
            except Exception as e:
                log.error("添加监听失败 %s: %s", nickname, e)
                return False
        except Exception as e:
            log.error("添加监听失败 %s: %s", nickname, e)
            return False

    def keep_running(self):
        if self._wx and hasattr(self._wx, "KeepRunning"):
            self._wx.KeepRunning()
        else:
            while self._wx:
                time.sleep(1)

    # ---------- 信息 ----------
    def status(self):
        return {
            "connected": self.connected,
            "core": self.core,
            "core_label": {"plus": "Plus 版（wxautox4）",
                           "free": "免费版（wxauto4）",
                           "none": "未连接"}.get(self.core, self.core),
            "core_detail": self.core_detail,
            "online": self.is_online() if self.connected else False,
            "caps": dict(self.caps),
        }
