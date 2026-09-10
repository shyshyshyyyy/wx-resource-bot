# -*- coding: utf-8 -*-
"""回归测试：轮询「新消息定位」——序列前后缀对齐（单点，无内容豁免）。

设计原则（2026-09-10 重构）：
wxauto4 免费版没有跨轮稳定且唯一的消息 ID（msg.id 切 UI 会变、msg.hash 可能重复），
内容主键对「连发两条相同内容的消息」必然撞键。因此**唯一性由位置提供，不由内容提供**：
每轮保存窗口消息键序列，下一轮求「上轮后缀 == 本轮前缀」的最大重叠 t，
cur[t:] 就是新增消息。连发 N 次「下一页」天然是 N 条不同的消息。

这套逻辑取代了旧的四层补丁：条数游标、内容指纹游标、is_page 豁免、_is_last 豁免、
尾部兜底 —— 全部不再需要。seen 只保留一个作用：两轮窗口完全无法对齐（t=0）时防重放。

对照实验见 _t_dedup_compare.py：Claude 提的 occurrence 计数方案在回缩场景下
只处理了 5 次翻页中的 2 次（回缩后同内容消息的 occurrence 重新从 1 开始）。

运行：
    "D:/python/python.exe" _t_poll_regression.py
"""


class _Msg:
    def __init__(self, attr, sender, typ, content):
        self.attr = attr
        self.sender = sender
        self.type = typ
        self.content = content

    def __repr__(self):
        return f"<{self.attr}|{self.sender}|{self.content[:16]}>"


def msg_key(m, who=None):
    """与 wxbot_core._msg_key 一致：会话名 + 发送人 + 类型 + 内容（不含 attr）。"""
    return (who or '', getattr(m, 'sender', ''), getattr(m, 'type', ''),
            str(getattr(m, 'content', '')))


def seq_overlap(prev, cur):
    """最大 t 使 prev[-t:] == cur[:t]（与 wxbot_core._seq_overlap 一致）。"""
    k = len(prev)
    if k > len(cur):
        k = len(cur)
    for t in range(k, 0, -1):
        if prev[-t:] == cur[:t]:
            return t
    return 0


class PollSim:
    """忠实复刻 wxbot_core._poll_loop 的核心判定逻辑（纯内存，不依赖 wxauto）。"""

    def __init__(self, cmd="文件传输助手"):
        self.config_cmd = cmd
        self.poll_seen = {}       # who -> {key: ts}
        self.poll_prev_seq = {}   # who -> 上轮窗口的消息键序列
        self.handled = []         # (who, content) 处理记录
        self.aligned_log = []     # 每轮是否对齐成功

    # ---- 对应 wxbot_core._mark_chat_seen ----
    def mark_chat_seen(self, who, msgs):
        """机器人发送后调用：只标 attr=self，并把序列对齐到含本次回复的状态。"""
        seen = self.poll_seen.setdefault(who, {})
        for m in msgs:
            if getattr(m, 'attr', '') != 'self':
                continue
            seen[msg_key(m, who)] = 0.0
        if msgs:
            self.poll_prev_seq[who] = [msg_key(m, who) for m in msgs]

    def seed(self, who, msgs):
        seen = self.poll_seen.setdefault(who, {})
        for m in msgs:
            seen[msg_key(m, who)] = 0.0
        self.poll_prev_seq[who] = [msg_key(m, who) for m in msgs]

    def poll_once(self, who, msgs):
        """模拟 _poll_loop 单轮对单个 who 的处理。"""
        n = len(msgs)
        if n == 0:
            return []                       # 空读保护：不动序列
        seen = self.poll_seen.setdefault(who, {})
        cur_seq = [msg_key(m, who) for m in msgs]
        prev_seq = self.poll_prev_seq.get(who, [])
        t = seq_overlap(prev_seq, cur_seq)
        aligned = t > 0
        self.aligned_log.append(aligned)
        if aligned:
            new_idx = range(t, n)            # 位置判定，不查 seen
        else:
            new_idx = [i for i in range(n) if cur_seq[i] not in seen]   # seen 防重放
        out = []
        for idx in new_idx:
            m = msgs[idx]
            key = cur_seq[idx]
            content = str(getattr(m, 'content', '')).strip()
            attr = getattr(m, 'attr', '')
            typ = getattr(m, 'type', '')
            seen[key] = 0.0
            if attr == 'self' and who != self.config_cmd:
                continue
            if attr == 'system' or typ == 'time':
                continue
            if attr == 'self' and who == self.config_cmd:
                continue                     # 简化：recent_self 为空
            out.append(content)
            self.handled.append((who, content))
        self.poll_prev_seq[who] = cur_seq
        return out


