# -*- coding: utf-8 -*-
"""机器人主逻辑：把微信、盘搜、会话、转存串起来。"""

import time
import re
import logging
import threading

try:
    import schedule
except Exception:
    schedule = None

from core import session as sess
from core import template as tpl
from core.wx_adapter import WeChatClient, WxError

try:
    from search import imported as _imp
except Exception:
    _imp = None

log = logging.getLogger("bot")

DEFAULT_TRIGGERS = ["搜索", "搜", "查询", "find"]


class Bot:
    def __init__(self, config, searcher, transfer_service, license_info):
        self.cfg = config
        self.searcher = searcher
        self.transfer = transfer_service
        self.license_info = license_info or {}
        self.wx = None
        self.sessions = sess.SessionStore(
            ttl=int(config.get("search", {}).get("session_ttl", 300)),
            page_size=int(config.get("search", {}).get("page_size", 10)))
        self._running = False
        self._thread = None
        self._stats_lock = threading.Lock()      # 群里多人并发时自增要互斥
        self._at_native_cache = None
        self.stats = {"searches": 0, "transfers": 0, "failures": 0,
                      "started_at": 0}

    # ---------- 生命周期 ----------
    def start(self):
        if self._running:
            return True, "已在运行"
        if not self.license_info.get("ok"):
            return False, self.license_info.get("msg", "未激活")

        wcfg = self.cfg.get("wechat", {})
        self.wx = WeChatClient(
            prefer=wcfg.get("core", "auto"),
            nickname=wcfg.get("nickname", ""),
            reply_interval_ms=int(wcfg.get("reply_interval_ms", 1200)))
        try:
            self.wx.connect()
        except WxError as e:
            return False, str(e)

        for group in wcfg.get("listen_groups", []):
            self.wx.add_listen(group, self._on_message)
        if wcfg.get("listen_private", True):
            for who in wcfg.get("whitelist", []):
                self.wx.add_listen(who, self._on_message)

        self._running = True
        self.stats["started_at"] = int(time.time())
        self._setup_cleanup_schedule()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True, "已启动（内核：%s）" % self.wx.status()["core_label"]

    def stop(self):
        self._running = False
        if self.wx:
            self.wx.close()
            self.wx = None
        return True, "已停止"

    def _loop(self):
        while self._running:
            self.sessions.sweep()
            if schedule is not None:
                schedule.run_pending()
            time.sleep(5)

    # ---------- 定时清理（移植自网盘搜索站 delete_search）----------
    def _setup_cleanup_schedule(self):
        """每天指定时刻执行一次「清理超期转存文件」。仅当面板开启时注册。"""
        if schedule is None:
            return
        tcfg = self.cfg.get("transfer", {}).get("cleanup", {})
        if not tcfg.get("enabled", False):
            return
        timestr = (tcfg.get("time", "03:00") or "03:00")
        try:
            schedule.every().day.at(timestr).do(self._cleanup_job)
            log.info("已注册定时清理任务：每天 %s", timestr)
        except Exception as e:
            log.warning("注册定时清理任务失败（时刻=%s）: %s", timestr, e)

    def _cleanup_job(self):
        try:
            from transfer import cleanup as TC
            done, msg = TC.cleanup_due(self.cfg, self.transfer.pool)
            log.info("定时清理执行：%s", msg)
        except Exception:
            log.exception("定时清理异常")

    @property
    def running(self):
        return self._running

    # ---------- 模板 ----------
    def t(self, name, **kw):
        return tpl.render(self.cfg.get("templates", {}).get(name, ""), **kw)

    def reply(self, chat, text, sender=None, is_group=False):
        """回复。群聊时 @ 发起人，避免多人同时搜索时分不清哪份结果是自己的。

        会话本身按 (chat, sender) 隔离，数据不会串；这里解决的是"看得见"
        的归属问题 —— 群里 N 个人各搜各的，回复必须标明是给谁的。
        """
        if not text or not self.wx:
            return
        at = None
        if is_group and sender and self._group_at_enabled():
            if self._at_native():
                at = sender                       # Plus：原生 @
            else:
                text = "@%s\n%s" % (sender, text)  # 免费内核：文本 @ 兜底
        try:
            self.wx.send(text, who=chat, at=at)
        except TypeError:
            self.wx.send(text, who=chat)

    def _group_at_enabled(self):
        return bool(self.cfg.get("wechat", {}).get("group_reply_at", True))

    def _at_native(self):
        """内核是否支持原生 @（wxautox4 的 SendMsg(at=...)）。缓存结果。"""
        if self._at_native_cache is None:
            try:
                from core import wx_compat
                self._at_native_cache = bool(wx_compat.CAPS.get("at"))
            except Exception:
                self._at_native_cache = False
        return self._at_native_cache

    # ---------- 消息入口 ----------
    def _allowed(self, chat, sender, is_group):
        wcfg = self.cfg.get("wechat", {})
        if sender in wcfg.get("blacklist", []):
            return False
        if is_group:
            return chat in wcfg.get("listen_groups", [])
        wl = wcfg.get("whitelist", [])
        return (not wl) or (sender in wl)

    def _on_message(self, msg, chat):
        try:
            self.handle(getattr(msg, "content", "") or "",
                        chat=getattr(chat, "who", None) or str(chat),
                        sender=getattr(msg, "sender", "") or "")
        except Exception:
            log.exception("处理消息出错")

    def handle(self, text, chat, sender, is_group=False):
        if not self._allowed(chat, sender, is_group):
            return
        triggers = self.cfg.get("wechat", {}).get("triggers") or DEFAULT_TRIGGERS
        cmd = sess.parse_command(text, triggers)
        if not cmd:
            return

        # 群聊拿不到发言人时，所有人会共用同一份上下文。
        # 搜索照常回应（结果大家都能用），但选号一律忽略 ——
        # 否则 A 搜完，B 随手发个"1"就把 A 的结果取走了。
        if is_group and not (sender or "").strip():
            if cmd["kind"] == "pick":
                return
            if log.isEnabledFor(logging.WARNING):
                log.warning("群聊消息缺少 sender，已忽略选号：%s", text)

        kind = cmd["kind"]
        if kind == "search":
            return self._do_search(chat, sender, cmd, is_group)
        if kind in ("next", "prev"):
            return self._do_page(chat, sender, 1 if kind == "next" else -1,
                                 explicit=cmd.get("explicit", True),
                                 is_group=is_group)
        if kind == "pick":
            return self._do_pick(chat, sender, cmd["index"], is_group)
        if kind == "cancel":
            self.sessions.drop(chat, sender)

    # ---------- 广告词过滤 ----------
    @staticmethod
    def _parse_ad_words(raw):
        """把面板里的「逗号/换行分隔」文本解析成小写广告词列表。"""
        if not raw:
            return []
        out = []
        for part in re.split(r"[,\n，\r]+", str(raw)):
            w = part.strip().lower()
            if w:
                out.append(w)
        return out

    def _filter_ad_words(self, results):
        """剔除标题里包含任一广告词的资源（去广告/引流）。
        参考站内 search_ad_words 逻辑：对结果标题做大小写不敏感的子串匹配。"""
        raw = (self.cfg.get("search", {}) or {}).get("ad_words") or ""
        words = self._parse_ad_words(raw)
        if not words:
            return results
        kept, removed = [], 0
        for it in results:
            title = (it.get("title") or "").lower()
            if any(w in title for w in words):
                removed += 1
                continue
            kept.append(it)
        if removed:
            log.info("广告词过滤：剔除 %d 条含广告词资源（剩余 %d 条）", removed, len(kept))
        return kept

    # ---------- 搜索 ----------
    def _do_search(self, chat, sender, cmd, is_group=False):
        keyword = cmd.get("keyword") or ""
        pan = cmd.get("pan")
        if not keyword:
            return self.reply(chat, self.t("search_hint"), sender, is_group)

        # 可选：要求指令必须带网盘类型（面板「结果展示」里的开关）。
        # 开启后，未带类型的搜索会提示用户先选类型，而不是返回混合结果。
        if not pan and (self.cfg.get("search", {}) or {}).get("require_pan_type"):
            return self.reply(chat, self.t("require_pan_hint", keyword=keyword),
                              sender, is_group)

        pan_name = sess.PAN_DISPLAY.get(pan, "全部网盘")
        self.reply(chat, self.t("searching", keyword=keyword, pan_name=pan_name),
                   sender, is_group)

        results, errors = self.searcher.search(keyword, pan=pan)

        # 并入本地导入的资源（顾客需求 A）：混排盘搜结果 + 导入表
        if _imp is not None and (self.cfg.get("imported", {}) or {}).get("enabled", True):
            try:
                imported_items = _imp.search_imported(keyword, pan=pan)
                if imported_items:
                    results = results + imported_items
                    log.info("搜索并入本地导入 %d 条（关键词=%s）", len(imported_items), keyword)
            except Exception as e:
                log.warning("并入本地导入失败: %s", e)

        # 去重：同一链接在盘搜结果和导入表里都出现时只留一条
        seen, deduped = set(), []
        for it in results:
            k = it.uid
            if k in seen:
                continue
            seen.add(k)
            deduped.append(it)
        results = deduped

        results = self._filter_ad_words(results)
        with self._stats_lock:
            self.stats["searches"] += 1
        if not results:
            if errors:
                log.warning("搜索无结果，错误：%s", "；".join(errors))
            return self.reply(chat, self.t("no_result", keyword=keyword,
                                           pan_name=pan_name), sender, is_group)

        ctx = self.sessions.put(chat, sender, keyword, pan, results)
        self.reply(chat, self._render_page(ctx), sender, is_group)

    def _do_page(self, chat, sender, delta, explicit=True, is_group=False):
        ctx = self.sessions.get(chat, sender)
        if not ctx:
            # 「n」「p」这类单字母别名没有上下文时静默忽略，避免群里刷屏；
            # 用户明确打了「下一页」才提示已过期
            return self.reply(chat, self.t("expired"), sender, is_group) \
                if explicit else None
        if not ctx.move(delta):
            return
        self.reply(chat, self._render_page(ctx), sender, is_group)

    def _render_page(self, ctx):
        pan_name = sess.PAN_DISPLAY.get(ctx.pan, "全部网盘")
        head = self.t("result_header", keyword=ctx.keyword, total=ctx.total,
                      page=ctx.page, pages=ctx.pages, pan_name=pan_name)
        lines = []
        for i, item in enumerate(ctx.page_items(), 1):
            pan = item.get("pan", "")
            # 自有资源在标题前加 🏠，不改动用户自定义模板（避免 {own_mark} 占位符兼容问题）
            title = item.get("title", "")
            if item.get("own"):
                title = "🏠 " + title
            lines.append(self.t(
                "result_item", index=i,
                index_emoji=tpl.index_emoji(i),
                pan_icon=tpl.pan_icon(pan),
                title=title,
                pan_name=sess.PAN_DISPLAY.get(pan, pan),
                source=item.get("source", ""),
                size=item.get("size", ""),
                datetime=item.get("datetime", ""),
                dead_mark="🔴 " if item.get("dead") else ""))
        foot = self.t("result_footer", page=ctx.page, pages=ctx.pages,
                      total=ctx.total)
        return "\n".join([head, ""] + lines + ["", foot]).strip()

    # ---------- 取资源 ----------
    # 自动跳过的上限：避免一整批源链接都死了时无限/过深递归
    _MAX_AUTOSKIP = 5

    def _do_pick(self, chat, sender, index, is_group=False):
        # 注意：ctx 是按 (chat, sender) 取的，所以群聊里 A 的序号只会命中
        # A 自己的结果，不会拿到 B 的。
        ctx = self.sessions.get(chat, sender)
        if not ctx:
            return  # 没有活跃上下文时，纯数字消息一律忽略
        item = ctx.pick(index)
        if not item:
            # 群里别人随手发的数字、或自己敲了超出本页范围的序号，
            # 都直接吞掉不回复 —— 否则群里会不停刷"序号超出范围"。
            return
        self._transfer_item(chat, sender, ctx, item, is_group, depth=0)

    def _transfer_item(self, chat, sender, ctx, item, is_group, depth=0):
        """对单条资源执行取链。失败按「死链 / 账号失效 / 可重试 / 其他」分类处理；
        死链且开启 auto_skip_dead 时自动跳到下一条未失效资源。"""
        pan = item.get("pan", "")
        pan_name = sess.PAN_DISPLAY.get(pan, pan)
        title = item.get("title", "")
        tcfg = self.cfg.get("transfer", {}) or {}

        # 已经确认失效的（自动跳过途中遇到），直接跳下一条
        if item.get("dead"):
            return self._auto_skip(chat, sender, ctx, item, is_group, depth)

        # 本地导入表里标「是自己的资源」：跳过转存，直接给原链接
        if item.get("own"):
            return self._reply_own(chat, item, sender, is_group)

        if not tcfg.get("enabled", True):
            return self._reply_origin(chat, item, "转存功能已关闭",
                                      sender, is_group)

        if pan not in self.transfer.available_pans():
            return self.reply(chat, self.t("no_account", pan_name=pan_name,
                                           pan_icon=tpl.pan_icon(pan)),
                              sender, is_group) \
                if not tcfg.get("fallback_original_link") \
                else self._reply_origin(chat, item, "没有可用账号",
                                        sender, is_group)

        self.reply(chat, self.t("getting", title=title, pan_name=pan_name,
                                pan_icon=tpl.pan_icon(pan)),
                   sender, is_group)

        res, err, cat = self.transfer.run(pan, item.get("url", ""),
                                          password=item.get("password", ""),
                                          title=title)
        if res:
            with self._stats_lock:
                self.stats["transfers"] += 1
            pwd = res.get("password", "")
            pwd_line = self.t("password_line", password=pwd) if pwd else ""
            self.reply(chat, self.t("success", title=title,
                                    share_url=res.get("url", ""),
                                    password_line=pwd_line,
                                    pan_name=pan_name,
                                    pan_icon=tpl.pan_icon(pan),
                                    expire=res.get("expire", "永久")),
                       sender, is_group)
            return

        with self._stats_lock:
            self.stats["failures"] += 1

        # ① 源链接失效：标记 + （按需）自动跳下一条有效资源
        if cat.get("dead_link"):
            item["dead"] = True
            return self._auto_skip(chat, sender, ctx, item, is_group, depth)

        # ② 账号失效：明确告诉用户是「他自己的账号」问题，去面板更新
        if cat.get("invalid_account"):
            return self.reply(chat,
                              self.t("account_invalid", pan_name=pan_name,
                                     pan_icon=tpl.pan_icon(pan), reason=err),
                              sender, is_group)

        # ③ 可重试（网络/风控）：提示稍后重试
        if cat.get("retryable"):
            return self.reply(chat,
                              self.t("transfer_retry", pan_icon=tpl.pan_icon(pan),
                                     reason=err),
                              sender, is_group)

        # ④ 其他：回落原始链接（保持旧行为）
        return self._reply_origin(chat, item, err, sender, is_group)

    def _auto_skip(self, chat, sender, ctx, item, is_group, depth):
        """当前这条已失效，按配置自动跳到下一条未失效资源。

        depth==0 表示是用户主动选的这条 —— 若关闭自动跳过或无下一条，
        就只提示"已失效"；depth>0 表示连跳多条后仍无可用，提示"都已失效"。
        """
        tcfg = self.cfg.get("transfer", {}) or {}
        if tcfg.get("auto_skip_dead", True) and depth < self._MAX_AUTOSKIP:
            nxt = self._next_valid(ctx, item)
            if nxt is not None:
                # 先告诉用户这条死了，再尝试下一条（连跳时每条都给个反馈）
                self.reply(chat,
                           self.t("dead_link", title=item.get("title", ""),
                                  pan_name=sess.PAN_DISPLAY.get(
                                      item.get("pan", ""), item.get("pan", "")),
                                  pan_icon=tpl.pan_icon(item.get("pan", ""))),
                           sender, is_group)
                return self._transfer_item(chat, sender, ctx, nxt,
                                           is_group, depth + 1)
        if depth == 0:
            return self.reply(chat,
                              self.t("dead_link", title=item.get("title", ""),
                                     pan_name=sess.PAN_DISPLAY.get(
                                         item.get("pan", ""), item.get("pan", "")),
                                     pan_icon=tpl.pan_icon(item.get("pan", ""))),
                              sender, is_group)
        return self.reply(chat,
                          self.t("dead_link_end", keyword=ctx.keyword,
                                 pan_name=sess.PAN_DISPLAY.get(
                                     item.get("pan", ""), "")),
                          sender, is_group)

    def _next_valid(self, ctx, current):
        """从 current 之后找下一条「未失效 + 本机有可用账号」的资源。"""
        items = ctx.results
        try:
            start = items.index(current)
        except ValueError:
            start = -1
        avail = set(self.transfer.available_pans())
        for it in items[start + 1:]:
            if it.get("dead"):
                continue
            if it.get("pan", "") not in avail:
                continue
            return it
        return None

    def _reply_own(self, chat, item, sender=None, is_group=False):
        """本地导入表里标「自己的资源」：跳过转存，直接把原链接发给用户。"""
        url = item.get("url", "")
        if item.get("password"):
            url = "%s\n提取码：%s" % (url, item["password"])
        self.reply(chat, self.t("own_resource", title=item.get("title", ""), url=url),
                   sender, is_group)

    def _reply_origin(self, chat, item, reason, sender=None, is_group=False):
        if not self.cfg.get("transfer", {}).get("fallback_original_link", True):
            return self.reply(chat, self.t(
                "no_account",
                pan_name=sess.PAN_DISPLAY.get(item.get("pan"), "")),
                sender, is_group)
        url = item.get("url", "")
        if item.get("password"):
            url = "%s\n提取码：%s" % (url, item["password"])
        self.reply(chat, self.t("transfer_failed", title=item.get("title", ""),
                                reason=reason, origin_url=url,
                                pan_name=sess.PAN_DISPLAY.get(item.get("pan"), ""),
                                pan_icon=tpl.pan_icon(item.get("pan", ""))),
                   sender, is_group)

    # ---------- 状态 ----------
    def status(self):
        s = dict(self.stats)
        s["running"] = self._running
        s["active_sessions"] = self.sessions.active_count()
        s["wechat"] = self.wx.status() if self.wx else {"connected": False,
                                                        "core": "none",
                                                        "core_label": "未连接"}
        return s
