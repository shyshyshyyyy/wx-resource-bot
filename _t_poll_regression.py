# -*- coding: utf-8 -*-
"""回归测试：验证轮询监听「不漏消息 / 不重放历史 / 连续翻页都执行」。

对照 v2.7.3（它跑在 wxautox4 的 GetNextNewMessage 新消息轮询模式，每条只投递一次，
不需要内容去重）。本项目跑 wxauto4 免费版，无该 API，只能 ChatWith 轮询 —— 因此
必须在「条数游标 + 内容指纹」之上再补两道保险：

  保险一：发送后立刻重对齐游标（_mark_chat_seen）
      机器人长回复会让微信虚拟列表可渲染条数骤降 → 下轮判定「回缩」→ 改用内容指纹
      定位。而连续两条「下一页」内容完全相同、指纹一样，定位必然把新发的那条误判成
      已消费的那条（用户实测：第一次翻页成功、第二次无反应）。
  保险二：尾部兜底
      窗口最后一条若是「从未处理过的用户消息」，无论游标/指纹如何失准都直接处理。

覆盖场景：
  1. 启动 seed：历史消息不执行
  2. 正常增量：新消息只处理一次
  3. 连续翻页：两次「下一页」都处理
  4. 回缩(shrink) + 新消息：指纹定位，正确处理新消息、不重放历史
  5. 回缩且 last_fp 被顶出：整段重扫 + seen 兜底
  6. _mark_chat_seen 只标 self：用户「下一页」不被误标
  7. 回缩 + 翻页间有机器人回复 + 第二次「下一页」
  8. 空读保护：切窗未就绪读到空，不动游标/指纹
  9. 【用户真实场景】搜索 → 下一页 → 长回复导致回缩 → 第二次「下一页」
  10. 尾部兜底：游标完全失准时，末尾的全新用户消息仍被处理
"""
import time


class _Msg:
    def __init__(self, attr, sender, typ, content):
        self.attr = attr
        self.sender = sender
        self.type = typ
        self.content = content

    def __repr__(self):
        return f"<{self.attr}|{self.sender}|{self.content}>"


NEXT_WORDS = {"下一页", "下页", "next", "n", "+", "更多"}
PREV_WORDS = {"上一页", "上页", "prev", "p", "-"}
PAGE_CMD_WORDS = frozenset(list(NEXT_WORDS) + list(PREV_WORDS))


def msg_key(m, who=None):
    # 与 wxbot_core._msg_key 一致：会话名 + 发送人 + 类型 + 内容（不含 attr）
    return (who or '', getattr(m, 'sender', ''), getattr(m, 'type', ''),
            str(getattr(m, 'content', '')))


def is_page_cmd(content):
    return bool(content) and content.strip() in PAGE_CMD_WORDS