def fr(sender, content, typ="text"):
    return _Msg('friend', sender, typ, content)


def slf(content, sender="机器人"):
    return _Msg('self', sender, 'text', content)


NX = lambda: fr("Silence", "下一页")     # noqa: E731 每次新对象，模拟新消息
R = lambda p: slf(f"第{p}/8页 结果（多行长消息）")   # noqa: E731


# ---- 场景 1：启动 seed 不重放历史 ----
sim = PollSim()
history = [fr("Silence", "你好"), slf("你好，我是机器人"), fr("Silence", "搜索 AI 迅雷")]
sim.seed("Silence", history)
assert sim.poll_once("Silence", history) == [], "场景1 失败：启动不应回放历史"
print("场景1 启动 seed 不重放历史 OK")

# ---- 场景 2：正常增量，新消息只处理一次 ----
sim = PollSim()
hist = [fr("Silence", "搜索 AI 迅雷")]
sim.seed("Silence", hist)
got = sim.poll_once("Silence", hist + [slf("结果..."), NX()])
assert got == ["下一页"], f"场景2 失败: {got}"
assert sim.poll_once("Silence", hist + [slf("结果..."), NX()]) == [], "场景2b 失败：不应重复处理"
print("场景2 正常增量处理新消息且不重复 OK")

# ---- 场景 3：连续翻页 2 次 ----
sim = PollSim()
hist = [fr("Silence", "搜索 AI 迅雷"), slf("结果...")]
sim.seed("Silence", hist)
assert sim.poll_once("Silence", hist + [NX()]) == ["下一页"], "场景3a 失败"
sim.mark_chat_seen("Silence", hist + [NX(), slf("结果2")])
assert sim.poll_once("Silence", hist + [NX(), slf("结果2"), NX()]) == ["下一页"], "场景3b 失败"
print("场景3 连续翻页两条都处理 OK")

# ---- 场景 4：回缩（顶部被截断）+ 新消息 ----
sim = PollSim()
hist = [fr("Silence", f"旧消息{i}") for i in range(20)]
sim.seed("Silence", hist)
shrunk = hist[5:] + [NX()]
got = sim.poll_once("Silence", shrunk)
assert got == ["下一页"], f"场景4 失败（回缩时应只处理新消息）: {got}"
print("场景4 回缩(顶部截断)时只处理新消息、不重放历史 OK")

# ---- 场景 5：回缩但无新消息，不重放 ----
sim = PollSim()
hist = [fr("Silence", f"旧消息{i}") for i in range(20)]
sim.seed("Silence", hist)
assert sim.poll_once("Silence", hist[8:]) == [], "场景5 失败：回缩无新消息不应重放"
print("场景5 回缩但无新消息不重放 OK")

# ---- 场景 6：两轮完全无重叠（切窗读到别的聊天）→ seen 防重放 ----
sim = PollSim()
hist = [fr("Silence", f"旧消息{i}") for i in range(10)]
sim.seed("Silence", hist)
only_new = [fr("Silence", "新消息A"), fr("Silence", "新消息B")]
got = sim.poll_once("Silence", only_new)
assert got == ["新消息A", "新消息B"], f"场景6 失败: {got}"
assert not sim.aligned_log[-1], "场景6 应记录为未对齐"
print("场景6 两轮无重叠时整段重扫 + seen 防重放 OK")

# ---- 场景 7：_mark_chat_seen 只标 self，不吞用户「下一页」 ----
sim = PollSim()
hist = [fr("Silence", "搜索 AI 迅雷")]
sim.seed("Silence", hist)
nx = NX()
sim.mark_chat_seen("Silence", [slf("结果..."), nx])
got = sim.poll_once("Silence", hist + [slf("结果..."), nx])
assert got == ["下一页"], f"场景7 失败（_mark_chat_seen 不应吞用户下一页）: {got}"
print("场景7 _mark_chat_seen 只标 self、不误吞用户消息 OK")

# ---- 场景 8：空读保护 ----
sim = PollSim()
hist = [fr("Silence", "搜索 AI 迅雷")]
sim.seed("Silence", hist)
assert sim.poll_once("Silence", []) == [], "场景8a 空读应返回空"
assert sim.poll_prev_seq["Silence"] == [msg_key(hist[0], "Silence")], "场景8a 失败：空读不应污染序列"
assert sim.poll_once("Silence", hist + [NX()]) == ["下一页"], "场景8b 失败：空读恢复后应处理新消息"
print("场景8 空读保护：切窗未就绪不污染序列，恢复后不漏消息 OK")

