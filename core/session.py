# -*- coding: utf-8 -*-
"""
会话状态机：指令解析 + 结果分页 + 数字选号。

关键设计：只有当该聊天窗口存在「等待选号」的活跃上下文时，
纯数字消息才会被当成选号处理。否则原样忽略，避免群里正常聊天被误触发。
"""

import re
import time
import threading

# 网盘类型：中文名 / 别名 → pansou 类型键
PAN_ALIASES = {
    "quark":   ["夸克", "夸克网盘", "kuake", "quark"],
    "uc":      ["uc", "UC", "uc网盘", "优视"],
    "xunlei":  ["迅雷", "迅雷网盘", "xunlei", "thunder"],
    "baidu":   ["百度", "百度网盘", "度盘", "baidu", "bdy"],
    "guangya": ["光鸭", "光鸭云盘", "光鸭网盘", "guangya", "gy"],
    "aliyun":  ["阿里", "阿里云盘", "阿里网盘", "aliyun", "ali", "alipan"],
    "tianyi":  ["天翼", "天翼云盘", "189", "tianyi"],
    "mobile":  ["移动", "移动云盘", "和彩云", "mobile"],
    "115":     ["115", "115网盘"],
    "123":     ["123", "123网盘", "123盘"],
    "pikpak":  ["pikpak", "PikPak", "pp"],
    "magnet":  ["磁力", "magnet", "bt"],
    "ed2k":    ["电驴", "ed2k"],
}

PAN_DISPLAY = {
    "quark": "夸克", "uc": "UC", "xunlei": "迅雷", "baidu": "百度",
    "guangya": "光鸭", "aliyun": "阿里云盘", "tianyi": "天翼",
    "mobile": "移动云盘", "115": "115", "123": "123网盘",
    "pikpak": "PikPak", "magnet": "磁力", "ed2k": "电驴", "others": "其他",
}

_ALIAS_INDEX = {}
for _key, _names in PAN_ALIASES.items():
    for _n in _names:
        _ALIAS_INDEX[_n.lower()] = _key

NEXT_WORDS = {"下一页", "下页", "next", "n", "+", "更多"}
PREV_WORDS = {"上一页", "上页", "prev", "p", "-"}
CANCEL_WORDS = {"取消", "退出", "结束", "cancel", "q"}


def normalize_pan(word):
    """把用户写的网盘名转成内部类型键。认不出来返回 None。"""
    if not word:
        return None
    return _ALIAS_INDEX.get(word.strip().lower())


def parse_command(text, triggers):
    """
    解析「搜索 关键词 网盘类型」。

    网盘类型可选，写在最后。关键词允许带空格。
    返回 dict(kind, keyword, pan) 或 None。
    kind: search | next | prev | pick | cancel
    """
    if not text:
        return None
    s = text.strip()

    if s in CANCEL_WORDS:
        return {"kind": "cancel"}
    low = s.lower()
    if low in NEXT_WORDS:
        return {"kind": "next", "explicit": len(s) > 1 and not s.isascii()}
    if low in PREV_WORDS:
        return {"kind": "prev", "explicit": len(s) > 1 and not s.isascii()}
    if re.fullmatch(r"\d{1,3}", s):
        return {"kind": "pick", "index": int(s)}

    for trig in triggers:
        trig = (trig or "").strip()
        if not trig:
            continue
        if s.startswith(trig):
            rest = s[len(trig):].strip(" 　:：")
            if not rest:
                return {"kind": "search", "keyword": "", "pan": None}
            parts = rest.split()
            pan = None
            if len(parts) >= 2:
                maybe = normalize_pan(parts[-1])
                if maybe:
                    pan = maybe
                    parts = parts[:-1]
            return {"kind": "search", "keyword": " ".join(parts).strip(), "pan": pan}
    return None


class Context:
    """一个聊天窗口 + 一个用户 的搜索上下文。"""

    __slots__ = ("chat", "sender", "keyword", "pan", "results",
                 "page", "page_size", "created", "touched")

    def __init__(self, chat, sender, keyword, pan, results, page_size):
        self.chat = chat
        self.sender = sender
        self.keyword = keyword
        self.pan = pan
        self.results = results
        self.page = 1
        self.page_size = page_size
        self.created = time.time()
        self.touched = time.time()

    @property
    def total(self):
        return len(self.results)

    @property
    def pages(self):
        return max(1, (self.total + self.page_size - 1) // self.page_size)

    def page_items(self):
        start = (self.page - 1) * self.page_size
        return self.results[start:start + self.page_size]

    def pick(self, index):
        """index 是本页内的 1-based 序号。"""
        items = self.page_items()
        if 1 <= index <= len(items):
            return items[index - 1]
        return None

    def move(self, delta):
        new = self.page + delta
        if new < 1 or new > self.pages:
            return False
        self.page = new
        self.touched = time.time()
        return True


class SessionStore:
    def __init__(self, ttl=300, page_size=10):
        self.ttl = ttl
        self.page_size = page_size
        self._data = {}
        self._lock = threading.RLock()

    @staticmethod
    def _key(chat, sender):
        return "%s\x00%s" % (chat or "", sender or "")

    def put(self, chat, sender, keyword, pan, results):
        ctx = Context(chat, sender, keyword, pan, results, self.page_size)
        with self._lock:
            self._data[self._key(chat, sender)] = ctx
        return ctx

    def get(self, chat, sender):
        with self._lock:
            ctx = self._data.get(self._key(chat, sender))
            if not ctx:
                return None
            if time.time() - ctx.touched > self.ttl:
                self._data.pop(self._key(chat, sender), None)
                return None
            ctx.touched = time.time()
            return ctx

    def drop(self, chat, sender):
        with self._lock:
            self._data.pop(self._key(chat, sender), None)

    def sweep(self):
        now = time.time()
        with self._lock:
            for k in [k for k, v in self._data.items() if now - v.touched > self.ttl]:
                self._data.pop(k, None)

    def active_count(self):
        self.sweep()
        with self._lock:
            return len(self._data)