class PollSim:
    """忠实复刻 wxbot_core._poll_loop 的核心判定逻辑（纯内存，不依赖 wxauto）。"""

    def __init__(self, cmd="文件传输助手"):
        self.config_cmd = cmd
        self.poll_seen = {}        # who -> {key: ts}
        self.poll_count = {}       # who -> 条数游标
        self.poll_last_fp = {}     # who -> 最后一条已消费消息的 key
        self.poll_resync = {}      # who -> 发送后已重对齐游标
        self.poll_tail_ready = set()
        self.handled = []          # (who, content) 处理记录

    # ---- 对应 wxbot_core._mark_chat_seen ----
    def mark_chat_seen(self, who, msgs):
        """机器人发送后调用：只标 attr=self，并把游标重对齐到「含本次回复」的真实状态。"""
        seen = self.poll_seen.setdefault(who, {})
        t = time.time()
        for m in msgs:
            if getattr(m, 'attr', '') != 'self':
                continue
            seen[msg_key(m, who)] = t
        if msgs:
            self.poll_count[who] = len(msgs)
            self.poll_last_fp[who] = msg_key(msgs[-1], who)
            self.poll_resync[who] = True

    def seed(self, who, msgs):
        seen = self.poll_seen.setdefault(who, {})
        t = time.time()
        for m in msgs:
            seen[msg_key(m, who)] = t
        self.poll_count[who] = len(msgs)
        if msgs:
            self.poll_last_fp[who] = msg_key(msgs[-1], who)

    def poll_once(self, who, msgs):
        """模拟 _poll_loop 单轮对单个 who 的处理。"""
        n = len(msgs)
        if n == 0:
            return []   # 空读保护：切窗未就绪读到空，不动游标/指纹
        seen = self.poll_seen.setdefault(who, {})
        cursor = self.poll_count.get(who, 0)
        shrink = n < cursor
        rescan_all = False
        if shrink:
            last_fp = self.poll_last_fp.get(who, "")
            start = -1
            if last_fp:
                # 从前往后找：匹配「最早出现的」last_fp（上次已消费的那条）
                for i in range(n):
                    if msg_key(msgs[i], who) == last_fp:
                        start = i
                        break
            if start != -1:
                cursor = start + 1   # 指纹定位成功
            else:
                cursor = 0
                rescan_all = True    # 整段重扫，靠 seen 兜底
        out = []
        _handled = set()
        for idx in range(cursor, n):
            m = msgs[idx]
            is_last = (idx == n - 1)   # 窗口里最新的一条
            key = msg_key(m, who)
            content = str(getattr(m, 'content', '')).strip()
            attr = getattr(m, 'attr', '')
            typ = getattr(m, 'type', '')
            pg = is_page_cmd(content)
            if not pg and key in seen:
                continue
            # 分页指令：只有「最新一条」豁免 seen 去重，其余查 seen 防重放
            if pg and (not is_last) and key in seen:
                continue
            seen[key] = time.time()
            if attr == 'self' and who != self.config_cmd:
                continue
            if attr == 'system' or typ == 'time':
                continue
            if attr == 'self' and who == self.config_cmd:
                if content in [s.strip() for s in []]:  # 简化：recent_self 为空
                    continue
            _handled.add(key)
            out.append(content)
            self.handled.append((who, content))

        # ---- 尾部兜底：窗口最后一条「从未处理过的用户消息」绝不漏 ----
        tail = msgs[-1]
        t_attr = getattr(tail, 'attr', '')
        t_type = getattr(tail, 'type', '')
        t_content = str(getattr(tail, 'content', '')).strip()
        if (who in self.poll_tail_ready and t_attr not in ('self', 'system')
                and t_type != 'time' and t_content):
            t_key = msg_key(tail, who)
            if t_key not in _handled and t_key not in seen:
                seen[t_key] = time.time()
                _handled.add(t_key)
                out.append(t_content)
                self.handled.append((who, t_content))

        # 轮末推进游标；但若本轮机器人发过消息，_mark_chat_seen 已对齐过，不要覆盖
        if not self.poll_resync.pop(who, False):
            self.poll_count[who] = n
            if msgs:
                self.poll_last_fp[who] = msg_key(msgs[-1], who)
        self.poll_tail_ready.add(who)
        return out


def fr(sender, content, typ="text"):
    return _Msg('friend', sender, typ, content)


def slf(content, sender="机器人"):
    return _Msg('self', sender, 'text', content)


# ---- 场景 1：启动 seed ----
sim = PollSim()
history = [fr("Silence", "你好"), slf("你好，我是机器人"), fr("Silence", "搜索 AI 迅雷")]
sim.seed("Silence", history)
assert sim.poll_once("Silence", history) == [], "场景1 失败：启动不应回放历史"
print("场景1 启动 seed 不重放历史 OK")

# ---- 场景 2：正常增量，新消息处理一次 ----
sim = PollSim()
hist = [fr("Silence", "搜索 AI 迅雷")]
sim.seed("Silence", hist)
got = sim.poll_once("Silence", hist + [slf("结果..."), fr("Silence", "下一页")])
assert got == ["下一页"], f"场景2 失败: {got}"
print("场景2 正常增量处理新消息 OK")