# ---- 场景 9：【用户真实场景】搜索 → 下一页 → 长回复致回缩 → 第二次「下一页」 ----
def _s9_base():
    s = PollSim()
    h = [fr("Silence", "搜索 刘德华 夸克"), slf("第1/8页 结果")]
    s.seed("Silence", h)
    assert s.poll_once("Silence", h + [NX()]) == ["下一页"], "场景9 第一次翻页应执行"
    return s, h


# 9A：回复在发送后已渲染，下轮仍可见
s, h = _s9_base()
s.mark_chat_seen("Silence", h + [NX(), R(2)])
got = s.poll_once("Silence", [NX(), R(2), NX()])
assert got == ["下一页"], f"场景9A 失败: {got}"
print("场景9A 长回复可见：第二次翻页执行 OK")

# 9B：回缩极狠，窗口只剩 2 条（虚拟列表只截顶部，机器人刚发的回复必然在末尾附近）
s, h = _s9_base()
s.mark_chat_seen("Silence", h + [NX(), R(2)])
got = s.poll_once("Silence", [R(2), NX()])
assert got == ["下一页"], f"场景9B 失败: {got}"
print("场景9B 回缩至只剩 2 条：第二次翻页仍执行 OK")

# 9C：发送后即时读取时回复尚未渲染（序列不含回复），下轮才补上
s, h = _s9_base()
s.mark_chat_seen("Silence", h + [NX()])          # 回复未渲染，序列仍以 NX1 结尾
got = s.poll_once("Silence", [NX(), R(2), NX()])  # 顶部截断，末尾是第二次翻页
assert got == ["下一页"], f"场景9C 失败: {got}"
print("场景9C 回复未即时渲染：第二次翻页仍执行 OK")

# ---- 场景 10：【关键】连续 5 次「下一页」+ 每次长回复都回缩 ----
# 用「完整消息流 + 只渲染最后 N 条」建模，贴近虚拟列表的真实行为。
# Claude 描述的「第一次成功、第二次靠豁免成功、第三次开始必然失效」必须不复现
# （_t_dedup_compare.py 里 occurrence 方案实测逐轮为 [1,1,0,0,0]）。
sim = PollSim()
stream = [fr("Silence", "搜索 刘德华 夸克"), R(1)]
sim.seed("Silence", stream[-3:])
got_all, per_round = [], []
for i in range(5):
    stream.append(NX())                     # 用户发「下一页」
    r = sim.poll_once("Silence", stream[-3:])   # 窗口只渲染最后 3 条（回缩）
    got_all.extend(r)
    per_round.append(len(r))
    stream.append(R(2 + i))                 # 机器人回复结果页
    sim.mark_chat_seen("Silence", stream[-3:])  # 发送后读取（同样只渲染 3 条）
assert got_all == ["下一页"] * 5, \
    f"场景10 失败（连续 5 次翻页应全部执行）: 逐轮={per_round} 实际={got_all}"
print(f"场景10 连续 5 次翻页 + 每次回缩，全部执行 OK（逐轮 {per_round}）")

# ---- 场景 11：一轮内用户连发两条不同指令，都要处理 ----
sim = PollSim()
hist = [fr("Silence", "旧1")]
sim.seed("Silence", hist)
got = sim.poll_once("Silence", hist + [fr("Silence", "搜索 A"), fr("Silence", "搜索 B")])
assert got == ["搜索 A", "搜索 B"], f"场景11 失败: {got}"
print("场景11 一轮内连发两条不同指令都处理 OK")

# ---- 场景 12：中间插入了机器人消息（两轮之间发送但序列未重对齐） ----
sim = PollSim()
hist = [fr("Silence", "旧1"), fr("Silence", "旧2")]
sim.seed("Silence", hist)
# 机器人主动推送一条（未走 mark_chat_seen 重对齐），然后用户发指令
got = sim.poll_once("Silence", hist + [slf("定时推送"), NX()])
assert got == ["下一页"], f"场景12 失败（中间插入消息不应影响定位）: {got}"
print("场景12 两轮间插入机器人消息仍能正确定位新指令 OK")

# ---- 场景 13：系统/时间消息不触发处理 ----
sim = PollSim()
hist = [fr("Silence", "旧1")]
sim.seed("Silence", hist)
got = sim.poll_once("Silence", hist + [_Msg('system', 'system', 'other', 'xxx 撤回了一条消息'),
                                       _Msg('time', 'time', 'time', '2026-09-10 18:00:00')])
assert got == [], f"场景13 失败（系统/时间消息不应触发）: {got}"
print("场景13 系统/时间消息不触发处理 OK")

print("\n全部回归场景通过 ✅")
