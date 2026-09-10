# -*- coding: utf-8 -*-
"""
网盘资源搜索桥接层

把 core/bot.py（WxSearchBot 的搜索/选号/转存编排）接到 SiverWXbot_plus 底座上：
底座负责微信收发与监听，本模块只负责"这条消息是不是资源搜索命令"。

用法（在底座 process_message 开头）：
    from netdisk_bot import handle_message
    if handle_message(bot, chat, message):
        return      # 已被网盘搜索处理
"""

import logging
import queue
import threading

log = logging.getLogger("netdisk")

_bridge = None
_lock = threading.RLock()

# ------------------------------------------------------------------
# 并发：搜索走线程池，发送走单条串行队列
#
# 群里 N 个人同时搜，如果处理是串行的，A 那个慢请求（网络超时最长 20s）
# 会把 B、C 的指令全堵在后面 —— 这就是"一个人卡住影响所有人"。
# 所以：指令判定（纯 CPU，很快）同步做，搜索/转存丢线程池；
# 发送一律丢进 _send_q，由单条工作线程串行执行 —— wxauto 是 UI 自动化，
# 并发 SendMsg 会互相踩窗口，必须排队。
# ------------------------------------------------------------------
_POOL = None
_send_q = queue.Queue()
_send_thread = None


def _pool():
    global _POOL
    if _POOL is None:
        from concurrent.futures import ThreadPoolExecutor
        _POOL = ThreadPoolExecutor(max_workers=8,
                                   thread_name_prefix="ndsearch")
    return _POOL


def _ensure_send_thread():
    global _send_thread
    if _send_thread is not None and _send_thread.is_alive():
        return
    def _worker():
        # wxauto 走 COM，工作线程里要显式初始化一次
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass
        while True:
            fn = _send_q.get()
            if fn is None:
                break
            try:
                fn()
            except Exception:
                log.exception("发送任务异常")
    _send_thread = threading.Thread(target=_worker, name="ndsend",
                                    daemon=True)
    _send_thread.start()


def _enqueue_send(fn):
    _ensure_send_thread()
    _send_q.put(fn)


class _SenderBridge:
    """把底座的发送能力伪装成 core.wx_adapter.WeChatClient 的 send"""

    def __init__(self):
        self._fn = None

    def set(self, fn):
        self._fn = fn

    def send(self, text, who=None, at=None, **kwargs):
        """at：群聊里要 @ 的昵称；不支持时由调用方降级为文本 @。

        这里是异步的：只把发送任务丢进串行队列就返回，
        不让慢速 UI 自动化拖住处理线程。
        """
        if not self._fn or not text:
            return False
        who, text, at = str(who), str(text), at
        _enqueue_send(lambda: self._fn(who, text, at))
        return True

    # 兼容 WeChatClient 其余接口（本桥接不会用到）
    def close(self):
        pass

    def status(self):
        return {"core_label": "bridge"}


class NetdiskBridge:
    """单例：持有搜索/转存/会话，供底座调用"""

    def __init__(self):
        import config_manager as CM
        from search.pansou_client import PansouClient
        from transfer.base import AccountPool, TransferService
        from core.bot import Bot

        self.cm = CM
        self.cfg = CM.load_config()
        self._sync_triggers()
        self.searcher = PansouClient(self.cfg)
        self.pool = AccountPool(self.cfg, CM.save_config)
        self.transfer = TransferService(self.cfg, self.pool)
        self.bot = Bot(self.cfg, self.searcher, self.transfer, {"ok": True})
        self.sender = _SenderBridge()
        self.bot.wx = self.sender
        # 名单与触发范围由底座控制，这里不再二次过滤
        self.bot._allowed = lambda *a, **k: True

    # ---------- 对外 ----------
    def set_sender(self, fn):
        """fn(who: str, text: str, at: str|None)"""
        self.sender.set(fn)

    def _sync_triggers(self):
        """面板里配的触发指令同步给 core.bot（它读 wechat.triggers）"""
        trig = self.cfg.get("triggers", {}) or {}
        base = (trig.get("search_cmd") or "搜索").strip()
        cmds = [base] if base else []
        extra = trig.get("extra_cmds") or []
        if isinstance(extra, str):
            extra = [x.strip() for x in extra.split(",") if x.strip()]
        cmds += [x for x in extra if x]
        # 始终内置 DEFAULT_TRIGGERS（含「搜」「查询」「find」等简写）。
        # 否则用户打「搜 XXX」时 parse_command 不匹配，消息漏判落到 AI 路径，
        # AI 一旦失败就误回「在忙，我稍后回复您」，且用户收不到结果会反复重发 → 重复执行。
        try:
            from core.bot import DEFAULT_TRIGGERS as _DT
        except Exception:
            _DT = ["搜索", "搜", "查询", "find"]
        for _t in _DT:
            if _t and _t not in cmds:
                cmds.append(_t)
        wcfg = self.cfg.setdefault("wechat", {})
        wcfg["triggers"] = cmds
        # 翻页 / 帮助指令
        wcfg["next_cmds"] = [trig.get("next_page_cmd") or "下一页"]
        wcfg["prev_cmds"] = [trig.get("prev_page_cmd") or "上一页"]
        wcfg["help_cmds"] = [trig.get("help_cmd") or "帮助"]

    def refresh_config(self):
        self.cfg = self.cm.load_config(force=True)
        self._sync_triggers()
        self.bot.cfg = self.cfg
        try:
            self.bot.searcher = self.searcher.__class__(self.cfg)
        except Exception:
            pass

    def handle(self, text, chat_who, sender, is_group=False):
        """
        返回 True 表示这条消息是网盘搜索命令，已被处理（底座应跳过后续逻辑）。
        注意：core.bot.Bot.handle 本身不回返回值，所以这里先用 parse_command 判定。
        """
        try:
            from core.session import parse_command
            cmd = parse_command(text or "", self.cfg.get("wechat", {}).get("triggers") or ["搜索"])
            if not cmd:
                return False
            # 搜索/翻页/选号都走编排；cancel 直接丢弃上下文
            self.bot.handle(text or "", chat=chat_who, sender=sender, is_group=is_group)
            return True
        except Exception:
            log.exception("网盘搜索处理异常")
            return False

    def triggers(self):
        return (self.cfg.get("triggers", {}) or {}).get("search_cmd", "搜索")