# ---- 场景 3：连续翻页 ----
sim = PollSim()
hist = [fr("Silence", "搜索 AI 迅雷"), slf("结果...")]
sim.seed("Silence", hist)
got1 = sim.poll_once("Silence", hist + [fr("Silence", "下一页")])
got2 = sim.poll_once("Silence", hist + [fr("Silence", "下一页"), fr("Silence", "下一页")])
assert got1 == ["下一页"], f"场景3a 失败: {got1}"
assert got2 == ["下一页"], f"场景3b 失败（连续翻页第二条应处理）: {got2}"
print("场景3 连续翻页两条都处理 OK")

# ---- 场景 4：shrink 回缩 + 新消息（指纹定位） ----
sim = PollSim()
hist = [fr("Silence", f"旧消息{i}") for i in range(20)]
sim.seed("Silence", hist)
shrunk = hist[5:] + [fr("Silence", "下一页")]
got = sim.poll_once("Silence", shrunk)
assert got == ["下一页"], f"场景4 失败（回缩时指纹定位应只处理新消息）: {got}"
print("场景4 回缩时指纹定位不重放历史、正确处理新消息 OK")

# ---- 场景 5：回缩且 last_fp 被顶出（整段重扫 + seen 兜底） ----
sim = PollSim()
hist = [fr("Silence", f"旧消息{i}") for i in range(20)]
sim.seed("Silence", hist)
only_new = [fr("Silence", "新消息A"), fr("Silence", "新消息B")]
got = sim.poll_once("Silence", only_new)
assert got == ["新消息A", "新消息B"], f"场景5 失败: {got}"
print("场景5 回缩且 last_fp 被顶出时回退 seen 兜底 OK")

# ---- 场景 6：_mark_chat_seen 只标 self，不吞用户「下一页」 ----
sim = PollSim()
hist = [fr("Silence", "搜索 AI 迅雷")]
sim.seed("Silence", hist)
sim.mark_chat_seen("Silence", [slf("结果..."), fr("Silence", "下一页")])
sim.poll_resync.pop("Silence", None)   # 模拟：发送发生在两轮之间，游标已被对齐
got = sim.poll_once("Silence", hist + [slf("结果..."), fr("Silence", "下一页")])
assert got == ["下一页"], f"场景6 失败（_mark_chat_seen 不应吞用户下一页）: {got}"
print("场景6 _mark_chat_seen 只标 self、不误吞用户消息 OK")

# ---- 场景 7：回缩 + 翻页间有机器人回复 + 第二次「下一页」 ----
sim = PollSim()
hist20 = [fr("群", f"旧消息{i}") for i in range(20)]
sim.seed("群", hist20)
got1 = sim.poll_once("群", hist20 + [fr("群", "下一页")])
assert got1 == ["下一页"], f"场景7a 失败: {got1}"
sim.poll_once("群", hist20 + [fr("群", "下一页"), slf("结果...")])
shrunk = hist20[5:] + [fr("群", "下一页"), slf("结果..."), fr("群", "下一页")]
got2 = sim.poll_once("群", shrunk)
assert got2 == ["下一页"], f"场景7b 失败（第二次翻页应处理）: {got2}"
print("场景7 回缩时指纹定位成功、第二次翻页不被 seen 误判 OK")

# ---- 场景 8：空读保护 ----
sim = PollSim()
hist = [fr("Silence", "搜索 AI 迅雷")]
sim.seed("Silence", hist)
assert sim.poll_once("Silence", []) == [], "场景8a 空读应返回空"
assert sim.poll_count["Silence"] == 1, "场景8a 失败：空读不应清空游标"
assert sim.poll_last_fp["Silence"] == msg_key(hist[-1], "Silence"), "场景8a 失败：空读不应污染指纹"
got = sim.poll_once("Silence", hist + [fr("Silence", "下一页")])
assert got == ["下一页"], f"场景8b 失败（空读后恢复应正确处理新消息）: {got}"
print("场景8 空读保护：切窗未就绪不污染游标/指纹，恢复后不漏消息 OK")


# ---- 场景 9：【用户真实场景】搜索 → 下一页 → 长回复致回缩 → 第二次「下一页」 ----
# 三种子情形都必须让第二次「下一页」被执行。
def _s9_base():
    s = PollSim()
    h = [fr("Silence", "搜索 刘德华 夸克"), slf("🔵 第1/8页 结果…")]
    s.seed("Silence", h)
    # 用户发第一次「下一页」→ 必须执行
    assert s.poll_once("Silence", h + [fr("Silence", "下一页")]) == ["下一页"], \
        "场景9 第一次翻页应执行"
    return s, h


P2 = slf("🔵 第2/8页 结果…（很长的多行搜索结果）")
NX1 = fr("Silence", "下一页")     # 第一次翻页（已在 seen 中）
NX2 = fr("Silence", "下一页")     # 第二次翻页（内容完全相同）

# 9A：发送后回复已渲染，下轮窗口里回复仍可见 → 指纹定位到回复之后
s, h = _s9_base()
s.mark_chat_seen("Silence", h + [NX1, P2])     # 游标对齐到 4 条
s.poll_resync.pop("Silence", None)
got = s.poll_once("Silence", [NX1, P2, NX2])   # 回缩到 3 条
assert got == ["下一页"], f"场景9A 失败（第二次翻页应执行）: {got}"
print("场景9A 长回复可见：指纹定位到回复之后，第二次翻页执行 OK")

# 9B：发送后回复已渲染，但下轮回缩后回复不可见 → 整段重扫 + 最新一条豁免 seen
s, h = _s9_base()
s.mark_chat_seen("Silence", h + [NX1, P2])     # 游标对齐到 4 条
s.poll_resync.pop("Silence", None)
got = s.poll_once("Silence", [h[1], NX1, NX2])  # 回缩到 3 条，机器人回复不在窗口内
assert got == ["下一页"], f"场景9B 失败（第二次翻页应执行）: {got}"
print("场景9B 长回复不可见：整段重扫靠最新一条豁免，第二次翻页执行 OK")

# 9C：发送后即时读取时回复尚未渲染 → 游标停在旧值，下轮走正常增量
s, h = _s9_base()
s.mark_chat_seen("Silence", h + [NX1])         # 回复未渲染，游标对齐到 3 条
s.poll_resync.pop("Silence", None)
got = s.poll_once("Silence", [h[0], NX1, P2, NX2])   # 4 条 > 游标 3，正常增量
assert got == ["下一页"], f"场景9C 失败（第二次翻页应执行）: {got}"
print("场景9C 回复未即时渲染：游标停在旧值走正常增量，第二次翻页执行 OK")

# ---- 场景 10：尾部兜底（游标完全失准，末尾是全新的用户消息） ----
sim = PollSim()
hist = [fr("Silence", f"旧消息{i}") for i in range(30)]
sim.seed("Silence", hist)
sim.poll_once("Silence", hist)              # 第一轮：进入 tail_ready
# 窗口剧烈回缩且内容与历史毫无重叠，末尾是一条全新指令
got = sim.poll_once("Silence", [hist[3], fr("Silence", "搜索 周星驰 夸克")])
assert got == ["搜索 周星驰 夸克"], f"场景10 失败（尾部兜底应补处理末尾新指令）: {got}"
print("场景10 尾部兜底：游标失准时末尾全新用户消息仍被处理 OK")

# ---- 场景 11：尾部兜底不重放历史（已处理过的消息不重复执行） ----
sim = PollSim()
hist = [fr("Silence", "旧消息A"), fr("Silence", "旧消息B")]
sim.seed("Silence", hist)
got = sim.poll_once("Silence", hist)
assert got == [], f"场景11a 失败（已 seed 的历史不应重放）: {got}"
got = sim.poll_once("Silence", [fr("Silence", "旧消息B"), fr("Silence", "旧消息C")])
assert got == ["旧消息C"], f"场景11b 失败（只应处理新消息 C）: {got}"
print("场景11 尾部兜底只补新消息、不重放历史 OK")

print("\n全部回归场景通过 ✅")