def get_bridge(refresh=False):
    global _bridge
    with _lock:
        if _bridge is None:
            _bridge = NetdiskBridge()
        elif refresh:
            _bridge.refresh_config()
        return _bridge


def handle_message(bot, chat, message) -> bool:
    """
    底座调用入口。
    :param bot:     wxbot_core.WXBot 实例
    :param chat:    wxauto 聊天窗口对象
    :param message: 消息对象
    :return:        True=已处理（底座应跳过后续 AI/关键词逻辑）

    指令判定同步完成（纯字符串解析，很快），真正的搜索/转存丢线程池，
    这样群里一个人搜得慢不会堵住其他人。
    """
    try:
        who = getattr(chat, "who", None) or str(chat)
        content = (getattr(message, "content", "") or "").strip()
        sender = getattr(message, "sender", "") or ""
        is_group = (getattr(chat, "chat_type", "") == "group")
        if not content:
            return False

        bridge = get_bridge()
        try:
            from core.session import parse_command
            triggers = (bridge.cfg.get("wechat", {}).get("triggers")
                        or ["搜索"])
            if not parse_command(content, triggers):
                return False
        except Exception:
            return False

        bridge.set_sender(lambda w, t, a=None: _do_send(bot, w, t, a))
        _pool().submit(_safe_handle, bridge, content, who, sender, is_group)
        return True
    except Exception:
        log.exception("netdisk handle_message 异常")
        return False


def _safe_handle(bridge, content, who, sender, is_group):
    """线程池里的执行体：一个人的异常不能影响其他人。"""
    try:
        bridge.handle(content, who, sender, is_group)
    except Exception:
        log.exception("网盘搜索处理异常: %s / %s", who, sender)


def _do_send(bot, who, text, at=None):
    """通过底座的微信实例发送文本。

    ⚠️ 关键约束：发送【必须】走 bot.wx（免费版即 _WxSendRecorder），因为它会在
    SendMsg 时把"我刚发给谁什么内容"记录进 recent_self，轮询去重正是靠它来区分
    「用户发来的指令」与「我自己刚发的回显」，从而杜绝自问自答死循环。
    因此这里【绝不】走 GetAllSubWindow() 拿到的原始子窗口对象去发——那会绕过
    记录器，导致回显漏记、下一轮被当成新指令反复重跑。

    at 只有 Plus 内核（wxautox4）支持；免费内核的 SendMsg 不认这个关键字
    参数，会抛 TypeError，这里捕获后降级为纯文本。
    """
    wx = getattr(bot, "wx", None)
    if wx is None:
        return False
    if at:
        try:
            wx.SendMsg(msg=text, who=who, at=at)
            return True
        except TypeError:
            pass          # 免费内核不认 at 关键字，走下面降级
        except Exception as e:
            log.warning("带 @ 发送失败，降级为纯文本: %s", e)
    try:
        # 始终带 who 走底座（记录器据此记录 recent_self），不回退到无 who 的旁路
        wx.SendMsg(msg=text, who=who)
        return True
    except Exception as e:
        # 极个别 who 直发瞬态失败：重试一次（COM/UI 自动化偶发抖动），仍失败则放弃。
        # 注意：绝不使用"无 who"的发送兜底——那会让该回显漏记 recent_self，
        # 下一轮被当新指令反复重跑。发不出去就不会产生需要去重的回显，比"发了不记录"更安全。
        try:
            wx.SendMsg(msg=text, who=who)
            return True
        except Exception as e2:
            log.warning("发送失败(who=%s): %s / %s", who, e, e2)
            return False
